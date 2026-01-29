"""
Version Tracker
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Set, List
from modules.vps.ssh_client import SSHClient

class VersionTracker:
    """Tracks versions vs remote"""
    
    def __init__(self, repo_root: Path, ssh_client: SSHClient, logger: Optional[logging.Logger] = None):
        self.repo_root = repo_root
        self.ssh_client = ssh_client
        self.logger = logger or logging.getLogger(__name__)
        
        self._target_versions: Dict[str, str] = {}
        self._skipped: Dict[str, str] = {}
        self._built: Dict[str, str] = {}
        
        # We need this method to be accessible for internal use
        self._parse_package_filename_with_arch = self._parse_filename

    def is_package_on_remote(self, pkg_name: str, version: str) -> Tuple[bool, Optional[str], Optional[str]]:
        inventory = self.ssh_client.get_cached_inventory()
        for filename in inventory.keys():
            parsed = self._parse_filename(filename)
            if not parsed: continue
            
            p_name, p_ver, p_arch = parsed
            if p_name == pkg_name:
                if p_ver == version: # Simplified strict equality for now
                    return True, p_ver, None # Hash check omitted for simplicity
        return False, None, None

    def register_built_package(self, pkg_name: str, version: str, hash_val: Optional[str] = None):
        self._built[pkg_name] = version
        self._target_versions[pkg_name] = version

    def queue_deletion(self, remote_path: str):
        # Placeholder for queue logic, handled by CleanupManager in practice? 
        # Actually RecoveryManager/CleanupManager use explicit deletions
        pass
    
    def _versions_match(self, v1: str, v2: str) -> bool:
        return v1 == v2

    def _parse_filename(self, filename: str) -> Optional[Tuple[str, str, str]]:
        # simplified parsing: name-version-release-arch.pkg.tar.zst
        # This is complex, implementing a basic heuristic
        parts = filename.split('-')
        if len(parts) < 4: return None
        
        arch = parts[-1].split('.')[0]
        rel = parts[-2]
        ver = parts[-3]
        name = "-".join(parts[:-3])
        full_ver = f"{ver}-{rel}"
        return name, full_ver, arch