#!/usr/bin/env python3
"""
Manjaro Package Builder - Fixed with working bash script logic
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import logging
import socket
from pathlib import Path
from datetime import datetime

# Try to import our config files
try:
    import config
    import packages
    HAS_CONFIG_FILES = True
except ImportError as e:
    print(f"⚠️ Warning: Could not import config files: {e}")
    print("⚠️ Using default configurations")
    HAS_CONFIG_FILES = False

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
        # Get the repository root from environment or detect it
        self.repo_root = self._get_repo_root()
        
        # Load configuration
        self._load_config()
        
        # Setup directories - use config values or defaults
        self.output_dir = self.repo_root / getattr(config, 'OUTPUT_DIR', 'built_packages') if HAS_CONFIG_FILES else self.repo_root / "built_packages"
        self.build_tracking_dir = self.repo_root / getattr(config, 'BUILD_TRACKING_DIR', '.build_tracking') if HAS_CONFIG_FILES else self.repo_root / ".build_tracking"
        
        # Setup directories
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # State
        self.remote_files = []
        self.packages_to_clean = set()
        self.built_packages = []
        self.skipped_packages = []
        self.rebuilt_local_packages = []  # Track local packages that were rebuilt
        
        # Special dependencies from config
        self.special_dependencies = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
        
        # SSH options - SIMPLIFIED like bash scripts
        self.ssh_options = ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30"]
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
        }
    
    def _get_repo_root(self):
        """Get the repository root directory reliably."""
        # First, check GITHUB_WORKSPACE environment variable
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                logger.info(f"Using GITHUB_WORKSPACE: {workspace_path}")
                return workspace_path
        
        # If we're in a container, check the typical GitHub Actions workspace path
        container_workspace = Path('/__w/manjaro-awesome/manjaro-awesome')
        if container_workspace.exists():
            logger.info(f"Using container workspace: {container_workspace}")
            return container_workspace
        
        # As a last resort, return the current directory
        current_dir = Path.cwd()
        logger.info(f"Using current directory: {current_dir}")
        return current_dir
    
    def _load_config(self):
        """Load configuration from environment and config files."""
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        self.repo_server_url = os.getenv('REPO_SERVER_URL')
        self.remote_dir = os.getenv('REMOTE_DIR', '/var/www/repo')
        
        # Get repo name from env, then config, then default
        env_repo_name = os.getenv('REPO_NAME')
        if HAS_CONFIG_FILES:
            config_repo_name = getattr(config, 'REPO_DB_NAME', 'manjaro-awesome')
            self.repo_name = env_repo_name if env_repo_name else config_repo_name
        else:
            self.repo_name = env_repo_name if env_repo_name else 'manjaro-awesome'
        
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
        print(f"   Config files loaded: {HAS_CONFIG_FILES}")
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, env=None):
        """Run command with error handling."""
        logger.debug(f"Running: {cmd}")
        
        # If no cwd specified, use repo_root
        if cwd is None:
            cwd = self.repo_root
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                shell=shell,
                capture_output=capture,
                text=True,
                check=check,
                env=env
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {cmd}")
            if e.stderr:
                logger.error(f"Error: {e.stderr[:200]}")
            if check:
                raise
            return e
    
    def test_connection(self):
        """Test SSH connection to VPS - like bash scripts."""
        print("\n🔍 Testing SSH connection to VPS...")
        
        # Test basic connectivity
        print("1. Testing port 22 connectivity...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)
            result = sock.connect_ex((self.vps_host, 22))
            sock.close()
            
            if result == 0:
                print("✅ Port 22 is open on VPS")
            else:
                print(f"⚠️ Port 22 is closed (error code: {result})")
                return False
        except Exception as e:
            print(f"⚠️ Socket test failed: {e}")
            return False
        
        # Test SSH as builder user using simple options like bash scripts
        print("2. Testing SSH connection as builder user...")
        ssh_test_cmd = [
            "ssh",
            *self.ssh_options,
            "-i", "/home/builder/.ssh/id_ed25519",
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]
        
        result = self.run_cmd(ssh_test_cmd, check=False, capture=True, shell=False)
        if result and result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout:
            print("✅ SSH connection successful")
            return True
        else:
            print(f"❌ SSH connection failed: {result.stderr[:100] if result and result.stderr else 'No output'}")
            return False
    
    def fetch_remote_packages(self):
        """Fetch list of packages from server - like bash scripts."""
        print("\n📡 Fetching remote package list...")
        
        # Build SSH command with simple options
        ssh_cmd = [
            "ssh",
            *self.ssh_options,
            "-i", "/home/builder/.ssh/id_ed25519",
            f"{self.vps_user}@{self.vps_host}"
        ]
        
        # Use simple ls command like bash scripts
        remote_cmd = f'ls -1 "{self.remote_dir}" 2>/dev/null || echo "ERROR: Could not list remote files"'
        
        # Join SSH command with remote command
        full_cmd = ssh_cmd + [remote_cmd]
        
        result = self.run_cmd(full_cmd, capture=True, check=False, shell=False)
        
        if result and result.returncode == 0 and result.stdout:
            # Filter out error messages and non-package files
            lines = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            self.remote_files = [f for f in lines if f.endswith('.pkg.tar.zst') or f.endswith('.pkg.tar.xz')]
            
            if self.remote_files:
                logger.info(f"Found {len(self.remote_files)} packages on server")
                # Save to file like bash scripts
                remote_files_path = self.repo_root / "remote_files.txt"
                with open(remote_files_path, 'w') as f:
                    for file in self.remote_files:
                        f.write(f"{file}\n")
                logger.info(f"Saved remote files list to: {remote_files_path}")
            else:
                logger.warning("No packages found on server (or server unreachable)")
        else:
            self.remote_files = []
            logger.warning("Could not fetch remote package list")
            if result and result.stderr:
                logger.error(f"SSH error: {result.stderr[:200]}")
    
    def download_database(self):
        """Download existing database from server - like bash scripts."""
        print("\n📥 Downloading existing database...")
        
        db_file = self.output_dir / f"{self.repo_name}.db.tar.gz"
        
        # Use scp to download database
        scp_cmd = [
            "scp",
            *self.ssh_options,
            "-i", "/home/builder/.ssh/id_ed25519",
            f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/{self.repo_name}.db.tar.gz",
            str(db_file)
        ]
        
        result = self.run_cmd(scp_cmd, check=False, capture=True, shell=False)
        
        if result and result.returncode == 0:
            if db_file.exists():
                size = db_file.stat().st_size
                logger.info(f"✅ Downloaded database: {db_file.name} ({size} bytes)")
                return True
            else:
                logger.warning("SCP succeeded but file not found")
                return False
        else:
            logger.info("No existing database found (or download failed) - will create new one")
            return False
    
    def package_exists(self, pkg_name, version=None):
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        # First check if we have a remote_files.txt file
        remote_files_path = self.repo_root / "remote_files.txt"
        if remote_files_path.exists():
            with open(remote_files_path, 'r') as f:
                remote_files = [line.strip() for line in f if line.strip()]
        else:
            remote_files = self.remote_files
        
        if version:
            pattern = f"^{re.escape(pkg_name)}-{re.escape(version)}-"
        else:
            pattern = f"^{re.escape(pkg_name)}-"
        
        matches = [f for f in remote_files if re.match(pattern, f)]
        
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
    
    def get_package_lists(self):
        """Get package lists from packages.py or use defaults."""
        if HAS_CONFIG_FILES and hasattr(packages, 'LOCAL_PACKAGES') and hasattr(packages, 'AUR_PACKAGES'):
            print("📦 Using package lists from packages.py")
            return packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
        else:
            print("⚠️ Using default package lists (packages.py not found or incomplete)")
            # NO hardcoded package lists - return empty lists
            return [], []
    
    def build_packages(self):
        """Build packages."""
        print("\n" + "="*60)
        print("Building packages")
        print("="*60)
        
        # Get package lists from packages.py
        local_packages, aur_packages = self.get_package_lists()
        
        print(f"📦 Package statistics:")
        print(f"   Local packages: {len(local_packages)}")
        print(f"   AUR packages: {len(aur_packages)}")
        print(f"   Total packages: {len(local_packages) + len(aur_packages)}")
        
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
        """Build AUR package - simplified like bash scripts."""
        aur_dir = self.repo_root / "build_aur"
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        
        # Clone from AUR - multiple attempts like bash script
        print(f"Cloning {pkg_name} from AUR...")
        
        # Try different AUR URLs like bash script
        aur_urls = [
            f"https://aur.archlinux.org/{pkg_name}.git",
            f"https://aur.archlinux.org/{pkg_name}",
            f"git://aur.archlinux.org/{pkg_name}.git"
        ]
        
        cloned = False
        for aur_url in aur_urls:
            result = self.run_cmd(
                f"git clone {aur_url} {pkg_dir}",
                check=False,
                capture=True
            )
            if result and result.returncode == 0:
                cloned = True
                break
            else:
                print(f"  Failed with URL: {aur_url}")
        
        if not cloned:
            logger.error(f"Failed to clone {pkg_name} from AUR")
            return False
        
        # Check if PKGBUILD exists
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir)
            return False
        
        # Extract version
        try:
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
            else:
                version = "unknown"
        except:
            version = "unknown"
        
        # Build
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Change to package directory
            old_cwd = os.getcwd()
            os.chdir(pkg_dir)
            
            # Download sources
            print("Downloading sources...")
            source_result = self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}: {source_result.stderr[:200]}")
                os.chdir(old_cwd)
                shutil.rmtree(pkg_dir)
                return False
            
            # Install dependencies with yay (like bash script)
            print("Installing dependencies...")
            self.run_cmd("yay -S --asdeps --needed --noconfirm $(makepkg --printsrcinfo | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//' | tr '\n' ' ')", 
                        check=False, capture=True)
            
            # Build package
            print("Building package...")
            build_result = self.run_cmd(
                "makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            os.chdir(old_cwd)
            
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
            if 'pkg_dir' in locals() and pkg_dir.exists():
                shutil.rmtree(pkg_dir)
            return False
    
    def _build_local_package(self, pkg_name):
        """Build local package - simplified."""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        # Check if PKGBUILD exists
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        # Extract version from PKGBUILD
        try:
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
            else:
                version = "unknown"
        except:
            version = "unknown"
        
        # Check for special dependencies
        if pkg_name in self.special_dependencies:
            logger.info(f"Found special dependencies for {pkg_name}")
            for dep in self.special_dependencies[pkg_name]:
                logger.info(f"Installing special dependency: {dep}")
                self.run_cmd(f"sudo pacman -S --needed --noconfirm {dep}", check=False)
        
        # Build
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Change to package directory
            old_cwd = os.getcwd()
            os.chdir(pkg_dir)
            
            # Download sources
            print("Downloading sources...")
            source_result = self.run_cmd("makepkg -od --noconfirm", cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}: {source_result.stderr[:200]}")
                os.chdir(old_cwd)
                return False
            
            # Build package
            print("Building package...")
            
            # Special handling for gtk2 like bash script
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                logger.warn("GTK2: Skipping checks (takes too long)")
            
            build_result = self.run_cmd(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            os.chdir(old_cwd)
            
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
                    self.rebuilt_local_packages.append(pkg_name)
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
        """Update repository database - like bash scripts."""
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not pkg_files:
            logger.info("No packages to add to database")
            return False
        
        logger.info(f"Updating database with {len(pkg_files)} packages...")
        
        # Change to output directory
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            # Check if database exists
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Download existing database first (already done in download_database)
            # Now run repo-add like bash scripts
            pkg_files_str = ' '.join([str(p.name) for p in pkg_files])
            
            if os.path.exists(db_file):
                logger.info("Adding packages to existing database...")
                cmd = f"repo-add {db_file} {pkg_files_str}"
            else:
                logger.info("Creating new database...")
                cmd = f"repo-add {db_file} {pkg_files_str}"
            
            result = self.run_cmd(cmd, check=False, capture=True)
            
            if result and result.returncode == 0:
                # Check that database files were created
                expected_files = [
                    f"{self.repo_name}.db",
                    f"{self.repo_name}.db.tar.gz", 
                    f"{self.repo_name}.files",
                    f"{self.repo_name}.files.tar.gz"
                ]
                
                all_exist = all(os.path.exists(f) for f in expected_files)
                if all_exist:
                    # Check sizes
                    for f in expected_files:
                        size = os.path.getsize(f)
                        logger.info(f"  {f}: {size} bytes")
                    
                    logger.info("✅ Database updated successfully")
                    return True
                else:
                    missing = [f for f in expected_files if not os.path.exists(f)]
                    logger.error(f"❌ Database files missing: {missing}")
                    return False
            else:
                logger.error(f"repo-add failed: {result.stderr if result else 'Unknown error'}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def upload_packages(self):
        """Upload packages to server using SCP - like bash scripts."""
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not pkg_files:
            logger.warning("No files to upload")
            return False
        
        logger.info(f"Uploading {len(pkg_files)} files...")
        
        # Upload packages with SCP (3 attempts like bash script)
        upload_success = False
        
        for attempt in range(1, 4):
            logger.info(f"Upload attempt {attempt}/3...")
            
            # Build SCP command for all files
            files_str = ' '.join([str(f) for f in pkg_files])
            scp_cmd = [
                "scp",
                *self.ssh_options,
                "-i", "/home/builder/.ssh/id_ed25519",
                files_str,
                f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/"
            ]
            
            # Run SCP
            result = self.run_cmd(scp_cmd, check=False, capture=True, shell=False)
            
            if result and result.returncode == 0:
                logger.info("✅ Package upload successful")
                upload_success = True
                break
            else:
                logger.warning(f"Upload failed (attempt {attempt}): {result.stderr[:200] if result else 'Unknown error'}")
                if attempt < 3:
                    time.sleep(3)
        
        if not upload_success:
            logger.error("❌ Package upload failed after 3 attempts")
            return False
        
        # Also upload database files
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
        if db_files:
            logger.info(f"Uploading {len(db_files)} database files...")
            
            db_files_str = ' '.join([str(f) for f in db_files])
            db_scp_cmd = [
                "scp",
                *self.ssh_options,
                "-i", "/home/builder/.ssh/id_ed25519",
                db_files_str,
                f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/"
            ]
            
            db_result = self.run_cmd(db_scp_cmd, check=False, capture=True, shell=False)
            if db_result and db_result.returncode == 0:
                logger.info("✅ Database files uploaded")
            else:
                logger.error(f"Failed to upload database files: {db_result.stderr[:200] if db_result else 'Unknown error'}")
                # Don't fail the whole upload if database files fail
        
        return upload_success
    
    def cleanup_old_packages(self):
        """Remove old package versions - like bash scripts."""
        if not self.packages_to_clean:
            logger.info("No packages to clean up")
            return
        
        logger.info(f"Cleaning up old versions for {len(self.packages_to_clean)} packages...")
        
        cleaned = 0
        for pkg in self.packages_to_clean:
            # Build remote command to keep only last 3 versions
            remote_cmd = f'cd "{self.remote_dir}" && ls -t {pkg}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | xargs -r rm -f'
            
            ssh_cmd = [
                "ssh",
                *self.ssh_options,
                "-i", "/home/builder/.ssh/id_ed25519",
                f"{self.vps_user}@{self.vps_host}",
                remote_cmd
            ]
            
            result = self.run_cmd(ssh_cmd, check=False, shell=False)
            if result and result.returncode == 0:
                cleaned += 1
        
        logger.info(f"✅ Cleanup complete ({cleaned} packages)")
    
    def run(self):
        """Main execution."""
        print("\n" + "="*60)
        print("🚀 MANJARO PACKAGE BUILDER (Fixed Version)")
        print("="*60)
        
        try:
            # Setup
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Using repository: {self.repo_name}")
            print(f"Output directory: {self.output_dir}")
            print(f"Special dependencies loaded: {len(self.special_dependencies)}")
            
            # Test connection first
            if not self.test_connection():
                logger.warning("⚠️ Connection test failed, but continuing...")
            
            # Fetch remote packages
            self.fetch_remote_packages()
            
            # Download existing database
            self.download_database()
            
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