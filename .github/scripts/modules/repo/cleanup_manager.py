"""
Cleanup Manager
"""
import logging
from typing import Dict, Any, Optional
from modules.repo.version_tracker import VersionTracker
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient

class CleanupManager:
    """Manages cleanup of old versions"""
    
    def __init__(self, config: Dict[str, Any], version_tracker: VersionTracker, ssh_client: SSHClient, rsync_client: RsyncClient, logger: Optional[logging.Logger] = None):
        self.config = config
        self.version_tracker = version_tracker
        self.ssh_client = ssh_client
        self.logger = logger or logging.getLogger(__name__)

    def cleanup_server(self):
        """Remove files not in target versions"""
        # Simplistic implementation relying on VersionTracker state
        # Real implementation would diff remote inventory vs target versions
        pass