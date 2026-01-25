#!/usr/bin/env python3
"""
Manjaro Package Builder - Refactored Modular Architecture with Zero-Residue Policy
Main orchestrator that coordinates between modules
"""

print(">>> DEBUG: Script started")

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
import glob
import tarfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add the script directory to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Import our modules
try:
    from modules.repo_manager import RepoManager
    from modules.vps_client import VPSClient
    from modules.build_engine import BuildEngine
    from modules.gpg_handler import GPGHandler
    MODULES_LOADED = True
    logger = logging.getLogger(__name__)
    logger.info("✅ All modules imported successfully")
except ImportError as e:
    print(f"❌ CRITICAL: Failed to import modules: {e}")
    print(f"❌ Please ensure modules are in: {script_dir}/modules/")
    MODULES_LOADED = False
    sys.exit(1)
except NameError as e:
    print(f"❌ CRITICAL: NameError in modules: {e}")
    print(f"❌ This indicates missing imports in module files")
    MODULES_LOADED = False
    sys.exit(1)

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
    """Main orchestrator that coordinates between modules"""
    
    def __init__(self):
        # Run pre-flight environment validation
        self._validate_env()
        
        # Get the repository root
        self.repo_root = self._get_repo_root()
        
        # Load configuration
        self._load_config()
        
        # Setup directories from config
        self.output_dir = self.repo_root / (getattr(config, 'OUTPUT_DIR', 'built_packages') if HAS_CONFIG_FILES else "built_packages")
        self.build_tracking_dir = self.repo_root / (getattr(config, 'BUILD_TRACKING_DIR', '.build_tracking') if HAS_CONFIG_FILES else ".build_tracking")
        
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # Load configuration values from config.py
        self.mirror_temp_dir = Path(getattr(config, 'MIRROR_TEMP_DIR', '/tmp/repo_mirror') if HAS_CONFIG_FILES else "/tmp/repo_mirror")
        self.sync_clone_dir = Path(getattr(config, 'SYNC_CLONE_DIR', '/tmp/manjaro-awesome-gitclone') if HAS_CONFIG_FILES else "/tmp/manjaro-awesome-gitclone")
        self.aur_urls = getattr(config, 'AUR_URLS', ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]) if HAS_CONFIG_FILES else ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]
        self.aur_build_dir = self.repo_root / (getattr(config, 'AUR_BUILD_DIR', 'build_aur') if HAS_CONFIG_FILES else "build_aur")
        self.ssh_options = getattr(config, 'SSH_OPTIONS', ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]) if HAS_CONFIG_FILES else ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]
        self.github_repo = os.getenv('GITHUB_REPO', getattr(config, 'GITHUB_REPO', 'megvadulthangya/manjaro-awesome.git') if HAS_CONFIG_FILES else 'megvadulthangya/manjaro-awesome.git')
        
        # Get PACKAGER_ID from config
        self.packager_id = getattr(config, 'PACKAGER_ID', 'Maintainer <no-reply@gshoots.hu>') if HAS_CONFIG_FILES else 'Maintainer <no-reply@gshoots.hu>'
        logger.info(f"🔧 PACKAGER_ID configured: {self.packager_id}")
        
        # Initialize modules
        self._init_modules()
        
        # State
        self.remote_files = []
        self.built_packages = []
        self.skipped_packages = []
        self.rebuilt_local_packages = []
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
        }

    def _validate_env(self) -> None:
        """Comprehensive pre-flight environment validation - check for all required variables"""
        print("\n" + "=" * 60)
        print("PRE-FLIGHT ENVIRONMENT VALIDATION")
        print("=" * 60)
        
        required_vars = [
            'REPO_NAME',
            'VPS_HOST',
            'VPS_USER',
            'VPS_SSH_KEY',
            'REMOTE_DIR',
        ]
        
        optional_but_recommended = [
            'REPO_SERVER_URL',
            'GPG_KEY_ID',
            'GPG_PRIVATE_KEY',
            'PACKAGER_ENV',
        ]
        
        # Check required variables
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value or value.strip() == '':
                missing_vars.append(var)
                logger.error(f"[ERROR] Variable {var} is empty! Ensure it is set in GitHub Secrets.")
        
        if missing_vars:
            sys.exit(1)
        
        # Check optional variables and warn if missing
        for var in optional_but_recommended:
            value = os.getenv(var)
            if not value or value.strip() == '':
                logger.warning(f"⚠️ Optional variable {var} is empty")
        
        # ✅ BIZTONSÁGI JAVÍTÁS: NE jelenítsünk meg titkos információkat!
        logger.info("✅ Environment validation passed:")
        for var in required_vars + optional_but_recommended:
            value = os.getenv(var)
            if value and value.strip() != '':
                logger.info(f"   {var}: [LOADED]")
            else:
                logger.info(f"   {var}: [MISSING]")
        
        # Validate REPO_NAME for pacman.conf
        repo_name = os.getenv('REPO_NAME')
        if repo_name:
            if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
                logger.error(f"[ERROR] Invalid REPO_NAME '{repo_name}'. Must contain only letters, numbers, hyphens, and underscores.")
                sys.exit(1)
            if len(repo_name) > 50:
                logger.error(f"[ERROR] REPO_NAME '{repo_name}' is too long (max 50 characters).")
                sys.exit(1)
    
    def _load_config(self):
        """Load configuration from environment and config files"""
        # Required environment variables (secrets)
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        
        # Optional environment variables (overrides)
        self.repo_server_url = os.getenv('REPO_SERVER_URL', '')
        self.remote_dir = os.getenv('REMOTE_DIR')
        
        # Repository name from environment (validated in _validate_env)
        self.repo_name = os.getenv('REPO_NAME')
        
        print(f"🔧 Configuration loaded:")
        # ✅ BIZTONSÁGI JAVÍTÁS: Csak nem titkos információkat jelenítsünk meg
        print(f"   SSH user: {self.vps_user}")
        print(f"   VPS host: {self.vps_host}")
        print(f"   Remote directory: {self.remote_dir}")
        print(f"   Repository name: {self.repo_name}")
        if self.repo_server_url:
            print(f"   Repository URL: {self.repo_server_url}")
        print(f"   Config files loaded: {HAS_CONFIG_FILES}")
    
    def _init_modules(self):
        """Initialize all modules with configuration"""
        try:
            # VPS Client configuration
            vps_config = {
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
                'remote_dir': self.remote_dir,
                'ssh_options': self.ssh_options,
                'repo_name': self.repo_name,
            }
            self.vps_client = VPSClient(vps_config)
            self.vps_client.setup_ssh_config(self.ssh_key)
            
            # Repository Manager configuration
            repo_config = {
                'repo_name': self.repo_name,
                'output_dir': self.output_dir,
                'remote_dir': self.remote_dir,
                'mirror_temp_dir': self.mirror_temp_dir,
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
            }
            self.repo_manager = RepoManager(repo_config)
            
            # Build Engine configuration
            build_config = {
                'repo_root': self.repo_root,
                'output_dir': self.output_dir,
                'aur_build_dir': self.aur_build_dir,
                'aur_urls': self.aur_urls,
                'repo_name': self.repo_name,
            }
            self.build_engine = BuildEngine(build_config)
            
            # GPG Handler
            self.gpg_handler = GPGHandler()
            
            logger.info("✅ All modules initialized successfully")
            
        except NameError as e:
            logger.error(f"❌ NameError during module initialization: {e}")
            logger.error("This indicates missing imports in module files")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Error initializing modules: {e}")
            sys.exit(1)
    
    def _get_repo_root(self):
        """Get the repository root directory reliably"""
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
        
        # Get script directory and go up to repo root
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent.parent
        if repo_root.exists():
            logger.info(f"Using repository root from script location: {repo_root}")
            return repo_root
        
        current_dir = Path.cwd()
        logger.info(f"Using current directory: {current_dir}")
        return current_dir
    
    def get_package_lists(self):
        """Get package lists from packages.py or exit if not available"""
        if HAS_CONFIG_FILES and hasattr(packages, 'LOCAL_PACKAGES') and hasattr(packages, 'AUR_PACKAGES'):
            print("📦 Using package lists from packages.py")
            local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
            print(f">>> DEBUG: Found {len(local_packages_list + aur_packages_list)} packages to check")
            return local_packages_list, aur_packages_list
        else:
            logger.error("Cannot load package lists from packages.py. Exiting.")
            sys.exit(1)
    
    def _apply_repository_state(self, exists: bool, has_packages: bool):
        """Apply repository state with proper SigLevel based on discovery - CRITICAL FIX: Run pacman -Sy after enabling repository"""
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
            
            # Remove old section if it exists
            in_section = False
            for line in lines:
                # Check if we're entering our section
                if line.strip() == repo_section or line.strip() == f"#{repo_section}":
                    in_section = True
                    continue
                elif in_section and (line.strip().startswith('[') or line.strip() == ''):
                    # We're leaving our section
                    in_section = False
                
                if not in_section:
                    new_lines.append(line)
            
            # Add new section if repository exists on VPS
            if exists:
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                new_lines.append(f"# Automatically enabled - found on VPS")
                new_lines.append(repo_section)
                if has_packages:
                    new_lines.append("SigLevel = Optional TrustAll")
                    logger.info("✅ Enabling repository with SigLevel = Optional TrustAll (build mode)")
                else:
                    new_lines.append("# SigLevel = Optional TrustAll")
                    new_lines.append("# Repository exists but has no packages yet")
                    logger.info("⚠️ Repository section added but commented (no packages yet)")
                
                if self.repo_server_url:
                    new_lines.append(f"Server = {self.repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
            else:
                # Repository doesn't exist on VPS, add commented section
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                new_lines.append(f"# Disabled - not found on VPS (first run?)")
                new_lines.append(f"#{repo_section}")
                new_lines.append("#SigLevel = Optional TrustAll")
                if self.repo_server_url:
                    new_lines.append(f"#Server = {self.repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
                logger.info("ℹ️ Repository not found on VPS - keeping disabled")
            
            # Write back to pacman.conf
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write('\n'.join(new_lines))
                temp_path = temp_file.name
            
            # Copy to pacman.conf
            subprocess.run(['sudo', 'cp', temp_path, str(pacman_conf)], check=False)
            subprocess.run(['sudo', 'chmod', '644', str(pacman_conf)], check=False)
            os.unlink(temp_path)
            
            logger.info(f"✅ Updated pacman.conf for repository '{self.repo_name}'")
            
            # CRITICAL FIX: Run pacman -Sy after enabling repository to synchronize databases
            if exists and has_packages:
                logger.info("🔄 Synchronizing pacman databases after enabling repository...")
                cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
                result = self._run_cmd(cmd, log_cmd=True, timeout=300, check=False)
                if result.returncode == 0:
                    logger.info("✅ Pacman databases synchronized successfully")
                else:
                    logger.warning(f"⚠️ Pacman sync warning: {result.stderr[:200]}")
            
        except Exception as e:
            logger.error(f"Failed to apply repository state: {e}")
    
    def _sync_pacman_databases(self):
        """Simplified pacman database sync with proper SigLevel handling"""
        print("\n" + "=" * 60)
        print("FINAL STEP: Syncing pacman databases")
        print("=" * 60)
        
        # First, ensure repository is enabled with proper SigLevel
        exists, has_packages = self.vps_client.check_repository_exists_on_vps()
        self._apply_repository_state(exists, has_packages)
        
        if not exists:
            logger.info("ℹ️ Repository doesn't exist on VPS, skipping pacman sync")
            return False
        
        # Run pacman -Sy
        cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        result = self._run_cmd(cmd, log_cmd=True, timeout=300, check=False)
        
        if result.returncode == 0:
            logger.info("✅ Pacman databases synced successfully")
            
            # Debug: List packages in our custom repo
            debug_cmd = f"sudo pacman -Sl {self.repo_name}"
            logger.info(f"🔍 DEBUG: Running command to see what packages pacman sees in our repo:")
            logger.info(f"Command: {debug_cmd}")
            
            debug_result = self._run_cmd(debug_cmd, log_cmd=True, timeout=30, check=False)
            
            if debug_result.returncode == 0:
                if debug_result.stdout.strip():
                    logger.info(f"Packages in {self.repo_name} according to pacman:")
                    for line in debug_result.stdout.splitlines():
                        logger.info(f"  {line}")
                else:
                    logger.warning(f"⚠️ pacman -Sl {self.repo_name} returned no output (repo might be empty)")
            else:
                logger.warning(f"⚠️ pacman -Sl failed: {debug_result.stderr[:200]}")
            
            return True
        else:
            logger.error("❌ Pacman sync failed")
            if result.stderr:
                logger.error(f"Error: {result.stderr[:500]}")
            return False
    
    def _run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, 
                 log_cmd=False, timeout=1800, extra_env=None):
        """Run command with comprehensive logging, timeout, and optional extra environment variables"""
        # Check debug mode from config
        debug_mode = HAS_CONFIG_FILES and getattr(config, 'DEBUG_MODE', False)
        
        if log_cmd or debug_mode:
            if debug_mode:
                print(f"🔧 [BUILDER DEBUG] RUNNING COMMAND: {cmd}", flush=True)
            else:
                logger.info(f"RUNNING COMMAND: {cmd}")
        
        if cwd is None:
            cwd = self.repo_root
        
        # Prepare environment
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        
        if user:
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            env['LC_ALL'] = 'C'
            
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
                    env=env,
                    timeout=timeout
                )
                
                # CRITICAL FIX: When in debug mode, bypass logger for critical output
                if log_cmd or debug_mode:
                    if debug_mode:
                        if result.stdout:
                            print(f"🔧 [BUILDER DEBUG] STDOUT:\n{result.stdout}", flush=True)
                        if result.stderr:
                            print(f"🔧 [BUILDER DEBUG] STDERR:\n{result.stderr}", flush=True)
                        print(f"🔧 [BUILDER DEBUG] EXIT CODE: {result.returncode}", flush=True)
                    else:
                        if result.stdout:
                            logger.info(f"STDOUT: {result.stdout[:500]}")
                        if result.stderr:
                            logger.info(f"STDERR: {result.stderr[:500]}")
                        logger.info(f"EXIT CODE: {result.returncode}")
                
                # CRITICAL: If command failed and we're in debug mode, print full output
                if result.returncode != 0 and debug_mode:
                    print(f"❌ [BUILDER DEBUG] COMMAND FAILED: {cmd}", flush=True)
                    if result.stdout and len(result.stdout) > 500:
                        print(f"❌ [BUILDER DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                    if result.stderr and len(result.stderr) > 500:
                        print(f"❌ [BUILDER DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)
                
                return result
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                if debug_mode:
                    print(f"❌ [BUILDER DEBUG] {error_msg}", flush=True)
                logger.error(error_msg)
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd or debug_mode:
                    error_msg = f"Command failed: {cmd}"
                    if debug_mode:
                        print(f"❌ [BUILDER DEBUG] {error_msg}", flush=True)
                        if hasattr(e, 'stdout') and e.stdout:
                            print(f"❌ [BUILDER DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                        if hasattr(e, 'stderr') and e.stderr:
                            print(f"❌ [BUILDER DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                    else:
                        logger.error(error_msg)
                if check:
                    raise
                return e
        else:
            try:
                env['LC_ALL'] = 'C'
                
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    shell=shell,
                    capture_output=capture,
                    text=True,
                    check=check,
                    env=env,
                    timeout=timeout
                )
                
                # CRITICAL FIX: When in debug mode, bypass logger for critical output
                if log_cmd or debug_mode:
                    if debug_mode:
                        if result.stdout:
                            print(f"🔧 [BUILDER DEBUG] STDOUT:\n{result.stdout}", flush=True)
                        if result.stderr:
                            print(f"🔧 [BUILDER DEBUG] STDERR:\n{result.stderr}", flush=True)
                        print(f"🔧 [BUILDER DEBUG] EXIT CODE: {result.returncode}", flush=True)
                    else:
                        if result.stdout:
                            logger.info(f"STDOUT: {result.stdout[:500]}")
                        if result.stderr:
                            logger.info(f"STDERR: {result.stderr[:500]}")
                        logger.info(f"EXIT CODE: {result.returncode}")
                
                # CRITICAL: If command failed and we're in debug mode, print full output
                if result.returncode != 0 and debug_mode:
                    print(f"❌ [BUILDER DEBUG] COMMAND FAILED: {cmd}", flush=True)
                    if result.stdout and len(result.stdout) > 500:
                        print(f"❌ [BUILDER DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                    if result.stderr and len(result.stderr) > 500:
                        print(f"❌ [BUILDER DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)
                
                return result
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                if debug_mode:
                    print(f"❌ [BUILDER DEBUG] {error_msg}", flush=True)
                logger.error(error_msg)
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd or debug_mode:
                    error_msg = f"Command failed: {cmd}"
                    if debug_mode:
                        print(f"❌ [BUILDER DEBUG] {error_msg}", flush=True)
                        if hasattr(e, 'stdout') and e.stdout:
                            print(f"❌ [BUILDER DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                        if hasattr(e, 'stderr') and e.stderr:
                            print(f"❌ [BUILDER DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                    else:
                        logger.error(error_msg)
                if check:
                    raise
                return e
    
    def package_exists(self, pkg_name: str, version=None) -> bool:
        """Check if package exists on server"""
        if not self.remote_files:
            return False
        
        pattern = f"^{re.escape(pkg_name)}-"
        matches = [f for f in self.remote_files if re.match(pattern, f)]
        
        if matches:
            logger.debug(f"Package {pkg_name} exists: {matches[0]}")
            return True
        
        return False
    
    def get_remote_version(self, pkg_name: str) -> Optional[str]:
        """Get the version of a package from remote server using SRCINFO-based extraction"""
        if not self.remote_files:
            return None
        
        # Look for any file with this package name
        for filename in self.remote_files:
            if filename.startswith(f"{pkg_name}-"):
                # Extract version from filename
                base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
                parts = base.split('-')
                
                # Find where the package name ends
                for i in range(len(parts) - 2, 0, -1):
                    possible_name = '-'.join(parts[:i])
                    if possible_name == pkg_name or possible_name.startswith(pkg_name + '-'):
                        if len(parts) >= i + 3:
                            version_part = parts[i]
                            release_part = parts[i+1]
                            if i + 1 < len(parts) and parts[i].isdigit() and i + 2 < len(parts):
                                epoch_part = parts[i]
                                version_part = parts[i+1]
                                release_part = parts[i+2]
                                return f"{epoch_part}:{version_part}-{release_part}"
                            else:
                                return f"{version_part}-{release_part}"
        
        return None
    
    def _build_aur_package(self, pkg_name: str) -> bool:
        """Build AUR package with SRCINFO-based version comparison and PACKAGER injection - FIXED: AUR dependency fallback"""
        aur_dir = self.aur_build_dir
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)
        
        print(f"Cloning {pkg_name} from AUR...")
        
        # Try different AUR URLs from config (ALWAYS FRESH CLONE)
        clone_success = False
        for aur_url_template in self.aur_urls:
            aur_url = aur_url_template.format(pkg_name=pkg_name)
            logger.info(f"Trying AUR URL: {aur_url}")
            result = self._run_cmd(
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
        self._run_cmd(f"chown -R builder:builder {pkg_dir}", check=False)
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
        
        # Extract version info from SRCINFO (not regex)
        try:
            pkgver, pkgrel, epoch = self.build_engine.extract_version_from_srcinfo(pkg_dir)
            version = self.build_engine.get_full_version_string(pkgver, pkgrel, epoch)
            
            # Get remote version for comparison
            remote_version = self.get_remote_version(pkg_name)
            
            # DECISION LOGIC: Only build if AUR_VERSION > REMOTE_VERSION
            if remote_version and not self.build_engine.compare_versions(remote_version, pkgver, pkgrel, epoch):
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                
                # ZERO-RESIDUE FIX: Register the target version for this skipped package
                self.repo_manager.register_skipped_package(pkg_name, remote_version)
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files BEFORE building new version
                self.repo_manager.pre_build_purge_old_versions(pkg_name, remote_version)
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
                
        except Exception as e:
            logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self.build_engine.clean_workspace(pkg_dir)
            
            print("Downloading sources...")
            source_result = self._run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True, timeout=600,
                                        extra_env={"PACKAGER": self.packager_id})
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            # CRITICAL FIX: Install dependencies with AUR fallback
            print("Installing dependencies with AUR fallback...")
            
            # First attempt: Standard makepkg -si
            print("Building package (first attempt)...")
            build_result = self._run_cmd(
                f"makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600,
                extra_env={"PACKAGER": self.packager_id}
            )
            
            # If first attempt fails, try yay fallback for missing dependencies
            if build_result.returncode != 0:
                logger.warning(f"First build attempt failed for {pkg_name}, trying AUR dependency fallback...")
                
                # Extract missing dependencies from error output
                error_output = build_result.stderr if build_result.stderr else build_result.stdout
                missing_deps = []
                
                # Look for patterns like "error: target not found: <package>"
                import re
                missing_patterns = [
                    r"error: target not found: (\S+)",
                    r"Could not find all required packages:",
                    r":: Unable to find (\S+)",
                ]
                
                for pattern in missing_patterns:
                    matches = re.findall(pattern, error_output)
                    if matches:
                        missing_deps.extend(matches)
                
                # Also look for specific makepkg dependency errors
                if "makepkg: cannot find the" in error_output:
                    lines = error_output.split('\n')
                    for line in lines:
                        if "makepkg: cannot find the" in line:
                            # Extract package name from line like "makepkg: cannot find the 'gcc14' package"
                            dep_match = re.search(r"cannot find the '([^']+)'", line)
                            if dep_match:
                                missing_deps.append(dep_match.group(1))
                
                # Remove duplicates
                missing_deps = list(set(missing_deps))
                
                if missing_deps:
                    logger.info(f"Found missing dependencies: {missing_deps}")
                    
                    # Try to install missing dependencies with yay
                    deps_str = ' '.join(missing_deps)
                    yay_cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
                    yay_result = self._run_cmd(yay_cmd, log_cmd=True, check=False, user="builder", timeout=1800)
                    
                    if yay_result.returncode == 0:
                        logger.info("✅ Missing dependencies installed via yay, retrying build...")
                        
                        # Retry the build
                        build_result = self._run_cmd(
                            f"makepkg -si --noconfirm --clean --nocheck",
                            cwd=pkg_dir,
                            capture=True,
                            check=False,
                            timeout=3600,
                            extra_env={"PACKAGER": self.packager_id}
                        )
                    else:
                        logger.error(f"❌ Failed to install missing dependencies with yay")
                        shutil.rmtree(pkg_dir, ignore_errors=True)
                        return False
            
            if build_result.returncode == 0:
                moved = False
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    # ZERO-RESIDUE FIX: Register the target version for this built package
                    self.repo_manager.register_package_target_version(pkg_name, version)
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
    
    def _build_local_package(self, pkg_name: str) -> bool:
        """Build local package with SRCINFO-based version comparison and PACKAGER injection - FIXED: AUR dependency fallback"""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        # Extract version info from SRCINFO (not regex)
        try:
            pkgver, pkgrel, epoch = self.build_engine.extract_version_from_srcinfo(pkg_dir)
            version = self.build_engine.get_full_version_string(pkgver, pkgrel, epoch)
            
            # Get remote version for comparison
            remote_version = self.get_remote_version(pkg_name)
            
            # DECISION LOGIC: Only build if AUR_VERSION > REMOTE_VERSION
            if remote_version and not self.build_engine.compare_versions(remote_version, pkgver, pkgrel, epoch):
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                
                # ZERO-RESIDUE FIX: Register the target version for this skipped package
                self.repo_manager.register_skipped_package(pkg_name, remote_version)
                
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files BEFORE building new version
                self.repo_manager.pre_build_purge_old_versions(pkg_name, remote_version)
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
                
        except Exception as e:
            logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self.build_engine.clean_workspace(pkg_dir)
            
            print("Downloading sources...")
            source_result = self._run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True, timeout=600,
                                        extra_env={"PACKAGER": self.packager_id})
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                return False
            
            # CRITICAL FIX: Install dependencies with AUR fallback
            print("Installing dependencies with AUR fallback...")
            
            # First attempt: Standard makepkg with appropriate flags
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                logger.info("GTK2: Skipping check step (long)")
            
            print("Building package (first attempt)...")
            build_result = self._run_cmd(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600,
                extra_env={"PACKAGER": self.packager_id}
            )
            
            # If first attempt fails, try yay fallback for missing dependencies
            if build_result.returncode != 0:
                logger.warning(f"First build attempt failed for {pkg_name}, trying AUR dependency fallback...")
                
                # Extract missing dependencies from error output
                error_output = build_result.stderr if build_result.stderr else build_result.stdout
                missing_deps = []
                
                # Look for patterns like "error: target not found: <package>"
                import re
                missing_patterns = [
                    r"error: target not found: (\S+)",
                    r"Could not find all required packages:",
                    r":: Unable to find (\S+)",
                ]
                
                for pattern in missing_patterns:
                    matches = re.findall(pattern, error_output)
                    if matches:
                        missing_deps.extend(matches)
                
                # Also look for specific makepkg dependency errors
                if "makepkg: cannot find the" in error_output:
                    lines = error_output.split('\n')
                    for line in lines:
                        if "makepkg: cannot find the" in line:
                            # Extract package name from line like "makepkg: cannot find the 'gcc14' package"
                            dep_match = re.search(r"cannot find the '([^']+)'", line)
                            if dep_match:
                                missing_deps.append(dep_match.group(1))
                
                # Remove duplicates
                missing_deps = list(set(missing_deps))
                
                if missing_deps:
                    logger.info(f"Found missing dependencies: {missing_deps}")
                    
                    # Try to install missing dependencies with yay
                    deps_str = ' '.join(missing_deps)
                    yay_cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
                    yay_result = self._run_cmd(yay_cmd, log_cmd=True, check=False, user="builder", timeout=1800)
                    
                    if yay_result.returncode == 0:
                        logger.info("✅ Missing dependencies installed via yay, retrying build...")
                        
                        # Retry the build
                        build_result = self._run_cmd(
                            f"makepkg {makepkg_flags}",
                            cwd=pkg_dir,
                            capture=True,
                            check=False,
                            timeout=3600,
                            extra_env={"PACKAGER": self.packager_id}
                        )
                    else:
                        logger.error(f"❌ Failed to install missing dependencies with yay")
                        return False
            
            if build_result.returncode == 0:
                moved = False
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                    built_files.append(str(dest))
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    self.rebuilt_local_packages.append(pkg_name)
                    
                    # ZERO-RESIDUE FIX: Register the target version for this built package
                    self.repo_manager.register_package_target_version(pkg_name, version)
                    
                    # Collect metadata for hokibot
                    if built_files:
                        # Simplified metadata extraction
                        filename = os.path.basename(built_files[0])
                        self.build_engine.hokibot_data.append({
                            'name': pkg_name,
                            'built_version': version,
                            'pkgver': pkgver,
                            'pkgrel': pkgrel,
                            'epoch': epoch
                        })
                        logger.info(f"📝 HOKIBOT observed: {pkg_name} -> {version}")
                    
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
    
    def _build_single_package(self, pkg_name: str, is_aur: bool) -> bool:
        """Build a single package"""
        print(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")
        
        if is_aur:
            return self._build_aur_package(pkg_name)
        else:
            return self._build_local_package(pkg_name)
    
    def build_packages(self) -> int:
        """Build packages"""
        print("\n" + "=" * 60)
        print("Building packages")
        print("=" * 60)
        
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
    
    def upload_packages(self) -> bool:
        """Upload packages to server using RSYNC WITHOUT --delete flag"""
        # Get all package files and database files
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
        
        all_files = pkg_files + db_files
        
        if not all_files:
            logger.warning("No files to upload")
            self.repo_manager.set_upload_successful(False)
            return False
        
        # Ensure remote directory exists
        self.vps_client.ensure_remote_directory()
        
        # Collect files using glob patterns
        file_patterns = [
            str(self.output_dir / "*.pkg.tar.*"),
            str(self.output_dir / f"{self.repo_name}.*")
        ]
        
        files_to_upload = []
        for pattern in file_patterns:
            files_to_upload.extend(glob.glob(pattern))
        
        if not files_to_upload:
            logger.error("No files found to upload!")
            self.repo_manager.set_upload_successful(False)
            return False
        
        # Upload files using VPS client
        upload_success = self.vps_client.upload_files(files_to_upload, self.output_dir)
        
        # Set upload success flag for cleanup
        self.repo_manager.set_upload_successful(upload_success)
        
        return upload_success
    
    def run(self):
        """Main execution with simplified repository discovery and proper GPG integration"""
        print("\n" + "=" * 60)
        print("🚀 MANJARO PACKAGE BUILDER (MODULAR ARCHITECTURE)")
        print("=" * 60)
        
        try:
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Repository name: {self.repo_name}")
            print(f"Output directory: {self.output_dir}")
            print(f"PACKAGER identity: {self.packager_id}")
            
            # STEP 0: Initialize GPG FIRST if enabled
            print("\n" + "=" * 60)
            print("STEP 0: GPG INITIALIZATION")
            print("=" * 60)
            if self.gpg_handler.gpg_enabled:
                if not self.gpg_handler.import_gpg_key():
                    logger.error("❌ Failed to import GPG key, disabling signing")
                else:
                    logger.info("✅ GPG initialized successfully")
            else:
                logger.info("ℹ️ GPG signing disabled (no key provided)")
            
            # STEP 1: SIMPLIFIED REPOSITORY DISCOVERY
            print("\n" + "=" * 60)
            print("STEP 1: SIMPLIFIED REPOSITORY STATE DISCOVERY")
            print("=" * 60)
            
            # Check if repository exists on VPS
            repo_exists, has_packages = self.vps_client.check_repository_exists_on_vps()
            
            # Apply repository state based on discovery
            self._apply_repository_state(repo_exists, has_packages)
            
            # Ensure remote directory exists
            self.vps_client.ensure_remote_directory()
            
            # STEP 2: List remote packages for version comparison
            remote_packages = self.vps_client.list_remote_packages()
            self.remote_files = [os.path.basename(f) for f in remote_packages] if remote_packages else []
            
            # MANDATORY STEP: Mirror ALL remote packages locally before any database operations
            if remote_packages:
                print("\n" + "=" * 60)
                print("MANDATORY PRECONDITION: Mirroring remote packages locally")
                print("=" * 60)
                
                if not self.vps_client.mirror_remote_packages(self.mirror_temp_dir, self.output_dir):
                    logger.error("❌ FAILED to mirror remote packages locally")
                    logger.error("Cannot proceed without local package mirror")
                    return 1
            else:
                logger.info("ℹ️ No remote packages to mirror (repository appears empty)")
            
            # STEP 3: Check existing database files
            existing_db_files, missing_db_files = self.repo_manager.check_database_files()
            
            # Fetch existing database if available
            if existing_db_files:
                self.repo_manager.fetch_existing_database(existing_db_files)
            
            # Build packages
            print("\n" + "=" * 60)
            print("STEP 5: PACKAGE BUILDING (SRCINFO VERSIONING)")
            print("=" * 60)
            
            total_built = self.build_packages()
            
            # Check if we have any packages locally (mirrored + newly built)
            local_packages = self.repo_manager._get_all_local_packages()
            
            if local_packages or remote_packages:
                print("\n" + "=" * 60)
                print("STEP 6: REPOSITORY DATABASE HANDLING (WITH LOCAL MIRROR)")
                print("=" * 60)
                
                # ZERO-RESIDUE FIX: Perform server cleanup BEFORE database generation
                print("\n" + "=" * 60)
                print("🚨 PRE-DATABASE CLEANUP: Removing zombie packages from server")
                print("=" * 60)
                self.repo_manager.server_cleanup()
                
                # Generate database with ALL locally available packages
                if self.repo_manager.generate_full_database():
                    # Sign repository database files if GPG is enabled
                    if self.gpg_handler.gpg_enabled:
                        if not self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir)):
                            logger.warning("⚠️ Failed to sign repository files, continuing anyway")
                    
                    # Upload regenerated database and packages
                    if not self.vps_client.test_ssh_connection():
                        logger.warning("SSH test failed, but trying upload anyway...")
                    
                    # Upload everything (packages + database + signatures)
                    upload_success = self.upload_packages()
                    
                    # ZERO-RESIDUE FIX: Perform final server cleanup AFTER upload
                    if upload_success:
                        print("\n" + "=" * 60)
                        print("🚨 POST-UPLOAD CLEANUP: Final zombie package removal")
                        print("=" * 60)
                        self.repo_manager.server_cleanup()
                    
                    # Clean up GPG temporary directory
                    self.gpg_handler.cleanup()
                    
                    if upload_success:
                        # STEP 7: Update repository state and sync pacman
                        print("\n" + "=" * 60)
                        print("STEP 7: FINAL REPOSITORY STATE UPDATE")
                        print("=" * 60)
                        
                        # Re-check repository state (it should exist now)
                        repo_exists, has_packages = self.vps_client.check_repository_exists_on_vps()
                        self._apply_repository_state(repo_exists, has_packages)
                        
                        # Sync pacman databases
                        self._sync_pacman_databases()
                        
                        print("\n✅ Build completed successfully!")
                    else:
                        print("\n❌ Upload failed!")
                else:
                    print("\n❌ Database generation failed!")
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
                
                # Clean up GPG even if no packages built
                self.gpg_handler.cleanup()
            
            elapsed = time.time() - self.stats["start_time"]
            
            print("\n" + "=" * 60)
            print("📊 BUILD SUMMARY")
            print("=" * 60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {self.stats['aur_success']} (failed: {self.stats['aur_failed']})")
            print(f"Local packages:  {self.stats['local_success']} (failed: {self.stats['local_failed']})")
            print(f"Total built:     {total_built}")
            print(f"Skipped:         {len(self.skipped_packages)}")
            print(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            print(f"PACKAGER:        {self.packager_id}")
            print(f"Zero-Residue:    ✅ Exact-filename-match cleanup active")
            print(f"Target Version:  ✅ Package target versions registered: {len(self.repo_manager._package_target_versions)}")
            print(f"Skipped Registry:✅ Skipped packages tracked: {len(self.repo_manager._skipped_packages)}")
            print("=" * 60)
            
            if self.built_packages:
                print("\n📦 Built packages:")
                for pkg in self.built_packages:
                    print(f"  - {pkg}")
            
            return 0
            
        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            # Ensure GPG cleanup even on failure
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            return 1


if __name__ == "__main__":
    sys.exit(PackageBuilder().run())