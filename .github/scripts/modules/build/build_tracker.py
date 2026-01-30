"""
Build tracking module
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class BuildTracker:
    """Tracks build status and history"""
    
    def __init__(self, tracking_dir):
        self.tracking_dir = Path(tracking_dir)
        self.tracking_dir.mkdir(exist_ok=True)
    
    def get_build_status(self, package_name):
        """Get build status for a package"""
        status_file = self.tracking_dir / f"{package_name}.json"
        
        if not status_file.exists():
            return None
        
        try:
            with open(status_file, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    
    def update_build_status(self, package_name, status, version=None, error=None):
        """Update build status for a package"""
        status_file = self.tracking_dir / f"{package_name}.json"
        
        status_data = {
            'package': package_name,
            'status': status,
            'last_updated': datetime.now().isoformat(),
            'version': version,
            'error': error
        }
        
        try:
            with open(status_file, 'w') as f:
                json.dump(status_data, f, indent=2)
            
            logger.info(f"Updated build status for {package_name}: {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to update build status for {package_name}: {e}")
            return False
    
    def get_all_statuses(self):
        """Get build status for all packages"""
        statuses = {}
        
        for status_file in self.tracking_dir.glob("*.json"):
            try:
                with open(status_file, 'r') as f:
                    status_data = json.load(f)
                    package_name = status_data.get('package', status_file.stem)
                    statuses[package_name] = status_data
            except Exception:
                pass
        
        return statuses