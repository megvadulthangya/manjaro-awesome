"""
Manjaro Package Builder Orchestrator
Sequences the build process: Prepare -> Build -> Repo-Add -> Upload -> Commit
"""

import os
import shutil
import logging
from typing import List, Tuple

# Common Modules
from modules.common.logging_utils import setup_logging, get_logger
from modules.common.config_loader import ConfigLoader
from modules.common.environment import EnvironmentValidator
from modules.common.shell_executor import ShellExecutor

# State & Tracking
from modules.orchestrator.state import BuildState
from modules.repo.version_tracker import VersionTracker
from modules.build.build_tracker import BuildTracker
from modules.build.artifact_manager import ArtifactManager

# SCM & VPS
from modules.scm.git_client import GitClient
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient

# Logic Managers
from modules.build.version_manager import VersionManager
from modules.build.aur_builder import AURBuilder
from modules.build.local_builder import LocalBuilder
from modules.repo.database_manager import DatabaseManager
from modules.repo.cleanup_manager import CleanupManager
from modules.repo.recovery_manager import RecoveryManager
from modules.gpg.gpg_handler import GPGHandler

class PackageBuilder:
    """Orchestrator for the package build process"""
    
    def __init__(self):
        self.logger = get_logger(__name__)
        
        # 1. Environment & Config
        self.env_validator = EnvironmentValidator(self.logger)
        self.repo_root = self.env_validator.get_repo_root()
        
        self.config_loader = ConfigLoader(self.repo_root, self.logger)
        self.config = self.config_loader.load_config()
        
        setup_logging(self.config.get('debug_mode', False))
        
        # 2. Base Infrastructure
        self.shell_executor = ShellExecutor(self.config.get('debug_mode', False))
        
        # 3. Clients & Handlers
        self.git_client = GitClient(self.config, self.shell_executor, self.logger)
        self.ssh_client = SSHClient(self.config, self.shell_executor, self.logger)
        self.rsync_client = RsyncClient(self.config, self.shell_executor, self.logger)
        self.gpg_handler = GPGHandler(self.config)
        
        # 4. State Managers
        self.build_state = BuildState(self.logger)
        self.version_tracker = VersionTracker(self.repo_root, self.ssh_client, self.logger)
        self.version_manager = VersionManager(self.shell_executor, self.logger)
        
        # 5. Logic Managers
        self.artifact_manager = ArtifactManager(self.config, self.logger)
        self.recovery_manager = RecoveryManager(self.config, self.ssh_client, self.logger)
        self.database_manager = DatabaseManager(self.config, self.ssh_client, self.rsync_client, self.logger)
        self.cleanup_manager = CleanupManager(self.config, self.version_tracker, self.ssh_client, self.rsync_client, self.logger)
        
        # BuildTracker deferred until clone is ready
        self.build_tracker = None
        
        self.local_packages: List[str] = []
        self.aur_packages: List[str] = []
        self._staging_dir = None
        self._has_changes = False

    def _sync_pacman(self):
        """Sync pacman databases"""
        self.logger.info("Syncing pacman databases...")
        self.shell_executor.run("sudo LC_ALL=C pacman -Sy --noconfirm", check=False)

    def run(self) -> int:
        """Main execution sequence"""
        try:
            self.logger.info("🚀 STARTING BUILD PROCESS")
            
            # --- 1. PREPARE ---
            self._sync_pacman()
            
            if self.gpg_handler.gpg_enabled:
                self.gpg_handler.import_gpg_key()
                
            self.ssh_client.setup_ssh_config(self.config.get('vps_ssh_key'))
            
            if not self.ssh_client.test_connection():
                self.logger.error("❌ SSH connection failed - Aborting")
                return 1
                
            self.ssh_client.ensure_directory()
            
            # --- 2. CLONE TRACKING REPO ---
            if not self.git_client.clone_repo():
                self.logger.error("❌ Clone failed - Aborting")
                return 1
                
            # Initialize BuildTracker inside the cloned repo
            temp_tracker_dir = self.git_client.clone_dir / ".build_tracking"
            temp_tracker_dir.mkdir(exist_ok=True)
            self.build_tracker = BuildTracker(
                temp_tracker_dir,
                self.version_tracker,
                self.version_manager,
                self.logger
            )
            
            # --- 3. DISCOVERY ---
            self.local_packages, self.aur_packages = self.config_loader.get_package_lists()
            
            # --- 4. BUILD PHASE ---
            # Builds packages and puts them in output_dir
            self._process_local_packages()
            self._process_aur_packages()
            
            # --- 5. REPO UPDATE PHASE ---
            # Only proceed if we have built something OR we want to force a sync
            # But technically self-healing should run regardless.
            if not self._update_database_sequence():
                self.logger.error("❌ Database/Upload sequence failed - Aborting commit")
                return 1
            
            # --- 6. COMMIT PHASE ---
            # Only commit if database update was successful and we actually did something
            if self._has_changes:
                self.logger.info("💾 Saving changes to git...")
                self.git_client.commit_and_push()
            else:
                self.logger.info("ℹ️ No build changes detected, skipping git commit")
            
            # --- 7. CLEANUP ---
            self.gpg_handler.cleanup()
            self.build_state.mark_complete()
            
            self.logger.info("✅ BUILD COMPLETED SUCCESSFULLY")
            return 0
            
        except Exception as e:
            self.logger.error(f"❌ BUILD FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.gpg_handler.cleanup()
            return 1

    def _process_local_packages(self):
        """Process local packages using temp clone"""
        if not self.local_packages: return
        
        self.logger.info("🔨 Processing Local Packages")
        
        # Configure LocalBuilder to use temp clone as source
        clone_config = self.config.copy()
        clone_config['repo_root'] = self.git_client.clone_dir
        local_builder = LocalBuilder(
            clone_config,
            self.shell_executor,
            self.version_manager,
            self.version_tracker,
            self.build_state,
            self.logger
        )
        
        for pkg in self.local_packages:
            pkg_dir = self.git_client.clone_dir / pkg
            should_build, tracking_data = self.build_tracker.should_build(pkg, pkg_dir)
            
            if should_build:
                # Pass explicit pkg_dir to builder
                success = local_builder.build(pkg, pkg_dir)
                if success:
                    self._has_changes = True
                    # Update tracking info in JSON (staged for commit)
                    pkgver, pkgrel, epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
                    version_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
                    
                    tracking_data.update({
                        'pkgver': pkgver,
                        'pkgrel': pkgrel,
                        'epoch': epoch,
                        'last_hash': tracking_data.get('last_hash'),
                        'last_version': version_str
                    })
                    
                    self.build_tracker.save_tracking(pkg, tracking_data)
                    self.artifact_manager.sanitize_artifacts(pkg)
                else:
                    self.logger.error(f"❌ Failed to build {pkg}")
            else:
                self.build_state.add_skipped(pkg, tracking_data.get('last_version', 'unknown'), False)

    def _process_aur_packages(self):
        """Process AUR packages"""
        if not self.aur_packages: return
        self.logger.info("🔨 Processing AUR Packages")
        
        # Instantiate AUR Builder
        aur_builder = AURBuilder(
            self.config,
            self.shell_executor,
            self.version_manager,
            self.version_tracker,
            self.build_state,
            self.logger
        )
        
        for pkg in self.aur_packages:
            # For now, simplistic approach: Always try to build AUR packages
            # Real logic would check remote version if possible
            success = aur_builder.build(pkg, None)
            if success:
                self._has_changes = True
                self.artifact_manager.sanitize_artifacts(pkg)

    def _update_database_sequence(self) -> bool:
        """Execute self-healing database update sequence"""
        self.logger.info("🔄 Starting Database Update Sequence")
        
        try:
            # 1. Prepare Staging
            self._staging_dir = self.database_manager.create_staging_dir()
            
            # 2. Download Existing DB (to append to it)
            self.database_manager.download_existing_database()
            
            # 3. Auto-Recovery (Get missing files from VPS to Staging)
            self.recovery_manager.reset()
            missing = self.recovery_manager.discover_missing(self._staging_dir)
            if missing:
                self.recovery_manager.download_missing(missing, self._staging_dir)
            
            # 4. Move NEW artifacts from output_dir to staging
            # This merges newly built files with the existing/recovered ones
            self.artifact_manager.move_to_staging(self._staging_dir)
            
            # 5. Update DB (Additive - scans staging dir)
            if not self.database_manager.update_database_additive():
                self.logger.error("Failed to update database")
                return False
                
            # 6. Upload Everything (DB + Packages) to VPS
            if not self.database_manager.upload_updated_files():
                self.logger.error("Failed to upload files")
                return False
                
            # 7. Cleanup Remote Zombies
            self.cleanup_manager.cleanup_server()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Database sequence exception: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self.database_manager.cleanup_staging_dir()