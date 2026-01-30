"""
Package builder orchestrator - main coordination logic
"""

import os
import sys
import time
import logging
from pathlib import Path

# Add parent directories to path
script_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(script_dir))

# Import from our modules
from modules.common.config_loader import load_config
from modules.common.environment import get_repo_root
from modules.common.shell_executor import ShellExecutor
from modules.common.logging_utils import DebugLogger

from modules.build.artifact_manager import ArtifactManager
from modules.build.aur_builder import AurBuilder
from modules.build.local_builder import LocalBuilder
from modules.build.version_manager import VersionManager
from modules.build.build_tracker import BuildTracker

from modules.gpg.gpg_handler import GPGHandler

logger = logging.getLogger(__name__)


class PackageBuilder:
    """Main orchestrator that coordinates between modules"""
    
    def __init__(self):
        # Load configuration
        self.config = load_config()
        
        # Setup debug logger
        self.debug_logger = DebugLogger(self.config.get('debug_mode', False))
        
        # Get repository root
        self.repo_root = get_repo_root()
        
        # Setup directories from config
        self.output_dir = Path(self.repo_root) / self.config['output_dir']
        self.build_tracking_dir = Path(self.repo_root) / self.config['build_tracking_dir']
        
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # Initialize modules
        self._init_modules()
        
        # State
        self.built_packages = []
        self.skipped_packages = []
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
        }
    
    def _init_modules(self):
        """Initialize all modules"""
        try:
            # Common modules
            self.shell_executor = ShellExecutor(self.config.get('debug_mode', False))
            self.artifact_manager = ArtifactManager(self.output_dir, self.config.get('debug_mode', False))
            
            # Build modules
            self.version_manager = VersionManager(self.config.get('debug_mode', False))
            self.build_tracker = BuildTracker(self.build_tracking_dir)
            self.aur_builder = AurBuilder(self.config, self.shell_executor, self.artifact_manager)
            self.local_builder = LocalBuilder(self.config, self.shell_executor, self.artifact_manager)
            
            # GPG module
            self.gpg_handler = GPGHandler(self.config)
            
            self.debug_logger.log("✅ All modules initialized successfully")
            
        except Exception as e:
            self.debug_logger.error(f"❌ Error initializing modules: {e}")
            sys.exit(1)
    
    def get_package_lists(self):
        """Get package lists from packages.py"""
        try:
            # Add parent directory to path
            import sys
            script_dir = Path(__file__).parent.parent.parent
            sys.path.insert(0, str(script_dir))
            
            import packages
            local_packages_list = packages.LOCAL_PACKAGES
            aur_packages_list = packages.AUR_PACKAGES
            
            self.debug_logger.log(f"📦 Found {len(local_packages_list + aur_packages_list)} packages to check")
            return local_packages_list, aur_packages_list
        except ImportError:
            self.debug_logger.error("Cannot load package lists from packages.py. Exiting.")
            sys.exit(1)
    
    def build_packages(self):
        """Build all packages"""
        self.debug_logger.log("Building packages")
        
        local_packages, aur_packages = self.get_package_lists()
        
        self.debug_logger.log(f"📦 Package statistics:")
        self.debug_logger.log(f"   Local packages: {len(local_packages)}")
        self.debug_logger.log(f"   AUR packages: {len(aur_packages)}")
        self.debug_logger.log(f"   Total packages: {len(local_packages) + len(aur_packages)}")
        
        # Build AUR packages
        self.debug_logger.log(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if self.aur_builder.build(pkg):
                self.stats["aur_success"] += 1
                self.built_packages.append(pkg)
            else:
                self.stats["aur_failed"] += 1
        
        # Build local packages
        self.debug_logger.log(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self.local_builder.build(pkg, self.repo_root):
                self.stats["local_success"] += 1
                self.built_packages.append(pkg)
            else:
                self.stats["local_failed"] += 1
        
        return self.stats["aur_success"] + self.stats["local_success"]
    
    def generate_database(self):
        """Generate repository database"""
        if self.debug_mode:
            print(f"🔧 [DEBUG] Generating database", flush=True)
        else:
            logger.info("Generating database")
        
        # Implementation would go here
        # For now, just return True
        return True
    
    def upload_packages(self):
        """Upload packages to VPS"""
        if self.debug_mode:
            print(f"🔧 [DEBUG] Uploading packages", flush=True)
        else:
            logger.info("Uploading packages")
        
        # Implementation would go here
        # For now, just return True
        return True
    
    def run(self):
        """Main execution"""
        self.debug_logger.log("🚀 MANJARO PACKAGE BUILDER (MODULAR ARCHITECTURE)")
        
        try:
            self.debug_logger.log("\n🔧 Initial setup...")
            self.debug_logger.log(f"Repository root: {self.repo_root}")
            self.debug_logger.log(f"Repository name: {self.config['repo_name']}")
            self.debug_logger.log(f"Output directory: {self.output_dir}")
            self.debug_logger.log(f"PACKAGER identity: {self.config['packager_id']}")
            
            # Initialize GPG
            self.debug_logger.log("\nSTEP 0: GPG INITIALIZATION")
            if self.gpg_handler.gpg_enabled:
                if not self.gpg_handler.import_gpg_key():
                    self.debug_logger.error("❌ Failed to import GPG key, disabling signing")
                else:
                    self.debug_logger.log("✅ GPG initialized successfully")
            else:
                self.debug_logger.log("ℹ️ GPG signing disabled (no key provided)")
            
            # Build packages
            self.debug_logger.log("\nSTEP 1: PACKAGE BUILDING")
            total_built = self.build_packages()
            
            # Generate database if packages were built
            if total_built > 0:
                self.debug_logger.log("\nSTEP 2: DATABASE GENERATION")
                
                # Generate database
                if self.generate_database():
                    # Sign repository if GPG is enabled
                    if self.gpg_handler.gpg_enabled:
                        self.gpg_handler.sign_repository_files(self.config['repo_name'], str(self.output_dir))
                    
                    # Upload packages
                    self.debug_logger.log("\nSTEP 3: UPLOAD PACKAGES")
                    if self.upload_packages():
                        self.debug_logger.log("✅ Upload successful")
                    else:
                        self.debug_logger.log("❌ Upload failed")
                
                # Clean up GPG
                self.gpg_handler.cleanup()
            
            # Print summary
            elapsed = time.time() - self.stats["start_time"]
            
            self.debug_logger.log("\n📊 BUILD SUMMARY")
            self.debug_logger.log(f"Duration: {elapsed:.1f}s")
            self.debug_logger.log(f"AUR packages:    {self.stats['aur_success']} (failed: {self.stats['aur_failed']})")
            self.debug_logger.log(f"Local packages:  {self.stats['local_success']} (failed: {self.stats['local_failed']})")
            self.debug_logger.log(f"Total built:     {total_built}")
            self.debug_logger.log(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            
            if self.built_packages:
                self.debug_logger.log("\n📦 Built packages:")
                for pkg in self.built_packages:
                    self.debug_logger.log(f"  - {pkg}")
            
            return 0
            
        except Exception as e:
            self.debug_logger.error(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            
            # Ensure GPG cleanup even on failure
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            
            return 1