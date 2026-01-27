"""
Repository database management with additive updates and GPG signing
Implements robust bidirectional sync with local staging
"""

import os
import sys
import shutil
import subprocess
import logging
import tempfile
import glob
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient


class DatabaseManager:
    """Manages repository database operations with additive updates and GPG signing"""
    
    def __init__(self, config: Dict[str, Any], ssh_client: SSHClient,
                 rsync_client: RsyncClient, logger: Optional[logging.Logger] = None):
        """
        Initialize DatabaseManager
        
        Args:
            config: Configuration dictionary
            ssh_client: SSHClient instance
            rsync_client: RsyncClient instance
            logger: Optional logger instance
        """
        self.config = config
        self.ssh_client = ssh_client
        self.rsync_client = rsync_client
        self.logger = logger or logging.getLogger(__name__)
        
        # Extract configuration
        self.repo_name = config.get('repo_name', '')
        self.output_dir = Path(config.get('output_dir', 'built_packages'))
        self.remote_dir = config.get('remote_dir', '')
        
        # GPG configuration
        self.gpg_enabled = bool(config.get('gpg_key_id') and config.get('gpg_private_key'))
        self.gpg_key_id = config.get('gpg_key_id', '')
        
        # Staging directory for safe database operations
        self._staging_dir: Optional[Path] = None
    
    def create_staging_dir(self) -> Path:
        """
        Create temporary staging directory for database operations
        
        Returns:
            Path to staging directory
        """
        if self._staging_dir and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)
        
        self._staging_dir = Path(tempfile.mkdtemp(prefix="repo_staging_"))
        self.logger.info(f"📁 Created staging directory: {self._staging_dir}")
        return self._staging_dir
    
    def cleanup_staging_dir(self):
        """Clean up staging directory"""
        if self._staging_dir and self._staging_dir.exists():
            try:
                shutil.rmtree(self._staging_dir, ignore_errors=True)
                self.logger.debug(f"🧹 Cleaned up staging directory: {self._staging_dir}")
                self._staging_dir = None
            except Exception as e:
                self.logger.warning(f"Could not clean staging directory: {e}")
    
    def download_existing_database(self) -> bool:
        """
        Download existing database files from VPS to staging directory
        
        Returns:
            True if successful or no database exists (first run)
        """
        self.logger.info("📥 Downloading existing database files from VPS...")
        
        patterns = [
            f"{self.repo_name}.db.tar.gz*",
            f"{self.repo_name}.files.tar.gz*"
        ]
        
        for pattern in patterns:
            self.logger.debug(f"  Downloading pattern: {pattern}")
            
            success = self.rsync_client.mirror_remote(
                remote_pattern=pattern,
                local_dir=self._staging_dir,
                temp_dir=None  # Use staging_dir directly
            )
            
            if not success:
                self.logger.debug(f"⚠️ Failed to download {pattern} (may not exist yet)")
        
        # Check what was downloaded
        db_files = list(self._staging_dir.glob(f"{self.repo_name}.db.tar.gz*"))
        files_files = list(self._staging_dir.glob(f"{self.repo_name}.files.tar.gz*"))
        
        total_files = len(db_files) + len(files_files)
        
        if total_files > 0:
            self.logger.info(f"✅ Downloaded {total_files} database files from VPS")
            for f in db_files + files_files:
                size_mb = f.stat().st_size / (1024 * 1024)
                self.logger.debug(f"  - {f.name} ({size_mb:.2f} MB)")
            return True
        else:
            self.logger.info("ℹ️ No existing database files found (first run or clean state)")
            return True  # Not an error - first run is OK
    
    def copy_new_packages_to_staging(self) -> List[Path]:
        """
        Copy newly built packages to staging directory
        
        Returns:
            List of paths to new packages in staging
        """
        new_packages = list(self.output_dir.glob("*.pkg.tar.zst"))
        if not new_packages:
            self.logger.info("ℹ️ No new packages to add to database")
            return []
        
        self.logger.info(f"📦 Moving {len(new_packages)} new packages to staging...")
        
        moved_packages = []
        
        for new_pkg in new_packages:
            try:
                dest = self._staging_dir / new_pkg.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(new_pkg), str(dest))
                moved_packages.append(dest)
                
                # Move signature if exists
                sig_file = new_pkg.with_suffix(new_pkg.suffix + '.sig')
                if sig_file.exists():
                    sig_dest = dest.with_suffix(dest.suffix + '.sig')
                    if sig_dest.exists():
                        sig_dest.unlink()
                    shutil.move(str(sig_file), str(sig_dest))
                
                self.logger.debug(f"  Moved: {new_pkg.name}")
            except Exception as e:
                self.logger.error(f"Failed to move {new_pkg.name}: {e}")
        
        self.logger.info(f"✅ Moved {len(moved_packages)} new packages to staging")
        return moved_packages
    
    def update_database_additive(self, force_repair: bool = False) -> bool:
        """
        Update repository database additively with GPG signing
        
        Args:
            force_repair: If True, force database re-signing even if no new packages
        
        Returns:
            True if successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("ADDITIVE DATABASE UPDATE WITH GPG SIGNING")
        self.logger.info("=" * 60)
        
        try:
            # Step 1: Create staging directory
            self.create_staging_dir()
            
            # Step 2: Download existing database files
            if not self.download_existing_database():
                self.logger.error("❌ Failed to download existing database")
                return False
            
            # Step 3: Copy new packages to staging
            new_packages = self.copy_new_packages_to_staging()
            
            # Step 4: Check if we have anything to update
            existing_db = list(self._staging_dir.glob(f"{self.repo_name}.db.tar.gz"))
            has_existing_db = len(existing_db) > 0
            
            if not new_packages and not (force_repair and has_existing_db):
                self.logger.info("ℹ️ No new packages and not forcing repair - skipping database update")
                return True
            
            # Step 5: Update database locally with GPG signing
            old_cwd = os.getcwd()
            os.chdir(self._staging_dir)
            
            try:
                db_file = f"{self.repo_name}.db.tar.gz"
                
                # Clean any partial database files
                for f in [f"{self.repo_name}.db", f"{self.repo_name}.files"]:
                    if os.path.exists(f):
                        os.remove(f)
                
                # Build repo-add command with appropriate flags
                if self.gpg_enabled:
                    self.logger.info("🔏 Running repo-add with GPG signing...")
                    
                    # Set environment for non-interactive GPG signing
                    env = os.environ.copy()
                    env['GNUPGHOME'] = '/etc/pacman.d/gnupg'
                    
                    cmd = f"repo-add --sign --key {self.gpg_key_id} --remove {db_file} *.pkg.tar.zst"
                    
                    result = subprocess.run(
                        cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        env=env,
                        check=False
                    )
                else:
                    self.logger.info("🔧 Running repo-add without signing...")
                    cmd = f"repo-add --remove {db_file} *.pkg.tar.zst"
                    
                    result = subprocess.run(
                        cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                
                if result.returncode == 0:
                    self.logger.info("✅ Database updated successfully")
                    
                    # Verify the database was created
                    if not os.path.exists(db_file):
                        self.logger.error("❌ Database file not created")
                        return False
                    
                    # Verify database entries
                    self._verify_database_entries(db_file)
                    
                    # Generate .files database if needed
                    if not os.path.exists(f"{self.repo_name}.files.tar.gz"):
                        self.logger.info("Generating .files database...")
                        files_cmd = f"repo-add --files {db_file}"
                        subprocess.run(files_cmd, shell=True, check=False)
                    
                    return True
                else:
                    self.logger.error(f"❌ repo-add failed with exit code {result.returncode}:")
                    if result.stdout:
                        self.logger.error(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        self.logger.error(f"STDERR: {result.stderr[:500]}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"❌ Database update error: {e}")
                import traceback
                traceback.print_exc()
                return False
            finally:
                os.chdir(old_cwd)
                
        except Exception as e:
            self.logger.error(f"❌ Additive update failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _verify_database_entries(self, db_file: str) -> None:
        """Verify database entries after update"""
        try:
            list_cmd = ["tar", "-tzf", db_file]
            result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                db_entries = [line for line in result.stdout.split('\n') if line.endswith('/desc')]
                self.logger.info(f"✅ Database contains {len(db_entries)} package entries")
                if len(db_entries) == 0:
                    self.logger.warning("⚠️ Database is empty (no packages)")
                else:
                    self.logger.debug(f"Sample entries: {db_entries[:3]}")
            else:
                self.logger.warning(f"Could not list database contents: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Could not verify database: {e}")
    
    def upload_updated_files(self) -> bool:
        """
        Upload updated database and new packages to VPS
        
        Returns:
            True if successful
        """
        if not self._staging_dir or not self._staging_dir.exists():
            self.logger.error("❌ Staging directory not found")
            return False
        
        self.logger.info("📤 Uploading updated files to VPS...")
        
        # Collect all files to upload
        files_to_upload = []
        
        # 1. Database files and signatures
        repo_patterns = [
            f"{self.repo_name}.db*",
            f"{self.repo_name}.files*",
        ]
        
        for pattern in repo_patterns:
            for file_path in self._staging_dir.glob(pattern):
                if file_path.stat().st_size > 0:  # Skip empty files
                    files_to_upload.append(file_path)
        
        # 2. New package files and their signatures
        for pkg_file in self._staging_dir.glob("*.pkg.tar.zst"):
            if pkg_file.stat().st_size > 0:
                files_to_upload.append(pkg_file)
                
                # Include signature if it exists
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if sig_file.exists() and sig_file.stat().st_size > 0:
                    files_to_upload.append(sig_file)
        
        if not files_to_upload:
            self.logger.warning("⚠️ No files to upload")
            return True
        
        self.logger.info(f"📦 Total files to upload: {len(files_to_upload)}")
        
        # Log file details
        for f in files_to_upload:
            size_mb = f.stat().st_size / (1024 * 1024)
            file_type = "PACKAGE" if ".pkg.tar.zst" in f.name else "DATABASE"
            if f.name.endswith('.sig'):
                file_type = "SIGNATURE"
            self.logger.debug(f"  - {f.name} ({size_mb:.1f}MB) [{file_type}]")
        
        # Upload using rsync
        files_list = [str(f) for f in files_to_upload]
        upload_success = self.rsync_client.upload(files_list, self._staging_dir)
        
        if upload_success:
            self.logger.info("✅ All files uploaded successfully")
            
            # Verify upload by checking file counts
            self._verify_remote_upload(files_to_upload)
            return True
        else:
            self.logger.error("❌ File upload failed")
            return False
    
    def _verify_remote_upload(self, expected_files: List[Path]):
        """Verify that files were uploaded successfully"""
        self.logger.info("🔍 Verifying remote upload...")
        
        for local_file in expected_files:
            filename = local_file.name
            remote_path = f"{self.remote_dir}/{filename}"
            
            if self.ssh_client.file_exists(remote_path):
                self.logger.debug(f"✅ Verified: {filename}")
            else:
                self.logger.warning(f"⚠️ File not found on remote: {filename}")
    
    def generate_database(self) -> bool:
        """
        Legacy method for backward compatibility
        Uses the new additive update approach
        
        Returns:
            True if successful
        """
        return self.update_database_additive()
    
    def check_database_files(self) -> Tuple[List[str], List[str]]:
        """
        Check if repository database files exist on server
        
        Returns:
            Tuple of (existing_files, missing_files)
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("Checking existing database files on server")
        self.logger.info("=" * 60)
        
        db_files = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz"
        ]
        
        existing_files = []
        missing_files = []
        
        for db_file in db_files:
            if self.ssh_client.file_exists(f"{self.remote_dir}/{db_file}"):
                existing_files.append(db_file)
                self.logger.info(f"✅ Database file exists: {db_file}")
            else:
                missing_files.append(db_file)
                self.logger.info(f"ℹ️ Database file missing: {db_file}")
        
        if existing_files:
            self.logger.info(f"Found {len(existing_files)} database files on server")
        else:
            self.logger.info("No database files found on server")
        
        return existing_files, missing_files
    
    def get_database_files(self) -> List[Path]:
        """Get list of generated database files"""
        if not self._staging_dir:
            return []
        
        db_files = []
        patterns = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz",
            f"{self.repo_name}.db.sig",
            f"{self.repo_name}.db.tar.gz.sig",
            f"{self.repo_name}.files.sig",
            f"{self.repo_name}.files.tar.gz.sig",
        ]
        
        for pattern in patterns:
            for file_path in self._staging_dir.glob(pattern):
                if file_path.exists():
                    db_files.append(file_path)
        
        return db_files
    
    def cleanup_old_databases(self) -> None:
        """Clean up old database files from output directory"""
        patterns = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz",
        ]
        
        for pattern in patterns:
            for file_path in self.output_dir.glob(pattern):
                try:
                    if file_path.exists():
                        file_path.unlink()
                        self.logger.debug(f"Removed old database file: {file_path.name}")
                except Exception as e:
                    self.logger.warning(f"Could not remove {file_path}: {e}")