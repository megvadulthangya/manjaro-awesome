"""
Version Tracker Module - Handles package version tracking and comparison
"""

import re
import logging
from typing import Dict, List, Optional, Tuple

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
        
        logger.info(f"📝 Registered SKIPPED package: {pkg_name} (remote: {remote_version}, target: {remote_version})")
    
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
                
                # Find where the package name ends
                for i in range(len(parts) - 2, 0, -1):
                    possible_name = '-'.join(parts[:i])
                    if possible_name == pkg_name or possible_name.startswith(pkg_name + '-'):
                        if len(parts) >= i + 3:
                            version_part = parts[i]
                            release_part = parts[i+1]
                            if i + 1 < len(parts) and parts[i].isdigit() and i + 2 < len(parts):
                                epoch_part = parts[i]
                                version_part = parts[i+1]
                                release_part = parts[i+2]
                                return f"{epoch_part}:{version_part}-{release_part}"
                            else:
                                return f"{version_part}-{release_part}"
        
        return None