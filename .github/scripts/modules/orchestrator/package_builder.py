"""
Main orchestrator for package builder system - SERVER-FIRST ARCHITECTURE
VPS file list is the ONLY source of truth
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
    """Main orchestrator - SERVER-FIRST ARCHITECTURE"""
    
    def __init__(self):
        """Initialize PackageBuilder with server-first architecture"""
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
        
        self.logger.info("✅ PackageBuilder initialized with SERVER-FIRST architecture")
    
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
        Download ONLY database files from VPS to staging (no packages)
        
        Returns:
            True if successful or no database exists (first run)
        """
        repo_name = self.config.get('repo_name', '')
        
        self.logger.info("📥 Downloading existing database files only from VPS...")
        
        patterns = [
            f"{repo_name}.db.tar.gz*",
            f"{repo_name}.files.tar.gz*"
        ]
        
        for pattern in patterns:
            self.logger.info(f"  Downloading pattern: {pattern}")
            
            success = self.rsync_client.mirror_remote(
                remote_pattern=pattern,
                local_dir=self._staging_dir,
                temp_dir=None
            )
            
            if not success:
                self.logger.warning(f"⚠️ Failed to download {pattern}")
        
        db_files = list(self._staging_dir.glob(f"{repo_name}.db.tar.gz*"))
        files_files = list(self._staging_dir.glob(f"{repo_name}.files.tar.gz*"))
        
        total_files = len(db_files) + len(files_files)
        
        if total_files > 0:
            self.logger.info(f"✅ Downloaded {total_files} database files")
        else:
            self.logger.info("ℹ️ No existing database files found (first run or clean state)")
        
        return True
    
    def _create_dummy_files_for_all_packages(self) -> None:
        """
        Create dummy files for ALL packages that should be in the repository
        
        Creates dummy files for:
        1. Newly built packages (already moved to staging)
        2. Adopted packages (already on server)
        3. Any other packages that exist on server
        
        This ensures repo-add has a complete view of the repository.
        """
        self.logger.info("🔄 Creating dummy files for all repository packages...")
        
        # Get all packages that should be in the repository
        all_packages = set()
        
        # 1. Get adopted packages (already on server, skipped in this build)
        adopted_packages = self.version_tracker.get_skipped_packages_dict()
        for pkg_name, version_str in adopted_packages.items():
            # Create filename pattern for this package
            dummy_name = f"{pkg_name}-{version_str}-x86_64.pkg.tar.zst"
            all_packages.add((dummy_name, True))  # True = is dummy (needs creation)
        
        # 2. Get built packages (already in staging with real files)
        staging_packages = list(self._staging_dir.glob("*.pkg.tar.zst"))
        for pkg_file in staging_packages:
            if pkg_file.stat().st_size > 0:  # Only count real files
                all_packages.add((pkg_file.name, False))  # False = real file (already exists)
        
        # 3. Get all packages from server inventory
        remote_files = self.ssh_client.get_cached_inventory()
        for filename in remote_files.keys():
            if filename.endswith('.pkg.tar.zst'):
                # Check if we already have this package (either dummy or real)
                if not any(filename == pkg_name for pkg_name, _ in all_packages):
                    all_packages.add((filename, True))  # Need dummy
        
        # Create dummy files for those that need them
        created_count = 0
        for pkg_filename, needs_dummy in all_packages:
            if needs_dummy:
                dummy_path = self._staging_dir / pkg_filename
                if not dummy_path.exists():
                    try:
                        dummy_path.touch()
                        self.logger.debug(f"  Created dummy: {pkg_filename}")
                        created_count += 1
                        
                        # Also create dummy signature
                        sig_path = dummy_path.with_suffix(dummy_path.suffix + '.sig')
                        if not sig_path.exists():
                            sig_path.touch()
                            self.logger.debug(f"  Created dummy signature: {sig_filename}")
                    except Exception as e:
                        self.logger.warning(f"Failed to create dummy for {pkg_filename}: {e}")
        
        self.logger.info(f"✅ Created {created_count} dummy package files")
        self.logger.info(f"📊 Total packages in staging: {len(all_packages)}")
    
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
    
    def _clean_dummy_files_before_upload(self) -> None:
        """
        Remove all 0-byte dummy files from staging before upload
        
        This ensures dummy files never reach the VPS
        """
        self.logger.info("🧹 Cleaning dummy files before upload...")
        
        removed_count = 0
        
        # Remove dummy package files (0-byte .pkg.tar.zst)
        for pkg_file in self._staging_dir.glob("*.pkg.tar.zst"):
            if pkg_file.stat().st_size == 0:
                try:
                    pkg_file.unlink()
                    removed_count += 1
                    
                    # Also remove corresponding signature if it's also 0-byte
                    sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                    if sig_file.exists() and sig_file.stat().st_size == 0:
                        sig_file.unlink()
                        removed_count += 1
                except Exception as e:
                    self.logger.warning(f"Failed to remove dummy file {pkg_file.name}: {e}")
        
        self.logger.info(f"✅ Removed {removed_count} dummy files")
    
    def _update_database_locally(self) -> bool:
        """
        Update repository database locally with GPG signing
        
        Returns:
            True if successful
        """
        repo_name = self.config.get('repo_name', '')
        
        self.logger.info("\n" + "=" * 60)
        self.logger.info("LOCAL DATABASE UPDATE WITH GPG SIGNING")
        self.logger.info("=" * 60)
        
        old_cwd = os.getcwd()
        os.chdir(self._staging_dir)
        
        try:
            db_file = f"{repo_name}.db.tar.gz"
            
            self.logger.info("Cleaning old database files...")
            for f in [f"{repo_name}.db", f"{repo_name}.db.tar.gz", 
                      f"{repo_name}.files", f"{repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            package_files = list(glob.glob("*.pkg.tar.zst"))
            if not package_files:
                self.logger.error("❌ No package files found for database update")
                return False
            
            self.logger.info(f"Found {len(package_files)} package files for database update")
            
            if self.gpg_handler.gpg_enabled:
                self.logger.info("🔏 Running repo-add with GPG signing...")
                
                # Set GNUPGHOME environment variable for non-interactive signing
                env = os.environ.copy()
                if hasattr(self.gpg_handler, 'gpg_home') and self.gpg_handler.gpg_home:
                    env['GNUPGHOME'] = self.gpg_handler.gpg_home
                
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
                self.logger.info("🔧 Running repo-add without signing...")
                cmd = f"repo-add --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False
                )
            
            if result.returncode == 0:
                self.logger.info("✅ Database updated successfully")
                
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
    
    def _upload_only_real_files(self) -> bool:
        """
        Upload ONLY real files (not dummies) to VPS
        
        Returns:
            True if successful
        """
        self.logger.info("\n📤 Uploading real files to VPS (excluding dummies)...")
        
        files_to_upload = []
        
        # Collect real package files (non-zero size)
        for pkg_file in self._staging_dir.glob("*.pkg.tar.zst"):
            if pkg_file.stat().st_size > 0:
                files_to_upload.append(pkg_file)
                
                # Include signature if it exists and has content
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if sig_file.exists() and sig_file.stat().st_size > 0:
                    files_to_upload.append(sig_file)
        
        self.logger.info(f"Found {len([f for f in files_to_upload if str(f).endswith('.pkg.tar.zst')])} real package files")
        
        # Collect database files
        repo_name = self.config.get('repo_name', '')
        for pattern in [f"{repo_name}.db*", f"{repo_name}.files*"]:
            for db_file in self._staging_dir.glob(pattern):
                if db_file.stat().st_size > 0:
                    files_to_upload.append(db_file)
        
        if not files_to_upload:
            self.logger.warning("⚠️ No files to upload (all files are dummies or empty)")
            return True
        
        self.logger.info(f"📦 Total real files to upload: {len(files_to_upload)}")
        
        files_list = [str(f) for f in files_to_upload]
        upload_success = self.rsync_client.upload(files_list, self._staging_dir)
        
        if upload_success:
            self.logger.info("✅ All real files uploaded successfully")
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
        FORCE database update even if no new packages were built
        
        This ensures the remote DB is always healthy and signed
        
        Returns:
            True if successful
        """
        self.logger.info("\n🔧 FORCING database update (ensuring remote DB is healthy)...")
        
        try:
            # Step 1: Create staging directory
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 1: Create local staging directory")
            self.logger.info("=" * 60)
            staging_dir = self._create_local_staging()
            
            # Step 2: Download existing database files
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 2: Download existing database files from VPS")
            self.logger.info("=" * 60)
            self._download_existing_database_only()
            
            # Step 3: Move any new packages to staging
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 3: Move new packages to staging")
            self.logger.info("=" * 60)
            self._move_new_packages_to_staging()
            
            # Step 4: Create dummy files for all packages
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 4: Create dummy files for all repository packages")
            self.logger.info("=" * 60)
            self._create_dummy_files_for_all_packages()
            
            # Step 5: Update database locally with GPG signing
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 5: Update database locally with GPG signing")
            self.logger.info("=" * 60)
            if not self._update_database_locally():
                self.logger.error("❌ Local database update failed")
                return False
            
            # Step 6: Clean dummy files before upload
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 6: Clean dummy files before upload")
            self.logger.info("=" * 60)
            self._clean_dummy_files_before_upload()
            
            # Step 7: Upload only real files
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 7: Upload only real files to VPS")
            self.logger.info("=" * 60)
            if not self._upload_only_real_files():
                self.logger.error("❌ File upload failed")
                return False
            
            # Step 8: Execute queued cleanup
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 8: Execute queued cleanup operations")
            self.logger.info("=" * 60)
            cleanup_success = self.version_tracker.commit_queued_deletions()
            
            if cleanup_success:
                self.logger.info("✅ Cleanup operations completed")
            else:
                self.logger.warning("⚠️ Some cleanup operations failed")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Force database update failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 9: Cleanup staging directory")
            self.logger.info("=" * 60)
            self._cleanup_staging()
    
    def run(self) -> int:
        """
        Main execution workflow - SERVER-FIRST ARCHITECTURE
        
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        try:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("🚀 MANJARO PACKAGE BUILDER - SERVER-FIRST ARCHITECTURE")
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
            self.logger.info("STEP 5: FORCED DATABASE UPDATE (ALWAYS RUN)")
            self.logger.info("=" * 60)
            
            # ALWAYS run database update, even if no new packages
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
            self.logger.info(f"Forced DB update: ✅ Always executed")
            
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