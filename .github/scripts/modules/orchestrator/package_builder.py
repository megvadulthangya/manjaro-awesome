"""
Manjaro Package Builder Orchestrator
Sequences the build process with Upstream-First logic and Yay fallback.
"""

import os
import shutil
import logging
import subprocess
from typing import List, Tuple, Optional

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
        self.recovery_manager = RecoveryManager(self.config, self.ssh_client, self.logger)
        self.database_manager = DatabaseManager(self.config, self.ssh_client, self.rsync_client, self.logger)
        self.cleanup_manager = CleanupManager(self.config, self.version_tracker, self.ssh_client, self.rsync_client, self.logger)
        
        self.build_tracker = None
        self.local_packages: List[str] = []
        self.aur_packages: List[str] = []
        self._staging_dir = None
        self._has_changes = False

    def run(self) -> int:
        """Main execution sequence"""
        try:
            self.logger.info("🚀 STARTING BUILD PROCESS (UPSTREAM-FIRST)")
            
            # --- 1. SETUP ---
            self.ssh_client.setup_ssh_config(self.config.get('vps_ssh_key'))
            if not self.ssh_client.test_connection():
                return 1
            self.ssh_client.ensure_directory()
            
            # --- 2. CLONE ---
            if not self.git_client.clone_repo():
                return 1
            
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
            
            # --- 4. PREPARE STAGING & DB ---
            self._staging_dir = self.database_manager.create_staging_dir()
            self.database_manager.download_existing_database()
            
            # --- 5. BUILD LOOP ---
            self._process_local_packages()
            self._process_aur_packages()
            
            # --- 6. UPDATE REPO ---
            if not self._update_database_sequence():
                return 1
            
            # --- 7. COMMIT ---
            if self._has_changes:
                self.logger.info("💾 Saving changes to git...")
                self.git_client.commit_and_push()
            else:
                self.logger.info("ℹ️ No changes to commit")
            
            # --- 8. CLEANUP ---
            self.database_manager.cleanup_staging_dir()
            self.build_state.mark_complete()
            
            self.logger.info("✅ BUILD COMPLETED SUCCESSFULLY")
            return 0
            
        except Exception as e:
            self.logger.error(f"❌ BUILD FAILED: {e}")
            return 1

    def _get_remote_version_raw(self, pkg_name: str) -> Optional[str]:
        inventory = self.ssh_client.get_cached_inventory()
        for filename in inventory.keys():
            if not filename.endswith('.pkg.tar.zst'): continue
            
            parts = filename.split('-')
            if len(parts) < 4: continue
            
            if filename.startswith(f"{pkg_name}-"):
                try:
                    name_parts = parts[:-3]
                    extracted_name = "-".join(name_parts)
                    if extracted_name == pkg_name:
                        return f"{parts[-3]}-{parts[-2]}"
                except Exception:
                    continue
        return None

    def _process_local_packages(self):
        self.logger.info("🔨 Processing Local Packages")
        
        clone_config = self.config.copy()
        clone_config['repo_root'] = self.git_client.clone_dir
        local_builder = LocalBuilder(
            clone_config, self.shell_executor, self.version_manager,
            self.version_tracker, self.build_state, self.logger
        )
        
        for pkg in self.local_packages:
            pkg_dir = self.git_client.clone_dir / pkg
            if not pkg_dir.exists(): continue

            # 1. Get current PKGBUILD version
            pkgver, pkgrel, epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
            current_ver_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            # 2. Check for dynamic updates (pkgver() function)
            dynamic_ver = self.version_manager.get_local_git_version(pkg_dir)
            
            target_ver = dynamic_ver if dynamic_ver else current_ver_str
            remote_ver = self._get_remote_version_raw(pkg)
            
            self.logger.info(f"🧐 CHECK {pkg}: Target='{target_ver}' | Remote='{remote_ver or 'None'}'")
            
            needs_build = False
            if remote_ver != target_ver:
                self.logger.info(f"🔄 Version mismatch. Building {pkg}...")
                needs_build = True
                
            if needs_build:
                if self._attempt_build_with_fallback(local_builder, pkg, pkg_dir):
                    # Tracking updated in fallback
                    pass
            else:
                self.logger.info(f"✅ {pkg} is up-to-date")

    def _process_aur_packages(self):
        self.logger.info("🔨 Processing AUR Packages")
        
        aur_builder = AURBuilder(
            self.config, self.shell_executor, self.version_manager,
            self.version_tracker, self.build_state, self.logger
        )
        
        for pkg in self.aur_packages:
            remote_ver = self._get_remote_version_raw(pkg)
            self.logger.info(f"🧐 CHECK AUR {pkg}: Remote='{remote_ver or 'None'}'")
            
            needs_build = False
            if remote_ver:
                # Upstream Check
                has_update, new_ver = self.version_manager.check_upstream_version(pkg, remote_ver)
                if has_update:
                    self.logger.info(f"🆕 Upstream update found: {new_ver} > {remote_ver}")
                    needs_build = True
                else:
                    self.logger.info(f"ℹ️ Upstream is not newer")
            else:
                self.logger.info(f"🆕 Package {pkg} not on VPS. Building...")
                needs_build = True

            if needs_build:
                self._attempt_build_with_fallback(aur_builder, pkg, None)

    def _attempt_build_with_fallback(self, builder, pkg_name: str, pkg_dir: Optional[str]) -> bool:
        self.logger.info(f"🏗️ Building Package: {pkg_name}")
        
        success = builder.build(pkg_name, pkg_dir)
        
        if not success:
            self.logger.warning(f"⚠️ Build failed. Attempting Yay Fallback for dependencies...")
            
            # 1. Install deps with Yay (bypassing local db issues if possible)
            try:
                # If pkg_dir exists (local), try to get deps from SRCINFO
                # For now, simplistic approach: update yay db and try to install package deps
                # This is tricky without parsing depends. 
                # Strategy: Run yay -Sy to ensure it sees AUR
                self.shell_executor.run("yay -Sy", check=False)
                
                # Retry Build
                self.logger.info("🔄 Retrying build after yay sync...")
                success = builder.build(pkg_name, pkg_dir)
            except Exception:
                pass
        
        if success:
            self._has_changes = True
            self.artifact_manager.move_to_staging(self._staging_dir)
            self.artifact_manager.sanitize_artifacts(pkg_name)
            self.logger.info(f"✅ Build successful: {pkg_name}")
            return True
        
        self.logger.error(f"❌ Failed to build {pkg_name}")
        return False

    def _update_database_sequence(self) -> bool:
        self.logger.info("🔄 Starting Database Update Sequence")
        
        # Auto-Recovery
        self.recovery_manager.reset()
        missing = self.recovery_manager.discover_missing(self._staging_dir)
        if missing:
            self.recovery_manager.download_missing(missing, self._staging_dir)
        
        # Update DB (with isolated GPG home)
        if not self.database_manager.update_database_additive():
            self.logger.error("Failed to update database")
            return False
            
        # Upload
        if not self.database_manager.upload_updated_files():
            self.logger.error("Failed to upload files")
            return False
            
        self.cleanup_manager.cleanup_server()
        return True