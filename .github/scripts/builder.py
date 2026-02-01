"""
Main Orchestration Script for Arch Linux Package Builder
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
    """Main orchestrator coordinating all phases"""
    
    def __init__(self):
        """Initialize orchestrator with all modules"""
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
        self.allowlist = set()
        self.built_packages = []
        self.skipped_packages = []
        
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
        self.smart_cleanup = SmartCleanup(self.repo_name, self.output_dir)
        
        # Build modules
        self.artifact_manager = ArtifactManager()
        self.build_tracker = BuildTracker()
        
        # GPG Handler
        self.gpg_handler = GPGHandler(self.sign_packages)
        
        # Shell executor
        self.shell_executor = ShellExecutor(self.debug_mode)
        
        # Package builder
        self.package_builder = create_package_builder(
            packager_id=self.packager_id,
            output_dir=self.output_dir,
            gpg_key_id=self.gpg_key_id,
            gpg_private_key=self.gpg_private_key,
            sign_packages=self.sign_packages,
            debug_mode=self.debug_mode
        )
        
        logger.info("All modules initialized successfully")
    
    def _apply_repository_state(self, exists: bool, has_packages: bool):
        """Apply repository state with proper SigLevel based on discovery"""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found")
            return
        
        try:
            with open(pacman_conf, 'r') as f:
                content = f.read()
            
            repo_section = f"[{self.repo_name}]"
            lines = content.split('\n')
            new_lines = []
            
            # Remove old section if it exists
            in_section = False
            for line in lines:
                # Check if we're entering our section
                if line.strip() == repo_section or line.strip() == f"#{repo_section}":
                    in_section = True
                    continue
                elif in_section and (line.strip().startswith('[') or line.strip() == ''):
                    # We're leaving our section
                    in_section = False
                
                if not in_section:
                    new_lines.append(line)
            
            # Add new section if repository exists on VPS AND we have a server URL
            if exists and self.repo_server_url and self.repo_server_url.strip():
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                new_lines.append(f"# Automatically enabled - found on VPS")
                new_lines.append(repo_section)
                if has_packages:
                    new_lines.append("SigLevel = Optional TrustAll")
                    logger.info(f"Enabling repository '{self.repo_name}' with Server URL")
                else:
                    new_lines.append("# SigLevel = Optional TrustAll")
                    new_lines.append("# Repository exists but has no packages yet")
                    logger.info("Repository section added but commented (no packages yet)")
                
                # ADD THE SERVER LINE - THIS IS CRITICAL
                new_lines.append(f"Server = {self.repo_server_url}")
                new_lines.append('')
            else:
                # Repository doesn't exist on VPS or no server URL, add commented section
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                if not exists:
                    new_lines.append(f"# Disabled - not found on VPS (first run?)")
                elif not self.repo_server_url or not self.repo_server_url.strip():
                    new_lines.append(f"# Disabled - no server URL configured")
                new_lines.append(f"#{repo_section}")
                new_lines.append("#SigLevel = Optional TrustAll")
                if self.repo_server_url and self.repo_server_url.strip():
                    new_lines.append(f"#Server = {self.repo_server_url}")
                new_lines.append('')
                
                if not self.repo_server_url or not self.repo_server_url.strip():
                    logger.warning("Repository exists on VPS but no REPO_SERVER_URL configured - keeping disabled")
                else:
                    logger.info("Repository not found on VPS - keeping disabled")
            
            # Write back to pacman.conf
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write('\n'.join(new_lines))
                temp_path = temp_file.name
            
            # Copy to pacman.conf
            subprocess.run(['sudo', 'cp', temp_path, str(pacman_conf)], check=False)
            subprocess.run(['sudo', 'chmod', '644', str(pacman_conf)], check=False)
            os.unlink(temp_path)
            
            logger.info(f"Updated pacman.conf for repository '{self.repo_name}'")
            
        except Exception as e:
            logger.error(f"Failed to apply repository state: {e}")
    
    def _sync_pacman_databases(self):
        """Sync pacman databases after enabling repository"""
        # First, ensure pacman-key is initialized
        logger.info("Initializing pacman-key database...")
        cmd = "sudo pacman-key --init && sudo pacman-key --populate"
        result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
        
        # Update pacman-key database
        logger.info("Updating pacman-key database...")
        cmd = "sudo pacman-key --updatedb"
        result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
        
        # Now sync pacman databases
        logger.info("Synchronizing pacman databases...")
        cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
        
        if result.returncode == 0:
            logger.info("Pacman databases synchronized successfully")
            return True
        else:
            logger.warning(f"Pacman sync warning: {result.stderr[:200]}")
            
            # Try without LC_ALL setting
            logger.info("Retrying pacman sync without LC_ALL...")
            cmd = "sudo pacman -Sy --noconfirm"
            result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
            
            if result.returncode == 0:
                logger.info("Pacman databases synchronized successfully")
                return True
            else:
                logger.error(f"Pacman sync failed: {result.stderr[:500]}")
                return False
    
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
    
    def phase_i_vps_sync(self) -> bool:
        """
        Phase I: VPS State Fetch
        - List VPS repo files
        - Sync missing files locally
        - CRITICAL FIX: Apply repository state and update pacman database
        """
        logger.info("PHASE I: VPS State Fetch")
        
        # Test SSH connection
        if not self.ssh_client.test_ssh_connection():
            logger.warning("SSH connection test failed")
        
        # Ensure remote directory exists
        self.ssh_client.ensure_remote_directory()
        
        # List remote packages
        remote_files = self.ssh_client.list_remote_packages()
        self.vps_files = remote_files  # Already basenames
        
        logger.info(f"Found {len(self.vps_files)} files on VPS")
        
        # CRITICAL FIX: Apply repository state BEFORE mirroring
        exists, has_packages = self.ssh_client.check_repository_exists_on_vps()
        self._apply_repository_state(exists, has_packages)
        
        # CRITICAL FIX: Update pacman database after enabling repository
        if exists and self.repo_server_url and self.repo_server_url.strip():
            logger.info("Updating pacman database after enabling repository...")
            if not self._sync_pacman_databases():
                logger.warning("Pacman database sync failed, but continuing")
        
        # Mirror remote packages locally
        if remote_files:
            logger.info("Mirroring remote packages locally...")
            success = self.rsync_client.mirror_remote_packages(
                self.mirror_temp_dir,
                self.output_dir,
                remote_files  # Pass the list of basenames
            )
            if not success:
                logger.warning("Failed to mirror remote packages")
                return False
        
        return True
    
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
        
        logger.info(f"Allowlist generated: {len(self.allowlist)} package names")
        
        return len(self.allowlist) > 0
    
    def phase_iii_smart_cleanup(self) -> bool:
        """
        Phase III: Smart Cleanup
        - Compare VPS files with allowlist
        - Delete only files NOT present in allowlist
        - Remove deleted files from repo database
        """
        logger.info("PHASE III: Smart Cleanup (Allowlist-based)")
        
        if not self.vps_files:
            logger.info("No VPS files to clean up")
            return True
        
        # Execute smart cleanup
        success, deleted_files = self.smart_cleanup.execute_cleanup(
            vps_files=self.vps_files,
            allowlist=self.allowlist,
            remote_dir=self.remote_dir,
            vps_user=self.vps_user,
            vps_host=self.vps_host,
            repo_db_path=self.output_dir / f"{self.repo_name}.db.tar.gz"
        )
        
        # Update VPS files list after cleanup
        if deleted_files:
            deleted_set = set(deleted_files)
            self.vps_files = [f for f in self.vps_files if f not in deleted_set]
            logger.info(f"VPS files after cleanup: {len(self.vps_files)}")
        
        return success
    
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
        
        # Batch audit and build
        built_packages, skipped_packages, failed_packages = (
            self.package_builder.batch_audit_and_build(
                local_packages=local_packages_with_versions,
                aur_packages=aur_packages_with_versions,
                aur_build_dir=self.aur_build_dir
            )
        )
        
        # Update state
        self.built_packages = built_packages
        self.skipped_packages = skipped_packages
        
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
        Phase V: Sign and Update
        - Sign new packages
        - Update repository database
        - Upload to VPS
        """
        logger.info("PHASE V: Sign and Update")
        
        # Check if we have any packages to process
        local_packages = list(self.output_dir.glob("*.pkg.tar.*"))
        if not local_packages:
            logger.info("No packages to process")
            return True
        
        # Step 1: Sign all unsigned packages if signing is enabled
        if self.sign_packages and self.gpg_handler.gpg_enabled:
            logger.info("Signing all unsigned packages...")
            signed_count = 0
            for pkg_file in local_packages:
                # Check if signature exists
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if not sig_file.exists():
                    if self.gpg_handler.sign_package(str(pkg_file)):
                        signed_count += 1
            if signed_count > 0:
                logger.info(f"Signed {signed_count} previously unsigned packages")
        
        # Step 2: Generate repository database
        logger.info("Generating repository database...")
        
        # CRITICAL: Zero-Residue cleanup before database generation
        self.cleanup_manager.revalidate_output_dir_before_database()
        
        # Generate database
        db_success = self.database_manager.generate_full_database(
            self.repo_name,
            self.output_dir,
            self.cleanup_manager
        )
        
        if not db_success:
            logger.error("Failed to generate repository database")
            return False
        
        # Step 3: Sign repository files if GPG enabled
        if self.gpg_handler.gpg_enabled:
            logger.info("Signing repository database files...")
            self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir))
        
        # Step 4: Upload to VPS
        logger.info("Uploading packages and database to VPS...")
        
        # Collect all files to upload
        files_to_upload = []
        for pattern in ["*.pkg.tar.*", f"{self.repo_name}.*"]:
            files_to_upload.extend(self.output_dir.glob(pattern))
        
        if not files_to_upload:
            logger.error("No files to upload")
            return False
        
        # Upload using Rsync
        upload_success = self.rsync_client.upload_files(
            [str(f) for f in files_to_upload],
            self.output_dir
        )
        
        if not upload_success:
            logger.error("Failed to upload files to VPS")
            return False
        
        # Step 5: Final server cleanup with version tracker
        logger.info("Final server cleanup...")
        self.cleanup_manager.server_cleanup(self.version_tracker)
        
        return True
    
    def run(self) -> int:
        """Main execution flow"""
        logger.info("ARCH LINUX PACKAGE BUILDER - MODULAR ORCHESTRATION")
        
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
            
            # Phase III: Smart Cleanup (using PKGBUILD-derived allowlist)
            if not self.phase_iii_smart_cleanup():
                logger.warning("Phase III had issues, but continuing")
            
            # Phase IV: Version Audit & Build
            built_packages, skipped_packages = self.phase_iv_version_audit_and_build()
            
            # Phase V: Sign and Update
            if built_packages or list(self.output_dir.glob("*.pkg.tar.*")):
                if not self.phase_v_sign_and_update():
                    logger.error("Phase V failed")
                    return 1
            else:
                logger.info("All packages are up-to-date")
            
            # Summary
            logger.info("BUILD SUMMARY")
            logger.info(f"Repository: {self.repo_name}")
            logger.info(f"Packages built: {len(built_packages)}")
            logger.info(f"Packages skipped: {len(skipped_packages)}")
            logger.info(f"Allowlist entries: {len(self.allowlist)}")
            logger.info(f"VPS files after cleanup: {len(self.vps_files)}")
            logger.info(f"Package signing: {'Enabled' if self.sign_packages else 'Disabled'}")
            logger.info(f"GPG signing: {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            
            if built_packages:
                logger.info("Newly built packages:")
                for pkg in built_packages:
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
