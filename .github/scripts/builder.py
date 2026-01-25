#!/usr/bin/env python3
"""
Manjaro Package Builder - Optimized Workflow
Main orchestrator with state-first initialization and metadata-based comparison
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Add the script directory to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Import our modules
try:
    from modules.repo_manager import RepoManager
    from modules.vps_client import VPSClient
    from modules.build_engine import BuildEngine
    from modules.gpg_handler import GPGHandler
    from modules.aur_client import AURClient
    MODULES_LOADED = True
    logger = logging.getLogger(__name__)
    logger.info("✅ All modules imported successfully")
except ImportError as e:
    print(f"❌ CRITICAL: Failed to import modules: {e}")
    print(f"❌ Please ensure modules are in: {script_dir}/modules/")
    MODULES_LOADED = False
    sys.exit(1)

# Try to import our config files
try:
    import config
    import packages
    HAS_CONFIG_FILES = True
except ImportError as e:
    print(f"⚠️ Warning: Could not import config files: {e}")
    print("⚠️ Using default configurations")
    HAS_CONFIG_FILES = False

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
    """Main orchestrator with optimized workflow"""
    
    def __init__(self):
        # Run pre-flight environment validation
        self._validate_env()
        
        # Get the repository root
        self.repo_root = self._get_repo_root()
        
        # Setup directories
        self.output_dir = self.repo_root / (getattr(config, 'OUTPUT_DIR', 'built_packages') if HAS_CONFIG_FILES else "built_packages")
        self.output_dir.mkdir(exist_ok=True)
        
        # Load configuration values
        self.aur_urls = getattr(config, 'AUR_URLS', ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]) if HAS_CONFIG_FILES else ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]
        self.aur_build_dir = self.repo_root / (getattr(config, 'AUR_BUILD_DIR', 'build_aur') if HAS_CONFIG_FILES else "build_aur")
        self.ssh_options = getattr(config, 'SSH_OPTIONS', ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]) if HAS_CONFIG_FILES else ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]
        self.ssh_repo_url = getattr(config, 'SSH_REPO_URL', '') if HAS_CONFIG_FILES else ''
        
        # Get PACKAGER_ID - FIXED: Load after config check
        if HAS_CONFIG_FILES:
            self.packager_id = getattr(config, 'PACKAGER_ID', 'Maintainer <no-reply@gshoots.hu>')
        else:
            self.packager_id = 'Maintainer <no-reply@gshoots.hu>'
        
        # Load environment configuration
        self._load_config()
        
        # Initialize modules
        self._init_modules()
        
        # State tracking
        self.built_packages = []
        self.skipped_packages = []
        self.failed_packages = []
        self.decisions = {}
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
            "dependency_injections": 0,
            "pacman_syncs": 0,
            "state_initializations": 0,
            "metadata_checks": 0,
        }

    def _validate_env(self) -> None:
        """Pre-flight environment validation"""
        logger.info("\n" + "=" * 60)
        logger.info("ENVIRONMENT VALIDATION")
        logger.info("=" * 60)
        
        required_vars = ['REPO_NAME', 'VPS_HOST', 'VPS_USER', 'VPS_SSH_KEY', 'REMOTE_DIR']
        
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value or value.strip() == '':
                missing_vars.append(var)
                logger.error(f"[ERROR] Variable {var} is empty! Ensure it is set in GitHub Secrets.")
        
        if missing_vars:
            sys.exit(1)
        
        logger.info("✅ Environment validation passed")
    
    def _load_config(self):
        """Load configuration from environment variables"""
        # Required environment variables (secrets)
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        
        # Optional environment variables
        self.repo_server_url = os.getenv('REPO_SERVER_URL', '')
        self.remote_dir = os.getenv('REMOTE_DIR')
        self.repo_name = os.getenv('REPO_NAME')
        
        logger.info(f"🔧 Configuration loaded")
        logger.info(f"   SSH user: {self.vps_user}")
        logger.info(f"   VPS host: {self.vps_host}")
        logger.info(f"   Remote directory: {self.remote_dir}")
        logger.info(f"   Repository name: {self.repo_name}")
        logger.info(f"   PACKAGER: {self.packager_id}")
        if self.repo_server_url:
            logger.info(f"   Repository URL: {self.repo_server_url}")
    
    def _init_modules(self):
        """Initialize all modules with configuration"""
        try:
            # VPS Client configuration
            vps_config = {
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
                'remote_dir': self.remote_dir,
                'ssh_options': self.ssh_options,
                'repo_name': self.repo_name,
            }
            self.vps_client = VPSClient(vps_config)
            self.vps_client.setup_ssh_config(self.ssh_key)
            
            # Repository Manager configuration
            repo_config = {
                'repo_name': self.repo_name,
                'output_dir': self.output_dir,
                'remote_dir': self.remote_dir,
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
            }
            self.repo_manager = RepoManager(repo_config)
            
            # Build Engine configuration
            build_config = {
                'repo_root': self.repo_root,
                'output_dir': self.output_dir,
                'aur_build_dir': self.aur_build_dir,
                'aur_urls': self.aur_urls,
                'repo_name': self.repo_name,
            }
            self.build_engine = BuildEngine(build_config)
            
            # GPG Handler
            self.gpg_handler = GPGHandler()
            
            # AUR RPC Client
            self.aur_client = AURClient()
            
            logger.info("✅ All modules initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Error initializing modules: {e}")
            sys.exit(1)
    
    def _get_repo_root(self):
        """Get the repository root directory reliably"""
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                return workspace_path
        
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent.parent
        if repo_root.exists():
            return repo_root
        
        return Path.cwd()
    
    def get_package_lists(self):
        """Get package lists from packages.py"""
        if HAS_CONFIG_FILES and hasattr(packages, 'LOCAL_PACKAGES') and hasattr(packages, 'AUR_PACKAGES'):
            local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
            logger.info(f"📦 Loaded {len(local_packages_list)} local + {len(aur_packages_list)} AUR packages")
            return local_packages_list, aur_packages_list
        else:
            logger.error("Cannot load package lists from packages.py. Exiting.")
            sys.exit(1)
    
    def _enable_custom_repository(self, exists: bool, has_packages: bool):
        """Enable custom repository with immediate pacman sync"""
        logger.info(f"\n🔧 Configuring repository: {self.repo_name}")
        
        pacman_conf = Path("/etc/pacman.conf")
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found")
            return False
        
        try:
            # Read current pacman.conf
            with open(pacman_conf, 'r') as f:
                content = f.read()
            
            # Check if our repo already exists
            repo_section = f"[{self.repo_name}]"
            if repo_section in content:
                logger.info(f"✅ Repository {self.repo_name} already in pacman.conf")
            else:
                # Add repository section
                new_section = f"""
# Custom repository: {self.repo_name}
{repo_section}
SigLevel = Optional TrustAll
Server = {self.repo_server_url if self.repo_server_url else '$REPO_SERVER_URL'}
"""
                
                # Append to pacman.conf
                with open(pacman_conf, 'a') as f:
                    f.write(new_section)
                logger.info(f"✅ Added repository {self.repo_name} to pacman.conf")
            
            # CRITICAL: Immediate pacman sync
            logger.info("🔄 Running pacman -Sy to sync databases...")
            result = subprocess.run(
                ["sudo", "pacman", "-Sy", "--noconfirm"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False
            )
            
            if result.returncode == 0:
                self.stats["pacman_syncs"] += 1
                logger.info("✅ Pacman databases synchronized")
                return True
            else:
                logger.error(f"❌ Pacman sync failed: {result.stderr[:200]}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to configure repository: {e}")
            return False
    
    def _state_first_initialization(self) -> bool:
        """
        State-first initialization: Load state from VPS before any operations
        """
        logger.info("\n📊 STATE-FIRST INITIALIZATION")
        
        # Step 1: Try to download existing state from VPS
        logger.info("1. Downloading state from VPS...")
        state_downloaded = self.vps_client.download_state_file(self.repo_manager.state_file)
        
        # Step 2: Load state or initialize from VPS
        if state_downloaded:
            logger.info("2. Loading existing state...")
            if not self.repo_manager.load_state():
                logger.warning("⚠️ Failed to load state, initializing from VPS")
                if not self.repo_manager.initialize_state_from_vps(self.vps_client):
                    logger.error("❌ Failed to initialize state from VPS")
                    return False
        else:
            logger.info("2. No state on VPS, initializing from VPS package list...")
            if not self.repo_manager.initialize_state_from_vps(self.vps_client):
                logger.error("❌ Failed to initialize state from VPS")
                return False
        
        self.stats["state_initializations"] += 1
        logger.info(f"✅ State initialized with {len(self.repo_manager.state_data)} packages")
        return True
    
    def _metadata_based_comparison(self, local_packages: List[str], aur_packages: List[str]) -> Dict[str, Dict]:
        """
        Metadata-based comparison using AUR RPC API and local PKGBUILDs
        """
        logger.info("\n🔍 METADATA-BASED COMPARISON")
        
        decisions = {}
        
        # Process AUR packages via RPC API
        if aur_packages:
            logger.info(f"📡 Fetching AUR metadata for {len(aur_packages)} packages...")
            
            for pkg_name in aur_packages:
                self.stats["metadata_checks"] += 1
                aur_info = self.aur_client.get_package_info(pkg_name)
                aur_version = aur_info.get("Version") if aur_info else None
                
                if not aur_version:
                    logger.warning(f"⚠️ Could not fetch AUR metadata for {pkg_name}")
                    decisions[pkg_name] = {
                        "type": "aur",
                        "build": True,
                        "reason": "Failed to fetch AUR metadata",
                        "version": None
                    }
                    continue
                
                # Decision Engine
                decision = self.repo_manager.decision_engine(
                    pkg_name=pkg_name,
                    pkg_type="aur",
                    local_version=aur_version,
                    aur_version=aur_version,
                    vps_client=self.vps_client
                )
                
                decision["type"] = "aur"
                decision["version"] = aur_version
                decisions[pkg_name] = decision
                
                if decision.get("skip"):
                    logger.info(f"✅ {pkg_name}: SKIPPED ({decision['reason']})")
        
        # Process Local packages from PKGBUILD
        for pkg_name in local_packages:
            pkg_dir = self.repo_root / pkg_name
            pkgbuild = pkg_dir / "PKGBUILD"
            
            if not pkgbuild.exists():
                logger.warning(f"⚠️ PKGBUILD not found for {pkg_name}")
                decisions[pkg_name] = {
                    "type": "local",
                    "build": False,
                    "reason": "PKGBUILD not found",
                    "version": None
                }
                continue
            
            try:
                # Extract version from PKGBUILD
                pkgver, pkgrel, epoch = self.build_engine.extract_version_from_srcinfo(pkg_dir)
                local_version = self.build_engine.get_full_version_string(pkgver, pkgrel, epoch)
                
                # Decision Engine
                decision = self.repo_manager.decision_engine(
                    pkg_name=pkg_name,
                    pkg_type="local",
                    local_version=local_version,
                    vps_client=self.vps_client
                )
                
                decision["type"] = "local"
                decision["version"] = local_version
                decisions[pkg_name] = decision
                
                if decision.get("skip"):
                    logger.info(f"✅ {pkg_name}: SKIPPED ({decision['reason']})")
                    
            except Exception as e:
                logger.error(f"❌ Failed to extract version for {pkg_name}: {e}")
                decisions[pkg_name] = {
                    "type": "local",
                    "build": False,
                    "reason": f"Version extraction failed: {e}",
                    "version": None
                }
        
        # Summary
        build_count = sum(1 for d in decisions.values() if d.get("build"))
        skip_count = sum(1 for d in decisions.values() if d.get("skip"))
        
        logger.info(f"\n📊 Comparison results:")
        logger.info(f"   To build: {build_count}")
        logger.info(f"   To skip: {skip_count}")
        
        return decisions
    
    def _clone_and_build_aur(self, pkg_name: str, aur_version: str) -> bool:
        """Clone and build AUR package"""
        logger.info(f"\n🏗️  Building AUR: {pkg_name} ({aur_version})")
        
        pkg_dir = self.aur_build_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)
        
        # Clone from AUR
        clone_success = False
        for aur_url_template in self.aur_urls:
            aur_url = aur_url_template.format(pkg_name=pkg_name)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", aur_url, str(pkg_dir)],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                clone_success = True
                break
        
        if not clone_success:
            logger.error(f"❌ Failed to clone {pkg_name}")
            return False
        
        # Build with makepkg
        build_result = subprocess.run(
            ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"],
            cwd=pkg_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=3600,
            env={**os.environ, "PACKAGER": self.packager_id}
        )
        
        if build_result.returncode == 0:
            # Move built packages
            for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                dest = self.output_dir / pkg_file.name
                shutil.move(str(pkg_file), str(dest))
                logger.info(f"✅ Built: {pkg_file.name}")
                
                # Update state
                self.repo_manager.update_package_state(
                    pkg_name, aur_version, pkg_file.name, self.vps_client
                )
            
            shutil.rmtree(pkg_dir, ignore_errors=True)
            self.built_packages.append(f"{pkg_name} ({aur_version})")
            return True
        else:
            logger.error(f"❌ Build failed: {build_result.stderr[:500]}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
    
    def _build_local_package(self, pkg_name: str, local_version: str) -> bool:
        """Build local package"""
        logger.info(f"\n🏗️  Building local: {pkg_name} ({local_version})")
        
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"❌ Package directory not found: {pkg_name}")
            return False
        
        build_result = subprocess.run(
            ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"],
            cwd=pkg_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=3600,
            env={**os.environ, "PACKAGER": self.packager_id}
        )
        
        if build_result.returncode == 0:
            # Move built packages
            for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                dest = self.output_dir / pkg_file.name
                shutil.move(str(pkg_file), str(dest))
                logger.info(f"✅ Built: {pkg_file.name}")
                
                # Update state
                self.repo_manager.update_package_state(
                    pkg_name, local_version, pkg_file.name, self.vps_client
                )
            
            self.built_packages.append(f"{pkg_name} ({local_version})")
            return True
        else:
            logger.error(f"❌ Build failed: {build_result.stderr[:500]}")
            return False
    
    def _run_multi_pass_build(self, decisions: Dict[str, Dict]) -> Tuple[int, int]:
        """
        Multi-pass build system with dependency injection
        """
        logger.info("\n🔄 MULTI-PASS BUILD SYSTEM")
        
        # Get packages to build
        packages_to_build = [pkg for pkg, dec in decisions.items() if dec.get("build")]
        logger.info(f"Starting with {len(packages_to_build)} packages to build")
        
        max_passes = 3
        success_count = 0
        fail_count = 0
        
        for pass_num in range(1, max_passes + 1):
            if not packages_to_build:
                break
            
            logger.info(f"\n🔄 Pass {pass_num}/{max_passes}")
            built_this_pass = []
            
            for pkg_name in list(packages_to_build):
                decision = decisions[pkg_name]
                pkg_type = decision["type"]
                version = decision.get("version")
                
                if not version:
                    logger.warning(f"⚠️ {pkg_name}: No version, skipping")
                    packages_to_build.remove(pkg_name)
                    fail_count += 1
                    continue
                
                # Build attempt
                success = False
                if pkg_type == "aur":
                    success = self._clone_and_build_aur(pkg_name, version)
                else:  # local
                    success = self._build_local_package(pkg_name, version)
                
                if success:
                    built_this_pass.append(pkg_name)
                    packages_to_build.remove(pkg_name)
                    success_count += 1
                    
                    # Dependency injection after each successful build
                    logger.info("⚛️ Updating local database...")
                    if self.repo_manager.atomic_dependency_injection(self.build_engine):
                        self.stats["dependency_injections"] += 1
                else:
                    fail_count += 1
                    self.failed_packages.append(pkg_name)
            
            logger.info(f"Pass {pass_num}: Built {len(built_this_pass)} packages, {len(packages_to_build)} remaining")
            
            if not built_this_pass and packages_to_build:
                logger.warning("⚠️ No packages built this pass, breaking loop")
                break
        
        return success_count, fail_count
    
    def _final_sync(self):
        """
        Final synchronization: Upload packages and state to VPS
        """
        logger.info("\n🧹 FINAL SYNC")
        
        # Step 1: Generate final database
        logger.info("1. Generating final repository database...")
        if not self.repo_manager.generate_full_database():
            logger.error("❌ Failed to generate final database")
            return False
        
        # Step 2: GPG signing
        if self.gpg_handler.gpg_enabled:
            logger.info("2. Signing repository files...")
            self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir))
        
        # Step 3: Upload to VPS
        logger.info("3. Uploading packages to VPS...")
        files_to_upload = [str(f) for f in self.output_dir.glob("*")]
        if files_to_upload:
            if not self.vps_client.upload_files(files_to_upload, self.output_dir):
                logger.error("❌ Upload failed")
                return False
        
        # Step 4: Upload updated state
        logger.info("4. Uploading updated state to VPS...")
        self.vps_client.upload_state_file(self.repo_manager.state_file)
        
        # Step 5: Final pacman sync
        logger.info("5. Final pacman sync...")
        subprocess.run(["sudo", "pacman", "-Sy", "--noconfirm"], 
                     capture_output=True, timeout=120, check=False)
        self.stats["pacman_syncs"] += 1
        
        # Step 6: Git sync (optional)
        if self.ssh_repo_url:
            logger.info("6. Syncing state to Git...")
            self._sync_state_to_git()
        
        logger.info("✅ Final sync completed")
        return True
    
    def _sync_state_to_git(self):
        """Sync state file to Git repository"""
        logger.info("📤 Syncing state to Git...")
        
        state_file = self.repo_manager.state_file
        if not state_file.exists():
            logger.warning("⚠️ No state file to sync")
            return
        
        temp_dir = Path("/tmp/git_sync")
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        try:
            temp_dir.mkdir(parents=True)
            
            # Setup SSH for git
            env = os.environ.copy()
            ssh_key_path = "/home/builder/.ssh/id_ed25519"
            if os.path.exists(ssh_key_path):
                env['GIT_SSH_COMMAND'] = f'ssh -i {ssh_key_path} -o StrictHostKeyChecking=no'
            
            # Clone
            clone_cmd = ["git", "clone", "--depth", "1", self.ssh_repo_url, str(temp_dir)]
            result = subprocess.run(clone_cmd, capture_output=True, text=True, env=env, timeout=300, check=False)
            
            if result.returncode != 0:
                logger.error(f"❌ Git clone failed: {result.stderr[:200]}")
                return
            
            # Copy state file
            dest_state_dir = temp_dir / ".build_tracking"
            dest_state_dir.mkdir(exist_ok=True)
            shutil.copy2(state_file, dest_state_dir / "vps_state.json")
            
            # Commit and push
            subprocess.run(["git", "config", "user.email", "builder@github-actions.com"], cwd=temp_dir, check=False)
            subprocess.run(["git", "config", "user.name", "GitHub Actions Builder"], cwd=temp_dir, check=False)
            subprocess.run(["git", "add", ".build_tracking/vps_state.json"], cwd=temp_dir, check=False)
            subprocess.run(["git", "commit", "-m", "Update package state"], cwd=temp_dir, check=False)
            push_result = subprocess.run(["git", "push"], cwd=temp_dir, capture_output=True, text=True, env=env, check=False)
            
            if push_result.returncode == 0:
                logger.info("✅ State synced to Git")
            else:
                logger.error(f"❌ Git push failed: {push_result.stderr[:200]}")
            
        except Exception as e:
            logger.error(f"❌ Git sync error: {e}")
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def run(self) -> int:
        """Main workflow execution"""
        try:
            # STEP 0: GPG Initialization
            logger.info("\n" + "=" * 60)
            logger.info("STEP 0: GPG INITIALIZATION")
            logger.info("=" * 60)
            if self.gpg_handler.gpg_enabled:
                self.gpg_handler.import_gpg_key()
            
            # STEP 1: Repository Setup
            logger.info("\n" + "=" * 60)
            logger.info("STEP 1: REPOSITORY SETUP")
            logger.info("=" * 60)
            repo_exists, has_packages = self.vps_client.check_repository_exists_on_vps()
            self._enable_custom_repository(repo_exists, has_packages)
            self.vps_client.ensure_remote_directory()
            
            # STEP 2: STATE-FIRST INITIALIZATION
            if not self._state_first_initialization():
                logger.error("❌ State initialization failed")
                return 1
            
            # STEP 3: METADATA-BASED COMPARISON
            local_packages, aur_packages = self.get_package_lists()
            self.decisions = self._metadata_based_comparison(local_packages, aur_packages)
            
            # STEP 4: MULTI-PASS BUILD
            success_count, fail_count = self._run_multi_pass_build(self.decisions)
            
            # Update statistics
            for pkg_name, decision in self.decisions.items():
                if decision.get("build"):
                    if pkg_name in self.failed_packages:
                        if decision["type"] == "aur":
                            self.stats["aur_failed"] += 1
                        else:
                            self.stats["local_failed"] += 1
                    else:
                        if decision["type"] == "aur":
                            self.stats["aur_success"] += 1
                        else:
                            self.stats["local_success"] += 1
            
            # STEP 5: FINAL SYNC
            if success_count > 0:
                self._final_sync()
            
            # STEP 6: GPG Cleanup
            self.gpg_handler.cleanup()
            
            # FINAL STATISTICS
            elapsed = time.time() - self.stats["start_time"]
            
            logger.info("\n" + "=" * 60)
            logger.info("📊 WORKFLOW SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Duration: {elapsed:.1f}s")
            logger.info(f"AUR packages: {self.stats['aur_success']} (failed: {self.stats['aur_failed']})")
            logger.info(f"Local packages: {self.stats['local_success']} (failed: {self.stats['local_failed']})")
            logger.info(f"Total built: {self.stats['aur_success'] + self.stats['local_success']}")
            logger.info(f"Failed: {self.stats['aur_failed'] + self.stats['local_failed']}")
            logger.info(f"Dependency injections: {self.stats['dependency_injections']}")
            logger.info(f"Pacman syncs: {self.stats['pacman_syncs']}")
            logger.info(f"Metadata checks: {self.stats['metadata_checks']}")
            logger.info("=" * 60)
            
            if self.built_packages:
                logger.info("\n📦 Built packages:")
                for pkg in self.built_packages:
                    logger.info(f"  - {pkg}")
            
            if self.failed_packages:
                logger.info("\n❌ Failed packages:")
                for pkg in self.failed_packages:
                    logger.info(f"  - {pkg}")
            
            return 0 if fail_count == 0 else 1
            
        except Exception as e:
            logger.error(f"\n❌ Workflow failed: {e}")
            import traceback
            traceback.print_exc()
            self.gpg_handler.cleanup()
            return 1


if __name__ == "__main__":
    sys.exit(PackageBuilder().run())