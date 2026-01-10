#!/usr/bin/env python3
"""
Manjaro Package Builder - Arch Linux compatible version
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
from typing import List, Tuple, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('builder.log')
    ]
)
logger = logging.getLogger(__name__)

# ANSI color codes for pretty output
COLORS = {
    'INFO': '\033[34m',      # Blue
    'SUCCESS': '\033[32m',   # Green
    'WARNING': '\033[33m',   # Yellow
    'ERROR': '\033[31m',     # Red
    'RESET': '\033[0m',      # Reset
}

def colorize(level, message):
    """Add color to log messages based on level."""
    color = COLORS.get(level, COLORS['RESET'])
    return f"{color}{message}{COLORS['RESET']}"

class PackageBuilder:
    def __init__(self):
        self.repo_root = Path(os.getcwd())
        self.output_dir = self.repo_root / "built_packages"
        self.build_tracking_dir = self.repo_root / ".buildtracking"
        
        # Load configuration
        self._load_config()
        
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
        }
        
        # Package lists
        self.local_packages = [
            "gghelper", "gtk2", "awesome-freedesktop-git", "lain-git",
            "awesome-rofi", "nordic-backgrounds", "awesome-copycats-manjaro",
            "i3lock-fancy-git", "ttf-font-awesome-5", "nvidia-driver-assistant",
            "grayjay-bin"
        ]
        
        self.aur_packages = [
            "libinput-gestures", "qt5-styleplugins", "urxvt-resize-font-git",
            "i3lock-color", "raw-thumbnailer", "gsconnect", "awesome-git",
            "tilix-git", "tamzen-font", "betterlockscreen", "nordic-theme",
            "nordic-darker-theme", "geany-nord-theme", "nordzy-icon-theme",
            "oh-my-posh-bin", "fish-done", "find-the-command", "p7zip-gui",
            "qownnotes", "xorg-font-utils", "xnviewmp", "simplescreenrecorder",
            "gtkhash-thunar", "a4tech-bloody-driver-git", "nordic-bluish-accent-theme",
            "nordic-bluish-accent-standard-buttons-theme", "nordic-polar-standard-buttons-theme",
            "nordic-standard-buttons-theme", "nordic-darker-standard-buttons-theme"
        ]
    
    def _load_config(self):
        """Load configuration from environment."""
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        self.repo_server_url = os.getenv('REPO_SERVER_URL')
        self.remote_dir = os.getenv('REMOTE_DIR', '/var/www/repo')
        self.repo_name = os.getenv('REPO_NAME', 'manjaro-awesome')
        
        # Validate
        required = ['VPS_USER', 'VPS_HOST', 'VPS_SSH_KEY', 'REPO_SERVER_URL']
        missing = [var for var in required if not os.getenv(var)]
        
        if missing:
            logger.error(colorize('ERROR', f"Missing required environment variables: {missing}"))
            sys.exit(1)
        
        print(colorize('INFO', f"Configuration:"))
        print(colorize('INFO', f"  SSH: {self.vps_user}@{self.vps_host}"))
        print(colorize('INFO', f"  Remote: {self.remote_dir}"))
        print(colorize('INFO', f"  Repo: {self.repo_name} -> {self.repo_server_url}"))
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=False):
        """Run command with proper error handling."""
        logger.debug(f"Running: {cmd}")
        
        try:
            if shell or isinstance(cmd, str):
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    shell=True,
                    capture_output=capture,
                    text=True,
                    check=check
                )
            else:
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    capture_output=capture,
                    text=True,
                    check=check
                )
            
            if result.returncode != 0 and check:
                logger.error(f"Command failed with exit code {result.returncode}: {cmd}")
                if capture and result.stderr:
                    logger.error(f"Stderr: {result.stderr[:500]}")
            
            return result
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {cmd}")
            if e.stderr:
                logger.error(f"Error: {e.stderr[:500]}")
            if check:
                raise
            return e
        except Exception as e:
            logger.error(f"Error running command {cmd}: {e}")
            if check:
                raise
            return None
    
    def setup_environment(self):
        """Setup build environment."""
        print(colorize('INFO', "\n=== Setting up environment ==="))
        
        # Configure SSH
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(parents=True, exist_ok=True)
        
        key_file = ssh_dir / "id_ed25519"
        try:
            # Try to decode base64
            import base64
            key_data = base64.b64decode(self.ssh_key)
            key_file.write_bytes(key_data)
        except:
            # If not base64, write as text
            key_file.write_text(self.ssh_key)
        
        key_file.chmod(0o600)
        
        # Add known hosts
        known_hosts = ssh_dir / "known_hosts"
        for host in [self.vps_host, "github.com"]:
            result = self.run_cmd(f"ssh-keyscan -H {host}", capture=True, check=False)
            if result and result.stdout:
                with open(known_hosts, 'a') as f:
                    f.write(result.stdout)
        
        # Set ownership
        self.run_cmd(f"chown -R builder:builder {ssh_dir}")
        
        # Configure git
        self.run_cmd("git config --global user.name 'GitHub Action Bot'")
        self.run_cmd("git config --global user.email 'action@github.com'")
        
        # Configure pacman with our repository
        self._configure_pacman()
        
        # Install yay if needed
        self._install_yay()
        
        print(colorize('SUCCESS', "✅ Environment setup complete"))
    
    def _configure_pacman(self):
        """Configure pacman with our custom repository."""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found!")
            return
        
        # Backup
        backup = pacman_conf.with_suffix('.conf.backup')
        if not backup.exists():
            shutil.copy2(pacman_conf, backup)
        
        # Read content
        with open(pacman_conf, 'r') as f:
            content = f.read()
        
        # Check if already configured
        if f"[{self.repo_name}]" in content:
            logger.info(f"Repository '{self.repo_name}' already in pacman.conf")
            return
        
        # Add our repository
        repo_config = f"\n[{self.repo_name}]\nServer = {self.repo_server_url}\nSigLevel = Optional TrustAll\n"
        
        # Insert before [community] or at end
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if line.strip().startswith("[community]"):
                lines.insert(i, repo_config)
                break
        else:
            lines.append(repo_config)
        
        # Write back
        with open(pacman_conf, 'w') as f:
            f.write('\n'.join(lines))
        
        # Update database
        self.run_cmd("pacman -Sy --noconfirm", check=False)
        logger.info(f"✅ Added repository '{self.repo_name}' to pacman.conf")
    
    def _install_yay(self):
        """Install yay AUR helper."""
        # Check if yay is already installed
        result = self.run_cmd("which yay", capture=True, check=False)
        if result and result.returncode == 0:
            logger.info("yay is already installed")
            return
        
        logger.info("Installing yay...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Clone yay
            self.run_cmd(f"git clone https://aur.archlinux.org/yay.git {tmpdir}/yay")
            
            # Build and install
            self.run_cmd(f"cd {tmpdir}/yay && makepkg -si --noconfirm --clean")
        
        # Configure yay for automation
        config_cmds = [
            "yay -Y --gendb --noconfirm",
            "yay -Y --devel --save --noconfirm",
            "yay -Y --nodiffmenu --save --noconfirm",
            "yay -Y --noeditmenu --save --noconfirm",
            "yay -Y --removemake --save --noconfirm",
        ]
        
        for cmd in config_cmds:
            self.run_cmd(cmd, check=False)
        
        logger.info("✅ yay installed and configured")
    
    def fetch_remote_packages(self):
        """Fetch list of packages from server."""
        print(colorize('INFO', "\n=== Fetching remote package list ==="))
        
        cmd = f"ssh {self.vps_user}@{self.vps_host} 'find \"{self.remote_dir}\" -name \"*.pkg.tar.*\" -type f -printf \"%f\\n\" 2>/dev/null'"
        result = self.run_cmd(cmd, capture=True, check=False)
        
        if result and result.stdout:
            self.remote_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            logger.info(f"Found {len(self.remote_files)} packages on server")
            
            # Also download database
            self._download_database()
        else:
            self.remote_files = []
            logger.warning("Could not fetch remote package list")
    
    def _download_database(self):
        """Download repository database."""
        db_source = f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/{self.repo_name}.db.tar.gz"
        db_dest = self.output_dir / f"{self.repo_name}.db.tar.gz"
        
        cmd = f"scp {db_source} {db_dest}"
        result = self.run_cmd(cmd, check=False)
        
        if result and result.returncode == 0:
            logger.info(f"Database downloaded: {db_dest}")
        else:
            logger.info("No existing database found (first run?)")
    
    def package_exists(self, pkg_name, version=None):
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        if version:
            pattern = f"^{re.escape(pkg_name)}-{re.escape(version)}-"
        else:
            pattern = f"^{re.escape(pkg_name)}-"
        
        return any(re.match(pattern, f) for f in self.remote_files)
    
    def extract_version(self, pkg_dir):
        """Extract version from PKGBUILD."""
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            return "unknown", "1"
        
        content = pkgbuild.read_text()
        
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        pkgver = pkgver_match.group(1) if pkgver_match else "unknown"
        pkgrel = pkgrel_match.group(1) if pkgrel_match else "1"
        
        return pkgver, pkgrel
    
    def build_aur_package(self, pkg_name):
        """Build AUR package."""
        print(colorize('INFO', f"\n--- Building AUR: {pkg_name} ---"))
        
        # Create AUR build directory
        aur_dir = self.repo_root / "build_aur"
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        
        # Clone from AUR
        result = self.run_cmd(
            f"git clone https://aur.archlinux.org/{pkg_name}.git {pkg_dir}",
            check=False
        )
        
        if not result or result.returncode != 0:
            logger.error(f"Failed to clone {pkg_name}")
            return False
        
        # Check version and skip if already exists
        pkgver, pkgrel = self.extract_version(pkg_dir)
        full_version = f"{pkgver}-{pkgrel}"
        
        if self.package_exists(pkg_name, full_version):
            logger.info(f"✅ {pkg_name} {full_version} already on server - skipping")
            self.skipped_packages.append(pkg_name)
            shutil.rmtree(pkg_dir)
            return False
        
        # Special handling for qt5-styleplugins
        if pkg_name == "qt5-styleplugins":
            self._handle_qt5_styleplugins(pkg_dir)
        
        # Build
        logger.info(f"Building {pkg_name} ({full_version})...")
        
        try:
            # Download sources
            self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir)
            
            # Install AUR dependencies
            self._install_aur_deps(pkg_dir)
            
            # Build package
            build_result = self.run_cmd(
                "makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=False,
                check=False
            )
            
            if build_result.returncode == 0:
                # Move built packages
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(pkg_file, dest)
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                
                # Cleanup
                shutil.rmtree(pkg_dir)
                return True
            else:
                logger.error(f"Failed to build {pkg_name}")
                shutil.rmtree(pkg_dir)
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            if pkg_dir.exists():
                shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
    
    def build_local_package(self, pkg_name):
        """Build local package."""
        print(colorize('INFO', f"\n--- Building Local: {pkg_name} ---"))
        
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        # Check version and skip if already exists
        pkgver, pkgrel = self.extract_version(pkg_dir)
        full_version = f"{pkgver}-{pkgrel}"
        
        if self.package_exists(pkg_name, full_version):
            logger.info(f"✅ {pkg_name} {full_version} already on server - skipping")
            self.skipped_packages.append(pkg_name)
            return False
        
        # Build
        logger.info(f"Building {pkg_name} ({full_version})...")
        
        try:
            # Download sources
            self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir)
            
            # Build package
            build_result = self.run_cmd(
                "makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=False,
                check=False
            )
            
            if build_result.returncode == 0:
                # Move built packages
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(pkg_file, dest)
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                
                # Update git repository
                self._update_git_repo(pkg_name, pkg_dir, full_version)
                return True
            else:
                logger.error(f"Failed to build {pkg_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            return False
    
    def _handle_qt5_styleplugins(self, pkg_dir):
        """Special handling for qt5-styleplugins."""
        # Check if gtk2 was built
        gtk2_built = any("gtk2" in str(p) for p in self.output_dir.glob("*.pkg.tar.*"))
        
        if gtk2_built:
            logger.info("Removing gtk2 dependency from qt5-styleplugins")
            pkgbuild = pkg_dir / "PKGBUILD"
            if pkgbuild.exists():
                content = pkgbuild.read_text()
                # Remove gtk2 dependency
                content = re.sub(r'\bgtk2\b', '', content)
                content = re.sub(r'["\']gtk2["\']', '', content)
                pkgbuild.write_text(content)
    
    def _install_aur_deps(self, pkg_dir):
        """Install dependencies for AUR package."""
        # Generate .SRCINFO
        self.run_cmd("makepkg --printsrcinfo", cwd=pkg_dir, check=False)
        
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            return
        
        # Parse dependencies
        deps = []
        with open(srcinfo, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("depends =") or line.startswith("makedepends ="):
                    dep = line.split('=', 1)[1].strip()
                    if dep and "gtk2" not in dep:  # Skip gtk2
                        deps.append(dep)
        
        if not deps:
            return
        
        logger.info(f"Installing {len(deps)} dependencies...")
        
        # Try to install each dependency
        for dep in deps:
            # Clean version specifiers
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            
            # Try pacman first
            result = self.run_cmd(f"pacman -S --needed --noconfirm {dep_clean}", check=False)
            if result.returncode != 0:
                # Try yay for AUR dependencies
                self.run_cmd(f"yay -S --asdeps --needed --noconfirm {dep_clean}", check=False)
    
    def _update_git_repo(self, pkg_name, pkg_dir, version):
        """Update git repository."""
        try:
            # Generate .SRCINFO
            self.run_cmd("makepkg --printsrcinfo", cwd=pkg_dir)
            
            # Add files
            self.run_cmd(f"git add {pkg_name}/PKGBUILD {pkg_name}/.SRCINFO")
            
            # Commit
            commit_msg = f"Auto-update: {pkg_name} to {version} [skip ci]"
            self.run_cmd(f"git commit -m '{commit_msg}'", check=False)
            
            # Push
            self.run_cmd("git push", check=False)
            logger.info(f"✅ Git repository updated for {pkg_name}")
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
        
        # Build repo-add command
        if db_file.exists():
            cmd = ["repo-add", "-R", str(db_file)]
        else:
            cmd = ["repo-add", str(db_file)]
        
        cmd.extend([str(p) for p in pkg_files])
        
        result = self.run_cmd(cmd, cwd=self.output_dir, check=False)
        
        if result and result.returncode == 0:
            logger.info("✅ Database updated")
            return True
        else:
            logger.error("Failed to update database")
            return False
    
    def upload_packages(self):
        """Upload packages to server."""
        files = list(self.output_dir.glob("*"))
        if not files:
            logger.warning("No files to upload")
            return False
        
        logger.info(f"Uploading {len(files)} files...")
        
        # Create remote directory
        self.run_cmd(f"ssh {self.vps_user}@{self.vps_host} 'mkdir -p \"{self.remote_dir}\"'", check=False)
        
        # Upload files
        files_str = " ".join([f'"{str(f)}"' for f in files])
        cmd = f"scp -B {files_str} {self.vps_user}@{self.vps_host}:\"{self.remote_dir}/\""
        
        result = self.run_cmd(cmd, check=False)
        
        if result and result.returncode == 0:
            logger.info("✅ Upload successful")
            return True
        else:
            logger.error("❌ Upload failed")
            return False
    
    def cleanup_old_packages(self):
        """Remove old package versions."""
        if not self.packages_to_clean:
            logger.info("No packages to clean up")
            return
        
        logger.info(f"Cleaning up old versions for {len(self.packages_to_clean)} packages...")
        
        for pkg in self.packages_to_clean:
            cmd = f"ssh {self.vps_user}@{self.vps_host} 'cd \"{self.remote_dir}\" && ls -t {pkg}-*.pkg.tar.zst 2>/dev/null | tail -n +3 | xargs -r rm -f 2>/dev/null || true'"
            self.run_cmd(cmd, check=False)
        
        logger.info("✅ Cleanup complete")
    
    def run(self):
        """Main execution."""
        print(colorize('INFO', "\n" + "="*60))
        print(colorize('INFO', "MANJARO PACKAGE BUILDER"))
        print(colorize('INFO', "="*60))
        print(colorize('INFO', f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"))
        
        try:
            # Setup
            self.setup_environment()
            self.fetch_remote_packages()
            
            # Build AUR packages
            print(colorize('INFO', f"\n=== Building {len(self.aur_packages)} AUR packages ==="))
            for pkg in self.aur_packages:
                if self.build_aur_package(pkg):
                    self.stats["aur_success"] += 1
            
            # Build local packages
            print(colorize('INFO', f"\n=== Building {len(self.local_packages)} local packages ==="))
            for pkg in self.local_packages:
                if self.build_local_package(pkg):
                    self.stats["local_success"] += 1
            
            # Finalize if we built anything
            total_built = self.stats["aur_success"] + self.stats["local_success"]
            
            if total_built > 0:
                print(colorize('INFO', "\n=== Finalizing build ==="))
                
                if self.update_database():
                    if self.upload_packages():
                        self.cleanup_old_packages()
                        print(colorize('SUCCESS', "\n✅ Build completed successfully!"))
                    else:
                        print(colorize('ERROR', "\n❌ Upload failed!"))
                else:
                    print(colorize('ERROR', "\n❌ Database update failed!"))
            else:
                print(colorize('INFO', "\n✅ All packages are up to date!"))
                if self.skipped_packages:
                    print(colorize('INFO', f"Skipped packages: {len(self.skipped_packages)}"))
            
            # Summary
            elapsed = time.time() - self.stats["start_time"]
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            print(colorize('INFO', "\n" + "="*60))
            print(colorize('INFO', "BUILD SUMMARY"))
            print(colorize('INFO', "="*60))
            print(colorize('INFO', f"Duration: {minutes}m {seconds}s"))
            print(colorize('INFO', f"AUR packages:    {self.stats['aur_success']}/{len(self.aur_packages)}"))
            print(colorize('INFO', f"Local packages:  {self.stats['local_success']}/{len(self.local_packages)}"))
            print(colorize('INFO', f"Total built:     {total_built}"))
            print(colorize('INFO', f"Skipped:         {len(self.skipped_packages)}"))
            print(colorize('INFO', "="*60))
            
            return 0 if total_built > 0 or len(self.skipped_packages) > 0 else 1
            
        except Exception as e:
            print(colorize('ERROR', f"\n❌ Build failed: {e}"))
            import traceback
            traceback.print_exc()
            return 1

if __name__ == "__main__":
    sys.exit(PackageBuilder().run())