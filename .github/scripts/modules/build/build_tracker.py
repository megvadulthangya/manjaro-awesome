"""
Build Tracker for managing package build state
Handles PKGBUILD hashing, tracking JSON, and build decision logic
"""

import json
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

# Avoid circular imports by using TYPE_CHECKING if needed, 
# but for logic we pass instances
from modules.repo.version_tracker import VersionTracker
from modules.build.version_manager import VersionManager

class BuildTracker:
    """Tracks build state and determines if packages need rebuilding"""

    def __init__(self, tracking_dir: Path, version_tracker: VersionTracker, 
                 version_manager: VersionManager, logger: Optional[logging.Logger] = None):
        """
        Initialize BuildTracker
        
        Args:
            tracking_dir: Directory to store tracking JSON files
            version_tracker: VersionTracker instance for remote checks
            version_manager: VersionManager for version extraction
            logger: Optional logger instance
        """
        self.tracking_dir = tracking_dir
        self.version_tracker = version_tracker
        self.version_manager = version_manager
        self.logger = logger or logging.getLogger(__name__)
        
        if not self.tracking_dir.exists():
            self.tracking_dir.mkdir(parents=True, exist_ok=True)

    def calculate_hash(self, file_path: Path) -> str:
        """
        Calculate SHA256 hash of a file
        
        Args:
            file_path: Path to file
            
        Returns:
            SHA256 hash string
        """
        if not file_path.exists():
            return ""
        
        try:
            with open(file_path, 'rb') as f:
                file_hash = hashlib.sha256()
                chunk = f.read(8192)
                while chunk:
                    file_hash.update(chunk)
                    chunk = f.read(8192)
                return file_hash.hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to calculate hash for {file_path}: {e}")
            return ""

    def load_tracking(self, pkg_name: str) -> Dict[str, Any]:
        """
        Load tracking JSON for a package
        
        Args:
            pkg_name: Package name
            
        Returns:
            Tracking data dictionary
        """
        tracking_file = self.tracking_dir / f"{pkg_name}.json"
        
        if not tracking_file.exists():
            return {}
        
        try:
            with open(tracking_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load tracking JSON for {pkg_name}: {e}")
            return {}

    def save_tracking(self, pkg_name: str, data: Dict[str, Any]) -> bool:
        """
        Save tracking JSON for a package
        
        Args:
            pkg_name: Package name
            data: Tracking data to save
            
        Returns:
            True if successful
        """
        tracking_file = self.tracking_dir / f"{pkg_name}.json"
        
        try:
            with open(tracking_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.debug(f"Saved tracking JSON for {pkg_name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save tracking JSON for {pkg_name}: {e}")
            return False

    def should_build(self, pkg_name: str, pkg_dir: Path) -> Tuple[bool, Dict[str, Any]]:
        """
        Determine if local package needs to be built
        
        Args:
            pkg_name: Package name
            pkg_dir: Directory containing PKGBUILD
            
        Returns:
            Tuple of (should_build, tracking_data)
        """
        # Load existing tracking data
        tracking_data = self.load_tracking(pkg_name)
        
        if not pkg_dir.exists():
            self.logger.error(f"Package directory not found: {pkg_dir}")
            return False, tracking_data
        
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            self.logger.error(f"PKGBUILD not found for {pkg_name}")
            return False, tracking_data
        
        # Calculate current PKGBUILD hash
        current_hash = self.calculate_hash(pkgbuild_path)
        if not current_hash:
            self.logger.error(f"Failed to calculate PKGBUILD hash for {pkg_name}")
            return False, tracking_data
        
        # Extract current version from PKGBUILD using VersionManager
        # Note: VersionManager must have extract_from_pkgbuild method
        current_pkgver, current_pkgrel, current_epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
        
        if not current_pkgver or not current_pkgrel:
            self.logger.error(f"Failed to extract version from PKGBUILD for {pkg_name}")
            return False, tracking_data
        
        current_version = f"{current_pkgver}-{current_pkgrel}"
        if current_epoch and current_epoch != '0':
            current_version = f"{current_epoch}:{current_version}"
        
        # Prepare new tracking data
        new_data = {
            'last_hash': current_hash,
            'last_version': current_version,
            'last_built': datetime.now().isoformat(),
            'pkgver': current_pkgver,
            'pkgrel': current_pkgrel,
            'epoch': current_epoch
        }
        
        # Check tracking data
        if not tracking_data:
            # No tracking data - first build
            self.logger.info(f"🆕 First build detected for {pkg_name}")
            return True, new_data
        
        # Check if PKGBUILD has changed
        last_hash = tracking_data.get('last_hash', '')
        last_version = tracking_data.get('last_version', '')
        
        if current_hash != last_hash:
            self.logger.info(f"🔀 PKGBUILD changed for {pkg_name} (hash mismatch)")
            return True, new_data
        
        # Check if version has changed (in case hash is same but version updated elsewhere)
        if current_version != last_version:
            self.logger.info(f"🔀 Version changed for {pkg_name}: {last_version} -> {current_version}")
            return True, new_data
        
        # Also check if package exists on server with same version
        found, remote_version, _ = self.version_tracker.is_package_on_remote(pkg_name, current_version)
        
        if found:
            self.logger.info(f"✅ {pkg_name} already on server with same version ({current_version})")
            return False, tracking_data
        else:
            self.logger.info(f"🔄 {pkg_name} not on server or different version, needs build")
            return True, new_data