"""
Package Builder Module - Main orchestrator for package building coordination
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import glob
from pathlib import Path
from typing import List, Optional, Tuple

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

# Import our modules - adjust imports to work from the modules directory
try:
    from modules.common.logging_utils import setup_logger
    logger = setup_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

from modules.common.config_loader import ConfigLoader
from modules.common.environment import EnvironmentValidator
from modules.common.shell_executor import ShellExecutor
from modules.build.artifact_manager import ArtifactManager
from modules.build.aur_builder import AURBuilder
from modules.build.local_builder import LocalBuilder
from modules.build.version_manager import VersionManager
from modules.build.build_tracker import BuildTracker
from modules.gpg.gpg_handler import GPGHandler
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient
from modules.repo.cleanup_manager import CleanupManager
from modules.repo.database_manager import DatabaseManager
from modules.repo.version_tracker import VersionTracker


class PackageBuilder:
    """Main orchestrator that coordinates between modules for package building"""
    
    def __init__(self):
        # Run pre-flight environment validation
        EnvironmentValidator.validate_env()
        
        # Load configuration
        self.config_loader = ConfigLoader()
        self.repo_root = self.config_loader.get_repo_root()
        env_config = self.config_loader.load_environment_config()
        python_config = self.config_loader.load_from_python_config()
        
        # Store configuration
        self.vps_user = env_config['vps_user']
        self.vps_host = env_config['vps_host']
        self.ssh_key = env_config['ssh_key']
        self.repo_server_url = env_config['repo_server_url']
        self.remote_dir = env_config['remote_dir']
        self.repo_name = env_config['repo_name']
        
        self.output_dir = self.repo_root / python_config['output_dir']
        self.build_tracking_dir = self.repo_root / python_config['build_tracking_dir']
        self.mirror_temp_dir = Path(python_config['mirror_temp_dir'])
        self.sync_clone_dir = Path(python_config['sync_clone_dir'])
        self.aur_urls = python_config['aur_urls']
        self.aur_build_dir = self.repo_root / python_config['aur_build_dir']
        self.ssh_options = python_config['ssh_options']
        self.github_repo = python_config['github_repo']
        self.packager_id = python_config['packager_id']
        self.debug_mode = python_config['debug_mode']
        
        # Create directories
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
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
    
    def _init_modules(self):
        """Initialize all modules with configuration"""
        try:
            # VPS modules
            vps_config = {
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
                'remote_dir': self.remote_dir,
                'ssh_options': self.ssh_options,
                'repo_name': self.repo_name,
            }
            self.ssh_client = SSHClient(vps_config)
            self.ssh_client.setup_ssh_config(self.ssh_key)
            
            self.rsync_client = RsyncClient(vps_config)
            
            # Repository modules
            repo_config = {
                'repo_name': self.repo_name,
                'output_dir': self.output_dir,
                'remote_dir': self.remote_dir,
                'mirror_temp_dir': self.mirror_temp_dir,
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
            }
            self.cleanup_manager = CleanupManager(repo_config)
            self.database_manager = DatabaseManager(repo_config)
            self.version_tracker = VersionTracker(repo_config)
            
            # Build modules
            self.artifact_manager = ArtifactManager()
            self.aur_builder = AURBuilder(self.debug_mode)
            self.local_builder = LocalBuilder(self.debug_mode)
            self.version_manager = VersionManager()
            self.build_tracker = BuildTracker()
            
            # GPG Handler
            self.gpg_handler = GPGHandler()
            
            # Shell executor
            self.shell_executor = ShellExecutor(self.debug_mode)
            
            logger.info("✅ All modules initialized successfully")
            
        except NameError as e:
            logger.error(f"❌ NameError during module initialization: {e}")
            logger.error("This indicates missing imports in module files")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Error initializing modules: {e}")
            sys.exit(1)
    
    def get_package_lists(self):
        """Get package lists from packages.py or exit if not available"""
        try:
            # First try to import from the current directory
            import packages
            print("📦 Using package lists from packages.py")
            local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
            print(f">>> DEBUG: Found {len(local_packages_list + aur_packages_list)} packages to check")
            return local_packages_list, aur_packages_list
        except ImportError:
            try:
                # Try to import from parent directory
                import sys
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                import scripts.packages as packages
                print("📦 Using package lists from packages.py")
                local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
                print(f">>> DEBUG: Found {len(local_packages_list + aur_packages_list)} packages to check")
                return local_packages_list, aur_packages_list
            except ImportError:
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
            
            # CRITICAL FIX: Run pacman -Syy after enabling repository to force refresh
            if exists and has_packages:
                logger.info("🔄 Synchronizing pacman databases after enabling repository...")
                
                # CRITICAL FIX: Update pacman-key database first
                cmd = "sudo pacman-key --updatedb"
                result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
                if result.returncode != 0:
                    logger.warning(f"⚠️ pacman-key --updatedb warning: {result.stderr[:200]}")
                
                cmd = "sudo LC_ALL=C pacman -Syy --noconfirm"
                result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
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
        exists, has_packages = self.ssh_client.check_repository_exists_on_vps()
        self._apply_repository_state(exists, has_packages)
        
        if not exists:
            logger.info("ℹ️ Repository doesn't exist on VPS, skipping pacman sync")
            return False
        
        # CRITICAL FIX: Update pacman-key database first
        cmd = "sudo pacman-key --updatedb"
        result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
        if result.returncode != 0:
            logger.warning(f"⚠️ pacman-key --updatedb warning: {result.stderr[:200]}")
        
        # CRITICAL FIX: Use Syy to force refresh instead of Sy
        cmd = "sudo LC_ALL=C pacman -Syy --noconfirm"
        result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
        
        if result.returncode == 0:
            logger.info("✅ Pacman databases synced successfully")
            
            # Debug: List packages in our custom repo
            debug_cmd = f"sudo pacman -Sl {self.repo_name}"
            logger.info(f"🔍 DEBUG: Running command to see what packages pacman sees in our repo:")
            logger.info(f"Command: {debug_cmd}")
            
            debug_result = self.shell_executor.run_command(debug_cmd, log_cmd=True, timeout=30, check=False)
            
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
    
    def package_exists(self, pkg_name: str, version=None) -> bool:
        """Check if package exists on server"""
        return self.version_tracker.package_exists(pkg_name, self.remote_files)
    
    def get_remote_version(self, pkg_name: str) -> Optional[str]:
        """Get the version of a package from remote server using SRCINFO-based extraction"""
        return self.version_tracker.get_remote_version(pkg_name, self.remote_files)
    
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
            result = self.shell_executor.run_command(
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
        self.shell_executor.run_command(f"chown -R builder:builder {pkg_dir}", check=False)
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
        
        # Extract version info from SRCINFO (not regex)
        try:
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
            version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            # Get remote version for comparison
            remote_version = self.get_remote_version(pkg_name)
            
            # DECISION LOGIC: Only build if AUR_VERSION > REMOTE_VERSION
            if remote_version and not self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch):
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                
                # ZERO-RESIDUE FIX: Register the target version for this skipped package
                self.version_tracker.register_skipped_package(pkg_name, remote_version)
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files BEFORE building new version
                self.cleanup_manager.pre_build_purge_old_versions(pkg_name, remote_version)
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
                
        except Exception as e:
            logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self.artifact_manager.clean_workspace(pkg_dir)
            
            print("Downloading sources...")
            source_result = self.shell_executor.run_command(f"makepkg -od --noconfirm", 
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
            build_result = self.shell_executor.run_command(
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
                    
                    # CRITICAL FIX: Use Syy for dependency resolution
                    deps_str = ' '.join(missing_deps)
                    yay_cmd = f"LC_ALL=C yay -Syy --needed --noconfirm {deps_str}"
                    yay_result = self.shell_executor.run_command(yay_cmd, log_cmd=True, check=False, user="builder", timeout=1800)
                    
                    if yay_result.returncode == 0:
                        logger.info("✅ Missing dependencies installed via yay, retrying build...")
                        
                        # Retry the build
                        build_result = self.shell_executor.run_command(
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
                    self.version_tracker.register_package_target_version(pkg_name, version)
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
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
            version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            # Get remote version for comparison
            remote_version = self.get_remote_version(pkg_name)
            
            # DECISION LOGIC: Only build if AUR_VERSION > REMOTE_VERSION
            if remote_version and not self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch):
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                
                # ZERO-RESIDUE FIX: Register the target version for this skipped package
                self.version_tracker.register_skipped_package(pkg_name, remote_version)
                
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files BEFORE building new version
                self.cleanup_manager.pre_build_purge_old_versions(pkg_name, remote_version)
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
                
        except Exception as e:
            logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self.artifact_manager.clean_workspace(pkg_dir)
            
            print("Downloading sources...")
            source_result = self.shell_executor.run_command(f"makepkg -od --noconfirm", 
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
            build_result = self.shell_executor.run_command(
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
                    
                    # CRITICAL FIX: Use Syy for dependency resolution
                    deps_str = ' '.join(missing_deps)
                    yay_cmd = f"LC_ALL=C yay -Syy --needed --noconfirm {deps_str}"
                    yay_result = self.shell_executor.run_command(yay_cmd, log_cmd=True, check=False, user="builder", timeout=1800)
                    
                    if yay_result.returncode == 0:
                        logger.info("✅ Missing dependencies installed via yay, retrying build...")
                        
                        # Retry the build
                        build_result = self.shell_executor.run_command(
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
                    self.version_tracker.register_package_target_version(pkg_name, version)
                    
                    # Collect metadata for hokibot
                    if built_files:
                        # Simplified metadata extraction
                        filename = os.path.basename(built_files[0])
                        self.build_tracker.add_hokibot_data(pkg_name, pkgver, pkgrel, epoch)
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
                self.build_tracker.record_built_package(pkg, "unknown", is_aur=True)
            else:
                self.stats["aur_failed"] += 1
                self.build_tracker.record_failed_package(is_aur=True)
        
        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self._build_single_package(pkg, is_aur=False):
                self.stats["local_success"] += 1
                self.build_tracker.record_built_package(pkg, "unknown", is_aur=False)
            else:
                self.stats["local_failed"] += 1
                self.build_tracker.record_failed_package(is_aur=False)
        
        return self.stats["aur_success"] + self.stats["local_success"]
    
    def upload_packages(self) -> bool:
        """Upload packages to server using RSYNC WITHOUT --delete flag"""
        # Get all package files and database files
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
        
        all_files = pkg_files + db_files
        
        if not all_files:
            logger.warning("No files to upload")
            self.version_tracker.set_upload_successful(False)
            return False
        
        # Ensure remote directory exists
        self.ssh_client.ensure_remote_directory()
        
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
            self.version_tracker.set_upload_successful(False)
            return False
        
        # Upload files using Rsync client
        upload_success = self.rsync_client.upload_files(files_to_upload, self.output_dir)
        
        # Set upload success flag for cleanup
        self.version_tracker.set_upload_successful(upload_success)
        
        return upload_success
    
    def create_artifact_archive_for_github(self) -> Optional[Path]:
        """
        Create a tar.gz archive of all built artifacts for GitHub upload.
        This avoids issues with colon (:) characters in package filenames.
        """
        log_path = Path("builder.log")
        return self.artifact_manager.create_artifact_archive(self.output_dir, log_path)
    
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
            repo_exists, has_packages = self.ssh_client.check_repository_exists_on_vps()
            
            # Apply repository state based on discovery
            self._apply_repository_state(repo_exists, has_packages)
            
            # Ensure remote directory exists
            self.ssh_client.ensure_remote_directory()
            
            # STEP 2: List remote packages for version comparison
            remote_packages = self.ssh_client.list_remote_packages()
            self.remote_files = [os.path.basename(f) for f in remote_packages] if remote_packages else []
            
            # MANDATORY STEP: Mirror ALL remote packages locally before any database operations
            if remote_packages:
                print("\n" + "=" * 60)
                print("MANDATORY PRECONDITION: Mirroring remote packages locally")
                print("=" * 60)
                
                if not self.rsync_client.mirror_remote_packages(self.mirror_temp_dir, self.output_dir):
                    logger.error("❌ FAILED to mirror remote packages locally")
                    logger.error("Cannot proceed without local package mirror")
                    return 1
            else:
                logger.info("ℹ️ No remote packages to mirror (repository appears empty)")
            
            # STEP 3: Check existing database files
            existing_db_files, missing_db_files = self.database_manager.check_database_files()
            
            # Fetch existing database if available
            if existing_db_files:
                self.database_manager.fetch_existing_database(existing_db_files)
            
            # Build packages
            print("\n" + "=" * 60)
            print("STEP 5: PACKAGE BUILDING (SRCINFO VERSIONING)")
            print("=" * 60)
            
            total_built = self.build_packages()
            
            # Check if we have any packages locally (mirrored + newly built)
            local_packages = self.database_manager._get_all_local_packages()
            
            if local_packages or remote_packages:
                print("\n" + "=" * 60)
                print("STEP 6: REPOSITORY DATABASE HANDLING (WITH LOCAL MIRROR)")
                print("=" * 60)
                
                # ZERO-RESIDUE FIX: Perform server cleanup BEFORE database generation
                print("\n" + "=" * 60)
                print("🚨 PRE-DATABASE CLEANUP: Removing zombie packages from server")
                print("=" * 60)
                self.cleanup_manager.server_cleanup(self.version_tracker)
                
                # Generate database with ALL locally available packages
                if self.database_manager.generate_full_database(self.repo_name, self.output_dir, self.cleanup_manager):
                    # Sign repository database files if GPG is enabled
                    if self.gpg_handler.gpg_enabled:
                        if not self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir)):
                            logger.warning("⚠️ Failed to sign repository files, continuing anyway")
                    
                    # Upload regenerated database and packages
                    if not self.ssh_client.test_ssh_connection():
                        logger.warning("SSH test failed, but trying upload anyway...")
                    
                    # Upload everything (packages + database + signatures)
                    upload_success = self.upload_packages()
                    
                    # ZERO-RESIDUE FIX: Perform final server cleanup AFTER upload
                    if upload_success:
                        print("\n" + "=" * 60)
                        print("🚨 POST-UPLOAD CLEANUP: Final zombie package removal")
                        print("=" * 60)
                        self.cleanup_manager.server_cleanup(self.version_tracker)
                    
                    # Clean up GPG temporary directory
                    self.gpg_handler.cleanup()
                    
                    if upload_success:
                        # STEP 7: Update repository state and sync pacman
                        print("\n" + "=" * 60)
                        print("STEP 7: FINAL REPOSITORY STATE UPDATE")
                        print("=" * 60)
                        
                        # Re-check repository state (it should exist now)
                        repo_exists, has_packages = self.ssh_client.check_repository_exists_on_vps()
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
            
            # STEP 8: Create artifact archive for GitHub upload
            print("\n" + "=" * 60)
            print("STEP 8: CREATING ARTIFACT ARCHIVE FOR GITHUB")
            print("=" * 60)
            
            artifact_archive = self.create_artifact_archive_for_github()
            if artifact_archive:
                logger.info(f"✅ Artifact archive created: {artifact_archive.name}")
                logger.info("📦 Upload this archive to GitHub to avoid colon character issues")
            else:
                logger.warning("⚠️ Failed to create artifact archive")
            
            elapsed = time.time() - self.stats["start_time"]
            summary = self.build_tracker.get_summary()
            
            print("\n" + "=" * 60)
            print("📊 BUILD SUMMARY")
            print("=" * 60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {summary['aur_success']} (failed: {summary['aur_failed']})")
            print(f"Local packages:  {summary['local_success']} (failed: {summary['local_failed']})")
            print(f"Total built:     {summary['total_built']}")
            print(f"Skipped:         {summary['skipped']}")
            print(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            print(f"PACKAGER:        {self.packager_id}")
            print(f"Zero-Residue:    ✅ Exact-filename-match cleanup active")
            print(f"Target Version:  ✅ Package target versions registered: {len(self.version_tracker._package_target_versions)}")
            print(f"Skipped Registry:✅ Skipped packages tracked: {len(self.version_tracker._skipped_packages)}")
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