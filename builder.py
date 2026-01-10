#!/usr/bin/env python3
"""
Manjaro Package Builder - Simplified and robust version
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

class PackageBuilder:
    def __init__(self):
        self.repo_root = Path(os.getcwd())
        self.output_dir = self.repo_root / "built_packages"
        self.build_tracking_dir = self.repo_root / ".build_tracking"  # Note: your directory is .build_tracking
        
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
            logger.error(f"❌ Missing required environment variables: {missing}")
            logger.error("Please set these in your GitHub repository secrets")
            sys.exit(1)
        
        print(f"🔧 Configuration loaded:")
        print(f"   SSH: {self.vps_user}@{self.vps_host}")
        print(f"   Remote directory: {self.remote_dir}")
        print(f"   Repository: {self.repo_name} -> {self.repo_server_url}")
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True):
        """Run command with error handling."""
        logger.debug(f"Running: {cmd}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                shell=isinstance(cmd, str),
                capture_output=capture,
                text=True,
                check=check
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {cmd}")
            if e.stderr:
                logger.error(f"Error: {e.stderr[:200]}")
            if check:
                raise
            return e
    
    def setup_environment(self):
        """Setup build environment."""
        print("\n" + "="*60)
        print("Setting up environment")
        print("="*60)
        
        # Configure SSH
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(parents=True, exist_ok=True)
        
        key_file = ssh_dir / "id_ed25519"
        
        # Write SSH key (handle both base64 and plain text)
        try:
            import base64
            key_data = base64.b64decode(self.ssh_key)
            key_file.write_bytes(key_data)
            logger.debug("SSH key decoded from base64")
        except:
            key_file.write_text(self.ssh_key)
            logger.debug("SSH key written as plain text")
        
        key_file.chmod(0o600)
        
        # Add known hosts
        known_hosts = ssh_dir / "known_hosts"
        for host in [self.vps_host, "github.com"]:
            result = self.run_cmd(f"ssh-keyscan -H {host}", capture=True, check=False)
            if result and result.stdout:
                known_hosts.write_text(result.stdout)
        
        # Set ownership
        self.run_cmd(f"chown -R builder:builder {ssh_dir}")
        
        # Git configuration
        self.run_cmd("git config --global user.name 'GitHub Action Bot'")
        self.run_cmd("git config --global user.email 'action@github.com'")
        
        print("✅ Environment setup complete")
    
    def fetch_remote_packages(self):
        """Fetch list of packages from server."""
        print("\n📡 Fetching remote package list...")
        
        cmd = f"ssh {self.vps_user}@{self.vps_host} 'find \"{self.remote_dir}\" -name \"*.pkg.tar.*\" -type f -printf \"%f\\n\" 2>/dev/null'"
        result = self.run_cmd(cmd, capture=True, check=False)
        
        if result and result.stdout:
            self.remote_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            logger.info(f"Found {len(self.remote_files)} packages on server")
        else:
            self.remote_files = []
            logger.warning("Could not fetch remote package list")
    
    def package_exists(self, pkg_name, version=None):
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        if version:
            pattern = f"^{re.escape(pkg_name)}-{re.escape(version)}-"
        else:
            pattern = f"^{re.escape(pkg_name)}-"
        
        return any(re.match(pattern, f) for f in self.remote_files)
    
    def build_packages(self):
        """Build packages."""
        print("\n" + "="*60)
        print("Building packages")
        print("="*60)
        
        # Package lists
        aur_packages = [
            "libinput-gestures", "qt5-styleplugins", "urxvt-resize-font-git",
            "i3lock-color", "raw-thumbnailer", "gsconnect", "awesome-git",
            "tilix-git", "tamzen-font", "betterlockscreen", "nordic-theme",
            "nordic-darker-theme", "geany-nord-theme", "nordzy-icon-theme",
            "oh-my-posh-bin", "fish-done", "find-the-command", "p7zip-gui",
            "qownnotes", "xorg-font-utils", "xnviewmp", "simplescreenrecorder",
            "gtkhash-thunar", "a4tech-bloody-driver-git"
        ]
        
        local_packages = [
            "gghelper", "gtk2", "awesome-freedesktop-git", "lain-git",
            "awesome-rofi", "nordic-backgrounds", "awesome-copycats-manjaro",
            "i3lock-fancy-git", "ttf-font-awesome-5", "nvidia-driver-assistant",
            "grayjay-bin"
        ]
        
        # Build AUR packages
        print(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if self._build_single_package(pkg, is_aur=True):
                self.stats["aur_success"] += 1
        
        # Build local packages
        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self._build_single_package(pkg, is_aur=False):
                self.stats["local_success"] += 1
        
        return self.stats["aur_success"] + self.stats["local_success"]
    
    def _build_single_package(self, pkg_name, is_aur):
        """Build a single package."""
        logger.info(f"Processing: {pkg_name} ({'AUR' if is_aur else 'Local'})")
        
        if is_aur:
            # Build AUR package
            return self._build_aur_package(pkg_name)
        else:
            # Build local package
            return self._build_local_package(pkg_name)
    
    def _build_aur_package(self, pkg_name):
        """Build AUR package."""
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
        
        # Check if already exists
        pkgbuild = pkg_dir / "PKGBUILD"
        if pkgbuild.exists():
            content = pkgbuild.read_text()
            pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            
            if pkgver_match and pkgrel_match:
                version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
                if self.package_exists(pkg_name, version):
                    logger.info(f"✅ {pkg_name} {version} already exists - skipping")
                    self.skipped_packages.append(pkg_name)
                    shutil.rmtree(pkg_dir)
                    return False
        
        # Build
        try:
            logger.info(f"Building {pkg_name}...")
            
            # Download sources
            self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir, check=False)
            
            # Build package
            result = self.run_cmd(
                "makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=False,
                check=False
            )
            
            if result.returncode == 0:
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
    
    def _build_local_package(self, pkg_name):
        """Build local package."""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        # Check if already exists
        pkgbuild = pkg_dir / "PKGBUILD"
        if pkgbuild.exists():
            content = pkgbuild.read_text()
            pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            
            if pkgver_match and pkgrel_match:
                version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
                if self.package_exists(pkg_name, version):
                    logger.info(f"✅ {pkg_name} {version} already exists - skipping")
                    self.skipped_packages.append(pkg_name)
                    return False
        
        # Build
        try:
            logger.info(f"Building {pkg_name}...")
            
            # Download sources
            self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir, check=False)
            
            # Build package
            result = self.run_cmd(
                "makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=False,
                check=False
            )
            
            if result.returncode == 0:
                # Move built packages
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(pkg_file, dest)
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                return True
            else:
                logger.error(f"Failed to build {pkg_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            return False
    
    def update_database(self):
        """Update repository database."""
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not pkg_files:
            logger.info("No packages to add to database")
            return False
        
        logger.info(f"Updating database with {len(pkg_files)} packages...")
        
        db_file = self.output_dir / f"{self.repo_name}.db.tar.gz"
        
        # Build repo-add command
        cmd = ["repo-add", str(db_file)] + [str(p) for p in pkg_files]
        
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
        print("\n" + "="*60)
        print("🚀 MANJARO PACKAGE BUILDER")
        print("="*60)
        
        try:
            # Setup
            self.setup_environment()
            self.fetch_remote_packages()
            
            # Build packages
            total_built = self.build_packages()
            
            # Finalize if we built anything
            if total_built > 0:
                print("\n" + "="*60)
                print("📦 Finalizing build")
                print("="*60)
                
                if self.update_database():
                    if self.upload_packages():
                        self.cleanup_old_packages()
                        print("\n✅ Build completed successfully!")
                    else:
                        print("\n❌ Upload failed!")
                else:
                    print("\n❌ Database update failed!")
            else:
                print("\n✅ All packages are up to date!")
                if self.skipped_packages:
                    print(f"Skipped {len(self.skipped_packages)} packages")
            
            # Summary
            elapsed = time.time() - self.stats["start_time"]
            
            print("\n" + "="*60)
            print("📊 BUILD SUMMARY")
            print("="*60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {self.stats['aur_success']}")
            print(f"Local packages:  {self.stats['local_success']}")
            print(f"Total built:     {total_built}")
            print(f"Skipped:         {len(self.skipped_packages)}")
            print("="*60)
            
            return 0
            
        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            return 1

if __name__ == "__main__":
    sys.exit(PackageBuilder().run())