"""
Version Tracker Module - Handles package version tracking and comparison
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Set

logger = logging.getLogger(__name__)


class VersionTracker:
    """Handles package version tracking, comparison, and Zero-Residue policy"""
    
    def __init__(self, config: dict):
        """
        Initialize VersionTracker with configuration
        
        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory (SOURCE OF TRUTH)
                - remote_dir: Remote directory on VPS
                - mirror_temp_dir: Temporary mirror directory
                - vps_user: VPS username
                - vps_host: VPS hostname
        """
        self.repo_name = config['repo_name']
        self.output_dir = config['output_dir']
        self.remote_dir = config['remote_dir']
        self.mirror_temp_dir = config.get('mirror_temp_dir', '/tmp/repo_mirror')
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        
        # 🚨 ZERO-RESIDUE POLICY: Explicit version tracking
        self._skipped_packages: Dict[str, str] = {}  # {pkg_name: remote_version} - packages skipped as up-to-date
        self._package_target_versions: Dict[str, str] = {}  # {pkg_name: target_version} - versions we want to keep
        self._built_packages: Dict[str, str] = {}  # {pkg_name: built_version} - packages we just built
        self._upload_successful = False
        self._desired_inventory: Set[str] = set()  # NEW: Desired inventory for cleanup guard
        
        # FIX: Add persistent remote version index
        self._remote_version_index: Dict[str, str] = {}  # {pkg_name: normalized_version}
    
    def set_desired_inventory(self, desired_inventory: Set[str]):
        """Set the desired inventory for cleanup guard"""
        self._desired_inventory = desired_inventory
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
    
    def build_remote_version_index(self, remote_files: List[str]):
        """
        FIX: Build authoritative remote version index from VPS package files.
        This index persists across phases and is the source of truth for remote versions.
        
        Args:
            remote_files: List of VPS filenames (basenames) from SSH find
        """
        logger.info("Building remote version index from VPS package files...")
        self._remote_version_index = {}
        
        processed_count = 0
        for filename in remote_files:
            # Only process package files, not signatures
            if not (filename.endswith('.pkg.tar.zst') or filename.endswith('.pkg.tar.xz')):
                continue
            
            pkg_name, version = self._parse_package_filename_for_index(filename)
            if pkg_name and version:
                # Store the normalized version
                self._remote_version_index[pkg_name] = version
                processed_count += 1
                logger.debug(f"Indexed: {pkg_name} -> {version}")
        
        logger.info(f"Remote version index built: {processed_count} packages indexed")
    
    def _parse_package_filename_for_index(self, filename: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse package name and version from package filename for indexing.
        
        Args:
            filename: Package filename (e.g., 'package-1.0-1-x86_64.pkg.tar.zst')
            
        Returns:
            Tuple of (pkg_name, normalized_version) or (None, None) if cannot parse
        """
        # Remove extensions
        if filename.endswith('.pkg.tar.zst'):
            base = filename[:-12]
        elif filename.endswith('.pkg.tar.xz'):
            base = filename[:-11]
        else:
            # Not a package file
            return None, None
        
        # Parse using the same logic as VersionManager/VersionTracker normalization
        # Extract package name and full version from the base filename
        parts = base.split('-')
        if len(parts) < 3:
            return None, None
        
        # Try to find the split point between package name and version
        # Package name can contain hyphens, so we need to find where version starts
        for i in range(1, len(parts) - 1):
            # Check if this could be a version part (contains digits or colon)
            test_part = parts[i]
            if any(c.isdigit() for c in test_part) or ':' in test_part:
                # Found the version start
                pkg_name = '-'.join(parts[:i])
                version_components = parts[i:]
                
                # Reconstruct version string without architecture
                # Remove architecture suffix (last part if it doesn't look like version/release)
                if len(version_components) >= 2:
                    # Check if last part looks like an architecture
                    last_part = version_components[-1]
                    arch_suffixes = ['x86_64', 'any', 'i686', 'aarch64', 'armv7h', 'armv6h']
                    if last_part in arch_suffixes:
                        version_components = version_components[:-1]
                
                # Now we have version components: could be [version, release] or [epoch, version, release]
                if len(version_components) >= 2:
                    if len(version_components) >= 3 and version_components[0].isdigit():
                        # epoch-version-release format
                        epoch, version, release = version_components[0], version_components[1], version_components[2]
                        version_str = f"{epoch}:{version}-{release}"
                    else:
                        # version-release format
                        version, release = version_components[0], version_components[1]
                        version_str = f"{version}-{release}"
                    
                    # Normalize the version
                    normalized = self.normalize_version_string(version_str)
                    return pkg_name, normalized
        
        return None, None
    
    def get_remote_version_index_stats(self) -> Tuple[int, List[str]]:
        """
        Get remote version index statistics for logging.
        
        Returns:
            Tuple of (count, first_10_package_entries) where entries are "pkgname=version"
        """
        count = len(self._remote_version_index)
        sample = []
        for i, (pkg_name, version) in enumerate(list(self._remote_version_index.items())[:10]):
            sample.append(f"{pkg_name}={version}")
        return count, sample
    
    def register_package_target_version(self, pkg_name: str, target_version: str):
        """
        Register the target version for a package.
        
        Args:
            pkg_name: Package name
            target_version: The version we want to keep (either built or latest from server)
        """
        self._package_target_versions[pkg_name] = target_version
        logger.info(f"📝 Registered target version for {pkg_name}: {target_version}")
    
    def register_skipped_package(self, pkg_name: str, remote_version: str):
        """
        Register a package that was skipped because it's up-to-date.
        
        Args:
            pkg_name: Package name
            remote_version: The remote version that should be kept (not deleted)
        """
        # Store in skipped registry
        self._skipped_packages[pkg_name] = remote_version
        
        # 🚨 CRITICAL: Explicitly set target version to remote version
        self._package_target_versions[pkg_name] = remote_version
        
        logger.info(f"📝 Registered skipped package: {pkg_name} ({remote_version})")
    
    def register_split_packages(self, pkg_names: List[str], version: str, is_built: bool = True):
        """
        NEW: Register target/skipped versions for ALL pkgname entries in a split/multi-package PKGBUILD.
        
        Args:
            pkg_names: List of package names produced by the PKGBUILD
            version: The version to register for all packages
            is_built: True if package was built, False if skipped
        """
        for pkg_name in pkg_names:
            if is_built:
                self._package_target_versions[pkg_name] = version
                logger.info(f"📝 Registered split package target version for {pkg_name}: {version}")
            else:
                self._skipped_packages[pkg_name] = version
                self._package_target_versions[pkg_name] = version
                logger.info(f"📝 Registered split skipped package: {pkg_name} ({version})")
    
    def get_target_version(self, pkg_name: str) -> Optional[str]:
        """
        Get the target version for a package from the internal registry.
        
        Args:
            pkg_name: Package name
            
        Returns:
            Target version string or None if not registered
        """
        return self._package_target_versions.get(pkg_name)
    
    def get_remote_version(self, pkg_name: str, remote_files: List[str] = None) -> Optional[str]:
        """
        FIX: Get remote version from persistent index, not from re-parsing files each time.
        Added grep-proof debug logging.
        
        Args:
            pkg_name: Package name
            remote_files: Ignored (kept for backward compatibility, using index instead)
            
        Returns:
            Normalized version string or None if not found
        """
        # Use the persistent index
        version = self._remote_version_index.get(pkg_name)
        
        # Log grep-proof debug line
        found = 1 if version else 0
        logger.info(f"REMOTE_LOOKUP: pkg={pkg_name} found={found} remote_ver={version or 'NONE'} source=vps_list")
        
        return version
    
    def parse_package_filename(self, filename: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse package name and version from package filename.
        Uses the same logic as _parse_package_filename_for_index for consistency.
        
        Args:
            filename: Package filename (e.g., 'package-1.0-1-x86_64.pkg.tar.zst')
            
        Returns:
            Tuple of (pkg_name, normalized_version) or (None, None) if cannot parse
        """
        return self._parse_package_filename_for_index(filename)
    
    def package_exists(self, pkg_name: str, remote_files: List[str]) -> bool:
        """Check if package exists on server"""
        # Use the index for existence check
        return pkg_name in self._remote_version_index
    
    def normalize_version_string(self, version_string: str) -> str:
        """
        Canonical version normalization: strip architecture suffix and ensure epoch format.
        
        Args:
            version_string: Raw version string that may include architecture suffix
            
        Returns:
            Normalized version string in format epoch:pkgver-pkgrel
        """
        if not version_string:
            return version_string
            
        # Remove known architecture suffixes from the end
        # These are only stripped if they appear as the final token
        arch_patterns = [r'-x86_64$', r'-any$', r'-i686$', r'-aarch64$', r'-armv7h$', r'-armv6h$']
        for pattern in arch_patterns:
            version_string = re.sub(pattern, '', version_string)
        
        # Ensure epoch format: if no epoch, prepend "0:"
        if ':' not in version_string:
            # Check if there's already a dash in the version part
            if '-' in version_string:
                # Already in pkgver-pkgrel format, add epoch
                version_string = f"0:{version_string}"
            else:
                # No dash, assume it's just pkgver, add default pkgrel
                version_string = f"0:{version_string}-1"
        
        return version_string
