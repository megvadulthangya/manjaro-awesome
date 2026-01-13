#!/usr/bin/env python3
"""
Manjaro Package Builder - Production Version
Repository lifecycle and dependency resolution strictly enforced.
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
        # Get the repository root
        self.repo_root = self._get_repo_root()
        
        # Load configuration
        self._load_config()
        
        # Setup directories
        self.output_dir = self.repo_root / getattr(config, 'OUTPUT_DIR', 'built_packages') if HAS_CONFIG_FILES else self.repo_root / "built_packages"
        self.build_tracking_dir = self.repo_root / getattr(config, 'BUILD_TRACKING_DIR', '.build_tracking') if HAS_CONFIG_FILES else self.repo_root / ".build_tracking"
        
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # State
        self.remote_files = []
        self.packages_to_clean = set()
        self.built_packages = []
        self.skipped_packages = []
        self.rebuilt_local_packages = []
        
        # Repository state
        self.repo_has_packages_pacman = None  # From pacman -Sl
        self.repo_has_packages_ssh = None     # From SSH find
        self.repo_final_state = None          # Final decision
        
        # SSH options
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
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                logger.info(f"Using GITHUB_WORKSPACE: {workspace_path}")
                return workspace_path
        
        container_workspace = Path('/__w/manjaro-awesome/manjaro-awesome')
        if container_workspace.exists():
            logger.info(f"Using container workspace: {container_workspace}")
            return container_workspace
        
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
        
        env_repo_name = os.getenv('REPO_NAME')
        if HAS_CONFIG_FILES:
            config_repo_name = getattr(config, 'REPO_DB_NAME', 'manjaro-awesome')
            self.repo_name = env_repo_name if env_repo_name else config_repo_name
        else:
            self.repo_name = env_repo_name if env_repo_name else 'manjaro-awesome'
        
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
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, log_cmd=True):
        """Run command with comprehensive logging as required."""
        if log_cmd:
            logger.info(f"RUNNING COMMAND: {cmd}")
        
        if cwd is None:
            cwd = self.repo_root
        
        if user:
            env = os.environ.copy()
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            
            try:
                sudo_cmd = ['sudo', '-u', user]
                if shell:
                    sudo_cmd.extend(['bash', '-c', f'cd "{cwd}" && {cmd}'])
                else:
                    sudo_cmd.extend(cmd)
                
                result = subprocess.run(
                    sudo_cmd,
                    capture_output=capture,
                    text=True,
                    check=check,
                    env=env
                )
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                    logger.info(f"EXIT CODE: {result.returncode}")
                return result
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
                    if e.stdout:
                        logger.error(f"STDOUT: {e.stdout[:500]}")
                    if e.stderr:
                        logger.error(f"STDERR: {e.stderr[:500]}")
                    logger.error(f"EXIT CODE: {e.returncode}")
                if check:
                    raise
                return e
        else:
            try:
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    shell=shell,
                    capture_output=capture,
                    text=True,
                    check=check
                )
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                    logger.info(f"EXIT CODE: {result.returncode}")
                return result
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
                    if e.stdout:
                        logger.error(f"STDOUT: {e.stdout[:500]}")
                    if e.stderr:
                        logger.error(f"STDERR: {e.stderr[:500]}")
                    logger.error(f"EXIT CODE: {e.returncode}")
                if check:
                    raise
                return e
    
    def _enable_repository_by_default(self):
        """HARD CONSTRAINT: Repository must be enabled by default."""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found")
            return False
        
        try:
            with open(pacman_conf, 'r') as f:
                content = f.read()
            
            repo_section = f"[{self.repo_name}]"
            
            logger.info("PACMAN.CONF BEFORE MODIFICATION:")
            for line in content.split('\n'):
                if repo_section in line or f"#{repo_section}" in line:
                    print(f"   {line}")
            
            if repo_section not in content and f"#{repo_section}" not in content:
                logger.info(f"Adding repository {self.repo_name} to pacman.conf")
                lines = content.split('\n')
                new_lines = []
                added = False
                for line in lines:
                    new_lines.append(line)
                    if line.strip() == "[extra]" and not added:
                        new_lines.append(f"\n# Custom repository: {self.repo_name}")
                        new_lines.append(f"[{self.repo_name}]")
                        new_lines.append(f"Server = {self.repo_server_url}")
                        new_lines.append(f"SigLevel = Optional TrustAll")
                        added = True
                content = '\n'.join(new_lines)
            else:
                logger.info(f"Repository {self.repo_name} already in pacman.conf, ensuring it's enabled")
                lines = content.split('\n')
                new_lines = []
                in_our_section = False
                
                for line in lines:
                    if line.strip() == f"#{repo_section}":
                        new_lines.append(repo_section)
                        in_our_section = True
                    elif line.strip() == repo_section:
                        new_lines.append(line)
                        in_our_section = True
                    elif in_our_section:
                        if line.strip().startswith('[') or line.strip() == '':
                            in_our_section = False
                            new_lines.append(line)
                        elif line.strip().startswith('#'):
                            new_lines.append(line.lstrip('#'))
                        else:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
                
                content = '\n'.join(new_lines)
            
            subprocess.run(['sudo', 'tee', str(pacman_conf)], input=content.encode(), check=True)
            
            logger.info("PACMAN.CONF AFTER MODIFICATION:")
            with open(pacman_conf, 'r') as f:
                new_content = f.read()
            for line in new_content.split('\n'):
                if repo_section in line or f"#{repo_section}" in line:
                    print(f"   {line}")
            
            logger.info(f"✅ Repository '{self.repo_name}' enabled by default in pacman.conf")
            return True
            
        except Exception as e:
            logger.error(f"Failed to enable repository by default: {e}")
            return False
    
    def _sync_pacman_databases(self):
        """STEP 0: Sync pacman databases (REQUIRED)."""
        print("\n" + "="*60)
        print("STEP 0: Syncing pacman databases (sudo pacman -Sy --noconfirm)")
        print("="*60)
        
        cmd = "sudo pacman -Sy --noconfirm"
        result = self.run_cmd(cmd, log_cmd=True)
        
        if result.returncode != 0:
            logger.error("❌ Failed to sync pacman databases - FAIL HARD")
            sys.exit(1)
        
        logger.info("✅ Pacman databases synced successfully")
        return True
    
    def _query_pacman_repository(self):
        """STEP 1: Pacman repository query (PRIMARY SOURCE)."""
        print("\n" + "="*60)
        print(f"STEP 1: Querying pacman repository '{self.repo_name}' (pacman -Sl)")
        print("="*60)
        
        cmd = f"pacman -Sl {self.repo_name}"
        result = self.run_cmd(cmd, log_cmd=True, check=False, shell=True)
        
        if result.returncode == 0:
            if result.stdout.strip():
                lines = [line.strip() for line in result.stdout.split('\n') if line.strip()]
                package_count = len(lines)
                logger.info(f"✅ pacman -Sl returned {package_count} package lines")
                print(f"Sample output: {lines[:3] if lines else 'None'}")
                self.repo_has_packages_pacman = True
                return True
            else:
                logger.info("ℹ️ pacman -Sl returned empty stdout (inconclusive)")
                self.repo_has_packages_pacman = False
                return False
        else:
            logger.warning(f"⚠️ pacman -Sl returned error (not authoritative): {result.stderr[:200]}")
            self.repo_has_packages_pacman = None  # Error state
            return None
    
    def _verify_repository_via_ssh(self):
        """STEP 2: SSH filesystem verification (SECONDARY, REQUIRED)."""
        print("\n" + "="*60)
        print("STEP 2: Verifying repository via SSH (find *.pkg.tar.zst files)")
        print("="*60)
        
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found at {ssh_key_path}")
            self.repo_has_packages_ssh = False
            return False
        
        ssh_cmd = [
            "ssh",
            *self.ssh_options,
            "-i", ssh_key_path,
            f"{self.vps_user}@{self.vps_host}",
            f"find {self.remote_dir} -maxdepth 1 -type f -name '*.pkg.tar.zst' 2>/dev/null"
        ]
        
        logger.info(f"RUNNING SSH COMMAND: {' '.join(ssh_cmd)}")
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.stdout:
                logger.info(f"STDOUT: {result.stdout[:1000]}")
            if result.stderr:
                logger.info(f"STDERR: {result.stderr[:500]}")
            
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
                file_count = len(files)
                logger.info(f"✅ SSH find returned {file_count} package files")
                if file_count > 0:
                    print(f"Sample files: {files[:5]}")
                    self.repo_has_packages_ssh = True
                    self.remote_files = [os.path.basename(f) for f in files]
                else:
                    self.repo_has_packages_ssh = False
                return True
            else:
                logger.warning(f"⚠️ SSH find returned error: {result.stderr[:200]}")
                self.repo_has_packages_ssh = None
                return False
                
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            self.repo_has_packages_ssh = None
            return False
    
    def _decide_repository_state(self):
        """STEP C: Repository decision matrix (NO DEVIATION)."""
        print("\n" + "="*60)
        print("REPOSITORY DECISION MATRIX")
        print("="*60)
        
        print(f"pacman -Sl result: {self.repo_has_packages_pacman}")
        print(f"SSH find result: {self.repo_has_packages_ssh}")
        
        # Decision matrix
        if self.repo_has_packages_pacman is True:
            # packages | any → ENABLE repo
            logger.info("✅ Decision: ENABLE repository (pacman -Sl shows packages)")
            self.repo_final_state = "ENABLE"
            return "ENABLE"
        
        elif self.repo_has_packages_pacman is None and self.repo_has_packages_ssh is True:
            # error | files → ENABLE repo
            logger.info("✅ Decision: ENABLE repository (SSH find shows files)")
            self.repo_final_state = "ENABLE"
            return "ENABLE"
        
        elif self.repo_has_packages_pacman is False and self.repo_has_packages_ssh is False:
            # empty | empty → DISABLE repo
            logger.info("✅ Decision: DISABLE repository (both checks empty)")
            self.repo_final_state = "DISABLE"
            return "DISABLE"
        
        elif self.repo_has_packages_pacman is None and self.repo_has_packages_ssh is None:
            # error | error → FAIL HARD
            logger.error("❌ Decision: FAIL HARD (both checks errored)")
            sys.exit(1)
        
        else:
            # Default: enable if unsure
            logger.warning("⚠️ Ambiguous state, defaulting to ENABLE")
            self.repo_final_state = "ENABLE"
            return "ENABLE"
    
    def _apply_repository_decision(self, decision):
        """Apply repository enable/disable decision."""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found")
            return
        
        try:
            with open(pacman_conf, 'r') as f:
                content = f.read()
            
            repo_section = f"[{self.repo_name}]"
            lines = content.split('\n')
            new_lines = []
            in_our_section = False
            
            for line in lines:
                if line.strip() == repo_section:
                    if decision == "DISABLE":
                        new_lines.append(f"#{repo_section}")
                    else:
                        new_lines.append(line)
                    in_our_section = True
                elif in_our_section:
                    if line.strip().startswith('[') or line.strip() == '':
                        in_our_section = False
                        new_lines.append(line)
                    else:
                        if decision == "DISABLE":
                            new_lines.append(f"#{line}")
                        else:
                            new_lines.append(line)
                else:
                    new_lines.append(line)
            
            content = '\n'.join(new_lines)
            subprocess.run(['sudo', 'tee', str(pacman_conf)], input=content.encode(), check=True)
            
            action = "enabled" if decision == "ENABLE" else "disabled"
            logger.info(f"✅ Repository '{self.repo_name}' {action} in pacman.conf")
            
        except Exception as e:
            logger.error(f"Failed to apply repository decision: {e}")
    
    def _install_dependencies_strict(self, deps):
        """STRICT dependency resolution: pacman first, then yay."""
        if not deps:
            return True
        
        print(f"\nInstalling {len(deps)} dependencies...")
        logger.info(f"Dependencies to install: {deps}")
        
        # Clean dependency names
        clean_deps = []
        for dep in deps:
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            if dep_clean and not any(x in dep_clean for x in ['$', '{', '}']):
                clean_deps.append(dep_clean)
        
        if not clean_deps:
            return True
        
        # STEP 1: Try system packages FIRST with sudo
        print("STEP 1: Trying pacman (sudo)...")
        deps_str = ' '.join(clean_deps)
        cmd = f"sudo pacman -S --needed --noconfirm {deps_str}"
        result = self.run_cmd(cmd, log_cmd=True, check=False)
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        logger.warning(f"⚠️ pacman failed for some dependencies, trying yay...")
        
        # STEP 2: Fallback to AUR (yay) WITHOUT sudo
        print("STEP 2: Trying yay (without sudo)...")
        cmd = f"yay -S --needed --noconfirm {deps_str}"
        result = self.run_cmd(cmd, log_cmd=True, check=False, user="builder")
        
        if result.returncode == 0:
            logger.info("✅ Dependencies installed via yay")
            return True
        
        # STEP 3: Failure handling - mark as failed but continue
        logger.error(f"❌ Failed to install dependencies: {deps}")
        print(f"Failed dependencies: {deps}")
        return False
    
    def package_exists(self, pkg_name, version=None):
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
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
            # Use defaults from bash script
            LOCAL_PACKAGES = [
                "gghelper",
                "gtk2",
                "awesome-freedesktop-git",
                "lain-git",
                "awesome-rofi",
                "nordic-backgrounds",
                "awesome-copycats-manjaro",
                "i3lock-fancy-git",
                "ttf-font-awesome-5",
                "nvidia-driver-assistant",
                "grayjay-bin"
            ]
            
            AUR_PACKAGES = [
                "libinput-gestures",
                "qt5-styleplugins",
                "urxvt-resize-font-git",
                "i3lock-color",
                "raw-thumbnailer",
                "gsconnect",
                "awesome-git",
                "tilix-git",
                "tamzen-font",
                "betterlockscreen",
                "nordic-theme",
                "nordic-darker-theme",
                "geany-nord-theme",
                "nordzy-icon-theme",
                "nordic-bluish-accent-theme",
                "nordic-bluish-accent-standard-buttons-theme",
                "nordic-polar-standard-buttons-theme",
                "nordic-standard-buttons-theme",
                "nordic-darker-standard-buttons-theme",
                "oh-my-posh-bin",
                "fish-done",
                "find-the-command",
                "p7zip-gui",
                "qownnotes",
                "xorg-font-utils",
                "xnviewmp",
                "simplescreenrecorder",
                "gtkhash-thunar",
                "a4tech-bloody-driver-git"
            ]
            
            return LOCAL_PACKAGES, AUR_PACKAGES
    
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
                logger.warning(f"Failed to clone from {aur_url}")
        
        if not clone_success:
            logger.error(f"Failed to clone {pkg_name} from any AUR URL")
            return False
        
        # Set correct permissions
        self.run_cmd(f"chown -R builder:builder {pkg_dir}", check=False)
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
        
        # Extract version info
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
        
        # Special dependencies from config
        special_deps = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
        if pkg_name in special_deps:
            logger.info(f"Installing special dependencies for {pkg_name}")
            self._install_dependencies_strict(special_deps[pkg_name])
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            # Extract and install dependencies from .SRCINFO
            self._install_aur_deps_from_srcinfo(pkg_dir, pkg_name)
            
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
                logger.error(f"Failed to build {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
    
    def _install_aur_deps_from_srcinfo(self, pkg_dir, pkg_name):
        """Install dependencies for AUR package using .SRCINFO file."""
        print(f"Checking dependencies for {pkg_name}...")
        
        # Generate .SRCINFO file
        srcinfo_result = self.run_cmd("makepkg --printsrcinfo", cwd=pkg_dir, check=False)
        
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            logger.warning(f"No .SRCINFO for {pkg_name}")
            return
        
        deps = []
        makedeps = []
        checkdeps = []
        
        with open(srcinfo, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('depends ='):
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
        
        logger.info(f"Found {len(all_deps)} dependencies")
        self._install_dependencies_strict(all_deps)
    
    def _build_local_package(self, pkg_name):
        """Build local package."""
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
        
        # Special dependencies from config
        special_deps = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
        if pkg_name in special_deps:
            logger.info(f"Installing special dependencies for {pkg_name}")
            self._install_dependencies_strict(special_deps[pkg_name])
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                return False
            
            # Install dependencies from .SRCINFO
            self._install_aur_deps_from_srcinfo(pkg_dir, pkg_name)
            
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
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
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
                logger.error(f"Failed to build {pkg_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            return False
    
    def build_packages(self):
        """Build packages."""
        print("\n" + "="*60)
        print("Building packages")
        print("="*60)
        
        local_packages, aur_packages = self.get_package_lists()
        
        print(f"📦 Package statistics:")
        print(f"   Local packages: {len(local_packages)}")
        print(f"   AUR packages: {len(aur_packages)}")
        
        print(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if self._build_aur_package(pkg):
                self.stats["aur_success"] += 1
            else:
                self.stats["aur_failed"] += 1
        
        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self._build_local_package(pkg):
                self.stats["local_success"] += 1
            else:
                self.stats["local_failed"] += 1
        
        return self.stats["aur_success"] + self.stats["local_success"]
    
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
        
        # Upload files
        scp_cmd = [
            "scp",
            *self.ssh_options,
            "-i", "/home/builder/.ssh/id_ed25519",
            *[str(f) for f in all_files],
            f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/"
        ]
        
        logger.info(f"RUNNING SCP COMMAND: {' '.join(scp_cmd)}")
        result = subprocess.run(scp_cmd, capture_output=True, text=True, check=False)
        
        logger.info(f"EXIT CODE: {result.returncode}")
        if result.stdout:
            logger.info(f"STDOUT: {result.stdout[:500]}")
        if result.stderr:
            logger.info(f"STDERR: {result.stderr[:500]}")
        
        if result.returncode == 0:
            logger.info("✅ Upload successful!")
            return True
        else:
            logger.error(f"Upload failed")
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
    
    def run(self):
        """Main execution."""
        print("\n" + "="*60)
        print("🚀 MANJARO PACKAGE BUILDER (STRICT REPOSITORY HANDLING)")
        print("="*60)
        
        try:
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Repository name: {self.repo_name}")
            
            # HARD CONSTRAINT: Repository must be enabled by default
            self._enable_repository_by_default()
            
            # STEP 0: Sync pacman databases (REQUIRED)
            self._sync_pacman_databases()
            
            # STEP 1: Pacman repository query (PRIMARY SOURCE)
            pacman_result = self._query_pacman_repository()
            
            # STEP 2: SSH filesystem verification (SECONDARY, REQUIRED)
            ssh_result = self._verify_repository_via_ssh()
            
            # STEP C: Repository decision matrix (NO DEVIATION)
            decision = self._decide_repository_state()
            
            # Apply repository decision
            self._apply_repository_decision(decision)
            
            # Only continue if repository is enabled
            if decision == "DISABLE":
                logger.info("Repository disabled, no packages to build")
                return 0
            
            # Build packages
            total_built = self.build_packages()
            
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
