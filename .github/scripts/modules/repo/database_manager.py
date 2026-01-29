"""
Database Manager
Handles repository database operations using Legacy Logic.
Uses shell wildcard expansion and manual GPG signing.
"""
import os
import shutil
import glob
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient
from modules.gpg.gpg_handler import GPGHandler

class DatabaseManager:
    """Manages the Pacman repository database"""
    
    def __init__(self, config: Dict[str, Any], ssh_client: SSHClient, 
                 rsync_client: RsyncClient, gpg_handler: GPGHandler, logger: Optional[logging.Logger] = None):
        self.config = config
        self.ssh_client = ssh_client
        self.rsync_client = rsync_client
        self.gpg_handler = gpg_handler
        self.logger = logger or logging.getLogger(__name__)
        
        self.repo_name = config.get('repo_name', 'custom_repo')
        self._staging_dir: Optional[Path] = None

    def create_staging_dir(self) -> Path:
        """Create a clean staging directory"""
        import tempfile
        self._staging_dir = Path(tempfile.mkdtemp(prefix=f"{self.repo_name}_staging_"))
        return self._staging_dir

    def cleanup_staging_dir(self):
        """Remove the staging directory"""
        if self._staging_dir and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)

    def download_existing_database(self) -> bool:
        """Download existing database files from VPS to staging"""
        if not self._staging_dir:
            return False
            
        self.logger.info("📥 Downloading existing database...")
        patterns = [
            f"{self.repo_name}.db*",
            f"{self.repo_name}.files*"
        ]
        
        for pattern in patterns:
            self.rsync_client.mirror_remote(pattern, self._staging_dir)
        
        return True

    def update_database_additive(self) -> bool:
        """
        Update the database using Legacy Logic.
        1. Remove old DB files.
        2. Run repo-add with shell wildcard (*.pkg.tar.zst).
        3. Manually sign files.
        """
        if not self._staging_dir:
            self.logger.error("❌ No staging directory active")
            return False
        
        cwd = os.getcwd()
        os.chdir(self._staging_dir)
        
        try:
            # Identify packages
            pkgs = glob.glob("*.pkg.tar.zst")
            if not pkgs:
                self.logger.info("ℹ️ No packages found in staging. Database update skipped.")
                return True
            
            # 1. Clean Old Database Files
            # We remove them to force a regeneration which is cleaner/safer in CI environments
            db_files = [
                f"{self.repo_name}.db",
                f"{self.repo_name}.db.tar.gz",
                f"{self.repo_name}.files",
                f"{self.repo_name}.files.tar.gz"
            ]
            for f in db_files:
                if os.path.exists(f):
                    os.remove(f)

            # 2. Run repo-add with Shell Wildcard
            # Legacy logic: DO NOT use --sign here. We sign later.
            # Use shell=True to let the shell expand *.pkg.tar.zst
            db_target = f"{self.repo_name}.db.tar.gz"
            cmd = f"repo-add {db_target} *.pkg.tar.zst"
            
            env = os.environ.copy()
            env['LC_ALL'] = 'C'
            
            self.logger.info(f"RUNNING: {cmd}")
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                env=env
            )
            
            if result.returncode != 0:
                self.logger.error("❌ repo-add failed!")
                self.logger.error(f"STDOUT: {result.stdout}")
                self.logger.error(f"STDERR: {result.stderr}")
                return False
            
            # Verify creation
            if not Path(db_target).exists():
                self.logger.error("❌ Database file was not created")
                return False
            
            # 3. Manual Signing (Legacy Logic)
            if self.gpg_handler.gpg_enabled:
                self.logger.info("🔐 Manually signing database files...")
                if not self.gpg_handler.sign_repository_files(self.repo_name, str(self._staging_dir)):
                    self.logger.error("❌ Failed to sign database files")
                    return False
                self.logger.info("✅ Database signed successfully")
            else:
                self.logger.warning("⚠️ GPG disabled, database unsigned")

            self.logger.info("✅ Database regeneration complete")
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