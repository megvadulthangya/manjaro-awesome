"""
Database Manager
Handles repository database operations, signing, and consistency checks.
Isolates GPG keyring to prevent environment conflicts.
"""
import os
import shutil
import glob
import subprocess
import logging
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List

from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient

class DatabaseManager:
    """Manages the Pacman repository database"""
    
    def __init__(self, config: Dict[str, Any], ssh_client: SSHClient, 
                 rsync_client: RsyncClient, logger: Optional[logging.Logger] = None):
        self.config = config
        self.ssh_client = ssh_client
        self.rsync_client = rsync_client
        self.logger = logger or logging.getLogger(__name__)
        
        self.repo_name = config.get('repo_name', 'custom_repo')
        self.gpg_key_id = config.get('gpg_key_id')
        self.gpg_private_key = config.get('gpg_private_key')
        self.gpg_enabled = bool(self.gpg_private_key and self.gpg_key_id)
        
        self._staging_dir: Optional[Path] = None
        self._gpg_home: Optional[Path] = None

    def create_staging_dir(self) -> Path:
        """Create a clean staging directory"""
        self._staging_dir = Path(tempfile.mkdtemp(prefix=f"{self.repo_name}_staging_"))
        return self._staging_dir

    def cleanup_staging_dir(self):
        """Remove the staging directory and temp GPG home"""
        if self._staging_dir and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)
        if self._gpg_home and self._gpg_home.exists():
            shutil.rmtree(self._gpg_home, ignore_errors=True)

    def download_existing_database(self) -> bool:
        """Download existing database files from VPS to staging"""
        if not self._staging_dir:
            return False
            
        self.logger.info("📥 Downloading existing database...")
        patterns = [
            f"{self.repo_name}.db*",
            f"{self.repo_name}.files*"
        ]
        
        success = True
        for pattern in patterns:
            self.rsync_client.mirror_remote(pattern, self._staging_dir)
        
        return success

    def _setup_gpg_env(self) -> Optional[Dict[str, str]]:
        """
        Create isolated GPG home and import key.
        Returns environment dict with GNUPGHOME set.
        """
        if not self.gpg_enabled:
            return None

        try:
            # Create fresh temp GPG home
            self._gpg_home = Path(tempfile.mkdtemp(prefix="repo_gpg_"))
            env = os.environ.copy()
            env['GNUPGHOME'] = str(self._gpg_home)
            
            # Import key into this specific keyring
            self.logger.info(f"🔐 Importing GPG key to isolated keyring: {self._gpg_home}")
            
            # Handle key data format
            key_input = self.gpg_private_key
            if isinstance(key_input, str):
                key_input = key_input.encode('utf-8')

            import_res = subprocess.run(
                ["gpg", "--batch", "--import"],
                input=key_input,
                capture_output=True,
                env=env,
                check=False
            )
            
            if import_res.returncode != 0:
                self.logger.error(f"❌ GPG Import failed: {import_res.stderr.decode()}")
                return None

            return env
            
        except Exception as e:
            self.logger.error(f"❌ GPG Setup exception: {e}")
            return None

    def update_database_additive(self) -> bool:
        """
        Update the database with packages in the staging directory.
        Uses isolated GNUPGHOME to ensure repo-add sees the key.
        """
        if not self._staging_dir:
            self.logger.error("❌ No staging directory active")
            return False
        
        cwd = os.getcwd()
        os.chdir(self._staging_dir)
        
        try:
            pkgs = glob.glob("*.pkg.tar.zst")
            if not pkgs:
                self.logger.info("ℹ️ No packages to add to database")
                if (self._staging_dir / f"{self.repo_name}.db.tar.gz").exists():
                    return True
                return True
            
            db_file = f"{self.repo_name}.db.tar.gz"
            cmd = ["repo-add", "--remove"]
            
            # Setup GPG
            env = os.environ.copy()
            if self.gpg_enabled:
                gpg_env = self._setup_gpg_env()
                if gpg_env:
                    env = gpg_env
                    self.logger.info(f"🔐 Signing database with key {self.gpg_key_id}")
                    cmd.extend(["--sign", "--key", self.gpg_key_id])
                else:
                    self.logger.error("❌ GPG setup failed, cannot sign database")
                    return False
            
            cmd.append(db_file)
            cmd.extend(pkgs)
            
            self.logger.info(f"RUNNING: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                env=env # Pass the env with GNUPGHOME
            )
            
            if result.returncode != 0:
                self.logger.error("❌ repo-add failed!")
                self.logger.error(f"STDOUT: {result.stdout}")
                self.logger.error(f"STDERR: {result.stderr}")
                return False
            
            if not Path(db_file).exists():
                self.logger.error("❌ Database file was not created")
                return False
                
            if self.gpg_enabled:
                sig_file = Path(f"{db_file}.sig")
                if not sig_file.exists():
                    self.logger.error("❌ Database signature (.sig) missing!")
                    return False
                self.logger.info("✅ Database signature verified")

            self.logger.info("✅ Database updated successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Database update exception: {e}")
            return False
        finally:
            os.chdir(cwd)

    def upload_updated_files(self) -> bool:
        """Upload all files from staging to VPS"""
        if not self._staging_dir:
            return False
            
        files = glob.glob(str(self._staging_dir / "*"))
        if not files:
            return True
            
        self.logger.info(f"📤 Uploading {len(files)} files to remote...")
        return self.rsync_client.upload(files)