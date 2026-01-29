"""
Build State
"""
import time
import logging
from typing import Dict, Any, List, Optional

class BuildState:
    """Tracks build outcomes"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        self.built: List[str] = []
        self.skipped: List[str] = []
        self.failed: List[str] = []

    def add_built(self, pkg: str, ver: str, is_aur: bool = False):
        self.built.append(pkg)
    
    def add_skipped(self, pkg: str, ver: str, is_aur: bool = False, reason: str = ""):
        self.skipped.append(pkg)

    def add_failed(self, pkg: str, ver: str, is_aur: bool = False, error_message: str = ""):
        self.failed.append(pkg)

    def mark_complete(self):
        pass

    def get_summary(self) -> Dict[str, Any]:
        return {
            'built': len(self.built),
            'skipped': len(self.skipped),
            'failed': len(self.failed)
        }