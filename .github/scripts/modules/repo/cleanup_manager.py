"""
Cleanup Manager Module - Handles Zero-Residue policy and server cleanup ONLY
WITH IMPROVED DELETION OBSERVABILITY

CRITICAL: Version cleanup logic has been moved to SmartCleanup.
This module now handles ONLY:
- Server cleanup (VPS zombie package removal)
- Database file cleanup
"""

import os
import subprocess
import shutil
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class CleanupManager:
    """
    Manages server-side cleanup operations ONLY.
    
    CRITICAL: Version cleanup is now handled by SmartCleanup.
    This module only handles:
    1. Server cleanup (removing zombie packages from VPS)
    2. Database file maintenance
    """
    
    def __init__(self, config: dict):
        """
        Initialize CleanupManager with configuration
        
        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory
                - remote_dir: Remote directory on VPS
                - mirror_temp_dir: Temporary mirror directory
                - vps_user: VPS username
                - vps_host: VPS hostname
        """
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.mirror_temp_dir = Path(config.get('mirror_temp_dir', '/tmp/repo_mirror'))
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
    
    def revalidate_output_dir_before_database(self, allowlist: Optional[Set[str]] = None):
        """
        🚨 PRE-DATABASE VALIDATION: Remove outdated package versions and orphaned signatures.
        Operates ONLY on output_dir.
        
        Enforces:
        - Only the latest version of each package remains.
        - Orphaned .sig files (without a package) are removed.
        - Packages not in allowlist are removed (if allowlist provided).
        
        Args:
            allowlist: Set of valid package names from PKGBUILD extraction (optional)
        """
        logger.info("🚨 PRE-DATABASE VALIDATION: Starting output_dir revalidation...")
        
        # Import SmartCleanup here to avoid circular imports
        from modules.repo.smart_cleanup import SmartCleanup
        
        # Create SmartCleanup instance for output_dir cleanup
        smart_cleanup = SmartCleanup(self.repo_name, self.output_dir)
        
        # Step 1: Remove old package versions (keep only newest per package)
        smart_cleanup.remove_old_package_versions()
        
        # Step 2: Remove packages not in allowlist (if allowlist provided)
        if allowlist:
            smart_cleanup.remove_packages_not_in_allowlist(allowlist)
        
        # Step 3: Remove orphaned .sig files
        self._remove_orphaned_signatures()
        
        logger.info("✅ PRE-DATABASE VALIDATION: Output directory revalidated successfully.")
    
    def get_vps_files_to_delete(self, version_tracker) -> Tuple[List[str], List[str]]:
        """
        Identify files that should be deleted from VPS based on local output_dir state.
        
        Returns:
            Tuple of (files_to_delete, files_to_keep)
        """
        logger.info("Identifying VPS files for deletion based on local state...")
        
        # Get current VPS files
        vps_files = self._get_vps_file_inventory()
        if not vps_files:
            logger.info("No VPS files found")
            return [], []
        
        # Get local files from output_dir
        local_files = set(f.name for f in self.output_dir.glob("*"))
        
        # Identify files to delete (on VPS but not locally)
        files_to_delete = []
        files_to_keep = []
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            
            # Always keep database and signature files (they'll be regenerated)
            is_db_or_sig = any(filename.endswith(ext) for ext in [
                '.db', '.db.tar.gz', '.sig', '.files', '.files.tar.gz'
            ])
            
            if is_db_or_sig:
                # Database/signature files are handled separately
                files_to_keep.append(vps_file)
                continue
            
            if filename in local_files:
                files_to_keep.append(vps_file)
                logger.debug(f"Keeping {filename} (exists locally)")
            else:
                files_to_delete.append(vps_file)
                logger.info(f"Marking for deletion: {filename} (not in local output)")
        
        logger.info(f"VPS cleanup: {len(files_to_keep)} to keep, {len(files_to_delete)} to delete")
        return files_to_delete, files_to_keep
    
    def _remove_orphaned_signatures(self):
        """Remove orphaned .sig files that don't have a corresponding package"""
        logger.info("🔍 Checking for orphaned signature files...")
        
        orphaned_count = 0
        for sig_file in self.output_dir.glob("*.sig"):
            # Corresponding package file (remove .sig extension)
            pkg_file = sig_file.with_suffix('')
            
            if not pkg_file.exists():
                try:
                    sig_file.unlink()
                    logger.info(f"Removed orphaned signature: {sig_file.name}")
                    orphaned_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete orphaned signature {sig_file}: {e}")
        
        if orphaned_count > 0:
            logger.info(f"✅ Removed {orphaned_count} orphaned signature files")
        else:
            logger.info("✅ No orphaned signature files found")
    
    def cleanup_vps_orphaned_signatures(self) -> Tuple[int, int, int]:
        """
        🚨 VPS ORPHAN SIGNATURE SWEEP: Delete signature files without corresponding packages on VPS.
        ALWAYS SAFE TO RUN - NO PACKAGES ARE DELETED
        
        Returns:
            Tuple of (package_count, signature_count, deleted_orphan_count)
        """
        # Generate privacy-safe hash for logging
        remote_dir_hash = hashlib.sha256(self.remote_dir.encode()).hexdigest()[:8]
        logger.info(f"Starting VPS orphan signature sweep (remote_dir_hash: {remote_dir_hash})...")
        
        # Get ALL files from VPS (including signatures)
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory")
            return 0, 0, 0
        
        if not vps_files:
            logger.info("No files found on VPS")
            return 0, 0, 0
        
        # Separate package files and signature files
        package_files = set()
        signature_files = []
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            if filename.endswith('.sig'):
                signature_files.append(vps_file)
            elif filename.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                package_files.add(filename)
        
        # Log counts (privacy-safe)
        logger.info(f"Found {len(package_files)} package files and {len(signature_files)} signature files on VPS")
        
        # Identify orphaned signatures (signatures without corresponding package)
        orphaned_signatures = []
        for sig_file in signature_files:
            sig_filename = Path(sig_file).name
            # Corresponding package filename is the signature filename without .sig
            pkg_filename = sig_filename[:-4]  # Remove .sig extension
            
            # Check if this signature is for a package (not database)
            if pkg_filename.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                if pkg_filename not in package_files:
                    orphaned_signatures.append(sig_file)
        
        if not orphaned_signatures:
            logger.info("✅ No orphaned signatures found on VPS")
            return len(package_files), len(signature_files), 0
        
        logger.info(f"Found {len(orphaned_signatures)} orphaned signatures to delete")
        
        # Delete orphaned signatures in batches
        batch_size = 50
        deleted_count = 0
        deletion_status = 0
        
        for i in range(0, len(orphaned_signatures), batch_size):
            batch = orphaned_signatures[i:i + batch_size]
            if self._delete_files_remote(batch):
                deleted_count += len(batch)
            else:
                deletion_status = 1  # Mark failure
        
        # Log final status (privacy-safe)
        logger.info(f"VPS orphan sweep complete:")
        logger.info(f"  remote_dir_hash: {remote_dir_hash}")
        logger.info(f"  package_files_count: {len(package_files)}")
        logger.info(f"  signature_files_count: {len(signature_files)}")
        logger.info(f"  orphaned_signatures_found: {len(orphaned_signatures)}")
        logger.info(f"  deleted_orphan_signatures_count: {deleted_count}")
        logger.info(f"  deletion_exit_status: {deletion_status}")
        
        if deletion_status == 0:
            logger.info("✅ VPS orphan signature sweep completed successfully")
        else:
            logger.error("❌ VPS orphan signature sweep had failures")
        
        return len(package_files), len(signature_files), deleted_count
    
    def server_cleanup(self, version_tracker, desired_inventory: Optional[Set[str]] = None):
        """
        🚨 ZERO-RESIDUE SERVER CLEANUP: Remove zombie packages from VPS 
        using TARGET VERSIONS as SOURCE OF TRUTH with desired inventory guard.
        
        Only keeps packages that match registered target versions.
        Adds safety guard: NEVER delete a package whose pkgname is in desired_inventory.
        
        IMPROVED OBSERVABILITY: Logs first 20 basenames when deletions occur.
        
        Args:
            version_tracker: VersionTracker instance with target versions
            desired_inventory: Set of package names that should exist in repository (optional)
        """
        logger.info("Server cleanup: Removing zombie packages from VPS with desired inventory guard...")
        
        # Check if we have any target versions registered
        if not version_tracker._package_target_versions:
            logger.warning("No target versions registered - skipping server cleanup")
            return
        
        logger.info(f"Zero-Residue cleanup initiated with {len(version_tracker._package_target_versions)} target versions")
        if desired_inventory:
            logger.info(f"Desired inventory guard enabled with {len(desired_inventory)} package names")
        
        # Get ALL files from VPS (including signatures)
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory")
            return
        
        if not vps_files:
            logger.info("No files found on VPS - nothing to clean up")
            return
        
        # First, identify and delete orphaned signatures (signatures without corresponding packages)
        orphaned_sigs_deleted = self._cleanup_orphaned_signatures_vps(vps_files)
        if orphaned_sigs_deleted > 0:
            logger.info(f"Deleted {orphaned_sigs_deleted} orphaned signatures from VPS")
        
        # Refresh file list after orphan cleanup
        vps_files = self._get_vps_file_inventory()
        if not vps_files:
            logger.info("No files remaining on VPS after orphan cleanup")
            return
        
        # Import SmartCleanup for package name extraction
        from modules.repo.smart_cleanup import SmartCleanup
        
        # Identify files to keep based on target versions with desired inventory guard
        files_to_keep = set()
        files_to_delete = []
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            
            # Skip database and signature files from deletion logic (handled separately)
            is_db_or_sig = any(filename.endswith(ext) for ext in ['.db', '.db.tar.gz', '.sig', '.files', '.files.tar.gz'])
            if is_db_or_sig:
                files_to_keep.add(filename)
                continue
            
            # Extract package name from filename
            pkg_name = SmartCleanup.extract_package_name_from_filename(filename)
            
            if not pkg_name:
                # Can't parse, keep to be safe
                files_to_keep.add(filename)
                continue
            
            # SAFETY GUARD: Check if package is in desired inventory
            if desired_inventory and pkg_name in desired_inventory:
                # Package is in desired inventory, keep it even if no target version
                files_to_keep.add(filename)
                logger.info(f"Guard keep: {filename} (pkgname {pkg_name} in desired inventory)")
                continue
            
            # Check if this package has a target version
            # We only check by pkgname, not full version (simpler logic for server)
            if pkg_name in version_tracker._package_target_versions:
                # Keep the file (version cleanup is handled elsewhere)
                files_to_keep.add(filename)
                logger.debug(f"Keeping {filename} (has target version)")
            else:
                # No target version registered for this package
                # Check if it's in our skipped packages
                if pkg_name in version_tracker._skipped_packages:
                    files_to_keep.add(filename)
                    logger.debug(f"Keeping {filename} (skipped package)")
                else:
                    # Not in target versions or skipped packages - mark for deletion
                    files_to_delete.append(vps_file)
                    logger.info(f"Marking for deletion: {filename} (not in target versions)")
        
        # Execute deletion with improved observability
        if not files_to_delete:
            logger.info("No zombie packages found on VPS")
            return
        
        logger.info(f"Identified {len(files_to_delete)} zombie packages for deletion")
        
        # IMPROVED OBSERVABILITY: Log first 20 basenames
        if files_to_delete:
            logger.info(f"Deleting {len(files_to_delete)} remote files (showing first 20):")
            for i, vps_file in enumerate(files_to_delete[:20]):
                filename = Path(vps_file).name
                logger.info(f"  [{i+1}] {filename}")
            if len(files_to_delete) > 20:
                logger.info(f"  ... and {len(files_to_delete) - 20} more")
        
        # Delete files in batches
        batch_size = 50
        deleted_count = 0
        
        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i:i + batch_size]
            if self._delete_files_remote(batch):
                deleted_count += len(batch)
        
        logger.info(f"Server cleanup complete: Deleted {deleted_count} zombie packages")
        
        # After deleting packages, clean up any signatures for deleted packages
        self._cleanup_orphaned_signatures_vps()
    
    def _cleanup_orphaned_signatures_vps(self, vps_files: Optional[List[str]] = None) -> int:
        """
        Clean up orphaned signature files on VPS (signatures without corresponding packages).
        
        Args:
            vps_files: List of VPS files (if None, will fetch from server)
        
        Returns:
            Number of orphaned signatures deleted
        """
        logger.info("🔍 Sweeping for orphaned signatures on VPS...")
        
        if vps_files is None:
            vps_files = self._get_vps_file_inventory()
            if not vps_files:
                return 0
        
        # Separate package files and signature files
        package_files = set()
        signature_files = []
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            if filename.endswith('.sig'):
                signature_files.append(vps_file)
            elif filename.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                package_files.add(filename)
        
        logger.info(f"Found {len(signature_files)} signature files and {len(package_files)} package files on VPS")
        
        # Identify orphaned signatures (signatures without corresponding package)
        orphaned_signatures = []
        for sig_file in signature_files:
            sig_filename = Path(sig_file).name
            # Corresponding package filename is the signature filename without .sig
            pkg_filename = sig_filename[:-4]  # Remove .sig extension
            
            # Check if this signature is for a package (not database)
            if pkg_filename.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                if pkg_filename not in package_files:
                    orphaned_signatures.append(sig_file)
                    logger.info(f"Orphaned signature: {sig_filename} (package {pkg_filename} not found)")
        
        if not orphaned_signatures:
            logger.info("✅ No orphaned signatures found on VPS")
            return 0
        
        logger.info(f"Found {len(orphaned_signatures)} orphaned signatures to delete")
        
        # Delete orphaned signatures in batches
        batch_size = 50
        deleted_count = 0
        
        for i in range(0, len(orphaned_signatures), batch_size):
            batch = orphaned_signatures[i:i + batch_size]
            if self._delete_files_remote(batch):
                deleted_count += len(batch)
        
        logger.info(f"✅ Deleted {deleted_count} orphaned signatures from VPS")
        return deleted_count
    
    def _get_vps_file_inventory(self) -> Optional[List[str]]:
        """Get complete inventory of all files on VPS"""
        logger.info("Getting complete VPS file inventory...")
        
        remote_cmd = rf"""
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
                return None
            
            vps_files_raw = result.stdout.strip()
            if not vps_files_raw:
                logger.info("No files found on VPS")
                return []
            
            vps_files = [f.strip() for f in vps_files_raw.split('\n') if f.strip()]
            logger.info(f"Found {len(vps_files)} files on VPS")
            return vps_files
            
        except subprocess.TimeoutExpired:
            logger.error("SSH timeout getting VPS file inventory")
            return None
        except Exception as e:
            logger.error(f"Error getting VPS file inventory: {e}")
            return None
    
    def _delete_files_remote(self, files_to_delete: List[str]) -> bool:
        """Delete files from remote server"""
        if not files_to_delete:
            return True
        
        # Quote each filename for safety
        quoted_files = [f"'{f}'" for f in files_to_delete]
        files_to_delete_str = ' '.join(quoted_files)
        
        delete_cmd = f"rm -fv {files_to_delete_str}"
        
        logger.info(f"Executing deletion command for {len(files_to_delete)} files")
        
        # Execute the deletion command
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
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"Deletion successful for batch of {len(files_to_delete)} files")
                return True
            else:
                logger.error(f"Deletion failed: {result.stderr[:500]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("SSH command timed out - aborting cleanup for safety")
            return False
        except Exception as e:
            logger.error(f"Error during deletion: {e}")
            return False
    
    def cleanup_database_files(self):
        """Clean up old database files from output directory"""
        logger.info("Cleaning up old database files...")
        
        db_patterns = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz",
            f"{self.repo_name}.db.sig",
            f"{self.repo_name}.db.tar.gz.sig",
            f"{self.repo_name}.files.sig",
            f"{self.repo_name}.files.tar.gz.sig"
        ]
        
        deleted_count = 0
        for pattern in db_patterns:
            db_file = self.output_dir / pattern
            if db_file.exists():
                try:
                    db_file.unlink()
                    logger.info(f"Removed database file: {pattern}")
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete {pattern}: {e}")
        
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old database files")
        else:
            logger.info("No old database files to clean up")