"""
Main Orchestration Script for Arch Linux Package Builder
WITH NON-BLOCKING HOKIBOT AND STAGING PUBLISH + SAFETY UPGRADES
"""

import os
import sys
import logging
import subprocess
import tempfile
import random
import string
import datetime
from pathlib import Path
from typing import List, Tuple, Dict, Set

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add script directory to path for imports
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

try:
    # Import modules
    from modules.common.config_loader import ConfigLoader
    from modules.common.environment import EnvironmentValidator
    from modules.common.shell_executor import ShellExecutor
    
    from modules.vps.ssh_client import SSHClient
    from modules.vps.rsync_client import RsyncClient
    
    from modules.repo.manifest_factory import ManifestFactory
    from modules.repo.smart_cleanup import SmartCleanup
    from modules.repo.cleanup_manager import CleanupManager
    from modules.repo.database_manager import DatabaseManager
    from modules.repo.version_tracker import VersionTracker
    
    from modules.build.package_builder import create_package_builder
    from modules.build.artifact_manager import ArtifactManager
    from modules.build.build_tracker import BuildTracker
    
    from modules.gpg.gpg_handler import GPGHandler
    
    from modules.hokibot.hokibot import HokibotRunner
    
    MODULES_LOADED = True
except ImportError as e:
    logger.error(f"Failed to import modules: {e}")
    MODULES_LOADED = False
    sys.exit(1)


class PackageBuilderOrchestrator:
    """Main orchestrator coordinating all phases WITH NON-BLOCKING HOKIBOT AND STAGING PUBLISH + SAFETY UPGRADES"""
    
    def __init__(self):
        """Initialize orchestrator with all modules"""
        # CRITICAL: Single pipeline owner declaration
        logger.info("PIPELINE_OWNER=builder.py")
        
        # Pre-flight validation
        EnvironmentValidator.validate_env()
        
        # Load configuration
        self.config_loader = ConfigLoader()
        self.repo_root = self.config_loader.get_repo_root()
        
        env_config = self.config_loader.load_environment_config()
        python_config = self.config_loader.load_from_python_config()
        
        # Store configuration
        self.repo_name = env_config['repo_name']
        self.vps_user = env_config['vps_user']
        self.vps_host = env_config['vps_host']
        self.ssh_key = env_config['ssh_key']
        self.remote_dir = env_config['remote_dir']
        self.gpg_key_id = env_config['gpg_key_id']
        self.gpg_private_key = env_config['gpg_private_key']
        self.repo_server_url = env_config['repo_server_url']
        
        self.output_dir = self.repo_root / python_config['output_dir']
        self.mirror_temp_dir = Path(python_config['mirror_temp_dir'])
        self.aur_build_dir = self.repo_root / python_config['aur_build_dir']
        self.ssh_options = python_config['ssh_options']
        self.packager_id = python_config['packager_id']
        self.debug_mode = python_config['debug_mode']
        self.sign_packages = python_config['sign_packages']
        
        # Initialize modules
        self._init_modules()
        
        # State tracking
        self.vps_files = []
        self.vps_packages = []
        self.allowlist = set()
        self.built_packages = []
        self.skipped_packages = []
        self.desired_inventory = set()
        
        # GATE STATE TRACKING
        self.gate_state = {
            'packages_built': 0,
            'database_success': False,
            'signature_success': False,
            'upload_success': False,
            'up3_success': False,
            'promotion_success': False,   # NEW: staging promotion success
            'destructive_cleanup_allowed': False
        }
        
        # Post-repo-enable pacman -Sy tracking
        self.post_repo_enable_sy_count = 0
        self.post_repo_enable_sy_ran = False
        
        logger.info("PackageBuilderOrchestrator initialized")
    
    def _init_modules(self):
        """Initialize all required modules"""
        # VPS modules
        vps_config = {
            'vps_user': self.vps_user,
            'vps_host': self.vps_host,
            'remote_dir': self.remote_dir,
            'ssh_options': self.ssh_options,
            'repo_name': self.repo_name,
        }
        self.ssh_client = SSHClient(vps_config)
        self.ssh_client.setup_ssh_config(self.ssh_key)
        
        self.rsync_client = RsyncClient(vps_config)
        
        # Repository modules
        repo_config = {
            'repo_name': self.repo_name,
            'output_dir': self.output_dir,
            'remote_dir': self.remote_dir,
            'mirror_temp_dir': self.mirror_temp_dir,
            'vps_user': self.vps_user,
            'vps_host': self.vps_host,
        }
        self.cleanup_manager = CleanupManager(repo_config)
        self.database_manager = DatabaseManager(repo_config)
        self.version_tracker = VersionTracker(repo_config)
        
        # Build modules
        self.artifact_manager = ArtifactManager()
        self.build_tracker = BuildTracker()
        
        # GPG Handler
        self.gpg_handler = GPGHandler(self.sign_packages)
        
        # Shell executor
        self.shell_executor = ShellExecutor(self.debug_mode)
        
        # Package builder
        self._ensure_output_directory()
        
        self.package_builder = create_package_builder(
            packager_id=self.packager_id,
            output_dir=self.output_dir,
            gpg_key_id=self.gpg_key_id,
            gpg_private_key=self.gpg_private_key,
            sign_packages=self.sign_packages,
            debug_mode=self.debug_mode,
            version_tracker=self.version_tracker,
            build_tracker=self.build_tracker
        )
        
        # Initialize HokibotRunner
        self.hokibot_runner = HokibotRunner(debug_mode=self.debug_mode)
        
        logger.info("All modules initialized successfully")
    
    def _ensure_output_directory(self):
        """Ensure output directory exists with proper ownership and permissions."""
        try:
            self.output_dir.mkdir(exist_ok=True, parents=True)
            self.output_dir.chmod(0o755)
            subprocess.run(['chown', '-R', 'builder:builder', str(self.output_dir)], check=False)
            
            test_file = self.output_dir / ".write_test"
            try:
                test_file.touch()
                test_file.unlink()
                writable = True
            except (IOError, OSError):
                writable = False
            
            logger.info(f"OUTPUT_DIR_EXISTS=1 path={self.output_dir} writable={writable}")
            
            if not writable:
                logger.error(f"CRITICAL: Output directory is not writable: {self.output_dir}")
                subprocess.run(['chmod', '777', str(self.output_dir)], check=False)
                subprocess.run(['chown', '-R', 'builder:builder', str(self.output_dir)], check=False)
                    
        except Exception as e:
            logger.error(f"Failed to ensure output directory exists: {e}")
            raise
    
    def _generate_run_id(self) -> str:
        """
        Generate a unique run ID for staging directory.
        Uses GITHUB_RUN_ID environment variable if available.
        
        Returns:
            String identifier for this CI run
        """
        github_run_id = os.getenv('GITHUB_RUN_ID')
        if github_run_id:
            return f"run_{github_run_id}"
        else:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
            return f"{timestamp}_{suffix}"
    
    def _run_post_repo_enable_pacman_sy(self) -> bool:
        """Run post-repo-enable pacman -Sy with exactly-once proof logging."""
        if self.post_repo_enable_sy_ran:
            logger.info("PACMAN_POST_REPO_ENABLE_SY: BLOCKED (already_ran=true)")
            return False
        
        has_packages = len(self.vps_packages) > 0
        
        if not has_packages:
            logger.info("PACMAN_POST_REPO_ENABLE_SY: SKIP (reason=no_packages_in_repo)")
            return True
        
        logger.info(f"PACMAN_POST_REPO_ENABLE_SY: START (count_before={self.post_repo_enable_sy_count})")
        
        try:
            cmd = "sudo pacman -Sy --noconfirm"
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                check=False
            )
            
            if result.returncode == 0:
                self.post_repo_enable_sy_count += 1
                self.post_repo_enable_sy_ran = True
                logger.info(f"PACMAN_POST_REPO_ENABLE_SY: OK (count_after={self.post_repo_enable_sy_count})")
                return True
            else:
                self.post_repo_enable_sy_ran = True
                logger.warning(f"PACMAN_POST_REPO_ENABLE_SY: FAILED (error={result.stderr[:200]})")
                return False
                
        except subprocess.TimeoutExpired:
            self.post_repo_enable_sy_ran = True
            logger.warning("PACMAN_POST_REPO_ENABLE_SY: TIMEOUT")
            return False
        except Exception as e:
            self.post_repo_enable_sy_ran = True
            logger.warning(f"PACMAN_POST_REPO_ENABLE_SY: EXCEPTION (error={e})")
            return False
    
    def _evaluate_gates(self):
        """Evaluate fail-safe gates and determine if destructive cleanup is allowed."""
        # G1: Empty-run gate
        if self.gate_state['packages_built'] == 0:
            logger.info("GATE: empty-run (built=0) -> skipping destructive VPS deletions")
            self.gate_state['destructive_cleanup_allowed'] = False
        else:
            # G2: Partial-failure gate
            if (self.gate_state['database_success'] and 
                self.gate_state['signature_success'] and
                self.gate_state['upload_success']):
                self.gate_state['destructive_cleanup_allowed'] = True
            else:
                logger.info("GATE: partial failure -> skipping destructive VPS deletions")
                self.gate_state['destructive_cleanup_allowed'] = False
        
        # Version prune allowance
        version_prune_allowed = (
            self.gate_state['upload_success'] and
            self.gate_state['database_success'] and
            (self.gate_state['signature_success'] or not self.gpg_handler.gpg_enabled) and
            self.gate_state['up3_success']
        )
        
        if version_prune_allowed:
            logger.info("GATE: version prune allowed (upload+db+signature+UP3 success)")
        else:
            logger.info("GATE: version prune blocked (one or more checks failed)")
        
        return version_prune_allowed
    
    def phase_i_vps_sync(self) -> bool:
        """Phase I: VPS State Fetch"""
        logger.info("PHASE I: VPS State Fetch")
        
        if not self.ssh_client.test_ssh_connection():
            logger.warning("SSH connection test failed")
        
        self.ssh_client.ensure_remote_directory()
        
        remote_packages = self.ssh_client.list_remote_packages()
        self.vps_packages = remote_packages
        
        remote_signatures = self._get_vps_signatures()
        self.vps_files = self.vps_packages + remote_signatures
        
        logger.info(f"Found {len(self.vps_packages)} package files and {len(remote_signatures)} signatures on VPS")
        
        self.version_tracker.build_remote_version_index(self.vps_packages)
        
        if not self._run_post_repo_enable_pacman_sy():
            logger.warning("Post-repo-enable pacman -Sy was blocked or failed")
        
        self.package_builder.set_vps_files(self.vps_files)
        
        if self.vps_packages:
            logger.info("Mirroring remote packages locally (package files only)...")
            success = self.rsync_client.mirror_remote_packages(
                self.mirror_temp_dir,
                self.output_dir,
                self.vps_packages
            )
            if not success:
                logger.warning("Failed to mirror remote packages")
                return False
        
        return True
    
    def _get_vps_signatures(self) -> List[str]:
        """Get signature files from VPS for completeness check"""
        logger.info("Fetching VPS signature file list...")
        
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.warning(f"SSH key not found")
            return []
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            rf'find "{self.remote_dir}" -maxdepth 1 \( -type f -o -type l \) -name "*.sig" -printf "%f\\n" 2>/dev/null || echo "NO_FILES"'
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip() and f.strip() != 'NO_FILES']
                logger.info(f"Found {len(files)} signature files on remote server")
                return files
            else:
                logger.warning(f"SSH find for signatures returned error")
                return []
                
        except Exception as e:
            logger.warning(f"SSH command for signatures failed: {e}")
            return []
    
    def get_package_lists(self) -> Tuple[List[str], List[str]]:
        """Get package lists from packages.py"""
        try:
            import packages
            logger.info("Using package lists from packages.py")
            return packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
        except ImportError:
            try:
                import sys
                sys.path.insert(0, str(self.repo_root))
                import scripts.packages as packages
                logger.info("Using package lists from packages.py")
                return packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
            except ImportError:
                logger.error("Cannot load package lists from packages.py")
                sys.exit(1)
    
    def phase_ii_dynamic_allowlist(self) -> bool:
        """Phase II: Dynamic Allowlist Generation"""
        logger.info("PHASE II: Dynamic Allowlist Generation")
        
        local_packages, aur_packages = self.get_package_lists()
        
        package_sources = []
        
        for pkg in local_packages:
            pkg_dir = self.repo_root / pkg
            if pkg_dir.exists():
                package_sources.append(str(pkg_dir))
            else:
                logger.warning(f"Local package directory not found: {pkg}")
        
        for pkg in aur_packages:
            package_sources.append(pkg)
        
        logger.info(f"Processing {len(package_sources)} package sources...")
        self.allowlist = ManifestFactory.build_allowlist(package_sources)
        
        self.desired_inventory = self._build_desired_inventory(package_sources)
        logger.info(f"Desired inventory package names: {len(self.desired_inventory)}")
        if self.desired_inventory:
            first_ten = list(self.desired_inventory)[:10]
            logger.info(f"First 10 names: {first_ten}")
        
        logger.info(f"Allowlist generated: {len(self.allowlist)} package names")
        
        return len(self.allowlist) > 0
    
    def _build_desired_inventory(self, package_sources: List[str]) -> Set[str]:
        """Build desired inventory set from all PKGBUILDs."""
        desired_inventory = set()
        
        for source in package_sources:
            pkgbuild_content = ManifestFactory.get_pkgbuild(source)
            
            if pkgbuild_content:
                pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)
                
                if pkg_names:
                    desired_inventory.update(pkg_names)
                    logger.debug(f"Added to desired inventory from {source}: {pkg_names}")
                else:
                    logger.warning(f"No pkgname found in {source}")
            else:
                logger.warning(f"Could not load PKGBUILD from {source}")
        
        return desired_inventory
    
    def phase_iv_version_audit_and_build(self) -> Tuple[List[str], List[str]]:
        """Phase IV: Version Audit & Build"""
        logger.info("PHASE IV: Version Audit & Build")
        
        index_count, sample_list = self.version_tracker.get_remote_version_index_stats()
        logger.info(f"REMOTE_VERSION_INDEX_COUNT={index_count}")
        logger.info(f"REMOTE_VERSION_INDEX_SAMPLE={','.join(sample_list)}")
        
        local_packages, aur_packages = self.get_package_lists()
        
        local_packages_with_versions = []
        aur_packages_with_versions = []
        
        for pkg_name in local_packages:
            pkg_dir = self.repo_root / pkg_name
            if pkg_dir.exists():
                remote_version = self.version_tracker.get_remote_version(pkg_name, [])
                local_packages_with_versions.append((pkg_dir, remote_version))
            else:
                logger.warning(f"Local package directory not found: {pkg_name}")
        
        for pkg_name in aur_packages:
            remote_version = self.version_tracker.get_remote_version(pkg_name, [])
            aur_packages_with_versions.append((pkg_name, remote_version))
        
        self.version_tracker.set_desired_inventory(self.desired_inventory)
        
        built_packages, skipped_packages, failed_packages = (
            self.package_builder.batch_audit_and_build(
                local_packages=local_packages_with_versions,
                aur_packages=aur_packages_with_versions,
                aur_build_dir=self.aur_build_dir
            )
        )
        
        self.built_packages = built_packages
        self.skipped_packages = skipped_packages
        self.gate_state['packages_built'] = len(built_packages)
        
        hokibot_count = len(self.build_tracker.hokibot_data)
        logger.info(f"HOKIBOT_DATA_COUNT={hokibot_count}")
        
        logger.info(f"Build Results:")
        logger.info(f"   Built: {len(built_packages)} packages")
        logger.info(f"   Skipped: {len(skipped_packages)} packages")
        logger.info(f"   Failed: {len(failed_packages)} packages")
        
        if failed_packages:
            logger.error(f"Failed packages: {failed_packages}")
        
        return built_packages, skipped_packages
    
    def phase_v_sign_and_update(self) -> bool:
        """
        Phase V: Sign and Update WITH STAGING PUBLISH, ATOMIC PROMOTION,
        PRE‑PROMOTE VERIFICATION AND STALE STAGING CLEANUP.
        """
        logger.info("PHASE V: Sign and Update WITH STAGING PUBLISH + SAFETY UPGRADES")
        
        # ------------------------------------------------------------
        # P1) Best‑effort cleanup of stale staging directories (≥24h)
        # ------------------------------------------------------------
        logger.info("Cleaning up stale staging directories older than 24 hours...")
        self.ssh_client.cleanup_old_staging(max_age_hours=24)
        # ------------------------------------------------------------
        
        local_packages = list(self.output_dir.glob("*.pkg.tar.*"))
        if not local_packages:
            logger.info("No packages to process")
            return True
        
        # Step 1: Clean up old database files
        self.cleanup_manager.cleanup_database_files()
        
        # Step 2: Authoritative cleanup before database generation
        logger.info("Executing authoritative cleanup before database generation...")
        self.cleanup_manager.revalidate_output_dir_before_database(self.allowlist)
        
        # Step 3: Generate repository database
        logger.info("Generating repository database...")
        db_success = self.database_manager.generate_full_database(
            self.repo_name,
            self.output_dir,
            self.cleanup_manager
        )
        self.gate_state['database_success'] = db_success
        
        if not db_success:
            logger.error("Failed to generate repository database")
            self._run_safe_operations_only()
            return False
        
        # Step 4: Sign repository files if GPG enabled
        signature_success = True
        if self.gpg_handler.gpg_enabled:
            logger.info("Signing repository database files...")
            signature_success = self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir))
            self.gate_state['signature_success'] = signature_success
        
        if not signature_success and self.gpg_handler.gpg_enabled:
            logger.warning("Repository signature failed, but continuing...")
        
        # Step 5: STAGING PUBLISH
        # 5a: Collect all files to upload
        files_to_upload = []
        for pattern in ["*.pkg.tar.*", f"{self.repo_name}.*"]:
            files_to_upload.extend(self.output_dir.glob(pattern))
        
        if not files_to_upload:
            logger.error("No files to upload")
            self.gate_state['upload_success'] = False
            self._run_safe_operations_only()
            return False
        
        # 5b: Generate unique run ID and staging path
        run_id = self._generate_run_id()
        staging_path = f"{self.remote_dir}/.staging/{run_id}"
        logger.info(f"STAGING_RUN_ID={run_id} path={staging_path}")
        
        # 5c: Ensure staging directory exists on VPS
        if not self.ssh_client.ensure_staging_dir(run_id):
            logger.error("Failed to create staging directory on VPS")
            self.gate_state['upload_success'] = False
            self._run_safe_operations_only()
            return False
        
        # 5d: Upload all files to staging directory
        upload_success = self.rsync_client.upload_files(
            [str(f) for f in files_to_upload],
            self.output_dir,
            self.cleanup_manager,
            remote_path=staging_path
        )
        
        # 5e: PRE‑PROMOTE VERIFICATION (P0)
        promotion_success = False
        if upload_success:
            expected_basenames = {f.name for f in files_to_upload}
            verify_ok, missing_files = self.ssh_client.verify_upload(expected_basenames, remote_path=staging_path)
            
            if not verify_ok:
                logger.error(f"STAGING_VERIFY_FAIL: missing {len(missing_files)} files, promotion aborted. Staging left for debugging.")
                self.gate_state['upload_success'] = False
                self.gate_state['up3_success'] = False
                self._run_safe_operations_only()
                return False
            
            logger.info(f"Upload to staging verified. All {len(expected_basenames)} files present.")
            
            # 5f: Promote staging to live (with remote lock)
            logger.info(f"Promoting staging -> live...")
            promotion_success = self.ssh_client.promote_staging(run_id)
            self.gate_state['promotion_success'] = promotion_success
            
            if not promotion_success:
                logger.error(f"Staging promotion FAILED. Staging directory left at {staging_path} for debugging.")
                # Keep staging dir, do not delete; exit with error later
        else:
            logger.error("Upload to staging failed. Promotion aborted.")
        
        # 5g: Overall upload success = upload succeeded AND promotion succeeded
        overall_upload_success = upload_success and promotion_success
        self.gate_state['upload_success'] = overall_upload_success
        
        # 5h: Post‑promotion verification (UP3)
        up3_success = False
        if overall_upload_success:
            # Verify that all expected files are now present in live remote_dir
            expected_basenames = {f.name for f in files_to_upload}
            verify_ok, missing_files = self.ssh_client.verify_upload(expected_basenames, self.remote_dir)
            up3_success = verify_ok
            self.gate_state['up3_success'] = up3_success
            
            if not up3_success:
                logger.error("UP3 POST-UPLOAD VERIFICATION FAILED: missing files after promotion")
                # Exit with error later; staging dir already removed
        else:
            logger.error("Overall upload/promotion failed; skipping UP3 verification")
        
        # 5i: Permission normalization (only if overall success)
        if overall_upload_success and up3_success:
            if not self.ssh_client.normalize_permissions():
                logger.error("VPS permission normalization failed, aborting pipeline")
                self.gate_state['upload_success'] = False
                self.gate_state['up3_success'] = False
                self._run_safe_operations_only()
                return False
        else:
            logger.warning("Skipping permission normalization due to upload/promotion failure")
        
        # Step 6: VPS orphan signature sweep (ALWAYS RUN - SAFE)
        logger.info("Running VPS orphan signature sweep (safe operation)...")
        package_count, signature_count, orphaned_count = self.cleanup_manager.cleanup_vps_orphaned_signatures()
        logger.info(f"VPS orphan sweep complete: {package_count} packages, {signature_count} signatures, deleted {orphaned_count} orphans")
        
        # Step 7: Evaluate gates and conditionally run VPS version prune
        version_prune_allowed = self._evaluate_gates()
        
        if version_prune_allowed:
            logger.info("All gates passed - running STRICT VPS version prune...")
            self.cleanup_manager.version_prune_vps(self.version_tracker, self.desired_inventory)
        else:
            logger.info("Gates blocked VPS version prune")
        
        # Step 8: Run Hokibot action (non-blocking)
        if self.build_tracker.hokibot_data:
            logger.info("Running Hokibot action phase (non-blocking)...")
            try:
                hokibot_result = self.hokibot_runner.run(self.build_tracker.hokibot_data)
                logger.info(f"Hokibot result: {hokibot_result}")
            except Exception as e:
                logger.warning(f"Hokibot action failed (non-blocking): {e}")
        else:
            logger.info("No hokibot data to process")
        
        # Return overall success (upload/promotion/verification all succeeded)
        return overall_upload_success and up3_success
    
    def _run_safe_operations_only(self):
        """Run only safe operations when gates block destructive cleanup."""
        logger.info("Running safe operations only (orphan signature sweep)...")
        package_count, signature_count, orphaned_count = self.cleanup_manager.cleanup_vps_orphaned_signatures()
        logger.info(f"Safe operations complete: {package_count} packages, {signature_count} signatures, deleted {orphaned_count} orphans")
    
    def run(self) -> int:
        """Main execution flow WITH STAGING PUBLISH AND NON-BLOCKING HOKIBOT + SAFETY UPGRADES"""
        logger.info("ARCH LINUX PACKAGE BUILDER - MODULAR ORCHESTRATION WITH STAGING PUBLISH + SAFETY UPGRADES")
        
        try:
            # Import GPG key if enabled
            if self.gpg_handler.gpg_enabled:
                logger.info("Initializing GPG...")
                if not self.gpg_handler.import_gpg_key():
                    logger.warning("GPG key import failed, continuing without signing")
            
            # Phase I: VPS Sync
            if not self.phase_i_vps_sync():
                logger.error("Phase I failed")
                return 1
            
            # Phase II: Dynamic Allowlist
            if not self.phase_ii_dynamic_allowlist():
                logger.error("Phase II failed")
                return 1
            
            # Phase IV: Version Audit & Build
            built_packages, skipped_packages = self.phase_iv_version_audit_and_build()
            
            # Phase V: Sign and Update (with staging publish)
            if built_packages or list(self.output_dir.glob("*.pkg.tar.*")):
                if not self.phase_v_sign_and_update():
                    logger.error("Phase V failed or gates blocked operations")
                    return 1
            else:
                logger.info("All packages are up-to-date")
                self._run_safe_operations_only()
            
            # Summary with gate status
            logger.info("BUILD SUMMARY WITH GATE STATUS")
            logger.info(f"Repository: {self.repo_name}")
            logger.info(f"Packages built: {self.gate_state['packages_built']}")
            logger.info(f"Packages skipped: {len(self.skipped_packages)}")
            logger.info(f"Allowlist entries: {len(self.allowlist)}")
            logger.info(f"Desired inventory: {len(self.desired_inventory)}")
            logger.info(f"VPS files after cleanup: {len(self.vps_files)}")
            logger.info("GATE STATES:")
            logger.info(f"  Database success: {self.gate_state['database_success']}")
            logger.info(f"  Signature success: {self.gate_state['signature_success']}")
            logger.info(f"  Upload success: {self.gate_state['upload_success']}")
            logger.info(f"  Promotion success: {self.gate_state['promotion_success']}")
            logger.info(f"  UP3 success: {self.gate_state['up3_success']}")
            logger.info(f"  Destructive cleanup allowed: {self.gate_state['destructive_cleanup_allowed']}")
            logger.info(f"Package signing: {'Enabled' if self.sign_packages else 'Disabled'}")
            logger.info(f"GPG signing: {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            
            logger.info(f"PACMAN_POST_REPO_ENABLE_SY_COUNT={self.post_repo_enable_sy_count}")
            
            if self.built_packages:
                logger.info("Newly built packages:")
                for pkg in self.built_packages:
                    logger.info(f"  - {pkg}")
            
            logger.info("Build completed successfully!")
            return 0
            
        except Exception as e:
            logger.error(f"Build failed: {e}")
            import traceback
            traceback.print_exc()
            return 1
        finally:
            # Cleanup GPG
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()


def main():
    """Main entry point"""
    orchestrator = PackageBuilderOrchestrator()
    return orchestrator.run()


if __name__ == "__main__":
    sys.exit(main())