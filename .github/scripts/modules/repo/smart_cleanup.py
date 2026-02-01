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
            logger.debug(f"Could not parse filename: {e}")

        return None

    def extract_version_from_filename(self, filename: str, pkg_name: str) -> Optional[str]:
        """
        Extract version from package filename.

        Args:
            filename: Package filename (e.g., 'qownnotes-26.1.9-1-x86_64.pkg.tar.zst')
            pkg_name: Package name (e.g., 'qownnotes')

        Returns:
            Version string (e.g., '26.1.9-1') or None if cannot parse
        """
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')

            # Find where package name ends
            for i in range(len(parts) - 2, 0, -1):
                possible_name = '-'.join(parts[:i])
                if possible_name == pkg_name or possible_name.startswith(pkg_name + '-'):
                    # Remaining parts: version-release-architecture
                    if len(parts) >= i + 3:
                        version_part = parts[i]
                        release_part = parts[i + 1]

                        # Check for epoch (e.g., "2-26.1.9-1" -> "2:26.1.9-1")
                        if i + 2 < len(parts) and parts[i].isdigit():
                            epoch_part = parts[i]
                            version_part = parts[i + 1]
                            release_part = parts[i + 2]
                            return f"{epoch_part}:{version_part}-{release_part}"
                        else:
                            return f"{version_part}-{release_part}"
        except Exception as e:
            logger.debug(f"Could not extract version: {e}")

        return None

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
                return int(result.stdout.strip())
        except Exception as e:
            logger.warning(f"vercmp failed, using fallback comparison: {e}")

        # Fallback: string comparison (less accurate)
        return 1 if version1 > version2 else -1 if version1 < version2 else 0

    def remove_old_package_versions(self) -> List[str]:
        """
        🚨 AUTHORITATIVE VERSION CLEANUP: Keep only newest version per package

        For each pkgname:
        - Keep only the newest version
        - Delete older versions and their .sig files

        Returns:
            List of deleted basenames (packages and signatures)
        """
        logger.info("🔍 Starting version-based cleanup...")

        deleted: List[str] = []

        # Get all package files in output_dir
        package_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not package_files:
            logger.info("No package files found for version cleanup")
            return deleted

        # Remove signature files from the list (we'll handle them separately)
        package_files = [f for f in package_files if not f.name.endswith('.sig')]

        # Group files by package name
        packages_dict: Dict[str, List[Tuple[str, Path]]] = {}

        for pkg_file in package_files:
            # Extract package name and version
            pkg_name = self.extract_package_name_from_filename(pkg_file.name)
            if not pkg_name:
                # Keep unknowns untouched (safety)
                continue

            version = self.extract_version_from_filename(pkg_file.name, pkg_name)
            if not version:
                continue

            packages_dict.setdefault(pkg_name, []).append((version, pkg_file))

        total_deleted = 0

        for pkg_name, files in packages_dict.items():
            if len(files) <= 1:
                continue

            # Find newest
            newest_version, newest_file = files[0][0], files[0][1]
            for version, pkg_file in files[1:]:
                if self._compare_versions(version, newest_version) > 0:
                    newest_version, newest_file = version, pkg_file

            # Delete older
            for version, pkg_file in files:
                if pkg_file == newest_file:
                    continue

                try:
                    pkg_basename = pkg_file.name
                    pkg_file.unlink(missing_ok=True)
                    deleted.append(pkg_basename)
                    total_deleted += 1

                    sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                    if sig_file.exists():
                        sig_basename = sig_file.name
                        sig_file.unlink(missing_ok=True)
                        deleted.append(sig_basename)
                except Exception as e:
                    logger.warning(f"Could not delete old version for {pkg_name}: {e}")

        if total_deleted > 0:
            logger.info(f"✅ Version cleanup: Removed {total_deleted} old package versions")
        else:
            logger.info("✅ All packages have only one version")

        return deleted

    def remove_packages_not_in_allowlist(self, allowlist: Set[str]) -> List[str]:
        """
        🚨 ALLOWLIST CLEANUP: Remove packages not in allowlist

        Args:
            allowlist: Set of valid package names from PKGBUILD extraction

        Returns:
            List of deleted basenames (packages and signatures)
        """
        logger.info("🔍 Starting allowlist-based cleanup...")

        deleted: List[str] = []

        if not allowlist:
            logger.warning("⚠️ Allowlist is empty - skipping allowlist cleanup for safety")
            return deleted

        package_files = list(self.output_dir.glob("*.pkg.tar.*"))
        if not package_files:
            logger.info("No package files found for allowlist cleanup")
            return deleted

        package_files = [f for f in package_files if not f.name.endswith('.sig')]

        deleted_count = 0

        for pkg_file in package_files:
            pkg_name = self.extract_package_name_from_filename(pkg_file.name)
            if not pkg_name:
                # Keep unknowns untouched (safety)
                continue

            if pkg_name not in allowlist:
                try:
                    pkg_basename = pkg_file.name
                    pkg_file.unlink(missing_ok=True)
                    deleted.append(pkg_basename)
                    deleted_count += 1

                    sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                    if sig_file.exists():
                        sig_basename = sig_file.name
                        sig_file.unlink(missing_ok=True)
                        deleted.append(sig_basename)
                except Exception as e:
                    logger.warning(f"Could not delete package not in allowlist: {e}")

        if deleted_count > 0:
            logger.info(f"✅ Allowlist cleanup: Removed {deleted_count} packages not in allowlist")
        else:
            logger.info("✅ All packages are in allowlist")

        return deleted

    def cleanup_orphan_signatures(self) -> List[str]:
        """
        🚨 SIGNATURE HYGIENE: Remove orphaned .sig files with no corresponding package.

        Returns:
            List of deleted signature basenames
        """
        logger.info("🔍 Starting orphan signature cleanup...")

        deleted: List[str] = []
        sig_files = list(self.output_dir.glob("*.sig"))
        if not sig_files:
            return deleted

        for sig_file in sig_files:
            pkg_file = self.output_dir / sig_file.name[:-4]
            if not pkg_file.exists():
                try:
                    deleted.append(sig_file.name)
                    sig_file.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Could not delete orphan signature: {e}")

        if deleted:
            logger.info(f"✅ Signature hygiene: Removed {len(deleted)} orphan signatures")
        else:
            logger.info("✅ No orphan signatures found")

        return deleted

    def cleanup_invalid_signatures(self, gpg_handler) -> List[str]:
        """
        🚨 SIGNATURE VALIDATION: Remove invalid signature files

        Args:
            gpg_handler: GPGHandler instance for signature verification

        Returns:
            List of deleted signature basenames
        """
        logger.info("🔍 Starting signature validation cleanup...")

        deleted: List[str] = []

        sig_files = list(self.output_dir.glob("*.sig"))
        if not sig_files:
            return deleted

        # If we cannot verify, do not delete based on existence alone (policy)
        if not gpg_handler or not hasattr(gpg_handler, '_verify_signature'):
            logger.info("ℹ️ Signature verification unavailable - skipping invalid signature cleanup")
            return deleted

        for sig_file in sig_files:
            pkg_file = self.output_dir / sig_file.name[:-4]
            if not pkg_file.exists():
                # Orphans handled by hygiene; skip here
                continue

            try:
                if not gpg_handler._verify_signature(pkg_file, sig_file):
                    sig_file.unlink(missing_ok=True)
                    deleted.append(sig_file.name)
            except Exception as e:
                logger.warning(f"Could not verify signature: {e}")

        if deleted:
            logger.info(f"✅ Signature cleanup: Removed {len(deleted)} invalid signatures")
        else:
            logger.info("✅ All verifiable signatures are valid")

        return deleted

    def execute_comprehensive_cleanup(self, allowlist: Set[str], gpg_handler=None) -> List[str]:
        """
        Execute complete cleanup workflow.

        Args:
            allowlist: Set of valid package names from PKGBUILD extraction
            gpg_handler: GPGHandler instance for signature verification (optional)

        Returns:
            List of deleted basenames
        """
        logger.info("🚀 Starting comprehensive cleanup...")

        deleted: List[str] = []
        deleted.extend(self.remove_old_package_versions())
        deleted.extend(self.remove_packages_not_in_allowlist(allowlist))
        deleted.extend(self.cleanup_orphan_signatures())

        if gpg_handler:
            deleted.extend(self.cleanup_invalid_signatures(gpg_handler))

        logger.info("✅ Comprehensive cleanup completed successfully")
        return deleted

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
            if not filename.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                files_to_keep.append(filename)
                continue

            pkg_name = self.extract_package_name_from_filename(filename)
            if not pkg_name:
                files_to_keep.append(filename)
                continue

            if pkg_name in allowlist:
                files_to_keep.append(filename)
            else:
                files_to_delete.append(filename)

        return files_to_keep, files_to_delete


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

    Returns:
        Tuple of (success: bool, deleted_files: List[str])
    """
    cleaner = SmartCleanup(repo_name, output_dir)
    files_to_keep, files_to_delete = cleaner.identify_obsolete_files(vps_files, allowlist)
    return True, files_to_delete
