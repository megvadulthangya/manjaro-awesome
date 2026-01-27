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
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

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
        self._sanitized_files: Dict[str, str] = {}  # original -> sanitized
        
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
        
        # Run pacman -Sy to update all databases
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
            # Continue anyway - some repositories might be temporarily unavailable
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
            # For AUR packages, create a temporary clone
            aur_dir = Path(self.config.get('aur_build_dir', 'build_aur'))
            temp_dir = aur_dir / f"temp_{pkg_name}"
            
            # Clean up any existing temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            
            # Try different AUR URLs
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
            # For local packages, use the existing directory
            pkg_dir = self.repo_root / pkg_name
            if not pkg_dir.exists():
                self.logger.error(f"Package directory not found: {pkg_name}")
                return None
        
        try:
            # Use VersionTracker to resolve VCS version
            version_info = self.version_tracker.resolve_vcs_version(pkg_name, pkg_dir)
            
            if version_info:
                pkgver, pkgrel, epoch = version_info
                self.logger.info(f"✅ VCS version resolved: {pkgver}-{pkgrel}")
            else:
                # Fall back to standard SRCINFO extraction
                pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
                self.logger.info(f"✅ Standard version extracted: {pkgver}-{pkgrel}")
            
            # Clean up temp directory for AUR packages
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
        
        # Find all package files for this package
        patterns = [f"*{pkg_name}*.pkg.tar.*", f"{pkg_name}*.pkg.tar.*"]
        
        for pattern in patterns:
            for pkg_file in output_dir.glob(pattern):
                original_name = pkg_file.name
                
                # Check if filename contains colon
                if ':' in original_name:
                    sanitized_name = original_name.replace(':', '_')
                    sanitized_path = pkg_file.with_name(sanitized_name)
                    
                    # Rename the file
                    try:
                        pkg_file.rename(sanitized_path)
                        self.logger.info(f"  🔄 Renamed: {original_name} -> {sanitized_name}")
                        
                        # Track the sanitization
                        self._sanitized_files[str(pkg_file)] = str(sanitized_path)
                        
                        # Also rename signature if exists
                        sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                        if sig_file.exists():
                            sanitized_sig = sanitized_path.with_suffix(sanitized_path.suffix + '.sig')
                            sig_file.rename(sanitized_sig)
                            self.logger.info(f"  🔄 Renamed signature: {sig_file.name} -> {sanitized_sig.name}")
                        
                        sanitized_files.append(sanitized_path)
                    except Exception as e:
                        self.logger.error(f"Failed to rename {original_name}: {e}")
                        # Keep original file
                        sanitized_files.append(pkg_file)
                else:
                    sanitized_files.append(pkg_file)
        
        # Also check build directories
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
        # Check if exact version exists on server
        found, remote_version, remote_hash = self.version_tracker.is_package_on_remote(pkg_name, version_str)
        
        if found:
            self.logger.info(f"✅ [ADOPT] {pkg_name} {version_str} found on server. Skipping build.")
            
            # Update local state
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
            
            # VCS PRIORITY FIX: Resolve version BEFORE checking server
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
            
            # SERVER-FIRST CHECK: Does this version exist on server?
            decision = self._check_server_for_package(pkg_name, version_str, is_aur=True)
            
            if decision == "ADOPT":
                # Package already on server, skip building
                continue
            
            # Package not on server or outdated, build it
            self.logger.info(f"🚀 Building {pkg_name} ({version_str})...")
            
            # Build package
            success = self.aur_builder.build(pkg_name, None)  # Pass None to force build
            
            if success:
                # INTERNAL SANITIZATION: Rename files with colons
                self._sanitize_artifacts(pkg_name)
                
                # Register built package
                self.version_tracker.register_built_package(pkg_name, version_str)
                self.build_state.add_built(pkg_name, version_str, is_aur=True)
                
                # Cleanup old versions from server (queued, not executed yet)
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
            
            # VCS PRIORITY FIX: Resolve version BEFORE checking server
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
            
            # SERVER-FIRST CHECK: Does this version exist on server?
            decision = self._check_server_for_package(pkg_name, version_str, is_aur=False)
            
            if decision == "ADOPT":
                # Package already on server, skip building
                continue
            
            # Package not on server or outdated, build it
            self.logger.info(f"🚀 Building {pkg_name} ({version_str})...")
            
            # Build package
            success = self.local_builder.build(pkg_name, None)  # Pass None to force build
            
            if success:
                # INTERNAL SANITIZATION: Rename files with colons
                self._sanitize_artifacts(pkg_name)
                
                # Register built package
                self.version_tracker.register_built_package(pkg_name, version_str)
                self.build_state.add_built(pkg_name, version_str, is_aur=False)
                
                # Cleanup old versions from server (queued, not executed yet)
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
        
        # Get all remote files
        remote_files = self.ssh_client.get_cached_inventory()
        if not remote_files:
            return
        
        # Find files for this package
        for remote_path in remote_files.values():
            filename = Path(remote_path).name
            
            # Parse filename
            parsed = self.version_tracker._parse_package_filename_with_arch(filename)
            if not parsed:
                continue
            
            remote_pkg_name, remote_version, architecture = parsed
            
            # Check if it's the same package (case-insensitive)
            if remote_pkg_name.lower() == pkg_name.lower():
                # Check if it's NOT the version we want to keep
                if not self.version_tracker._versions_match(remote_version, keep_version):
                    # Queue for deletion (will be executed after successful upload)
                    self.version_tracker.queue_deletion(remote_path)
                    self.logger.debug(f"🗑️ Queued for deletion: {filename} (old version: {remote_version})")
                else:
                    self.logger.debug(f"✅ Keeping: {filename} (current version: {remote_version})")
    
    def _update_server_database(self) -> bool:
        """
        Update repository database on server
        
        Returns:
            True if successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("REMOTE DATABASE UPDATE: Running repo-add on VPS")
        self.logger.info("=" * 60)
        
        repo_name = self.config.get('repo_name', '')
        remote_dir = self.config.get('remote_dir', '')
        
        # Run repo-add --remove on server
        remote_cmd = f"""
        cd "{remote_dir}" && 
        repo-add --remove "{repo_name}.db.tar.gz" *.pkg.tar.zst 2>&1
        """
        
        success, output = self.ssh_client.execute_remote_command(remote_cmd)
        
        if success:
            self.logger.info("✅ Database updated on server")
            self.logger.debug(f"Output: {output}")
            
            # Download database files for signing
            return self._download_and_sign_database()
        else:
            self.logger.error(f"❌ Failed to update database on server: {output}")
            return False
    
    def _download_and_sign_database(self) -> bool:
        """
        Download database files, sign them, and upload signatures
        
        Returns:
            True if successful
        """
        self.logger.info("\n📥 Downloading database files for signing...")
        
        repo_name = self.config.get('repo_name', '')
        remote_dir = self.config.get('remote_dir', '')
        output_dir = Path(self.config.get('output_dir', 'built_packages'))
        
        # Database files to download
        db_files = [
            f"{repo_name}.db",
            f"{repo_name}.db.tar.gz",
            f"{repo_name}.files",
            f"{repo_name}.files.tar.gz"
        ]
        
        # Download each file
        downloaded_files = []
        for db_file in db_files:
            remote_path = f"{remote_dir}/{db_file}"
            local_path = output_dir / db_file
            
            # Remove local copy if exists
            if local_path.exists():
                local_path.unlink()
            
            # Download via scp
            scp_cmd = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=30",
                f"{self.config.get('vps_user')}@{self.config.get('vps_host')}:{remote_path}",
                str(local_path)
            ]
            
            result = self.shell_executor.run(
                scp_cmd,
                capture=True,
                check=False,
                log_cmd=False
            )
            
            if result.returncode == 0 and local_path.exists():
                downloaded_files.append(local_path)
                self.logger.info(f"✅ Downloaded: {db_file}")
            else:
                self.logger.warning(f"⚠️ Could not download {db_file}")
        
        if not downloaded_files:
            self.logger.error("❌ No database files downloaded")
            return False
        
        # Sign database files if GPG is enabled
        if self.gpg_handler.gpg_enabled:
            self.logger.info("\n🔏 Signing database files with GPG...")
            
            for db_file in downloaded_files:
                if db_file.suffix in ['.db', '.files'] or '.db.' in db_file.name or '.files.' in db_file.name:
                    # Create detached signature
                    sig_file = db_file.with_suffix(db_file.suffix + '.sig')
                    
                    sign_cmd = [
                        "gpg",
                        "--detach-sign",
                        "--default-key", self.gpg_handler.gpg_key_id,
                        "--output", str(sig_file),
                        str(db_file)
                    ]
                    
                    result = self.shell_executor.run(
                        sign_cmd,
                        capture=True,
                        check=False,
                        log_cmd=False
                    )
                    
                    if result.returncode == 0 and sig_file.exists():
                        self.logger.info(f"✅ Signed: {db_file.name}")
                        downloaded_files.append(sig_file)
                    else:
                        self.logger.warning(f"⚠️ Failed to sign {db_file.name}")
        
        # Upload signatures back to server
        self.logger.info("\n📤 Uploading signatures to server...")
        
        # Filter for signature files
        sig_files = [f for f in downloaded_files if f.suffix == '.sig']
        
        if sig_files:
            files_to_upload = [str(f) for f in sig_files]
            upload_success = self.rsync_client.upload(files_to_upload, output_dir)
            
            if upload_success:
                self.logger.info(f"✅ Uploaded {len(sig_files)} signature file(s)")
            else:
                self.logger.warning("⚠️ Failed to upload some signatures")
        
        return True
    
    def _upload_new_packages(self) -> bool:
        """
        Upload newly built packages to server
        
        Returns:
            True if successful
        """
        output_dir = Path(self.config.get('output_dir'))
        
        # Get all package files in output directory
        package_files = list(output_dir.glob("*.pkg.tar.*"))
        
        if not package_files:
            self.logger.info("ℹ️ No new packages to upload")
            return True
        
        self.logger.info(f"\n📤 Uploading {len(package_files)} new package(s) to server...")
        
        # Upload packages
        files_to_upload = [str(f) for f in package_files]
        upload_success = self.rsync_client.upload(files_to_upload, output_dir)
        
        if upload_success:
            self.logger.info("✅ Packages uploaded successfully")
            
            # Now execute queued deletions
            self.logger.info("\n🧹 Executing queued cleanup operations...")
            cleanup_success = self.version_tracker.commit_queued_deletions()
            
            if cleanup_success:
                self.logger.info("✅ Cleanup operations completed")
            else:
                self.logger.warning("⚠️ Some cleanup operations failed")
            
            # Update server database
            return self._update_server_database()
        else:
            self.logger.error("❌ Package upload failed")
            return False
    
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
            
            # Initial setup
            self.logger.info("\n🔧 Initial setup...")
            self.logger.info(f"Repository root: {self.repo_root}")
            self.logger.info(f"Repository name: {self.config.get('repo_name')}")
            self.logger.info(f"Output directory: {self.config.get('output_dir')}")
            
            # STEP 0: Initialize GPG FIRST if enabled
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
            
            # STEP 1: TEST SSH CONNECTION
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 1: SSH CONNECTION TEST")
            self.logger.info("=" * 60)
            
            if not self.ssh_client.test_connection():
                self.logger.error("❌ SSH connection failed")
                return 1
            
            # DEBUG: List remote directory contents
            self.ssh_client.debug_remote_directory()
            
            # STEP 2: ENSURE REMOTE DIRECTORY EXISTS
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 2: REMOTE DIRECTORY SETUP")
            self.logger.info("=" * 60)
            
            if not self.ssh_client.ensure_directory():
                self.logger.warning("⚠️ Could not ensure remote directory exists")
            
            # STEP 3: GET PACKAGE LISTS
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 3: PACKAGE DISCOVERY")
            self.logger.info("=" * 60)
            
            self.local_packages, self.aur_packages = self._get_package_lists()
            
            self.logger.info(f"📦 Package statistics:")
            self.logger.info(f"   Local packages: {len(self.local_packages)}")
            self.logger.info(f"   AUR packages: {len(self.aur_packages)}")
            self.logger.info(f"   Total packages: {len(self.local_packages) + len(self.aur_packages)}")
            
            # STEP 4: SERVER-FIRST PACKAGE PROCESSING
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 4: SERVER-FIRST PACKAGE PROCESSING")
            self.logger.info("=" * 60)
            
            # Process AUR packages (server-first logic with git fix)
            self._build_aur_packages_server_first()
            
            # Process local packages (server-first logic)
            self._build_local_packages_server_first()
            
            # Check if we have any new packages
            output_dir = Path(self.config.get('output_dir'))
            new_packages = list(output_dir.glob("*.pkg.tar.*"))
            
            if new_packages:
                self.logger.info(f"\n📊 New packages built: {len(new_packages)}")
                
                # STEP 5: UPLOAD AND UPDATE SERVER
                self.logger.info("\n" + "=" * 60)
                self.logger.info("STEP 5: SERVER UPLOAD AND DATABASE UPDATE")
                self.logger.info("=" * 60)
                
                # Upload new packages and update database
                upload_success = self._upload_new_packages()
                
                if not upload_success:
                    self.logger.error("\n❌ Server upload failed!")
                    return 1
                
                # Clean up GPG
                self.gpg_handler.cleanup()
                
                self.logger.info("\n✅ Server update completed successfully!")
            else:
                self.logger.info("\n📊 No new packages were built - all packages already on server")
                
                # Save state even if no packages built
                self.version_tracker.save_state()
                
                # Clean up GPG
                self.gpg_handler.cleanup()
            
            # STEP 6: FINAL STATISTICS
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
            
            # State summary
            state_summary = self.version_tracker.get_state_summary()
            self.logger.info(f"Packages tracked: {state_summary['total_packages']}")
            self.logger.info("=" * 60)
            
            return 0
            
        except Exception as e:
            self.logger.error(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure GPG cleanup even on failure
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            
            # Save state on failure
            if hasattr(self, 'version_tracker'):
                self.version_tracker.save_state()
            
            return 1