"""
Main Orchestration Script for Arch Linux Package Builder
WITH FAIL-SAFE GATES
"""

import os
import sys
import logging
import subprocess
import tempfile
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
    
    MODULES_LOADED = True
except ImportError as e:
    logger.error(f"Failed to import modules: {e}")
    MODULES_LOADED = False
    sys.exit(1)


class PackageBuilderOrchestrator:
    """Main orchestrator coordinating all phases WITH FAIL-SAFE GATES"""
    
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
        self.vps_packages = []  # NEW: Separate list for package files only
        self.allowlist = set()
        self.built_packages = []
        self.skipped_packages = []
        self.desired_inventory = set()  # NEW: Desired inventory for cleanup guard
        
        # GATE STATE TRACKING
        self.gate_state = {
            'packages_built': 0,
            'database_success': False,
            'signature_success': False,
            'upload_success': False,
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
        
        # AUTHORITATIVE: CleanupManager handles all cleanup, SmartCleanup is internal helper
        # Do NOT instantiate SmartCleanup here - let CleanupManager use it internally
        
        # Build modules
        self.artifact_manager = ArtifactManager()
        self.build_tracker = BuildTracker()
        
        # GPG Handler
        self.gpg_handler = GPGHandler(self.sign_packages)
        
        # Shell executor
        self.shell_executor = ShellExecutor(self.debug_mode)
        
        # Package builder - initialized without vps_files first, will be set in phase_i_vps_sync
        self.package_builder = create_package_builder(
            packager_id=self.packager_id,
            output_dir=self.output_dir,
            gpg_key_id=self.gpg_key_id,
            gpg_private_key=self.gpg_private_key,
            sign_packages=self.sign_packages,
            debug_mode=self.debug_mode,
            version_tracker=self.version_tracker  # Pass version tracker
        )
        
        logger.info("All modules initialized successfully")
    
    def _run_post_repo_enable_pacman_sy(self) -> bool:
        """
        Run post-repo-enable pacman -Sy with exactly-once proof logging.
        
        Returns:
            True if executed or skipped appropriately, False if blocked due to already ran
        """
        # Block if already ran
        if self.post_repo_enable_sy_ran:
            logger.info("PACMAN_POST_REPO_ENABLE_SY: BLOCKED (already_ran=true)")
            return False
        
        # Check if repository has packages to determine if sync is needed
        has_packages = len(self.vps_packages) > 0
        
        if not has_packages:
            logger.info("PACMAN_POST_REPO_ENABLE_SY: SKIP (reason=no_packages_in_repo)")
            return True
        
        # Log start
        logger.info(f"PACMAN_POST_REPO_ENABLE_SY: START (count_before={self.post_repo_enable_sy_count})")
        
        try:
            # Run the command
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
                # Even on failure, mark as ran to prevent retries
                self.post_repo_enable_sy_ran = True
                logger.error(f"PACMAN_POST_REPO_ENABLE_SY: FAILED (error={result.stderr[:200]})")
                return False
                
        except subprocess.TimeoutExpired:
            self.post_repo_enable_sy_ran = True
            logger.error("PACMAN_POST_REPO_ENABLE_SY: TIMEOUT")
            return False
        except Exception as e:
            self.post_repo_enable_sy_ran = True
            logger.error(f"PACMAN_POST_REPO_ENABLE_SY: EXCEPTION (error={e})")
            return False
    
    def _evaluate_gates(self):
        """
        Evaluate fail-safe gates and determine if destructive cleanup is allowed.
        
        G1: Empty-run gate - skip destructive cleanup if no packages built
        G2: Partial-failure gate - only allow destructive cleanup if:
            a) repo database generation succeeded AND
            b) repo signature succeeded AND  
            c) rsync upload succeeded
        """
        # G1: Empty-run gate
        if self.gate_state['packages_built'] == 0:
            logger.info("GATE: empty-run (built=0) -> skipping destructive VPS deletions")
            self.gate_state['destructive_cleanup_allowed'] = False
            return False
        
        # G2: Partial-failure gate
        if (self.gate_state['database_success'] and 
            self.gate_state['signature_success'] and
            self.gate_state['upload_success']):
            self.gate_state['destructive_cleanup_allowed'] = True
            return True
        else:
            logger.info("GATE: partial failure -> skipping destructive VPS deletions")
            self.gate_state['destructive_cleanup_allowed'] = False
            return False
    
    def phase_i_vps_sync(self) -> bool:
        """
        Phase I: VPS State Fetch
        - List VPS repo files
        - Sync missing files locally
        """
        logger.info("PHASE I: VPS State Fetch")
        
        # Test SSH connection
        if not self.ssh_client.test_ssh_connection():
            logger.warning("SSH connection test failed")
        
        # Ensure remote directory exists
        self.ssh_client.ensure_remote_directory()
        
        # List remote packages
        remote_packages = self.ssh_client.list_remote_packages()
        self.vps_packages = remote_packages  # Already basenames, ONLY package files
        
        # NEW: Also get signatures for completeness check (separate list)
        remote_signatures = self._get_vps_signatures()
        
        # Combine for completeness checks (but keep separate for mirror sync)
        self.vps_files = self.vps_packages + remote_signatures
        
        logger.info(f"Found {len(self.vps_packages)} package files and {len(remote_signatures)} signatures on VPS")
        
        # Run post-repo-enable pacman -Sy if repository has packages
        if not self._run_post_repo_enable_pacman_sy():
            logger.warning("Post-repo-enable pacman -Sy was blocked or failed")
        
        # Set VPS files in package builder for completeness checks
        self.package_builder.set_vps_files(self.vps_files)
        
        # Mirror remote packages locally (PACKAGE FILES ONLY)
        if self.vps_packages:
            logger.info("Mirroring remote packages locally (package files only)...")
            success = self.rsync_client.mirror_remote_packages(
                self.mirror_temp_dir,
                self.output_dir,
                self.vps_packages  # Pass ONLY package files, no signatures
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
            logger.error(f"SSH key not found")
            return []
        
        # Get signature files - FIX: include both regular files and symlinks
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
            logger.error(f"SSH command for signatures failed: {e}")
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
        """
        Phase II: Dynamic Allowlist (Manifest)
        - Iterate over packages.py entries
        - Load PKGBUILD (AUR or local)
        - Extract all pkgname values
        - Build full allowlist of valid package filenames
        """
        logger.info("PHASE II: Dynamic Allowlist Generation")
        
        local_packages, aur_packages = self.get_package_lists()
        
        # Collect all package sources
        package_sources = []
        
        # Add local packages
        for pkg in local_packages:
            pkg_dir = self.repo_root / pkg
            if pkg_dir.exists():
                package_sources.append(str(pkg_dir))
            else:
                logger.warning(f"Local package directory not found: {pkg}")
        
        # Add AUR packages
        for pkg in aur_packages:
            package_sources.append(pkg)  # AUR package names
        
        # Build allowlist using ManifestFactory
        logger.info(f"Processing {len(package_sources)} package sources...")
        self.allowlist = ManifestFactory.build_allowlist(package_sources)
        
        # NEW: Build desired inventory from PKGBUILDs
        self.desired_inventory = self._build_desired_inventory(package_sources)
        logger.info(f"Desired inventory package names: {len(self.desired_inventory)}")
        if self.desired_inventory:
            first_ten = list(self.desired_inventory)[:10]
            logger.info(f"First 10 names: {first_ten}")
        
        logger.info(f"Allowlist generated: {len(self.allowlist)} package names")
        
        return len(self.allowlist) > 0
    
    def _build_desired_inventory(self, package_sources: List[str]) -> Set[str]:
        """
        Build desired inventory set from all PKGBUILDs.
        This includes ALL pkgname entries from multi-package PKGBUILDs.
        
        Args:
            package_sources: List of package sources (local paths or AUR names)
            
        Returns:
            Set of all package names that should exist in the repository
        """
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
        """
        Phase IV: Version Audit & Build
        - Compare PKGBUILD version vs mirror version
        - Build only if source is newer
        """
        logger.info("PHASE IV: Version Audit & Build")
        
        local_packages, aur_packages = self.get_package_lists()
        
        # Prepare package lists with remote versions
        local_packages_with_versions = []
        aur_packages_with_versions = []
        
        # Process local packages
        for pkg_name in local_packages:
            pkg_dir = self.repo_root / pkg_name
            if pkg_dir.exists():
                remote_version = self.version_tracker.get_remote_version(pkg_name, self.vps_files)
                local_packages_with_versions.append((pkg_dir, remote_version))
            else:
                logger.warning(f"Local package directory not found: {pkg_name}")
        
        # Process AUR packages
        for pkg_name in aur_packages:
            remote_version = self.version_tracker.get_remote_version(pkg_name, self.vps_files)
            aur_packages_with_versions.append((pkg_name, remote_version))
        
        # NEW: Set desired inventory in version tracker for cleanup guard
        self.version_tracker.set_desired_inventory(self.desired_inventory)
        
        # Batch audit and build
        built_packages, skipped_packages, failed_packages = (
            self.package_builder.batch_audit_and_build(
                local_packages=local_packages_with_versions,
                aur_packages=aur_packages_with_versions,
                aur_build_dir=self.aur_build_dir
            )
        )
        
        # Update state and gate tracking
        self.built_packages = built_packages
        self.skipped_packages = skipped_packages
        self.gate_state['packages_built'] = len(built_packages)
        
        # Log results
        logger.info(f"Build Results:")
        logger.info(f"   Built: {len(built_packages)} packages")
        logger.info(f"   Skipped: {len(skipped_packages)} packages")
        logger.info(f"   Failed: {len(failed_packages)} packages")
        
        if failed_packages:
            logger.error(f"Failed packages: {failed_packages}")
        
        return built_packages, skipped_packages
    
    def phase_v_sign_and_update(self) -> bool:
        """
        Phase V: Sign and Update WITH FAIL-SAFE GATES
        - Sign new packages
        - Update repository database
        - Upload to VPS with proper cleanup
        """
        logger.info("PHASE V: Sign and Update WITH FAIL-SAFE GATES")
        
        # Check if we have any packages to process
        local_packages = list(self.output_dir.glob("*.pkg.tar.*"))
        if not local_packages:
            logger.info("No packages to process")
            return True
        
        # Step 1: Clean up old database files
        self.cleanup_manager.cleanup_database_files()
        
        # Step 2: AUTHORITATIVE CLEANUP: Revalidate output_dir before database generation
        logger.info("Executing authoritative cleanup before database generation...")
        self.cleanup_manager.revalidate_output_dir_before_database(self.allowlist)
        
        # Step 3: Generate repository database (track for G2)
        logger.info("Generating repository database...")
        
        # CRITICAL: Pass allowlist to database_manager so it can call CleanupManager
        db_success = self.database_manager.generate_full_database(
            self.repo_name,
            self.output_dir,
            self.cleanup_manager
        )
        self.gate_state['database_success'] = db_success
        
        if not db_success:
            logger.error("Failed to generate repository database")
            # Still proceed with orphan signature sweep (safe)
            self._run_safe_operations_only()
            return False
        
        # Step 4: Sign repository files if GPG enabled (track for G2)
        signature_success = True  # Default to success if signing disabled
        if self.gpg_handler.gpg_enabled:
            logger.info("Signing repository database files...")
            signature_success = self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir))
            self.gate_state['signature_success'] = signature_success
        
        if not signature_success and self.gpg_handler.gpg_enabled:
            logger.warning("Repository signature failed, but continuing...")
        
        # Step 5: Upload to VPS with --delete to ensure VPS matches local state (track for G2)
        logger.info("Uploading packages and database to VPS...")
        
        # Collect all files to upload
        files_to_upload = []
        for pattern in ["*.pkg.tar.*", f"{self.repo_name}.*"]:
            files_to_upload.extend(self.output_dir.glob(pattern))
        
        if not files_to_upload:
            logger.error("No files to upload")
            self.gate_state['upload_success'] = False
            self._run_safe_operations_only()
            return False
        
        # Upload using Rsync WITH --delete to remove VPS files not present locally
        upload_success = self.rsync_client.upload_files(
            [str(f) for f in files_to_upload],
            self.output_dir,
            self.cleanup_manager
        )
        
        # NEW: UP3 POST-UPLOAD VERIFICATION
        if upload_success:
            upload_success = self._up3_verify_upload_completeness(files_to_upload)
        
        self.gate_state['upload_success'] = upload_success
        
        if not upload_success:
            logger.error("Failed to upload files to VPS")
            self._run_safe_operations_only()
            return False
        
        # Step 5.5: VPS orphan signature sweep (ALWAYS RUN - SAFE)
        logger.info("Running VPS orphan signature sweep (safe operation)...")
        package_count, signature_count, orphaned_count = self.cleanup_manager.cleanup_vps_orphaned_signatures()
        logger.info(f"VPS orphan sweep complete: {package_count} packages, {signature_count} signatures, deleted {orphaned_count} orphans")
        
        # Step 6: Evaluate gates and conditionally run destructive cleanup
        destructive_allowed = self._evaluate_gates()
        
        if destructive_allowed:
            logger.info("All gates passed - running destructive VPS cleanup...")
            self.cleanup_manager.server_cleanup(self.version_tracker, self.desired_inventory)
        else:
            logger.info("Gates blocked destructive VPS cleanup")
        
        return upload_success
    
    def _up3_verify_upload_completeness(self, uploaded_files: List[Path]) -> bool:
        """
        UP3 POST-UPLOAD VERIFICATION: Verify all uploaded artifacts exist on VPS
        
        Args:
            uploaded_files: List of local file paths that were uploaded
            
        Returns:
            True if all uploaded files are present on VPS, False otherwise
        """
        logger.info("UP3: Starting post-upload VPS verification...")
        
        # Get basenames of uploaded files
        expected_basenames = {f.name for f in uploaded_files}
        
        # Fetch fresh VPS inventory (packages + signatures + repo DB/files) - FIX: include symlinks
        vps_packages = self.ssh_client.list_remote_packages()
        vps_signatures = self._get_vps_signatures()
        vps_db_files = self._get_vps_database_files()
        
        # Combine all VPS files
        vps_all_files = set(vps_packages + vps_signatures + vps_db_files)
        
        # Check for missing files
        missing_files = expected_basenames - vps_all_files
        
        if not missing_files:
            logger.info(f"UP3 OK: all uploaded artifacts present on VPS (expected={len(expected_basenames)}, missing=0)")
            return True
        else:
            missing_list = list(missing_files)
            # Limit to first 20 for logging
            missing_display = missing_list[:20]
            logger.error(f"UP3 FAIL: missing on VPS (expected={len(expected_basenames)}, missing={len(missing_files)}) missing: {', '.join(missing_display)}")
            return False
    
    def _get_vps_database_files(self) -> List[str]:
        """Get database files from VPS - FIX: include both regular files and symlinks"""
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found")
            return []
        
        # Get database files - FIX: include both regular files and symlinks
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            rf'find "{self.remote_dir}" -maxdepth 1 \( -type f -o -type l \) \( -name "{self.repo_name}.db*" -o -name "{self.repo_name}.files*" \) -printf "%f\\n" 2>/dev/null || echo "NO_FILES"'
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
                return files
            else:
                logger.warning(f"SSH find for database files returned error")
                return []
                
        except Exception as e:
            logger.error(f"SSH command for database files failed: {e}")
            return []
    
    def _run_safe_operations_only(self):
        """
        Run only safe operations when gates block destructive cleanup.
        Currently only orphan signature sweep is considered safe.
        """
        logger.info("Running safe operations only (orphan signature sweep)...")
        package_count, signature_count, orphaned_count = self.cleanup_manager.cleanup_vps_orphaned_signatures()
        logger.info(f"Safe operations complete: {package_count} packages, {signature_count} signatures, deleted {orphaned_count} orphans")
    
    def run(self) -> int:
        """Main execution flow WITH FAIL-SAFE GATES"""
        logger.info("ARCH LINUX PACKAGE BUILDER - MODULAR ORCHESTRATION WITH FAIL-SAFE GATES")
        
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
            
            # Phase V: Sign and Update (with gates)
            if built_packages or list(self.output_dir.glob("*.pkg.tar.*")):
                if not self.phase_v_sign_and_update():
                    logger.error("Phase V failed or gates blocked operations")
            else:
                logger.info("All packages are up-to-date")
                # Still run safe operations
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
            logger.info(f"  Destructive cleanup allowed: {self.gate_state['destructive_cleanup_allowed']}")
            logger.info(f"Package signing: {'Enabled' if self.sign_packages else 'Disabled'}")
            logger.info(f"GPG signing: {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            
            # Print post-repo-enable pacman -Sy count
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