"""
Build Tracker Module - Tracks build progress and statistics
"""

import time
from typing import Dict, List


class BuildTracker:
    """Tracks build progress, statistics, and package information"""
    
    def __init__(self):
        # State
        self.hokibot_data = []
        self.rebuilt_local_packages = []
        self.skipped_packages = []
        self.built_packages = []
        
        # Statistics
        self.stats = {
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
        }
        
        # Start time
        self.start_time = time.time()
    
    def add_hokibot_data(self, pkg_name: str, pkgver: str, pkgrel: str, epoch: str = None):
        """Add package metadata for hokibot tracking"""
        self.hokibot_data.append({
            'name': pkg_name,
            'built_version': f"{epoch or '0'}:{pkgver}-{pkgrel}" if epoch and epoch != '0' else f"{pkgver}-{pkgrel}",
            'pkgver': pkgver,
            'pkgrel': pkgrel,
            'epoch': epoch
        })
    
    def record_built_package(self, pkg_name: str, version: str, is_aur: bool = False):
        """Record a successfully built package"""
        self.built_packages.append(f"{pkg_name} ({version})")
        if is_aur:
            self.stats["aur_success"] += 1
        else:
            self.stats["local_success"] += 1
    
    def record_failed_package(self, is_aur: bool = False):
        """Record a failed package build"""
        if is_aur:
            self.stats["aur_failed"] += 1
        else:
            self.stats["local_failed"] += 1
    
    def record_skipped_package(self, pkg_name: str, version: str):
        """Record a skipped package (already up-to-date)"""
        self.skipped_packages.append(f"{pkg_name} ({version})")
    
    def get_elapsed_time(self) -> float:
        """Get elapsed time since tracking started"""
        return time.time() - self.start_time
    
    def get_summary(self) -> Dict:
        """Get build summary statistics"""
        return {
            "elapsed": self.get_elapsed_time(),
            **self.stats,
            "total_built": self.stats["aur_success"] + self.stats["local_success"],
            "skipped": len(self.skipped_packages),
            "hokibot_entries": len(self.hokibot_data)
        }