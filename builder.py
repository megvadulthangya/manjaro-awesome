#!/usr/bin/env python3
"""
Unified Manjaro Package Builder - Simplified version
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='\033[34m[%(asctime)s]\033[0m %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('builder.log')
    ]
)
logger = logging.getLogger(__name__)

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
        
        # Load configuration from environment - SIMPLIFIED
        self._load_environment_config()
        
        # Package lists
        self.local_packages = LOCAL_PACKAGES
        self.aur_packages = AUR_PACKAGES
        
        # Setup directories
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # State
        self.remote_files = []
        self.packages_to_clean = set()
        self.built_packages = []
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "bytes_uploaded": 0
        }
    
    def _load_environment_config(self):
        """Load configuration from environment variables - SIMPLIFIED."""
        # REQUIRED - fail if missing
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        
        if not all([self.vps_user, self.vps_host, self.ssh_key]):
            logger.error("Missing required environment variables: VPS_USER, VPS_HOST, VPS_SSH_KEY")
            sys.exit(1)
        
        # REQUIRED but with fallback warning
        self.remote_dir = os.getenv('REMOTE_DIR')
        if not self.remote_dir:
            logger.warning("REMOTE_DIR not set, using default: /var/www/repo")
            self.remote_dir = "/var/www/repo"
        
        # OPTIONAL
        self.repo_server_url = os.getenv('REPO_SERVER_URL', 'https://your-repo.example.com')
        
        logger.info(f"Configuration: {self.vps_user}@{self.vps_host}:{self.remote_dir}")
    
    def run_command(self, cmd: List[str], cwd: Path = None, 
                   capture_output: bool = True, check: bool = True) -> subprocess.CompletedProcess:
        """Run a shell command with logging."""
        logger.debug(f"Running: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {' '.join(cmd)}")
            if e.stderr:
                logger.error(f"Error: {e.stderr[:200]}")
            raise
    
    def setup_environment(self):
        """Setup the build environment."""
        logger.info("Setting up environment...")
        
        # Configure SSH
        self._setup_ssh()
        
        # Git configuration
        self.run_command(["git", "config", "--global", "user.name", "GitHub Action Bot"])
        self.run_command(["git", "config", "--global", "user.email", "action@github.com"])
        
        # Install yay if needed
        self._install_yay_if_needed()
        
        logger.info("Environment ready")
    
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
        
        # Set ownership
        self.run_command(["chown", "-R", "builder:builder", str(ssh_dir)])
    
    def _install_yay_if_needed(self):
        """Install yay only if not present."""
        try:
            self.run_command(["which", "yay"], check=False)
            logger.info("yay already installed")
            return
        except:
            pass
        
        logger.info("Installing yay...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            self.run_command(
                ["git", "clone", "https://aur.archlinux.org/yay.git", f"{tmpdir}/yay"]
            )
            
            self.run_command(
                ["makepkg", "-si", "--noconfirm"],
                cwd=f"{tmpdir}/yay"
            )
    
    def fetch_remote_packages(self):
        """Fetch list of packages from remote server."""
        logger.info("Fetching remote package list...")
        
        ssh_cmd = [
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{self.vps_user}@{self.vps_host}",
            f"find {self.remote_dir} -name '*.pkg.tar.*' -printf '%f\\n' 2>/dev/null || true"
        ]
        
        try:
            result = self.run_command(ssh_cmd, capture_output=True)
            self.remote_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            logger.info(f"Found {len(self.remote_files)} packages on server")
        except:
            self.remote_files = []
            logger.warning("Could not fetch remote package list")
    
    def is_package_on_server(self, package_name: str, version: str = None) -> bool:
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        if version:
            pattern = f"^{package_name}-{version}-"
        else:
            pattern = f"^{package_name}-"
        
        return any(re.match(pattern, f) for f in self.remote_files)
    
    def build_package(self, package_name: str, pkg_type: PackageType) -> bool:
        """Build a single package."""
        logger.info(f"Building {package_name} ({pkg_type.value})")
        
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
        
        # Extract version
        pkgver, pkgrel = self._extract_package_info(pkg_dir)
        full_version = f"{pkgver}-{pkgrel}"
        
        # Skip if already on server
        if self.is_package_on_server(package_name, full_version):
            logger.info(f"✓ {package_name} {full_version} already on server")
            return False
        
        # Build the package
        try:
            # Download sources
            self.run_command(["makepkg", "-od", "--noconfirm"], cwd=pkg_dir)
            
            # Install dependencies (for AUR packages)
            if pkg_type == PackageType.AUR:
                self._install_aur_dependencies(pkg_dir)
            
            # Build
            result = self.run_command(
                ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"],
                cwd=pkg_dir,
                capture_output=False
            )
            
            # Move built packages
            for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                dest = self.output_dir / pkg_file.name
                shutil.move(pkg_file, dest)
                logger.info(f"✓ Built: {pkg_file.name}")
                self.packages_to_clean.add(package_name)
            
            # Update git for local packages
            if pkg_type == PackageType.LOCAL:
                self._update_git_repository(package_name, pkg_dir, full_version)
            
            return True
            
        except Exception as e:
            logger.error(f"✗ Failed to build {package_name}: {e}")
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
        except:
            logger.error(f"Failed to clone AUR package: {package_name}")
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
    
    def _install_aur_dependencies(self, pkg_dir: Path):
        """Install dependencies for AUR package."""
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            return
        
        # Generate .SRCINFO if needed
        self.run_command(["makepkg", "--printsrcinfo"], cwd=pkg_dir, check=False)
        
        if srcinfo.exists():
            content = srcinfo.read_text()
            # Extract dependencies
            deps = []
            for line in content.split('\n'):
                if line.strip().startswith("depends =") or line.strip().startswith("makedepends ="):
                    dep = line.split('=', 1)[1].strip()
                    if dep and dep not in ["gtk2"]:  # Skip packages we build ourselves
                        deps.append(dep)
            
            if deps:
                logger.info(f"Installing dependencies: {', '.join(deps)}")
                for dep in deps:
                    self.run_command(
                        ["yay", "-S", "--asdeps", "--noconfirm", dep],
                        check=False
                    )
    
    def _update_git_repository(self, package_name: str, pkg_dir: Path, version: str):
        """Update git repository with new package version."""
        logger.info(f"Updating git repository for {package_name}...")
        
        # For simplicity, we'll update the local repo and push
        try:
            # Generate .SRCINFO
            self.run_command(["makepkg", "--printsrcinfo"], cwd=pkg_dir)
            
            # Add changes
            self.run_command(["git", "add", f"{package_name}/PKGBUILD", f"{package_name}/.SRCINFO"])
            
            # Commit
            self.run_command([
                "git", "commit", "-m", 
                f"Auto-update: {package_name} to {version} [skip ci]"
            ])
            
            # Push
            self.run_command(["git", "push"])
            logger.info(f"✓ Git repository updated")
            
        except Exception as e:
            logger.warning(f"Could not update git: {e}")
    
    def update_database(self):
        """Update repository database."""
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not pkg_files:
            return
        
        logger.info(f"Updating database with {len(pkg_files)} packages")
        
        db_file = self.output_dir / f"{REPO_DB_NAME}.db.tar.gz"
        cmd = ["repo-add", str(db_file)] + [str(p) for p in pkg_files]
        
        self.run_command(cmd)
    
    def upload_packages(self):
        """Upload packages to remote server."""
        files_to_upload = list(self.output_dir.glob("*"))
        if not files_to_upload:
            return True
        
        logger.info(f"Uploading {len(files_to_upload)} files...")
        
        try:
            # Create remote directory if it doesn't exist
            ssh_cmd = [
                "ssh", f"{self.vps_user}@{self.vps_host}",
                f"mkdir -p {self.remote_dir}"
            ]
            self.run_command(ssh_cmd, check=False)
            
            # Upload files
            scp_cmd = ["scp"] + [str(f) for f in files_to_upload] + \
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
        """Remove old package versions from server (keep n-1)."""
        if not self.packages_to_clean:
            return
        
        logger.info("Cleaning up old package versions...")
        
        for package in self.packages_to_clean:
            cmd = [
                "ssh", f"{self.vps_user}@{self.vps_host}",
                f"cd {self.remote_dir} && "
                f"ls -t {package}-*.pkg.tar.zst 2>/dev/null | tail -n +3 | xargs -r rm -f"
            ]
            self.run_command(cmd, check=False)
    
    def run(self):
        """Main execution."""
        logger.info("=" * 60)
        logger.info("Manjaro Package Builder")
        logger.info("=" * 60)
        
        try:
            # Setup
            self.setup_environment()
            self.fetch_remote_packages()
            
            # Build AUR packages
            logger.info(f"\nBuilding {len(self.aur_packages)} AUR packages...")
            for pkg in self.aur_packages:
                if self.build_package(pkg, PackageType.AUR):
                    self.stats["aur_success"] += 1
            
            # Build local packages
            logger.info(f"\nBuilding {len(self.local_packages)} local packages...")
            for pkg in self.local_packages:
                if self.build_package(pkg, PackageType.LOCAL):
                    self.stats["local_success"] += 1
            
            # Finalize if we built anything
            if self.stats["aur_success"] > 0 or self.stats["local_success"] > 0:
                self.update_database()
                if self.upload_packages():
                    self.cleanup_old_packages()
            else:
                logger.info("\n✓ All packages are up to date!")
            
            # Summary
            elapsed = time.time() - self.stats["start_time"]
            logger.info("=" * 60)
            logger.info("Build Summary:")
            logger.info(f"  AUR:   {self.stats['aur_success']}/{len(self.aur_packages)}")
            logger.info(f"  Local: {self.stats['local_success']}/{len(self.local_packages)}")
            logger.info(f"  Time:  {elapsed:.1f}s")
            logger.info("=" * 60)
            
            return 0
            
        except Exception as e:
            logger.error(f"\n✗ Build failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 1

def main():
    builder = PackageBuilder()
    return builder.run()

if __name__ == "__main__":
    sys.exit(main())