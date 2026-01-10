#!/usr/bin/env python3
"""
Manjaro Package Builder - With proper pacman repository handling
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
        self.build_tracking_dir = self.repo_root / ".build_tracking"
        
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
        
        # Verify pacman repository is configured
        self._verify_pacman_repository()
    
    def _verify_pacman_repository(self):
        """Verify that our repository is configured in pacman."""
        print("\n🔍 Verifying pacman repository configuration...")
        
        # Check if repository exists in pacman.conf
        result = self.run_cmd(f"grep -q '\\[{self.repo_name}\\]' /etc/pacman.conf", check=False)
        if result.returncode == 0:
            print(f"✅ Repository '{self.repo_name}' found in pacman.conf")
            
            # Check if we can query the repository
            query_result = self.run_cmd(f"pacman -Sl {self.repo_name}", check=False, capture=True)
            if query_result.returncode == 0:
                print(f"✅ Repository '{self.repo_name}' is accessible via pacman")
                if query_result.stdout:
                    print(f"   Available packages: {len(query_result.stdout.strip().split('\\n'))}")
            else:
                print(f"⚠️ Repository '{self.repo_name}' found but not accessible")
                print("   This may cause dependency issues during build")
        else:
            print(f"❌ Repository '{self.repo_name}' NOT found in pacman.conf")
            print("   Please run the 'Configure Pacman Repository' step in the workflow")
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True):
        """Run command with error handling."""
        logger.debug(f"Running: {cmd}")
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                shell=shell,
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
        
        cmd = f"ssh -o ConnectTimeout=30 -o BatchMode=yes {self.vps_user}@{self.vps_host} 'find \"{self.remote_dir}\" -name \"*.pkg.tar.*\" -type f -printf \"%f\\n\" 2>/dev/null'"
        result = self.run_cmd(cmd, capture=True, check=False)
        
        if result and result.stdout:
            self.remote_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            logger.info(f"Found {len(self.remote_files)} packages on server")
            
            # Debug: show some packages
            if self.remote_files:
                logger.debug(f"First 5 packages: {self.remote_files[:5]}")
        else:
            self.remote_files = []
            logger.warning("Could not fetch remote package list")
            if result and result.stderr:
                logger.error(f"SSH error: {result.stderr}")
    
    def package_exists(self, pkg_name, version=None):
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        if version:
            pattern = f"^{re.escape(pkg_name)}-{re.escape(version)}-"
        else:
            pattern = f"^{re.escape(pkg_name)}-"
        
        matches = [f for f in self.remote_files if re.match(pattern, f)]
        
        if matches:
            logger.debug(f"Package {pkg_name} exists: {matches[0]}")
            return True
        
        return False
    
    def get_remote_version(self, pkg_name):
        """Get the version of a package from remote server."""
        if not self.remote_files:
            return None
        
        pattern = f"^{re.escape(pkg_name)}-([0-9].*?)-"
        for filename in self.remote_files:
            match = re.match(pattern, filename)
            if match:
                return match.group(1)
        
        return None
    
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
        print(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")
        
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
        print(f"Cloning {pkg_name} from AUR...")
        result = self.run_cmd(
            f"git clone https://aur.archlinux.org/{pkg_name}.git {pkg_dir}",
            check=False
        )
        
        if not result or result.returncode != 0:
            logger.error(f"Failed to clone {pkg_name}")
            return False
        
        # Check if PKGBUILD exists
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir)
            return False
        
        # Extract version
        content = pkgbuild.read_text()
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        if pkgver_match and pkgrel_match:
            version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
            
            # Check if this exact version already exists
            if self.package_exists(pkg_name, version):
                logger.info(f"✅ {pkg_name} {version} already exists on server - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                shutil.rmtree(pkg_dir)
                return False
            
            # Check if any version exists (for logging)
            remote_version = self.get_remote_version(pkg_name)
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
        else:
            version = "unknown"
            logger.warning(f"Could not extract version for {pkg_name}")
        
        # Special handling for qt5-styleplugins
        if pkg_name == "qt5-styleplugins":
            self._handle_qt5_styleplugins(pkg_dir)
        
        # Build
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Download sources
            print("Downloading sources...")
            source_result = self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}: {source_result.stderr[:200]}")
                shutil.rmtree(pkg_dir)
                return False
            
            # Install AUR dependencies
            self._install_aur_deps(pkg_dir, pkg_name)
            
            # Build package
            print("Building package...")
            build_result = self.run_cmd(
                "makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            if build_result.returncode == 0:
                # Move built packages
                moved = False
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(pkg_file, dest)
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                
                # Cleanup
                shutil.rmtree(pkg_dir)
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                logger.error(f"Failed to build {pkg_name}: {build_result.stderr[:500]}")
                shutil.rmtree(pkg_dir)
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            if pkg_dir.exists():
                shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
    
    def _handle_qt5_styleplugins(self, pkg_dir):
        """Special handling for qt5-styleplugins."""
        # Check if gtk2 is available in our repository
        gtk2_result = self.run_cmd(f"pacman -Sl {self.repo_name} | grep -q 'gtk2'", check=False)
        
        if gtk2_result.returncode == 0:
            logger.info("gtk2 is available in our repository, will be installed as dependency")
            # No need to modify PKGBUILD
        else:
            logger.warning("gtk2 not found in our repository, checking if we built it...")
            # Check if we built gtk2 in this session
            gtk2_built = any("gtk2" in pkg for pkg in self.built_packages)
            if gtk2_built:
                logger.info("gtk2 was built in this session, removing from dependencies")
                pkgbuild = pkg_dir / "PKGBUILD"
                if pkgbuild.exists():
                    content = pkgbuild.read_text()
                    # Remove gtk2 dependency
                    content = re.sub(r'\bgtk2\b', '', content)
                    content = re.sub(r'["\']gtk2["\']', '', content)
                    pkgbuild.write_text(content)
    
    def _install_aur_deps(self, pkg_dir, pkg_name):
        """Install dependencies for AUR package."""
        print(f"Checking dependencies for {pkg_name}...")
        
        # Generate .SRCINFO
        self.run_cmd("makepkg --printsrcinfo", cwd=pkg_dir, check=False)
        
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            logger.warning(f"No .SRCINFO for {pkg_name}")
            return
        
        # Parse dependencies
        deps = []
        with open(srcinfo, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith("depends =") or line.startswith("makedepends ="):
                    dep = line.split('=', 1)[1].strip()
                    if dep and dep not in ["gtk2"]:  # Skip gtk2 (handled separately)
                        deps.append(dep)
        
        if not deps:
            logger.info(f"No dependencies for {pkg_name}")
            return
        
        logger.info(f"Found {len(deps)} dependencies: {', '.join(deps[:5])}{'...' if len(deps) > 5 else ''}")
        
        # Try to install each dependency
        installed_count = 0
        for dep in deps:
            # Clean version specifiers
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            
            if not dep_clean:
                continue
            
            # Skip if already installed
            check_result = self.run_cmd(f"pacman -Qi {dep_clean} >/dev/null 2>&1", check=False)
            if check_result.returncode == 0:
                logger.debug(f"Dependency already installed: {dep_clean}")
                installed_count += 1
                continue
            
            # Try pacman first (from our repository or official repos)
            print(f"Installing {dep_clean}...")
            result = self.run_cmd(f"pacman -S --needed --noconfirm {dep_clean}", check=False, capture=True)
            
            if result.returncode != 0:
                # Try yay for AUR dependencies
                logger.info(f"Trying yay for {dep_clean}...")
                yay_result = self.run_cmd(f"yay -S --asdeps --needed --noconfirm {dep_clean}", check=False, capture=True)
                if yay_result.returncode == 0:
                    installed_count += 1
                else:
                    logger.warning(f"Failed to install dependency: {dep_clean}")
            else:
                installed_count += 1
        
        logger.info(f"Installed {installed_count}/{len(deps)} dependencies")
    
    def _build_local_package(self, pkg_name):
        """Build local package."""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        # Check if PKGBUILD exists
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        # Extract version
        content = pkgbuild.read_text()
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        if pkgver_match and pkgrel_match:
            version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
            
            # Check if this exact version already exists
            if self.package_exists(pkg_name, version):
                logger.info(f"✅ {pkg_name} {version} already exists on server - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                return False
            
            # Check if any version exists (for logging)
            remote_version = self.get_remote_version(pkg_name)
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
        else:
            version = "unknown"
            logger.warning(f"Could not extract version for {pkg_name}")
        
        # Build
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Download sources
            print("Downloading sources...")
            source_result = self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}: {source_result.stderr[:200]}")
                return False
            
            # Build package
            print("Building package...")
            build_result = self.run_cmd(
                "makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            if build_result.returncode == 0:
                # Move built packages
                moved = False
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(pkg_file, dest)
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                logger.error(f"Failed to build {pkg_name}: {build_result.stderr[:500]}")
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
        
        # Check if database exists
        if db_file.exists():
            cmd = ["repo-add", "-R", str(db_file)]
        else:
            cmd = ["repo-add", str(db_file)]
        
        cmd.extend([str(p) for p in pkg_files])
        
        result = self.run_cmd(cmd, cwd=self.output_dir, check=False, shell=False)
        
        if result and result.returncode == 0:
            logger.info("✅ Database updated")
            return True
        else:
            logger.error(f"Failed to update database: {result.stderr if result else 'Unknown error'}")
            return False
    
    def upload_packages(self):
        """Upload packages to server."""
        files = list(self.output_dir.glob("*"))
        if not files:
            logger.warning("No files to upload")
            return False
        
        logger.info(f"Uploading {len(files)} files...")
        
        # First, create remote directory if it doesn't exist
        mkdir_cmd = f"ssh {self.vps_user}@{self.vps_host} 'mkdir -p \"{self.remote_dir}\"'"
        self.run_cmd(mkdir_cmd, check=False)
        
        # Upload files
        files_str = " ".join([f'"{str(f)}"' for f in files])
        cmd = f"scp -B {files_str} {self.vps_user}@{self.vps_host}:\"{self.remote_dir}/\""
        
        result = self.run_cmd(cmd, check=False, capture=True)
        
        if result and result.returncode == 0:
            logger.info("✅ Upload successful")
            return True
        else:
            logger.error(f"❌ Upload failed: {result.stderr if result else 'Unknown error'}")
            return False
    
    def cleanup_old_packages(self):
        """Remove old package versions."""
        if not self.packages_to_clean:
            logger.info("No packages to clean up")
            return
        
        logger.info(f"Cleaning up old versions for {len(self.packages_to_clean)} packages...")
        
        cleaned = 0
        for pkg in self.packages_to_clean:
            cmd = f"ssh {self.vps_user}@{self.vps_host} 'cd \"{self.remote_dir}\" && ls -t {pkg}-*.pkg.tar.zst 2>/dev/null | tail -n +3 | xargs -r rm -f 2>/dev/null || true'"
            result = self.run_cmd(cmd, check=False)
            if result and result.returncode == 0:
                cleaned += 1
        
        logger.info(f"✅ Cleanup complete ({cleaned} packages)")
    
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
                    print(f"Skipped packages: {len(self.skipped_packages)}")
            
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
            
            if self.built_packages:
                print("\n📦 Built packages:")
                for pkg in self.built_packages:
                    print(f"  - {pkg}")
            
            return 0
            
        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            return 1

if __name__ == "__main__":
    sys.exit(PackageBuilder().run())