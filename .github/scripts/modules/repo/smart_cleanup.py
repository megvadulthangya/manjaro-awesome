"""
Smart Cleanup Module - Authoritative version-based cleanup system

Handles:
1. Version-based cleanup (keep only newest version per package)
2. Allowlist-based cleanup (remove packages not in allowlist)
3. Signature cleanup (remove invalid/old signatures)
"""

import os
import subprocess
import shutil
import re
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict
from functools import cmp_to_key

logger = logging.getLogger(__name__)


class SmartCleanup:
    """
    Authoritative cleanup system for repository management.
    
    Core rules:
    1. Only ONE version per pkgname may exist in output_dir
    2. Keep only the newest version (based on version comparison)
    3. Delete older versions and their .sig files
    4. Remove packages not in allowlist
    5. Delete invalid/old signature files
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
    
    @staticmethod
    def parse_package_filename(filename: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse package name and full version (epoch:pkgver-pkgrel) from filename.
        Returns (pkgname, version) or (None, None) on failure.
        """
        # Remove .pkg.tar.* suffix
        for ext in ['.pkg.tar.zst', '.pkg.tar.xz', '.pkg.tar.gz', '.pkg.tar.bz2', '.pkg.tar.lzo']:
            if filename.endswith(ext):
                base = filename[:-len(ext)]
                break
        else:
            return None, None

        # Remove architecture suffix
        arch_suffixes = ['-x86_64', '-any', '-i686', '-aarch64', '-armv7h', '-armv6h']
        for arch in arch_suffixes:
            if base.endswith(arch):
                base = base[:-len(arch)]
                break

        # Now split by hyphen; last part is pkgrel, second last is pkgver (may contain colon), rest is pkgname
        parts = base.split('-')
        if len(parts) < 3:
            return None, None

        pkgrel = parts[-1]
        pkgver = parts[-2]
        pkgname = '-'.join(parts[:-2])

        # pkgver may contain epoch, e.g., "2:1.0". That's fine.
        version = f"{pkgver}-{pkgrel}"
        return pkgname, version

    @staticmethod
    def extract_package_name_from_filename(filename: str) -> Optional[str]:
        """Extract package name from package filename."""
        pkgname, _ = SmartCleanup.parse_package_filename(filename)
        return pkgname

    @staticmethod
    def extract_version_from_filename(filename: str, pkg_name: str) -> Optional[str]:
        """
        Extract version from package filename.
        (pkg_name is ignored, kept for backward compatibility)
        """
        _, version = SmartCleanup.parse_package_filename(filename)
        return version

    def _compare_versions(self, version1: str, version2: str) -> int:
        """
        Compare two version strings using vercmp.
        
        Args:
            version1: First version string
            version2: Second version string
            
        Returns:
            -1 if version1 < version2, 0 if equal, 1 if version1 > version2
        """
        try:
            result = subprocess.run(
                ['vercmp', version1, version2],
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                cmp_result = int(result.stdout.strip())
                return cmp_result
        except Exception as e:
            logger.warning(f"vercmp failed, using fallback comparison: {e}")
        
        # Fallback: string comparison (less accurate)
        return 1 if version1 > version2 else -1 if version1 < version2 else 0

    def remove_old_package_versions(self):
        """
        🚨 AUTHORITATIVE VERSION CLEANUP: Keep only newest version per package
        
        For each pkgname:
        - Keep only the newest version
        - Delete older versions and their .sig files
        """
        logger.info("🔍 Starting version-based cleanup...")
        
        # Get all package files in output_dir
        package_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not package_files:
            logger.info("No package files found for version cleanup")
            return
        
        # Remove signature files from the list (we'll handle them separately)
        package_files = [f for f in package_files if not f.name.endswith('.sig')]
        
        # Group files by package name using robust parser
        packages_dict: Dict[str, List[Tuple[str, Path]]] = {}
        
        for pkg_file in package_files:
            pkg_name = self.extract_package_name_from_filename(pkg_file.name)
            if not pkg_name:
                logger.warning(f"Could not parse package name from {pkg_file.name}")
                continue
            
            version = self.extract_version_from_filename(pkg_file.name, pkg_name)
            if not version:
                logger.warning(f"Could not parse version from {pkg_file.name}")
                continue
            
            if pkg_name not in packages_dict:
                packages_dict[pkg_name] = []
            
            packages_dict[pkg_name].append((version, pkg_file))
        
        # Process each package
        total_deleted = 0
        
        for pkg_name, files in packages_dict.items():
            if len(files) <= 1:
                continue  # Only one version, nothing to do
            
            logger.info(f"Found {len(files)} versions for {pkg_name}: {[v[0] for v in files]}")
            
            # Find the newest version using version comparison
            # We need to sort by version descending
            def version_cmp(a, b):
                return self._compare_versions(b[0], a[0])  # descending
            files_sorted = sorted(files, key=cmp_to_key(version_cmp))
            newest_version, newest_file = files_sorted[0]
            older_files = files_sorted[1:]
            
            logger.info(f"Keeping newest version for {pkg_name}: {newest_version}")
            
            # Delete older versions
            for version, pkg_file in older_files:
                try:
                    # Delete package file
                    pkg_file.unlink()
                    logger.info(f"Removed old version: {pkg_file.name}")
                    
                    # Delete signature file if exists
                    sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                    if sig_file.exists():
                        sig_file.unlink()
                        logger.info(f"Removed signature: {sig_file.name}")
                    
                    total_deleted += 1
                except Exception as e:
                    logger.warning(f"Could not delete {pkg_file}: {e}")
        
        if total_deleted > 0:
            logger.info(f"✅ Version cleanup: Removed {total_deleted} old package versions")
        else:
            logger.info("✅ All packages have only one version")
    
    def remove_packages_not_in_allowlist(self, allowlist: Set[str]):
        """
        🚨 ALLOWLIST CLEANUP: Remove packages not in allowlist
        
        Args:
            allowlist: Set of valid package names from PKGBUILD extraction
        """
        logger.info("🔍 Starting allowlist-based cleanup...")
        
        # Get all package files in output_dir
        package_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not package_files:
            logger.info("No package files found for allowlist cleanup")
            return
        
        # Remove signature files from the list (we'll handle them separately)
        package_files = [f for f in package_files if not f.name.endswith('.sig')]
        
        deleted_count = 0
        
        for pkg_file in package_files:
            pkg_name = self.extract_package_name_from_filename(pkg_file.name)
            
            if not pkg_name:
                logger.warning(f"Could not parse package name from {pkg_file.name}")
                continue
            
            if pkg_name not in allowlist:
                try:
                    # Delete package file
                    pkg_file.unlink()
                    logger.info(f"Removed package not in allowlist: {pkg_file.name}")
                    
                    # Delete signature file if exists
                    sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                    if sig_file.exists():
                        sig_file.unlink()
                        logger.info(f"Removed signature: {sig_file.name}")
                    
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete {pkg_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ Allowlist cleanup: Removed {deleted_count} packages not in allowlist")
        else:
            logger.info("✅ All packages are in allowlist")
    
    def cleanup_invalid_signatures(self, gpg_handler):
        """
        🚨 SIGNATURE VALIDATION: Remove invalid signature files
        
        Args:
            gpg_handler: GPGHandler instance for signature verification
        """
        logger.info("🔍 Starting signature validation cleanup...")
        
        # Get all signature files
        sig_files = list(self.output_dir.glob("*.sig"))
        if not sig_files:
            logger.info("No signature files found")
            return
        
        invalid_count = 0
        
        for sig_file in sig_files:
            # Find corresponding package file (remove .sig extension)
            pkg_file = self.output_dir / sig_file.name[:-4]
            
            if not pkg_file.exists():
                logger.warning(f"Package file not found for signature: {sig_file.name}")
                try:
                    sig_file.unlink()
                    logger.info(f"Removed orphaned signature: {sig_file.name}")
                    invalid_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete orphaned signature {sig_file}: {e}")
                continue
            
            # Verify the signature
            if hasattr(gpg_handler, '_verify_signature'):
                if not gpg_handler._verify_signature(pkg_file, sig_file):
                    logger.warning(f"Invalid signature detected: {sig_file.name}")
                    try:
                        sig_file.unlink()
                        logger.info(f"Removed invalid signature: {sig_file.name}")
                        invalid_count += 1
                    except Exception as e:
                        logger.warning(f"Could not delete invalid signature {sig_file}: {e}")
            else:
                logger.debug(f"Skipping signature verification (gpg_handler missing _verify_signature)")
        
        if invalid_count > 0:
            logger.info(f"✅ Signature cleanup: Removed {invalid_count} invalid signatures")
        else:
            logger.info("✅ All signatures are valid")
    
    def execute_comprehensive_cleanup(self, allowlist: Set[str], gpg_handler=None):
        """
        Execute complete cleanup workflow.
        
        Args:
            allowlist: Set of valid package names from PKGBUILD extraction
            gpg_handler: GPGHandler instance for signature verification (optional)
        """
        logger.info("🚀 Starting comprehensive cleanup...")
        
        # Step 1: Version-based cleanup (keep only newest per package)
        self.remove_old_package_versions()
        
        # Step 2: Allowlist-based cleanup (remove packages not in allowlist)
        self.remove_packages_not_in_allowlist(allowlist)
        
        # Step 3: Signature validation (if gpg_handler is provided)
        if gpg_handler:
            self.cleanup_invalid_signatures(gpg_handler)
        
        logger.info("✅ Comprehensive cleanup completed successfully")
    
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
                logger.warning(f"Could not parse package name from {filename}, keeping")
                files_to_keep.append(filename)
                continue
            
            # Check if package name is in allowlist
            if pkg_name in allowlist:
                files_to_keep.append(filename)
                logger.debug(f"Keeping {filename} (allowlist: {pkg_name})")
            else:
                files_to_delete.append(filename)
                logger.info(f"Marking for deletion: {filename} (not in allowlist)")
        
        return files_to_keep, files_to_delete


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
    
    # This is kept for backward compatibility
    # Note: This only does VPS cleanup, not local version cleanup
    files_to_keep, files_to_delete = cleaner.identify_obsolete_files(vps_files, allowlist)
    
    # In practice, the remote deletion should be handled by a separate module
    # This function is now deprecated in favor of execute_comprehensive_cleanup
    
    return True, files_to_delete