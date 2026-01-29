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

class BuildTracker:
    """Tracks build state and determines if packages need rebuilding"""

    def __init__(self, tracking_dir: Path, version_tracker, 
                 version_manager, logger: Optional[logging.Logger] = None):
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
        
        # Ensure tracking directory exists
        if not self.tracking_dir.exists():
            self.tracking_dir.mkdir(parents=True, exist_ok=True)

    def calculate_hash(self, file_path: Path) -> str:
        """
        Calculate SHA256 hash of a file
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
        """
        # Double check directory exists
        if not self.tracking_dir.exists():
            self.tracking_dir.mkdir(parents=True, exist_ok=True)
            
        tracking_file = self.tracking_dir / f"{pkg_name}.json"
        
        try:
            with open(tracking_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.info(f"💾 Saved build tracking for {pkg_name}")
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to save tracking JSON for {pkg_name}: {e}")
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
            self.logger.debug(f"Package directory not found: {pkg_dir}")
            return False, tracking_data
        
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            self.logger.debug(f"PKGBUILD not found for {pkg_name}")
            return False, tracking_data
        
        # Calculate current PKGBUILD hash
        current_hash = self.calculate_hash(pkgbuild_path)
        if not current_hash:
            return False, tracking_data
        
        # Extract current version
        current_pkgver, current_pkgrel, current_epoch = self.version_manager.extract_from_pkgbuild(pkg_dir)
        
        if not current_pkgver:
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
            return True, new_data
        
        # Check if PKGBUILD has changed
        last_hash = tracking_data.get('last_hash', '')
        last_version = tracking_data.get('last_version', '')
        
        if current_hash != last_hash:
            self.logger.info(f"🔀 PKGBUILD hash changed for {pkg_name}")
            return True, new_data
        
        if current_version != last_version:
            self.logger.info(f"🔀 Version changed for {pkg_name}: {last_version} -> {current_version}")
            return True, new_data
        
        return False, new_data