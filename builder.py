#!/usr/bin/env python3
"""
Manjaro Package Builder - Dinamikus repository kezeléssel
Javítva: Függőségek helyes kinyerése, pacman elsőbbsége
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
        
        # Repository state tracking
        self.repo_exists = False  # Will be determined by fetch_remote_packages()
        self.repo_has_packages = False  # Will be determined by fetch_remote_packages()
        
        # PHASE 1 OBSERVER: hokibot data collection (in-memory only)
        self.hokibot_data = []  # List of dicts: {name, built_version, pkgrel, epoch}
        
        # Special dependencies from config
        self.special_dependencies = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
        
        # SSH options for consistent behavior
        self.ssh_options = [
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=60",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=5",
            "-o", "TCPKeepAlive=yes",
            "-o", "BatchMode=yes",
            "-o", "LogLevel=ERROR"
        ]
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
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
        self.repo_server_url = os.getenv('REPO_SERVER_URL', '')
        self.remote_dir = os.getenv('REMOTE_DIR', '/var/www/repo')
        
        # Get repo name from env, then config, then default
        env_repo_name = os.getenv('REPO_NAME')
        if HAS_CONFIG_FILES:
            config_repo_name = getattr(config, 'REPO_DB_NAME', 'manjaro-awesome')
            self.repo_name = env_repo_name if env_repo_name else config_repo_name
        else:
            self.repo_name = env_repo_name if env_repo_name else 'manjaro-awesome'
        
        # Validate
        required = ['VPS_USER', 'VPS_HOST', 'VPS_SSH_KEY']
        missing = [var for var in required if not os.getenv(var)]
        
        if missing:
            logger.error(f"❌ Missing required environment variables: {missing}")
            logger.error("Please set these in your GitHub repository secrets")
            sys.exit(1)
        
        print(f"🔧 Configuration loaded:")
        print(f"   SSH: {self.vps_user}@{self.vps_host}")
        print(f"   Remote directory: {self.remote_dir}")
        print(f"   Repository name: {self.repo_name}")
        if self.repo_server_url:
            print(f"   Repository URL: {self.repo_server_url}")
        print(f"   Config files loaded: {HAS_CONFIG_FILES}")
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None):
        """Run command with error handling."""
        logger.debug(f"Running: {cmd}")
        
        # If no cwd specified, use repo_root
        if cwd is None:
            cwd = self.repo_root
        
        # If user is specified, we need to handle it differently
        if user:
            # Use sudo -u with env variables
            env = os.environ.copy()
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            
            try:
                # Build the command with sudo -u
                sudo_cmd = ['sudo', '-u', user]
                if shell:
                    # For shell commands, use bash -c
                    sudo_cmd.extend(['bash', '-c', f'cd "{cwd}" && {cmd}'])
                else:
                    # For non-shell commands, add the command directly
                    sudo_cmd.extend(cmd)
                
                result = subprocess.run(
                    sudo_cmd,
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
        else:
            # Run as current user
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
    
    def _manage_repository_state(self, enable=True):
        """Enable or disable our repository in pacman.conf dynamically."""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found")
            return
        
        try:
            # Read current content
            with open(pacman_conf, 'r') as f:
                content = f.read()
            
            # Check if our repository is already in the file
            repo_section = f"[{self.repo_name}]"
            if repo_section not in content:
                logger.info(f"Repository {self.repo_name} not found in pacman.conf, adding...")
                # Add our repository section
                lines = content.split('\n')
                new_lines = []
                for line in lines:
                    new_lines.append(line)
                    if line.strip() == "[extra]":
                        new_lines.append(f"\n# Custom repository: {self.repo_name}")
                        new_lines.append(f"{'#' if not enable else ''}[{self.repo_name}]")
                        new_lines.append(f"{'#' if not enable else ''}Server = {self.repo_server_url}")
                        new_lines.append(f"{'#' if not enable else ''}SigLevel = Optional TrustAll")
                content = '\n'.join(new_lines)
            else:
                # Update existing repository
                lines = content.split('\n')
                new_lines = []
                in_our_section = False
                comment_prefix = "#" if not enable else ""
                
                for line in lines:
                    if line.strip().startswith(f"[{self.repo_name}]"):
                        new_lines.append(f"{comment_prefix}[{self.repo_name}]")
                        in_our_section = True
                    elif in_our_section:
                        if line.strip().startswith('[') or line.strip() == '':
                            in_our_section = False
                            new_lines.append(line)
                        else:
                            new_lines.append(f"{comment_prefix}{line}")
                    else:
                        new_lines.append(line)
                
                content = '\n'.join(new_lines)
            
            # Write back with root permissions
            subprocess.run(['sudo', 'tee', str(pacman_conf)], input=content.encode(), check=True)
            
            action = "enabled" if enable else "disabled"
            logger.info(f"Repository '{self.repo_name}' {action} in pacman.conf")
            
        except Exception as e:
            logger.error(f"Failed to modify pacman.conf: {e}")
            # Don't exit, just continue
    
    def test_ssh_connection(self):
        """Test SSH connection to VPS."""
        print("\n🔍 Testing SSH connection to VPS...")
        
        ssh_test_cmd = [
            "ssh",
            *self.ssh_options,
            "-i", "/home/builder/.ssh/id_ed25519",
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]
        
        result = subprocess.run(ssh_test_cmd, capture_output=True, text=True, check=False)
        if result and result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout:
            print("✅ SSH connection successful")
            return True
        else:
            print(f"⚠️ SSH connection failed: {result.stderr[:100] if result and result.stderr else 'No output'}")
            return False
    
    def fetch_remote_packages(self):
        """Fetch list of packages from server and determine repository state."""
        print("\n📡 Fetching remote package list...")
        
        try:
            ssh_cmd = [
                "ssh",
                *self.ssh_options,
                "-i", "/home/builder/.ssh/id_ed25519",
                f"{self.vps_user}@{self.vps_host}"
            ]
            
            # First check if remote directory exists
            test_cmd = ssh_cmd + [f"test -d {self.remote_dir} && echo 'EXISTS' || echo 'NOT_EXISTS'"]
            test_result = subprocess.run(test_cmd, capture_output=True, text=True, check=False)
            
            if test_result.returncode == 0 and "EXISTS" in test_result.stdout:
                self.repo_exists = True
                
                # Now list package files
                list_cmd = ssh_cmd + [f'find {self.remote_dir} -name "*.pkg.tar.*" -type f 2>/dev/null | head -50']
                list_result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
                
                if list_result and list_result.returncode == 0 and list_result.stdout.strip():
                    lines = [f.strip() for f in list_result.stdout.split('\n') if f.strip()]
                    self.remote_files = [os.path.basename(f) for f in lines]
                    
                    if self.remote_files:
                        logger.info(f"Found {len(self.remote_files)} packages on server")
                        self.repo_has_packages = True
                    else:
                        logger.info("Repository exists but has no packages")
                        self.repo_has_packages = False
                else:
                    self.remote_files = []
                    self.repo_has_packages = False
                    logger.info("Repository exists but could not list packages")
            else:
                self.repo_exists = False
                self.repo_has_packages = False
                self.remote_files = []
                logger.info("Repository directory does not exist on server")
                
        except Exception as e:
            self.repo_exists = False
            self.repo_has_packages = False
            self.remote_files = []
            logger.info(f"Error checking repository: {str(e)[:100]}")
    
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
    
    def get_package_lists(self):
        """Get package lists from packages.py or use defaults."""
        if HAS_CONFIG_FILES and hasattr(packages, 'LOCAL_PACKAGES') and hasattr(packages, 'AUR_PACKAGES'):
            print("📦 Using package lists from packages.py")
            return packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
        else:
            print("⚠️ Using default package lists (packages.py not found or incomplete)")
            return [], []
    
    def build_packages(self):
        """Build packages."""
        print("\n" + "="*60)
        print("Building packages")
        print("="*60)
        
        local_packages, aur_packages = self.get_package_lists()
        
        print(f"📦 Package statistics:")
        print(f"   Local packages: {len(local_packages)}")
        print(f"   AUR packages: {len(aur_packages)}")
        print(f"   Total packages: {len(local_packages) + len(aur_packages)}")
        
        print(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if self._build_single_package(pkg, is_aur=True):
                self.stats["aur_success"] += 1
            else:
                self.stats["aur_failed"] += 1
        
        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self._build_single_package(pkg, is_aur=False):
                self.stats["local_success"] += 1
            else:
                self.stats["local_failed"] += 1
        
        return self.stats["aur_success"] + self.stats["local_success"]
    
    def _build_single_package(self, pkg_name, is_aur):
        """Build a single package."""
        print(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")
        
        if is_aur:
            return self._build_aur_package(pkg_name)
        else:
            return self._build_local_package(pkg_name)
    
    def _build_aur_package(self, pkg_name):
        """Build AUR package."""
        aur_dir = self.repo_root / "build_aur"
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)
        
        print(f"Cloning {pkg_name} from AUR...")
        
        # Try different AUR URLs
        aur_urls = [
            f"https://aur.archlinux.org/{pkg_name}.git",
            f"git://aur.archlinux.org/{pkg_name}.git",
        ]
        
        clone_success = False
        for aur_url in aur_urls:
            logger.info(f"Trying AUR URL: {aur_url}")
            result = self.run_cmd(
                f"git clone --depth 1 {aur_url} {pkg_dir}",
                check=False
            )
            if result and result.returncode == 0:
                clone_success = True
                logger.info(f"Successfully cloned {pkg_name} from {aur_url}")
                break
            else:
                if pkg_dir.exists():
                    shutil.rmtree(pkg_dir, ignore_errors=True)
                logger.warning(f"Failed to clone from {aur_url}: {result.stderr[:100] if result and result.stderr else 'Unknown error'}")
        
        if not clone_success:
            logger.error(f"Failed to clone {pkg_name} from any AUR URL")
            # Try one more time with a different approach
            logger.info("Trying alternative cloning method...")
            try:
                # Use wget to download the AUR package as tar.gz
                aur_tar_url = f"https://aur.archlinux.org/cgit/aur.git/snapshot/{pkg_name}.tar.gz"
                tar_file = aur_dir / f"{pkg_name}.tar.gz"
                
                result = self.run_cmd(f"wget -q -O {tar_file} {aur_tar_url}", check=False)
                if result and result.returncode == 0:
                    # Extract the tar.gz
                    self.run_cmd(f"mkdir -p {pkg_dir}", check=False)
                    self.run_cmd(f"tar -xzf {tar_file} -C {aur_dir}", check=False)
                    # Move contents to pkg_dir
                    extracted_dir = aur_dir / pkg_name
                    if extracted_dir.exists() and extracted_dir != pkg_dir:
                        if pkg_dir.exists():
                            shutil.rmtree(pkg_dir)
                        shutil.move(str(extracted_dir), str(pkg_dir))
                    clone_success = True
                    logger.info(f"Successfully downloaded and extracted {pkg_name}")
            except Exception as e:
                logger.error(f"Alternative method also failed: {e}")
        
        if not clone_success:
            logger.error(f"⚠️ Skipping {pkg_name} - cannot clone from AUR")
            return False
        
        # Set correct permissions
        self.run_cmd(f"chown -R builder:builder {pkg_dir}", check=False)
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
        
        content = pkgbuild.read_text()
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        if pkgver_match and pkgrel_match:
            version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
            
            if self.package_exists(pkg_name):
                logger.info(f"✅ {pkg_name} already exists on server - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            remote_version = self.get_remote_version(pkg_name)
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
        else:
            version = "unknown"
            logger.warning(f"Could not extract version for {pkg_name}")
        
        if pkg_name in self.special_dependencies:
            logger.info(f"Found special dependencies for {pkg_name}: {self.special_dependencies[pkg_name]}")
            for dep in self.special_dependencies[pkg_name]:
                logger.info(f"Installing special dependency: {dep}")
                self.run_cmd(f"pacman -S --needed --noconfirm {dep}", check=False)
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm",
                                        cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}: {source_result.stderr[:200]}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            self._install_aur_deps(pkg_dir, pkg_name)
            
            print("Building package...")
            build_result = self.run_cmd(
                f"makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            if build_result.returncode == 0:
                moved = False
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                logger.error(f"Failed to build {pkg_name}: {build_result.stderr[:500]}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
    
    def _install_aur_deps(self, pkg_dir, pkg_name):
        """Install dependencies for AUR package using .SRCINFO file."""
        print(f"Checking dependencies for {pkg_name}...")
        
        if pkg_name in self.special_dependencies:
            for dep in self.special_dependencies[pkg_name]:
                logger.info(f"Installing special dependency: {dep}")
                self.run_cmd(f"pacman -S --needed --noconfirm {dep}", check=False)
        
        # Generate .SRCINFO file
        srcinfo_result = self.run_cmd("makepkg --printsrcinfo", cwd=pkg_dir, check=False)
        
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            logger.warning(f"No .SRCINFO for {pkg_name}, trying to parse PKGBUILD directly")
            self._parse_pkgbuild_deps(pkg_dir, pkg_name)
            return
        
        deps = []
        makedeps = []
        checkdeps = []
        
        with open(srcinfo, 'r') as f:
            current_section = None
            for line in f:
                line = line.strip()
                if line.startswith('pkgbase =') or line.startswith('pkgname ='):
                    # Skip these lines
                    continue
                elif line.startswith('pkgdesc =') or line.startswith('url ='):
                    # Skip these too
                    continue
                elif line.startswith('depends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        deps.append(dep)
                elif line.startswith('makedepends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        makedeps.append(dep)
                elif line.startswith('checkdepends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        checkdeps.append(dep)
        
        all_deps = deps + makedeps + checkdeps
        
        if not all_deps:
            logger.info(f"No dependencies for {pkg_name}")
            return
        
        logger.info(f"Found {len(all_deps)} dependencies: {', '.join(all_deps[:5])}{'...' if len(all_deps) > 5 else ''}")
        
        logger.info("Refreshing pacman database...")
        self.run_cmd("pacman -Sy --noconfirm", check=False)
        
        installed_count = 0
        for dep in all_deps:
            # Clean dependency name (remove version constraints)
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            
            if not dep_clean:
                continue
            
            # Skip special variables
            if any(x in dep_clean for x in ['$', '{', '}', '(', ')']):
                logger.debug(f"Skipping variable dependency: {dep_clean}")
                continue
            
            # Check if already installed
            check_result = self.run_cmd(f"pacman -Qi {dep_clean} >/dev/null 2>&1", check=False)
            if check_result.returncode == 0:
                logger.debug(f"Dependency already installed: {dep_clean}")
                installed_count += 1
                continue
            
            # Try pacman first
            print(f"Installing {dep_clean} via pacman...")
            result = self.run_cmd(f"sudo pacman -S --needed --noconfirm {dep_clean}", check=False, capture=True)
            
            if result.returncode != 0:
                logger.info(f"Trying yay for {dep_clean}...")
                yay_result = self.run_cmd(f"yay -S --aur --asdeps --needed --noconfirm {dep_clean}",
                                         check=False, capture=True)
                if yay_result.returncode == 0:
                    installed_count += 1
                else:
                    logger.warning(f"Failed to install dependency: {dep_clean}")
            else:
                installed_count += 1
        
        logger.info(f"Installed {installed_count}/{len(all_deps)} dependencies")
    
    def _parse_pkgbuild_deps(self, pkg_dir, pkg_name):
        """Parse dependencies directly from PKGBUILD when .SRCINFO is not available."""
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            # Simple parsing for depends and makedepends arrays
            # This is a basic parser and might not handle all edge cases
            deps = []
            
            # Look for depends=(
            dep_match = re.search(r'depends\s*=\s*\((.*?)\)', content, re.DOTALL)
            if dep_match:
                dep_content = dep_match.group(1)
                # Split by lines and clean
                for line in dep_content.split('\n'):
                    line = line.strip().strip("'\"")
                    if line and not line.startswith('#') and not any(x in line for x in ['$', '{', '}']):
                        deps.append(line)
            
            # Look for makedepends=(
            makedep_match = re.search(r'makedepends\s*=\s*\((.*?)\)', content, re.DOTALL)
            if makedep_match:
                makedep_content = makedep_match.group(1)
                for line in makedep_content.split('\n'):
                    line = line.strip().strip("'\"")
                    if line and not line.startswith('#') and not any(x in line for x in ['$', '{', '}']):
                        deps.append(line)
            
            if not deps:
                logger.info(f"No dependencies found in PKGBUILD for {pkg_name}")
                return
            
            logger.info(f"Found {len(deps)} dependencies from PKGBUILD: {', '.join(deps[:5])}{'...' if len(deps) > 5 else ''}")
            
            logger.info("Refreshing pacman database...")
            self.run_cmd("pacman -Sy --noconfirm", check=False)
            
            installed_count = 0
            for dep in deps:
                # Clean dependency name
                dep_clean = re.sub(r'[<=>].*', '', dep).strip()
                
                if not dep_clean:
                    continue
                
                # Check if already installed
                check_result = self.run_cmd(f"pacman -Qi {dep_clean} >/dev/null 2>&1", check=False)
                if check_result.returncode == 0:
                    logger.debug(f"Dependency already installed: {dep_clean}")
                    installed_count += 1
                    continue
                
                # Try pacman first
                print(f"Installing {dep_clean} via pacman...")
                result = self.run_cmd(f"sudo pacman -S --needed --noconfirm {dep_clean}", check=False, capture=True)
                
                if result.returncode != 0:
                    logger.info(f"Trying yay for {dep_clean}...")
                    yay_result = self.run_cmd(f"yay -S --aur --asdeps --needed --noconfirm {dep_clean}",
                                             check=False, capture=True)
                    if yay_result.returncode == 0:
                        installed_count += 1
                    else:
                        logger.warning(f"Failed to install dependency: {dep_clean}")
                else:
                    installed_count += 1
            
            logger.info(f"Installed {installed_count}/{len(deps)} dependencies")
            
        except Exception as e:
            logger.error(f"Failed to parse PKGBUILD for dependencies: {e}")
    
    def _extract_package_metadata(self, pkg_file_path):
        """Extract metadata from built package file for hokibot observation."""
        try:
            filename = os.path.basename(pkg_file_path)
            base_name = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base_name.split('-')
            
            arch = parts[-1]
            pkgrel = parts[-2]
            version_part = parts[-3]
            
            version_index = len(parts) - 3
            pkgname = '-'.join(parts[:version_index])
            
            epoch = None
            pkgver = version_part
            if ':' in version_part:
                epoch_part, pkgver = version_part.split(':', 1)
                epoch = epoch_part
            
            return {
                'filename': filename,
                'pkgname': pkgname,
                'pkgver': pkgver,
                'pkgrel': pkgrel,
                'epoch': epoch,
                'built_version': f"{epoch + ':' if epoch else ''}{pkgver}-{pkgrel}"
            }
        except Exception as e:
            logger.warning(f"Could not extract metadata from {pkg_file_path}: {e}")
            return None
    
    def _build_local_package(self, pkg_name):
        """Build local package - simpler version without builder user."""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        content = pkgbuild.read_text()
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        epoch_match = re.search(r'^epoch\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        if pkgver_match and pkgrel_match:
            version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
            
            if self.package_exists(pkg_name):
                logger.info(f"✅ {pkg_name} already exists on server - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                return False
            
            remote_version = self.get_remote_version(pkg_name)
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
        else:
            version = "unknown"
            logger.warning(f"Could not extract version for {pkg_name}")
        
        if pkg_name in self.special_dependencies:
            logger.info(f"Found special dependencies for {pkg_name}")
            for dep in self.special_dependencies[pkg_name]:
                logger.info(f"Installing special dependency: {dep}")
                self.run_cmd(f"pacman -S --needed --noconfirm {dep}", check=False)
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm",
                                        cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}: {source_result.stderr[:200]}")
                return False
            
            # Install dependencies
            self._install_local_deps(pkg_dir, pkg_name)
            
            print("Building package...")
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                logger.info("GTK2: Skipping check step (long)")
            
            build_result = self.run_cmd(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            if build_result.returncode == 0:
                moved = False
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                    built_files.append(str(dest))
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    self.rebuilt_local_packages.append(pkg_name)
                    
                    if built_files:
                        metadata = self._extract_package_metadata(built_files[0])
                        if metadata:
                            self.hokibot_data.append({
                                'name': pkg_name,
                                'built_version': metadata['built_version'],
                                'pkgver': metadata['pkgver'],
                                'pkgrel': metadata['pkgrel'],
                                'epoch': metadata['epoch']
                            })
                            logger.info(f"📝 HOKIBOT observed: {pkg_name} -> {metadata['built_version']}")
                    
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
    
    def _install_local_deps(self, pkg_dir, pkg_name):
        """Install dependencies for local package using .SRCINFO file."""
        print(f"Checking dependencies for {pkg_name}...")
        
        # First try to generate .SRCINFO
        srcinfo_result = self.run_cmd("makepkg --printsrcinfo", cwd=pkg_dir, check=False)
        
        srcinfo = pkg_dir / ".SRCINFO"
        if srcinfo.exists():
            # Use .SRCINFO parsing (same as AUR)
            self._install_aur_deps(pkg_dir, pkg_name)
            return
        
        # Fall back to PKGBUILD parsing
        self._parse_pkgbuild_deps(pkg_dir, pkg_name)
    
    def update_database(self):
        """Update repository database."""
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not pkg_files:
            logger.info("No packages to add to database")
            return False
        
        logger.info(f"Updating database with {len(pkg_files)} packages...")
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz",
                      f"{self.repo_name}.files", f"{self.repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            logger.info("Creating new database...")
            cmd = ["repo-add", db_file] + [os.path.basename(str(p)) for p in pkg_files]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                created_files = [
                    f"{self.repo_name}.db",
                    f"{self.repo_name}.db.tar.gz",
                    f"{self.repo_name}.files",
                    f"{self.repo_name}.files.tar.gz"
                ]
                
                for f in created_files:
                    if os.path.exists(f):
                        size = os.path.getsize(f)
                        logger.info(f"  {f}: {size} bytes")
                    else:
                        logger.error(f"  {f}: NOT CREATED")
                
                logger.info("✅ Database created successfully")
                return True
            else:
                logger.error(f"repo-add failed: {result.stderr}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def upload_packages(self):
        """Upload packages to server using SCP."""
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
        
        all_files = pkg_files + db_files
        
        if not all_files:
            logger.warning("No files to upload")
            return False
        
        logger.info(f"Uploading {len(all_files)} files...")
        
        # Create remote directory if it doesn't exist
        mkdir_cmd = [
            "ssh",
            *self.ssh_options,
            "-i", "/home/builder/.ssh/id_ed25519",
            f"{self.vps_user}@{self.vps_host}",
            f"mkdir -p {self.remote_dir}"
        ]
        
        mkdir_result = subprocess.run(mkdir_cmd, capture_output=True, text=True, check=False)
        if mkdir_result.returncode != 0:
            logger.warning(f"Failed to create remote directory: {mkdir_result.stderr[:200]}")
        
        # Upload files
        scp_cmd = [
            "scp",
            *self.ssh_options,
            "-i", "/home/builder/.ssh/id_ed25519",
            *[str(f) for f in all_files],
            f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/"
        ]
        
        result = subprocess.run(scp_cmd, capture_output=True, text=True, check=False)
        
        if result.returncode == 0:
            logger.info("✅ Upload successful!")
            return True
        else:
            logger.error(f"Upload failed: {result.stderr[:200]}")
            return False
    
    def cleanup_old_packages(self):
        """Remove old package versions."""
        if not self.packages_to_clean:
            logger.info("No packages to clean up")
            return
        
        logger.info(f"Cleaning up old versions for {len(self.packages_to_clean)} packages...")
        
        cleaned = 0
        for pkg in self.packages_to_clean:
            remote_cmd = f'cd {self.remote_dir} && ls -t {pkg}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | xargs -r rm -f 2>/dev/null || true'
            
            ssh_cmd = [
                "ssh",
                *self.ssh_options,
                "-i", "/home/builder/.ssh/id_ed25519",
                f"{self.vps_user}@{self.vps_host}",
                remote_cmd
            ]
            
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
            if result and result.returncode == 0:
                cleaned += 1
        
        logger.info(f"✅ Cleanup complete ({cleaned} packages)")
    
    def _update_pkgbuild_in_clone(self, clone_dir, pkg_data):
        """Update a single PKGBUILD in the git clone based on observed data."""
        pkg_dir = clone_dir / pkg_data['name']
        pkgbuild_path = pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            logger.warning(f"PKGBUILD not found in clone for {pkg_data['name']}")
            return False
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            changed = False
            
            current_pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if current_pkgver_match:
                current_pkgver = current_pkgver_match.group(1)
                if current_pkgver != pkg_data['pkgver']:
                    content = re.sub(
                        r'^pkgver\s*=\s*["\']?[^"\'\n]+',
                        f"pkgver={pkg_data['pkgver']}",
                        content,
                        flags=re.MULTILINE
                    )
                    changed = True
                    logger.info(f"  Updated pkgver: {current_pkgver} -> {pkg_data['pkgver']}")
            
            current_pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if current_pkgrel_match:
                current_pkgrel = current_pkgrel_match.group(1)
                if current_pkgrel != pkg_data['pkgrel']:
                    content = re.sub(
                        r'^pkgrel\s*=\s*["\']?[^"\'\n]+',
                        f"pkgrel={pkg_data['pkgrel']}",
                        content,
                        flags=re.MULTILINE
                    )
                    changed = True
                    logger.info(f"  Updated pkgrel: {current_pkgrel} -> {pkg_data['pkgrel']}")
            
            current_epoch_match = re.search(r'^epoch\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if pkg_data['epoch'] is not None:
                if current_epoch_match:
                    current_epoch = current_epoch_match.group(1)
                    if current_epoch != pkg_data['epoch']:
                        content = re.sub(
                            r'^epoch\s*=\s*["\']?[^"\'\n]+',
                            f"epoch={pkg_data['epoch']}",
                            content,
                            flags=re.MULTILINE
                        )
                        changed = True
                        logger.info(f"  Updated epoch: {current_epoch} -> {pkg_data['epoch']}")
                else:
                    lines = content.split('\n')
                    new_lines = []
                    epoch_added = False
                    for line in lines:
                        new_lines.append(line)
                        if not epoch_added and line.strip().startswith('pkgver='):
                            new_lines.append(f'epoch={pkg_data["epoch"]}')
                            epoch_added = True
                            changed = True
                            logger.info(f"  Added epoch: {pkg_data['epoch']}")
                    content = '\n'.join(new_lines)
            else:
                if current_epoch_match:
                    content = re.sub(r'^epoch\s*=\s*["\']?[^"\'\n]+\n?', '', content, flags=re.MULTILINE)
                    changed = True
                    logger.info(f"  Removed epoch: {current_epoch_match.group(1)}")
            
            if changed:
                with open(pkgbuild_path, 'w') as f:
                    f.write(content)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update PKGBUILD for {pkg_data['name']} in clone: {e}")
            return False
    
    def _synchronize_pkgbuilds(self):
        """PHASE 2: Isolated PKGBUILD synchronization."""
        if not self.hokibot_data:
            logger.info("No local packages were rebuilt - skipping PKGBUILD synchronization")
            return
        
        print("\n" + "="*60)
        print("🔄 PHASE 2: Isolated PKGBUILD Synchronization")
        print("="*60)
        
        clone_dir = Path("/tmp/manjaro-awesome-gitclone")
        
        try:
            if clone_dir.exists():
                shutil.rmtree(clone_dir)
            
            clone_dir.mkdir(parents=True, exist_ok=True)
            
            github_ssh_key = os.getenv('CI_PUSH_SSH_KEY')
            if not github_ssh_key:
                logger.warning("CI_PUSH_SSH_KEY not set in environment - skipping PKGBUILD sync")
                return
            
            # Use GITHUB_TOKEN for authentication instead of SSH key
            repo_url = f"https://x-access-token:{github_ssh_key}@github.com/megvadulthangya/manjaro-awesome.git"
            
            print(f"📥 Cloning repository to {clone_dir}...")
            clone_result = subprocess.run(
                ['git', 'clone', repo_url, str(clone_dir)],
                capture_output=True,
                text=True
            )
            
            if clone_result.returncode != 0:
                logger.error(f"Failed to clone repository: {clone_result.stderr}")
                return
            
            subprocess.run(
                ['git', 'config', 'user.name', 'GitHub Actions Builder'],
                cwd=clone_dir,
                capture_output=True
            )
            subprocess.run(
                ['git', 'config', 'user.email', 'builder@github-actions.local'],
                cwd=clone_dir,
                capture_output=True
            )
            
            modified_packages = []
            for pkg_data in self.hokibot_data:
                print(f"\n📝 Processing {pkg_data['name']}...")
                print(f"   Observed version: {pkg_data['built_version']}")
                
                if self._update_pkgbuild_in_clone(clone_dir, pkg_data):
                    modified_packages.append(pkg_data['name'])
            
            if not modified_packages:
                print("\n✅ No PKGBUILDs needed updates")
                return
            
            print(f"\n📝 Committing changes for {len(modified_packages)} package(s)...")
            
            for pkg_name in modified_packages:
                pkgbuild_path = clone_dir / pkg_name / "PKGBUILD"
                if pkgbuild_path.exists():
                    subprocess.run(
                        ['git', 'add', str(pkgbuild_path.relative_to(clone_dir))],
                        cwd=clone_dir,
                        capture_output=True
                    )
            
            commit_msg = f"chore: synchronize PKGBUILDs with built versions\n\n"
            commit_msg += f"Updated {len(modified_packages)} rebuilt local package(s):\n"
            for pkg_name in modified_packages:
                for pkg_data in self.hokibot_data:
                    if pkg_data['name'] == pkg_name:
                        commit_msg += f"- {pkg_name}: {pkg_data['built_version']}\n"
                        break
            
            commit_result = subprocess.run(
                ['git', 'commit', '-m', commit_msg],
                cwd=clone_dir,
                capture_output=True,
                text=True
            )
            
            if commit_result.returncode == 0:
                print("✅ Changes committed")
                
                print("\n📤 Pushing changes to main branch...")
                push_result = subprocess.run(
                    ['git', 'push', 'origin', 'main'],
                    cwd=clone_dir,
                    capture_output=True,
                    text=True
                )
                
                if push_result.returncode == 0:
                    print("✅ Changes pushed to main branch")
                else:
                    logger.error(f"Failed to push changes: {push_result.stderr}")
            else:
                logger.warning(f"Commit failed or no changes: {commit_result.stderr}")
            
        except Exception as e:
            logger.error(f"Error during PKGBUILD synchronization: {e}")
            import traceback
            traceback.print_exc()
    
    def run(self):
        """Main execution."""
        print("\n" + "="*60)
        print("🚀 MANJARO PACKAGE BUILDER")
        print("="*60)
        
        try:
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Using repository: {self.repo_name}")
            print(f"Output directory: {self.output_dir}")
            print(f"Special dependencies loaded: {len(self.special_dependencies)}")
            
            # First, check and configure repository
            self.fetch_remote_packages()
            
            # Enable repository if it has packages, disable if empty
            if self.repo_has_packages:
                print(f"📦 Repository has packages - enabling in pacman.conf")
                self._manage_repository_state(enable=True)
            else:
                print(f"📭 Repository empty or doesn't exist - disabling in pacman.conf")
                self._manage_repository_state(enable=False)
            
            total_built = self.build_packages()
            
            if total_built > 0:
                print("\n" + "="*60)
                print("📦 Finalizing build")
                print("="*60)
                
                if self.update_database():
                    if self.test_ssh_connection():
                        if self.upload_packages():
                            self.cleanup_old_packages()
                            self._synchronize_pkgbuilds()
                            print("\n✅ Build completed successfully!")
                        else:
                            print("\n❌ Upload failed!")
                    else:
                        print("\n⚠️ SSH connection failed, trying upload anyway...")
                        if self.upload_packages():
                            self.cleanup_old_packages()
                            self._synchronize_pkgbuilds()
                            print("\n✅ Build completed despite connection issues!")
                        else:
                            print("\n❌ Upload failed completely!")
                else:
                    print("\n❌ Database update failed!")
            else:
                print("\n📊 Build summary:")
                print(f"   AUR packages built: {self.stats['aur_success']}")
                print(f"   AUR packages failed: {self.stats['aur_failed']}")
                print(f"   Local packages built: {self.stats['local_success']}")
                print(f"   Local packages failed: {self.stats['local_failed']}")
                print(f"   Total skipped: {len(self.skipped_packages)}")
                
                if self.stats['aur_failed'] > 0 or self.stats['local_failed'] > 0:
                    print("⚠️ Some packages failed to build")
                else:
                    print("✅ All packages are up to date or built successfully!")
            
            elapsed = time.time() - self.stats["start_time"]
            
            print("\n" + "="*60)
            print("📊 BUILD SUMMARY")
            print("="*60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {self.stats['aur_success']} (failed: {self.stats['aur_failed']})")
            print(f"Local packages:  {self.stats['local_success']} (failed: {self.stats['local_failed']})")
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
