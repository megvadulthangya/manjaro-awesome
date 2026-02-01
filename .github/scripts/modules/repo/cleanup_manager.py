# FILE: .github/scripts/modules/repo/cleanup_manager.py
"""
Cleanup Manager Module - Handles Zero-Residue policy and server cleanup ONLY

CRITICAL: Version cleanup logic has been moved to SmartCleanup.
This module now handles ONLY:
- Server cleanup (VPS zombie package removal)
- Database file cleanup
"""

import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Optional

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
    
    def revalidate_output_dir_before_database(self):
        """
        🚨 PRE-DATABASE VALIDATION: Remove outdated package versions and orphaned signatures.
        Operates ONLY on output_dir.
        
        Enforces:
        - Only the latest version of each package remains.
        - Orphaned .sig files (without a package) are removed.
        """
        logger.info("🚨 PRE-DATABASE VALIDATION: Starting output_dir revalidation...")
        
        # Import SmartCleanup here to avoid circular imports
        from modules.repo.smart_cleanup import SmartCleanup
        
        # Create SmartCleanup instance for output_dir cleanup
        smart_cleanup = SmartCleanup(self.repo_name, self.output_dir)
        
        # Step 1: Remove old package versions (keep only newest per package)
        smart_cleanup.remove_old_package_versions()
        
        # Step 2: Remove orphaned .sig files
        self._remove_orphaned_signatures()
        
        logger.info("✅ PRE-DATABASE VALIDATION: Output directory revalidated successfully.")
    
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
    
    def server_cleanup(self, version_tracker):
        """
        🚨 ZERO-RESIDUE SERVER CLEANUP: Remove zombie packages from VPS 
        using TARGET VERSIONS as SOURCE OF TRUTH.
        
        Only keeps packages that match registered target versions.
        """
        logger.info("Server cleanup: Removing zombie packages from VPS...")
        
        # Check if we have any target versions registered
        if not version_tracker._package_target_versions:
            logger.warning("No target versions registered - skipping server cleanup")
            return
        
        logger.info(f"Zero-Residue cleanup initiated with {len(version_tracker._package_target_versions)} target versions")
        
        # Get ALL files from VPS
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory")
            return
        
        if not vps_files:
            logger.info("No files found on VPS - nothing to clean up")
            return
        
        # Identify files to keep based on target versions
        files_to_keep = set()
        files_to_delete = []
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            
            # Skip database and signature files from deletion logic
            is_db_or_sig = any(filename.endswith(ext) for ext in ['.db', '.db.tar.gz', '.sig', '.files', '.files.tar.gz'])
            if is_db_or_sig:
                files_to_keep.add(filename)
                continue
            
            # Simple package name extraction (basic logic)
            # CRITICAL: Full version parsing is done by SmartCleanup
            # This is just for server cleanup matching
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            # Try to extract pkgname (everything before version)
            pkg_name = None
            for i in range(len(parts) - 3, 0, -1):
                potential_name = '-'.join(parts[:i])
                remaining = parts[i:]
                
                if len(remaining) >= 3:
                    # Check if remaining parts look like version-release-arch
                    if remaining[0].isdigit() or any(c.isdigit() for c in remaining[0]):
                        pkg_name = potential_name
                        break
            
            if not pkg_name:
                # Can't parse, keep to be safe
                files_to_keep.add(filename)
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
        
        # Execute deletion
        if not files_to_delete:
            logger.info("No zombie packages found on VPS")
            return
        
        logger.info(f"Identified {len(files_to_delete)} zombie packages for deletion")
        
        # Delete files in batches
        batch_size = 50
        deleted_count = 0
        
        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i:i + batch_size]
            if self._delete_files_remote(batch):
                deleted_count += len(batch)
        
        logger.info(f"Server cleanup complete: Deleted {deleted_count} zombie packages")
    
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