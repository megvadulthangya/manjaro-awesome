#!/usr/bin/env python3
"""
Manjaro Package Builder - Refactored with JSON State Tracking
Main orchestrator that coordinates between modules
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
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
    """Main orchestrator with JSON State Tracking"""
    
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
        self.aur_urls = getattr(config, 'AUR_URLS', ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]) if HAS_CONFIG_FILES else ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]
        self.aur_build_dir = self.repo_root / (getattr(config, 'AUR_BUILD_DIR', 'build_aur') if HAS_CONFIG_FILES else "build_aur")
        self.ssh_options = getattr(config, 'SSH_OPTIONS', ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]) if HAS_CONFIG_FILES else ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]
        self.ssh_repo_url = getattr(config, 'SSH_REPO_URL', '') if HAS_CONFIG_FILES else ''
        
        # Get PACKAGER_ID from config
        self.packager_id = getattr(config, 'PACKAGER_ID', 'Maintainer <no-reply@gshoots.hu>') if HAS_CONFIG_FILES else 'Maintainer <no-reply@gshoots.hu>'
        logger.info(f"🔧 PACKAGER_ID configured: {self.packager_id}")
        
        # Initialize modules
        self._init_modules()
        
        # State tracking
        self.built_packages = []
        self.skipped_packages = []
        self.adopted_packages = []
        self.packages_to_build = []
        self.failed_packages = []
        
        # Dependency tracking
        self.dependency_map = {}
        self.build_order = []
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
            "dependency_checks": 0,
            "pacman_syncs": 0,
        }

    def _validate_env(self) -> None:
        """Comprehensive pre-flight environment validation"""
        logger.info("\n" + "=" * 60)
        logger.info("PRE-FLIGHT ENVIRONMENT VALIDATION")
        logger.info("=" * 60)
        
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
        
        logger.info("✅ Environment validation passed")
    
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
        
        logger.info(f"🔧 Configuration loaded")
        logger.info(f"   SSH user: {self.vps_user}")
        logger.info(f"   VPS host: {self.vps_host}")
        logger.info(f"   Remote directory: {self.remote_dir}")
        logger.info(f"   Repository name: {self.repo_name}")
        if self.repo_server_url:
            logger.info(f"   Repository URL: {self.repo_server_url}")
    
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
            logger.info("📦 Using package lists from packages.py")
            local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
            logger.info(f"Found {len(local_packages_list + aur_packages_list)} packages to check")
            return local_packages_list, aur_packages_list
        else:
            logger.error("Cannot load package lists from packages.py. Exiting.")
            sys.exit(1)
    
    def _enable_custom_repository(self, exists: bool, has_packages: bool):
        """
        Enable custom repository in pacman.conf and SYNC databases
        
        CRITICAL FIX: After writing to pacman.conf, MUST run pacman -Sy
        so makepkg can find dependencies from our custom repo
        """
        logger.info(f"\n🔧 Configuring custom repository: {self.repo_name}")
        
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found")
            return False
        
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
                    logger.info("✅ Enabling repository with SigLevel = Optional TrustAll")
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
            
            # Copy to pacman.conf with sudo
            subprocess.run(['sudo', 'cp', temp_path, str(pacman_conf)], check=False)
            subprocess.run(['sudo', 'chmod', '644', str(pacman_conf)], check=False)
            os.unlink(temp_path)
            
            logger.info(f"✅ Updated pacman.conf for repository '{self.repo_name}'")
            
            # CRITICAL FIX: SYNC PACMAN DATABASES AFTER ENABLING REPOSITORY
            if exists and has_packages:
                logger.info("🔄 Synchronizing pacman databases (pacman -Sy)...")
                try:
                    result = subprocess.run(
                        ["sudo", "pacman", "-Sy", "--noconfirm"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        check=False
                    )
                    
                    if result.returncode == 0:
                        logger.info("✅ Pacman databases synchronized successfully")
                        self.stats["pacman_syncs"] += 1
                        
                        # Verify our repository is visible
                        logger.info(f"🔍 Checking if {self.repo_name} is visible to pacman...")
                        check_result = subprocess.run(
                            ["pacman", "-Sl", self.repo_name],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if check_result.returncode == 0 and check_result.stdout.strip():
                            logger.info(f"✅ Repository {self.repo_name} is visible to pacman")
                            for line in check_result.stdout.strip().split('\n')[:5]:
                                logger.info(f"  {line}")
                        else:
                            logger.warning(f"⚠️ Repository {self.repo_name} not visible to pacman (may be empty)")
                    else:
                        logger.error(f"❌ Pacman sync failed: {result.stderr[:200]}")
                        return False
                        
                except subprocess.TimeoutExpired:
                    logger.error("❌ Pacman sync timed out")
                    return False
                except Exception as e:
                    logger.error(f"❌ Pacman sync error: {e}")
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure repository: {e}")
            return False
    
    def _check_dependency_satisfaction(self, pkg_name: str, pkg_dir: Path, is_aur: bool) -> Tuple[bool, List[str]]:
        """
        Check if all dependencies for a package are satisfied
        
        Returns:
            Tuple of (all_satisfied, missing_deps)
        """
        try:
            # Extract dependencies from PKGBUILD or .SRCINFO
            deps = []
            makedeps = []
            
            srcinfo_path = pkg_dir / ".SRCINFO"
            if srcinfo_path.exists():
                with open(srcinfo_path, 'r') as f:
                    content = f.read()
                
                in_depends = False
                in_makedepends = False
                
                for line in content.split('\n'):
                    line = line.strip()
                    if line.startswith('depends ='):
                        deps.append(line.split('=', 1)[1].strip())
                    elif line.startswith('makedepends ='):
                        makedeps.append(line.split('=', 1)[1].strip())
            
            all_deps = deps + makedeps
            if not all_deps:
                return True, []
            
            # Clean dependency names (remove version constraints)
            clean_deps = []
            for dep in all_deps:
                # Remove version constraints like >=, <=, =
                dep_clean = re.sub(r'[<=>].*', '', dep).strip()
                # Remove any arch specifiers
                dep_clean = re.sub(r':.*$', '', dep_clean).strip()
                if dep_clean:
                    clean_deps.append(dep_clean)
            
            # Check which dependencies are available
            missing_deps = []
            
            for dep in clean_deps:
                self.stats["dependency_checks"] += 1
                
                # Check if dependency is in our custom repository
                if dep in self.dependency_map:
                    logger.debug(f"✅ Dependency {dep} is provided by {self.dependency_map[dep]} in our repo")
                    continue
                
                # Check if dependency is available in pacman
                check_cmd = ["pacman", "-Si", dep]
                result = subprocess.run(check_cmd, capture_output=True, text=True, check=False)
                
                if result.returncode != 0:
                    # Check if it's a group
                    check_group = ["pacman", "-Sg", dep]
                    group_result = subprocess.run(check_group, capture_output=True, text=True, check=False)
                    
                    if group_result.returncode != 0:
                        missing_deps.append(dep)
                    else:
                        logger.debug(f"✅ Dependency {dep} is a package group")
            
            if missing_deps:
                logger.warning(f"⚠️ {pkg_name}: Missing {len(missing_deps)} dependencies: {', '.join(missing_deps[:5])}")
                if len(missing_deps) > 5:
                    logger.warning(f"   ... and {len(missing_deps) - 5} more")
                return False, missing_deps
            else:
                logger.debug(f"✅ {pkg_name}: All dependencies satisfied")
                return True, []
                
        except Exception as e:
            logger.warning(f"⚠️ Could not check dependencies for {pkg_name}: {e}")
            # If we can't check, assume they're satisfied (makepkg will fail if not)
            return True, []
    
    def _run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, 
                 log_cmd=False, timeout=1800, extra_env=None):
        """Run command with comprehensive logging, timeout, and optional extra environment variables"""
        if log_cmd:
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
                
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                
                return result
            except subprocess.TimeoutExpired as e:
                logger.error(f"⚠️ Command timed out after {timeout} seconds: {cmd}")
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
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
                
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                
                return result
            except subprocess.TimeoutExpired as e:
                logger.error(f"⚠️ Command timed out after {timeout} seconds: {cmd}")
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
                if check:
                    raise
                return e
    
    def _fetch_aur_packages(self, aur_packages: List[str]) -> bool:
        """
        Fetch AUR packages to make PKGBUILD files available
        
        Args:
            aur_packages: List of AUR package names
            
        Returns:
            True if all packages fetched successfully
        """
        if not aur_packages:
            return True
        
        logger.info("\n" + "=" * 60)
        logger.info("📥 AUR PACKAGE FETCH PHASE")
        logger.info("=" * 60)
        
        success_count = 0
        failure_count = 0
        
        for pkg_name in aur_packages:
            logger.info(f"Fetching {pkg_name} from AUR...")
            
            pkg_dir = self.aur_build_dir / pkg_name
            if pkg_dir.exists():
                shutil.rmtree(pkg_dir, ignore_errors=True)
            
            # Try different AUR URLs from config
            clone_success = False
            for aur_url_template in self.aur_urls:
                aur_url = aur_url_template.format(pkg_name=pkg_name)
                result = self._run_cmd(
                    f"git clone --depth 1 {aur_url} {pkg_dir}",
                    check=False,
                    timeout=300
                )
                if result and result.returncode == 0:
                    clone_success = True
                    break
            
            if clone_success:
                # Set correct permissions
                self._run_cmd(f"chown -R builder:builder {pkg_dir}", check=False)
                
                # Verify PKGBUILD exists
                pkgbuild = pkg_dir / "PKGBUILD"
                if pkgbuild.exists():
                    success_count += 1
                    logger.info(f"✅ Successfully fetched {pkg_name}")
                else:
                    failure_count += 1
                    logger.error(f"❌ No PKGBUILD found for {pkg_name}")
                    shutil.rmtree(pkg_dir, ignore_errors=True)
            else:
                failure_count += 1
                logger.error(f"❌ Failed to fetch {pkg_name}")
        
        logger.info(f"📊 AUR fetch results: {success_count} successful, {failure_count} failed")
        return failure_count == 0
    
    def _build_single_package(self, pkg_name: str, is_aur: bool, attempt: int = 1) -> bool:
        """Build a single package with dependency checking"""
        logger.info(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")
        
        # Determine package directory
        if is_aur:
            pkg_dir = self.aur_build_dir / pkg_name
        else:
            pkg_dir = self.repo_root / pkg_name
        
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            self.failed_packages.append(pkg_name)
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            self.failed_packages.append(pkg_name)
            return False
        
        # Extract version info from SRCINFO
        try:
            pkgver, pkgrel, epoch = self.build_engine.extract_version_from_srcinfo(pkg_dir)
            version = self.build_engine.get_full_version_string(pkgver, pkgrel, epoch)
            
            # Verify package state
            pkg_type = "aur" if is_aur else "local"
            needs_build, remote_version = self.repo_manager.verify_package_state(
                pkg_name, pkg_type, version, self.vps_client, self.build_engine
            )
            
            if not needs_build:
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                return False
            
            logger.info(f"ℹ️ {pkg_name}: building {version}")
            
        except Exception as e:
            logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        try:
            # PRE-BUILD: Check dependency satisfaction
            logger.info(f"🔍 Checking dependencies for {pkg_name}...")
            deps_satisfied, missing_deps = self._check_dependency_satisfaction(pkg_name, pkg_dir, is_aur)
            
            if not deps_satisfied and attempt == 1:
                logger.warning(f"⚠️ {pkg_name}: Missing dependencies, will try again later")
                # Return False but don't mark as failed yet
                return False
            
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self.build_engine.clean_workspace(pkg_dir)
            
            # Build package with dependency installation
            build_result = self._run_cmd(
                f"makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600,
                extra_env={"PACKAGER": self.packager_id},
                user="builder"
            )
            
            if build_result.returncode == 0:
                # Move built packages to output directory
                moved = False
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    logger.info(f"✅ Built: {pkg_file.name}")
                    built_files.append(pkg_file.name)
                    
                    # Update state
                    self.repo_manager.update_package_state(pkg_name, version, pkg_file.name, self.vps_client)
                    
                    # Add to dependency map for other packages
                    self.dependency_map[pkg_name] = version
                    moved = True
                
                if is_aur:
                    # Clean up AUR directory after successful build
                    shutil.rmtree(pkg_dir, ignore_errors=True)
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    if is_aur:
                        self.stats["aur_success"] += 1
                    else:
                        self.stats["local_success"] += 1
                    
                    # Update local database immediately for inter-package dependencies
                    if built_files:
                        self._update_local_database()
                    
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    if is_aur:
                        self.stats["aur_failed"] += 1
                    else:
                        self.stats["local_failed"] += 1
                    self.failed_packages.append(pkg_name)
                    return False
            else:
                error_msg = build_result.stderr[:500] if build_result.stderr else build_result.stdout[:500] if build_result.stdout else "Unknown error"
                logger.error(f"Failed to build {pkg_name}: {error_msg}")
                if is_aur:
                    self.stats["aur_failed"] += 1
                else:
                    self.stats["local_failed"] += 1
                self.failed_packages.append(pkg_name)
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            if is_aur:
                self.stats["aur_failed"] += 1
            else:
                self.stats["local_failed"] += 1
            self.failed_packages.append(pkg_name)
            return False
    
    def _update_local_database(self):
        """Update local database after each build for inter-package dependencies"""
        try:
            # Create a simple local database for dependencies
            old_cwd = os.getcwd()
            os.chdir(self.output_dir)
            
            # Generate temporary database
            db_file = f"{self.repo_name}.db.tar.gz"
            cmd = f"repo-add {db_file} *.pkg.tar.* 2>/dev/null || true"
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            os.chdir(old_cwd)
            
            if result.returncode == 0:
                logger.debug("✅ Updated local package database")
            else:
                logger.debug("ℹ️ Local database update skipped (no packages or error)")
                
        except Exception as e:
            logger.debug(f"Local database update error (non-critical): {e}")
    
    def _sync_state_to_git(self):
        """
        Git Sync Phase (The Sandbox Push) - FIXED VERSION
        
        If vps_state.json changed, push it to the repository from a clean clone
        to avoid detached HEAD or dirty tree issues.
        """
        logger.info("\n" + "=" * 60)
        logger.info("🔄 GIT STATE SYNCHRONIZATION")
        logger.info("=" * 60)
        
        # Check if state file exists and has changed
        state_file = self.repo_manager.build_tracking_dir / "vps_state.json"
        if not state_file.exists():
            logger.info("ℹ️ No state file to sync")
            return
        
        # Determine which repository URL to use
        repo_url = self.ssh_repo_url if self.ssh_repo_url else os.getenv('GITHUB_REPO', '')
        if not repo_url:
            logger.warning("⚠️ No repository URL configured, skipping git sync")
            return
        
        logger.info(f"Using repository URL: {repo_url}")
        
        # Create temporary directory for clean clone
        temp_dir = Path("/tmp/state_sync")
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        try:
            temp_dir.mkdir(parents=True)
            
            # Setup SSH environment for git
            env = os.environ.copy()
            ssh_key_path = "/home/builder/.ssh/id_ed25519"
            
            if os.path.exists(ssh_key_path):
                # Set GIT_SSH_COMMAND to use our SSH key
                env['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key_path} -o StrictHostKeyChecking=no'
                logger.info(f"🔑 Using SSH key: {ssh_key_path}")
            else:
                logger.warning("⚠️ SSH key not found, trying without explicit key")
            
            # Clone the repository with depth 1 for speed
            logger.info(f"📥 Cloning repository: {repo_url}")
            clone_cmd = ["git", "clone", "--depth", "1", repo_url, str(temp_dir)]
            
            clone_result = subprocess.run(
                clone_cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
                check=False,
                cwd="/tmp"
            )
            
            if clone_result.returncode != 0:
                logger.error(f"❌ Failed to clone repository: {clone_result.stderr[:200]}")
                
                # Try alternative approach with git URL conversion
                if "github.com" in repo_url and repo_url.startswith("git@"):
                    # Convert SSH URL to HTTPS
                    https_url = repo_url.replace("git@github.com:", "https://github.com/")
                    logger.info(f"🔄 Trying HTTPS URL: {https_url}")
                    
                    clone_cmd = ["git", "clone", "--depth", "1", https_url, str(temp_dir)]
                    clone_result = subprocess.run(
                        clone_cmd,
                        capture_output=True,
                        text=True,
                        timeout=300,
                        check=False,
                        cwd="/tmp"
                    )
                    
                    if clone_result.returncode != 0:
                        logger.error(f"❌ HTTPS clone also failed: {clone_result.stderr[:200]}")
                        return
                else:
                    return
            
            logger.info("✅ Repository cloned successfully")
            
            # Copy the state file
            dest_state_dir = temp_dir / ".build_tracking"
            dest_state_dir.mkdir(exist_ok=True)
            shutil.copy2(state_file, dest_state_dir / "vps_state.json")
            
            # Configure git
            subprocess.run(["git", "config", "user.email", "builder@github-actions.com"], 
                         cwd=temp_dir, check=False)
            subprocess.run(["git", "config", "user.name", "GitHub Actions Builder"], 
                         cwd=temp_dir, check=False)
            
            # Add and commit
            subprocess.run(["git", "add", ".build_tracking/vps_state.json"], 
                         cwd=temp_dir, check=False)
            
            commit_result = subprocess.run(
                ["git", "commit", "-m", "Update VPS package state JSON"],
                cwd=temp_dir,
                capture_output=True,
                text=True,
                check=False
            )
            
            if commit_result.returncode == 0:
                logger.info("✅ Changes committed")
                
                # Push with SSH environment
                push_result = subprocess.run(
                    ["git", "push"],
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False
                )
                
                if push_result.returncode == 0:
                    logger.info("✅ State file pushed to repository")
                else:
                    logger.error(f"❌ Failed to push: {push_result.stderr[:200]}")
                    
                    # Try with force if it's a simple fast-forward issue
                    if "non-fast-forward" in push_result.stderr:
                        logger.info("🔄 Trying with --force-with-lease")
                        force_result = subprocess.run(
                            ["git", "push", "--force-with-lease"],
                            cwd=temp_dir,
                            capture_output=True,
                            text=True,
                            env=env,
                            check=False
                        )
                        if force_result.returncode == 0:
                            logger.info("✅ Force push successful")
                        else:
                            logger.error(f"❌ Force push failed: {force_result.stderr[:200]}")
            else:
                logger.info("ℹ️ No changes to commit (state file unchanged)")
                
        except Exception as e:
            logger.error(f"❌ Git sync error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # Clean up
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def run(self):
        """Main execution with JSON State Tracking"""
        logger.info("\n" + "=" * 60)
        logger.info("🚀 MANJARO PACKAGE BUILDER (JSON STATE TRACKING)")
        logger.info("=" * 60)
        
        try:
            logger.info("\n🔧 Initial setup...")
            logger.info(f"Repository root: {self.repo_root}")
            logger.info(f"Repository name: {self.repo_name}")
            logger.info(f"Output directory: {self.output_dir}")
            logger.info(f"PACKAGER identity: {self.packager_id}")
            
            # STEP 0: Initialize GPG FIRST if enabled
            logger.info("\n" + "=" * 60)
            logger.info("STEP 0: GPG INITIALIZATION")
            logger.info("=" * 60)
            if self.gpg_handler.gpg_enabled:
                if not self.gpg_handler.import_gpg_key():
                    logger.error("❌ Failed to import GPG key, disabling signing")
                else:
                    logger.info("✅ GPG initialized successfully")
            else:
                logger.info("ℹ️ GPG signing disabled (no key provided)")
            
            # STEP 1: Check repository state on VPS
            logger.info("\n" + "=" * 60)
            logger.info("STEP 1: REPOSITORY STATE CHECK")
            logger.info("=" * 60)
            
            repo_exists, has_packages = self.vps_client.check_repository_exists_on_vps()
            
            # CRITICAL FIX: Enable repository AND sync pacman databases
            self._enable_custom_repository(repo_exists, has_packages)
            
            # Ensure remote directory exists
            self.vps_client.ensure_remote_directory()
            
            # Download existing state file from VPS
            self.vps_client.download_state_file(self.repo_manager.state_file)
            
            # STEP 2: List remote packages for state migration
            remote_packages = self.vps_client.list_remote_packages()
            self.repo_manager.set_remote_packages_cache(remote_packages)
            
            # STEP 3: AUR Fetch Phase (CRITICAL: before state migration)
            logger.info("\n" + "=" * 60)
            logger.info("STEP 2: AUR FETCH PHASE")
            logger.info("=" * 60)
            
            local_packages, aur_packages = self.get_package_lists()
            if aur_packages:
                if not self._fetch_aur_packages(aur_packages):
                    logger.warning("⚠️ Some AUR packages failed to fetch")
            
            # STEP 4: State Migration Phase
            logger.info("\n" + "=" * 60)
            logger.info("STEP 3: STATE MIGRATION PHASE")
            logger.info("=" * 60)
            
            migration_results = self.repo_manager.migrate_state(
                self.vps_client, local_packages, aur_packages, self.build_engine
            )
            self.adopted_packages = migration_results["adopted"]
            self.packages_to_build = migration_results["to_build"]
            
            # STEP 5: Build Phase with dependency handling
            logger.info("\n" + "=" * 60)
            logger.info("STEP 4: BUILD PHASE WITH DEPENDENCY CHECKING")
            logger.info("=" * 60)
            
            logger.info(f"📦 Package statistics:")
            logger.info(f"   Local packages: {len(local_packages)}")
            logger.info(f"   AUR packages: {len(aur_packages)}")
            logger.info(f"   Adopted packages: {len(self.adopted_packages)}")
            logger.info(f"   Packages to build: {len(self.packages_to_build)}")
            
            # Build packages in multiple passes to handle dependencies
            max_passes = 3
            remaining_packages = aur_packages + local_packages
            
            for pass_num in range(1, max_passes + 1):
                if not remaining_packages:
                    break
                
                logger.info(f"\n🔄 Build pass {pass_num}/{max_passes}")
                successful_this_pass = []
                
                for pkg in list(remaining_packages):
                    is_aur = pkg in aur_packages
                    success = self._build_single_package(pkg, is_aur, attempt=pass_num)
                    
                    if success:
                        successful_this_pass.append(pkg)
                
                # Remove successfully built packages
                for pkg in successful_this_pass:
                    if pkg in remaining_packages:
                        remaining_packages.remove(pkg)
                
                logger.info(f"Pass {pass_num}: Built {len(successful_this_pass)} packages, {len(remaining_packages)} remaining")
                
                # Sync pacman databases between passes
                if remaining_packages and pass_num < max_passes:
                    logger.info("🔄 Syncing pacman databases between passes...")
                    subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm"], 
                                 capture_output=True, timeout=60, check=False)
                    self.stats["pacman_syncs"] += 1
            
            # Report any still-failed packages
            if self.failed_packages:
                logger.warning(f"\n⚠️ {len(self.failed_packages)} packages failed to build:")
                for pkg in self.failed_packages:
                    logger.warning(f"  - {pkg}")
            
            # Check if we have any built packages
            built_files = list(self.output_dir.glob("*.pkg.tar.*"))
            if built_files:
                logger.info("\n" + "=" * 60)
                logger.info("STEP 5: REPOSITORY DATABASE GENERATION")
                logger.info("=" * 60)
                
                # Generate final database
                if self.repo_manager.generate_full_database():
                    # Sign repository database files if GPG is enabled
                    if self.gpg_handler.gpg_enabled:
                        if not self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir)):
                            logger.warning("⚠️ Failed to sign repository files, continuing anyway")
                    
                    # Upload packages and database
                    files_to_upload = [str(f) for f in self.output_dir.glob("*")]
                    if files_to_upload:
                        logger.info(f"📤 Uploading {len(files_to_upload)} files to VPS...")
                        upload_success = self.vps_client.upload_files(files_to_upload, self.output_dir)
                        
                        if upload_success:
                            # Upload state file to VPS
                            self.vps_client.upload_state_file(self.repo_manager.state_file)
                            
                            # Final pacman sync
                            logger.info("\n" + "=" * 60)
                            logger.info("STEP 6: FINAL PACMAN DATABASE SYNC")
                            logger.info("=" * 60)
                            
                            subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm"], 
                                         capture_output=True, timeout=120, check=False)
                            self.stats["pacman_syncs"] += 1
                            
                            # STEP 7: Git Sync Phase
                            self._sync_state_to_git()
                            
                            logger.info("\n✅ Build completed successfully!")
                        else:
                            logger.error("❌ Upload failed!")
                    else:
                        logger.error("❌ No files to upload!")
                else:
                    logger.error("❌ Database generation failed!")
            else:
                if not self.failed_packages:
                    logger.info("\n📊 Build summary:")
                    logger.info(f"   AUR packages built: {self.stats['aur_success']}")
                    logger.info(f"   AUR packages failed: {self.stats['aur_failed']}")
                    logger.info(f"   Local packages built: {self.stats['local_success']}")
                    logger.info(f"   Local packages failed: {self.stats['local_failed']}")
                    logger.info(f"   Total skipped: {len(self.skipped_packages)}")
                    logger.info(f"   Adopted packages: {len(self.adopted_packages)}")
                    
                    if self.stats['aur_failed'] > 0 or self.stats['local_failed'] > 0:
                        logger.warning("⚠️ Some packages failed to build")
                    else:
                        logger.info("✅ All packages are up to date!")
                else:
                    logger.error("\n❌ Build failed with errors!")
            
            # Clean up GPG
            self.gpg_handler.cleanup()
            
            elapsed = time.time() - self.stats["start_time"]
            
            logger.info("\n" + "=" * 60)
            logger.info("📊 BUILD SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Duration: {elapsed:.1f}s")
            logger.info(f"AUR packages:    {self.stats['aur_success']} (failed: {self.stats['aur_failed']})")
            logger.info(f"Local packages:  {self.stats['local_success']} (failed: {self.stats['local_failed']})")
            logger.info(f"Total built:     {self.stats['aur_success'] + self.stats['local_success']}")
            logger.info(f"Skipped:         {len(self.skipped_packages)}")
            logger.info(f"Adopted:         {len(self.adopted_packages)}")
            logger.info(f"Failed:          {len(self.failed_packages)}")
            logger.info(f"Dependency checks: {self.stats['dependency_checks']}")
            logger.info(f"Pacman syncs:    {self.stats['pacman_syncs']}")
            logger.info(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            logger.info(f"JSON State:      ✅ Efficient tracking active")
            logger.info(f"Dependency handling: ✅ Multi-pass build system")
            logger.info("=" * 60)
            
            if self.built_packages:
                logger.info("\n📦 Built packages:")
                for pkg in self.built_packages:
                    logger.info(f"  - {pkg}")
            
            # Return success if no critical failures
            return 0 if len(self.failed_packages) == 0 else 1
            
        except Exception as e:
            logger.error(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            # Ensure GPG cleanup even on failure
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            return 1


if __name__ == "__main__":
    sys.exit(PackageBuilder().run())