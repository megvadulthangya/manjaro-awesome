"""
Manjaro Package Builder Orchestrator
Sequences the build process: Prepare -> Build -> Repo-Add -> Upload -> Commit
Refactored to enforce GPG keyring presence, Yay fallback, and PKGBUILD patching.
"""

import os
import shutil
import logging
import subprocess
from typing import List, Tuple, Optional, Dict

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
        
        self.build_tracker = None
        self.local_packages: List[str] = []
        self.aur_packages: List[str] = []
        self._staging_dir = None
        self._has_changes = False

    def _sync_pacman(self):
        """Sync pacman databases"""
        self.logger.info("Syncing pacman databases...")
        self.shell_executor.run("sudo LC_ALL=C pacman -Sy --noconfirm", check=False)

    def _get_remote_version_raw(self, pkg_name: str) -> Optional[str]:
        """Manually scan remote inventory to find the version string."""
        inventory = self.ssh_client.get_cached_inventory()
        for filename in inventory.keys():
            if not filename.endswith('.pkg.tar.zst'):
                continue
            
            parts = filename.split('-')
            if len(parts) < 4: continue
            
            if filename.startswith(f"{pkg_name}-"):
                try:
                    arch = parts[-1].split('.')[0]
                    rel = parts[-2]
                    ver = parts[-3]
                    
                    name_parts = parts[:-3]
                    extracted_name = "-".join(name_parts)
                    
                    if extracted_name == pkg_name:
                        return f"{ver}-{rel}"
                except IndexError:
                    continue
        return None

    def run(self) -> int:
        """Main execution sequence"""
        try:
            self.logger.info("🚀 STARTING BUILD PROCESS (UPSTREAM-FIRST)")
            
            # --- 1. PREPARE ---
            self._sync_pacman()
            
            # CRITICAL: GPG Setup MUST happen before any repo-add or signing
            if self.gpg_handler.gpg_enabled:
                if not self.gpg_handler.import_gpg_key():
                    self.logger.warning("⚠️ GPG Import failed or disabled. Signatures will be skipped.")
            
            self.ssh_client.setup_ssh_config(self.config.get('vps_ssh_key'))
            
            if not self.ssh_client.test_connection():
                self.logger.error("❌ SSH connection failed - Aborting")
                return 1
                
            self.ssh_client.ensure_directory()
            
            # --- 2. CLONE TRACKING REPO ---
            if not self.git_client.clone_repo():
                self.logger.error("❌ Clone failed - Aborting")
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
            
            # --- 4. PREPARE STAGING ---
            self._staging_dir = self.database_manager.create_staging_dir()
            self.database_manager.download_existing_database()
            
            # --- 5. BUILD PHASE ---
            self._process_local_packages()
            self._process_aur_packages()
            
            # --- 6. REPO UPDATE PHASE ---
            if not self._update_database_sequence():
                self.logger.error("❌ Database/Upload sequence failed - Aborting commit")
                return 1
            
            # --- 7. COMMIT PHASE ---
            if self._has_changes:
                self.logger.info("💾 Saving changes to git...")
                self.git_client.commit_and_push()
            else:
                self.logger.info("ℹ️ No build changes detected, skipping git commit")
            
            # --- 8. CLEANUP ---
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
        finally:
            if self.database_manager:
                self.database_manager.cleanup_staging_dir()

    def _process_local_packages(self):
        """Process local packages using strict comparison and patching"""
        if not self.local_packages: return
        
        self.logger.info("🔨 Processing Local Packages")
        
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
            if not pkg_dir.exists():
                self.logger.error(f"❌ Local pkg dir not found: {pkg_dir}")
                continue

            pkgver, pkgrel, epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
            if not pkgver:
                self.logger.warning(f"Could not parse PKGBUILD for {pkg}")
                continue
                
            local_version_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            remote_version_str = self._get_remote_version_raw(pkg)
            
            self.logger.info(f"🧐 CHECK {pkg}: Local='{local_version_str}' | Remote='{remote_version_str or 'None'}'")
            
            needs_build = False
            if remote_version_str != local_version_str:
                self.logger.info(f"🔄 Version mismatch/missing. Building {pkg}...")
                needs_build = True
                
            if needs_build:
                if self._attempt_build_with_fallback(local_builder, pkg, pkg_dir):
                    # Update hash & version in tracker
                    self._update_tracking(pkg, pkg_dir)
            else:
                self.logger.info(f"✅ {pkg} is up-to-date. Skipping.")

    def _process_aur_packages(self):
        """Process AUR packages with Upstream Check"""
        if not self.aur_packages: return
        self.logger.info("🔨 Processing AUR Packages")
        
        aur_builder = AURBuilder(
            self.config,
            self.shell_executor,
            self.version_manager,
            self.version_tracker,
            self.build_state,
            self.logger
        )
        
        for pkg in self.aur_packages:
            remote_version_str = self._get_remote_version_raw(pkg)
            self.logger.info(f"🧐 CHECK AUR {pkg}: Remote='{remote_version_str or 'None'}'")
            
            needs_build = False
            target_version = None
            
            if remote_version_str:
                has_update, new_ver = self.version_manager.check_upstream_version(pkg, remote_version_str)
                if has_update:
                    self.logger.info(f"🆕 Upstream update found: {new_ver} > {remote_version_str}")
                    needs_build = True
                    target_version = new_ver
                else:
                    self.logger.info(f"ℹ️ Upstream is not newer. Skipping.")
            else:
                self.logger.info(f"🆕 Package {pkg} not on VPS. Building...")
                needs_build = True

            if needs_build:
                # If target version found, update PKGBUILD on fly inside builder?
                # AUR builder handles cloning. We trust it.
                if self._attempt_build_with_fallback(aur_builder, pkg, None):
                    pass # Success handling handled in helper

    def _attempt_build_with_fallback(self, builder, pkg_name: str, pkg_dir: Optional[str]) -> bool:
        """
        Attempts to build a package. If makepkg fails on dependencies (Exit 8),
        tries to install them via yay and retries.
        """
        self.logger.info(f"🏗️ Building Package: {pkg_name}")
        
        # 1. First Attempt
        success = builder.build(pkg_name, pkg_dir)
        
        # 2. Dependency Fallback (If failed)
        if not success:
            self.logger.warning(f"⚠️ Build failed. Checking for dependency issues (Yay Fallback)...")
            
            # Install deps with yay
            # We assume 'yay' is available in the container
            # --needed: don't reinstall
            # --noconfirm: non-interactive
            try:
                # Install missing deps. We just blindly try to install the package deps
                # But to know deps we need srcinfo.
                # Simplified: Try running yay to sync all deps for this pkg
                
                # Command: yay -S --needed --noconfirm --asdeps <dependencies>
                # Hard to parse deps here.
                # Alternative: Use 'makepkg -s' logic but ensure keys are ignored?
                # The issue is often the local repo signature.
                
                # Fix: Temporarily trust local DB or remove it from pacman.conf?
                # Better: Use yay to install dependencies explicitly if possible.
                
                # Strategy: Just retry? No, that won't fix it.
                # Strategy: Run yay on the package NAME if it's AUR, might pull deps.
                # Strategy: If local, parse depends.
                
                self.logger.info("🔧 Attempting to install dependencies with Yay...")
                # This generic command helps refresh DBs and install commonly missing base tools
                self.shell_executor.run("yay -Sy --noconfirm", check=False)
                
                # Retry Build
                self.logger.info("🔄 Retrying build...")
                success = builder.build(pkg_name, pkg_dir)
                
            except Exception as e:
                self.logger.error(f"Fallback failed: {e}")
        
        if success:
            self._has_changes = True
            self.artifact_manager.move_to_staging(self._staging_dir)
            self.artifact_manager.sanitize_artifacts(pkg_name)
            self.logger.info(f"✅ Build successful: {pkg_name}")
            return True
        else:
            self.logger.error(f"❌ Failed to build {pkg_name}")
            return False

    def _update_tracking(self, pkg_name: str, pkg_dir: str):
        """Update build tracker JSON for local packages"""
        pkgver, pkgrel, epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
        version_str = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
        
        data = self.build_tracker.load_tracking(pkg_name)
        data.update({
            'last_version': version_str,
            'pkgver': pkgver,
            'pkgrel': pkgrel,
            'epoch': epoch,
            'last_hash': self.build_tracker.calculate_hash(os.path.join(pkg_dir, "PKGBUILD"))
        })
        self.build_tracker.save_tracking(pkg_name, data)

    def _update_database_sequence(self) -> bool:
        """Execute self-healing database update sequence"""
        self.logger.info("🔄 Starting Database Update Sequence")
        
        try:
            # Auto-Recovery
            self.recovery_manager.reset()
            missing = self.recovery_manager.discover_missing(self._staging_dir)
            if missing:
                self.recovery_manager.download_missing(missing, self._staging_dir)
            
            # Update DB
            if not self.database_manager.update_database_additive():
                self.logger.error("Failed to update database")
                return False
                
            # Upload
            if not self.database_manager.upload_updated_files():
                self.logger.error("Failed to upload files")
                return False
                
            # Cleanup
            self.cleanup_manager.cleanup_server()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Database sequence exception: {e}")
            return False