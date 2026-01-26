"""
Version tracking for Zero-Residue cleanup policy
Tracks target versions and remote inventory for precise package management
"""

import json
import re
import logging
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any
from datetime import datetime

from modules.common.shell_executor import ShellExecutor
from modules.vps.ssh_client import SSHClient


class VersionTracker:
    """
    Tracks package versions with JSON state persistence
    Implements Metadata-Driven approach with Zero-Download
    """
    
    def __init__(self, repo_root: Path, ssh_client: SSHClient, 
                 shell_executor: ShellExecutor, logger: Optional[logging.Logger] = None):
        """
        Initialize VersionTracker
        
        Args:
            repo_root: Repository root directory
            ssh_client: SSHClient instance for remote operations
            shell_executor: ShellExecutor for command execution
            logger: Optional logger instance
        """
        self.repo_root = repo_root
        self.ssh_client = ssh_client
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
        
        # State tracking
        self.state_file = self.repo_root / ".build_tracking" / "vps_state.json"
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # In-memory state
        self.state: Dict[str, Any] = self._load_state()
        
        # Initialize default structure
        if "packages" not in self.state:
            self.state["packages"] = {}
        if "metadata" not in self.state:
            self.state["metadata"] = {
                "last_updated": None,
                "repository": str(self.repo_root),
                "vps_host": ssh_client.vps_host
            }
    
    def _load_state(self) -> Dict[str, Any]:
        """Load state from JSON file"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            self.logger.info("No existing state file found, creating new")
        except Exception as e:
            self.logger.warning(f"Could not load state file: {e}")
        return {}
    
    def save_state(self) -> bool:
        """Save state to JSON file"""
        try:
            self.state["metadata"]["last_updated"] = datetime.now().isoformat()
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            self.logger.info(f"Saved state to {self.state_file}")
            return True
        except Exception as e:
            self.logger.error(f"Could not save state: {e}")
            return False
    
    def check_package_status(self, pkg_name: str, local_version: str) -> Tuple[str, Optional[str]]:
        """
        Check package status and return build decision
        
        Args:
            pkg_name: Package name
            local_version: Local version string (from SRCINFO)
        
        Returns:
            Tuple of (decision, remote_version)
            decision: "BUILD" or "SKIP"
            remote_version: Version on VPS (if exists)
        """
        self.logger.info(f"🔍 Checking package status: {pkg_name} (local: {local_version})")
        
        # Check local state first
        if pkg_name in self.state["packages"]:
            stored_package = self.state["packages"][pkg_name]
            stored_version = stored_package.get("version")
            stored_hash = stored_package.get("hash")
            
            if stored_version == local_version:
                # Version matches, verify integrity via SSH
                self.logger.debug(f"Version match for {pkg_name}, verifying integrity")
                remote_file = self._get_remote_file_path(pkg_name, stored_version)
                
                if remote_file and self.ssh_client.file_exists(remote_file):
                    current_hash = self.ssh_client.get_remote_hash(remote_file)
                    if current_hash and current_hash == stored_hash:
                        self.logger.info(f"✅ {pkg_name}: Integrity verified, skipping")
                        return "SKIP", stored_version
                    else:
                        self.logger.warning(f"⚠️ {pkg_name}: Hash mismatch, rebuilding")
                        return "BUILD", stored_version
                else:
                    self.logger.info(f"ℹ️ {pkg_name}: File missing on VPS, rebuilding")
                    return "BUILD", stored_version
            else:
                # Version mismatch
                self.logger.info(f"🔄 {pkg_name}: Version mismatch (local: {local_version}, stored: {stored_version})")
                return "BUILD", stored_version
        
        # Not in local state, check VPS directly
        self.logger.info(f"🔍 {pkg_name}: Not in state, checking VPS...")
        
        # Try to find any version on VPS
        remote_version = self._get_remote_version(pkg_name)
        if remote_version:
            # Found on VPS, adopt into state
            self.logger.info(f"📥 {pkg_name}: Found on VPS ({remote_version}), adopting into state")
            
            remote_file = self._get_remote_file_path(pkg_name, remote_version)
            remote_hash = None
            if remote_file:
                remote_hash = self.ssh_client.get_remote_hash(remote_file)
            
            self.state["packages"][pkg_name] = {
                "version": remote_version,
                "hash": remote_hash,
                "last_checked": datetime.now().isoformat(),
                "source": "adopted"
            }
            
            # Compare with local version
            if remote_version == local_version:
                self.logger.info(f"✅ {pkg_name}: Adopted and matches local, skipping")
                return "SKIP", remote_version
            else:
                self.logger.info(f"🔄 {pkg_name}: Adopted but version differs, building")
                return "BUILD", remote_version
        
        # Not found anywhere
        self.logger.info(f"📦 {pkg_name}: Not found on VPS, building")
        return "BUILD", None
    
    def _get_remote_version(self, pkg_name: str) -> Optional[str]:
        """Get version of package from VPS using SSH"""
        # List remote files for this package
        remote_files = self.ssh_client.list_remote_files(f"{pkg_name}-*.pkg.tar.*")
        
        if not remote_files:
            return None
        
        # Parse first matching file for version
        for file_path in remote_files:
            filename = Path(file_path).name
            parsed = self._parse_package_filename(filename)
            if parsed and parsed[0] == pkg_name:
                return parsed[1]
        
        return None
    
    def _get_remote_file_path(self, pkg_name: str, version: str) -> Optional[str]:
        """Get full remote path for a package version"""
        # Generate possible filename patterns
        patterns = []
        
        if ':' in version:
            # Version with epoch
            epoch, rest = version.split(':', 1)
            patterns.append(f"{pkg_name}-{epoch}-{rest}-*.pkg.tar.zst")
            patterns.append(f"{pkg_name}-{epoch}-{rest}-*.pkg.tar.xz")
        else:
            # Standard version
            patterns.append(f"{pkg_name}-{version}-*.pkg.tar.zst")
            patterns.append(f"{pkg_name}-{version}-*.pkg.tar.xz")
        
        # Check each pattern
        for pattern in patterns:
            remote_files = self.ssh_client.list_remote_files(pattern)
            if remote_files:
                return remote_files[0]
        
        return None
    
    def update_package_state(self, pkg_name: str, version: str, local_hash: Optional[str] = None) -> bool:
        """
        Update state for a built package
        
        Args:
            pkg_name: Package name
            version: Package version
            local_hash: Optional local hash (for verification)
        
        Returns:
            True if state updated successfully
        """
        try:
            # Get remote hash after upload
            remote_file = self._get_remote_file_path(pkg_name, version)
            remote_hash = None
            if remote_file:
                remote_hash = self.ssh_client.get_remote_hash(remote_file)
            
            self.state["packages"][pkg_name] = {
                "version": version,
                "hash": remote_hash or local_hash,
                "last_updated": datetime.now().isoformat(),
                "source": "built"
            }
            
            self.logger.info(f"📝 Updated state for {pkg_name}: {version}")
            return True
        except Exception as e:
            self.logger.error(f"Could not update state for {pkg_name}: {e}")
            return False
    
    def _parse_package_filename(self, filename: str) -> Optional[Tuple[str, str]]:
        """Parse package filename to extract name and version"""
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
                    # Check for epoch format
                    if remaining[0].isdigit() and '-' in '-'.join(remaining[1:]):
                        epoch = remaining[0]
                        version_part = remaining[1]
                        release_part = remaining[2]
                        version_str = f"{epoch}:{version_part}-{release_part}"
                        return potential_name, version_str
                    # Standard format
                    elif any(c.isdigit() for c in remaining[0]) and remaining[1].isdigit():
                        version_part = remaining[0]
                        release_part = remaining[1]
                        version_str = f"{version_part}-{release_part}"
                        return potential_name, version_str
        except Exception as e:
            self.logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None
    
    def sync_state_to_git(self) -> bool:
        """Sync state file to git repository"""
        try:
            # Save state first
            if not self.save_state():
                return False
            
            # Add to git
            rel_path = self.state_file.relative_to(self.repo_root)
            add_cmd = f"git add {rel_path}"
            self.shell_executor.run(add_cmd, check=True, log_cmd=True)
            
            # Commit
            commit_cmd = 'git commit -m "chore: update vps state [skip ci]"'
            self.shell_executor.run(commit_cmd, check=True, log_cmd=True)
            
            self.logger.info("✅ State synced to git")
            return True
        except Exception as e:
            self.logger.error(f"Could not sync state to git: {e}")
            return False
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Get state summary for logging"""
        return {
            "total_packages": len(self.state.get("packages", {})),
            "last_updated": self.state.get("metadata", {}).get("last_updated"),
            "vps_host": self.state.get("metadata", {}).get("vps_host")
        }
