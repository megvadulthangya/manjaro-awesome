"""
Version tracking for Zero-Residue cleanup policy
Tracks target versions and remote inventory for precise package management
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any
from datetime import datetime

from modules.vps.ssh_client import SSHClient


class VersionTracker:
    """
    Tracks package versions for Zero-Residue cleanup
    Maintains source of truth for what versions should exist on server
    """
    
    def __init__(self, repo_root: Path, ssh_client: SSHClient, logger: Optional[logging.Logger] = None):
        """
        Initialize VersionTracker
        
        Args:
            repo_root: Repository root directory
            ssh_client: SSHClient instance for remote operations
            logger: Optional logger instance
        """
        self.repo_root = repo_root
        self.ssh_client = ssh_client
        self.logger = logger or logging.getLogger(__name__)
        
        # Target versions: {pkg_name: target_version} - versions we want to keep
        self._target_versions: Dict[str, str] = {}
        
        # Skipped packages: {pkg_name: remote_version} - packages skipped as up-to-date
        self._skipped_packages: Dict[str, str] = {}
        
        # Built packages: {pkg_name: built_version} - packages we just built
        self._built_packages: Dict[str, str] = {}
        
        # Remote inventory cache: {filename: full_path} from VPS
        self._remote_inventory: Dict[str, str] = {}
        
        # JSON state file
        self.state_file = self.repo_root / ".build_tracking" / "vps_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Any] = self._load_state()
    
    def _load_state(self) -> Dict[str, Any]:
        """Load state from JSON file"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                self.logger.info(f"Loaded state from {self.state_file}")
                return state
            else:
                self.logger.info(f"State file {self.state_file} does not exist, creating new")
                return {"packages": {}, "metadata": {"created": datetime.now().isoformat()}}
        except Exception as e:
            self.logger.error(f"Failed to load state file: {e}")
            return {"packages": {}, "metadata": {"created": datetime.now().isoformat()}}
    
    def save_state(self) -> bool:
        """Save state to JSON file"""
        try:
            self.state["metadata"]["last_updated"] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            self.logger.debug(f"Saved state to {self.state_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
            return False
    
    def is_package_on_remote(self, pkg_name: str, version: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if package with specific version exists on remote server
        
        Args:
            pkg_name: Package name (e.g., 'libinput-gestures')
            version: Package version (e.g., '2.81-1')
        
        Returns:
            Tuple of (found, remote_version, remote_hash) or (False, None, None)
        """
        self.logger.debug(f"Checking if {pkg_name} version {version} exists on remote...")
        
        # Get remote file list
        remote_files = self.ssh_client.get_remote_file_list()
        
        if not remote_files:
            self.logger.debug(f"No remote files found")
            return False, None, None
        
        # Normalize package name for matching (case-insensitive)
        pkg_name_lower = pkg_name.lower()
        
        for file_path in remote_files:
            filename = Path(file_path).name
            self.logger.debug(f"Checking remote file: {filename}")
            
            # Parse filename to extract name, version, and architecture
            parsed = self._parse_package_filename_with_arch(filename)
            if not parsed:
                continue
            
            remote_pkg_name, remote_version, architecture = parsed
            remote_pkg_name_lower = remote_pkg_name.lower()
            
            # Check if package name matches (case-insensitive)
            if remote_pkg_name_lower == pkg_name_lower:
                # Check if version matches (including epoch handling)
                if self._versions_match(remote_version, version):
                    self.logger.info(f"✅ Found matching package on remote: {pkg_name} {version}")
                    
                    # Get hash from remote file
                    remote_hash = self.ssh_client.get_remote_hash(file_path)
                    
                    # Register as adopted
                    self.register_built_package(pkg_name, version, remote_hash)
                    
                    return True, remote_version, remote_hash
        
        self.logger.debug(f"Package {pkg_name} version {version} not found in remote files")
        return False, None, None
    
    def _versions_match(self, version1: str, version2: str) -> bool:
        """Check if two version strings match (handles epoch and architecture)"""
        # Normalize versions by removing epoch if it's 0
        def normalize_version(v: str) -> str:
            if ':' in v:
                epoch, rest = v.split(':', 1)
                if epoch == '0':
                    return rest
            return v
        
        v1_norm = normalize_version(version1)
        v2_norm = normalize_version(version2)
        
        return v1_norm == v2_norm
    
    def discover_and_adopt_remote_packages(self, pkg_name: str) -> Optional[Tuple[str, Optional[str]]]:
        """
        Enhanced adoption logic: Check remote server for package and adopt if found
        
        Args:
            pkg_name: Package name to search for
        
        Returns:
            Tuple of (version, hash) or None if not found
        """
        self.logger.info(f"🔍 Searching for {pkg_name} on remote server...")
        
        # MANDATORY: Use explicit file listing with debug
        remote_files = self.ssh_client.get_remote_file_list()
        
        if not remote_files:
            self.logger.debug(f"No remote files found for {pkg_name}")
            return None
        
        # Case-insensitive matching with architecture suffix handling
        pkg_name_lower = pkg_name.lower()
        self.logger.debug(f"Searching for package name (case-insensitive): {pkg_name_lower}")
        
        for file_path in remote_files:
            filename = Path(file_path).name
            self.logger.debug(f"Checking file: {filename}")
            
            # Parse package name and version from filename
            parsed = self._parse_package_filename_with_arch(filename)
            if not parsed:
                continue
            
            remote_pkg_name, version, architecture = parsed
            remote_pkg_name_lower = remote_pkg_name.lower()
            
            # Case-insensitive comparison with architecture suffix handling
            if remote_pkg_name_lower == pkg_name_lower:
                self.logger.info(f"✅ Found {pkg_name} on remote server: {filename}")
                
                # Get hash from remote file
                remote_hash = self.ssh_client.get_remote_hash(file_path)
                
                # Update state
                self.state["packages"][pkg_name] = {
                    "version": version,
                    "hash": remote_hash,
                    "last_updated": datetime.now().isoformat(),
                    "source": "adopted",
                    "filename": filename,
                    "architecture": architecture
                }
                
                # Save state immediately
                self.save_state()
                
                # Update target versions
                self._target_versions[pkg_name] = version
                self._skipped_packages[pkg_name] = version
                
                self.logger.info(f"📥 Adopted {pkg_name} version {version} from remote server")
                return version, remote_hash
        
        self.logger.debug(f"Package {pkg_name} not found in remote files")
        return None
    
    def _parse_package_filename_with_arch(self, filename: str) -> Optional[Tuple[str, str, str]]:
        """
        Parse package filename to extract name, version, and architecture
        
        Args:
            filename: Package filename (e.g., 'qownnotes-26.1.9-1-x86_64.pkg.tar.zst')
        
        Returns:
            Tuple of (package_name, version_string, architecture) or None
        """
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            if len(parts) < 4:
                return None
            
            # Try to find where package name ends and architecture begins
            # Architecture is usually the last part (x86_64, any, etc.)
            # Version is usually the 2 or 3 parts before architecture
            
            # Start from the end and work backwards
            for i in range(len(parts) - 2, 0, -1):
                # Check if the remaining parts look like version-release-architecture
                remaining = parts[i:]
                
                if len(remaining) >= 3:
                    # Check for architecture suffix (x86_64, any, etc.)
                    arch = remaining[-1]
                    
                    # Check for epoch format (e.g., "2-26.1.9-1-x86_64")
                    if remaining[0].isdigit() and len(remaining) >= 4:
                        epoch = remaining[0]
                        version_part = remaining[1]
                        release_part = remaining[2]
                        version_str = f"{epoch}:{version_part}-{release_part}"
                        package_name = '-'.join(parts[:i])
                        return package_name, version_str, arch
                    # Standard format (e.g., "26.1.9-1-x86_64")
                    elif any(c.isdigit() for c in remaining[0]) and remaining[1].isdigit():
                        version_part = remaining[0]
                        release_part = remaining[1]
                        version_str = f"{version_part}-{release_part}"
                        package_name = '-'.join(parts[:i])
                        return package_name, version_str, arch
        
        except Exception as e:
            self.logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None
    
    def register_built_package(self, pkg_name: str, version: str, hash_value: Optional[str] = None) -> None:
        """
        Register a package that was just built or adopted from VPS
        
        Args:
            pkg_name: Package name
            version: Package version
            hash_value: Optional hash value for verification
        """
        # Update built packages registry
        self._built_packages[pkg_name] = version
        self._target_versions[pkg_name] = version
        
        # Update JSON state
        if "packages" not in self.state:
            self.state["packages"] = {}
        
        source = "adopted" if hash_value is not None else "built"
        
        self.state["packages"][pkg_name] = {
            "version": version,
            "hash": hash_value,
            "last_updated": datetime.now().isoformat(),
            "source": source
        }
        
        # Save state
        self.save_state()
        
        self.logger.info(f"📝 Registered {source} package: {pkg_name} ({version})")
    
    def register_target_version(self, pkg_name: str, target_version: str) -> None:
        """
        Register the target version for a package
        
        Args:
            pkg_name: Package name
            target_version: The version we want to keep (either built or latest from server)
        """
        self._target_versions[pkg_name] = target_version
        self.logger.info(f"📝 Registered target version for {pkg_name}: {target_version}")
    
    def register_skipped_package(self, pkg_name: str, remote_version: str) -> None:
        """
        Register a package that was skipped because it's up-to-date
        
        Args:
            pkg_name: Package name
            remote_version: The remote version that should be kept (not deleted)
        """
        # Store in skipped registry
        self._skipped_packages[pkg_name] = remote_version
        
        # 🚨 CRITICAL: Explicitly set target version to remote version
        self._target_versions[pkg_name] = remote_version
        
        # Update JSON state
        if "packages" not in self.state:
            self.state["packages"] = {}
        
        self.state["packages"][pkg_name] = {
            "version": remote_version,
            "hash": None,
            "last_updated": datetime.now().isoformat(),
            "source": "skipped"
        }
        
        # Save state
        self.save_state()
        
        self.logger.info(f"📝 Registered SKIPPED package: {pkg_name} (remote: {remote_version}, target: {remote_version})")
    
    def get_target_version(self, pkg_name: str) -> Optional[str]:
        """
        Get target version for a package
        
        Args:
            pkg_name: Package name
        
        Returns:
            Target version or None if not registered
        """
        return self._target_versions.get(pkg_name)
    
    def has_target_version(self, pkg_name: str) -> bool:
        """
        Check if a package has a registered target version
        
        Args:
            pkg_name: Package name
        
        Returns:
            True if target version exists
        """
        return pkg_name in self._target_versions
    
    def is_skipped(self, pkg_name: str) -> bool:
        """
        Check if a package was skipped
        
        Args:
            pkg_name: Package name
        
        Returns:
            True if package was skipped
        """
        return pkg_name in self._skipped_packages
    
    def is_built(self, pkg_name: str) -> bool:
        """
        Check if a package was built in this run
        
        Args:
            pkg_name: Package name
        
        Returns:
            True if package was built
        """
        return pkg_name in self._built_packages
    
    def set_remote_inventory(self, remote_files: Dict[str, str]) -> None:
        """
        Set remote inventory from VPS
        
        Args:
            remote_files: Dictionary of {filename: full_path} from VPS
        """
        self._remote_inventory = remote_files
        self.logger.info(f"📋 Remote inventory updated: {len(remote_files)} files")
    
    def get_remote_inventory(self) -> Dict[str, str]:
        """
        Get current remote inventory
        
        Returns:
            Dictionary of {filename: full_path}
        """
        return self._remote_inventory.copy()
    
    def get_files_to_keep(self) -> Set[str]:
        """
        Determine which files should be kept based on target versions
        
        Returns:
            Set of filenames that match target versions
        """
        files_to_keep = set()
        
        for filename in self._remote_inventory:
            # Parse filename to extract package name and version
            parsed = self._parse_package_filename(filename)
            if not parsed:
                # Can't parse, keep it to be safe
                files_to_keep.add(filename)
                continue
            
            pkg_name, version_str = parsed
            
            # Check if this package has a target version
            if pkg_name in self._target_versions:
                target_version = self._target_versions[pkg_name]
                if version_str == target_version:
                    # This is the version we want to keep
                    files_to_keep.add(filename)
                    self.logger.debug(f"✅ Keeping {filename} (matches target version {target_version})")
                else:
                    self.logger.debug(f"🗑️ Marking for deletion: {filename} (target is {target_version})")
            else:
                # No target version registered - keep to be safe
                files_to_keep.add(filename)
                self.logger.debug(f"⚠️ Keeping unknown package: {filename} (not in target versions)")
        
        return files_to_keep
    
    def get_files_to_delete(self) -> List[str]:
        """
        Determine which files should be deleted based on target versions
        
        Returns:
            List of full paths to delete
        """
        files_to_delete = []
        files_to_keep = self.get_files_to_keep()
        
        for filename, full_path in self._remote_inventory.items():
            if filename not in files_to_keep:
                files_to_delete.append(full_path)
        
        return files_to_delete
    
    def _parse_package_filename(self, filename: str) -> Optional[Tuple[str, str]]:
        """
        Parse package filename to extract name and version (without architecture)
        
        Args:
            filename: Package filename (e.g., 'qownnotes-26.1.9-1-x86_64.pkg.tar.zst')
        
        Returns:
            Tuple of (package_name, version_string) or None
        """
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            if len(parts) < 4:
                return None
            
            # Try to find where package name ends
            for i in range(len(parts) - 3, 0, -1):
                potential_name = '-'.join(parts[:i])
                remaining = parts[i:]
                
                if len(remaining) >= 3:
                    # Check for epoch format (e.g., "2-26.1.9-1")
                    if remaining[0].isdigit() and '-' in '-'.join(remaining[1:]):
                        epoch = remaining[0]
                        version_part = remaining[1]
                        release_part = remaining[2]
                        version_str = f"{epoch}:{version_part}-{release_part}"
                        return potential_name, version_str
                    # Standard format (e.g., "26.1.9-1")
                    elif any(c.isdigit() for c in remaining[0]) and remaining[1].isdigit():
                        version_part = remaining[0]
                        release_part = remaining[1]
                        version_str = f"{version_part}-{release_part}"
                        return potential_name, version_str
        
        except Exception as e:
            self.logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None
    
    def clear_remote_inventory(self) -> None:
        """Clear remote inventory cache"""
        self._remote_inventory.clear()
        self.logger.debug("Cleared remote inventory cache")
    
    def get_target_packages(self) -> Dict[str, str]:
        """Get all target packages"""
        return self._target_versions.copy()
    
    def get_skipped_packages_dict(self) -> Dict[str, str]:
        """Get all skipped packages"""
        return self._skipped_packages.copy()
    
    def get_built_packages_dict(self) -> Dict[str, str]:
        """Get all built packages"""
        return self._built_packages.copy()
    
    def has_packages(self) -> bool:
        """Check if any packages are registered"""
        return bool(self._target_versions)
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get state summary for logging"""
        return {
            "total_packages": len(self.state.get("packages", {})),
            "last_updated": self.state.get("metadata", {}).get("last_updated"),
        }