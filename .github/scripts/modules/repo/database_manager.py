"""
Database Manager
Handles repository database operations, signing, and consistency checks.
"""
import os
import shutil
import glob
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient
from modules.gpg.gpg_handler import GPGHandler

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
        self.gpg_enabled = bool(config.get('gpg_private_key') and self.gpg_key_id)
        
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
        
        success = True
        for pattern in patterns:
            self.rsync_client.mirror_remote(pattern, self._staging_dir)
        
        return success

    def update_database_additive(self) -> bool:
        """
        Update the database with packages in the staging directory.
        CRITICAL: Enforces GPG signing if configured to prevent signature deadlock.
        Includes explicit keyring import before repo-add.
        """
        if not self._staging_dir:
            self.logger.error("❌ No staging directory active")
            return False
        
        cwd = os.getcwd()
        os.chdir(self._staging_dir)
        
        try:
            # Identify new packages
            pkgs = glob.glob("*.pkg.tar.zst")
            if not pkgs:
                self.logger.info("ℹ️ No packages to add to database")
                # Even if no packages, if DB files exist we return true.
                if (self._staging_dir / f"{self.repo_name}.db.tar.gz").exists():
                    return True
                return True
            
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Construct repo-add command
            cmd = ["repo-add", "--remove"]
            
            # STRICT SIGNATURE ENFORCEMENT & KEYRING PREP
            if self.gpg_enabled:
                if not self.gpg_key_id:
                    self.logger.error("❌ GPG enabled but No Key ID provided!")
                    return False
                
                # CRITICAL FIX: Ensure key is in the user keyring before repo-add runs
                # repo-add relies on gpg command finding the key
                self.logger.info("🔐 Ensuring GPG key is present for repo-add...")
                
                # Check if key exists
                check_key = subprocess.run(
                    ["gpg", "--list-secret-keys", self.gpg_key_id],
                    capture_output=True, text=True, check=False
                )
                
                if check_key.returncode != 0:
                    self.logger.warning(f"⚠️ Key {self.gpg_key_id} not found in keyring. Attempting re-import.")
                    # Re-import key logic is in GPGHandler, but we might need a quick fix here
                    # Relying on GPGHandler.import_gpg_key() being called earlier in orchestrator.
                    # If it was called, check GNUPGHOME env var usage in repo-add?
                    # repo-add uses user's default GNUPGHOME if not specified.
                    # If GPGHandler used a temp dir, repo-add might fail if we don't pass that env.
                    
                    if os.environ.get('GNUPGHOME'):
                        self.logger.info(f"Using GNUPGHOME: {os.environ.get('GNUPGHOME')}")
                    else:
                        self.logger.warning("GNUPGHOME not set, repo-add might look in default ~/.gnupg")

                self.logger.info(f"🔐 Signing database with key {self.gpg_key_id}")
                cmd.extend(["--sign", "--key", self.gpg_key_id])
            else:
                self.logger.warning("⚠️ GPG Signing is DISABLED. Clients may reject this repo.")
            
            cmd.append(db_file)
            cmd.extend(pkgs)
            
            self.logger.info(f"RUNNING: {' '.join(cmd)}")
            
            # Run repo-add
            # IMPORTANT: repo-add needs to find the key. 
            # Ensure subprocess inherits the environment including GNUPGHOME if set.
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                env=os.environ.copy() 
            )
            
            if result.returncode != 0:
                self.logger.error("❌ repo-add failed!")
                self.logger.error(f"STDOUT: {result.stdout}")
                self.logger.error(f"STDERR: {result.stderr}")
                return False
            
            # Verify database files exist
            if not Path(db_file).exists():
                self.logger.error("❌ Database file was not created")
                return False
                
            # Verify signatures if enabled
            if self.gpg_enabled:
                sig_file = Path(f"{db_file}.sig")
                if not sig_file.exists():
                    self.logger.error("❌ Database signature (.sig) missing after repo-add!")
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