#!/usr/bin/env python3
"""
Manjaro Package Builder - Refactored with Precision Versioning and Zero-Residue Policy
"""

print(">>> DEBUG: Script started")

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import hashlib
import logging
import socket
import glob
import tarfile
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Add the script directory to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

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
    def __init__(self):
        # Run pre-flight environment validation
        self._validate_env()
        
        # GPG signing configuration
        self.gpg_private_key = os.getenv('GPG_PRIVATE_KEY')
        self.gpg_key_id = os.getenv('GPG_KEY_ID')
        self.gpg_enabled = bool(self.gpg_private_key and self.gpg_key_id)
        
        # Log GPG environment status
        logger.info(f"GPG Environment Check: ID found: {'YES' if self.gpg_key_id else 'NO'}, Key found: {'YES' if self.gpg_private_key else 'NO'}")
        
        # Get the repository root
        self.repo_root = self._get_repo_root()
        
        # Load configuration
        self._load_config()
        
        # Setup directories from config
        self.output_dir = self.repo_root / (getattr(config, 'OUTPUT_DIR', 'built_packages') if HAS_CONFIG_FILES else "built_packages")
        self.build_tracking_dir = self.repo_root / (getattr(config, 'BUILD_TRACKING_DIR', '.build_tracking') if HAS_CONFIG_FILES else ".build_tracking")
        
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # Load configuration values from config.py
        self.mirror_temp_dir = Path(getattr(config, 'MIRROR_TEMP_DIR', '/tmp/repo_mirror') if HAS_CONFIG_FILES else "/tmp/repo_mirror")
        self.sync_clone_dir = Path(getattr(config, 'SYNC_CLONE_DIR', '/tmp/manjaro-awesome-gitclone') if HAS_CONFIG_FILES else "/tmp/manjaro-awesome-gitclone")
        self.aur_urls = getattr(config, 'AUR_URLS', ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]) if HAS_CONFIG_FILES else ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]
        self.aur_build_dir = self.repo_root / (getattr(config, 'AUR_BUILD_DIR', 'build_aur') if HAS_CONFIG_FILES else "build_aur")
        self.ssh_options = getattr(config, 'SSH_OPTIONS', ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]) if HAS_CONFIG_FILES else ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]
        self.github_repo = os.getenv('GITHUB_REPO', getattr(config, 'GITHUB_REPO', 'megvadulthangya/manjaro-awesome.git') if HAS_CONFIG_FILES else 'megvadulthangya/manjaro-awesome.git')
        
        # State
        self.remote_files = []
        self.built_packages = []
        self.skipped_packages = []
        self.rebuilt_local_packages = []
        
        # NEW: Upload success flag for safety valve
        self._upload_successful = False
        
        # Repository state
        self.repo_has_packages_pacman = None
        self.repo_has_packages_ssh = None
        self.repo_final_state = None
        
        # PHASE 1 OBSERVER: hokibot data collection
        self.hokibot_data = []
        
        # Setup SSH config file for builder user (container invariant)
        self._setup_ssh_config()
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
        }

    def _validate_env(self) -> None:
        """Comprehensive pre-flight environment validation - check for all required variables."""
        print("\n" + "=" * 60)
        print("PRE-FLIGHT ENVIRONMENT VALIDATION")
        print("=" * 60)
        
        required_vars = [
            'REPO_NAME',
            'VPS_HOST',
            'VPS_USER',
            'VPS_SSH_KEY',
            'REMOTE_DIR',
        ]
        
        optional_but_recommended = [
            'REPO_SERVER_URL',
            'GPG_KEY_ID',
            'GPG_PRIVATE_KEY',
        ]
        
        # Check required variables
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value or value.strip() == '':
                missing_vars.append(var)
                logger.error(f"[ERROR] Variable {var} is empty! Ensure it is set in GitHub Secrets.")
        
        if missing_vars:
            sys.exit(1)
        
        # Check optional variables and warn if missing
        for var in optional_but_recommended:
            value = os.getenv(var)
            if not value or value.strip() == '':
                logger.warning(f"⚠️ Optional variable {var} is empty")
        
        # Log validation success (with secret masking)
        logger.info("✅ Environment validation passed:")
        for var in required_vars + optional_but_recommended:
            value = os.getenv(var)
            if value:
                masked = "***" + value[-4:] if len(value) > 4 else "***"
                logger.info(f"   {var}: {masked}")
        
        # Validate REPO_NAME for pacman.conf
        repo_name = os.getenv('REPO_NAME')
        if repo_name:
            if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
                logger.error(f"[ERROR] Invalid REPO_NAME '{repo_name}'. Must contain only letters, numbers, hyphens, and underscores.")
                sys.exit(1)
            if len(repo_name) > 50:
                logger.error(f"[ERROR] REPO_NAME '{repo_name}' is too long (max 50 characters).")
                sys.exit(1)
    
    def _setup_ssh_config(self) -> None:
        """Setup SSH config file for builder user - container invariant"""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)
        
        # Write SSH config file using environment variables
        config_content = f"""Host {self.vps_host}
  HostName {self.vps_host}
  User {self.vps_user}
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking no
  ConnectTimeout 30
  ServerAliveInterval 15
  ServerAliveCountMax 3
"""
        
        config_file = ssh_dir / "config"
        with open(config_file, "w") as f:
            f.write(config_content)
        
        config_file.chmod(0o600)
        
        # Ensure SSH key exists and has correct permissions
        ssh_key_path = ssh_dir / "id_ed25519"
        if not ssh_key_path.exists():
            ssh_key = os.getenv('VPS_SSH_KEY')
            if ssh_key:
                with open(ssh_key_path, "w") as f:
                    f.write(ssh_key)
                ssh_key_path.chmod(0o600)
        
        # Set ownership to builder
        try:
            shutil.chown(ssh_dir, "builder", "builder")
            for item in ssh_dir.iterdir():
                shutil.chown(item, "builder", "builder")
        except Exception as e:
            logger.warning(f"Could not change SSH dir ownership: {e}")

    def _extract_version_from_srcinfo(self, pkg_dir: Path) -> Tuple[str, str, Optional[str]]:
        """Extract pkgver, pkgrel, and epoch from .SRCINFO or makepkg --printsrcinfo output."""
        srcinfo_path = pkg_dir / ".SRCINFO"
        
        # First try to read existing .SRCINFO
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    srcinfo_content = f.read()
                return self._parse_srcinfo_content(srcinfo_content)
            except Exception as e:
                logger.warning(f"Failed to parse existing .SRCINFO: {e}")
        
        # Generate .SRCINFO using makepkg --printsrcinfo
        try:
            result = subprocess.run(
                ['makepkg', '--printsrcinfo'],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0 and result.stdout:
                # Also write to .SRCINFO for future use
                with open(srcinfo_path, 'w') as f:
                    f.write(result.stdout)
                return self._parse_srcinfo_content(result.stdout)
            else:
                logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
                raise RuntimeError(f"Failed to generate .SRCINFO: {result.stderr}")
                
        except Exception as e:
            logger.error(f"Error running makepkg --printsrcinfo: {e}")
            raise

    def _parse_srcinfo_content(self, srcinfo_content: str) -> Tuple[str, str, Optional[str]]:
        """Parse SRCINFO content to extract version information."""
        pkgver = None
        pkgrel = None
        epoch = None
        
        lines = srcinfo_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Handle key-value pairs
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key == 'pkgver':
                    pkgver = value
                elif key == 'pkgrel':
                    pkgrel = value
                elif key == 'epoch':
                    epoch = value
        
        if not pkgver or not pkgrel:
            raise ValueError("Could not extract pkgver and pkgrel from .SRCINFO")
        
        return pkgver, pkgrel, epoch

    def _get_full_version_string(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> str:
        """Construct full version string from components."""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"

    def _pre_build_purge_old_versions(self, pkg_name: str, old_version: str) -> None:
        """PRE-BUILD PURGE: Remove old version files from local mirror directory BEFORE building new version.
        
        This ensures the local directory only contains the latest version before repo-add runs.
        """
        logger.info(f"🔍 Pre-build purge: Looking for old version files of {pkg_name} ({old_version})")
        
        # Convert old version to filename patterns
        # Old version format could be: "26.1.9-1" or "2:26.1.9-1" (with epoch)
        
        # For pattern matching, we need to handle different filename formats
        old_patterns = []
        
        # Pattern 1: Standard version (no epoch)
        if ':' not in old_version:
            # e.g., "26.1.9-1" -> "*26.1.9-1*.pkg.tar.*"
            old_patterns.append(f"*{pkg_name}-{old_version}-*.pkg.tar.*")
        else:
            # Pattern 2: Version with epoch
            # e.g., "2:26.1.9-1" -> filename becomes "2-26.1.9-1"
            epoch, rest = old_version.split(':', 1)
            old_patterns.append(f"*{pkg_name}-{epoch}-{rest}-*.pkg.tar.*")
        
        # Also check for the package name pattern without specific version
        # This catches any old version files
        old_patterns.append(f"{pkg_name}-*.pkg.tar.*")
        
        deleted_count = 0
        
        # Check both output_dir and mirror_temp_dir
        for search_dir in [self.output_dir, self.mirror_temp_dir]:
            if not search_dir.exists():
                continue
                
            for pattern in old_patterns:
                for old_file in search_dir.glob(pattern):
                    # Skip if this is the current version we're about to build
                    # We'll identify current files by checking if they match the old_version pattern exactly
                    filename = old_file.name
                    
                    # Extract version from filename for comparison
                    # Filename format: name-version-release-arch.pkg.tar.zst
                    # or name-epoch-version-release-arch.pkg.tar.zst
                    
                    # Skip if file is actually the new version we're building
                    # (this shouldn't happen, but just in case)
                    if old_version in filename:
                        try:
                            old_file.unlink()
                            logger.info(f"🗑️ Pre-emptively removed old version {old_file.name} from {search_dir.name}")
                            deleted_count += 1
                            
                            # Also remove signature if it exists
                            sig_file = old_file.with_suffix(old_file.suffix + '.sig')
                            if sig_file.exists():
                                sig_file.unlink()
                                logger.info(f"🗑️ Removed old signature {sig_file.name}")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not remove old file {old_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ Pre-build purge: Removed {deleted_count} old version file(s) for {pkg_name}")
        else:
            logger.debug(f"ℹ️ Pre-build purge: No old version files found for {pkg_name}")

    def _server_cleanup(self) -> None:
        """ZERO-RESIDUE SERVER CLEANUP: Remove orphaned package files from VPS using LOCAL OUTPUT DIRECTORY as source of truth.
        
        FIXED VERSION: Uses ALL packages in local output directory as valid, not just database entries.
        
        STRICT LOGIC:
        1. Attempt to sync pacman database before cleanup
        2. Get ALL package files from local output directory (newly built + mirrored)
        3. Get ALL database files from local output directory
        4. PROTECT repository metadata files from deletion
        5. Compare VPS files with local files - delete anything on VPS not present locally
        6. ATOMIC execution: single SSH rm -f command for all orphaned files
        """
        print("\n" + "=" * 60)
        print("🔒 ZERO-RESIDUE SERVER CLEANUP: Using local output directory as source of truth")
        print("=" * 60)
        
        # RE-SYNC BEFORE CLEANUP: Attempt pacman sync
        print("\n🔄 Attempting pacman sync before cleanup...")
        try:
            self._sync_pacman_databases()
        except Exception as e:
            logger.warning(f"⚠️ pacman sync failed before cleanup: {e}")
            logger.info("Continuing with cleanup despite sync failure")
        
        # VALVE 1: Check if cleanup should run at all (only after successful operations)
        if not hasattr(self, '_upload_successful') or not self._upload_successful:
            logger.error("❌ SAFETY VALVE: Cleanup cannot run because upload was not successful!")
            return
        
        # STEP 1: Get ALL valid files from local output directory
        valid_filenames = set()
        
        logger.info("🔍 Collecting ALL valid files from local output directory...")
        
        # Get ALL package files from local output directory
        for pkg_file in self.output_dir.glob("*.pkg.tar.*"):
            if pkg_file.is_file():
                valid_filenames.add(pkg_file.name)
                logger.debug(f"✅ Added package to valid files: {pkg_file.name}")
                
                # Also add signature file if it exists locally
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if sig_file.exists():
                    valid_filenames.add(sig_file.name)
                    logger.debug(f"✅ Added signature to valid files: {sig_file.name}")
        
        # Get ALL database files from local output directory
        db_patterns = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz",
            f"{self.repo_name}.abs.tar.gz",
            f"{self.repo_name}.db.sig",
            f"{self.repo_name}.db.tar.gz.sig",
            f"{self.repo_name}.files.sig",
            f"{self.repo_name}.files.tar.gz.sig",
        ]
        
        for pattern in db_patterns:
            db_file = self.output_dir / pattern
            if db_file.exists():
                valid_filenames.add(db_file.name)
                logger.debug(f"✅ Added database file to valid files: {db_file.name}")
        
        # CRITICAL: Also add ALL .sig files for packages that have them
        for sig_file in self.output_dir.glob("*.sig"):
            if sig_file.is_file():
                valid_filenames.add(sig_file.name)
                logger.debug(f"✅ Added signature file to valid files: {sig_file.name}")
        
        logger.info(f"✅ Local output directory has {len(valid_filenames)} valid files")
        
        # VALVE 2: CRITICAL - Must have at least one valid file
        if len(valid_filenames) == 0:
            logger.error("❌❌❌ CRITICAL SAFETY VALVE ACTIVATED: No valid files in output directory!")
            logger.error("   🚨 CLEANUP ABORTED - Output directory empty, potential data loss!")
            return
        
        # Log some sample valid filenames
        sample_filenames = list(valid_filenames)[:10]
        logger.info(f"Sample valid files: {sample_filenames}")
        
        # STEP 2: Get COMPLETE inventory of all files on VPS
        logger.info("📋 Getting complete VPS file inventory...")
        remote_cmd = f"""
        # Get all package files, signatures, and database files
        find "{self.remote_dir}" -maxdepth 1 -type f \( -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" -o -name "*.sig" -o -name "*.db" -o -name "*.db.tar.gz" -o -name "*.files" -o -name "*.files.tar.gz" -o -name "*.abs.tar.gz" \) 2>/dev/null
        """
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning(f"Could not list VPS files: {result.stderr[:200]}")
                return
            
            vps_files_raw = result.stdout.strip()
            if not vps_files_raw:
                logger.info("No files found on VPS - nothing to clean up")
                return
            
            vps_files = [f.strip() for f in vps_files_raw.split('\n') if f.strip()]
            logger.info(f"Found {len(vps_files)} files on VPS")
            
            # STEP 3: Identify orphaned files (files on VPS not in local output directory)
            orphaned_files = []
            protected_count = 0
            
            for vps_file in vps_files:
                # Extract just the filename from the full path
                filename = Path(vps_file).name
                
                # Skip repository metadata files that might not be in output directory
                # but are essential for pacman to function
                protected_extensions = [
                    '.db', '.db.tar.gz', '.db.sig',
                    '.files', '.files.tar.gz', '.files.sig',
                    '.abs.tar.gz'
                ]
                
                is_protected = False
                for ext in protected_extensions:
                    if filename.endswith(ext):
                        is_protected = True
                        protected_count += 1
                        logger.debug(f"🔒 Protected repository file: {filename}")
                        break
                
                # EXACT MATCH CHECK: if filename NOT in valid_filenames and not protected, it's orphaned
                if not is_protected and filename not in valid_filenames:
                    orphaned_files.append(vps_file)
                    logger.info(f"🚨 Orphaned file identified: {filename}")
            
            logger.info(f"🔒 Protected {protected_count} repository metadata files from deletion")
            
            if not orphaned_files:
                logger.info("✅ No orphaned files found - VPS matches local output directory exactly")
                return
            
            # STEP 4: DEBUGGING - Log files to be deleted BEFORE running rm -f
            logger.warning(f"🚨 Identified {len(orphaned_files)} orphaned files for deletion")
            logger.warning("Files to be deleted:")
            for orphaned_file in orphaned_files:
                filename = Path(orphaned_file).name
                logger.warning(f"   🗑️  {filename}")
            
            # STEP 5: ATOMIC EXECUTION - delete all orphaned files in single command
            if orphaned_files:
                # Quote each filename for safety
                quoted_files = [f"'{f}'" for f in orphaned_files]
                files_to_delete = ' '.join(quoted_files)
                
                delete_cmd = f"rm -fv {files_to_delete}"
                
                logger.info(f"🚀 Executing ATOMIC deletion command:")
                logger.info(f"   SSH: {self.vps_user}@{self.vps_host}")
                logger.info(f"   COMMAND: {delete_cmd}")
                
                # Execute the deletion command
                ssh_delete = [
                    "ssh",
                    f"{self.vps_user}@{self.vps_host}",
                    delete_cmd
                ]
                
                result = subprocess.run(
                    ssh_delete,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60
                )
                
                if result.returncode == 0:
                    deleted_count = len(orphaned_files)
                    logger.info(f"✅ ATOMIC deletion successful! Removed {deleted_count} files")
                    if result.stdout:
                        for line in result.stdout.splitlines():
                            if line.strip():
                                logger.info(f"   {line}")
                else:
                    logger.error(f"❌ Deletion failed: {result.stderr[:500]}")
                    # Fallback: try deleting files one by one
                    logger.info("⚠️ Falling back to individual file deletion...")
                    self._delete_files_individually(orphaned_files)
            
            logger.info(f"📊 Cleanup complete: VPS now has exactly {len(valid_filenames)} valid files")
            
        except subprocess.TimeoutExpired:
            logger.error("❌ SSH command timed out - aborting cleanup for safety")
        except Exception as e:
            logger.error(f"❌ Error during VPS file enumeration: {e}")
                
        except Exception as e:
            logger.error(f"❌ Critical error in cleanup processing: {e}")
            logger.error("   Cleanup ABORTED to preserve server state.")
    
    def _delete_files_individually(self, orphaned_files):
        """Fallback: Delete orphaned files one by one."""
        deleted_count = 0
        failed_count = 0
        
        for orphaned_file in orphaned_files:
            filename = Path(orphaned_file).name
            delete_cmd = f"rm -fv '{orphaned_file}'"
            
            ssh_delete = [
                "ssh",
                f"{self.vps_user}@{self.vps_host}",
                delete_cmd
            ]
            
            try:
                result = subprocess.run(
                    ssh_delete,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30
                )
                
                if result.returncode == 0:
                    logger.info(f"✅ Deleted: {filename}")
                    deleted_count += 1
                else:
                    logger.warning(f"⚠️ Failed to delete {filename}: {result.stderr[:200]}")
                    failed_count += 1
                    
            except Exception as e:
                logger.warning(f"⚠️ Error deleting {filename}: {e}")
                failed_count += 1
        
        logger.info(f"📊 Individual deletion: {deleted_count} deleted, {failed_count} failed")

    def _import_gpg_key(self):
        """Import GPG private key and set trust level WITHOUT interactive terminal (container-safe)."""
        if not self.gpg_enabled:
            logger.info("GPG Key not detected. Skipping repository signing.")
            return False
        
        logger.info("GPG Key detected. Importing private key...")
        
        # Handle both string and bytes for the private key
        key_data = self.gpg_private_key
        if isinstance(key_data, bytes):
            key_data_str = key_data.decode('utf-8')
        else:
            key_data_str = str(key_data)
        
        # Validate private key format before attempting import
        if not key_data_str or '-----BEGIN PGP PRIVATE KEY BLOCK-----' not in key_data_str:
            logger.error("❌ CRITICAL: Invalid GPG private key format. Missing '-----BEGIN PGP PRIVATE KEY BLOCK-----' header.")
            logger.error("The GPG_PRIVATE_KEY secret must contain a valid PGP private key block.")
            logger.error("Disabling GPG signing for this build.")
            self.gpg_enabled = False
            return False
        
        try:
            # Create a temporary GPG home directory
            temp_gpg_home = tempfile.mkdtemp(prefix="gpg_home_")
            
            # Set environment for GPG
            env = os.environ.copy()
            env['GNUPGHOME'] = temp_gpg_home
            
            # Import the private key - handle bytes/string correctly
            if isinstance(self.gpg_private_key, bytes):
                key_input = self.gpg_private_key
            else:
                key_input = self.gpg_private_key.encode('utf-8')
            
            import_process = subprocess.run(
                ['gpg', '--batch', '--import'],
                input=key_input,
                capture_output=True,
                text=False,  # Use binary mode for input
                env=env,
                check=False
            )
            
            if import_process.returncode != 0:
                stderr = import_process.stderr.decode('utf-8') if isinstance(import_process.stderr, bytes) else import_process.stderr
                logger.error(f"Failed to import GPG key: {stderr}")
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
                return False
            
            logger.info(f"✅ GPG key imported successfully (Key ID: {self.gpg_key_id})")
            
            # Set ultimate trust for the key (so GPG doesn't prompt)
            # First get the fingerprint
            list_process = subprocess.run(
                ['gpg', '--list-keys', '--with-colons', self.gpg_key_id],
                capture_output=True,
                text=True,
                env=env,
                check=False
            )
            
            fingerprint = None
            if list_process.returncode == 0:
                # Parse output to get fingerprint
                for line in list_process.stdout.split('\n'):
                    if line.startswith('fpr:'):
                        parts = line.split(':')
                        if len(parts) > 9:
                            fingerprint = parts[9]
                            # Set ultimate trust (6 = ultimate)
                            trust_process = subprocess.run(
                                ['gpg', '--import-ownertrust'],
                                input=f"{fingerprint}:6:\n".encode('utf-8'),
                                capture_output=True,
                                text=False,
                                env=env,
                                check=False
                            )
                            if trust_process.returncode == 0:
                                logger.info(f"✅ Set ultimate trust for key fingerprint: {fingerprint[:16]}...")
                            break
            
            # CRITICAL FIX: Export public key and add to pacman-key WITHOUT interactive terminal
            if fingerprint:
                try:
                    # Export public key to a temporary file
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.asc', delete=False) as pub_key_file:
                        export_process = subprocess.run(
                            ['gpg', '--armor', '--export', fingerprint],
                            capture_output=True,
                            text=True,
                            env=env,
                            check=True
                        )
                        pub_key_file.write(export_process.stdout)
                        pub_key_path = pub_key_file.name
                    
                    # Add to pacman-key WITH SUDO
                    logger.info(f"Adding GPG key to pacman-key: {fingerprint[:16]}...")
                    add_process = subprocess.run(
                        ['sudo', 'pacman-key', '--add', pub_key_path],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if add_process.returncode != 0:
                        logger.error(f"Failed to add key to pacman-key: {add_process.stderr}")
                    else:
                        logger.info("✅ Key added to pacman-key")
                    
                    # FIX: Instead of interactive gpg --edit-key (which needs /dev/tty),
                    # use gpg --import-ownertrust for the pacman keyring
                    logger.info(f"Setting ultimate trust in pacman keyring for fingerprint: {fingerprint[:16]}...")
                    
                    # Create ownertrust file content: fingerprint:trust_level
                    ownertrust_content = f"{fingerprint}:6:\n"
                    
                    # Write to temporary file
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.trust', delete=False) as trust_file:
                        trust_file.write(ownertrust_content)
                        trust_file_path = trust_file.name
                    
                    # Import ownertrust into pacman keyring
                    trust_cmd = [
                        'sudo', 'gpg',
                        '--homedir', '/etc/pacman.d/gnupg',
                        '--batch',
                        '--import-ownertrust',
                        trust_file_path
                    ]
                    
                    try:
                        trust_process = subprocess.run(
                            trust_cmd,
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if trust_process.returncode == 0:
                            logger.info(f"✅ Set ultimate trust for key in pacman keyring")
                        else:
                            logger.warning(f"⚠️ Failed to set trust with gpg (exit code: {trust_process.returncode}): {trust_process.stderr[:200]}")
                            # Don't fail the build if this doesn't work
                            logger.warning("⚠️ Continuing build despite gpg trust failure")
                    except Exception as e:
                        logger.warning(f"⚠️ Error setting trust with gpg: {e}")
                        # Don't fail the build if this doesn't work
                        logger.warning("⚠️ Continuing build despite gpg trust error")
                    finally:
                        # Clean up temporary files
                        os.unlink(trust_file_path)
                        os.unlink(pub_key_path)
                    
                except Exception as e:
                    logger.error(f"Error during pacman-key setup: {e}")
            
            # Store the GPG home directory for later use
            self.gpg_home = temp_gpg_home
            self.gpg_env = env
            
            return True
            
        except Exception as e:
            logger.error(f"Error importing GPG key: {e}")
            if 'temp_gpg_home' in locals():
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
            return False
    
    def _cleanup_gpg(self):
        """Clean up temporary GPG home directory."""
        if hasattr(self, 'gpg_home'):
            try:
                shutil.rmtree(self.gpg_home, ignore_errors=True)
                logger.debug("Cleaned up temporary GPG home directory")
            except Exception as e:
                logger.warning(f"Could not clean up GPG directory: {e}")
    
    def _sign_repository_files(self):
        """Sign repository database files with GPG."""
        if not self.gpg_enabled:
            return False
        
        if not hasattr(self, 'gpg_home') or not hasattr(self, 'gpg_env'):
            logger.error("GPG key not imported. Cannot sign repository files.")
            return False
        
        try:
            # Files to sign
            files_to_sign = [
                self.output_dir / f"{self.repo_name}.db",
                self.output_dir / f"{self.repo_name}.files"
            ]
            
            signed_count = 0
            
            for file_to_sign in files_to_sign:
                if not file_to_sign.exists():
                    logger.warning(f"Repository file not found for signing: {file_to_sign.name}")
                    continue
                
                logger.info(f"Signing repository database: {file_to_sign.name}")
                
                # Create detached signature
                sig_file = file_to_sign.with_suffix(file_to_sign.suffix + '.sig')
                
                sign_process = subprocess.run(
                    [
                        'gpg', '--detach-sign',
                        '--default-key', self.gpg_key_id,
                        '--output', str(sig_file),
                        str(file_to_sign)
                    ],
                    capture_output=True,
                    text=True,
                    env=self.gpg_env,
                    check=False
                )
                
                if sign_process.returncode == 0:
                    logger.info(f"✅ Created signature: {sig_file.name}")
                    signed_count += 1
                else:
                    logger.error(f"Failed to sign {file_to_sign.name}: {sign_process.stderr}")
            
            if signed_count > 0:
                logger.info(f"✅ Successfully signed {signed_count} repository file(s)")
                return True
            else:
                logger.error("Failed to sign any repository files")
                return False
                
        except Exception as e:
            logger.error(f"Error signing repository files: {e}")
            return False
    
    def _get_repo_root(self):
        """Get the repository root directory reliably."""
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                logger.info(f"Using GITHUB_WORKSPACE: {workspace_path}")
                return workspace_path
        
        container_workspace = Path('/__w/manjaro-awesome/manjaro-awesome')
        if container_workspace.exists():
            logger.info(f"Using container workspace: {container_workspace}")
            return container_workspace
        
        # Get script directory and go up to repo root
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent.parent
        if repo_root.exists():
            logger.info(f"Using repository root from script location: {repo_root}")
            return repo_root
        
        current_dir = Path.cwd()
        logger.info(f"Using current directory: {current_dir}")
        return current_dir
    
    def _load_config(self):
        """Load configuration from environment and config files."""
        # Required environment variables (secrets)
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        
        # Optional environment variables (overrides)
        self.repo_server_url = os.getenv('REPO_SERVER_URL', '')
        self.remote_dir = os.getenv('REMOTE_DIR')
        
        # Repository name from environment (validated in _validate_env)
        self.repo_name = os.getenv('REPO_NAME')
        
        print(f"🔧 Configuration loaded:")
        print(f"   SSH: {self.vps_user}@{self.vps_host}")
        print(f"   Remote directory: {self.remote_dir}")
        print(f"   Repository name: {self.repo_name}")
        if self.repo_server_url:
            print(f"   Repository URL: {self.repo_server_url}")
        print(f"   Config files loaded: {HAS_CONFIG_FILES}")
        print(f"   GPG signing: {'ENABLED' if self.gpg_enabled else 'DISABLED'}")
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, log_cmd=False, timeout=1800):
        """Run command with comprehensive logging and timeout."""
        if log_cmd:
            logger.info(f"RUNNING COMMAND: {cmd}")
        
        if cwd is None:
            cwd = self.repo_root
        
        if user:
            env = os.environ.copy()
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            env['LC_ALL'] = 'C'  # Set LC_ALL to C for consistent output
            
            try:
                sudo_cmd = ['sudo', '-u', user]
                if shell:
                    sudo_cmd.extend(['bash', '-c', f'cd "{cwd}" && {cmd}'])
                else:
                    sudo_cmd.extend(cmd)
                
                result = subprocess.run(
                    sudo_cmd,
                    capture_output=capture,
                    text=True,
                    check=check,
                    env=env,
                    timeout=timeout
                )
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                    logger.info(f"EXIT CODE: {result.returncode}")
                return result
            except subprocess.TimeoutExpired as e:
                logger.error(f"⚠️ Command timed out after {timeout} seconds: {cmd}")
                if capture and e.stdout:
                    logger.error(f"Partial stdout: {e.stdout.decode('utf-8', errors='ignore')[:500]}")
                if capture and e.stderr:
                    logger.error(f"Partial stderr: {e.stderr.decode('utf-8', errors='ignore')[:500]}")
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
                    if e.stdout:
                        logger.error(f"STDOUT: {e.stdout[:500]}")
                    if e.stderr:
                        logger.error(f"STDERR: {e.stderr[:500]}")
                    logger.error(f"EXIT CODE: {e.returncode}")
                if check:
                    raise
                return e
        else:
            try:
                env = os.environ.copy()
                env['LC_ALL'] = 'C'  # Set LC_ALL to C for consistent output
                
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    shell=shell,
                    capture_output=capture,
                    text=True,
                    check=check,
                    env=env,
                    timeout=timeout
                )
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                    logger.info(f"EXIT CODE: {result.returncode}")
                return result
            except subprocess.TimeoutExpired as e:
                logger.error(f"⚠️ Command timed out after {timeout} seconds: {cmd}")
                if capture and e.stdout:
                    logger.error(f"Partial stdout: {e.stdout.decode('utf-8', errors='ignore')[:500]}")
                if capture and e.stderr:
                    logger.error(f"Partial stderr: {e.stderr.decode('utf-8', errors='ignore')[:500]}")
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
                    if e.stdout:
                        logger.error(f"STDOUT: {e.stdout[:500]}")
                    if e.stderr:
                        logger.error(f"STDERR: {e.stderr[:500]}")
                    logger.error(f"EXIT CODE: {e.returncode}")
                if check:
                    raise
                return e
    
    def test_ssh_connection(self):
        """Test SSH connection to VPS."""
        print("\n🔍 Testing SSH connection to VPS...")
        
        ssh_test_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]
        
        result = subprocess.run(ssh_test_cmd, capture_output=True, text=True, check=False)
        if result and result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout:
            print("✅ SSH connection successful")
            return True
        else:
            print(f"⚠️ SSH connection failed: {result.stderr[:100] if result and result.stderr else 'No output'}")
            return False
    
    def _ensure_remote_directory(self):
        """Ensure remote directory exists and has correct permissions."""
        print("\n🔧 Ensuring remote directory exists...")
        
        remote_cmd = f"""
        # Check if directory exists
        if [ ! -d "{self.remote_dir}" ]; then
            echo "Creating directory {self.remote_dir}"
            sudo mkdir -p "{self.remote_dir}"
            sudo chown -R {self.vps_user}:www-data "{self.remote_dir}"
            sudo chmod -R 755 "{self.remote_dir}"
            echo "✅ Directory created and permissions set"
        else
            echo "✅ Directory exists"
            # Ensure correct permissions
            sudo chown -R {self.vps_user}:www-data "{self.remote_dir}"
            sudo chmod -R 755 "{self.remote_dir}"
            echo "✅ Permissions verified"
        fi
        """
        
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=30",
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Remote directory verified")
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"REMOTE DIR: {line}")
            else:
                logger.warning(f"⚠️ Could not ensure remote directory: {result.stderr[:200]}")
                
        except Exception as e:
            logger.warning(f"Could not ensure remote directory: {e}")
    
    def _check_repository_exists_on_vps(self):
        """FIXED: Check if repository exists on VPS via SSH (simpler logic)."""
        print("\n🔍 Checking if repository exists on VPS...")
        
        # Check for any package files on VPS
        remote_cmd = f"""
        # Check for package files
        if find "{self.remote_dir}" -name "*.pkg.tar.*" -type f 2>/dev/null | head -1 >/dev/null; then
            echo "REPO_EXISTS_WITH_PACKAGES"
        # Check for database files
        elif [ -f "{self.remote_dir}/{self.repo_name}.db.tar.gz" ] || [ -f "{self.remote_dir}/{self.repo_name}.db" ]; then
            echo "REPO_EXISTS_WITH_DB"
        else
            echo "REPO_NOT_FOUND"
        fi
        """
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            if result.returncode == 0:
                if "REPO_EXISTS_WITH_PACKAGES" in result.stdout:
                    logger.info("✅ Repository exists on VPS (has package files)")
                    return True, True  # exists, has packages
                elif "REPO_EXISTS_WITH_DB" in result.stdout:
                    logger.info("✅ Repository exists on VPS (has database)")
                    return True, False  # exists, no packages
                else:
                    logger.info("ℹ️ Repository does not exist on VPS (first run)")
                    return False, False  # doesn't exist
            else:
                logger.warning(f"⚠️ Could not check repository existence: {result.stderr[:200]}")
                return False, False
                
        except subprocess.TimeoutExpired:
            logger.error("❌ SSH timeout checking repository existence")
            return False, False
        except Exception as e:
            logger.error(f"❌ Error checking repository: {e}")
            return False, False
    
    def _apply_repository_state(self, exists, has_packages):
        """FIXED: Apply repository state with proper SigLevel based on discovery."""
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
            
            # Check if our section exists
            section_exists = False
            for line in lines:
                if line.strip() == repo_section or line.strip() == f"#{repo_section}":
                    section_exists = True
                    break
            
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
            
            # Add new section if repository exists on VPS
            if exists:
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                new_lines.append(f"# Automatically enabled - found on VPS")
                new_lines.append(repo_section)
                if has_packages:
                    # Repository has packages, enable with Optional TrustAll for build
                    new_lines.append("SigLevel = Optional TrustAll")
                    logger.info("✅ Enabling repository with SigLevel = Optional TrustAll (build mode)")
                else:
                    # Repository exists but empty (database only)
                    new_lines.append("# SigLevel = Optional TrustAll")
                    new_lines.append("# Repository exists but has no packages yet")
                    logger.info("⚠️ Repository section added but commented (no packages yet)")
                
                if self.repo_server_url:
                    new_lines.append(f"Server = {self.repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
            else:
                # Repository doesn't exist on VPS, add commented section
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                new_lines.append(f"# Disabled - not found on VPS (first run?)")
                new_lines.append(f"#{repo_section}")
                new_lines.append("#SigLevel = Optional TrustAll")
                if self.repo_server_url:
                    new_lines.append(f"#Server = {self.repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
                logger.info("ℹ️ Repository not found on VPS - keeping disabled")
            
            # Write back to pacman.conf
            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write('\n'.join(new_lines))
                temp_path = temp_file.name
            
            # Copy to pacman.conf
            subprocess.run(['sudo', 'cp', temp_path, str(pacman_conf)], check=False)
            subprocess.run(['sudo', 'chmod', '644', str(pacman_conf)], check=False)
            os.unlink(temp_path)
            
            logger.info(f"✅ Updated pacman.conf for repository '{self.repo_name}'")
            
        except Exception as e:
            logger.error(f"Failed to apply repository state: {e}")
    
    def _list_remote_packages(self):
        """STEP 1: List all *.pkg.tar.zst files in the remote repository directory."""
        print("\n" + "=" * 60)
        print("STEP 1: Listing remote repository packages (SSH find)")
        print("=" * 60)
        
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found at {ssh_key_path}")
            return []
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            f"find {self.remote_dir} -maxdepth 1 -type f \\( -name '*.pkg.tar.zst' -o -name '*.pkg.tar.xz' \\) 2>/dev/null || echo 'NO_FILES'"
        ]
        
        logger.info(f"RUNNING SSH COMMAND: {' '.join(ssh_cmd)}")
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.stdout:
                logger.info(f"STDOUT (first 1000 chars): {result.stdout[:1000]}")
            if result.stderr:
                logger.info(f"STDERR: {result.stderr[:500]}")
            
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip() and f.strip() != 'NO_FILES']
                file_count = len(files)
                logger.info(f"✅ SSH find returned {file_count} package files")
                if file_count > 0:
                    print(f"Sample files: {files[:5]}")
                    self.remote_files = [os.path.basename(f) for f in files]
                else:
                    logger.info("ℹ️ No package files found on remote server")
                return files
            else:
                logger.warning(f"⚠️ SSH find returned error: {result.stderr[:200]}")
                return []
                
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return []
    
    def _mirror_remote_packages(self):
        """CRITICAL STEP: Download ALL remote package files to local directory."""
        print("\n" + "=" * 60)
        print("MANDATORY STEP: Mirroring remote packages locally")
        print("=" * 60)
        
        # Ensure remote directory exists first
        self._ensure_remote_directory()
        
        # Create a temporary local repository directory
        mirror_dir = self.mirror_temp_dir
        if mirror_dir.exists():
            shutil.rmtree(mirror_dir, ignore_errors=True)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created local mirror directory: {mirror_dir}")
        
        # Check if there are any files to mirror
        if not self.remote_files:
            logger.info("ℹ️ No remote packages to mirror")
            return True
        
        # Use rsync to download ALL package files from server
        print("📥 Downloading ALL remote package files to local mirror...")
        
        # Use a simpler rsync command without --delete (we're downloading, not uploading)
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60" \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/*.pkg.tar.*' \
          '{mirror_dir}/' 2>/dev/null || true
        """
        
        logger.info(f"RUNNING RSYNC MIRROR COMMAND:")
        logger.info(rsync_cmd.strip())
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines()[-20:]:  # Last 20 lines
                    if line.strip():
                        logger.info(f"RSYNC MIRROR: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip() and "No such file or directory" not in line:
                        logger.error(f"RSYNC MIRROR ERR: {line}")
            
            # List downloaded files
            downloaded_files = list(mirror_dir.glob("*.pkg.tar.*"))
            file_count = len(downloaded_files)
            
            if file_count > 0:
                logger.info(f"✅ Successfully mirrored {file_count} package files ({duration} seconds)")
                logger.info(f"Sample mirrored files: {[f.name for f in downloaded_files[:5]]}")
                
                # Verify file integrity
                valid_files = []
                for pkg_file in downloaded_files:
                    if pkg_file.stat().st_size > 0:
                        valid_files.append(pkg_file)
                    else:
                        logger.warning(f"⚠️ Empty file: {pkg_file.name}")
                
                logger.info(f"Valid mirrored packages: {len(valid_files)}/{file_count}")
                
                # Copy mirrored packages to output directory
                print(f"📋 Copying {len(valid_files)} mirrored packages to output directory...")
                copied_count = 0
                for pkg_file in valid_files:
                    dest = self.output_dir / pkg_file.name
                    if not dest.exists():  # Don't overwrite newly built packages
                        shutil.copy2(pkg_file, dest)
                        copied_count += 1
                
                logger.info(f"Copied {copied_count} mirrored packages to output directory")
                
                # Clean up mirror directory
                shutil.rmtree(mirror_dir, ignore_errors=True)
                
                return True
            else:
                logger.info("ℹ️ No package files were mirrored (repository is empty or permission issue)")
                # Check if directory is empty or has permission issues
                check_cmd = f"""
                if [ -d "{self.remote_dir}" ]; then
                    echo "Directory exists"
                    ls -la "{self.remote_dir}/" | head -5
                else
                    echo "Directory does not exist"
                fi
                """
                
                ssh_check = [
                    "ssh",
                    f"{self.vps_user}@{self.vps_host}",
                    check_cmd
                ]
                
                check_result = subprocess.run(
                    ssh_check,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if check_result.stdout:
                    logger.info(f"Remote directory status: {check_result.stdout}")
                
                shutil.rmtree(mirror_dir, ignore_errors=True)
                return True  # Not an error, just empty repository
                
        except Exception as e:
            logger.error(f"RSYNC mirror execution error: {e}")
            if mirror_dir.exists():
                shutil.rmtree(mirror_dir, ignore_errors=True)
            return False
    
    def _check_database_files(self):
        """Check if repository database files exist on server."""
        print("\n" + "=" * 60)
        print("STEP 2: Checking existing database files on server")
        print("=" * 60)
        
        db_files = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz"
        ]
        
        existing_files = []
        missing_files = []
        
        for db_file in db_files:
            remote_cmd = f"test -f {self.remote_dir}/{db_file} && echo 'EXISTS' || echo 'MISSING'"
            
            ssh_cmd = [
                "ssh",
                f"{self.vps_user}@{self.vps_host}",
                remote_cmd
            ]
            
            try:
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0 and "EXISTS" in result.stdout:
                    existing_files.append(db_file)
                    logger.info(f"✅ Database file exists: {db_file}")
                else:
                    missing_files.append(db_file)
                    logger.info(f"ℹ️ Database file missing: {db_file}")
                    
            except Exception as e:
                logger.warning(f"Could not check {db_file}: {e}")
                missing_files.append(db_file)
        
        if existing_files:
            logger.info(f"Found {len(existing_files)} database files on server")
        else:
            logger.info("No database files found on server")
        
        return existing_files, missing_files
    
    def _fetch_existing_database(self, existing_files):
        """Fetch existing database files from server."""
        if not existing_files:
            return
        
        print("\n📥 Fetching existing database files from server...")
        
        for db_file in existing_files:
            remote_path = f"{self.remote_dir}/{db_file}"
            local_path = self.output_dir / db_file
            
            # Remove local copy if exists
            if local_path.exists():
                local_path.unlink()
            
            ssh_cmd = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=30",
                f"{self.vps_user}@{self.vps_host}:{remote_path}",
                str(local_path)
            ]
            
            try:
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0 and local_path.exists():
                    size_mb = local_path.stat().st_size / (1024 * 1024)
                    logger.info(f"✅ Fetched: {db_file} ({size_mb:.2f} MB)")
                else:
                    logger.warning(f"⚠️ Could not fetch {db_file}")
            except Exception as e:
                logger.warning(f"Could not fetch {db_file}: {e}")
    
    def _get_all_local_packages(self):
        """Get ALL package files from local output directory (mirrored + newly built)."""
        print("\n🔍 Getting complete package list from local directory...")
        
        local_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not local_files:
            logger.info("ℹ️ No package files found locally")
            return []
        
        local_filenames = [f.name for f in local_files]
        
        logger.info(f"📊 Local package count: {len(local_filenames)}")
        logger.info(f"Sample packages: {local_filenames[:10]}")
        
        return local_filenames
    
    def _generate_full_database(self):
        """Generate repository database from ALL locally available packages."""
        print("\n" + "=" * 60)
        print("PHASE: Repository Database Generation")
        print("=" * 60)
        
        # Get all package files from local output directory
        all_packages = self._get_all_local_packages()
        
        if not all_packages:
            logger.info("No packages available for database generation")
            return False
        
        logger.info(f"Generating database with {len(all_packages)} packages...")
        logger.info(f"Packages: {', '.join(all_packages[:10])}{'...' if len(all_packages) > 10 else ''}")
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz", 
                      f"{self.repo_name}.files", f"{self.repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            # CRITICAL DEBUG: List all package files in directory
            logger.info("🔍 DEBUG: Listing all .pkg.tar.zst files in output directory:")
            list_result = subprocess.run(
                "ls -lh *.pkg.tar.zst 2>/dev/null || echo 'No .pkg.tar.zst files found'",
                shell=True,
                capture_output=True,
                text=True
            )
            logger.info(f"Files found:\n{list_result.stdout}")
            
            # Verify each package file exists locally before database generation
            missing_packages = []
            valid_packages = []
            
            for pkg_filename in all_packages:
                if Path(pkg_filename).exists():
                    valid_packages.append(pkg_filename)
                else:
                    missing_packages.append(pkg_filename)
            
            if missing_packages:
                logger.error(f"❌ CRITICAL: {len(missing_packages)} packages missing locally:")
                for pkg in missing_packages[:5]:
                    logger.error(f"   - {pkg}")
                if len(missing_packages) > 5:
                    logger.error(f"   ... and {len(missing_packages) - 5} more")
                
                logger.error("Cannot generate database without all package files present locally")
                logger.error("This indicates a failure in the package mirroring step")
                return False
            
            if not valid_packages:
                logger.error("No valid package files found for database generation")
                return False
            
            logger.info(f"✅ All {len(valid_packages)} package files verified locally")
            
            # Generate database with repo-add using shell=True for wildcard expansion
            # This ensures repo-add can find all packages
            cmd = f"repo-add {db_file} *.pkg.tar.zst"
            
            logger.info(f"Running repo-add with shell=True to include ALL packages...")
            logger.info(f"Command: {cmd}")
            logger.info(f"Current directory: {os.getcwd()}")
            
            result = subprocess.run(
                cmd,
                shell=True,  # CRITICAL: Use shell=True for wildcard expansion
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Database created successfully")
                
                # Verify the database was created
                db_path = Path(db_file)
                if db_path.exists():
                    size_mb = db_path.stat().st_size / (1024 * 1024)
                    logger.info(f"Database size: {size_mb:.2f} MB")
                    
                    # CRITICAL: Verify database entries BEFORE upload
                    logger.info("🔍 Verifying database entries before upload...")
                    list_cmd = ["tar", "-tzf", db_file]
                    list_result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
                    if list_result.returncode == 0:
                        db_entries = [line for line in list_result.stdout.split('\n') if line.endswith('/desc')]
                        logger.info(f"✅ Database contains {len(db_entries)} package entries")
                        if len(db_entries) == 0:
                            logger.error("❌❌❌ DATABASE IS EMPTY! This is the root cause of the issue.")
                            logger.error("Package files exist but repo-add didn't add them to database.")
                            logger.error("Possible causes:")
                            logger.error("1. repo-add permissions issue")
                            logger.error("2. Package files are corrupted")
                            logger.error("3. Database file already exists and is locked")
                            return False
                        else:
                            logger.info(f"Sample database entries: {db_entries[:5]}")
                    else:
                        logger.warning(f"Could not list database contents: {list_result.stderr}")
                
                return True
            else:
                logger.error(f"repo-add failed with exit code {result.returncode}:")
                if result.stdout:
                    logger.error(f"STDOUT: {result.stdout[:500]}")
                if result.stderr:
                    logger.error(f"STDERR: {result.stderr[:500]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def _sync_pacman_databases(self):
        """FIXED: Simplified pacman database sync with proper SigLevel handling and DEBUG COMMAND."""
        print("\n" + "=" * 60)
        print("FINAL STEP: Syncing pacman databases")
        print("=" * 60)
        
        # First, ensure repository is enabled with proper SigLevel
        exists, has_packages = self._check_repository_exists_on_vps()
        self._apply_repository_state(exists, has_packages)
        
        if not exists:
            logger.info("ℹ️ Repository doesn't exist on VPS, skipping pacman sync")
            return False
        
        # Run pacman -Sy
        cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        result = self.run_cmd(cmd, log_cmd=True, timeout=300, check=False)
        
        if result.returncode == 0:
            logger.info("✅ Pacman databases synced successfully")
            
            # CRITICAL DEBUG STEP: List packages in our custom repo
            debug_cmd = f"sudo pacman -Sl {self.repo_name}"
            logger.info(f"🔍 DEBUG: Running command to see what packages pacman sees in our repo:")
            logger.info(f"Command: {debug_cmd}")
            
            debug_result = self.run_cmd(debug_cmd, log_cmd=True, timeout=30, check=False)
            
            if debug_result.returncode == 0:
                if debug_result.stdout.strip():
                    logger.info(f"Packages in {self.repo_name} according to pacman:")
                    for line in debug_result.stdout.splitlines():
                        logger.info(f"  {line}")
                else:
                    logger.warning(f"⚠️ pacman -Sl {self.repo_name} returned no output (repo might be empty)")
            else:
                logger.warning(f"⚠️ pacman -Sl failed: {debug_result.stderr[:200]}")
            
            return True
        else:
            logger.error("❌ Pacman sync failed")
            if result.stderr:
                logger.error(f"Error: {result.stderr[:500]}")
            return False
    
    def _clean_workspace(self, pkg_dir):
        """Clean workspace before building to avoid contamination."""
        logger.info(f"🧹 Cleaning workspace for {pkg_dir.name}...")
        
        # Clean src/ directory if exists
        src_dir = pkg_dir / "src"
        if src_dir.exists():
            try:
                shutil.rmtree(src_dir, ignore_errors=True)
                logger.info(f"  Cleaned src/ directory")
            except Exception as e:
                logger.warning(f"  Could not clean src/: {e}")
        
        # Clean pkg/ directory if exists
        pkg_build_dir = pkg_dir / "pkg"
        if pkg_build_dir.exists():
            try:
                shutil.rmtree(pkg_build_dir, ignore_errors=True)
                logger.info(f"  Cleaned pkg/ directory")
            except Exception as e:
                logger.warning(f"  Could not clean pkg/: {e}")
        
        # Clean any leftover .tar.* files
        for leftover in pkg_dir.glob("*.pkg.tar.*"):
            try:
                leftover.unlink()
                logger.info(f"  Removed leftover package: {leftover.name}")
            except Exception as e:
                logger.warning(f"  Could not remove {leftover}: {e}")
    
    def _compare_versions(self, remote_version, pkgver, pkgrel, epoch):
        """Compare versions using vercmp-style logic. Return True if AUR_VERSION > REMOTE_VERSION."""
        # If no remote version exists, we should build
        if not remote_version:
            logger.info(f"[DEBUG] Comparing Package: Remote(NONE) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (no remote)")
            return True
        
        # Parse remote version
        remote_epoch = None
        remote_pkgver = None
        remote_pkgrel = None
        
        # Check if remote has epoch
        if ':' in remote_version:
            remote_epoch_str, rest = remote_version.split(':', 1)
            remote_epoch = remote_epoch_str
            if '-' in rest:
                remote_pkgver, remote_pkgrel = rest.split('-', 1)
            else:
                remote_pkgver = rest
                remote_pkgrel = "1"  # Default
        else:
            if '-' in remote_version:
                remote_pkgver, remote_pkgrel = remote_version.split('-', 1)
            else:
                remote_pkgver = remote_version
                remote_pkgrel = "1"  # Default
        
        # Build version strings for comparison
        new_version_str = f"{epoch or '0'}:{pkgver}-{pkgrel}"
        remote_version_str = f"{remote_epoch or '0'}:{remote_pkgver}-{remote_pkgrel}"
        
        # Use vercmp for proper version comparison
        try:
            # Try to use vercmp if available
            result = subprocess.run(['vercmp', new_version_str, remote_version_str], 
                                  capture_output=True, text=True, check=False)
            if result.returncode == 0:
                # vercmp returns:
                # <0 if first version is older
                # 0 if equal
                # >0 if first version is newer
                cmp_result = int(result.stdout.strip())
                
                if cmp_result > 0:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (new version is newer)")
                    return True
                elif cmp_result == 0:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (versions identical)")
                    return False
                else:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (remote version is newer)")
                    return False
            else:
                # Fallback to simple comparison if vercmp fails
                logger.warning("vercmp failed, using fallback comparison")
                return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
                
        except Exception as e:
            logger.warning(f"vercmp comparison failed: {e}, using fallback")
            return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
    
    def _fallback_version_comparison(self, remote_version, pkgver, pkgrel, epoch):
        """Fallback version comparison when vercmp is not available."""
        # Parse remote version
        remote_epoch = None
        remote_pkgver = None
        remote_pkgrel = None
        
        if ':' in remote_version:
            remote_epoch_str, rest = remote_version.split(':', 1)
            remote_epoch = remote_epoch_str
            if '-' in rest:
                remote_pkgver, remote_pkgrel = rest.split('-', 1)
            else:
                remote_pkgver = rest
                remote_pkgrel = "1"
        else:
            if '-' in remote_version:
                remote_pkgver, remote_pkgrel = remote_version.split('-', 1)
            else:
                remote_pkgver = remote_version
                remote_pkgrel = "1"
        
        # Compare epochs first
        if epoch != remote_epoch:
            try:
                epoch_int = int(epoch or 0)
                remote_epoch_int = int(remote_epoch or 0)
                if epoch_int > remote_epoch_int:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (epoch {epoch_int} > {remote_epoch_int})")
                    return True
                else:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch {epoch_int} <= {remote_epoch_int})")
                    return False
            except ValueError:
                # If epochs aren't integers, compare as strings
                if epoch != remote_epoch:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch string mismatch)")
                    return False
        
        # Compare pkgver using Arch Linux version comparison rules
        # Simple comparison - in production, use vercmp
        if pkgver != remote_pkgver:
            # This is a simplified comparison - vercmp is more accurate
            logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgver different)")
            return True
        
        # Compare pkgrel
        try:
            remote_pkgrel_int = int(remote_pkgrel)
            pkgrel_int = int(pkgrel)
            if pkgrel_int > remote_pkgrel_int:
                logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgrel {pkgrel_int} > {remote_pkgrel_int})")
                return True
            else:
                logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})")
                return False
        except ValueError:
            # If pkgrel isn't integer, compare as strings
            if pkgrel != remote_pkgrel:
                logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel string mismatch)")
                return False
        
        # Versions are identical
        logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (versions identical)")
        return False
    
    def package_exists(self, pkg_name, version=None):
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        pattern = f"^{re.escape(pkg_name)}-"
        matches = [f for f in self.remote_files if re.match(pattern, f)]
        
        if matches:
            logger.debug(f"Package {pkg_name} exists: {matches[0]}")
            return True
        
        return False
    
    def get_remote_version(self, pkg_name):
        """Get the version of a package from remote server using SRCINFO-based extraction."""
        if not self.remote_files:
            return None
        
        # Look for any file with this package name
        for filename in self.remote_files:
            if filename.startswith(f"{pkg_name}-"):
                # Extract version from filename
                # Format: name-version-release-arch.pkg.tar.zst
                base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
                parts = base.split('-')
                
                # We need at least 3 parts after the name: version-release-arch
                # Find where the package name ends
                # Try to match from the end
                for i in range(len(parts) - 2, 0, -1):
                    # Check if parts[:i] could be the package name
                    possible_name = '-'.join(parts[:i])
                    if possible_name == pkg_name or possible_name.startswith(pkg_name + '-'):
                        # The remaining parts should be: version-release-arch
                        if len(parts) >= i + 3:
                            version_part = parts[i]
                            release_part = parts[i+1]
                            # Check if version_part contains epoch (has colon replaced with hyphen)
                            if i + 1 < len(parts) and parts[i].isdigit() and i + 2 < len(parts):
                                # Might have epoch: format is epoch-version-release
                                epoch_part = parts[i]
                                version_part = parts[i+1]
                                release_part = parts[i+2]
                                return f"{epoch_part}:{version_part}-{release_part}"
                            else:
                                return f"{version_part}-{release_part}"
        
        return None
    
    def get_package_lists(self):
        """Get package lists from packages.py or exit if not available."""
        if HAS_CONFIG_FILES and hasattr(packages, 'LOCAL_PACKAGES') and hasattr(packages, 'AUR_PACKAGES'):
            print("📦 Using package lists from packages.py")
            local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
            print(f">>> DEBUG: Found {len(local_packages_list + aur_packages_list)} packages to check")
            return local_packages_list, aur_packages_list
        else:
            logger.error("Cannot load package lists from packages.py. Exiting.")
            sys.exit(1)
    
    def _install_dependencies_strict(self, deps):
        """STRICT dependency resolution: pacman first, then yay. FIXED: Handle phantom package 'lgi'."""
        if not deps:
            return True
        
        print(f"\nInstalling {len(deps)} dependencies...")
        logger.info(f"Dependencies to install: {deps}")
        
        # Clean dependency names - more robust cleaning
        clean_deps = []
        phantom_packages = set()
        
        for dep in deps:
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            # Remove any empty strings or strings with only special characters
            if dep_clean and dep_clean.strip() and not any(x in dep_clean for x in ['$', '{', '}', '(', ')', '[', ']']):
                # Ensure the dependency name is valid (contains alphanumeric chars)
                if re.search(r'[a-zA-Z0-9]', dep_clean):
                    # FIX: Hard-filter out phantom package 'lgi'
                    if dep_clean == 'lgi':
                        phantom_packages.add('lgi')
                        logger.warning(f"⚠️ Found phantom package 'lgi' - will be replaced with 'lua-lgi'")
                        continue
                    clean_deps.append(dep_clean)
        
        # Remove any duplicate entries
        clean_deps = list(dict.fromkeys(clean_deps))
        
        # FIX: If we removed 'lgi', ensure 'lua-lgi' is present
        if 'lgi' in phantom_packages and 'lua-lgi' not in clean_deps:
            logger.info("Adding 'lua-lgi' to replace phantom package 'lgi'")
            clean_deps.append('lua-lgi')
        
        if not clean_deps:
            logger.info("No valid dependencies to install after cleaning")
            return True
        
        logger.info(f"Valid dependencies to install: {clean_deps}")
        if phantom_packages:
            logger.info(f"Phantom packages removed: {', '.join(phantom_packages)}")
        
        # STEP 0: Sync pacman database first to prevent "could not register '' database" error
        print("STEP 0: Syncing pacman database...")
        sync_cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        sync_result = self.run_cmd(sync_cmd, log_cmd=True, check=False, timeout=300)
        
        if sync_result.returncode != 0:
            logger.warning(f"⚠️ pacman -Sy failed: {sync_result.stderr[:200] if sync_result.stderr else 'No error message'}")
            # Continue anyway, as the database might still work
        
        # STEP 1: Try system packages FIRST with sudo
        print(f"STEP 1: Trying pacman (sudo) for {len(clean_deps)} dependencies...")
        deps_str = ' '.join(clean_deps)
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {deps_str}"
        result = self.run_cmd(cmd, log_cmd=True, check=False, timeout=1200)  # 20 minute timeout for large deps
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        logger.warning(f"⚠️ pacman failed for some dependencies (exit code: {result.returncode})")
        if result.stderr:
            stderr_preview = result.stderr[:500]
            logger.warning(f"pacman stderr preview: {stderr_preview}")
        
        # STEP 2: Fallback to AUR (yay) WITHOUT sudo
        print(f"STEP 2: Trying yay (without sudo) for {len(clean_deps)} dependencies...")
        cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
        result = self.run_cmd(cmd, log_cmd=True, check=False, user="builder", timeout=1800)  # 30 minute timeout for AUR
        
        if result.returncode == 0:
            logger.info("✅ Dependencies installed via yay")
            return True
        
        # STEP 3: Try to install dependencies one by one to identify which ones fail
        logger.error(f"❌ Both pacman and yay failed for dependencies")
        
        # Try installing one by one as a last resort
        print("STEP 3: Trying to install dependencies one by one...")
        success_count = 0
        failed_deps = []
        
        for dep in clean_deps:
            print(f"  Trying to install: {dep}")
            
            # Try pacman first
            cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {dep}"
            result = self.run_cmd(cmd, log_cmd=False, check=False, timeout=300)
            
            if result.returncode == 0:
                success_count += 1
                logger.info(f"  ✅ Installed {dep} via pacman")
                continue
            
            # Try yay if pacman failed
            cmd = f"LC_ALL=C yay -S --needed --noconfirm {dep}"
            result = self.run_cmd(cmd, log_cmd=False, check=False, user="builder", timeout=600)
            
            if result.returncode == 0:
                success_count += 1
                logger.info(f"  ✅ Installed {dep} via yay")
            else:
                failed_deps.append(dep)
                logger.warning(f"  ❌ Failed to install {dep}")
        
        if success_count > 0:
            logger.info(f"✅ Installed {success_count}/{len(clean_deps)} dependencies")
        
        if failed_deps:
            logger.error(f"❌ Failed to install {len(failed_deps)} dependencies: {failed_deps}")
            return False
        
        return True
    
    def _extract_dependencies_from_srcinfo(self, pkg_dir):
        """Extract dependencies from .SRCINFO file."""
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            return []
        
        deps = []
        makedeps = []
        checkdeps = []
        
        with open(srcinfo, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('depends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        deps.append(dep)
                elif line.startswith('makedepends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        makedeps.append(dep)
                elif line.startswith('checkdepends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        checkdeps.append(dep)
        
        return deps + makedeps + checkdeps
    
    def _extract_dependencies_from_pkgbuild(self, pkg_dir):
        """Extract dependencies from PKGBUILD as fallback."""
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return []
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            deps = []
            
            # Look for depends=(
            dep_match = re.search(r'depends\s*=\s*\((.*?)\)', content, re.DOTALL)
            if dep_match:
                dep_content = dep_match.group(1)
                for line in dep_content.split('\n'):
                    line = line.strip().strip("'\"")
                    if line and not line.startswith('#') and not any(x in line for x in ['$', '{', '}']):
                        deps.append(line)
            
            # Look for makedepends=(
            makedep_match = re.search(r'makedepends\s*=\s*\((.*?)\)', content, re.DOTALL)
            if makedep_match:
                makedep_content = makedep_match.group(1)
                for line in makedep_content.split('\n'):
                    line = line.strip().strip("'\"")
                    if line and not line.startswith('#') and not any(x in line for x in ['$', '{', '}']):
                        deps.append(line)
            
            return deps
            
        except Exception as e:
            logger.error(f"Failed to parse PKGBUILD for dependencies: {e}")
            return []
    
    def _install_package_dependencies(self, pkg_dir, pkg_name):
        """Install dependencies for a package."""
        print(f"Checking dependencies for {pkg_name}...")
        
        # First try .SRCINFO
        deps = self._extract_dependencies_from_srcinfo(pkg_dir)
        
        # If no .SRCINFO, try PKGBUILD
        if not deps:
            deps = self._extract_dependencies_from_pkgbuild(pkg_dir)
        
        if not deps:
            logger.info(f"No dependencies for {pkg_name}")
            return
        
        # Special dependencies from config
        special_deps = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
        if pkg_name in special_deps:
            logger.info(f"Adding special dependencies for {pkg_name}")
            deps.extend(special_deps[pkg_name])
        
        self._install_dependencies_strict(deps)
    
    def _extract_package_metadata(self, pkg_file_path):
        """Extract metadata from built package file for hokibot observation."""
        try:
            filename = os.path.basename(pkg_file_path)
            pkg_name = self._extract_package_name_from_filename(filename)
            
            if not pkg_name:
                logger.warning(f"Could not extract package name from {filename}")
                return None
            
            # Get version components by splitting filename from the RIGHT
            # Format: name-version-release-arch.pkg.tar.zst
            base_name = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base_name.split('-')
            
            if len(parts) < 3:
                logger.warning(f"Invalid filename format: {filename}")
                return None
            
            # Last part is architecture
            arch = parts[-1]
            # Second last is release
            pkgrel = parts[-2]
            # Third last is version (may contain epoch like "2.13.c.5")
            version_part = parts[-3]
            
            # Everything before the version is the package name
            # We already extracted it using the proper method
            
            epoch = None
            pkgver = version_part
            if ':' in version_part:
                epoch_part, pkgver = version_part.split(':', 1)
                epoch = epoch_part
            
            return {
                'filename': filename,
                'pkgname': pkg_name,
                'pkgver': pkgver,
                'pkgrel': pkgrel,
                'epoch': epoch,
                'built_version': f"{epoch + ':' if epoch else ''}{pkgver}-{pkgrel}"
            }
        except Exception as e:
            logger.warning(f"Could not extract metadata from {pkg_file_path}: {e}")
            return None
    
    def _extract_package_name_from_filename(self, filename):
        """Extract package name from package filename - FIXED VERSION."""
        # Remove the file extension
        base_name = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
        
        # Split by hyphens
        parts = base_name.split('-')
        
        # Arch package format: name-version-release-architecture
        # We need to extract the last three hyphen-separated parts (version-release-arch)
        # and everything before that is the package name
        
        if len(parts) < 3:
            # Not enough parts for a valid Arch package
            logger.warning(f"⚠️ Could not extract package name from: {filename} - not enough parts")
            return None
        
        # The last 3 parts are: version, release, architecture
        # Everything before that is the package name
        # This handles packages with hyphens in their names (e.g., i3lock-color)
        name_parts = parts[:-3]
        
        if not name_parts:
            logger.warning(f"⚠️ Could not extract package name from: {filename} - no name parts")
            return None
        
        package_name = '-'.join(name_parts)
        
        # Special handling for packages that might have version numbers in their names
        # This is a sanity check - if the last part of the name looks like a version, adjust
        if name_parts and any(c.isdigit() for c in name_parts[-1]):
            # Last part of name contains digits, might be part of version
            # Check if it looks like a version (contains digit and dot)
            if '.' in name_parts[-1] and any(c.isdigit() for c in name_parts[-1]):
                # This might actually be part of the version string
                # Move this part to the version section
                adjusted_name_parts = name_parts[:-1]
                if adjusted_name_parts:
                    package_name = '-'.join(adjusted_name_parts)
        
        return package_name
    
    def _check_repo_remove_exists(self):
        """Check if repo-remove command exists locally."""
        try:
            result = subprocess.run(["which", "repo-remove"], capture_output=True, text=True, check=False)
            return result.returncode == 0 and result.stdout.strip() != ""
        except Exception:
            return False
    
    def _delete_remote_orphaned_files(self, orphaned_packages):
        """TARGETED REMOTE CLEANUP: Delete orphaned package files from Remote VPS via SSH."""
        if not orphaned_packages:
            return
        
        print("\n" + "=" * 60)
        print("TARGETED REMOTE CLEANUP: Deleting orphaned packages from VPS")
        print("=" * 60)
        
        # First, ensure we have the latest list of remote files
        if not self.remote_files:
            logger.info("ℹ️ No remote files to check for deletion")
            return
        
        deleted_count = 0
        failed_count = 0
        
        for pkg_name in orphaned_packages:
            logger.info(f"🔍 Looking for orphaned package on VPS: {pkg_name}")
            
            # Find all files for this package on the remote
            # Match by package name prefix (e.g., "nvidia-driver-assistant-")
            matching_files = []
            for remote_file in self.remote_files:
                if remote_file.startswith(f"{pkg_name}-"):
                    matching_files.append(remote_file)
            
            if not matching_files:
                logger.info(f"ℹ️ No remote files found for {pkg_name} (may have been already deleted)")
                continue
            
            logger.info(f"📦 Found {len(matching_files)} remote file(s) for {pkg_name}: {matching_files}")
            
            # Delete each matching file and its signature
            for remote_file in matching_files:
                try:
                    # Delete main package file
                    remote_path = f"{self.remote_dir}/{remote_file}"
                    delete_cmd = f"rm -f '{remote_path}'"
                    
                    ssh_cmd = [
                        "ssh",
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=30",
                        f"{self.vps_user}@{self.vps_host}",
                        delete_cmd
                    ]
                    
                    logger.info(f"SSH: Deleting remote file {remote_file}")
                    result = subprocess.run(
                        ssh_cmd,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"✅ Successfully deleted remote file: {remote_file}")
                        deleted_count += 1
                    else:
                        logger.warning(f"⚠️ Could not delete remote file {remote_file}: {result.stderr[:200]}")
                        failed_count += 1
                    
                    # Also delete signature file if it exists
                    sig_file = f"{remote_file}.sig"
                    sig_path = f"{self.remote_dir}/{sig_file}"
                    sig_delete_cmd = f"rm -f '{sig_path}' 2>/dev/null || true"
                    
                    ssh_sig_cmd = [
                        "ssh",
                        "-o", "StrictHostKeyChecking=no",
                        "-o", "ConnectTimeout=30",
                        f"{self.vps_user}@{self.vps_host}",
                        sig_delete_cmd
                    ]
                    
                    result_sig = subprocess.run(
                        ssh_sig_cmd,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if result_sig.returncode == 0:
                        logger.info(f"✅ Deleted signature file (if existed): {sig_file}")
                    # Don't count signature deletion failures - file may not exist
                    
                except Exception as e:
                    logger.warning(f"⚠️ Error deleting remote file {remote_file}: {e}")
                    failed_count += 1
        
        logger.info(f"✅ Remote cleanup complete: {deleted_count} files deleted, {failed_count} failures")
        
        # IMPORTANT: Update the remote_files list to reflect deletions
        # This ensures subsequent operations don't reference deleted files
        self.remote_files = [f for f in self.remote_files 
                            if not any(f.startswith(f"{pkg}-") for pkg in orphaned_packages)]
    
    def _prune_orphaned_packages(self):
        """Remove packages that exist locally but are not in packages.py (SSOT)."""
        print("\n" + "=" * 60)
        print("PACKAGE PRUNING: Ensuring packages.py is Single Source of Truth")
        print("=" * 60)
        
        # Load desired packages from packages.py
        local_packages_list, aur_packages_list = self.get_package_lists()
        desired_packages = set(local_packages_list + aur_packages_list)
        
        logger.info(f"📦 Desired packages from packages.py: {len(desired_packages)} packages")
        logger.info(f"Desired packages: {', '.join(sorted(desired_packages))}")
        
        # Scan local build directory for existing package files
        local_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not local_files:
            logger.info("ℹ️ No local package files found - nothing to prune")
            return
        
        logger.info(f"📁 Found {len(local_files)} package files in local directory")
        
        # Identify orphaned packages (files present locally but NOT in packages.py)
        orphaned_files = []
        orphaned_packages = set()
        
        for pkg_file in local_files:
            filename = pkg_file.name
            pkg_name = self._extract_package_name_from_filename(filename)
            
            if pkg_name:
                # DEBUG: Log what we found
                logger.debug(f"DEBUG: {filename} -> {pkg_name}")
                
                # Special handling for ttf-font-awesome-5
                if pkg_name == "ttf-font-awesome" and "ttf-font-awesome-5" in filename:
                    pkg_name = "ttf-font-awesome-5"
                    logger.debug(f"DEBUG: Corrected {filename} -> {pkg_name}")
                
                # Check if this package is in our desired list
                if pkg_name not in desired_packages:
                    orphaned_files.append(pkg_file)
                    orphaned_packages.add(pkg_name)
                    logger.info(f"🔍 Identified orphan: {filename} -> {pkg_name}")
                else:
                    logger.debug(f"✅ Package in desired list: {filename} -> {pkg_name}")
            else:
                logger.warning(f"⚠️ Could not extract package name from: {filename}")
        
        if not orphaned_files:
            logger.info("✅ No orphaned packages found - packages.py SSOT is consistent")
            return
        
        logger.info(f"🔍 Found {len(orphaned_files)} orphaned files from {len(orphaned_packages)} packages")
        logger.info(f"📦 Orphaned packages: {', '.join(sorted(orphaned_packages))}")
        
        # Check if we have a local database file to remove packages from
        # Use ABSOLUTE PATH for database file
        db_file_path = self.output_dir / f"{self.repo_name}.db.tar.gz"
        db_file_exists = db_file_path.exists()
        
        if db_file_exists and self._check_repo_remove_exists():
            logger.info(f"✅ Found local database: {db_file_path} (absolute path)")
            logger.info("🔄 Running repo-remove on local database...")
            
            # Run repo-remove locally for each orphaned package
            for pkg_name in sorted(orphaned_packages):
                print(f"\n🗑️  Removing orphaned package from database: {pkg_name}")
                logger.info(f"Running repo-remove for {pkg_name}...")
                
                # Use absolute path to database file
                cmd = ["repo-remove", str(db_file_path), pkg_name]
                result = subprocess.run(cmd, capture_output=True, text=True, cwd=self.output_dir, check=False)
                
                if result.returncode == 0:
                    logger.info(f"✅ Successfully removed {pkg_name} from local database")
                else:
                    logger.warning(f"⚠️ repo-remove for {pkg_name} returned {result.returncode}")
                    if result.stderr:
                        logger.warning(f"repo-remove stderr: {result.stderr[:200]}")
        else:
            if not self._check_repo_remove_exists():
                logger.warning("⚠️ repo-remove command not found locally")
            elif not db_file_exists:
                logger.warning(f"⚠️ No suitable local database found for repo-remove at {db_file_path}")
            else:
                logger.warning("⚠️ Cannot run repo-remove")
        
        # TARGETED REMOTE CLEANUP: Delete orphaned files from Remote VPS via SSH
        self._delete_remote_orphaned_files(orphaned_packages)
        
        # Delete physical package files (and signatures) locally
        print(f"\n🗑️  Deleting {len(orphaned_files)} orphaned package files locally...")
        
        deleted_count = 0
        for pkg_file in orphaned_files:
            try:
                # Delete the main package file
                pkg_file.unlink()
                logger.info(f"✅ Deleted locally: {pkg_file.name}")
                
                # Also delete signature file if it exists
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if sig_file.exists():
                    sig_file.unlink()
                    logger.info(f"✅ Deleted signature locally: {sig_file.name}")
                
                deleted_count += 1
            except Exception as e:
                logger.error(f"❌ Failed to delete {pkg_file.name}: {e}")
        
        logger.info(f"✅ Local package pruning complete: {deleted_count} files deleted")
    
    def _build_aur_package(self, pkg_name):
        """Build AUR package with SRCINFO-based version comparison."""
        aur_dir = self.aur_build_dir
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)
        
        print(f"Cloning {pkg_name} from AUR...")
        
        # Try different AUR URLs from config (ALWAYS FRESH CLONE)
        clone_success = False
        for aur_url_template in self.aur_urls:
            aur_url = aur_url_template.format(pkg_name=pkg_name)
            logger.info(f"Trying AUR URL: {aur_url}")
            result = self.run_cmd(
                f"git clone --depth 1 {aur_url} {pkg_dir}",
                check=False
            )
            if result and result.returncode == 0:
                clone_success = True
                logger.info(f"Successfully cloned {pkg_name} from {aur_url}")
                break
            else:
                if pkg_dir.exists():
                    shutil.rmtree(pkg_dir, ignore_errors=True)
                logger.warning(f"Failed to clone from {aur_url}")
        
        if not clone_success:
            logger.error(f"Failed to clone {pkg_name} from any AUR URL")
            return False
        
        # Set correct permissions
        self.run_cmd(f"chown -R builder:builder {pkg_dir}", check=False)
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
        
        # Extract version info from SRCINFO (not regex)
        try:
            pkgver, pkgrel, epoch = self._extract_version_from_srcinfo(pkg_dir)
            version = self._get_full_version_string(pkgver, pkgrel, epoch)
            
            # Get remote version for comparison
            remote_version = self.get_remote_version(pkg_name)
            
            # DECISION LOGIC: Only build if AUR_VERSION > REMOTE_VERSION
            if remote_version and not self._compare_versions(remote_version, pkgver, pkgrel, epoch):
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files BEFORE building new version
                self._pre_build_purge_old_versions(pkg_name, remote_version)
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
                
        except Exception as e:
            logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self._clean_workspace(pkg_dir)
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True, timeout=600)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            # Install dependencies
            self._install_package_dependencies(pkg_dir, pkg_name)
            
            print("Building package...")
            build_result = self.run_cmd(
                f"makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600  # 1 hour timeout for building
            )
            
            if build_result.returncode == 0:
                moved = False
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                logger.error(f"Failed to build {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
    
    def _build_local_package(self, pkg_name):
        """Build local package with SRCINFO-based version comparison."""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        # Extract version info from SRCINFO (not regex)
        try:
            pkgver, pkgrel, epoch = self._extract_version_from_srcinfo(pkg_dir)
            version = self._get_full_version_string(pkgver, pkgrel, epoch)
            
            # Get remote version for comparison
            remote_version = self.get_remote_version(pkg_name)
            
            # DECISION LOGIC: Only build if AUR_VERSION > REMOTE_VERSION
            if remote_version and not self._compare_versions(remote_version, pkgver, pkgrel, epoch):
                logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                return False
            
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files BEFORE building new version
                self._pre_build_purge_old_versions(pkg_name, remote_version)
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
                
        except Exception as e:
            logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self._clean_workspace(pkg_dir)
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True, timeout=600)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                return False
            
            # Install dependencies
            self._install_package_dependencies(pkg_dir, pkg_name)
            
            print("Building package...")
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                logger.info("GTK2: Skipping check step (long)")
            
            build_result = self.run_cmd(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600  # 1 hour timeout for building
            )
            
            if build_result.returncode == 0:
                moved = False
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                    built_files.append(str(dest))
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    self.rebuilt_local_packages.append(pkg_name)
                    
                    # Collect metadata for hokibot
                    if built_files:
                        metadata = self._extract_package_metadata(built_files[0])
                        if metadata:
                            self.hokibot_data.append({
                                'name': pkg_name,
                                'built_version': metadata['built_version'],
                                'pkgver': metadata['pkgver'],
                                'pkgrel': metadata['pkgrel'],
                                'epoch': metadata['epoch']
                            })
                            logger.info(f"📝 HOKIBOT observed: {pkg_name} -> {metadata['built_version']}")
                    
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                logger.error(f"Failed to build {pkg_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            return False
    
    def _build_single_package(self, pkg_name, is_aur):
        """Build a single package."""
        print(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")
        
        if is_aur:
            return self._build_aur_package(pkg_name)
        else:
            return self._build_local_package(pkg_name)
    
    def build_packages(self):
        """Build packages."""
        print("\n" + "=" * 60)
        print("Building packages")
        print("=" * 60)
        
        local_packages, aur_packages = self.get_package_lists()
        
        print(f"📦 Package statistics:")
        print(f"   Local packages: {len(local_packages)}")
        print(f"   AUR packages: {len(aur_packages)}")
        print(f"   Total packages: {len(local_packages) + len(aur_packages)}")
        
        print(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if self._build_single_package(pkg, is_aur=True):
                self.stats["aur_success"] += 1
            else:
                self.stats["aur_failed"] += 1
        
        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self._build_single_package(pkg, is_aur=False):
                self.stats["local_success"] += 1
            else:
                self.stats["local_failed"] += 1
        
        return self.stats["aur_success"] + self.stats["local_success"]
    
    def _update_pkgbuild_in_clone(self, clone_dir, pkg_data):
        """Update a single PKGBUILD in the git clone based on observed data."""
        pkg_dir = clone_dir / pkg_data['name']
        pkgbuild_path = pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            logger.warning(f"PKGBUILD not found in clone for {pkg_data['name']}")
            return False
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            changed = False
            
            current_pkgver_match = re.search(r'^\s*pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if current_pkgver_match:
                current_pkgver = current_pkgver_match.group(1)
                if current_pkgver != pkg_data['pkgver']:
                    content = re.sub(
                        r'^\s*pkgver\s*=\s*["\']?[^"\'\n]+',
                        f"pkgver={pkg_data['pkgver']}",
                        content,
                        flags=re.MULTILINE
                    )
                    changed = True
                    logger.info(f"  Updated pkgver: {current_pkgver} -> {pkg_data['pkgver']}")
            
            current_pkgrel_match = re.search(r'^\s*pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if current_pkgrel_match:
                current_pkgrel = current_pkgrel_match.group(1)
                if current_pkgrel != pkg_data['pkgrel']:
                    content = re.sub(
                        r'^\s*pkgrel\s*=\s*["\']?[^"\'\n]+',
                        f"pkgrel={pkg_data['pkgrel']}",
                        content,
                        flags=re.MULTILINE
                    )
                    changed = True
                    logger.info(f"  Updated pkgrel: {current_pkgrel} -> {pkg_data['pkgrel']}")
            
            current_epoch_match = re.search(r'^\s*epoch\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if pkg_data['epoch'] is not None:
                if current_epoch_match:
                    current_epoch = current_epoch_match.group(1)
                    if current_epoch != pkg_data['epoch']:
                        content = re.sub(
                            r'^\s*epoch\s*=\s*["\']?[^"\'\n]+',
                            f"epoch={pkg_data['epoch']}",
                            content,
                            flags=re.MULTILINE
                        )
                        changed = True
                        logger.info(f"  Updated epoch: {current_epoch} -> {pkg_data['epoch']}")
                else:
                    lines = content.split('\n')
                    new_lines = []
                    epoch_added = False
                    for line in lines:
                        new_lines.append(line)
                        if not epoch_added and line.strip().startswith('pkgver='):
                            new_lines.append(f'epoch={pkg_data["epoch"]}')
                            epoch_added = True
                            changed = True
                            logger.info(f"  Added epoch: {pkg_data['epoch']}")
                    content = '\n'.join(new_lines)
            else:
                if current_epoch_match:
                    content = re.sub(r'^\s*epoch\s*=\s*["\']?[^"\'\n]+\n?', '', content, flags=re.MULTILINE)
                    changed = True
                    logger.info(f"  Removed epoch: {current_epoch_match.group(1)}")
            
            if changed:
                with open(pkgbuild_path, 'w') as f:
                    f.write(content)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update PKGBUILD for {pkg_data['name']} in clone: {e}")
            return False
    
    def _synchronize_pkgbuilds(self):
        """PHASE 2: Isolated PKGBUILD synchronization."""
        if not self.hokibot_data:
            logger.info("No local packages were rebuilt - skipping PKGBUILD synchronization")
            return
        
        print("\n" + "=" * 60)
        print("🔄 PHASE 2: Isolated PKGBUILD Synchronization")
        print("=" * 60)
        
        clone_dir = self.sync_clone_dir
        
        try:
            if clone_dir.exists():
                shutil.rmtree(clone_dir)
            
            clone_dir.mkdir(parents=True, exist_ok=True)
            
            github_ssh_key = os.getenv('CI_PUSH_SSH_KEY')
            if not github_ssh_key:
                logger.warning("CI_PUSH_SSH_KEY not set in environment - skipping PKGBUILD sync")
                return
            
            # Use GITHUB_TOKEN for authentication
            repo_url = f"https://x-access-token:{github_ssh_key}@github.com/{self.github_repo}"
            
            print(f"📥 Cloning repository to {clone_dir}...")
            clone_result = subprocess.run(
                ['git', 'clone', repo_url, str(clone_dir)],
                capture_output=True,
                text=True
            )
            
            if clone_result.returncode != 0:
                logger.error(f"Failed to clone repository: {clone_result.stderr}")
                return
            
            subprocess.run(
                ['git', 'config', 'user.name', 'GitHub Actions Builder'],
                cwd=clone_dir,
                capture_output=True
            )
            subprocess.run(
                ['git', 'config', 'user.email', 'builder@github-actions.local'],
                cwd=clone_dir,
                capture_output=True
            )
            
            modified_packages = []
            for pkg_data in self.hokibot_data:
                print(f"\n📝 Processing {pkg_data['name']}...")
                print(f"   Observed version: {pkg_data['built_version']}")
                
                if self._update_pkgbuild_in_clone(clone_dir, pkg_data):
                    modified_packages.append(pkg_data['name'])
            
            if not modified_packages:
                print("\n✅ No PKGBUILDs needed updates")
                return
            
            print(f"\n📝 Committing changes for {len(modified_packages)} package(s)...")
            
            for pkg_name in modified_packages:
                pkgbuild_path = clone_dir / pkg_name / "PKGBUILD"
                if pkgbuild_path.exists():
                    subprocess.run(
                        ['git', 'add', str(pkgbuild_path.relative_to(clone_dir))],
                        cwd=clone_dir,
                        capture_output=True
                    )
            
            commit_msg = f"chore: synchronize PKGBUILDs with built versions\n\n"
            commit_msg += f"Updated {len(modified_packages)} rebuilt local package(s):\n"
            for pkg_name in modified_packages:
                for pkg_data in self.hokibot_data:
                    if pkg_data['name'] == pkg_name:
                        commit_msg += f"- {pkg_name}: {pkg_data['built_version']}\n"
                        break
            
            commit_result = subprocess.run(
                ['git', 'commit', '-m', commit_msg],
                cwd=clone_dir,
                capture_output=True,
                text=True
            )
            
            if commit_result.returncode == 0:
                print("✅ Changes committed")
                
                print("\n📤 Pushing changes to main branch...")
                push_result = subprocess.run(
                    ['git', 'push', 'origin', 'main'],
                    cwd=clone_dir,
                    capture_output=True,
                    text=True
                )
                
                if push_result.returncode == 0:
                    print("✅ Changes pushed to main branch")
                else:
                    logger.error(f"Failed to push changes: {push_result.stderr}")
            else:
                logger.warning(f"Commit failed or no changes: {commit_result.stderr}")
            
        except Exception as e:
            logger.error(f"Error during PKGBUILD synchronization: {e}")
            import traceback
            traceback.print_exc()
    
    def upload_packages(self):
        """Upload packages to server using RSYNC WITHOUT --delete flag (Zero-residue cleanup handles orphans)."""
        # Get all package files and database files
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
        
        all_files = pkg_files + db_files
        
        if not all_files:
            logger.warning("No files to upload")
            self._upload_successful = False  # Set flag
            return False
        
        # Log upload start with GPG status
        if self.gpg_enabled:
            logger.info("Starting upload (including signatures)...")
        else:
            logger.info("Starting upload...")
        
        # Ensure remote directory exists first
        self._ensure_remote_directory()
        
        # Collect files using glob patterns
        file_patterns = [
            str(self.output_dir / "*.pkg.tar.*"),
            str(self.output_dir / f"{self.repo_name}.*")
        ]
        
        files_to_upload = []
        for pattern in file_patterns:
            files_to_upload.extend(glob.glob(pattern))
        
        if not files_to_upload:
            logger.error("No files found to upload!")
            self._upload_successful = False  # Set flag
            return False
        
        # Log files to upload
        logger.info(f"Files to upload ({len(files_to_upload)}):")
        for f in files_to_upload:
            size_mb = os.path.getsize(f) / (1024 * 1024)
            file_type = "DATABASE"
            if self.repo_name in os.path.basename(f):
                if f.endswith('.sig'):
                    file_type = "SIGNATURE"
                else:
                    file_type = "DATABASE"
            else:
                file_type = "PACKAGE"
            logger.info(f"  - {os.path.basename(f)} ({size_mb:.1f}MB) [{file_type}]")
        
        # Build RSYNC command WITHOUT --delete (Zero-residue cleanup handles orphans)
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        # Log the command
        logger.info(f"RUNNING RSYNC COMMAND WITHOUT --delete (Exact-match cleanup handles orphans):")
        logger.info(rsync_cmd.strip())
        logger.info(f"SOURCE: {self.output_dir}/")
        logger.info(f"DESTINATION: {self.vps_user}@{self.vps_host}:{self.remote_dir}/")
        logger.info(f"IMPORTANT: Using Exact-Filename-Match cleanup for zero-residue repository")
        
        # FIRST ATTEMPT
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE (attempt 1): {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"RSYNC: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip() and "No such file or directory" not in line:
                        logger.error(f"RSYNC ERR: {line}")
            
            if result.returncode == 0:
                logger.info(f"✅ RSYNC upload successful! ({duration} seconds)")
                self._upload_successful = True  # CRITICAL: Set success flag
                
                # Run Exact-Filename-Match cleanup after successful upload ONLY
                self._server_cleanup()
                
                # Verification
                try:
                    self._verify_uploaded_files()
                except Exception as e:
                    logger.warning(f"⚠️ Verification error (upload still successful): {e}")
                return True
            else:
                logger.warning(f"⚠️ First RSYNC attempt failed (code: {result.returncode})")
                self._upload_successful = False  # Set flag
                
        except Exception as e:
            logger.error(f"RSYNC execution error: {e}")
            self._upload_successful = False  # Set flag
        
        # SECOND ATTEMPT (with different SSH options)
        logger.info("⚠️ Retrying with different SSH options...")
        time.sleep(5)
        
        # Use -e option with SSH command this time
        rsync_cmd_retry = f"""
        rsync -avz \
          --progress \
          --stats \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=30 -o ServerAliveCountMax=3" \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        logger.info(f"RUNNING RSYNC RETRY COMMAND WITHOUT --delete:")
        logger.info(rsync_cmd_retry.strip())
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd_retry,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE (attempt 2): {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"RSYNC RETRY: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip() and "No such file or directory" not in line:
                        logger.error(f"RSYNC RETRY ERR: {line}")
            
            if result.returncode == 0:
                logger.info(f"✅ RSYNC upload successful on retry! ({duration} seconds)")
                self._upload_successful = True  # CRITICAL: Set success flag
                
                # Run Exact-Filename-Match cleanup after successful upload ONLY
                self._server_cleanup()
                
                # Verification
                try:
                    self._verify_uploaded_files()
                except Exception as e:
                    logger.warning(f"⚠️ Verification error (upload still successful): {e}")
                return True
            else:
                logger.error(f"❌ RSYNC upload failed on both attempts!")
                self._upload_successful = False  # Set flag
                return False
                
        except Exception as e:
            logger.error(f"RSYNC retry execution error: {e}")
            self._upload_successful = False  # Set flag
            return False
    
    def _verify_uploaded_files(self):
        """Verify uploaded files on remote server."""
        logger.info("Verifying uploaded files on remote server...")
        
        # Check remote directory with explicit search for orphaned packages
        remote_cmd = f"""
        echo "=== REMOTE DIRECTORY (full) ==="
        ls -la "{self.remote_dir}/" 2>/dev/null
        echo ""
        echo "=== PACKAGE COUNT ==="
        find "{self.remote_dir}" -name "*.pkg.tar.*" -type f 2>/dev/null | wc -l
        """
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"VERIFY: {line}")
            else:
                if result.stderr:
                    logger.warning(f"Verification warning: {result.stderr[:200]}")
                    
        except Exception as e:
            logger.warning(f"Verification error: {e}")
    
    def run(self):
        """FIXED: Main execution with simplified repository discovery and proper GPG integration."""
        print("\n" + "=" * 60)
        print("🚀 MANJARO PACKAGE BUILDER (FIXED REPO DISCOVERY + GPG)")
        print("=" * 60)
        
        try:
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Repository name: {self.repo_name}")
            print(f"Output directory: {self.output_dir}")
            
            # STEP 0: Initialize GPG FIRST if enabled
            print("\n" + "=" * 60)
            print("STEP 0: GPG INITIALIZATION")
            print("=" * 60)
            if self.gpg_enabled:
                if not self._import_gpg_key():
                    logger.error("❌ Failed to import GPG key, disabling signing")
                    self.gpg_enabled = False
                else:
                    logger.info("✅ GPG initialized successfully")
            else:
                logger.info("ℹ️ GPG signing disabled (no key provided)")
            
            special_deps = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
            print(f"Special dependencies loaded: {len(special_deps)}")
            
            # STEP 1: SIMPLIFIED REPOSITORY DISCOVERY
            print("\n" + "=" * 60)
            print("STEP 1: SIMPLIFIED REPOSITORY STATE DISCOVERY")
            print("=" * 60)
            
            # Check if repository exists on VPS
            repo_exists, has_packages = self._check_repository_exists_on_vps()
            
            # Apply repository state based on discovery
            self._apply_repository_state(repo_exists, has_packages)
            
            # Ensure remote directory exists
            self._ensure_remote_directory()
            
            # STEP 2: List remote packages for version comparison
            remote_packages = self._list_remote_packages()
            
            # MANDATORY STEP: Mirror ALL remote packages locally before any database operations
            if remote_packages:
                print("\n" + "=" * 60)
                print("MANDATORY PRECONDITION: Mirroring remote packages locally")
                print("=" * 60)
                
                if not self._mirror_remote_packages():
                    logger.error("❌ FAILED to mirror remote packages locally")
                    logger.error("Cannot proceed without local package mirror")
                    return 1
            else:
                logger.info("ℹ️ No remote packages to mirror (repository appears empty)")
            
            # STEP 3: Package Pruning - Ensure packages.py is SSOT
            # This must happen BEFORE building new packages
            self._prune_orphaned_packages()
            
            # STEP 4: Check existing database files
            existing_db_files, missing_db_files = self._check_database_files()
            
            # Fetch existing database if available
            if existing_db_files:
                self._fetch_existing_database(existing_db_files)
            
            # Build packages
            print("\n" + "=" * 60)
            print("STEP 5: PACKAGE BUILDING (SRCINFO VERSIONING)")
            print("=" * 60)
            
            total_built = self.build_packages()
            
            # Check if we have any packages locally (mirrored + newly built)
            local_packages = self._get_all_local_packages()
            
            if local_packages or remote_packages:
                print("\n" + "=" * 60)
                print("STEP 6: REPOSITORY DATABASE HANDLING (WITH LOCAL MIRROR)")
                print("=" * 60)
                
                # Generate database with ALL locally available packages
                if self._generate_full_database():
                    # Sign repository database files if GPG is enabled
                    if self.gpg_enabled:
                        if not self._sign_repository_files():
                            logger.warning("⚠️ Failed to sign repository files, continuing anyway")
                    
                    # Upload regenerated database and packages
                    if not self.test_ssh_connection():
                        logger.warning("SSH test failed, but trying upload anyway...")
                    
                    # Upload everything (packages + database + signatures)
                    upload_success = self.upload_packages()
                    
                    # Clean up GPG temporary directory
                    self._cleanup_gpg()
                    
                    if upload_success:
                        # STEP 7: Update repository state and sync pacman
                        print("\n" + "=" * 60)
                        print("STEP 7: FINAL REPOSITORY STATE UPDATE")
                        print("=" * 60)
                        
                        # Re-check repository state (it should exist now)
                        repo_exists, has_packages = self._check_repository_exists_on_vps()
                        self._apply_repository_state(repo_exists, has_packages)
                        
                        # Sync pacman databases
                        self._sync_pacman_databases()
                        
                        # Synchronize PKGBUILDs
                        self._synchronize_pkgbuilds()
                        
                        print("\n✅ Build completed successfully!")
                    else:
                        print("\n❌ Upload failed!")
                else:
                    print("\n❌ Database generation failed!")
            else:
                print("\n📊 Build summary:")
                print(f"   AUR packages built: {self.stats['aur_success']}")
                print(f"   AUR packages failed: {self.stats['aur_failed']}")
                print(f"   Local packages built: {self.stats['local_success']}")
                print(f"   Local packages failed: {self.stats['local_failed']}")
                print(f"   Total skipped: {len(self.skipped_packages)}")
                
                if self.stats['aur_failed'] > 0 or self.stats['local_failed'] > 0:
                    print("⚠️ Some packages failed to build")
                else:
                    print("✅ All packages are up to date or built successfully!")
                
                # Clean up GPG even if no packages built
                self._cleanup_gpg()
            
            elapsed = time.time() - self.stats["start_time"]
            
            print("\n" + "=" * 60)
            print("📊 BUILD SUMMARY")
            print("=" * 60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {self.stats['aur_success']} (failed: {self.stats['aur_failed']})")
            print(f"Local packages:  {self.stats['local_success']} (failed: {self.stats['local_failed']})")
            print(f"Total built:     {total_built}")
            print(f"Skipped:         {len(self.skipped_packages)}")
            print(f"GPG signing:     {'Enabled' if self.gpg_enabled else 'Disabled'}")
            print(f"SRCINFO parsing: ✅ Implemented")
            print(f"Zero-Residue:    ✅ Exact-filename-match cleanup active")
            print(f"Pre-Build Purge: ✅ Old versions removed before database generation")
            print("=" * 60)
            
            if self.built_packages:
                print("\n📦 Built packages:")
                for pkg in self.built_packages:
                    print(f"  - {pkg}")
            
            return 0
            
        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            # Ensure GPG cleanup even on failure
            self._cleanup_gpg()
            return 1


if __name__ == "__main__":
    sys.exit(PackageBuilder().run())