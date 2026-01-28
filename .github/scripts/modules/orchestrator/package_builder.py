"""
Manjaro Package Builder - Self-Healing Additive Architecture
Main entry point with auto-recovery for database consistency
"""

import os
import sys
import time
import re
import logging
import shutil
import subprocess
import tempfile
import glob
import tarfile
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set

# Common utilities
from modules.common.logging_utils import setup_logging, get_logger
from modules.common.config_loader import ConfigLoader
from modules.common.environment import EnvironmentValidator
from modules.common.shell_executor import ShellExecutor

# State management
from modules.orchestrator.state import BuildState
from modules.repo.version_tracker import VersionTracker

# VPS communication
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient

# Build logic
from modules.build.version_manager import VersionManager
from modules.build.aur_builder import AURBuilder
from modules.build.local_builder import LocalBuilder

# Repository management
from modules.repo.database_manager import DatabaseManager
from modules.repo.cleanup_manager import CleanupManager

# GPG handling
from modules.gpg.gpg_handler import GPGHandler


class PackageBuilder:
    """Main orchestrator - SELF-HEALING ADDITIVE ARCHITECTURE"""
    
    def __init__(self):
        """Initialize PackageBuilder with self-healing architecture"""
        self.logger = get_logger(__name__)
        
        # Phase 1: Common utilities
        self.env_validator = EnvironmentValidator(self.logger)
        self.env_validator.validate()
        
        self.repo_root = self.env_validator.get_repo_root()
        self.config_loader = ConfigLoader(self.repo_root, self.logger)
        self.config = self.config_loader.load_config()
        
        # Setup logging with debug mode from config
        debug_mode = self.config.get('debug_mode', False)
        setup_logging(debug_mode=debug_mode)
        
        # Shell executor with debug mode
        self.shell_executor = ShellExecutor(
            debug_mode=debug_mode,
            default_timeout=1800
        )
        
        # CRITICAL FIX: Run pacman -Sy BEFORE any operations
        self._sync_pacman_databases_initial()
        
        # Phase 2: State management and VPS communication
        self.build_state = BuildState(self.logger)
        
        # VPS clients
        self.ssh_client = SSHClient(self.config, self.shell_executor, self.logger)
        self.rsync_client = RsyncClient(self.config, self.shell_executor, self.logger)
        
        # Setup SSH configuration
        ssh_key = self.config.get('ssh_key', '')
        self.ssh_client.setup_ssh_config(ssh_key)
        
        # Version tracker with JSON state
        self.version_tracker = VersionTracker(
            repo_root=self.repo_root,
            ssh_client=self.ssh_client,
            logger=self.logger
        )
        
        # Phase 3: Build and repository logic
        self.version_manager = VersionManager(self.shell_executor, self.logger)
        
        # Builders (will be used only when server says we need to build)
        self.aur_builder = AURBuilder(
            config=self.config,
            shell_executor=self.shell_executor,
            version_manager=self.version_manager,
            version_tracker=self.version_tracker,
            build_state=self.build_state,
            logger=self.logger
        )
        
        self.local_builder = LocalBuilder(
            config=self.config,
            shell_executor=self.shell_executor,
            version_manager=self.version_manager,
            version_tracker=self.version_tracker,
            build_state=self.build_state,
            logger=self.logger
        )
        
        # Repository managers
        self.database_manager = DatabaseManager(
            config=self.config,
            ssh_client=self.ssh_client,
            rsync_client=self.rsync_client,
            logger=self.logger
        )
        
        self.cleanup_manager = CleanupManager(
            config=self.config,
            version_tracker=self.version_tracker,
            ssh_client=self.ssh_client,
            rsync_client=self.rsync_client,
            logger=self.logger
        )
        
        # GPG handler
        self.gpg_handler = GPGHandler()
        
        # Package lists
        self.local_packages: List[str] = []
        self.aur_packages: List[str] = []
        
        # Track sanitized artifacts
        self._sanitized_files: Dict[str, str] = {}
        
        # Local staging directory for database operations
        self._staging_dir: Optional[Path] = None
        
        # Auto-recovery state
        self._recovered_packages: List[str] = []
        self._missing_from_db: List[str] = []
        
        self.logger.info("✅ PackageBuilder initialized with SELF-HEALING architecture")
    
    def _sync_pacman_databases_initial(self) -> bool:
        """
        CRITICAL FIX: Sync pacman databases BEFORE any operations
        
        Returns:
            True if sync successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("CRITICAL: Syncing pacman databases BEFORE operations")
        self.logger.info("=" * 60)
        
        cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        result = self.shell_executor.run(
            cmd,
            log_cmd=True,
            timeout=300,
            check=False,
            shell=True
        )
        
        if result.returncode == 0:
            self.logger.info("✅ Pacman databases synced successfully")
            return True
        else:
            self.logger.error("❌ Initial pacman sync failed")
            if result.stderr:
                self.logger.error(f"Error: {result.stderr[:500]}")
            return False
    
    def _get_package_lists(self) -> Tuple[List[str], List[str]]:
        """Get package lists from configuration"""
        if not self.local_packages or not self.aur_packages:
            self.local_packages, self.aur_packages = self.config_loader.get_package_lists()
        return self.local_packages, self.aur_packages
    
    def _resolve_vcs_version_before_build(self, pkg_name: str, is_aur: bool) -> Optional[Tuple[str, str, str]]:
        """
        VCS PRIORITY FIX: Resolve git/VCS package version BEFORE building
        
        Args:
            pkg_name: Package name
            is_aur: Whether it's an AUR package
        
        Returns:
            Tuple of (pkgver, pkgrel, epoch) or None if failed
        """
        self.logger.info(f"🔍 Pre-resolving VCS version for {pkg_name}...")
        
        if is_aur:
            aur_dir = Path(self.config.get('aur_build_dir', 'build_aur'))
            temp_dir = aur_dir / f"temp_{pkg_name}"
            
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            aur_urls = self.config.get('aur_urls', [
                "https://aur.archlinux.org/{pkg_name}.git",
                "git://aur.archlinux.org/{pkg_name}.git"
            ])
            
            clone_success = False
            for aur_url_template in aur_urls:
                aur_url = aur_url_template.format(pkg_name=pkg_name)
                result = self.shell_executor.run(
                    f"git clone --depth 1 {aur_url} {temp_dir}",
                    check=False,
                    log_cmd=False
                )
                if result and result.returncode == 0:
                    clone_success = True
                    break
            
            if not clone_success:
                self.logger.error(f"Failed to clone {pkg_name} for version resolution")
                return None
            
            pkg_dir = temp_dir
        else:
            pkg_dir = self.repo_root / pkg_name
            if not pkg_dir.exists():
                self.logger.error(f"Package directory not found: {pkg_name}")
                return None
        
        try:
            version_info = self.version_tracker.resolve_vcs_version(pkg_name, pkg_dir)
            
            if version_info:
                pkgver, pkgrel, epoch = version_info
                self.logger.info(f"✅ VCS version resolved: {pkgver}-{pkgrel}")
            else:
                pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
                self.logger.info(f"✅ Standard version extracted: {pkgver}-{pkgrel}")
            
            if is_aur and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            return pkgver, pkgrel, epoch
        except Exception as e:
            self.logger.error(f"Failed to resolve version for {pkg_name}: {e}")
            if is_aur and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return None
    
    def _sanitize_artifacts(self, pkg_name: str) -> List[Path]:
        """
        INTERNAL SANITIZATION: Replace ':' with '_' in filenames BEFORE rsync
        
        Args:
            pkg_name: Package name
        
        Returns:
            List of sanitized file paths
        """
        self.logger.info(f"🔧 Sanitizing artifacts for {pkg_name}...")
        
        output_dir = Path(self.config.get('output_dir', 'built_packages'))
        sanitized_files = []
        
        patterns = [f"*{pkg_name}*.pkg.tar.*", f"{pkg_name}*.pkg.tar.*"]
        
        for pattern in patterns:
            for pkg_file in output_dir.glob(pattern):
                original_name = pkg_file.name
                
                if ':' in original_name:
                    sanitized_name = original_name.replace(':', '_')
                    sanitized_path = pkg_file.with_name(sanitized_name)
                    
                    try:
                        pkg_file.rename(sanitized_path)
                        self.logger.info(f"  🔄 Renamed: {original_name} -> {sanitized_name}")
                        
                        self._sanitized_files[str(pkg_file)] = str(sanitized_path)
                        
                        sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                        if sig_file.exists():
                            sanitized_sig = sanitized_path.with_suffix(sanitized_path.suffix + '.sig')
                            sig_file.rename(sanitized_sig)
                            self.logger.info(f"  🔄 Renamed signature: {sig_file.name} -> {sanitized_sig.name}")
                        
                        sanitized_files.append(sanitized_path)
                    except Exception as e:
                        self.logger.error(f"Failed to rename {original_name}: {e}")
                        sanitized_files.append(pkg_file)
                else:
                    sanitized_files.append(pkg_file)
        
        build_dirs = [
            Path(self.config.get('aur_build_dir', 'build_aur')) / pkg_name,
            self.repo_root / pkg_name
        ]
        
        for build_dir in build_dirs:
            if build_dir.exists():
                for pkg_file in build_dir.glob("*.pkg.tar.*"):
                    original_name = pkg_file.name
                    if ':' in original_name:
                        sanitized_name = original_name.replace(':', '_')
                        sanitized_path = pkg_file.with_name(sanitized_name)
                        
                        try:
                            pkg_file.rename(sanitized_path)
                            self.logger.info(f"  🔄 Renamed in build dir: {original_name} -> {sanitized_name}")
                            self._sanitized_files[str(pkg_file)] = str(sanitized_path)
                        except Exception as e:
                            self.logger.warning(f"Failed to rename in build dir {original_name}: {e}")
        
        self.logger.info(f"✅ Sanitized {len(sanitized_files)} files for {pkg_name}")
        return sanitized_files
    
    def _check_server_for_package(self, pkg_name: str, version_str: str, is_aur: bool) -> str:
        """
        SERVER-FIRST LOGIC: Check if package exists on server
        
        Args:
            pkg_name: Package name
            version_str: Full version string
            is_aur: Whether it's an AUR package
        
        Returns:
            "ADOPT" if package exists on server, "BUILD" if not
        """
        found, remote_version, remote_hash = self.version_tracker.is_package_on_remote(pkg_name, version_str)
        
        if found:
            self.logger.info(f"✅ [ADOPT] {pkg_name} {version_str} found on server. Skipping build.")
            
            self.version_tracker.register_built_package(pkg_name, version_str, remote_hash)
            self.build_state.add_skipped(pkg_name, version_str, is_aur=is_aur, reason="already-on-server")
            
            return "ADOPT"
        else:
            self.logger.info(f"🔄 [BUILD] {pkg_name} {version_str} not on server or outdated. Starting build.")
            return "BUILD"
    
    def _build_aur_packages_server_first(self) -> None:
        """
        Build AUR packages using SERVER-FIRST logic with VCS PRIORITY FIX
        """
        if not self.aur_packages:
            self.logger.info("No AUR packages to build")
            return
        
        self.logger.info(f"\n🔨 Processing {len(self.aur_packages)} AUR packages (SERVER-FIRST)")
        
        for pkg_name in self.aur_packages:
            self.logger.info(f"\n--- Processing AUR: {pkg_name} ---")
            
            version_info = self._resolve_vcs_version_before_build(pkg_name, is_aur=True)
            if not version_info:
                self.build_state.add_failed(
                    pkg_name,
                    "unknown",
                    is_aur=True,
                    error_message="Failed to resolve version"
                )
                continue
            
            pkgver, pkgrel, epoch = version_info
            version_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            decision = self._check_server_for_package(pkg_name, version_str, is_aur=True)
            
            if decision == "ADOPT":
                continue
            
            self.logger.info(f"🚀 Building {pkg_name} ({version_str})...")
            
            success = self.aur_builder.build(pkg_name, None)
            
            if success:
                self._sanitize_artifacts(pkg_name)
                
                self.version_tracker.register_built_package(pkg_name, version_str)
                self.build_state.add_built(pkg_name, version_str, is_aur=True)
                
                self._queue_old_version_cleanup(pkg_name, version_str)
            else:
                self.build_state.add_failed(
                    pkg_name,
                    version_str,
                    is_aur=True,
                    error_message="AUR build failed"
                )
    
    def _build_local_packages_server_first(self) -> None:
        """
        Build local packages using SERVER-FIRST logic with VCS PRIORITY FIX
        """
        if not self.local_packages:
            self.logger.info("No local packages to build")
            return
        
        self.logger.info(f"\n🔨 Processing {len(self.local_packages)} local packages (SERVER-FIRST)")
        
        for pkg_name in self.local_packages:
            self.logger.info(f"\n--- Processing Local: {pkg_name} ---")
            
            version_info = self._resolve_vcs_version_before_build(pkg_name, is_aur=False)
            if not version_info:
                self.build_state.add_failed(
                    pkg_name,
                    "unknown",
                    is_aur=False,
                    error_message="Failed to resolve version"
                )
                continue
            
            pkgver, pkgrel, epoch = version_info
            version_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            decision = self._check_server_for_package(pkg_name, version_str, is_aur=False)
            
            if decision == "ADOPT":
                continue
            
            self.logger.info(f"🚀 Building {pkg_name} ({version_str})...")
            
            success = self.local_builder.build(pkg_name, None)
            
            if success:
                self._sanitize_artifacts(pkg_name)
                
                self.version_tracker.register_built_package(pkg_name, version_str)
                self.build_state.add_built(pkg_name, version_str, is_aur=False)
                
                self._queue_old_version_cleanup(pkg_name, version_str)
            else:
                self.build_state.add_failed(
                    pkg_name,
                    version_str,
                    is_aur=False,
                    error_message="Local build failed"
                )
    
    def _queue_old_version_cleanup(self, pkg_name: str, keep_version: str):
        """
        Queue old versions for cleanup (but don't execute yet)
        
        Args:
            pkg_name: Package name
            keep_version: Version to keep (newly built/adopted)
        """
        self.logger.info(f"🧹 Queuing cleanup of old versions for {pkg_name}...")
        
        remote_files = self.ssh_client.get_cached_inventory()
        if not remote_files:
            return
        
        for remote_path in remote_files.values():
            filename = Path(remote_path).name
            
            parsed = self.version_tracker._parse_package_filename_with_arch(filename)
            if not parsed:
                continue
            
            remote_pkg_name, remote_version, architecture = parsed
            
            if remote_pkg_name.lower() == pkg_name.lower():
                if not self.version_tracker._versions_match(remote_version, keep_version):
                    self.version_tracker.queue_deletion(remote_path)
                    self.logger.debug(f"🗑️ Queued for deletion: {filename} (old version: {remote_version})")
                else:
                    self.logger.debug(f"✅ Keeping: {filename} (current version: {remote_version})")
    
    def _create_local_staging(self) -> Path:
        """
        Create local staging directory for database operations
        
        Returns:
            Path to staging directory
        """
        if self._staging_dir and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)
        
        self._staging_dir = Path(tempfile.mkdtemp(prefix="repo_staging_"))
        self.logger.info(f"📁 Created staging directory: {self._staging_dir}")
        return self._staging_dir
    
    def _download_existing_database_only(self) -> bool:
        """
        Download ONLY database files from VPS to staging
        
        Returns:
            True if successful or no database exists (first run)
        """
        repo_name = self.config.get('repo_name', '')
        
        self.logger.info("📥 Downloading existing database files from VPS...")
        
        patterns = [
            f"{repo_name}.db.tar.gz*",
            f"{repo_name}.files.tar.gz*"
        ]
        
        success_count = 0
        
        for pattern in patterns:
            self.logger.info(f"  Downloading pattern: {pattern}")
            
            success = self.rsync_client.mirror_remote(
                remote_pattern=pattern,
                local_dir=self._staging_dir,
                temp_dir=None
            )
            
            if success:
                success_count += 1
            else:
                self.logger.warning(f"⚠️ Failed to download {pattern}")
        
        db_files = list(self._staging_dir.glob(f"{repo_name}.db.tar.gz*"))
        files_files = list(self._staging_dir.glob(f"{repo_name}.files.tar.gz*"))
        
        total_files = len(db_files) + len(files_files)
        
        if total_files > 0:
            self.logger.info(f"✅ Downloaded {total_files} database files")
        else:
            self.logger.info("ℹ️ No existing database files found (first run or clean state)")
        
        return True
    
    def _get_db_package_list(self) -> Set[str]:
        """
        Extract package list from existing database file
        
        Returns:
            Set of package filenames (without path) in the database
        """
        repo_name = self.config.get('repo_name', '')
        db_file = self._staging_dir / f"{repo_name}.db.tar.gz"
        
        if not db_file.exists():
            self.logger.info("ℹ️ No database file found in staging")
            return set()
        
        self.logger.info("📋 Extracting package list from existing database...")
        
        try:
            # Use tar to list contents and find package entries
            cmd = ["tar", "-tzf", str(db_file)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                self.logger.warning(f"Failed to list database contents: {result.stderr}")
                return set()
            
            # Parse tar output to find package entries
            package_files = set()
            for line in result.stdout.splitlines():
                if line.strip() and '/' in line:
                    # Extract filename from path like: awesome-git-4.0.r123.gabc123def-1-x86_64/pkgname/desc
                    parts = line.split('/')
                    if len(parts) >= 2 and parts[1].endswith('/desc'):
                        # The directory name is the package filename
                        package_files.add(parts[0])
            
            self.logger.info(f"📊 Database contains {len(package_files)} package entries")
            if package_files:
                self.logger.debug(f"Sample DB entries: {list(package_files)[:5]}")
            
            return package_files
            
        except Exception as e:
            self.logger.error(f"❌ Failed to extract package list from DB: {e}")
            return set()
    
    def _discover_missing_packages(self) -> List[str]:
        """
        AUTO-RECOVERY: Compare remote inventory with database entries
        
        Returns:
            List of package filenames missing from database
        """
        self.logger.info("🔍 Discovering packages missing from database...")
        
        # Get packages in database
        db_packages = self._get_db_package_list()
        
        # Get remote inventory (physical files on VPS)
        remote_inventory = self.ssh_client.get_cached_inventory(force_refresh=True)
        
        if not remote_inventory:
            self.logger.info("ℹ️ No remote packages found")
            return []
        
        # Filter for package files only
        remote_packages = set()
        for filename in remote_inventory.keys():
            if filename.endswith('.pkg.tar.zst'):
                remote_packages.add(filename)
        
        self.logger.info(f"📊 Remote inventory: {len(remote_packages)} package files")
        
        # Find packages on VPS that are NOT in database
        missing_packages = []
        for pkg_file in remote_packages:
            if pkg_file not in db_packages:
                missing_packages.append(pkg_file)
                self.logger.info(f"⚠️ Missing from DB: {pkg_file}")
        
        self.logger.info(f"📊 Found {len(missing_packages)} packages missing from database")
        
        # Store for reporting
        self._missing_from_db = missing_packages
        
        return missing_packages
    
    def _download_missing_packages(self, missing_packages: List[str]) -> int:
        """
        Download missing packages from VPS to staging
        
        Args:
            missing_packages: List of package filenames to download
        
        Returns:
            Number of successfully downloaded packages
        """
        if not missing_packages:
            return 0
        
        self.logger.info(f"📥 Downloading {len(missing_packages)} missing packages from VPS...")
        
        downloaded_count = 0
        
        for pkg_filename in missing_packages:
            try:
                # Find full remote path
                remote_inventory = self.ssh_client.get_cached_inventory()
                remote_path = remote_inventory.get(pkg_filename)
                
                if not remote_path:
                    self.logger.warning(f"Could not find remote path for {pkg_filename}")
                    continue
                
                # Download using scp
                scp_cmd = [
                    "scp",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=30",
                    f"{self.config.get('vps_user')}@{self.config.get('vps_host')}:{remote_path}",
                    str(self._staging_dir / pkg_filename)
                ]
                
                result = subprocess.run(
                    scp_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0:
                    # Check if file was downloaded
                    local_path = self._staging_dir / pkg_filename
                    if local_path.exists() and local_path.stat().st_size > 0:
                        self.logger.info(f"✅ Downloaded: {pkg_filename}")
                        downloaded_count += 1
                        
                        # Add to recovered packages list
                        self._recovered_packages.append(pkg_filename)
                    else:
                        self.logger.warning(f"Downloaded file is empty: {pkg_filename}")
                else:
                    self.logger.warning(f"Failed to download {pkg_filename}: {result.stderr}")
                    
            except Exception as e:
                self.logger.error(f"Error downloading {pkg_filename}: {e}")
        
        self.logger.info(f"✅ Downloaded {downloaded_count} missing packages")
        return downloaded_count
    
    def _move_new_packages_to_staging(self) -> List[Path]:
        """
        Move newly built packages to staging directory
        
        Returns:
            List of paths to new packages moved to staging
        """
        output_dir = Path(self.config.get('output_dir', 'built_packages'))
        
        new_packages = list(output_dir.glob("*.pkg.tar.zst"))
        if not new_packages:
            self.logger.info("ℹ️ No new packages to move to staging")
            return []
        
        self.logger.info(f"📦 Moving {len(new_packages)} new packages to staging...")
        
        moved_packages = []
        
        for new_pkg in new_packages:
            try:
                dest = self._staging_dir / new_pkg.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(new_pkg), str(dest))
                moved_packages.append(dest)
                
                # Move signature if exists
                sig_file = new_pkg.with_suffix(new_pkg.suffix + '.sig')
                if sig_file.exists():
                    sig_dest = dest.with_suffix(dest.suffix + '.sig')
                    if sig_dest.exists():
                        sig_dest.unlink()
                    shutil.move(str(sig_file), str(sig_dest))
                
                self.logger.debug(f"  Moved: {new_pkg.name}")
            except Exception as e:
                self.logger.error(f"Failed to move {new_pkg.name}: {e}")
        
        self.logger.info(f"✅ Moved {len(moved_packages)} new packages to staging")
        return moved_packages
    
    def _update_database_additive(self) -> bool:
        """
        Additive database update: Add ALL packages in staging to database
        
        Returns:
            True if successful
        """
        repo_name = self.config.get('repo_name', '')
        
        self.logger.info("\n" + "=" * 60)
        self.logger.info("ADDITIVE DATABASE UPDATE (SELF-HEALING)")
        self.logger.info("=" * 60)
        
        old_cwd = os.getcwd()
        os.chdir(self._staging_dir)
        
        try:
            db_file = f"{repo_name}.db.tar.gz"
            
            # Get all package files in staging
            all_packages = list(glob.glob("*.pkg.tar.zst"))
            
            if not all_packages:
                self.logger.info("ℹ️ No packages to add to database")
                
                # Check if we have an existing database (force repair mode)
                existing_db_files = list(glob.glob(f"{repo_name}.db.tar.gz*"))
                if existing_db_files:
                    self.logger.info("🔧 Force repairing existing database...")
                    return self._force_repair_database(db_file)
                else:
                    self.logger.info("ℹ️ No existing database to repair")
                    return True
            
            self.logger.info(f"📊 Total packages to process: {len(all_packages)}")
            self.logger.info(f"  - Newly built: {len([p for p in all_packages if p not in self._recovered_packages])}")
            self.logger.info(f"  - Recovered: {len([p for p in all_packages if p in self._recovered_packages])}")
            
            # Run repo-add with ALL packages (additive update)
            if self.gpg_handler.gpg_enabled:
                self.logger.info("🔏 Running repo-add with GPG signing (additive)...")
                
                # Set GNUPGHOME environment variable for non-interactive signing
                env = os.environ.copy()
                if hasattr(self.gpg_handler, 'gpg_home') and self.gpg_handler.gpg_home:
                    env['GNUPGHOME'] = self.gpg_handler.gpg_home
                
                # Build command
                if self.gpg_handler.gpg_key_id:
                    cmd = f"repo-add --sign --key {self.gpg_handler.gpg_key_id} --remove {db_file} *.pkg.tar.zst"
                else:
                    cmd = f"repo-add --sign --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False
                )
            else:
                self.logger.info("🔧 Running repo-add without signing (additive)...")
                cmd = f"repo-add --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False
                )
            
            if result.returncode == 0:
                self.logger.info("✅ Database updated successfully (additive)")
                
                if not os.path.exists(db_file):
                    self.logger.error("❌ Database file not created")
                    return False
                
                # Verify the database was created with signatures if GPG enabled
                if self.gpg_handler.gpg_enabled:
                    sig_file = f"{db_file}.sig"
                    if os.path.exists(sig_file):
                        sig_size = os.path.getsize(sig_file)
                        if sig_size > 0:
                            self.logger.info(f"✅ Database signed successfully ({sig_size} bytes)")
                        else:
                            self.logger.warning("⚠️ Database signature file is empty")
                    else:
                        self.logger.warning("⚠️ Database signature file not found")
                
                # Verify database entries
                self._verify_database_entries(db_file)
                return True
            else:
                self.logger.error(f"❌ repo-add failed with exit code {result.returncode}:")
                if result.stdout:
                    self.logger.error(f"STDOUT: {result.stdout[:500]}")
                if result.stderr:
                    self.logger.error(f"STDERR: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Database update error: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            os.chdir(old_cwd)
    
    def _force_repair_database(self, db_file: str) -> bool:
        """
        Force repair existing database (re-signing)
        
        Args:
            db_file: Database file name
        
        Returns:
            True if successful
        """
        self.logger.info("🔧 Force repairing existing database...")
        
        try:
            # Recreate database with proper signing
            if self.gpg_handler.gpg_enabled:
                self.logger.info("🔏 Re-signing existing database...")
                
                env = os.environ.copy()
                if hasattr(self.gpg_handler, 'gpg_home') and self.gpg_handler.gpg_home:
                    env['GNUPGHOME'] = self.gpg_handler.gpg_home
                
                if self.gpg_handler.gpg_key_id:
                    cmd = f"repo-add --sign --key {self.gpg_handler.gpg_key_id} --remove {db_file} *.pkg.tar.zst"
                else:
                    cmd = f"repo-add --sign --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False
                )
            else:
                self.logger.info("🔧 Recreating database without signing...")
                cmd = f"repo-add --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False
                )
            
            if result.returncode == 0:
                self.logger.info("✅ Database repaired successfully")
                return True
            else:
                self.logger.error(f"Database repair failed: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            self.logger.error(f"Database repair error: {e}")
            return False
    
    def _verify_database_entries(self, db_file: str) -> None:
        """Verify database entries after update"""
        try:
            list_cmd = ["tar", "-tzf", db_file]
            result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                db_entries = [line for line in result.stdout.split('\n') if line.endswith('/desc')]
                self.logger.info(f"✅ Database contains {len(db_entries)} package entries")
                if len(db_entries) == 0:
                    self.logger.error("❌❌❌ DATABASE IS EMPTY!")
                else:
                    self.logger.info(f"Sample entries: {db_entries[:3]}")
            else:
                self.logger.warning(f"Could not list database contents: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Could not verify database: {e}")
    
    def _upload_updated_files(self) -> bool:
        """
        Upload updated database and new packages to VPS
        
        Returns:
            True if successful
        """
        if not self._staging_dir or not self._staging_dir.exists():
            self.logger.error("❌ Staging directory not found")
            return False
        
        self.logger.info("\n📤 Uploading updated files to VPS...")
        
        files_to_upload = []
        
        # 1. Database files and signatures (ALWAYS upload these)
        repo_patterns = [
            f"{self.config.get('repo_name', '')}.db*",
            f"{self.config.get('repo_name', '')}.files*",
        ]
        
        for pattern in repo_patterns:
            for file_path in self._staging_dir.glob(pattern):
                if file_path.stat().st_size > 0:  # Skip empty files
                    files_to_upload.append(file_path)
        
        # 2. NEW packages (not recovered) and their signatures
        for pkg_file in self._staging_dir.glob("*.pkg.tar.zst"):
            if pkg_file.stat().st_size > 0:
                # Check if this is a recovered package (already on VPS)
                if pkg_file.name not in self._recovered_packages:
                    files_to_upload.append(pkg_file)
                    
                    # Include signature if it exists
                    sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                    if sig_file.exists() and sig_file.stat().st_size > 0:
                        files_to_upload.append(sig_file)
                else:
                    self.logger.debug(f"Skipping recovered package: {pkg_file.name}")
        
        if not files_to_upload:
            self.logger.warning("⚠️ No files to upload")
            return True
        
        self.logger.info(f"📦 Total files to upload: {len(files_to_upload)}")
        
        # Log file details
        for f in files_to_upload:
            size_mb = f.stat().st_size / (1024 * 1024)
            file_type = "PACKAGE" if ".pkg.tar.zst" in f.name else "DATABASE"
            if f.name.endswith('.sig'):
                file_type = "SIGNATURE"
            self.logger.debug(f"  - {f.name} ({size_mb:.1f}MB) [{file_type}]")
        
        # Upload using rsync
        files_list = [str(f) for f in files_to_upload]
        upload_success = self.rsync_client.upload(files_list, self._staging_dir)
        
        if upload_success:
            self.logger.info("✅ All files uploaded successfully")
            return True
        else:
            self.logger.error("❌ File upload failed")
            return False
    
    def _cleanup_staging(self) -> None:
        """Clean up staging directory"""
        if self._staging_dir and os.path.exists(self._staging_dir):
            try:
                shutil.rmtree(self._staging_dir, ignore_errors=True)
                self.logger.debug(f"🧹 Cleaned up staging directory: {self._staging_dir}")
                self._staging_dir = None
            except Exception as e:
                self.logger.warning(f"Could not clean staging directory: {e}")
    
    def _force_database_update(self) -> bool:
        """
        FORCE database update with self-healing additive strategy
        
        Returns:
            True if successful
        """
        self.logger.info("\n🔧 FORCING DATABASE UPDATE (SELF-HEALING)")
        self.logger.info("=" * 60)
        
        try:
            # Reset recovery state
            self._recovered_packages = []
            self._missing_from_db = []
            
            # Step 1: Create staging directory
            self.logger.info("\n[1/7] Creating local staging directory")
            self.logger.info("-" * 40)
            staging_dir = self._create_local_staging()
            
            # Step 2: Download existing database files
            self.logger.info("\n[2/7] Downloading existing database files from VPS")
            self.logger.info("-" * 40)
            self._download_existing_database_only()
            
            # Step 3: AUTO-RECOVERY: Discover packages missing from database
            self.logger.info("\n[3/7] AUTO-RECOVERY: Discovering missing packages")
            self.logger.info("-" * 40)
            missing_packages = self._discover_missing_packages()
            
            # Step 4: Download missing packages from VPS
            if missing_packages:
                self.logger.info("\n[4/7] Downloading missing packages from VPS")
                self.logger.info("-" * 40)
                downloaded = self._download_missing_packages(missing_packages)
                self.logger.info(f"✅ Downloaded {downloaded} missing packages")
            
            # Step 5: Move newly built packages to staging
            self.logger.info("\n[5/7] Moving newly built packages to staging")
            self.logger.info("-" * 40)
            self._move_new_packages_to_staging()
            
            # Step 6: Update database additively with ALL packages
            self.logger.info("\n[6/7] Updating database additively (self-healing)")
            self.logger.info("-" * 40)
            if not self._update_database_additive():
                self.logger.error("❌ Additive database update failed")
                return False
            
            # Step 7: Upload updated files to VPS
            self.logger.info("\n[7/7] Uploading updated files to VPS")
            self.logger.info("-" * 40)
            if not self._upload_updated_files():
                self.logger.error("❌ File upload failed")
                return False
            
            # Step 8: Execute queued cleanup
            self.logger.info("\n[+] Executing queued cleanup operations")
            self.logger.info("-" * 40)
            cleanup_success = self.version_tracker.commit_queued_deletions()
            
            if cleanup_success:
                self.logger.info("✅ Cleanup operations completed")
            else:
                self.logger.warning("⚠️ Some cleanup operations failed")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Self-healing database update failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self._cleanup_staging()
    
    def run(self) -> int:
        """
        Main execution workflow - SELF-HEALING ARCHITECTURE
        
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        try:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("🚀 MANJARO PACKAGE BUILDER - SELF-HEALING ARCHITECTURE")
            self.logger.info("=" * 60)
            
            self.logger.info("\n🔧 Initial setup...")
            self.logger.info(f"Repository root: {self.repo_root}")
            self.logger.info(f"Repository name: {self.config.get('repo_name')}")
            self.logger.info(f"Output directory: {self.config.get('output_dir')}")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 0: GPG INITIALIZATION")
            self.logger.info("=" * 60)
            
            if self.gpg_handler.gpg_enabled:
                if not self.gpg_handler.import_gpg_key():
                    self.logger.error("❌ Failed to import GPG key, disabling signing")
                    self.gpg_handler.gpg_enabled = False
                else:
                    self.logger.info("✅ GPG initialized successfully")
            else:
                self.logger.info("ℹ️ GPG signing disabled (no key provided)")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 1: SSH CONNECTION TEST")
            self.logger.info("=" * 60)
            
            if not self.ssh_client.test_connection():
                self.logger.error("❌ SSH connection failed")
                return 1
            
            self.ssh_client.debug_remote_directory()
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 2: REMOTE DIRECTORY SETUP")
            self.logger.info("=" * 60)
            
            if not self.ssh_client.ensure_directory():
                self.logger.warning("⚠️ Could not ensure remote directory exists")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 3: PACKAGE DISCOVERY")
            self.logger.info("=" * 60)
            
            self.local_packages, self.aur_packages = self._get_package_lists()
            
            self.logger.info(f"📦 Package statistics:")
            self.logger.info(f"   Local packages: {len(self.local_packages)}")
            self.logger.info(f"   AUR packages: {len(self.aur_packages)}")
            self.logger.info(f"   Total packages: {len(self.local_packages) + len(self.aur_packages)}")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 4: SERVER-FIRST PACKAGE PROCESSING")
            self.logger.info("=" * 60)
            
            self._build_aur_packages_server_first()
            self._build_local_packages_server_first()
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 5: SELF-HEALING DATABASE UPDATE (ALWAYS RUN)")
            self.logger.info("=" * 60)
            
            # ALWAYS run self-healing database update
            db_update_success = self._force_database_update()
            
            if not db_update_success:
                self.logger.error("\n❌ Database update failed!")
                return 1
            
            self.gpg_handler.cleanup()
            self.logger.info("\n✅ Repository maintenance completed successfully!")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 6: FINAL STATISTICS")
            self.logger.info("=" * 60)
            
            self.build_state.mark_complete()
            summary = self.build_state.get_summary()
            
            self.logger.info(f"Duration: {summary['duration_seconds']:.1f}s")
            self.logger.info(f"AUR packages:    {summary['aur_success']} built, {summary['aur_skipped']} adopted, {summary['aur_failed']} failed")
            self.logger.info(f"Local packages:  {summary['local_success']} built, {summary['local_skipped']} adopted, {summary['local_failed']} failed")
            self.logger.info(f"Total built:     {summary['built']}")
            self.logger.info(f"Total adopted:   {summary['skipped']}")
            self.logger.info(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            self.logger.info(f"VCS priority fix: ✅ Implemented")
            self.logger.info(f"Internal sanitization: ✅ {len(self._sanitized_files)} files renamed")
            self.logger.info(f"Self-healing DB update: ✅ Implemented")
            self.logger.info(f"Packages recovered from VPS: {len(self._recovered_packages)}")
            self.logger.info(f"Packages missing from DB: {len(self._missing_from_db)}")
            
            state_summary = self.version_tracker.get_state_summary()
            self.logger.info(f"Packages tracked: {state_summary['total_packages']}")
            self.logger.info("=" * 60)
            
            return 0
            
        except Exception as e:
            self.logger.error(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            
            if hasattr(self, 'version_tracker'):
                self.version_tracker.save_state()
            
            if hasattr(self, '_staging_dir') and self._staging_dir and os.path.exists(self._staging_dir):
                shutil.rmtree(self._staging_dir, ignore_errors=True)
            
            return 1