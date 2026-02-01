import os
import re
import subprocess
import logging
from pathlib import Path
from typing import List, Set, Optional, Tuple

logger = logging.getLogger(__name__)


class SmartCleanup:
    """
    Smart cleanup logic for repository management.
    
    Core rules:
    1. Deletion based ONLY on PKGBUILD pkgname extraction (allowlist)
    2. Never based on packages.py strings
    3. Remove deleted files from repo database
    """
    
    def __init__(self, repo_name: str, output_dir: Path):
        """
        Initialize SmartCleanup with repository configuration.
        
        Args:
            repo_name: Name of the repository
            output_dir: Local output directory containing packages
        """
        self.repo_name = repo_name
        self.output_dir = output_dir
    
    def extract_package_name_from_filename(self, filename: str) -> Optional[str]:
        """
        Extract package name from package filename.
        
        Args:
            filename: Package filename (e.g., 'package-1.0-1-x86_64.pkg.tar.zst')
            
        Returns:
            Package name or None if cannot parse
        """
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            # Package name is everything before version-release-arch
            # Handle both standard and epoch formats
            for i in range(len(parts) - 3, 0, -1):
                potential_name = '-'.join(parts[:i])
                
                # Check if remaining parts look like version-release-arch
                remaining = parts[i:]
                if len(remaining) >= 3:
                    # Check for epoch format (e.g., "2-26.1.9-1")
                    if remaining[0].isdigit() and '-' in '-'.join(remaining[1:]):
                        # Valid epoch format
                        return potential_name
                    # Standard format (e.g., "26.1.9-1")
                    elif any(c.isdigit() for c in remaining[0]) and remaining[1].isdigit():
                        # Valid standard format
                        return potential_name
        
        except Exception as e:
            logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None
    
    def identify_obsolete_files(
        self, 
        vps_files: List[str], 
        allowlist: Set[str]
    ) -> Tuple[List[str], List[str]]:
        """
        Compare VPS files against allowlist to identify obsolete files.
        
        Args:
            vps_files: List of VPS repository filenames
            allowlist: Set of valid package names from PKGBUILD extraction
            
        Returns:
            Tuple of (files_to_keep, files_to_delete)
        """
        files_to_keep = []
        files_to_delete = []
        
        for filename in vps_files:
            # Skip non-package files (db, sig, etc.)
            if not filename.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                files_to_keep.append(filename)
                continue
            
            # Extract package name from filename
            pkg_name = self.extract_package_name_from_filename(filename)
            
            if not pkg_name:
                # Cannot parse, keep to be safe
                logger.warning(f"⚠️ Could not parse package name from {filename}, keeping")
                files_to_keep.append(filename)
                continue
            
            # Check if package name is in allowlist
            if pkg_name in allowlist:
                files_to_keep.append(filename)
                logger.debug(f"✅ Keeping {filename} (allowlist: {pkg_name})")
            else:
                files_to_delete.append(filename)
                logger.info(f"🗑️ Marking for deletion: {filename} (not in allowlist)")
        
        return files_to_keep, files_to_delete
    
    def delete_obsolete_files(
        self, 
        files_to_delete: List[str],
        remote_dir: str,
        vps_user: str,
        vps_host: str
    ) -> bool:
        """
        Delete obsolete files from remote server.
        
        Args:
            files_to_delete: List of files to delete
            remote_dir: Remote directory on VPS
            vps_user: VPS username
            vps_host: VPS hostname
            
        Returns:
            True if successful, False otherwise
        """
        if not files_to_delete:
            logger.info("✅ No obsolete files to delete")
            return True
        
        logger.info(f"🚀 Preparing to delete {len(files_to_delete)} obsolete files")
        
        # Delete in batches to avoid command line length limits
        batch_size = 50
        deleted_count = 0
        
        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i:i + batch_size]
            if self._delete_batch_remote(batch, remote_dir, vps_user, vps_host):
                deleted_count += len(batch)
        
        logger.info(f"📊 Cleanup complete: Deleted {deleted_count} obsolete files")
        return deleted_count > 0
    
    def _delete_batch_remote(
        self, 
        batch: List[str], 
        remote_dir: str,
        vps_user: str,
        vps_host: str
    ) -> bool:
        """Delete a batch of files from remote server."""
        # Quote each filename for safety
        quoted_files = [f"'{remote_dir}/{f}'" for f in batch]
        files_to_delete_str = ' '.join(quoted_files)
        
        delete_cmd = f"rm -fv {files_to_delete_str}"
        
        # Execute the deletion command via SSH
        ssh_cmd = [
            "ssh",
            f"{vps_user}@{vps_host}",
            delete_cmd
        ]
        
        try:
            logger.info(f"🗑️ Deleting batch of {len(batch)} files")
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Deletion successful for batch of {len(batch)} files")
                if result.stdout:
                    for line in result.stdout.splitlines():
                        if "removed" in line.lower():
                            logger.info(f"   {line}")
                return True
            else:
                logger.error(f"❌ Deletion failed: {result.stderr[:500]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("❌ SSH command timed out - aborting cleanup for safety")
            return False
        except Exception as e:
            logger.error(f"❌ Error during deletion: {e}")
            return False
    
    def remove_from_database(
        self,
        files_to_delete: List[str],
        repo_db_path: Optional[Path] = None
    ) -> bool:
        """
        Remove deleted packages from repository database.
        
        Args:
            files_to_delete: List of files that were deleted
            repo_db_path: Path to repository database file (optional)
            
        Returns:
            True if successful, False otherwise
        """
        if not files_to_delete:
            logger.info("✅ No database entries to remove")
            return True
        
        # Determine database file path
        if repo_db_path is None:
            repo_db_path = self.output_dir / f"{self.repo_name}.db.tar.gz"
        
        if not repo_db_path.exists():
            logger.warning(f"⚠️ Database file not found: {repo_db_path}")
            return False
        
        # Extract package names from deleted files
        packages_to_remove = set()
        for filename in files_to_delete:
            pkg_name = self.extract_package_name_from_filename(filename)
            if pkg_name:
                packages_to_remove.add(pkg_name)
        
        if not packages_to_remove:
            logger.warning("⚠️ No valid package names extracted from deleted files")
            return True
        
        logger.info(f"🗑️ Removing {len(packages_to_remove)} packages from database")
        
        # Use repo-remove to remove packages from database
        success_count = 0
        for pkg_name in packages_to_remove:
            if self._remove_package_from_db(pkg_name, repo_db_path):
                success_count += 1
        
        logger.info(f"📊 Database cleanup: Removed {success_count}/{len(packages_to_remove)} packages")
        return success_count > 0
    
    def _remove_package_from_db(self, pkg_name: str, repo_db_path: Path) -> bool:
        """Remove a single package from repository database using repo-remove."""
        try:
            # Check if repo-remove command is available
            if not shutil.which("repo-remove"):
                logger.error("❌ repo-remove command not found")
                return False
            
            cmd = ["repo-remove", str(repo_db_path), pkg_name]
            
            logger.debug(f"Running: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Removed {pkg_name} from database")
                return True
            else:
                logger.error(f"❌ Failed to remove {pkg_name} from database: {result.stderr[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error removing {pkg_name} from database: {e}")
            return False
    
    def execute_cleanup(
        self,
        vps_files: List[str],
        allowlist: Set[str],
        remote_dir: str,
        vps_user: str,
        vps_host: str,
        repo_db_path: Optional[Path] = None
    ) -> Tuple[bool, List[str]]:
        """
        Execute complete cleanup workflow.
        
        Args:
            vps_files: List of VPS repository filenames
            allowlist: Set of valid package names from PKGBUILD extraction
            remote_dir: Remote directory on VPS
            vps_user: VPS username
            vps_host: VPS hostname
            repo_db_path: Path to repository database file (optional)
            
        Returns:
            Tuple of (success: bool, deleted_files: List[str])
        """
        logger.info("🔍 Starting smart cleanup analysis")
        logger.info(f"📊 VPS files to analyze: {len(vps_files)}")
        logger.info(f"📊 Allowlist entries: {len(allowlist)}")
        
        # Step 1: Identify obsolete files
        files_to_keep, files_to_delete = self.identify_obsolete_files(vps_files, allowlist)
        
        if not files_to_delete:
            logger.info("✅ No obsolete files found")
            return True, []
        
        logger.info(f"📊 Analysis complete:")
        logger.info(f"   Files to keep: {len(files_to_keep)}")
        logger.info(f"   Files to delete: {len(files_to_delete)}")
        
        # Step 2: Delete obsolete files from remote
        deletion_success = self.delete_obsolete_files(
            files_to_delete, remote_dir, vps_user, vps_host
        )
        
        if not deletion_success:
            logger.error("❌ Failed to delete obsolete files")
            return False, files_to_delete
        
        # Step 3: Remove deleted packages from database
        db_success = self.remove_from_database(files_to_delete, repo_db_path)
        
        if not db_success:
            logger.warning("⚠️ Database cleanup had issues, but files were deleted")
        
        logger.info("✅ Smart cleanup completed successfully")
        return True, files_to_delete


# Optional: Helper function for direct usage
def execute_smart_cleanup(
    vps_files: List[str],
    allowlist: Set[str],
    repo_name: str,
    output_dir: Path,
    remote_dir: str,
    vps_user: str,
    vps_host: str
) -> Tuple[bool, List[str]]:
    """
    Convenience function to execute smart cleanup.
    
    Args:
        vps_files: List of VPS repository filenames
        allowlist: Set of valid package names from PKGBUILD extraction
        repo_name: Name of the repository
        output_dir: Local output directory containing packages
        remote_dir: Remote directory on VPS
        vps_user: VPS username
        vps_host: VPS hostname
        
    Returns:
        Tuple of (success: bool, deleted_files: List[str])
    """
    cleaner = SmartCleanup(repo_name, output_dir)
    return cleaner.execute_cleanup(
        vps_files=vps_files,
        allowlist=allowlist,
        remote_dir=remote_dir,
        vps_user=vps_user,
        vps_host=vps_host
    )


if __name__ == "__main__":
    # Example usage
    test_vps_files = [
        "package-a-1.0-1-x86_64.pkg.tar.zst",
        "package-b-2.0-1-x86_64.pkg.tar.zst",
        "package-c-3.0-1-x86_64.pkg.tar.zst",
        "repo.db.tar.gz",
        "repo.db.tar.gz.sig"
    ]
    
    test_allowlist = {"package-a", "package-c"}
    
    result = execute_smart_cleanup(
        vps_files=test_vps_files,
        allowlist=test_allowlist,
        repo_name="test-repo",
        output_dir=Path("/tmp/output"),
        remote_dir="/srv/http/repo",
        vps_user="user",
        vps_host="vps.example.com"
    )
    
    print(f"Cleanup result: {result}")