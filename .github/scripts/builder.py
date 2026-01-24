#!/usr/bin/env python3
"""
Manjaro Package Builder - Refactored with Remote State Verification
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
import json
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
    """Main orchestrator with remote state verification"""
    
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
        """Comprehensive pre-flight environment validation"""
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
        
        # Check optional variables
        for var in optional_but_recommended:
            value = os.getenv(var)
            if not value or value.strip() == '':
                logger.warning(f"⚠️ Optional variable {var} is empty")
        
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
                logger.error(f"[ERROR] Invalid REPO_NAME '{repo_name}'.")
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
        
        # Repository name from environment
        self.repo_name = os.getenv('REPO_NAME')
        
        print(f"🔧 Configuration loaded:")
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
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
            }
            self.repo_manager = RepoManager(repo_config)
            
            # Set VPS client in repo manager
            self.repo_manager.set_vps_client(self.vps_client)
            
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
        """Apply repository state with proper SigLevel"""
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
                if line.strip() == repo_section or line.strip() == f"#{repo_section}":
                    in_section = True
                    continue
                elif in_section and (line.strip().startswith('[') or line.strip() == ''):
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
            
            # Run pacman -Sy after enabling repository
            if exists and has_packages:
                logger.info("🔄 Synchronizing pacman databases after enabling repository...")
                cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
                result = self._run_cmd(cmd, log_cmd=True, timeout=300, check=False)
                if result.returncode == 0:
                    logger.info("✅ Pacman databases synchronized successfully")
            
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
            
            debug_result = self._run_cmd(debug_cmd, log_cmd=True, timeout=30, check=False)
            
            if debug_result.returncode == 0:
                if debug_result.stdout.strip():
                    logger.info(f"Packages in {self.repo_name} according to pacman:")
                    for line in debug_result.stdout.splitlines():
                        logger.info(f"  {line}")
            
            return True
        else:
            logger.error("❌ Pacman sync failed")
            return False
    
    def _run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, 
                 log_cmd=False, timeout=1800, extra_env=None):
        """Run command with comprehensive logging"""
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
                    else:
                        logger.error(error_msg)
                if check:
                    raise
                return e
    
    def _build_aur_package(self, pkg_name: str) -> bool:
        """Build AUR package with remote state verification"""
        aur_dir = self.aur_build_dir
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)
        
        print(f"Cloning {pkg_name} from AUR...")
        
        # Try different AUR URLs
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
        
        # Extract version info from SRCINFO
        try:
            pkgver, pkgrel, epoch = self.build_engine.extract_version_from_srcinfo(pkg_dir)
            version = self.build_engine.get_full_version_string(pkgver, pkgrel, epoch)
            
            # Check if package is up-to-date using remote state verification
            is_up_to_date, remote_version = self.repo_manager.is_package_up_to_date(
                pkg_name, version, pkgver, pkgrel, epoch
            )
            
            if is_up_to_date:
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                
                # Register the skipped package
                self.repo_manager.register_skipped_package(pkg_name, remote_version)
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files
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
            
            # Build package
            print("Building package...")
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
                
                if "makepkg: cannot find the" in error_output:
                    lines = error_output.split('\n')
                    for line in lines:
                        if "makepkg: cannot find the" in line:
                            dep_match = re.search(r"cannot find the '([^']+)'", line)
                            if dep_match:
                                missing_deps.append(dep_match.group(1))
                
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
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    logger.info(f"✅ Built: {pkg_file.name}")
                    built_files.append(dest)
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                
                if built_files:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    
                    # Update VPS state with new package
                    self.repo_manager.update_package_state(
                        pkg_name, version, built_files[0].name, built_files
                    )
                    
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
        """Build local package with remote state verification"""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        # Extract version info from SRCINFO
        try:
            pkgver, pkgrel, epoch = self.build_engine.extract_version_from_srcinfo(pkg_dir)
            version = self.build_engine.get_full_version_string(pkgver, pkgrel, epoch)
            
            # Check if package is up-to-date using remote state verification
            is_up_to_date, remote_version = self.repo_manager.is_package_up_to_date(
                pkg_name, version, pkgver, pkgrel, epoch
            )
            
            if is_up_to_date:
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                
                # Register the skipped package
                self.repo_manager.register_skipped_package(pkg_name, remote_version)
                
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files
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
            
            # Build package with appropriate flags
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                logger.info("GTK2: Skipping check step (long)")
            
            print("Building package...")
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
                
                error_output = build_result.stderr if build_result.stderr else build_result.stdout
                missing_deps = []
                
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
                
                if "makepkg: cannot find the" in error_output:
                    lines = error_output.split('\n')
                    for line in lines:
                        if "makepkg: cannot find the" in line:
                            dep_match = re.search(r"cannot find the '([^']+)'", line)
                            if dep_match:
                                missing_deps.append(dep_match.group(1))
                
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
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    logger.info(f"✅ Built: {pkg_file.name}")
                    built_files.append(dest)
                
                if built_files:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    self.rebuilt_local_packages.append(pkg_name)
                    
                    # Update VPS state with new package
                    self.repo_manager.update_package_state(
                        pkg_name, version, built_files[0].name, built_files
                    )
                    
                    # Collect metadata for hokibot
                    if built_files:
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
        print("Building packages with Remote State Verification")
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
        import glob
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
        """Main execution with remote state verification"""
        print("\n" + "=" * 60)
        print("🚀 MANJARO PACKAGE BUILDER (REMOTE STATE VERIFICATION)")
        print("=" * 60)
        
        try:
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Repository name: {self.repo_name}")
            print(f"Output directory: {self.output_dir}")
            print(f"PACKAGER identity: {self.packager_id}")
            
            # STEP 0: Initialize GPG if enabled
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
            
            # STEP 1: REPOSITORY DISCOVERY
            print("\n" + "=" * 60)
            print("STEP 1: REMOTE REPOSITORY STATE DISCOVERY")
            print("=" * 60)
            
            # Check if repository exists on VPS
            repo_exists, has_packages = self.vps_client.check_repository_exists_on_vps()
            
            # Apply repository state based on discovery
            self._apply_repository_state(repo_exists, has_packages)
            
            # Ensure remote directory exists
            self.vps_client.ensure_remote_directory()
            
            # Test SSH connection
            if not self.vps_client.test_ssh_connection():
                logger.warning("⚠️ SSH connection test failed, but continuing...")
            
            # STEP 2: List remote packages for initial reference
            remote_packages = self.vps_client.list_remote_packages()
            self.remote_files = [os.path.basename(f) for f in remote_packages] if remote_packages else []
            
            if remote_packages:
                logger.info(f"ℹ️ Found {len(remote_packages)} packages on remote server")
            else:
                logger.info("ℹ️ No packages found on remote server (first run or empty repository)")
            
            # STEP 3: Check existing database files
            existing_db_files, missing_db_files = self.repo_manager.check_database_files()
            
            # Fetch existing database if available
            if existing_db_files:
                self.repo_manager.fetch_existing_database(existing_db_files)
            
            # Build packages
            print("\n" + "=" * 60)
            print("STEP 4: PACKAGE BUILDING (REMOTE STATE VERIFICATION)")
            print("=" * 60)
            
            total_built = self.build_packages()
            
            # Check if we have any packages locally
            local_packages = self.repo_manager._get_all_local_packages()
            
            if local_packages or remote_packages:
                print("\n" + "=" * 60)
                print("STEP 5: REPOSITORY DATABASE HANDLING")
                print("=" * 60)
                
                # ZERO-RESIDUE: Perform server cleanup BEFORE database generation
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
                    upload_success = self.upload_packages()
                    
                    # ZERO-RESIDUE: Perform final server cleanup AFTER upload
                    if upload_success:
                        print("\n" + "=" * 60)
                        print("🚨 POST-UPLOAD CLEANUP: Final zombie package removal")
                        print("=" * 60)
                        self.repo_manager.server_cleanup()
                    
                    # Clean up GPG temporary directory
                    self.gpg_handler.cleanup()
                    
                    if upload_success:
                        # STEP 6: Update repository state and sync pacman
                        print("\n" + "=" * 60)
                        print("STEP 6: FINAL REPOSITORY STATE UPDATE")
                        print("=" * 60)
                        
                        # Re-check repository state
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
            
            # STEP 7: Commit VPS state changes to git
            print("\n" + "=" * 60)
            print("STEP 7: COMMITTING VPS STATE TO GIT")
            print("=" * 60)
            
            if self.repo_manager.get_state_changed():
                self.repo_manager.commit_vps_state_to_git()
                self.repo_manager.reset_state_changed()
            else:
                logger.info("ℹ️ No changes to VPS state, skipping git commit")
            
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
            print(f"Remote State:    ✅ JSON-based verification active")
            print(f"Bandwidth:       ✅ No bulk package downloads")
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