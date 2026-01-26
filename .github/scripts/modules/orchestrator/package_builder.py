"""
Main orchestrator for package builder system
Coordinates all modules to execute the complete build workflow
"""

import os
import sys
import time
import logging
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
    """Main orchestrator that coordinates all modules for package building workflow"""
    
    def __init__(self):
        """Initialize PackageBuilder with all required modules"""
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
        
        # Phase 2: State management and VPS communication
        self.build_state = BuildState(self.logger)
        self.version_tracker = VersionTracker(self.logger)
        
        # VPS clients
        self.ssh_client = SSHClient(self.config, self.shell_executor, self.logger)
        self.rsync_client = RsyncClient(self.config, self.shell_executor, self.logger)
        
        # Setup SSH configuration
        ssh_key = self.config.get('ssh_key', '')
        self.ssh_client.setup_ssh_config(ssh_key)
        
        # Phase 3: Build and repository logic
        self.version_manager = VersionManager(self.shell_executor, self.logger)
        
        # Builders
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
        
        # Remote files cache
        self.remote_files: List[str] = []
        
        self.logger.info("✅ PackageBuilder initialized with all modules")
    
    def _get_package_lists(self) -> Tuple[List[str], List[str]]:
        """Get package lists from configuration"""
        if not self.local_packages or not self.aur_packages:
            self.local_packages, self.aur_packages = self.config_loader.get_package_lists()
        return self.local_packages, self.aur_packages
    
    def _check_repository_state(self) -> Tuple[bool, bool]:
        """Check repository existence and state on VPS"""
        return self.ssh_client.check_repository_exists()
    
    def _mirror_remote_packages(self) -> bool:
        """Mirror remote packages to local directory"""
        mirror_temp_dir = Path(self.config.get('mirror_temp_dir', '/tmp/repo_mirror'))
        output_dir = Path(self.config.get('output_dir'))
        
        self.logger.info("🔄 Mirroring remote packages locally...")
        return self.rsync_client.mirror_remote(
            remote_pattern="*.pkg.tar.*",
            local_dir=output_dir,
            temp_dir=mirror_temp_dir
        )
    
    def _get_remote_version(self, pkg_name: str) -> Optional[str]:
        """
        Get the version of a package from remote server using SRCINFO-based extraction
        
        Note: This replicates the original logic from PackageBuilder.get_remote_version
        """
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
    
    def _build_aur_packages(self) -> None:
        """Build all AUR packages"""
        if not self.aur_packages:
            self.logger.info("No AUR packages to build")
            return
        
        self.logger.info(f"\n🔨 Building {len(self.aur_packages)} AUR packages")
        
        for pkg_name in self.aur_packages:
            self.logger.info(f"\n--- Processing AUR: {pkg_name} ---")
            
            # Get remote version for comparison
            remote_version = self._get_remote_version(pkg_name)
            
            # Build package
            success = self.aur_builder.build(pkg_name, remote_version)
            
            if not success:
                self.build_state.add_failed(
                    pkg_name,
                    remote_version or "unknown",
                    is_aur=True,
                    error_message="AUR build failed"
                )
    
    def _build_local_packages(self) -> None:
        """Build all local packages"""
        if not self.local_packages:
            self.logger.info("No local packages to build")
            return
        
        self.logger.info(f"\n🔨 Building {len(self.local_packages)} local packages")
        
        for pkg_name in self.local_packages:
            self.logger.info(f"\n--- Processing Local: {pkg_name} ---")
            
            # Get remote version for comparison
            remote_version = self._get_remote_version(pkg_name)
            
            # Build package
            success = self.local_builder.build(pkg_name, remote_version)
            
            if not success:
                self.build_state.add_failed(
                    pkg_name,
                    remote_version or "unknown",
                    is_aur=False,
                    error_message="Local build failed"
                )
    
    def _sync_pacman_databases(self) -> bool:
        """Sync pacman databases with proper repository state"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("FINAL STEP: Syncing pacman databases")
        self.logger.info("=" * 60)
        
        # Check repository state
        exists, has_packages = self.ssh_client.check_repository_exists()
        
        # Apply repository state to pacman.conf
        self._apply_repository_state(exists, has_packages)
        
        if not exists:
            self.logger.info("ℹ️ Repository doesn't exist on VPS, skipping pacman sync")
            return False
        
        # Run pacman -Sy
        cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        result = self.shell_executor.run(
            cmd,
            log_cmd=True,
            timeout=300,
            check=False
        )
        
        if result.returncode == 0:
            self.logger.info("✅ Pacman databases synced successfully")
            
            # Debug: List packages in our custom repo
            debug_cmd = f"sudo pacman -Sl {self.config.get('repo_name')}"
            self.logger.info(f"🔍 DEBUG: Running command to see what packages pacman sees in our repo:")
            self.logger.info(f"Command: {debug_cmd}")
            
            debug_result = self.shell_executor.run(
                debug_cmd,
                log_cmd=True,
                timeout=30,
                check=False
            )
            
            if debug_result.returncode == 0:
                if debug_result.stdout.strip():
                    self.logger.info(f"Packages in {self.config.get('repo_name')} according to pacman:")
                    for line in debug_result.stdout.splitlines():
                        self.logger.info(f"  {line}")
                else:
                    self.logger.warning(f"⚠️ pacman -Sl returned no output (repo might be empty)")
            else:
                self.logger.warning(f"⚠️ pacman -Sl failed: {debug_result.stderr[:200]}")
            
            return True
        else:
            self.logger.error("❌ Pacman sync failed")
            if result.stderr:
                self.logger.error(f"Error: {result.stderr[:500]}")
            return False
    
    def _apply_repository_state(self, exists: bool, has_packages: bool):
        """
        Apply repository state with proper SigLevel based on discovery
        Replicates original logic from PackageBuilder._apply_repository_state
        """
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            self.logger.warning("pacman.conf not found")
            return
        
        import tempfile
        import subprocess
        
        repo_name = self.config.get('repo_name')
        repo_server_url = self.config.get('repo_server_url', '')
        
        try:
            with open(pacman_conf, 'r') as f:
                content = f.read()
            
            repo_section = f"[{repo_name}]"
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
                new_lines.append(f"# Custom repository: {repo_name}")
                new_lines.append(f"# Automatically enabled - found on VPS")
                new_lines.append(repo_section)
                if has_packages:
                    new_lines.append("SigLevel = Optional TrustAll")
                    self.logger.info("✅ Enabling repository with SigLevel = Optional TrustAll (build mode)")
                else:
                    new_lines.append("# SigLevel = Optional TrustAll")
                    new_lines.append("# Repository exists but has no packages yet")
                    self.logger.info("⚠️ Repository section added but commented (no packages yet)")
                
                if repo_server_url:
                    new_lines.append(f"Server = {repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
            else:
                # Repository doesn't exist on VPS, add commented section
                new_lines.append('')
                new_lines.append(f"# Custom repository: {repo_name}")
                new_lines.append(f"# Disabled - not found on VPS (first run?)")
                new_lines.append(f"#{repo_section}")
                new_lines.append("#SigLevel = Optional TrustAll")
                if repo_server_url:
                    new_lines.append(f"#Server = {repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
                self.logger.info("ℹ️ Repository not found on VPS - keeping disabled")
            
            # Write back to pacman.conf
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write('\n'.join(new_lines))
                temp_path = temp_file.name
            
            # Copy to pacman.conf
            subprocess.run(['sudo', 'cp', temp_path, str(pacman_conf)], check=False)
            subprocess.run(['sudo', 'chmod', '644', str(pacman_conf)], check=False)
            os.unlink(temp_path)
            
            self.logger.info(f"✅ Updated pacman.conf for repository '{repo_name}'")
            
            # CRITICAL FIX: Run pacman -Sy after enabling repository to synchronize databases
            if exists and has_packages:
                self.logger.info("🔄 Synchronizing pacman databases after enabling repository...")
                cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
                result = self.shell_executor.run(cmd, log_cmd=True, timeout=300, check=False)
                if result.returncode == 0:
                    self.logger.info("✅ Pacman databases synchronized successfully")
                else:
                    self.logger.warning(f"⚠️ Pacman sync warning: {result.stderr[:200]}")
            
        except Exception as e:
            self.logger.error(f"Failed to apply repository state: {e}")
    
    def _upload_packages(self) -> bool:
        """Upload packages to server using RSYNC"""
        output_dir = Path(self.config.get('output_dir'))
        
        # Get all package files and database files
        import glob
        file_patterns = [
            str(output_dir / "*.pkg.tar.*"),
            str(output_dir / f"{self.config.get('repo_name')}.*")
        ]
        
        files_to_upload = []
        for pattern in file_patterns:
            files_to_upload.extend(glob.glob(pattern))
        
        if not files_to_upload:
            self.logger.error("No files found to upload!")
            self.cleanup_manager.set_upload_successful(False)
            return False
        
        # Upload files using Rsync client
        upload_success = self.rsync_client.upload(files_to_upload, output_dir)
        
        # Set upload success flag for cleanup
        self.cleanup_manager.set_upload_successful(upload_success)
        
        return upload_success
    
    def run(self) -> int:
        """
        Main execution workflow
        
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        try:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("🚀 MANJARO PACKAGE BUILDER (MODULAR ARCHITECTURE)")
            self.logger.info("=" * 60)
            
            # Initial setup
            self.logger.info("\n🔧 Initial setup...")
            self.logger.info(f"Repository root: {self.repo_root}")
            self.logger.info(f"Repository name: {self.config.get('repo_name')}")
            self.logger.info(f"Output directory: {self.config.get('output_dir')}")
            self.logger.info(f"PACKAGER identity: {self.config.get('packager_id')}")
            
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
            
            # STEP 1: SIMPLIFIED REPOSITORY DISCOVERY
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 1: SIMPLIFIED REPOSITORY STATE DISCOVERY")
            self.logger.info("=" * 60)
            
            # Check if repository exists on VPS
            repo_exists, has_packages = self._check_repository_state()
            
            # Apply repository state based on discovery
            self._apply_repository_state(repo_exists, has_packages)
            
            # Ensure remote directory exists
            self.ssh_client.ensure_directory()
            
            # STEP 2: List remote packages for version comparison
            self.remote_files = self.ssh_client.list_remote_files()
            
            # MANDATORY STEP: Mirror ALL remote packages locally before any database operations
            if self.remote_files:
                self.logger.info("\n" + "=" * 60)
                self.logger.info("MANDATORY PRECONDITION: Mirroring remote packages locally")
                self.logger.info("=" * 60)
                
                if not self._mirror_remote_packages():
                    self.logger.error("❌ FAILED to mirror remote packages locally")
                    self.logger.error("Cannot proceed without local package mirror")
                    return 1
            else:
                self.logger.info("ℹ️ No remote packages to mirror (repository appears empty)")
            
            # STEP 3: Check existing database files
            existing_db_files, missing_db_files = self.database_manager.check_database_files()
            
            # Fetch existing database if available
            if existing_db_files:
                self.database_manager.fetch_existing_database(existing_db_files)
            
            # Get package lists
            self.local_packages, self.aur_packages = self._get_package_lists()
            
            self.logger.info(f"\n📦 Package statistics:")
            self.logger.info(f"   Local packages: {len(self.local_packages)}")
            self.logger.info(f"   AUR packages: {len(self.aur_packages)}")
            self.logger.info(f"   Total packages: {len(self.local_packages) + len(self.aur_packages)}")
            
            # STEP 4: PACKAGE BUILDING (SRCINFO VERSIONING)
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 4: PACKAGE BUILDING (SRCINFO VERSIONING)")
            self.logger.info("=" * 60)
            
            self._build_aur_packages()
            self._build_local_packages()
            
            # Check if we have any packages locally
            output_dir = Path(self.config.get('output_dir'))
            local_packages = list(output_dir.glob("*.pkg.tar.*"))
            
            if local_packages or self.remote_files:
                self.logger.info("\n" + "=" * 60)
                self.logger.info("STEP 5: REPOSITORY DATABASE HANDLING (WITH LOCAL MIRROR)")
                self.logger.info("=" * 60)
                
                # ZERO-RESIDUE FIX: Perform server cleanup BEFORE database generation
                self.logger.info("\n" + "=" * 60)
                self.logger.info("🚨 PRE-DATABASE CLEANUP: Removing zombie packages from server")
                self.logger.info("=" * 60)
                self.cleanup_manager.cleanup_server()
                
                # Final validation before database generation
                self.cleanup_manager.validate_output_dir()
                
                # Generate database with ALL locally available packages
                if self.database_manager.generate_database():
                    # Sign repository database files if GPG is enabled
                    if self.gpg_handler.gpg_enabled:
                        if not self.gpg_handler.sign_repository_files(
                            self.config.get('repo_name'),
                            str(self.config.get('output_dir'))
                        ):
                            self.logger.warning("⚠️ Failed to sign repository files, continuing anyway")
                    
                    # Test SSH connection before upload
                    if not self.ssh_client.test_connection():
                        self.logger.warning("SSH test failed, but trying upload anyway...")
                    
                    # Upload everything (packages + database + signatures)
                    upload_success = self._upload_packages()
                    
                    # ZERO-RESIDUE FIX: Perform final server cleanup AFTER upload
                    if upload_success:
                        self.logger.info("\n" + "=" * 60)
                        self.logger.info("🚨 POST-UPLOAD CLEANUP: Final zombie package removal")
                        self.logger.info("=" * 60)
                        self.cleanup_manager.cleanup_server()
                    
                    # Clean up GPG temporary directory
                    self.gpg_handler.cleanup()
                    
                    if upload_success:
                        # STEP 6: Update repository state and sync pacman
                        self.logger.info("\n" + "=" * 60)
                        self.logger.info("STEP 6: FINAL REPOSITORY STATE UPDATE")
                        self.logger.info("=" * 60)
                        
                        # Re-check repository state (it should exist now)
                        repo_exists, has_packages = self._check_repository_state()
                        self._apply_repository_state(repo_exists, has_packages)
                        
                        # Sync pacman databases
                        self._sync_pacman_databases()
                        
                        self.logger.info("\n✅ Build completed successfully!")
                    else:
                        self.logger.error("\n❌ Upload failed!")
                        return 1
                else:
                    self.logger.error("\n❌ Database generation failed!")
                    return 1
            else:
                self.logger.info("\n📊 Build summary:")
                summary = self.build_state.get_summary()
                self.logger.info(f"   AUR packages built: {summary['aur_success']}")
                self.logger.info(f"   AUR packages failed: {summary['aur_failed']}")
                self.logger.info(f"   Local packages built: {summary['local_success']}")
                self.logger.info(f"   Local packages failed: {summary['local_failed']}")
                self.logger.info(f"   Total skipped: {summary['skipped']}")
                
                if summary['aur_failed'] > 0 or summary['local_failed'] > 0:
                    self.logger.info("⚠️ Some packages failed to build")
                else:
                    self.logger.info("✅ All packages are up to date or built successfully!")
                
                # Clean up GPG even if no packages built
                self.gpg_handler.cleanup()
            
            # Final statistics
            self.build_state.mark_complete()
            summary = self.build_state.get_summary()
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("📊 BUILD SUMMARY")
            self.logger.info("=" * 60)
            self.logger.info(f"Duration: {summary['duration_seconds']:.1f}s")
            self.logger.info(f"AUR packages:    {summary['aur_success']} (failed: {summary['aur_failed']})")
            self.logger.info(f"Local packages:  {summary['local_success']} (failed: {summary['local_failed']})")
            self.logger.info(f"Total built:     {summary['built']}")
            self.logger.info(f"Skipped:         {summary['skipped']}")
            self.logger.info(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            self.logger.info(f"PACKAGER:        {self.config.get('packager_id')}")
            self.logger.info(f"Zero-Residue:    ✅ Exact-filename-match cleanup active")
            self.logger.info(f"Target Version:  ✅ Package target versions registered: {len(self.version_tracker.get_target_packages())}")
            self.logger.info(f"Skipped Registry:✅ Skipped packages tracked: {len(self.version_tracker.get_skipped_packages_dict())}")
            self.logger.info("=" * 60)
            
            # List built packages
            built_packages = self.build_state.get_built_packages()
            if built_packages:
                self.logger.info("\n📦 Built packages:")
                for pkg in built_packages:
                    self.logger.info(f"  - {pkg['name']} ({pkg['version']})")
            
            return 0
            
        except Exception as e:
            self.logger.error(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure GPG cleanup even on failure
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            
            return 1