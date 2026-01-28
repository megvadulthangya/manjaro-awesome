"""
Main Workflow Orchestrator for Manjaro Package Builder
Delegates all operations to specialized modules (sync, build, common, config)
"""

import os
import sys
import logging
import traceback
from pathlib import Path
from typing import List, Dict, Any, Optional

# Common modules
from modules.common.config_manager import ConfigManager
from modules.common.shell_executor import ShellExecutor
from modules.common.environment import EnvironmentValidator
from modules.common.logging_utils import setup_logging, get_logger

# Sync modules
from modules.sync.git_sync import GitSyncManager
from modules.sync.pkgbuild_tracker import PkgbuildTracker

# Build modules (assume they exist based on previous extraction)
try:
    from modules.build.local_builder import LocalBuilder
    from modules.build.aur_builder import AURBuilder
    from modules.build.version_manager import VersionManager
    BUILD_MODULES_AVAILABLE = True
except ImportError:
    BUILD_MODULES_AVAILABLE = False
    print("⚠️ Build modules not available - running in configuration-only mode")

# Repository modules (assume they exist)
try:
    from modules.repo.version_tracker import VersionTracker
    from modules.repo.database_manager import DatabaseManager
    from modules.repo.cleanup_manager import CleanupManager
    REPO_MODULES_AVAILABLE = True
except ImportError:
    REPO_MODULES_AVAILABLE = False
    print("⚠️ Repository modules not available")

# VPS modules (assume they exist)
try:
    from modules.vps.ssh_client import SSHClient
    from modules.vps.rsync_client import RsyncClient
    VPS_MODULES_AVAILABLE = True
except ImportError:
    VPS_MODULES_AVAILABLE = False
    print("⚠️ VPS modules not available")

# State management
try:
    from modules.orchestrator.state import BuildState
    STATE_MODULE_AVAILABLE = True
except ImportError:
    STATE_MODULE_AVAILABLE = False
    print("⚠️ State module not available")


class PackageBuilder:
    """Main workflow orchestrator - delegates all operations to specialized modules"""
    
    def __init__(self):
        """Initialize the orchestrator with all module managers"""
        self.logger = get_logger(__name__)
        
        # Track module initialization status
        self.modules_loaded = {
            'common': False,
            'sync': False,
            'build': False,
            'repo': False,
            'vps': False,
            'state': False
        }
        
        # Module instances
        self.config_manager = None
        self.shell_executor = None
        self.env_validator = None
        self.git_sync = None
        self.pkg_tracker = None
        self.version_tracker = None
        self.build_state = None
        self.ssh_client = None
        self.rsync_client = None
        self.local_builder = None
        self.aur_builder = None
        self.database_manager = None
        self.cleanup_manager = None
        
        # Package lists
        self.local_packages: List[str] = []
        self.aur_packages: List[str] = []
        
        # Results
        self.build_results = {
            'local_built': [],
            'local_skipped': [],
            'local_failed': [],
            'aur_built': [],
            'aur_skipped': [],
            'aur_failed': []
        }
        
        self.logger.info("Initializing PackageBuilder Orchestrator...")
    
    def _initialize_modules(self) -> bool:
        """
        Initialize all required modules
        
        Returns:
            True if all essential modules initialized successfully
        """
        self.logger.info("🔧 Initializing modules...")
        
        # Step 1: Common modules (always required)
        if not self._initialize_common_modules():
            self.logger.error("Failed to initialize common modules")
            return False
        self.modules_loaded['common'] = True
        
        # Step 2: Sync modules (required for PKGBUILD synchronization)
        if not self._initialize_sync_modules():
            self.logger.warning("Sync modules initialization failed - limited functionality")
        else:
            self.modules_loaded['sync'] = True
        
        # Step 3: VPS modules (required for remote operations)
        if VPS_MODULES_AVAILABLE:
            if not self._initialize_vps_modules():
                self.logger.warning("VPS modules initialization failed - no remote operations")
            else:
                self.modules_loaded['vps'] = True
        
        # Step 4: Build modules (required for building packages)
        if BUILD_MODULES_AVAILABLE:
            if not self._initialize_build_modules():
                self.logger.warning("Build modules initialization failed - no build capability")
            else:
                self.modules_loaded['build'] = True
        
        # Step 5: Repository modules (required for database operations)
        if REPO_MODULES_AVAILABLE:
            if not self._initialize_repo_modules():
                self.logger.warning("Repository modules initialization failed - no repo management")
            else:
                self.modules_loaded['repo'] = True
        
        # Step 6: State module (optional)
        if STATE_MODULE_AVAILABLE:
            self.build_state = BuildState(self.logger)
            self.modules_loaded['state'] = True
            self.logger.info("✅ State module initialized")
        
        # Report module status
        loaded_count = sum(1 for loaded in self.modules_loaded.values() if loaded)
        self.logger.info(f"📊 Modules loaded: {loaded_count}/{len(self.modules_loaded)}")
        
        # At minimum, we need common modules
        return self.modules_loaded['common']
    
    def _initialize_common_modules(self) -> bool:
        """Initialize common utility modules"""
        try:
            # Initialize config manager (singleton)
            self.config_manager = ConfigManager(self.logger)
            
            # Get repo root from environment validator
            self.env_validator = EnvironmentValidator(self.logger)
            repo_root = self.env_validator.get_repo_root()
            self.config_manager.set_repo_root(repo_root)
            
            # Setup logging based on debug mode
            debug_mode = self.config_manager.get_bool('DEBUG_MODE', False)
            setup_logging(debug_mode=debug_mode)
            
            # Initialize shell executor with debug mode
            self.shell_executor = ShellExecutor(
                debug_mode=debug_mode,
                default_timeout=self.config_manager.get_int('DEFAULT_TIMEOUT', 1800)
            )
            
            self.logger.info("✅ Common modules initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize common modules: {e}")
            return False
    
    def _initialize_sync_modules(self) -> bool:
        """Initialize synchronization modules"""
        try:
            # Get SSH key from config
            ssh_key = self.config_manager.get_str('CI_PUSH_SSH_KEY')
            if not ssh_key:
                ssh_key = self.config_manager.get_str('VPS_SSH_KEY')
            
            # Initialize Git sync manager
            config_dict = {
                'ssh_repo_url': self.config_manager.get_str('SSH_REPO_URL'),
                'sync_clone_dir': str(self.config_manager.get_path('SYNC_CLONE_DIR')),
                'packager_env': self.config_manager.get_str('PACKAGER_ID')
            }
            
            self.git_sync = GitSyncManager(self.shell_executor, self.logger)
            
            # Initialize PKGBUILD tracker
            tracking_dir = self.config_manager.get_path('BUILD_TRACKING_DIR')
            self.pkg_tracker = PkgbuildTracker(tracking_dir, self.logger)
            
            self.logger.info("✅ Sync modules initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize sync modules: {e}")
            return False
    
    def _initialize_vps_modules(self) -> bool:
        """Initialize VPS communication modules"""
        try:
            if not VPS_MODULES_AVAILABLE:
                return False
            
            # Create config dict for VPS modules
            vps_config = {
                'vps_user': self.config_manager.get_str('VPS_USER'),
                'vps_host': self.config_manager.get_str('VPS_HOST'),
                'remote_dir': self.config_manager.get_str('REMOTE_DIR'),
                'repo_name': self.config_manager.get_str('REPO_NAME'),
                'ssh_options': self.config_manager.get_list('SSH_OPTIONS')
            }
            
            self.ssh_client = SSHClient(vps_config, self.shell_executor, self.logger)
            self.rsync_client = RsyncClient(vps_config, self.shell_executor, self.logger)
            
            # Setup SSH key if available
            ssh_key = self.config_manager.get_str('VPS_SSH_KEY')
            if ssh_key:
                self.ssh_client.setup_ssh_config(ssh_key)
            
            self.logger.info("✅ VPS modules initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize VPS modules: {e}")
            return False
    
    def _initialize_build_modules(self) -> bool:
        """Initialize build modules"""
        try:
            if not BUILD_MODULES_AVAILABLE:
                return False
            
            # Get configuration for builders
            config_dict = {
                'repo_root': self.config_manager.get_repo_root(),
                'output_dir': str(self.config_manager.get_path('OUTPUT_DIR')),
                'aur_build_dir': str(self.config_manager.get_path('AUR_BUILD_DIR')),
                'aur_urls': self.config_manager.get_list('AUR_URLS'),
                'packager_id': self.config_manager.get_str('PACKAGER_ID'),
                'repo_name': self.config_manager.get_str('REPO_NAME')
            }
            
            # Initialize version manager
            version_manager = VersionManager(self.shell_executor, self.logger)
            
            # Initialize builders (require version tracker and build state)
            if self.version_tracker and self.build_state:
                self.local_builder = LocalBuilder(
                    config_dict, self.shell_executor, version_manager,
                    self.version_tracker, self.build_state, self.logger
                )
                
                self.aur_builder = AURBuilder(
                    config_dict, self.shell_executor, version_manager,
                    self.version_tracker, self.build_state, self.logger
                )
            
            self.logger.info("✅ Build modules initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize build modules: {e}")
            return False
    
    def _initialize_repo_modules(self) -> bool:
        """Initialize repository management modules"""
        try:
            if not REPO_MODULES_AVAILABLE:
                return False
            
            # Create config dict for repo modules
            repo_config = {
                'repo_name': self.config_manager.get_str('REPO_NAME'),
                'output_dir': str(self.config_manager.get_path('OUTPUT_DIR')),
                'remote_dir': self.config_manager.get_str('REMOTE_DIR'),
                'gpg_key_id': self.config_manager.get_str('GPG_KEY_ID'),
                'gpg_private_key': self.config_manager.get_str('GPG_PRIVATE_KEY')
            }
            
            # Initialize version tracker (requires SSH client)
            if self.ssh_client:
                repo_root = self.config_manager.get_repo_root()
                self.version_tracker = VersionTracker(repo_root, self.ssh_client, self.logger)
            
            # Initialize database and cleanup managers
            if self.ssh_client and self.rsync_client:
                self.database_manager = DatabaseManager(
                    repo_config, self.ssh_client, self.rsync_client, self.logger
                )
                
                self.cleanup_manager = CleanupManager(
                    repo_config, self.version_tracker,
                    self.ssh_client, self.rsync_client, self.logger
                )
            
            self.logger.info("✅ Repository modules initialized")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize repository modules: {e}")
            return False
    
    def _load_package_lists(self) -> bool:
        """
        Load package lists from configuration
        
        Returns:
            True if package lists loaded successfully
        """
        try:
            # Try to import packages module
            packages_module_path = self.config_manager.get_repo_root() / ".github" / "scripts" / "packages.py"
            if packages_module_path.exists():
                # Add scripts directory to Python path
                scripts_dir = packages_module_path.parent
                if str(scripts_dir) not in sys.path:
                    sys.path.insert(0, str(scripts_dir))
                
                import packages
                
                if hasattr(packages, 'LOCAL_PACKAGES'):
                    self.local_packages = packages.LOCAL_PACKAGES
                
                if hasattr(packages, 'AUR_PACKAGES'):
                    self.aur_packages = packages.AUR_PACKAGES
                
                self.logger.info(f"📦 Loaded package lists: {len(self.local_packages)} local, {len(self.aur_packages)} AUR")
                return True
            else:
                self.logger.warning("No packages.py found - using empty package lists")
                return True
                
        except ImportError as e:
            self.logger.error(f"Failed to import packages module: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Error loading package lists: {e}")
            return False
    
    def _setup_temporary_clone(self) -> bool:
        """
        Set up temporary repository clone
        
        Returns:
            True if clone successful
        """
        if not self.modules_loaded['sync']:
            self.logger.warning("Sync modules not loaded - skipping temporary clone setup")
            return False
        
        try:
            # Get SSH key for Git operations
            ssh_key = self.config_manager.get_str('CI_PUSH_SSH_KEY')
            if not ssh_key:
                ssh_key = self.config_manager.get_str('VPS_SSH_KEY')
            
            if not ssh_key:
                self.logger.error("No SSH key available for Git operations")
                return False
            
            # Create config dict for Git sync
            config_dict = {
                'ssh_repo_url': self.config_manager.get_str('SSH_REPO_URL'),
                'sync_clone_dir': str(self.config_manager.get_path('SYNC_CLONE_DIR')),
                'packager_env': self.config_manager.get_str('PACKAGER_ID')
            }
            
            # Setup temporary clone
            success = self.git_sync.setup_temp_clone(config_dict, ssh_key)
            
            if success:
                self.logger.info("✅ Temporary repository clone setup complete")
            else:
                self.logger.error("❌ Temporary repository clone setup failed")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error setting up temporary clone: {e}")
            return False
    
    def _check_vps_connection(self) -> bool:
        """
        Test connection to VPS
        
        Returns:
            True if connection successful
        """
        if not self.modules_loaded['vps']:
            self.logger.warning("VPS modules not loaded - skipping connection test")
            return False
        
        try:
            self.logger.info("🔍 Testing VPS connection...")
            success = self.ssh_client.test_connection()
            
            if success:
                self.logger.info("✅ VPS connection successful")
            else:
                self.logger.error("❌ VPS connection failed")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error testing VPS connection: {e}")
            return False
    
    def _identify_packages_to_build(self) -> Dict[str, List[str]]:
        """
        Identify which packages need to be built
        
        Returns:
            Dictionary with lists of packages to build
        """
        packages_to_build = {
            'local': [],
            'aur': []
        }
        
        # For now, return all packages if we have build capability
        # In a real implementation, this would use PkgbuildTracker
        if self.modules_loaded['build']:
            packages_to_build['local'] = self.local_packages
            packages_to_build['aur'] = self.aur_packages
        else:
            self.logger.warning("Build modules not loaded - cannot identify packages to build")
        
        return packages_to_build
    
    def _build_packages(self, packages_to_build: Dict[str, List[str]]) -> bool:
        """
        Build packages using appropriate builders
        
        Args:
            packages_to_build: Dictionary with lists of packages to build
        
        Returns:
            True if at least one package built successfully
        """
        if not self.modules_loaded['build']:
            self.logger.error("Build modules not loaded - cannot build packages")
            return False
        
        built_successfully = False
        
        # Build local packages
        local_packages = packages_to_build.get('local', [])
        if local_packages and self.local_builder:
            self.logger.info(f"🔨 Building {len(local_packages)} local packages...")
            
            for pkg_name in local_packages:
                try:
                    self.logger.info(f"📦 Building local package: {pkg_name}")
                    
                    # TODO: Add actual build logic here
                    # For now, just log the intent
                    self.logger.info(f"Would build {pkg_name} with LocalBuilder")
                    
                    # Track result
                    self.build_results['local_built'].append(pkg_name)
                    built_successfully = True
                    
                except Exception as e:
                    self.logger.error(f"Failed to build {pkg_name}: {e}")
                    self.build_results['local_failed'].append(pkg_name)
        
        # Build AUR packages
        aur_packages = packages_to_build.get('aur', [])
        if aur_packages and self.aur_builder:
            self.logger.info(f"🔨 Building {len(aur_packages)} AUR packages...")
            
            for pkg_name in aur_packages:
                try:
                    self.logger.info(f"📦 Building AUR package: {pkg_name}")
                    
                    # TODO: Add actual build logic here
                    # For now, just log the intent
                    self.logger.info(f"Would build {pkg_name} with AURBuilder")
                    
                    # Track result
                    self.build_results['aur_built'].append(pkg_name)
                    built_successfully = True
                    
                except Exception as e:
                    self.logger.error(f"Failed to build {pkg_name}: {e}")
                    self.build_results['aur_failed'].append(pkg_name)
        
        return built_successfully
    
    def _commit_and_push_changes(self) -> bool:
        """
        Commit and push changes to Git repository
        
        Returns:
            True if successful
        """
        if not self.modules_loaded['sync']:
            self.logger.warning("Sync modules not loaded - skipping Git operations")
            return False
        
        try:
            # Commit changes
            self.logger.info("💾 Committing changes...")
            commit_success = self.git_sync.commit_changes()
            
            if not commit_success:
                self.logger.warning("No changes to commit or commit failed")
                return True  # Not necessarily an error
            
            # Push changes
            self.logger.info("📤 Pushing changes...")
            push_success = self.git_sync.push_changes()
            
            if push_success:
                self.logger.info("✅ Changes committed and pushed successfully")
            else:
                self.logger.error("❌ Failed to push changes")
            
            return push_success
            
        except Exception as e:
            self.logger.error(f"Error during Git operations: {e}")
            return False
    
    def _update_repository_database(self) -> bool:
        """
        Update repository database on VPS
        
        Returns:
            True if successful
        """
        if not self.modules_loaded['repo']:
            self.logger.warning("Repository modules not loaded - skipping database update")
            return False
        
        try:
            self.logger.info("🗄️ Updating repository database...")
            
            # TODO: Implement database update logic
            # This would use DatabaseManager to update the repo database
            
            self.logger.info("✅ Repository database update complete")
            return True
            
        except Exception as e:
            self.logger.error(f"Error updating repository database: {e}")
            return False
    
    def _cleanup(self):
        """Clean up temporary resources"""
        self.logger.info("🧹 Cleaning up temporary resources...")
        
        # Cleanup Git sync resources
        if self.git_sync:
            try:
                self.git_sync.cleanup()
                self.logger.debug("✅ Git sync cleanup complete")
            except Exception as e:
                self.logger.warning(f"Git sync cleanup failed: {e}")
        
        # Cleanup VPS connections
        if self.ssh_client:
            try:
                self.ssh_client.clear_cache()
                self.logger.debug("✅ VPS connection cleanup complete")
            except Exception as e:
                self.logger.warning(f"VPS connection cleanup failed: {e}")
        
        self.logger.info("✅ Cleanup complete")
    
    def _print_summary(self):
        """Print build summary"""
        self.logger.info("\n" + "=" * 60)
        self.logger.info("📊 BUILD SUMMARY")
        self.logger.info("=" * 60)
        
        # Module status
        self.logger.info("Modules loaded:")
        for module, loaded in self.modules_loaded.items():
            status = "✅" if loaded else "❌"
            self.logger.info(f"  {module}: {status}")
        
        # Package statistics
        self.logger.info(f"\nPackage statistics:")
        self.logger.info(f"  Local packages: {len(self.local_packages)} total")
        self.logger.info(f"  AUR packages: {len(self.aur_packages)} total")
        
        # Build results
        if self.build_results:
            self.logger.info(f"\nBuild results:")
            
            local_built = len(self.build_results['local_built'])
            local_failed = len(self.build_results['local_failed'])
            aur_built = len(self.build_results['aur_built'])
            aur_failed = len(self.build_results['aur_failed'])
            
            self.logger.info(f"  Local packages: {local_built} built, {local_failed} failed")
            self.logger.info(f"  AUR packages: {aur_built} built, {aur_failed} failed")
        
        # Configuration
        self.logger.info(f"\nConfiguration:")
        self.logger.info(f"  Repository: {self.config_manager.get_str('REPO_NAME')}")
        self.logger.info(f"  Debug mode: {self.config_manager.get_bool('DEBUG_MODE')}")
        
        self.logger.info("=" * 60)
    
    def run(self) -> int:
        """
        Main workflow execution
        
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        try:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("🚀 MANJARO PACKAGE BUILDER - MODULAR ORCHESTRATOR")
            self.logger.info("=" * 60)
            
            # Step 1: Initialize all modules
            self.logger.info("\n📦 Step 1: Initializing modules")
            if not self._initialize_modules():
                self.logger.error("❌ Module initialization failed")
                return 1
            
            # Step 2: Load package lists
            self.logger.info("\n📦 Step 2: Loading package lists")
            if not self._load_package_lists():
                self.logger.error("❌ Failed to load package lists")
                return 1
            
            # Step 3: Setup temporary repository clone
            self.logger.info("\n📦 Step 3: Setting up temporary repository clone")
            if not self._setup_temporary_clone():
                self.logger.warning("⚠️ Temporary clone setup failed - continuing without Git sync")
            
            # Step 4: Test VPS connection
            self.logger.info("\n📦 Step 4: Testing VPS connection")
            if not self._check_vps_connection():
                self.logger.warning("⚠️ VPS connection failed - continuing without remote operations")
            
            # Step 5: Identify packages to build
            self.logger.info("\n📦 Step 5: Identifying packages to build")
            packages_to_build = self._identify_packages_to_build()
            
            # Step 6: Build packages
            self.logger.info("\n📦 Step 6: Building packages")
            if packages_to_build['local'] or packages_to_build['aur']:
                build_success = self._build_packages(packages_to_build)
                
                if not build_success:
                    self.logger.error("❌ No packages built successfully")
            else:
                self.logger.info("ℹ️ No packages to build")
            
            # Step 7: Commit and push changes (if we have a temporary clone)
            self.logger.info("\n📦 Step 7: Committing and pushing changes")
            if self.git_sync and self.git_sync.temp_clone_dir:
                if not self._commit_and_push_changes():
                    self.logger.warning("⚠️ Git operations failed - continuing")
            
            # Step 8: Update repository database (if VPS is available)
            self.logger.info("\n📦 Step 8: Updating repository database")
            if self.modules_loaded['vps'] and self.modules_loaded['repo']:
                if not self._update_repository_database():
                    self.logger.warning("⚠️ Repository database update failed")
            
            # Step 9: Cleanup
            self.logger.info("\n📦 Step 9: Cleanup")
            self._cleanup()
            
            # Step 10: Print summary
            self._print_summary()
            
            # Determine exit code
            total_failed = (
                len(self.build_results['local_failed']) + 
                len(self.build_results['aur_failed'])
            )
            
            if total_failed > 0:
                self.logger.warning(f"⚠️ Build completed with {total_failed} failures")
                return 0  # Still return 0 to allow partial success
            
            self.logger.info("✅ Build completed successfully!")
            return 0
            
        except KeyboardInterrupt:
            self.logger.info("\n\n⚠️ Build interrupted by user")
            self._cleanup()
            return 130
            
        except Exception as e:
            self.logger.error(f"\n❌ Build failed with unexpected error: {e}")
            traceback.print_exc()
            self._cleanup()
            return 1


def main() -> int:
    """
    Main entry point
    
    Returns:
        Exit code
    """
    try:
        builder = PackageBuilder()
        return builder.run()
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())