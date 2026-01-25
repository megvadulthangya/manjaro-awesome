#!/usr/bin/env python3
"""
Main Builder Orchestrator - Coordinates VPSClient and RepoManager with strict paths
STRICT PATH COMPLIANCE: Follows all directory specifications
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

# ============================================================================
# ROBUST PATH INJECTION: Boilerplate-free module discovery
# ============================================================================

# Get the absolute path of the current script
SCRIPT_DIR = Path(__file__).resolve().parent
# Add script directory to sys.path for imports
sys.path.insert(0, str(SCRIPT_DIR))

# ENVIRONMENT VALIDATION: Check required module files exist
REQUIRED_MODULES = ['vps_client.py', 'repo_manager.py']
missing_modules = []

for module_file in REQUIRED_MODULES:
    module_path = SCRIPT_DIR / module_file
    if not module_path.exists():
        missing_modules.append(module_file)

if missing_modules:
    print(f"❌ CRITICAL: Missing module files: {', '.join(missing_modules)}")
    print(f"Expected in: {SCRIPT_DIR}")
    sys.exit(1)

# EXPLICIT IMPORTS: Import modules now that path is set
try:
    from vps_client import VPSClient
    from repo_manager import RepoManager
    MODULES_LOADED = True
except ImportError as e:
    print(f"❌ CRITICAL: Failed to import modules: {e}")
    print(f"sys.path: {sys.path}")
    MODULES_LOADED = False
    sys.exit(1)

# Try to import config
try:
    import config
    HAS_CONFIG = True
except ImportError:
    print("⚠️ Warning: config.py not found, using environment variables")
    HAS_CONFIG = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('builder.log')
    ]
)
logger = logging.getLogger(__name__)


class PackageBuilder:
    """Main orchestrator that coordinates between VPSClient and RepoManager"""
    
    def __init__(self):
        # Validate environment
        self._validate_env()
        
        # Load configuration
        self._load_config()
        
        # Initialize modules
        self._init_modules()
        
        # State
        self.vps_state = {}
        self.packages_to_update = []
    
    def _validate_env(self):
        """Validate required environment variables"""
        required_vars = [
            'VPS_USER',
            'VPS_HOST',
            'VPS_SSH_KEY',
            'REMOTE_DIR',
            'REPO_NAME'
        ]
        
        missing_vars = []
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)
        
        if missing_vars:
            logger.error(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
            sys.exit(1)
        
        logger.info("✅ Environment validation passed")
    
    def _load_config(self):
        """Load configuration from environment and config files"""
        # Environment variables (required)
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        self.remote_dir = os.getenv('REMOTE_DIR')
        self.repo_name = os.getenv('REPO_NAME')
        
        # SSH repo URL from config or env
        if HAS_CONFIG and hasattr(config, 'SSH_REPO_URL'):
            self.ssh_repo_url = config.SSH_REPO_URL
        else:
            # Construct from GitHub repository
            github_repo = os.getenv('GITHUB_REPOSITORY', 'user/repo')
            self.ssh_repo_url = f"git@github.com:{github_repo}.git"
        
        logger.info(f"SSH Repo URL: {self.ssh_repo_url}")
        logger.info(f"Repository Name: {self.repo_name}")
        
        # SSH options
        self.ssh_options = [
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=30",
            "-o", "BatchMode=yes",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3"
        ]
    
    def _init_modules(self):
        """Initialize VPSClient and RepoManager with strict directory paths"""
        try:
            # Extract repo name for directory paths
            temp_repo_manager = RepoManager({
                'ssh_repo_url': self.ssh_repo_url,
                'base_temp_dir': Path("/tmp"),  # Will be overridden
                'git_workflow_dir': Path("/tmp"),  # Will be overridden
                'state_tracking_dir': Path("/tmp")  # Will be overridden
            })
            extracted_repo_name = temp_repo_manager.repo_name
            
            # Use provided repo name if available, otherwise extracted
            actual_repo_name = self.repo_name if self.repo_name else extracted_repo_name
            
            # STRICT PATH SPECIFICATIONS
            base_temp_dir = Path(f"/tmp/{actual_repo_name}_build_temp")
            git_workflow_dir = base_temp_dir / "git_workflow"
            state_tracking_dir = base_temp_dir / ".build_tracking"
            
            # Ensure directories exist
            base_temp_dir.mkdir(parents=True, exist_ok=True)
            git_workflow_dir.mkdir(parents=True, exist_ok=True)
            state_tracking_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"📁 Directory structure:")
            logger.info(f"  Base temp: {base_temp_dir}")
            logger.info(f"  Git workflow: {git_workflow_dir}")
            logger.info(f"  State tracking: {state_tracking_dir}")
            
            # Initialize RepoManager with strict paths
            repo_config = {
                'ssh_repo_url': self.ssh_repo_url,
                'base_temp_dir': base_temp_dir,
                'git_workflow_dir': git_workflow_dir,
                'state_tracking_dir': state_tracking_dir
            }
            self.repo_manager = RepoManager(repo_config)
            
            # Initialize VPSClient
            vps_config = {
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
                'ssh_key': self.ssh_key,
                'remote_dir': self.remote_dir,
                'ssh_options': self.ssh_options,
                'state_tracking_dir': state_tracking_dir  # STRICT REQUIREMENT
            }
            self.vps_client = VPSClient(vps_config)
            
            logger.info("✅ All modules initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Error initializing modules: {e}")
            sys.exit(1)
    
    def sync_vps_state(self):
        """ZERO-DOWNLOAD POLICY: Get VPS state without downloading .pkg files"""
        logger.info("\n" + "="*60)
        logger.info("VPS STATE SYNCHRONIZATION (Zero-Download Policy)")
        logger.info("="*60)
        
        # Test SSH connection first
        if not self.vps_client.test_ssh_connection():
            logger.error("❌ Cannot connect to VPS, aborting")
            return False
        
        # Get VPS state (downloads or generates vps_state.json)
        self.vps_state = self.vps_client.get_vps_state()
        
        if not self.vps_state:
            logger.error("❌ Failed to get VPS state")
            return False
        
        logger.info(f"✅ VPS state synchronized: {len(self.vps_state.get('packages', []))} packages")
        return True
    
    def compare_package_versions(self):
        """Compare local PKGBUILD versions with VPS state to find updates needed"""
        logger.info("\n" + "="*60)
        logger.info("PACKAGE VERSION COMPARISON")
        logger.info("="*60)
        
        # Clone repository for comparison
        if not self.repo_manager.clone_repository():
            logger.error("❌ Failed to clone repository")
            return False
        
        # Find all PKGBUILD directories
        pkgbuild_dirs = self.repo_manager.find_pkgbuild_dirs()
        
        # Create mapping of package name to VPS version
        vps_packages = {}
        for pkg in self.vps_state.get('packages', []):
            vps_packages[pkg['name']] = pkg['version']
        
        # Compare versions
        for pkg_name, pkg_dir in pkgbuild_dirs:
            local_version = self.repo_manager.get_current_version(pkg_dir)
            
            if not local_version:
                logger.warning(f"⚠️ Could not get version for {pkg_name}")
                continue
            
            if pkg_name in vps_packages:
                vps_version = vps_packages[pkg_name]
                
                # Simple version comparison (for demo - use vercmp in production)
                if local_version != vps_version:
                    logger.info(f"📦 {pkg_name}: VPS={vps_version}, Local={local_version} -> UPDATE NEEDED")
                    self.packages_to_update.append({
                        'name': pkg_name,
                        'dir': pkg_dir,
                        'vps_version': vps_version,
                        'local_version': local_version
                    })
                else:
                    logger.info(f"✅ {pkg_name}: Up to date ({local_version})")
            else:
                logger.info(f"🆕 {pkg_name}: Not on VPS, new package")
                self.packages_to_update.append({
                    'name': pkg_name,
                    'dir': pkg_dir,
                    'vps_version': None,
                    'local_version': local_version
                })
        
        logger.info(f"\n📊 Summary: {len(self.packages_to_update)} packages need updates")
        return True
    
    def update_packages(self):
        """Update PKGBUILD versions and push changes"""
        if not self.packages_to_update:
            logger.info("✅ All packages are up to date")
            return True
        
        logger.info("\n" + "="*60)
        logger.info("UPDATING PACKAGES")
        logger.info("="*60)
        
        # Ensure repository is cloned
        if not self.repo_manager.git_workflow_dir.exists():
            if not self.repo_manager.clone_repository():
                return False
        
        # Update each package
        updated_count = 0
        for pkg_info in self.packages_to_update:
            pkg_name = pkg_info['name']
            pkg_dir = pkg_info['dir']
            local_version = pkg_info['local_version']
            
            logger.info(f"\n🔄 Updating {pkg_name} to {local_version}...")
            
            # Update PKGBUILD
            if self.repo_manager.update_pkgbuild_version(pkg_name, pkg_dir, local_version):
                updated_count += 1
                logger.info(f"✅ Updated {pkg_name}")
            else:
                logger.error(f"❌ Failed to update {pkg_name}")
        
        if updated_count > 0:
            # Commit and push changes
            commit_message = f"build: Update {updated_count} package(s)\n\n"
            commit_message += "Automated version bump by Package Builder\n"
            commit_message += "\nUpdated packages:\n"
            for pkg_info in self.packages_to_update[:5]:  # Limit to first 5
                commit_message += f"- {pkg_info['name']}: {pkg_info.get('vps_version', 'new')} → {pkg_info['local_version']}\n"
            if len(self.packages_to_update) > 5:
                commit_message += f"- ... and {len(self.packages_to_update) - 5} more\n"
            
            logger.info(f"\n📝 Commit message:\n{commit_message}")
            
            if self.repo_manager.commit_and_push(commit_message):
                logger.info(f"✅ Successfully pushed updates for {updated_count} packages")
                return True
            else:
                logger.error("❌ Failed to push updates")
                return False
        else:
            logger.info("ℹ️ No packages needed updates")
            return True
    
    def run(self):
        """Main execution flow"""
        logger.info("\n" + "="*60)
        logger.info("🚀 PACKAGE BUILDER ORCHESTRATOR")
        logger.info("="*60)
        
        try:
            # Step 1: Sync VPS state with Zero-Download Policy
            if not self.sync_vps_state():
                return 1
            
            # Step 2: Compare versions
            if not self.compare_package_versions():
                return 1
            
            # Step 3: Update packages if needed
            if not self.update_packages():
                return 1
            
            # Step 4: Cleanup
            self.repo_manager.cleanup()
            
            logger.info("\n" + "="*60)
            logger.info("✅ BUILD COMPLETED SUCCESSFULLY")
            logger.info("="*60)
            logger.info(f"Packages checked: {len(self.repo_manager.find_pkgbuild_dirs())}")
            logger.info(f"Packages to update: {len(self.packages_to_update)}")
            logger.info(f"VPS packages: {len(self.vps_state.get('packages', []))}")
            
            return 0
            
        except Exception as e:
            logger.error(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            # Always cleanup
            self.repo_manager.cleanup()


if __name__ == "__main__":
    builder = PackageBuilder()
    sys.exit(builder.run())