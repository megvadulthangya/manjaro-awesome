"""
Manjaro Package Builder Orchestrator
Refactored logic to prevent dependency loops and ensure valid builds.
"""

import os
import shutil
import logging
from typing import List, Tuple, Set

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
        
        # 1. Config
        self.env_validator = EnvironmentValidator(self.logger)
        self.repo_root = self.env_validator.get_repo_root()
        self.config_loader = ConfigLoader(self.repo_root, self.logger)
        self.config = self.config_loader.load_config()
        
        setup_logging(self.config.get('debug_mode', False))
        
        # 2. Base
        self.shell_executor = ShellExecutor(self.config.get('debug_mode', False))
        
        # 3. Clients
        self.git_client = GitClient(self.config, self.shell_executor, self.logger)
        self.ssh_client = SSHClient(self.config, self.shell_executor, self.logger)
        self.rsync_client = RsyncClient(self.config, self.shell_executor, self.logger)
        self.gpg_handler = GPGHandler(self.config)
        
        # 4. Managers
        self.build_state = BuildState(self.logger)
        self.version_tracker = VersionTracker(self.repo_root, self.ssh_client, self.logger)
        self.version_manager = VersionManager(self.shell_executor, self.logger)
        self.artifact_manager = ArtifactManager(self.config, self.logger)
        self.database_manager = DatabaseManager(self.config, self.ssh_client, self.rsync_client, self.logger)
        self.cleanup_manager = CleanupManager(self.config, self.version_tracker, self.ssh_client, self.rsync_client, self.logger)
        self.recovery_manager = RecoveryManager(self.config, self.ssh_client, self.logger)
        
        # Deferred
        self.build_tracker = None
        self._staging_dir = None
        self._has_changes = False

    def run(self) -> int:
        """Main execution sequence"""
        try:
            self.logger.info("🚀 STARTING BUILD PROCESS (FIXED LOGIC)")
            
            # --- 1. SETUP & REPAIR ---
            if self.gpg_handler.gpg_enabled:
                self.gpg_handler.import_gpg_key()
            
            self.ssh_client.setup_ssh_config(self.config.get('vps_ssh_key'))
            if not self.ssh_client.test_connection():
                self.logger.error("❌ SSH connection failed")
                return 1
            
            # Ensure we have a clean slate locally
            self.shell_executor.run("sudo rm -f /var/lib/pacman/db.lck", check=False)
            self.shell_executor.run("sudo LC_ALL=C pacman -Sy --noconfirm", check=False)
            
            # --- 2. CLONE ---
            if not self.git_client.clone_repo():
                return 1
            
            # Init tracker in clone dir
            tracker_dir = self.git_client.clone_dir / ".build_tracking"
            tracker_dir.mkdir(exist_ok=True)
            self.build_tracker = BuildTracker(
                tracker_dir,
                self.version_tracker,
                self.version_manager,
                self.logger
            )
            
            # --- 3. PREPARE STAGING ---
            # We create staging EARLY to accumulate artifacts
            self._staging_dir = self.database_manager.create_staging_dir()
            self.database_manager.download_existing_database()
            
            # --- 4. RECOVERY ---
            # Get files that are on VPS but not in DB (or just ensure we have them for repo-add)
            # Actually, for additive repo-add, we just need the DB file.
            # But if we want to ensure consistency, we might need missing pkgs.
            # For now, let's trust the DB download.
            
            # --- 5. BUILD LOOP ---
            local_pkgs, aur_pkgs = self.config_loader.get_package_lists()
            
            # Initialize builders
            clone_config = self.config.copy()
            clone_config['repo_root'] = self.git_client.clone_dir
            local_builder = LocalBuilder(
                clone_config, self.shell_executor, self.version_manager, 
                self.version_tracker, self.build_state, self.logger
            )
            aur_builder = AURBuilder(
                self.config, self.shell_executor, self.version_manager,
                self.version_tracker, self.build_state, self.logger
            )
            
            # Process Local
            for pkg in local_pkgs:
                self._process_package(pkg, is_aur=False, builder=local_builder)
                
            # Process AUR
            for pkg in aur_pkgs:
                self._process_package(pkg, is_aur=True, builder=aur_builder)
            
            # --- 6. FINALIZE ---
            if self._has_changes:
                # Update DB with everything in staging
                if self.database_manager.update_database_additive():
                    if self.database_manager.upload_updated_files():
                        self.logger.info("💾 Committing tracking data...")
                        self.git_client.commit_and_push()
                    else:
                        self.logger.error("❌ Upload failed")
                        return 1
                else:
                    self.logger.error("❌ Database update failed")
                    return 1
            else:
                self.logger.info("✨ No changes to apply.")
            
            return 0
            
        except Exception as e:
            self.logger.error(f"❌ CRITICAL FAILURE: {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            self.gpg_handler.cleanup()
            self.database_manager.cleanup_staging_dir()

    def _process_package(self, pkg_name: str, is_aur: bool, builder):
        """
        Smart build logic: Check Remote -> Build -> Stage
        """
        self.logger.info(f"🔍 Checking {pkg_name}...")
        
        # 1. Determine Local Version
        pkg_dir = None
        if not is_aur:
            pkg_dir = self.git_client.clone_dir / pkg_name
            if not pkg_dir.exists():
                self.logger.error(f"❌ Local pkg dir not found: {pkg_dir}")
                return
            
            pkgver, pkgrel, epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
        else:
            # For AUR, we must assume we need to check online or clone temp
            # This is a simplification: AUR builder handles internal check/clone usually.
            # But we need a version to compare.
            # For this strict fix, we let the AUR builder decide or force build if not on remote.
            pkgver, pkgrel, epoch = None, None, None

        local_version_str = "unknown"
        if pkgver and pkgrel:
            local_version_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)

        # 2. Check Remote
        # We need to know if this version exists on the server.
        # If is_aur, we might not know local version yet without cloning.
        
        needs_build = True
        
        if local_version_str != "unknown":
            is_on_remote, remote_ver, _ = self.version_tracker.is_package_on_remote(pkg_name, local_version_str)
            if is_on_remote:
                self.logger.info(f"✅ {pkg_name} {local_version_str} is up-to-date on server. Skipping.")
                needs_build = False
        
        # 3. Build if needed
        if needs_build:
            success = False
            if is_aur:
                # AUR Builder handles its own cloning/version check logic internally
                # but we should ensure it returns True ONLY if artifacts are made.
                success = builder.build(pkg_name)
            else:
                success = builder.build(pkg_name, pkg_dir)
            
            if success:
                self.logger.info(f"📦 Build successful for {pkg_name}. Staging artifacts.")
                self.artifact_manager.move_to_staging(self._staging_dir)
                self._has_changes = True
                
                # Update tracking if local
                if not is_aur and self.build_tracker:
                    # Re-extract version in case build updated it (dynamic pkgver)
                    pkgver, pkgrel, epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
                    v_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
                    
                    data = self.build_tracker.load_tracking(pkg_name)
                    data.update({
                        'last_version': v_str,
                        'pkgver': pkgver,
                        'pkgrel': pkgrel,
                        'epoch': epoch
                    })
                    self.build_tracker.save_tracking(pkg_name, data)
            else:
                self.logger.warning(f"⚠️ Build failed or skipped for {pkg_name}")