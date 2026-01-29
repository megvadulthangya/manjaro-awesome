"""
Rsync Client Module
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from modules.common.shell_executor import ShellExecutor

class RsyncClient:
    """Handles Rsync operations"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, logger: Optional[logging.Logger] = None):
        self.config = config
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
        self.vps_user = config.get('vps_user')
        self.vps_host = config.get('vps_host')
        self.remote_dir = config.get('remote_dir')

    def mirror_remote(self, remote_pattern: str, local_dir: Path, temp_dir: Optional[Path] = None) -> bool:
        """Download from remote"""
        local_dir.mkdir(parents=True, exist_ok=True)
        source = f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/{remote_pattern}"
        cmd = [
            "rsync", "-avz", "--quiet",
            "-e", "ssh -o StrictHostKeyChecking=no",
            source, str(local_dir)
        ]
        res = self.shell_executor.run(cmd, check=False)
        return res.returncode == 0

    def upload(self, local_files: List[str], base_dir: Optional[Path] = None) -> bool:
        """Upload to remote"""
        if not local_files: return True
        
        target = f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/"
        cmd = [
            "rsync", "-avz", "--quiet",
            "-e", "ssh -o StrictHostKeyChecking=no"
        ] + local_files + [target]
        
        res = self.shell_executor.run(cmd, check=False)
        return res.returncode == 0