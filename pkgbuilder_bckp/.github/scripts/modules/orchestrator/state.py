"""
Build state tracking for package builder system
Tracks built, skipped, and failed packages with comprehensive statistics
"""

import time
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging


@dataclass
class PackageInfo:
    """Information about a specific package"""
    name: str
    version: str
    is_aur: bool
    timestamp: float = field(default_factory=time.time)
    build_duration: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'name': self.name,
            'version': self.version,
            'is_aur': self.is_aur,
            'timestamp': self.timestamp,
            'build_duration': self.build_duration,
            'success': self.success,
            'error_message': self.error_message
        }


class BuildState:
    """Tracks build state, statistics, and package outcomes"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize BuildState
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        
        # Package tracking
        self._built_packages: List[PackageInfo] = []
        self._skipped_packages: List[PackageInfo] = []
        self._failed_packages: List[PackageInfo] = []
        
        # Statistics
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.total_packages = 0
        
        # Detailed statistics
        self.stats = {
            'aur_success': 0,
            'local_success': 0,
            'aur_failed': 0,
            'local_failed': 0,
            'aur_skipped': 0,
            'local_skipped': 0,
        }
    
    def add_built(self, pkg_name: str, version: str, is_aur: bool = False, 
                  build_duration: Optional[float] = None) -> None:
        """
        Add a successfully built package
        
        Args:
            pkg_name: Package name
            version: Package version
            is_aur: Whether it's an AUR package
            build_duration: Build duration in seconds
        """
        pkg_info = PackageInfo(
            name=pkg_name,
            version=version,
            is_aur=is_aur,
            build_duration=build_duration,
            success=True
        )
        
        self._built_packages.append(pkg_info)
        
        if is_aur:
            self.stats['aur_success'] += 1
        else:
            self.stats['local_success'] += 1
        
        self.total_packages += 1
        self.logger.info(f"✅ Built package registered: {pkg_name} ({version})")
    
    def add_skipped(self, pkg_name: str, version: str, is_aur: bool = False, 
                    reason: str = "up-to-date") -> None:
        """
        Add a skipped package
        
        Args:
            pkg_name: Package name
            version: Package version
            is_aur: Whether it's an AUR package
            reason: Reason for skipping
        """
        pkg_info = PackageInfo(
            name=pkg_name,
            version=version,
            is_aur=is_aur,
            success=True,
            error_message=f"Skipped: {reason}"
        )
        
        self._skipped_packages.append(pkg_info)
        
        if is_aur:
            self.stats['aur_skipped'] += 1
        else:
            self.stats['local_skipped'] += 1
        
        self.total_packages += 1
        self.logger.info(f"⏭️ Skipped package registered: {pkg_name} ({version}) - {reason}")
    
    def add_failed(self, pkg_name: str, version: str, is_aur: bool = False, 
                   error_message: str = "Build failed") -> None:
        """
        Add a failed package
        
        Args:
            pkg_name: Package name
            version: Package version
            is_aur: Whether it's an AUR package
            error_message: Error description
        """
        pkg_info = PackageInfo(
            name=pkg_name,
            version=version,
            is_aur=is_aur,
            success=False,
            error_message=error_message
        )
        
        self._failed_packages.append(pkg_info)
        
        if is_aur:
            self.stats['aur_failed'] += 1
        else:
            self.stats['local_failed'] += 1
        
        self.total_packages += 1
        self.logger.error(f"❌ Failed package registered: {pkg_name} - {error_message}")
    
    def mark_complete(self) -> None:
        """Mark build as complete and calculate final statistics"""
        self.end_time = time.time()
    
    def get_duration(self) -> float:
        """Get total build duration in seconds"""
        end = self.end_time or time.time()
        return end - self.start_time
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive build summary"""
        return {
            'total_packages': self.total_packages,
            'built': len(self._built_packages),
            'skipped': len(self._skipped_packages),
            'failed': len(self._failed_packages),
            'aur_success': self.stats['aur_success'],
            'local_success': self.stats['local_success'],
            'aur_failed': self.stats['aur_failed'],
            'local_failed': self.stats['local_failed'],
            'aur_skipped': self.stats['aur_skipped'],
            'local_skipped': self.stats['local_skipped'],
            'duration_seconds': self.get_duration(),
            'start_time': datetime.fromtimestamp(self.start_time).isoformat(),
            'end_time': datetime.fromtimestamp(self.end_time).isoformat() if self.end_time else None,
            'success_rate': (len(self._built_packages) / self.total_packages * 100) if self.total_packages > 0 else 0,
        }
    
    def get_built_packages(self) -> List[Dict[str, Any]]:
        """Get list of built packages as dictionaries"""
        return [pkg.to_dict() for pkg in self._built_packages]
    
    def get_skipped_packages(self) -> List[Dict[str, Any]]:
        """Get list of skipped packages as dictionaries"""
        return [pkg.to_dict() for pkg in self._skipped_packages]
    
    def get_failed_packages(self) -> List[Dict[str, Any]]:
        """Get list of failed packages as dictionaries"""
        return [pkg.to_dict() for pkg in self._failed_packages]
    
    def get_all_packages(self) -> List[Dict[str, Any]]:
        """Get all packages combined"""
        return (
            self.get_built_packages() +
            self.get_skipped_packages() +
            self.get_failed_packages()
        )
    
    def reset(self) -> None:
        """Reset build state for a new build"""
        self._built_packages.clear()
        self._skipped_packages.clear()
        self._failed_packages.clear()
        
        self.start_time = time.time()
        self.end_time = None
        self.total_packages = 0
        
        for key in self.stats:
            self.stats[key] = 0
        
        self.logger.info("Build state reset for new build")