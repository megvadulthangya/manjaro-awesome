#!/usr/bin/env python3
"""
Unified Manjaro Package Builder - With proper repository configuration
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass
from datetime import datetime
import requests
from enum import Enum

# Import configuration
from config import (
    REPO_DB_NAME, OUTPUT_DIR, BUILD_TRACKING_DIR,
    SSH_REPO_URL, MAKEPKG_TIMEOUT, SPECIAL_DEPENDENCIES
)

# Import package lists
from packages import LOCAL_PACKAGES, AUR_PACKAGES

# Configure logging with colors like bash scripts
class ColorFormatter(logging.Formatter):
    COLORS = {
        'INFO': '\033[34m',      # Blue
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[41m',  # Red background
        'DEBUG': '\033[35m',     # Purple
        'SUCCESS': '\033[32m',   # Green
    }
    
    def format(self, record):
        # Add custom level for success messages
        if hasattr(record, 'success'):
            record.levelname = 'SUCCESS'
        
        # Colorize the level name
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}[{record.levelname}]\033[0m"
        
        return super().format(record)

logger = logging.getLogger(__name__)
handler = logging.StreamHandler()
handler.setFormatter(ColorFormatter('[%(levelname)s] %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class PackageType(Enum):
    LOCAL = "local"
    AUR = "aur"

@dataclass
class Package:
    name: str
    pkg_type: PackageType
    version: str = ""
    pkgrel: str = "1"
    source_dir: Path = None
    built_files: List[Path] = None
    
    def __post_init__(self):
        self.built_files = []
    
    @property
    def full_version(self) -> str:
        return f"{self.version}-{self.pkgrel}"

class PackageBuilder:
    def __init__(self):
        self.repo_root = Path(os.getcwd())
        self.output_dir = self.repo_root / OUTPUT_DIR
        self.build_tracking_dir = self.repo_root / BUILD_TRACKING_DIR
        
        # Load configuration from environment
        self._load_environment_config()
        
        # Package lists
        self.local_packages = LOCAL_PACKAGES
        self.aur_packages = AUR_PACKAGES
        
        # Generate custom repository configuration
        self.custom_repo_config = self._generate_repo_config()
        
        # Setup directories
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # State
        self.remote_files = []
        self.packages_to_clean = set()
        self.built_packages = []
        self.skipped_packages = []
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "bytes_uploaded": 0
        }
    
    def _load_environment_config(self):
        """Load configuration from environment variables."""
        # REQUIRED - fail if missing
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        
        if not all([self.vps_user, self.vps_host, self.ssh_key]):
            logger.error("Missing required environment variables: VPS_USER, VPS_HOST, VPS_SSH_KEY")
            logger.error("Please set these in your GitHub repository secrets")
            sys.exit(1)
        
        # REQUIRED for repository configuration
        self.repo_server_url = os.getenv('REPO_SERVER_URL')
        if not self.repo_server_url:
            logger.error("REPO_SERVER_URL is required for pacman repository configuration!")
            logger.error("This should be the public URL of your repository (e.g., https://repo.example.com)")
            sys.exit(1)
        
        # REQUIRED but with fallback
        self.remote_dir = os.getenv('REMOTE_DIR', '/var/www/repo')
        
        # OPTIONAL with defaults
        self.repo_name = os.getenv('REPO_NAME', 'manjaro-awesome')
        
        logger.info("Configuration loaded:")
        logger.info(f"  SSH: {self.vps_user}@{self.vps_host}")
        logger.info(f"  Remote directory: {self.remote_dir}")
        logger.info(f"  Repository: {self.repo_name} -> {self.repo_server_url}")
    
    def _generate_repo_config(self) -> str:
        """Generate pacman repository configuration."""
        return f"""[{self.repo_name}]
Server = {self.repo_server_url}
SigLevel = Optional TrustAll
"""
    
    def run_command(self, cmd: List[str], cwd: Path = None, 
                   capture_output: bool = True, check: bool = True,
                   timeout: int = None) -> subprocess.CompletedProcess:
        """Run a shell command with logging."""
        logger.debug(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                check=check,
                timeout=timeout
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}")
            if e.stderr:
                # Show only first 500 chars of error
                error_msg = e.stderr[:500] + "..." if len(e.stderr) > 500 else e.stderr
                logger.error(f"Error: {error_msg}")
            raise
        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timeout after {timeout}s: {' '.join(cmd)}")
            raise
    
    def setup_environment(self):
        """Setup the build environment including pacman.conf."""
        logger.info("Setting up environment...")
        
        # 1. Configure pacman.conf with our repository
        self._configure_pacman()
        
        # 2. Configure SSH
        self._setup_ssh()
        
        # 3. Git configuration
        self.run_command(["git", "config", "--global", "user.name", "GitHub Action Bot"])
        self.run_command(["git", "config", "--global", "user.email", "action@github.com"])
        
        # 4. Install yay if needed
        self._install_yay_if_needed()
        
        logger.info("✓ Environment setup complete")
    
    def _configure_pacman(self):
        """Inject custom repository into pacman.conf."""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found!")
            return
        
        # Backup original
        backup_path = pacman_conf.with_suffix('.conf.backup')
        if not backup_path.exists():
            shutil.copy2(pacman_conf, backup_path)
        
        # Read current config
        content = pacman_conf.read_text()
        
        # Check if our repo is already configured
        repo_section = f"[{self.repo_name}]"
        if repo_section in content:
            logger.info(f"Repository '{self.repo_name}' already configured in pacman.conf")
            
            # Update server URL if different
            if self.repo_server_url not in content:
                logger.warning("Repository server URL might be different in pacman.conf")
            return
        
        # Find where to insert (before [community] or at end)
        lines = content.split('\n')
        insert_pos = len(lines)
        
        for i, line in enumerate(lines):
            if line.strip().startswith("[community]"):
                insert_pos = i
                break
            elif line.strip().startswith("[extra]"):
                insert_pos = i + 1
        
        # Insert our repo config with timestamp comment
        timestamp = datetime.now().strftime("%Y-%m-%d")
        repo_config = f"\n# Custom repository '{self.repo_name}' added by builder.py on {timestamp}\n"
        repo_config += self.custom_repo_config
        
        lines.insert(insert_pos, repo_config)
        
        # Write back
        pacman_conf.write_text('\n'.join(lines))
        logger.info(f"✓ Added repository '{self.repo_name}' to pacman.conf")
        
        # Update pacman database
        try:
            logger.info("Updating pacman database...")
            self.run_command(["pacman", "-Sy", "--noconfirm"])
            logger.info("✓ Pacman database synchronized")
        except Exception as e:
            logger.error(f"Failed to sync pacman database: {e}")
    
    def _setup_ssh(self):
        """Setup SSH for remote access."""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(parents=True, exist_ok=True)
        
        # Write SSH key
        key_path = ssh_dir / "id_ed25519"
        try:
            # Try to decode as base64
            import base64
            key_data = base64.b64decode(self.ssh_key)
            key_path.write_bytes(key_data)
        except:
            # If not base64, write as text
            key_path.write_text(self.ssh_key)
        
        key_path.chmod(0o600)
        
        # Add known hosts
        known_hosts = ssh_dir / "known_hosts"
        hosts = [self.vps_host, "github.com"]
        
        for host in hosts:
            result = self.run_command(
                ["ssh-keyscan", "-H", host],
                capture_output=True,
                check=False
            )
            if result.stdout:
                known_hosts.write_text(result.stdout)
                logger.debug(f"Added SSH key for {host}")
        
        # Set ownership
        self.run_command(["chown", "-R", "builder:builder", str(ssh_dir)])
        logger.info("✓ SSH setup complete")
    
    def _install_yay_if_needed(self):
        """Install yay only if not present."""
        try:
            self.run_command(["which", "yay"], check=False)
            logger.info("yay already installed")
            return
        except:
            pass
        
        logger.info("Installing yay AUR helper...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            self.run_command(
                ["git", "clone", "https://aur.archlinux.org/yay.git", f"{tmpdir}/yay"]
            )
            
            self.run_command(
                ["makepkg", "-si", "--noconfirm", "--clean"],
                cwd=f"{tmpdir}/yay"
            )
        
        # Configure yay for automation
        try:
            yay_config_cmds = [
                ["yay", "-Y", "--gendb", "--noconfirm"],
                ["yay", "-Y", "--devel", "--save", "--noconfirm"],
                ["yay", "-Y", "--nodiffmenu", "--save", "--noconfirm"],
                ["yay", "-Y", "--noeditmenu", "--save", "--noconfirm"],
                ["yay", "-Y", "--removemake", "--save", "--noconfirm"],
            ]
            
            for cmd in yay_config_cmds:
                self.run_command(cmd, check=False)
            
            logger.info("✓ yay installed and configured")
        except Exception as e:
            logger.warning(f"yay configuration failed: {e}")
    
    def fetch_remote_packages(self):
        """Fetch list of packages from remote server."""
        logger.info("Fetching remote package list...")
        
        ssh_cmd = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{self.vps_user}@{self.vps_host}",
            f"find {self.remote_dir} -name '*.pkg.tar.*' -type f -printf '%f\\n' 2>/dev/null | sort"
        ]
        
        try:
            result = self.run_command(ssh_cmd, capture_output=True, timeout=30)
            self.remote_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            logger.info(f"✓ Found {len(self.remote_files)} packages on server")
            
            # Also download the database file for repo-add
            db_source = f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/{self.repo_name}.db.tar.gz"
            db_dest = self.output_dir / f"{self.repo_name}.db.tar.gz"
            
            scp_cmd = ["scp", db_source, str(db_dest)]
            self.run_command(scp_cmd, check=False)
            
        except Exception as e:
            logger.warning(f"Could not fetch remote package list: {e}")
            self.remote_files = []
    
    def is_package_on_server(self, package_name: str, version: str = None) -> bool:
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        if version:
            pattern = f"^{package_name}-{version}-"
        else:
            pattern = f"^{package_name}-"
        
        return any(re.match(pattern, f) for f in self.remote_files)
    
    def get_package_hash(self, pkg_dir: Path) -> str:
        """Calculate hash of package for change detection."""
        if not pkg_dir.exists():
            return "no_dir"
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if pkgbuild.exists():
            content = pkgbuild.read_text()
            return hashlib.sha256(content.encode()).hexdigest()[:16]
        
        return "no_hash"
    
    def build_package(self, package_name: str, pkg_type: PackageType) -> bool:
        """Build a single package."""
        logger.info(f"Processing {package_name} ({pkg_type.value})")
        
        # Get package directory
        if pkg_type == PackageType.AUR:
            pkg_dir = self._clone_aur_package(package_name)
            if not pkg_dir:
                return False
        else:
            pkg_dir = self.repo_root / package_name
            if not pkg_dir.exists():
                logger.error(f"Package directory not found: {package_name}")
                return False
        
        # Extract version info
        pkgver, pkgrel = self._extract_package_info(pkg_dir)
        full_version = f"{pkgver}-{pkgrel}"
        
        # Skip if already on server
        if self.is_package_on_server(package_name, full_version):
            logger.info(f"✓ {package_name} {full_version} already on server - skipping")
            self.skipped_packages.append(package_name)
            return False
        
        # Special handling for qt5-styleplugins if gtk2 is built
        if package_name == "qt5-styleplugins" and self._is_gtk2_built():
            logger.info("Special handling: qt5-styleplugins - removing gtk2 dependency")
            self._remove_gtk2_dependency(pkg_dir)
        
        try:
            # Download sources
            logger.debug("Downloading sources...")
            self.run_command(["makepkg", "-od", "--noconfirm"], cwd=pkg_dir)
            
            # Install dependencies (for AUR packages)
            if pkg_type == PackageType.AUR:
                self._install_aur_dependencies(pkg_dir)
            
            # Build with appropriate timeout
            timeout = MAKEPKG_TIMEOUT.get("default", 3600)
            if any(x in package_name for x in ["gtk", "qt", "chromium"]):
                timeout = MAKEPKG_TIMEOUT.get("large_packages", 7200)
            
            logger.info(f"Building {package_name} (timeout: {timeout}s)...")
            self.run_command(
                ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"],
                cwd=pkg_dir,
                capture_output=False,
                timeout=timeout
            )
            
            # Move built packages to output directory
            moved_files = []
            for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                dest = self.output_dir / pkg_file.name
                shutil.move(pkg_file, dest)
                moved_files.append(pkg_file.name)
                self.packages_to_clean.add(package_name)
            
            if moved_files:
                logger.info(f"✓ Built {package_name}: {', '.join(moved_files)}")
                
                # Update git for local packages
                if pkg_type == PackageType.LOCAL:
                    self._update_git_repository(package_name, pkg_dir, full_version)
                
                # Cleanup AUR build directory
                if pkg_type == PackageType.AUR:
                    aur_dir = self.repo_root / "build_aur" / package_name
                    if aur_dir.exists():
                        shutil.rmtree(aur_dir, ignore_errors=True)
                
                return True
            else:
                logger.error(f"No package files created for {package_name}")
                return False
            
        except Exception as e:
            logger.error(f"✗ Failed to build {package_name}: {e}")
            
            # Cleanup on failure
            if pkg_type == PackageType.AUR:
                aur_dir = self.repo_root / "build_aur" / package_name
                if aur_dir.exists():
                    shutil.rmtree(aur_dir, ignore_errors=True)
            
            return False
    
    def _clone_aur_package(self, package_name: str) -> Optional[Path]:
        """Clone AUR package."""
        aur_dir = self.repo_root / "build_aur"
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / package_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        
        try:
            self.run_command([
                "git", "clone", 
                f"https://aur.archlinux.org/{package_name}.git",
                str(pkg_dir)
            ])
            return pkg_dir
        except Exception as e:
            logger.error(f"Failed to clone AUR package {package_name}: {e}")
            return None
    
    def _extract_package_info(self, pkg_dir: Path) -> Tuple[str, str]:
        """Extract pkgver and pkgrel from PKGBUILD."""
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            return "unknown", "1"
        
        content = pkgbuild.read_text()
        
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        pkgver = pkgver_match.group(1) if pkgver_match else "unknown"
        pkgrel = pkgrel_match.group(1) if pkgrel_match else "1"
        
        return pkgver, pkgrel
    
    def _is_gtk2_built(self) -> bool:
        """Check if gtk2 has been built in this session."""
        return "gtk2" in [pkg.name for pkg in self.built_packages]
    
    def _remove_gtk2_dependency(self, pkg_dir: Path):
        """Remove gtk2 dependency from PKGBUILD."""
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            return
        
        content = pkgbuild.read_text()
        
        # Remove gtk2 from depends arrays
        content = re.sub(r'\bgtk2\b', '', content)
        content = re.sub(r'["\']gtk2["\']', '', content)
        
        # Clean up empty arrays and extra commas
        content = re.sub(r'\([,\s]+\)', '()', content)
        content = re.sub(r',\s*,', ',', content)
        
        pkgbuild.write_text(content)
        logger.debug("Removed gtk2 dependency from PKGBUILD")
    
    def _install_aur_dependencies(self, pkg_dir: Path):
        """Install dependencies for AUR package."""
        # Generate .SRCINFO if it doesn't exist
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            self.run_command(["makepkg", "--printsrcinfo"], cwd=pkg_dir, check=False)
        
        if srcinfo.exists():
            content = srcinfo.read_text()
            
            # Extract dependencies
            deps = []
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith("depends =") or line.startswith("makedepends ="):
                    dep = line.split('=', 1)[1].strip()
                    if dep and dep not in ["gtk2"]:  # Skip packages we build ourselves
                        deps.append(dep)
            
            if deps:
                logger.info(f"Installing {len(deps)} dependencies...")
                
                # Separate AUR and official packages
                official_deps = []
                aur_deps = []
                
                for dep in deps:
                    # Clean version specifiers
                    dep_clean = re.sub(r'[<=>].*', '', dep).strip()
                    
                    # Check if it's an official package
                    try:
                        self.run_command(["pacman", "-Si", dep_clean], capture_output=True, check=False)
                        official_deps.append(dep_clean)
                    except:
                        aur_deps.append(dep_clean)
                
                # Install official packages first
                if official_deps:
                    logger.debug(f"Official deps: {official_deps}")
                    for dep in official_deps:
                        try:
                            self.run_command(["pacman", "-S", "--needed", "--noconfirm", dep], check=False)
                        except:
                            logger.warning(f"Failed to install {dep}")
                
                # Install AUR packages
                if aur_deps:
                    logger.debug(f"AUR deps: {aur_deps}")
                    for dep in aur_deps:
                        try:
                            self.run_command(["yay", "-S", "--asdeps", "--needed", "--noconfirm", dep], check=False)
                        except:
                            logger.warning(f"Failed to install AUR dependency {dep}")
    
    def _update_git_repository(self, package_name: str, pkg_dir: Path, version: str):
        """Update git repository with new package version."""
        try:
            # Generate .SRCINFO
            self.run_command(["makepkg", "--printsrcinfo"], cwd=pkg_dir)
            
            # Add changes
            self.run_command(["git", "add", f"{package_name}/PKGBUILD", f"{package_name}/.SRCINFO"])
            
            # Check if there are changes
            result = self.run_command(["git", "status", "--porcelain"], capture_output=True)
            if not result.stdout.strip():
                logger.debug("No changes to commit")
                return
            
            # Commit
            commit_msg = f"Auto-update: {package_name} to {version} [skip ci]"
            self.run_command(["git", "commit", "-m", commit_msg])
            
            # Push
            self.run_command(["git", "push"])
            logger.info(f"✓ Git repository updated for {package_name}")
            
        except Exception as e:
            logger.warning(f"Could not update git: {e}")
    
    def update_database(self):
        """Update repository database."""
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not pkg_files:
            logger.info("No packages to add to database")
            return False
        
        logger.info(f"Updating database with {len(pkg_files)} packages...")
        
        db_file = self.output_dir / f"{self.repo_name}.db.tar.gz"
        
        # Check if database exists, if not create new
        if db_file.exists():
            cmd = ["repo-add", "-R", str(db_file)]
        else:
            cmd = ["repo-add", str(db_file)]
        
        cmd.extend([str(p) for p in pkg_files])
        
        try:
            self.run_command(cmd, cwd=self.output_dir)
            logger.info("✓ Database updated")
            return True
        except Exception as e:
            logger.error(f"Failed to update database: {e}")
            return False
    
    def upload_packages(self):
        """Upload packages to remote server."""
        files_to_upload = list(self.output_dir.glob("*"))
        if not files_to_upload:
            logger.warning("No files to upload")
            return False
        
        logger.info(f"Uploading {len(files_to_upload)} files to {self.vps_host}:{self.remote_dir}")
        
        try:
            # Create remote directory if it doesn't exist
            ssh_cmd = [
                "ssh", f"{self.vps_user}@{self.vps_host}",
                f"mkdir -p {self.remote_dir}"
            ]
            self.run_command(ssh_cmd, check=False)
            
            # Upload files
            scp_cmd = ["scp", "-B"] + [str(f) for f in files_to_upload] + \
                     [f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/"]
            
            self.run_command(scp_cmd)
            
            # Calculate upload size
            total_size = sum(f.stat().st_size for f in files_to_upload)
            self.stats["bytes_uploaded"] = total_size
            
            logger.info(f"✓ Upload successful ({total_size/1024/1024:.1f} MB)")
            return True
            
        except Exception as e:
            logger.error(f"✗ Upload failed: {e}")
            return False
    
    def cleanup_old_packages(self):
        """Remove old package versions from server (keep latest 2)."""
        if not self.packages_to_clean:
            logger.info("No packages to clean up")
            return
        
        logger.info(f"Cleaning up old versions of {len(self.packages_to_clean)} packages...")
        
        cleaned_count = 0
        for package in self.packages_to_clean:
            cmd = [
                "ssh", f"{self.vps_user}@{self.vps_host}",
                f"cd {self.remote_dir} && "
                f"ls -t {package}-*.pkg.tar.zst 2>/dev/null | tail -n +3 | xargs -r rm -f 2>/dev/null || true"
            ]
            
            try:
                self.run_command(cmd, check=False)
                cleaned_count += 1
            except Exception as e:
                logger.warning(f"Failed to cleanup {package}: {e}")
        
        if cleaned_count > 0:
            logger.info(f"✓ Cleaned up old versions for {cleaned_count} packages")
    
    def run(self):
        """Main execution."""
        print("\n" + "="*60)
        print("MANJARO PACKAGE BUILDER")
        print("="*60)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Repository: {self.repo_name}")
        print(f"Server: {self.repo_server_url}")
        print("="*60 + "\n")
        
        try:
            # Setup
            self.setup_environment()
            self.fetch_remote_packages()
            
            # Build AUR packages
            print("\n" + "-"*40)
            print(f"BUILDING {len(self.aur_packages)} AUR PACKAGES")
            print("-"*40)
            
            for pkg in self.aur_packages:
                if self.build_package(pkg, PackageType.AUR):
                    self.stats["aur_success"] += 1
            
            # Build local packages
            print("\n" + "-"*40)
            print(f"BUILDING {len(self.local_packages)} LOCAL PACKAGES")
            print("-"*40)
            
            for pkg in self.local_packages:
                if self.build_package(pkg, PackageType.LOCAL):
                    self.stats["local_success"] += 1
            
            # Finalize if we built anything
            total_built = self.stats["aur_success"] + self.stats["local_success"]
            
            if total_built > 0:
                print("\n" + "-"*40)
                print("FINALIZING BUILD")
                print("-"*40)
                
                if self.update_database():
                    if self.upload_packages():
                        self.cleanup_old_packages()
                    else:
                        print("\n⚠️  WARNING: Upload failed!")
                else:
                    print("\n⚠️  WARNING: Database update failed!")
            else:
                print("\n" + "="*60)
                print("✅ ALL PACKAGES ARE UP TO DATE!")
                print(f"Skipped: {len(self.skipped_packages)} packages")
                print("="*60)
                return 0
            
            # Summary
            elapsed = time.time() - self.stats["start_time"]
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            print("\n" + "="*60)
            print("BUILD SUMMARY")
            print("="*60)
            print(f"Duration: {minutes}m {seconds}s")
            print(f"AUR packages:    {self.stats['aur_success']}/{len(self.aur_packages)}")
            print(f"Local packages:  {self.stats['local_success']}/{len(self.local_packages)}")
            print(f"Total built:     {total_built}")
            print(f"Upload size:     {self.stats['bytes_uploaded']/1024/1024:.1f} MB")
            print(f"Skipped:         {len(self.skipped_packages)}")
            
            if total_built > 0:
                print("\n✅ BUILD COMPLETED SUCCESSFULLY!")
                print(f"Repository updated: {self.repo_server_url}")
            else:
                print("\n⚠️  No packages were built")
            
            print("="*60)
            return 0
            
        except Exception as e:
            print(f"\n❌ BUILD FAILED: {e}")
            import traceback
            print(traceback.format_exc())
            return 1

def main():
    builder = PackageBuilder()
    return builder.run()

if __name__ == "__main__":
    sys.exit(main())