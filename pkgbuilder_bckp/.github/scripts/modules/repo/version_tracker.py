"""
Version tracking for Zero-Residue cleanup policy - SERVER-FIRST ARCHITECTURE
Enhanced with VCS version resolution and protected artifacts
"""

import os
import json
import re
import subprocess
import time
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set, Any
from datetime import datetime

from modules.vps.ssh_client import SSHClient


class VersionTracker:
    """
    Tracks package versions with VCS resolution and protected artifacts
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
        
        # VCS cache for git package versions
        self._vcs_version_cache: Dict[str, str] = {}
        
        # Protected artifacts registry (multi-package PKGBUILD outputs)
        self._protected_files: Set[str] = set()
        
        # Pending deletions queue
        self._pending_deletions: List[str] = []
        
        # Target versions: {pkg_name: target_version} - versions we want to keep
        self._target_versions: Dict[str, str] = {}
        
        # Skipped packages: {pkg_name: remote_version} - packages skipped as up-to-date
        self._skipped_packages: Dict[str, str] = {}
        
        # Built packages: {pkg_name: built_version} - packages we just built
        self._built_packages: Dict[str, str] = {}
        
        # JSON state file
        self.state_file = self._get_state_path()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state: Dict[str, Any] = self._load_state()
        
        # Load remote inventory at initialization
        self._load_remote_inventory()
    
    def _get_state_path(self) -> Path:
        """
        Get platform-appropriate state file path
        
        Returns:
            Path to state file
        """
        # Priority 1: GitHub Actions workspace
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                state_path = workspace_path / ".build_tracking" / "vps_state.json"
                self.logger.info(f"Using GitHub workspace state path: {state_path}")
                return state_path
        
        # Priority 2: Repository root
        repo_state_path = self.repo_root / ".build_tracking" / "vps_state.json"
        if self.repo_root.exists():
            self.logger.info(f"Using repository state path: {repo_state_path}")
            return repo_state_path
        
        # Priority 3: User home directory
        home_dir = Path.home()
        home_state_path = home_dir / ".build_tracking" / "vps_state.json"
        home_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Using home directory state path: {home_state_path}")
        return home_state_path
    
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
    
    def _load_remote_inventory(self):
        """Load remote inventory at initialization"""
        self.logger.info("🔍 Loading remote inventory...")
        remote_files = self.ssh_client.get_cached_inventory(force_refresh=True)
        
        self.logger.info(f"📋 Remote inventory loaded: {len(remote_files)} files")
    
    def resolve_vcs_version(self, pkg_name: str, pkg_dir: Path, force_refresh: bool = False) -> Optional[Tuple[str, str, str]]:
        """
        Resolve VCS package version by running makepkg --printsrcinfo
        
        Args:
            pkg_name: Package name
            pkg_dir: Directory containing PKGBUILD
            force_refresh: If True, ignore cache and refresh
        
        Returns:
            Tuple of (pkgver, pkgrel, epoch) or None if failed
        """
        # Check cache first
        cache_key = f"{pkg_name}_{pkg_dir}"
        if not force_refresh and cache_key in self._vcs_version_cache:
            version_str = self._vcs_version_cache[cache_key]
            return self._parse_version_string(version_str)
        
        # Determine if this is a VCS package
        is_vcs_package = self._is_vcs_package(pkg_name, pkg_dir)
        
        try:
            if is_vcs_package:
                self.logger.info(f"🔍 Resolving VCS version for {pkg_name}...")
                
                # For VCS packages, we need to run makepkg --printsrcinfo
                # This will resolve git commit hashes to actual versions
                result = subprocess.run(
                    ['makepkg', '--printsrcinfo'],
                    cwd=pkg_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300
                )
                
                if result.returncode == 0 and result.stdout:
                    version_info = self._extract_version_from_srcinfo(result.stdout)
                    if version_info:
                        pkgver, pkgrel, epoch = version_info
                        version_str = self._format_version_string(pkgver, pkgrel, epoch)
                        self._vcs_version_cache[cache_key] = version_str
                        self.logger.info(f"✅ VCS version resolved: {version_str}")
                        return version_info
                    else:
                        self.logger.warning(f"Could not parse version from SRCINFO for {pkg_name}")
                else:
                    self.logger.warning(f"makepkg --printsrcinfo failed for {pkg_name}: {result.stderr}")
            
            # Fall back to standard .SRCINFO parsing
            return self._extract_version_from_srcinfo_file(pkg_dir)
            
        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout resolving VCS version for {pkg_name}")
            return None
        except Exception as e:
            self.logger.error(f"Error resolving VCS version for {pkg_name}: {e}")
            return None
    
    def _is_vcs_package(self, pkg_name: str, pkg_dir: Path) -> bool:
        """
        Check if package is a VCS package
        
        Args:
            pkg_name: Package name
            pkg_dir: Package directory
        
        Returns:
            True if VCS package
        """
        # Check package name patterns
        vcs_patterns = ['-git', '_git', '-svn', '_svn', '-hg', '_hg', '-bzr', '_bzr']
        if any(pattern in pkg_name.lower() for pattern in vcs_patterns):
            return True
        
        # Check PKGBUILD content
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if pkgbuild_path.exists():
            try:
                with open(pkgbuild_path, 'r') as f:
                    content = f.read()
                
                # Look for VCS URLs
                vcs_url_patterns = [
                    r'git\+https?://',
                    r'https?://.*\.git',
                    r'svn\+https?://',
                    r'hg\+https?://',
                    r'bzr\+https?://'
                ]
                
                for pattern in vcs_url_patterns:
                    if re.search(pattern, content):
                        return True
            except Exception:
                pass
        
        return False
    
    def _extract_version_from_srcinfo(self, srcinfo_content: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """Parse SRCINFO content to extract version information"""
        pkgver = None
        pkgrel = None
        epoch = None
        
        lines = srcinfo_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Handle key-value pairs
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key == 'pkgver':
                    pkgver = value
                elif key == 'pkgrel':
                    pkgrel = value
                elif key == 'epoch':
                    epoch = value
        
        if not pkgver or not pkgrel:
            return None
        
        return pkgver, pkgrel, epoch
    
    def _extract_version_from_srcinfo_file(self, pkg_dir: Path) -> Optional[Tuple[str, str, Optional[str]]]:
        """Extract version from .SRCINFO file"""
        srcinfo_path = pkg_dir / ".SRCINFO"
        
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    content = f.read()
                return self._extract_version_from_srcinfo(content)
            except Exception as e:
                self.logger.warning(f"Failed to read .SRCINFO: {e}")
        
        return None
    
    def _parse_version_string(self, version_str: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """Parse version string into components"""
        if ':' in version_str:
            # Has epoch
            epoch_part, rest = version_str.split(':', 1)
            epoch = epoch_part
            if '-' in rest:
                pkgver, pkgrel = rest.split('-', 1)
            else:
                pkgver = rest
                pkgrel = "1"
        else:
            # No epoch
            epoch = None
            if '-' in version_str:
                pkgver, pkgrel = version_str.split('-', 1)
            else:
                pkgver = version_str
                pkgrel = "1"
        
        return pkgver, pkgrel, epoch
    
    def _format_version_string(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> str:
        """Format version components into string"""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"
    
    def register_protected_files(self, pkg_name: str, files: List[str]):
        """
        Register protected files that should not be deleted
        
        Args:
            pkg_name: Package name
            files: List of filenames to protect
        """
        protected_count = 0
        for filename in files:
            if filename not in self._protected_files:
                self._protected_files.add(filename)
                protected_count += 1
                self.logger.debug(f"🔒 Protected file: {filename}")
        
        if protected_count > 0:
            self.logger.info(f"🔒 Registered {protected_count} protected files for {pkg_name}")
    
    def is_protected(self, filename: str) -> bool:
        """
        Check if a file is protected from deletion
        
        Args:
            filename: Filename to check
        
        Returns:
            True if file is protected
        """
        return filename in self._protected_files
    
    def get_protected_files(self) -> Set[str]:
        """Get all protected files"""
        return self._protected_files.copy()
    
    def clear_protected_files(self):
        """Clear protected files registry"""
        self._protected_files.clear()
        self.logger.debug("Cleared protected files registry")
    
    def queue_deletion(self, remote_path: str):
        """
        Queue a file for batch deletion
        
        Args:
            remote_path: Full remote path to delete
        """
        filename = Path(remote_path).name
        
        # Don't queue protected files
        if self.is_protected(filename):
            self.logger.debug(f"Skipping protected file: {filename}")
            return
        
        self._pending_deletions.append(remote_path)
        self.logger.debug(f"Queued for deletion: {filename}")
    
    def commit_queued_deletions(self) -> bool:
        """
        Execute all queued deletions via SSH client
        
        Returns:
            True if successful
        """
        if not self._pending_deletions:
            return True
        
        self.logger.info(f"🔧 Committing {len(self._pending_deletions)} queued deletions...")
        success = self.ssh_client.commit_queued_deletions()
        
        if success:
            self._pending_deletions.clear()
        
        return success
    
    def get_pending_deletions(self) -> List[str]:
        """Get list of pending deletions"""
        return self._pending_deletions.copy()
    
    def clear_pending_deletions(self):
        """Clear pending deletions queue"""
        self._pending_deletions.clear()
        self.logger.debug("Cleared pending deletions queue")
    
    def save_state(self) -> bool:
        """Save state to JSON file"""
        try:
            self.state["metadata"]["last_updated"] = datetime.now().isoformat()
            self.state["metadata"]["protected_files"] = list(self._protected_files)
            
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            
            self.logger.debug(f"Saved state to {self.state_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}")
            return False
    
    def is_package_on_remote(self, pkg_name: str, version: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        SERVER-FIRST: Check if package with specific version exists on remote server
        
        Args:
            pkg_name: Package name (e.g., 'libinput-gestures')
            version: Package version (e.g., '2.81-1')
        
        Returns:
            Tuple of (found, remote_version, remote_hash) or (False, None, None)
        """
        self.logger.debug(f"Checking if {pkg_name} version {version} exists on remote...")
        
        # Get cached inventory
        remote_inventory = self.ssh_client.get_cached_inventory()
        
        # Normalize package name for matching (case-insensitive)
        pkg_name_lower = pkg_name.lower()
        
        for filename, file_path in remote_inventory.items():
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
        
        # Get cached inventory
        remote_inventory = self.ssh_client.get_cached_inventory()
        
        # Case-insensitive matching with architecture suffix handling
        pkg_name_lower = pkg_name.lower()
        
        for filename, file_path in remote_inventory.items():
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
        self.logger.info(f"📋 Remote inventory updated: {len(remote_files)} files")
    
    def get_remote_inventory(self) -> Dict[str, str]:
        """
        Get current remote inventory from cache
        
        Returns:
            Dictionary of {filename: full_path}
        """
        return self.ssh_client.get_cached_inventory()
    
    def get_files_to_keep(self) -> Set[str]:
        """
        Determine which files should be kept based on target versions
        
        Returns:
            Set of filenames that match target versions
        """
        files_to_keep = set()
        remote_inventory = self.get_remote_inventory()
        
        for filename in remote_inventory:
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
        remote_inventory = self.get_remote_inventory()
        files_to_keep = self.get_files_to_keep()
        
        for filename, full_path in remote_inventory.items():
            if filename not in files_to_keep and not self.is_protected(filename):
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
        self.ssh_client.clear_cache()
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
            "protected_files": len(self._protected_files),
            "pending_deletions": len(self._pending_deletions),
        }