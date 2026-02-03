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
    
    def set_desired_inventory(self, desired_inventory: Set[str]):
        """Set the desired inventory for cleanup guard"""
        self._desired_inventory = desired_inventory
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
    
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
    
    def package_exists(self, pkg_name: str, remote_files: List[str]) -> bool:
        """Check if package exists on server"""
        if not remote_files:
            return False
        
        pattern = f"^{re.escape(pkg_name)}-"
        matches = [f for f in remote_files if re.match(pattern, f)]
        
        if matches:
            logger.debug(f"Package {pkg_name} exists: {matches[0]}")
            return True
        
        return False
    
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
    
    def get_remote_version(self, pkg_name: str, remote_files: List[str]) -> Optional[str]:
        """Get the version of a package from remote server using SRCINFO-based extraction"""
        if not remote_files:
            return None
        
        # Look for any file with this package name
        for filename in remote_files:
            if filename.startswith(f"{pkg_name}-"):
                # Extract version from filename
                base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
                parts = base.split('-')
                
                # Find where the package name ends and version begins
                # Package name can have multiple hyphenated parts, so we need to find the split point
                for i in range(1, len(parts)):
                    possible_name = '-'.join(parts[:i])
                    if possible_name == pkg_name:
                        # Found the package name boundary
                        # The remaining parts are: [version, release, architecture] or [epoch, version, release, architecture]
                        remaining = parts[i:]
                        
                        # Handle different cases
                        if len(remaining) >= 3:
                            # Check if first part is epoch (all digits)
                            if remaining[0].isdigit() and len(remaining) >= 4:
                                # Format: epoch-version-release-architecture
                                epoch = remaining[0]
                                version = remaining[1]
                                release = remaining[2]
                                # Architecture is remaining[3] but we strip it later
                                raw_version = f"{epoch}:{version}-{release}"
                            else:
                                # Format: version-release-architecture
                                version = remaining[0]
                                release = remaining[1]
                                raw_version = f"{version}-{release}"
                            
                            # Normalize to remove architecture and ensure epoch format
                            normalized = self.normalize_version_string(raw_version)
                            logger.debug(f"Extracted remote version for {pkg_name}: raw='{raw_version}', normalized='{normalized}'")
                            return normalized
        
        return None
