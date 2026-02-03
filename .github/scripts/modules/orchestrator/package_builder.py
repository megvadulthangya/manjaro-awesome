"""
Package Builder Module - Main orchestrator for package building coordination
WITH CACHE-AWARE BUILDING
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import glob
import json
import urllib.request
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
    """Main orchestrator that coordinates between modules for package building WITH CACHE SUPPORT"""
    
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
        self.sign_packages = python_config['sign_packages']
        
        # Cache configuration
        self.use_cache = os.getenv('USE_CACHE', 'false').lower() == 'true'
        
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
            "cache_hits": 0,
            "cache_misses": 0,
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
            self.gpg_handler = GPGHandler(self.sign_packages)
            
            # Shell executor
            self.shell_executor = ShellExecutor(self.debug_mode)
            
            # Package builder from modules/build/package_builder.py
            from modules.build.package_builder import create_package_builder
            self.package_builder = create_package_builder(
                packager_id=self.packager_id,
                output_dir=self.output_dir,
                gpg_key_id=env_config.get('gpg_key_id'),
                gpg_private_key=env_config.get('gpg_private_key'),
                sign_packages=self.sign_packages,
                debug_mode=self.debug_mode,
                version_tracker=self.version_tracker,
                vps_files=self.remote_files  # NEW: Pass VPS file inventory
            )
            
            logger.info("✅ All modules initialized successfully")
            logger.info(f"📝 Package signing: {'ENABLED' if self.sign_packages else 'DISABLED'}")
            
            # Log cache status
            if self.use_cache:
                logger.info("🔧 CACHE: Cache-aware building ENABLED")
                # Check cache status
                built_count = len(list(self.output_dir.glob("*.pkg.tar.*")))
                logger.info(f"🔧 CACHE: Found {built_count} cached package files in output_dir")
            else:
                logger.info("🔧 CACHE: Cache-aware building DISABLED")
            
        except NameError as e:
            logger.error(f"❌ NameError during module initialization: {e}")
            logger.error("This indicates missing imports in module files")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Error initializing modules: {e}")
            sys.exit(1)
    
    def phase_i_vps_sync(self) -> bool:
        """
        Phase I: VPS State Fetch
        - List VPS repo files
        - Sync missing files locally
        """
        logger.info("PHASE I: VPS State Fetch")
        
        # Test SSH connection
        if not self.ssh_client.test_ssh_connection():
            logger.warning("SSH connection test failed")
        
        # Ensure remote directory exists
        self.ssh_client.ensure_remote_directory()
        
        # List remote packages
        remote_packages = self.ssh_client.list_remote_packages()
        self.remote_files = [os.path.basename(f) for f in remote_packages] if remote_packages else []
        
        # NEW: Also get signatures for completeness check
        remote_signatures = self._get_vps_signatures()
        self.remote_files.extend(remote_signatures)
        
        logger.info(f"Found {len(self.remote_files)} files on VPS (packages + signatures)")
        
        # Update package builder with VPS files
        self.package_builder.set_vps_files(self.remote_files)
        
        # Mirror remote packages locally
        if remote_packages:
            logger.info("Mirroring remote packages locally...")
            success = self.rsync_client.mirror_remote_packages(
                self.mirror_temp_dir,
                self.output_dir,
                remote_packages
            )
            if not success:
                logger.warning("Failed to mirror remote packages")
                return False
        
        return True
    
    def _get_vps_signatures(self) -> List[str]:
        """Get signature files from VPS for completeness check - FIX: include both regular files and symlinks"""
        logger.info("Fetching VPS signature file list...")
        
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found")
            return []
        
        # Get signature files - FIX: include both regular files and symlinks
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            rf'find "{self.remote_dir}" -maxdepth 1 \( -type f -o -type l \) -name "*.sig" -printf "%f\\n" 2>/dev/null || echo "NO_FILES"'
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip() and f.strip() != 'NO_FILES']
                logger.info(f"Found {len(files)} signature files on remote server")
                return files
            else:
                logger.warning(f"SSH find for signatures returned error")
                return []
                
        except Exception as e:
            logger.error(f"SSH command for signatures failed: {e}")
            return []
    
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
    
    def _check_cache_for_package(self, pkg_name: str, is_aur: bool) -> Tuple[bool, Optional[str]]:
        """
        Check if package is available in cache and up-to-date.
        
        Args:
            pkg_name: Package name
            is_aur: Whether it's an AUR package
        
        Returns:
            Tuple of (cached: bool, version: Optional[str])
        """
        if not self.use_cache:
            return False, None
        
        # Check built packages cache first
        cache_patterns = [
            f"{self.output_dir}/{pkg_name}-*.pkg.tar.*",
            f"{self.output_dir}/*{pkg_name}*.pkg.tar.*"
        ]
        
        cached_files = []
        for pattern in cache_patterns:
            cached_files.extend(glob.glob(pattern))
        
        if cached_files:
            # Extract version from cached file
            for cached_file in cached_files:
                try:
                    # Parse version from filename
                    filename = os.path.basename(cached_file)
                    base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
                    parts = base.split('-')
                    
                    # Try to extract version
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
                                    cached_version = f"{epoch_part}:{version_part}-{release_part}"
                                    
                                    # Extract components for comparison
                                    epoch = epoch_part
                                    pkgver = version_part
                                    pkgrel = release_part
                                else:
                                    cached_version = f"{version_part}-{release_part}"
                                    
                                    # Extract components for comparison
                                    epoch = None
                                    pkgver = version_part
                                    pkgrel = release_part
                                
                                # Check if this cached version is newer than remote
                                remote_version = self.get_remote_version(pkg_name)
                                if remote_version:
                                    # Compare versions
                                    should_build = self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch)
                                    if not should_build:
                                        logger.info(f"📦 CACHE HIT: {pkg_name} (cached: {cached_version}, remote: {remote_version}) - SKIP BUILD")
                                        self.stats["cache_hits"] += 1
                                        return True, cached_version
                                    else:
                                        logger.info(f"📦 CACHE STALE: {pkg_name} (cached: {cached_version}, remote: {remote_version}) - NEEDS REBUILD")
                                        self.stats["cache_misses"] += 1
                                        return False, None
                                else:
                                    # No remote version, cache is valid
                                    logger.info(f"📦 CACHE HIT: {pkg_name} (cached: {cached_version}, no remote) - SKIP BUILD")
                                    self.stats["cache_hits"] += 1
                                    return True, cached_version
                except Exception as e:
                    logger.debug(f"Could not parse version from cached file {cached_file}: {e}")
        
        self.stats["cache_misses"] += 1
        return False, None
    
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
                    
                    # CRITICAL: MANDATORY pacman -Sy when repository is enabled with packages
                    # DO NOT REMOVE - required for pacman to recognize the newly enabled repository
                    logger.info("🔄 MANDATORY: Running pacman -Sy after enabling repository...")
                    cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
                    result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
                    
                    if result.returncode == 0:
                        logger.info("✅ Pacman databases synchronized successfully")
                    else:
                        logger.error("❌ Pacman sync failed - dependency installation cannot proceed")
                        logger.error(f"Error: {result.stderr[:500] if result.stderr else 'Unknown error'}")
                        # Fail fast: exit if pacman sync fails
                        raise RuntimeError("Pacman database sync failed after enabling repository")
                else:
                    new_lines.append("# SigLevel = Optional TrustAll")
                    new_lines.append("# Repository exists but has no packages yet")
                    logger.info("⚠️ Repository section added but commented (no packages yet)")
                    # DO NOT run pacman -Sy when repository is disabled or has no packages
                
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
                # DO NOT run pacman -Sy when repository is disabled
            
            # Write back to pacman.conf
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write('\n'.join(new_lines))
                temp_path = temp_file.name
            
            # Copy to pacman.conf
            subprocess.run(['sudo', 'cp', temp_path, str(pacman_conf)], check=False)
            subprocess.run(['sudo', 'chmod', '644', str(pacman_conf)], check=False)
            os.unlink(temp_path)
            
            logger.info(f"✅ Updated pacman.conf for repository '{self.repo_name}'")
            
        except Exception as e:
            logger.error(f"Failed to apply repository state: {e}")
            raise
    
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
        
        # Note: _apply_repository_state already runs pacman -Sy when enabling repo
        # No need to run it again here
        
        return True
    
    def _fetch_aur_version(self, pkg_name: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Fetch the current version of an AUR package using the AUR RPC API
        
        Args:
            pkg_name: Name of the AUR package
            
        Returns:
            Tuple of (pkgver, pkgrel, epoch) or None if failed
        """
        try:
            url = f"https://aur.archlinux.org/rpc/?v=5&type=info&arg[]={pkg_name}"
            logger.info(f"📡 Fetching AUR version for {pkg_name} from {url}")
            
            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                if data.get('resultcount', 0) > 0:
                    result = data['results'][0]
                    version = result.get('Version', '')
                    
                    if version:
                        logger.info(f"📦 AUR version for {pkg_name}: {version}")
                        
                        # Parse version string (e.g., "1.2.3-1" or "2:1.2.3-1")
                        if ':' in version:
                            epoch_part, rest = version.split(':', 1)
                            epoch = epoch_part.strip()
                        else:
                            epoch = None
                            rest = version
                        
                        if '-' in rest:
                            pkgver, pkgrel = rest.rsplit('-', 1)
                            pkgver = pkgver.strip()
                            pkgrel = pkgrel.strip()
                        else:
                            pkgver = rest.strip()
                            pkgrel = '1'
                        
                        return pkgver, pkgrel, epoch
                    else:
                        logger.warning(f"⚠️ No version found for {pkg_name} in AUR response")
                else:
                    logger.warning(f"⚠️ Package {pkg_name} not found in AUR")
                    
        except urllib.error.URLError as e:
            logger.error(f"❌ Network error fetching AUR version for {pkg_name}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON decode error for {pkg_name}: {e}")
        except Exception as e:
            logger.error(f"❌ Error fetching AUR version for {pkg_name}: {e}")
        
        return None
    
    def _get_local_version(self, pkg_dir: Path) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Get version from local PKGBUILD or .SRCINFO
        
        Args:
            pkg_dir: Path to package directory
            
        Returns:
            Tuple of (pkgver, pkgrel, epoch) or None if failed
        """
        try:
            return self.version_manager.extract_version_from_srcinfo(pkg_dir)
        except Exception as e:
            logger.error(f"❌ Failed to extract version from {pkg_dir}: {e}")
            
            # Fallback: try to parse PKGBUILD directly
            pkgbuild_path = pkg_dir / "PKGBUILD"
            if pkgbuild_path.exists():
                try:
                    with open(pkgbuild_path, 'r') as f:
                        content = f.read()
                    
                    # Simple regex to extract pkgver and pkgrel
                    pkgver_match = re.search(r'pkgver=([^\s\']+)', content)
                    pkgrel_match = re.search(r'pkgrel=([^\s\']+)', content)
                    epoch_match = re.search(r'epoch=([^\s\']+)', content)
                    
                    if pkgver_match and pkgrel_match:
                        pkgver = pkgver_match.group(1).strip('"\'')
                        pkgrel = pkgrel_match.group(1).strip('"\'')
                        epoch = epoch_match.group(1).strip('"\'') if epoch_match else None
                        
                        logger.info(f"📦 Parsed version from PKGBUILD: pkgver={pkgver}, pkgrel={pkgrel}, epoch={epoch}")
                        return pkgver, pkgrel, epoch
                    
                except Exception as e2:
                    logger.error(f"❌ Failed to parse PKGBUILD: {e2}")
            
            return None
    
    def package_exists(self, pkg_name: str, version=None) -> bool:
        """Check if package exists on server"""
        return self.version_tracker.package_exists(pkg_name, self.remote_files)
    
    def get_remote_version(self, pkg_name: str) -> Optional[str]:
        """Get the version of a package from remote server using SRCINFO-based extraction"""
        return self.version_tracker.get_remote_version(pkg_name, self.remote_files)
    
    def _sign_existing_packages_in_output_dir(self) -> Tuple[int, int, int]:
        """
        Sign existing packages in output_dir that don't have signatures.
        
        Returns:
            Tuple of (unsigned_packages_found, packages_signed, signing_failures)
        """
        if not self.gpg_handler.sign_packages_enabled:
            logger.info("Package signing disabled, skipping existing package signing")
            return 0, 0, 0
        
        logger.info("🔐 Scanning output_dir for unsigned packages...")
        
        # Find all package files in output_dir
        package_files = []
        for ext in ['.pkg.tar.zst', '.pkg.tar.xz']:
            package_files.extend(self.output_dir.glob(f"*{ext}"))
        
        unsigned_packages_found = 0
        packages_signed = 0
        signing_failures = 0
        
        for pkg_file in package_files:
            # Check if signature already exists
            sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
            if not sig_file.exists():
                unsigned_packages_found += 1
                logger.info(f"Found unsigned package: {pkg_file.name}")
                
                # Attempt to sign
                if self.gpg_handler.sign_package(str(pkg_file)):
                    packages_signed += 1
                    logger.info(f"Successfully signed: {pkg_file.name}")
                else:
                    signing_failures += 1
                    logger.error(f"Failed to sign: {pkg_file.name}")
        
        # Log summary (privacy-safe)
        logger.info(f"Existing package signing complete:")
        logger.info(f"  unsigned_packages_found: {unsigned_packages_found}")
        logger.info(f"  packages_signed: {packages_signed}")
        logger.info(f"  signing_failures: {signing_failures}")
        
        if unsigned_packages_found == 0:
            logger.info("✅ All packages in output_dir are already signed")
        elif signing_failures == 0:
            logger.info(f"✅ Successfully signed {packages_signed} previously unsigned packages")
        else:
            logger.warning(f"⚠️ Signed {packages_signed} packages but failed to sign {signing_failures}")
        
        return unsigned_packages_found, packages_signed, signing_failures
    
    def _build_aur_package(self, pkg_name: str) -> bool:
        """Build AUR package with proper version checking and signing"""
        # Step 1: Fetch current version from AUR
        aur_version_info = self._fetch_aur_version(pkg_name)
        if not aur_version_info:
            logger.error(f"❌ Failed to fetch AUR version for {pkg_name}")
            return False
        
        pkgver, pkgrel, epoch = aur_version_info
        aur_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
        
        # Step 2: Get remote version
        remote_version = self.get_remote_version(pkg_name)
        
        # Step 3: Compare versions
        if remote_version:
            should_build = self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch)
            if not should_build:
                # NEW: Check completeness of split packages on VPS
                # Need to extract package names from AUR PKGBUILD first
                temp_dir = None
                try:
                    temp_dir = tempfile.mkdtemp(prefix=f"aur_check_{pkg_name}_")
                    temp_path = Path(temp_dir)
                    
                    # Clone AUR package temporarily to check PKGBUILD
                    for aur_url_template in self.aur_urls:
                        aur_url = aur_url_template.format(pkg_name=pkg_name)
                        result = subprocess.run(
                            ["git", "clone", "--depth", "1", aur_url, str(temp_path)],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=300
                        )
                        if result.returncode == 0:
                            break
                    
                    # Extract package names
                    from modules.repo.manifest_factory import ManifestFactory
                    pkgbuild_content = ManifestFactory.get_pkgbuild(str(temp_path))
                    pkg_names = []
                    if pkgbuild_content:
                        pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)
                    
                    # Check completeness with FIXED epoch handling
                    is_complete = True
                    if pkg_names and len(pkg_names) > 1:
                        # This is a multi-package PKGBUILD, check completeness
                        is_complete = self._check_split_package_completeness(pkg_name, pkg_names, pkgver, pkgrel, epoch)
                    
                    if is_complete:
                        logger.info(f"✅ {pkg_name}: AUR version {aur_version} matches remote version {remote_version} - SKIPPING")
                        self.skipped_packages.append(f"{pkg_name} ({aur_version})")
                        self.version_tracker.register_split_packages(pkg_names, remote_version, is_built=False)
                        return False
                    else:
                        logger.info(f"🔄 {pkg_name}: Version matches but VPS is incomplete - FORCING BUILD")
                except Exception as e:
                    logger.warning(f"Could not check completeness for {pkg_name}: {e}")
                    # Fall back to regular skip if we can't check completeness
                    logger.info(f"✅ {pkg_name}: AUR version {aur_version} matches remote version {remote_version} - SKIPPING")
                    self.skipped_packages.append(f"{pkg_name} ({aur_version})")
                    # Try to get pkg_names from PKGBUILD if we have it cached
                    try:
                        pkg_names = [pkg_name]  # Default
                        self.version_tracker.register_split_packages(pkg_names, remote_version, is_built=False)
                    except:
                        pass
                    return False
                finally:
                    if temp_dir and Path(temp_dir).exists():
                        shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                logger.info(f"🔄 {pkg_name}: AUR version {aur_version} is NEWER than remote {remote_version} - BUILDING")
        else:
            logger.info(f"🔄 {pkg_name}: No remote version found, building AUR version {aur_version}")
        
        # Step 4: Clone and build using the package_builder module
        logger.info(f"🔨 Building {pkg_name} ({aur_version})...")
        
        # Use the package_builder module for building
        built, version, metadata = self.package_builder.audit_and_build_aur(
            pkg_name, remote_version, self.aur_build_dir
        )
        
        if built:
            self.built_packages.append(f"{pkg_name} ({version})")
            return True
        else:
            logger.error(f"❌ Failed to build {pkg_name}")
            return False
    
    def _check_split_package_completeness(self, pkgbuild_name: str, pkg_names: List[str], pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        NEW: Check if ALL split package artifacts exist on VPS.
        FIXED: Correct epoch handling (colon instead of hyphen)
        
        Args:
            pkgbuild_name: Name of the PKGBUILD (for logging)
            pkg_names: List of package names produced by the PKGBUILD
            pkgver: Package version
            pkgrel: Package release
            epoch: Package epoch (optional)
            
        Returns:
            True if all expected artifacts exist on VPS, False otherwise
        """
        if not self.remote_files:
            logger.warning(f"No VPS file inventory available for {pkgbuild_name}")
            return False
        
        missing_artifacts = []
        
        for pkg_name in pkg_names:
            # FIXED: Build correct version segment with colon for epoch
            if epoch and epoch != '0':
                version_segment = f"{epoch}:{pkgver}-{pkgrel}"
            else:
                version_segment = f"{pkgver}-{pkgrel}"
            
            # Build base pattern with correct version formatting
            base_pattern = f"{pkg_name}-{version_segment}"
            
            # Check for package files (any architecture, any compression)
            package_found = False
            for vps_file in self.remote_files:
                # Check if file starts with base_pattern and has package extension
                if vps_file.startswith(base_pattern) and (vps_file.endswith('.pkg.tar.zst') or vps_file.endswith('.pkg.tar.xz')):
                    package_found = True
                    # Check for corresponding signature
                    sig_file = vps_file + '.sig'
                    if sig_file not in self.remote_files:
                        missing_artifacts.append(f"{vps_file}.sig")
                    break
            
            if not package_found:
                missing_artifacts.append(f"{base_pattern}-*.pkg.tar.*")
        
        if missing_artifacts:
            example = missing_artifacts[0] if missing_artifacts else "unknown"
            logger.warning(f"FORCE BUILD (incomplete VPS): {pkgbuild_name} missing {len(missing_artifacts)} artifacts, e.g. {example}")
            return False
        
        logger.info(f"SKIP OK (complete VPS): {pkgbuild_name} all split artifacts present")
        return True
    
    def _build_local_package(self, pkg_name: str) -> bool:
        """Build local package with proper version checking and signing"""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"❌ Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"❌ No PKGBUILD found for {pkg_name}")
            return False
        
        # Step 1: Get local version from PKGBUILD
        local_version_info = self._get_local_version(pkg_dir)
        if not local_version_info:
            logger.error(f"❌ Failed to extract version for {pkg_name}")
            return False
        
        pkgver, pkgrel, epoch = local_version_info
        local_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
        
        # Step 2: Get remote version
        remote_version = self.get_remote_version(pkg_name)
        
        # Step 3: Compare versions
        if remote_version:
            should_build = self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch)
            if not should_build:
                # NEW: Check completeness of split packages on VPS
                # Extract package names from PKGBUILD
                from modules.repo.manifest_factory import ManifestFactory
                pkgbuild_content = ManifestFactory.get_pkgbuild(str(pkg_dir))
                pkg_names = []
                if pkgbuild_content:
                    pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)
                
                # Check completeness with FIXED epoch handling
                is_complete = True
                if pkg_names and len(pkg_names) > 1:
                    # This is a multi-package PKGBUILD, check completeness
                    is_complete = self._check_split_package_completeness(pkg_name, pkg_names, pkgver, pkgrel, epoch)
                
                if is_complete:
                    logger.info(f"✅ {pkg_name}: Local version {local_version} matches remote version {remote_version} - SKIPPING")
                    self.skipped_packages.append(f"{pkg_name} ({local_version})")
                    self.version_tracker.register_split_packages(pkg_names, remote_version, is_built=False)
                    return False
                else:
                    logger.info(f"🔄 {pkg_name}: Version matches but VPS is incomplete - FORCING BUILD")
            else:
                logger.info(f"🔄 {pkg_name}: Local version {local_version} is NEWER than remote {remote_version} - BUILDING")
        else:
            logger.info(f"🔄 {pkg_name}: No remote version found, building local version {local_version}")
        
        # Step 4: Build using the package_builder module
        logger.info(f"🔨 Building {pkg_name} ({local_version})...")
        
        # Use the package_builder module for building
        built, version, metadata = self.package_builder.audit_and_build_local(
            pkg_dir, remote_version
        )
        
        if built:
            self.built_packages.append(f"{pkg_name} ({local_version})")
            self.rebuilt_local_packages.append(pkg_name)
            
            # Collect metadata for hokibot
            self.build_tracker.add_hokibot_data(pkg_name, pkgver, pkgrel, epoch)
            logger.info(f"📝 HOKIBOT observed: {pkg_name} -> {local_version}")
            
            return True
        else:
            logger.error(f"❌ Failed to build {pkg_name}")
            return False
    
    def _build_single_package(self, pkg_name: str, is_aur: bool) -> bool:
        """Build a single package WITH CACHE CHECK"""
        print(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")
        
        # Check cache first
        cached, cached_version = self._check_cache_for_package(pkg_name, is_aur)
        if cached:
            logger.info(f"✅ Using cached package: {pkg_name} ({cached_version})")
            self.built_packages.append(f"{pkg_name} ({cached_version}) [CACHED]")
            
            # Register target version for cleanup
            self.version_tracker.register_package_target_version(pkg_name, cached_version)
            
            # Record statistics
            if is_aur:
                self.stats["aur_success"] += 1
                self.build_tracker.record_built_package(pkg_name, cached_version, is_aur=True)
            else:
                self.stats["local_success"] += 1
                self.build_tracker.record_built_package(pkg_name, cached_version, is_aur=False)
            
            return True
        
        # If not cached, proceed with normal build
        if is_aur:
            return self._build_aur_package(pkg_name)
        else:
            return self._build_local_package(pkg_name)
    
    def build_packages(self) -> int:
        """Build packages with cache-aware optimization"""
        print("\n" + "=" * 60)
        print("Building packages (Cache-aware)")
        print("=" * 60)
        
        # Run Phase I first to get VPS files
        if not self.phase_i_vps_sync():
            logger.error("Failed to sync with VPS")
            return 0
        
        local_packages, aur_packages = self.get_package_lists()
        
        print(f"📦 Package statistics:")
        print(f"   Local packages: {len(local_packages)}")
        print(f"   AUR packages: {len(aur_packages)}")
        print(f"   Total packages: {len(local_packages) + len(aur_packages)}")
        print(f"   Cache enabled: {self.use_cache}")
        print(f"   Package signing: {'ENABLED' if self.gpg_handler.sign_packages_enabled else 'DISABLED'}")
        
        print(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if self._build_single_package(pkg, is_aur=True):
                # Success already recorded in _build_single_package
                pass
            else:
                self.stats["aur_failed"] += 1
                self.build_tracker.record_failed_package(is_aur=True)
        
        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self._build_single_package(pkg, is_aur=False):
                # Success already recorded in _build_single_package
                pass
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
        
        # NEW: Post-upload verification (UP3)
        if upload_success:
            upload_success = self._verify_upload_completeness(files_to_upload)
            self.version_tracker.set_upload_successful(upload_success)
        
        return upload_success
    
    def _verify_upload_completeness(self, uploaded_files: List[str]) -> bool:
        """
        UP3: Verify that all uploaded artifacts exist on VPS after rsync.
        
        Args:
            uploaded_files: List of local file paths that were uploaded
            
        Returns:
            True if all uploaded files are present on VPS, False otherwise
        """
        logger.info("UP3: Verifying upload completeness...")
        
        # Get basenames of uploaded files
        expected_basenames = set(os.path.basename(f) for f in uploaded_files)
        logger.info(f"Expected on VPS: {len(expected_basenames)} files")
        
        # Fetch fresh VPS inventory - FIX: include both regular files and symlinks
        vps_packages = self.ssh_client.list_remote_packages()
        vps_signatures = self._get_vps_signatures()
        vps_db_files = self._get_vps_database_files()
        
        # Combine all VPS files
        vps_all_files = set(vps_packages + vps_signatures + vps_db_files)
        logger.info(f"Found on VPS: {len(vps_all_files)} files")
        
        # Check for missing files
        missing_files = expected_basenames - vps_all_files
        
        if not missing_files:
            logger.info(f"UP3 OK: all uploaded artifacts present on VPS (expected={len(expected_basenames)}, missing=0)")
            return True
        else:
            missing_list = list(missing_files)
            logger.error(f"UP3 FAIL: missing on VPS (expected={len(expected_basenames)}, missing={len(missing_files)}) missing: {', '.join(missing_list[:10])}")
            if len(missing_files) > 10:
                logger.error(f"... and {len(missing_files) - 10} more")
            return False
    
    def _get_vps_database_files(self) -> List[str]:
        """Get database files from VPS - FIX: include both regular files and symlinks"""
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found")
            return []
        
        # Get database files - FIX: include both regular files and symlinks
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            rf'find "{self.remote_dir}" -maxdepth 1 \( -type f -o -type l \) \( -name "{self.repo_name}.db*" -o -name "{self.repo_name}.files*" \) -printf "%f\\n" 2>/dev/null || echo "NO_FILES"'
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip() and f.strip() != 'NO_FILES']
                return files
            else:
                logger.warning(f"SSH find for database files returned error")
                return []
                
        except Exception as e:
            logger.error(f"SSH command for database files failed: {e}")
            return []
    
    def create_artifact_archive_for_github(self) -> Optional[Path]:
        """
        Create a tar.gz archive of all built artifacts for GitHub upload.
        This avoids issues with colon (:) characters in package filenames.
        """
        log_path = Path("builder.log")
        return self.artifact_manager.create_artifact_archive(self.output_dir, log_path)
    
    def run(self):
        """Main execution with cache-aware building"""
        print("\n" + "=" * 60)
        print("🚀 MANJARO PACKAGE BUILDER (MODULAR ARCHITECTURE WITH CACHE)")
        print("=" * 60)
        
        try:
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Repository name: {self.repo_name}")
            print(f"Output directory: {self.output_dir}")
            print(f"PACKAGER identity: {self.packager_id}")
            print(f"Cache optimization: {'ENABLED' if self.use_cache else 'DISABLED'}")
            print(f"Package signing: {'ENABLED' if self.sign_packages else 'DISABLED'}")
            
            # Display initial cache status
            if self.use_cache:
                built_count = len(list(self.output_dir.glob("*.pkg.tar.*")))
                print(f"📦 Initial cache contains {built_count} package files")
            
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
            # Note: remote_packages already fetched in phase_i_vps_sync
            
            logger.info(f"📊 Found {len(self.remote_files)} remote files for version comparison")
            
            # MANDATORY STEP: Mirror ALL remote packages locally before any database operations
            # But check cache first
            remote_packages = [f for f in self.remote_files if f.endswith('.pkg.tar.zst') or f.endswith('.pkg.tar.xz')]
            if remote_packages:
                print("\n" + "=" * 60)
                print("MANDATORY PRECONDITION: Mirroring remote packages locally")
                print("=" * 60)
                
                # Check if we already have cached mirror
                cached_mirror_files = list(self.mirror_temp_dir.glob("*.pkg.tar.*"))
                if cached_mirror_files and self.use_cache:
                    print(f"📦 Using cached VPS mirror with {len(cached_mirror_files)} files")
                    # Copy cached files to output directory
                    for cached_file in cached_mirror_files:
                        dest = self.output_dir / cached_file.name
                        if not dest.exists():
                            shutil.copy2(cached_file, dest)
                else:
                    # No cache, perform fresh mirror
                    if not self.rsync_client.mirror_remote_packages(self.mirror_temp_dir, self.output_dir, remote_packages):
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
            
            # CRITICAL: Clean up orphaned signatures on VPS before building
            print("\n" + "=" * 60)
            print("STEP 3.5: VPS ORPHAN SIGNATURE CLEANUP")
            print("=" * 60)
            package_count, signature_count, orphaned_count = self.cleanup_manager.cleanup_vps_orphaned_signatures()
            logger.info(f"VPS state: {package_count} packages, {signature_count} signatures, deleted {orphaned_count} orphans")
            
            # Build packages with cache optimization
            print("\n" + "=" * 60)
            print("STEP 5: PACKAGE BUILDING (CACHE-AWARE SRCINFO VERSIONING)")
            print("=" * 60)
            
            total_built = self.build_packages()
            
            # STEP 5.5: Sign existing packages in output_dir
            print("\n" + "=" * 60)
            print("STEP 5.5: SIGN EXISTING PACKAGES IN OUTPUT_DIR")
            print("=" * 60)
            unsigned_found, signed_count, signing_failures = self._sign_existing_packages_in_output_dir()
            logger.info(f"Signed {signed_count} previously unsigned packages (found {unsigned_found}, failed {signing_failures})")
            
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
                print(f"   Cache hits: {self.stats['cache_hits']}")
                print(f"   Cache misses: {self.stats['cache_misses']}")
                print(f"   Cache efficiency: {self.stats['cache_hits']/(self.stats['cache_hits']+self.stats['cache_misses'])*100:.1f}%")
                print(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
                print(f"Package signing: {'Enabled' if self.gpg_handler.sign_packages_enabled else 'Disabled'}")
                print(f"PACKAGER:        {self.packager_id}")
                print(f"Zero-Residue:    ✅ Exact-filename-match cleanup active")
                print(f"Target Version:  ✅ Package target versions registered: {len(self.version_tracker._package_target_versions)}")
                print(f"Skipped Registry:✅ Skipped packages tracked: {len(self.version_tracker._skipped_packages)}")
                print("=" * 60)
                
                if self.built_packages:
                    print("\n📦 Built packages:")
                    for pkg in self.built_packages:
                        print(f"  - {pkg}")
                
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
            print("📊 BUILD SUMMARY WITH CACHE STATISTICS")
            print("=" * 60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {summary['aur_success']} (failed: {summary['aur_failed']})")
            print(f"Local packages:  {summary['local_success']} (failed: {summary['local_failed']})")
            print(f"Total built:     {summary['total_built']}")
            print(f"Skipped:         {summary['skipped']}")
            print(f"Cache hits:      {self.stats['cache_hits']}")
            print(f"Cache misses:    {self.stats['cache_misses']}")
            print(f"Cache efficiency: {self.stats['cache_hits']/(self.stats['cache_hits']+self.stats['cache_misses'])*100:.1f}%")
            print(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            print(f"Package signing: {'Enabled' if self.gpg_handler.sign_packages_enabled else 'Disabled'}")
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