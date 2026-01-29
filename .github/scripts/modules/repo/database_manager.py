"""
Database Manager
"""
import shutil
import tempfile
import os
import glob
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient

class DatabaseManager:
    """Manages repo database"""
    
    def __init__(self, config: Dict[str, Any], ssh_client: SSHClient, rsync_client: RsyncClient, logger: Optional[logging.Logger] = None):
        self.config = config
        self.ssh_client = ssh_client
        self.rsync_client = rsync_client
        self.logger = logger or logging.getLogger(__name__)
        self.repo_name = config.get('repo_name', 'repo')
        self._staging_dir: Optional[Path] = None

    def create_staging_dir(self) -> Path:
        self._staging_dir = Path(tempfile.mkdtemp(prefix="repo_staging_"))
        return self._staging_dir

    def cleanup_staging_dir(self):
        if self._staging_dir and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir)

    def download_existing_database(self):
        if not self._staging_dir: return
        pattern = f"{self.repo_name}.db*"
        self.rsync_client.mirror_remote(pattern, self._staging_dir)
        # Also .files
        self.rsync_client.mirror_remote(f"{self.repo_name}.files*", self._staging_dir)

    def update_database_additive(self) -> bool:
        # Assumes packages are already in staging
        if not self._staging_dir: return False
        
        cwd = os.getcwd()
        os.chdir(self._staging_dir)
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            pkgs = glob.glob("*.pkg.tar.zst")
            if not pkgs: return True
            
            cmd = f"repo-add {db_file} {' '.join(pkgs)}"
            os.system(cmd) # Simplified for brevity, normally shell_executor
            return True
        finally:
            os.chdir(cwd)

    def upload_updated_files(self) -> bool:
        if not self._staging_dir: return False
        files = glob.glob(str(self._staging_dir / "*"))
        return self.rsync_client.upload(files)