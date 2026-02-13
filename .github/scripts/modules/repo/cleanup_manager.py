"""
Cleanup Manager Module - Handles Zero-Residue policy and server cleanup ONLY
WITH IMPROVED DELETION OBSERVABILITY AND VERSION NORMALIZATION

CRITICAL: Version cleanup logic has been moved to SmartCleanup.
This module now handles ONLY:
1. Server cleanup (VPS zombie package removal)
2. Database file maintenance
3. VPS hygiene (extras classification and safe deletion)
"""

import os
import subprocess
import shutil
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple, Dict
import re

logger = logging.getLogger(__name__)


class CleanupManager:
    """
    Manages server-side cleanup operations ONLY.
    
    CRITICAL: Version cleanup is now handled by SmartCleanup.
    This module only handles:
    1. Server cleanup (removing zombie packages from VPS)
    2. Database file maintenance
    3. VPS hygiene (safe extras removal)
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
    
    def _normalize_version_for_comparison(self, version_str: str) -> str:
        """
        Normalize version string for comparison by ensuring epoch is present.
        
        Rules:
        - If version already contains ':', keep it as is (e.g., "1:r1797.88f5a8a-1")
        - If version doesn't contain ':', prepend "0:" (e.g., "5.15.4-1" -> "0:5.15.4-1")
        - Trim whitespace
        
        Args:
            version_str: Raw version string (may or may not have epoch)
            
        Returns:
            Normalized version string with guaranteed epoch
        """
        if not version_str:
            return version_str
        
        # Trim whitespace
        version_str = version_str.strip()
        
        # If already contains ':', return as is (already has epoch)
        if ':' in version_str:
            return version_str
        
        # No epoch found, prepend "0:"
        return f"0:{version_str}"
    
    def version_prune_vps(self, version_tracker, desired_inventory: Optional[Set[str]] = None):
        """
        🚨 STRICT VPS ZERO-RESIDUE VERSION PRUNE:
        When a package has a newer target/latest version, any older versions MUST be deleted from VPS.
        
        FIXED: Compare NORMALIZED versions (epoch-less target versions treated as epoch 0).
        
        NEW: Improved decision logging with normalized versions:
        VPS_PRUNE_DECISION: pkg=<pkg> file=<basename> vps_ver=<ver> target_ver=<target_or_NONE> 
                          vps_norm=<norm> target_norm=<norm_or_NONE> desired=<0/1> action=KEEP/DELETE reason=<...>
        
        Args:
            version_tracker: VersionTracker instance with target versions
            desired_inventory: Set of package names that should exist in repository
        """
        logger.info("STRICT VPS VERSION PRUNE: Removing old package versions from VPS...")
        
        # Get ALL files from VPS (including signatures)
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory")
            return
        
        if not vps_files:
            logger.info("No files found on VPS - nothing to prune")
            return
        
        # Separate package files and signature files
        package_files = []
        signature_files = []
        signature_map = {}  # package_filename -> signature_file_path
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            if filename.endswith('.sig'):
                signature_files.append(vps_file)
                # Map signature to package file
                pkg_filename = filename[:-4]  # Remove .sig extension
                signature_map[pkg_filename] = vps_file
            elif filename.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                package_files.append(vps_file)
        
        logger.info(f"Found {len(package_files)} package files and {len(signature_files)} signatures on VPS")
        
        # Parse package files and group by pkgname
        packages_by_name: Dict[str, List[Tuple[str, str, str]]] = {}  # pkgname -> [(file_path, filename, version)]
        
        for vps_file in package_files:
            filename = Path(vps_file).name
            pkg_name, file_version = version_tracker.parse_package_filename(filename)
            
            if not pkg_name or not file_version:
                # Cannot parse, skip to be safe
                logger.warning(f"Cannot parse package filename: {filename}, skipping")
                continue
            
            if pkg_name not in packages_by_name:
                packages_by_name[pkg_name] = []
            
            packages_by_name[pkg_name].append((vps_file, filename, file_version))
        
        # Determine files to delete based on strict version pruning rules
        files_to_delete = []
        deleted_count = 0
        
        for pkg_name, packages in packages_by_name.items():
            target_version = version_tracker.get_target_version(pkg_name)
            target_norm = self._normalize_version_for_comparison(target_version) if target_version else None
            is_desired = desired_inventory and pkg_name in desired_inventory
            
            # Log prune decision for each file
            for vps_file, filename, file_version in packages:
                file_norm = self._normalize_version_for_comparison(file_version)
                
                if target_version:
                    if file_norm == target_norm:
                        # This matches the target version - keep it
                        logger.info(f"VPS_PRUNE_DECISION: pkg={pkg_name} file={filename} "
                                  f"vps_ver={file_version} target_ver={target_version} "
                                  f"vps_norm={file_norm} target_norm={target_norm} "
                                  f"desired={1 if is_desired else 0} "
                                  f"action=KEEP reason=target_version_match_normalized")
                    else:
                        # Different version - mark for deletion
                        logger.info(f"VPS_PRUNE_DECISION: pkg={pkg_name} file={filename} "
                                  f"vps_ver={file_version} target_ver={target_version} "
                                  f"vps_norm={file_norm} target_norm={target_norm} "
                                  f"desired={1 if is_desired else 0} "
                                  f"action=DELETE reason=old_version_not_target_normalized")
                        files_to_delete.append(vps_file)
                        deleted_count += 1
                        
                        # Also delete corresponding signature if exists
                        if filename in signature_map:
                            files_to_delete.append(signature_map[filename])
                else:
                    # No target version registered for this package
                    if is_desired:
                        # Package is in desired inventory but no target version - KEEP
                        logger.info(f"VPS_PRUNE_DECISION: pkg={pkg_name} file={filename} "
                                  f"vps_ver={file_version} target_ver=NONE "
                                  f"vps_norm={file_norm} target_norm=NONE "
                                  f"desired=1 action=KEEP reason=desired_guard_no_target")
                    else:
                        # Package not in desired inventory - DELETE
                        logger.info(f"VPS_PRUNE_DECISION: pkg={pkg_name} file={filename} "
                                  f"vps_ver={file_version} target_ver=NONE "
                                  f"vps_norm={file_norm} target_norm=NONE "
                                  f"desired=0 action=DELETE reason=out_of_policy")
                        files_to_delete.append(vps_file)
                        deleted_count += 1
                        
                        # Also delete corresponding signature if exists
                        if filename in signature_map:
                            files_to_delete.append(signature_map[filename])
        
        # Also handle database/signature files - always keep them
        for vps_file in vps_files:
            filename = Path(vps_file).name
            # Database and signature files are handled by signature_map and package deletions
            # But keep any database files that weren't already processed
            if (filename.startswith(f"{self.repo_name}.db") or 
                filename.startswith(f"{self.repo_name}.files")):
                # Check if it's a .sig file for a database
                if filename.endswith('.sig'):
                    # Keep database signature files
                    continue
                else:
                    # Keep database files
                    logger.info(f"VPS_PRUNE_DECISION: pkg={self.repo_name} file={filename} vps_ver=db "
                              f"target_ver=db vps_norm=db target_norm=db desired=1 action=KEEP reason=db")
        
        # Execute deletion in batches
        if not files_to_delete:
            logger.info("No files to delete in version prune")
            logger.info(f"VPS_PRUNE_DELETED_COUNT=0")
            return
        
        logger.info(f"STRICT VERSION PRUNE: Deleting {len(files_to_delete)} files ({deleted_count} packages + signatures)")
        
        # IMPROVED OBSERVABILITY: Log first 20 basenames
        logger.info(f"Deleting files (showing first 20):")
        for i, vps_file in enumerate(files_to_delete[:20]):
            filename = Path(vps_file).name
            logger.info(f"  [{i+1}] {filename}")
        if len(files_to_delete) > 20:
            logger.info(f"  ... and {len(files_to_delete) - 20} more")
        
        # Delete files in batches
        batch_size = 50
        actual_deleted = 0
        
        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i:i + batch_size]
            if self._delete_files_remote(batch):
                actual_deleted += len(batch)
        
        logger.info(f"STRICT VERSION PRUNE: Deleted {actual_deleted} files")
        logger.info(f"VPS_PRUNE_DELETED_COUNT={actual_deleted}")
        
        # After deleting packages, clean up any orphaned signatures
        self._cleanup_orphaned_signatures_vps()
    
    def server_cleanup(self, version_tracker, desired_inventory: Optional[Set[str]] = None):
        """
        DEPRECATED: Use version_prune_vps instead.
        This function is kept for backward compatibility but now calls version_prune_vps.
        
        Args:
            version_tracker: VersionTracker instance with target versions
            desired_inventory: Set of package names that should exist in repository
        """
        logger.warning("server_cleanup is deprecated, using version_prune_vps instead")
        self.version_prune_vps(version_tracker, desired_inventory)
    
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
    
    # =========================================================================
    # VPS HYGIENE (P0) - Safe removal of extra files on VPS
    # =========================================================================
    def _parse_package_filename(self, filename: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse package name and version from a package filename.
        Works with both .pkg.tar.zst and .pkg.tar.xz.
        Returns (pkgname, version) where version is pkgver-pkgrel (with possible epoch).
        """
        # Remove extensions
        if filename.endswith('.pkg.tar.zst'):
            base = filename[:-12]
        elif filename.endswith('.pkg.tar.xz'):
            base = filename[:-11]
        else:
            return None, None
        
        # Remove known architecture suffixes from the end
        arch_patterns = [r'-x86_64$', r'-any$', r'-i686$', r'-aarch64$', r'-armv7h$', r'-armv6h$']
        for pattern in arch_patterns:
            base = re.sub(pattern, '', base)
        
        # Split by hyphens
        parts = base.split('-')
        if len(parts) < 3:
            return None, None
        
        # Find where version starts: the part before the last three fields (pkgver, pkgrel, arch)
        # After stripping arch, the last two parts are pkgver and pkgrel.
        # So pkgname is everything before the last two parts.
        # But epoch may be present, making pkgver contain ':'.
        # The last part is pkgrel, the second-last is pkgver.
        pkgrel = parts[-1]
        pkgver = parts[-2]
        # pkgname is everything before that
        pkgname = '-'.join(parts[:-2])
        version = f"{pkgver}-{pkgrel}"
        return pkgname, version
    
    def run_vps_hygiene(self, remote_dir: str, repo_name: str, desired_inventory: Set[str],
                        keep_latest_versions: int = 1, dry_run: bool = True,
                        keep_extra_metadata: bool = True):
        """
        Perform safe VPS hygiene cleanup:
          - Never delete DB/files artifacts or their signatures.
          - Remove orphan signatures (.sig whose base file is missing).
          - For packages in desired_inventory: keep only newest KEEP_LATEST_VERSIONS per pkgname.
          - For packages NOT in desired_inventory: only log, never delete.
          - If keep_extra_metadata is True, do not delete *.pub, *.key, etc.
          - Log all deletion candidates with reason.
        
        Args:
            remote_dir: Remote directory on VPS.
            repo_name: Repository name.
            desired_inventory: Set of valid package names (from PKGBUILD extraction).
            keep_latest_versions: Number of latest versions to keep per package.
            dry_run: If True, only log what would be deleted, do not actually delete.
            keep_extra_metadata: If True, never delete public key/metadata files.
        """
        logger.info(f"VPS_HYGIENE: starting (dry_run={dry_run}, keep_latest={keep_latest_versions}, keep_metadata={keep_extra_metadata})")
        
        # Get all remote files
        remote_files = self._get_vps_file_inventory()
        if remote_files is None:
            logger.error("VPS_HYGIENE: cannot get remote file list")
            return
        if not remote_files:
            logger.info("VPS_HYGIENE: no files on VPS")
            return
        
        # Prepare structures
        db_artifacts = set()        # repo_name.db*, repo_name.files* (including .sig)
        metadata_files = set()       # *.pub, *.key, etc.
        package_files = []           # list of (full_path, basename, pkgname, version)
        signature_map = {}           # basename -> full_path for .sig files
        unknown = set()
        
        repo_prefix = repo_name
        for fpath in remote_files:
            fname = Path(fpath).name
            if fname.startswith(f"{repo_prefix}.db") or fname.startswith(f"{repo_prefix}.files"):
                db_artifacts.add(fpath)
            elif fname.endswith(('.pub', '.key')):
                metadata_files.add(fpath)
            elif fname.endswith('.sig'):
                signature_map[fname] = fpath
            elif fname.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                pkgname, version = self._parse_package_filename(fname)
                if pkgname and version:
                    package_files.append((fpath, fname, pkgname, version))
                else:
                    unknown.add(fpath)
            else:
                unknown.add(fpath)
        
        # 1. DB artifacts: never delete
        if db_artifacts:
            logger.info(f"VPS_HYGIENE: keeping {len(db_artifacts)} database artifacts")
        
        # 2. Metadata files: delete only if keep_extra_metadata is False
        if keep_extra_metadata:
            logger.info(f"VPS_HYGIENE: keeping {len(metadata_files)} metadata files (keep_extra_metadata=True)")
        else:
            if metadata_files:
                logger.info(f"VPS_HYGIENE: would delete {len(metadata_files)} metadata files (dry_run={dry_run})")
                for fpath in metadata_files:
                    logger.info(f"VPS_HYGIENE_DELETE candidate={Path(fpath).name} reason=metadata_file dry_run={1 if dry_run else 0}")
                if not dry_run:
                    self._delete_files_remote(list(metadata_files))
        
        # 3. Orphan signatures: delete signatures whose base package file is missing
        base_pkg_filenames = {fname for (_, fname, _, _) in package_files}
        orphan_sigs = []
        for sig_fname, sig_fpath in signature_map.items():
            # Signature base is sig_fname without .sig
            base_fname = sig_fname[:-4]
            if base_fname not in base_pkg_filenames:
                orphan_sigs.append(sig_fpath)
        
        if orphan_sigs:
            logger.info(f"VPS_HYGIENE: found {len(orphan_sigs)} orphan signatures")
            for fpath in orphan_sigs:
                logger.info(f"VPS_HYGIENE_DELETE candidate={Path(fpath).name} reason=orphan_sig dry_run={1 if dry_run else 0}")
            if not dry_run:
                self._delete_files_remote(orphan_sigs)
        
        # 4. Package version pruning for desired inventory only
        # Group packages by pkgname (only those in desired_inventory)
        packages_by_name: Dict[str, List[Tuple[str, str, str]]] = {}  # pkgname -> [(full_path, version, basename)]
        for fpath, fname, pkgname, version in package_files:
            if pkgname in desired_inventory:
                if pkgname not in packages_by_name:
                    packages_by_name[pkgname] = []
                packages_by_name[pkgname].append((fpath, version, fname))
            else:
                # Package not in desired inventory: only log, never delete
                logger.info(f"VPS_HYGIENE: package {pkgname} not in desired inventory, keeping {fname}")
        
        # For each pkgname in desired_inventory, keep only the newest keep_latest_versions
        pkgs_to_delete = []
        for pkgname, pkg_entries in packages_by_name.items():
            if len(pkg_entries) <= keep_latest_versions:
                continue
            # Sort by version (using vercmp). We'll use subprocess for comparison.
            # Create list of (version, fpath, fname)
            entries_with_version = [(v, fp, fn) for (fp, v, fn) in pkg_entries]
            # Sort descending (newest first)
            sorted_entries = sorted(entries_with_version, key=lambda x: x[0], reverse=False)  # Placeholder, we'll actually compare with vercmp
            
            # Custom sort with vercmp
            import functools
            def vercmp_key(a, b):
                # a and b are (version, ...) tuples
                try:
                    res = subprocess.run(['vercmp', a[0], b[0]], capture_output=True, text=True, check=False)
                    if res.returncode == 0:
                        return int(res.stdout.strip())
                except:
                    pass
                # fallback: string compare
                return (a[0] > b[0]) - (a[0] < b[0])
            
            # Sort descending (newest first)
            sorted_entries = sorted(entries_with_version, key=functools.cmp_to_key(lambda x,y: -vercmp_key(x,y)))
            
            keep = sorted_entries[:keep_latest_versions]
            delete_candidates = sorted_entries[keep_latest_versions:]
            
            for (version, fpath, fname) in delete_candidates:
                pkgs_to_delete.append(fpath)
                logger.info(f"VPS_HYGIENE_DELETE candidate={fname} reason=old_version (keeping newest {keep_latest_versions}) dry_run={1 if dry_run else 0}")
                # Also delete corresponding signature if exists
                sig_fname = fname + '.sig'
                if sig_fname in signature_map:
                    pkgs_to_delete.append(signature_map[sig_fname])
                    logger.info(f"VPS_HYGIENE_DELETE candidate={sig_fname} reason=old_version_signature dry_run={1 if dry_run else 0}")
        
        # Execute deletions for package pruning
        if pkgs_to_delete:
            logger.info(f"VPS_HYGIENE: would delete {len(pkgs_to_delete)} files from version pruning (dry_run={dry_run})")
            if not dry_run:
                self._delete_files_remote(pkgs_to_delete)
        
        # 5. Unknown files: log them but do not delete by default (could be added later)
        if unknown:
            logger.info(f"VPS_HYGIENE: found {len(unknown)} unknown files (not classified)")
            for fpath in unknown:
                logger.info(f"VPS_HYGIENE_UNKNOWN candidate={Path(fpath).name}")
        
        logger.info("VPS_HYGIENE: completed")