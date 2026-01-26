"""
Repository database management
Handles database generation, verification, and VPS operations
Extracted from RepoManager with enhanced functionality
"""

import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient


class DatabaseManager:
    """Manages repository database operations and VPS synchronization"""
    
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
    
    def generate_database(self) -> bool:
        """
        Generate repository database from ALL locally available packages
        
        Returns:
            True if database generation successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("PHASE: Repository Database Generation")
        self.logger.info("=" * 60)
        
        # Get all package files from local output directory
        all_packages = self._get_all_local_packages()
        
        if not all_packages:
            self.logger.info("No packages available for database generation")
            return False
        
        self.logger.info(f"Generating database with {len(all_packages)} packages...")
        self.logger.info(f"Packages: {', '.join(all_packages[:10])}{'...' if len(all_packages) > 10 else ''}")
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz", 
                      f"{self.repo_name}.files", f"{self.repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            # Verify each package file exists locally before database generation
            missing_packages = []
            valid_packages = []
            
            for pkg_filename in all_packages:
                if Path(pkg_filename).exists():
                    valid_packages.append(pkg_filename)
                else:
                    missing_packages.append(pkg_filename)
            
            if missing_packages:
                self.logger.error(f"❌ CRITICAL: {len(missing_packages)} packages missing locally:")
                for pkg in missing_packages[:5]:
                    self.logger.error(f"   - {pkg}")
                if len(missing_packages) > 5:
                    self.logger.error(f"   ... and {len(missing_packages) - 5} more")
                return False
            
            if not valid_packages:
                self.logger.error("No valid package files found for database generation")
                return False
            
            self.logger.info(f"✅ All {len(valid_packages)} package files verified locally")
            
            # Generate database with repo-add using shell=True for wildcard expansion
            cmd = f"repo-add {db_file} *.pkg.tar.zst"
            
            self.logger.info(f"Running repo-add with shell=True to include ALL packages...")
            self.logger.info(f"Command: {cmd}")
            self.logger.info(f"Current directory: {os.getcwd()}")
            
            result = subprocess.run(
                cmd,
                shell=True,  # CRITICAL: Use shell=True for wildcard expansion
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                self.logger.info("✅ Database created successfully")
                
                # Verify the database was created
                db_path = Path(db_file)
                if db_path.exists():
                    size_mb = db_path.stat().st_size / (1024 * 1024)
                    self.logger.info(f"Database size: {size_mb:.2f} MB")
                    
                    # CRITICAL: Verify database entries BEFORE upload
                    self.logger.info("🔍 Verifying database entries before upload...")
                    list_cmd = ["tar", "-tzf", db_file]
                    list_result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
                    if list_result.returncode == 0:
                        db_entries = [line for line in list_result.stdout.split('\n') if line.endswith('/desc')]
                        self.logger.info(f"✅ Database contains {len(db_entries)} package entries")
                        if len(db_entries) == 0:
                            self.logger.error("❌❌❌ DATABASE IS EMPTY! This is the root cause of the issue.")
                            return False
                        else:
                            self.logger.info(f"Sample database entries: {db_entries[:5]}")
                    else:
                        self.logger.warning(f"Could not list database contents: {list_result.stderr}")
                
                return True
            else:
                self.logger.error(f"repo-add failed with exit code {result.returncode}:")
                if result.stdout:
                    self.logger.error(f"STDOUT: {result.stdout[:500]}")
                if result.stderr:
                    self.logger.error(f"STDERR: {result.stderr[:500]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def check_database_files(self) -> Tuple[List[str], List[str]]:
        """
        Check if repository database files exist on server
        
        Returns:
            Tuple of (existing_files, missing_files)
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("STEP 2: Checking existing database files on server")
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
            remote_cmd = f"test -f {self.remote_dir}/{db_file} && echo 'EXISTS' || echo 'MISSING'"
            
            ssh_cmd = [
                "ssh",
                f"{self.config.get('vps_user')}@{self.config.get('vps_host')}",
                remote_cmd
            ]
            
            try:
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0 and "EXISTS" in result.stdout:
                    existing_files.append(db_file)
                    self.logger.info(f"✅ Database file exists: {db_file}")
                else:
                    missing_files.append(db_file)
                    self.logger.info(f"ℹ️ Database file missing: {db_file}")
                    
            except Exception as e:
                self.logger.warning(f"Could not check {db_file}: {e}")
                missing_files.append(db_file)
        
        if existing_files:
            self.logger.info(f"Found {len(existing_files)} database files on server")
        else:
            self.logger.info("No database files found on server")
        
        return existing_files, missing_files
    
    def fetch_existing_database(self, existing_files: List[str]) -> bool:
        """
        Fetch existing database files from server
        
        Args:
            existing_files: List of database files to fetch
        
        Returns:
            True if all files fetched successfully
        """
        if not existing_files:
            return True
        
        self.logger.info("\n📥 Fetching existing database files from server...")
        
        success = True
        for db_file in existing_files:
            remote_path = f"{self.remote_dir}/{db_file}"
            local_path = self.output_dir / db_file
            
            # Remove local copy if exists
            if local_path.exists():
                local_path.unlink()
            
            ssh_cmd = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=30",
                f"{self.config.get('vps_user')}@{self.config.get('vps_host')}:{remote_path}",
                str(local_path)
            ]
            
            try:
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0 and local_path.exists():
                    size_mb = local_path.stat().st_size / (1024 * 1024)
                    self.logger.info(f"✅ Fetched: {db_file} ({size_mb:.2f} MB)")
                else:
                    self.logger.warning(f"⚠️ Could not fetch {db_file}")
                    success = False
            except Exception as e:
                self.logger.warning(f"Could not fetch {db_file}: {e}")
                success = False
        
        return success
    
    def upload_database(self) -> bool:
        """
        Upload database files to server
        
        Returns:
            True if upload successful
        """
        # Get all database files and signatures
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
        
        if not db_files:
            self.logger.warning("No database files to upload")
            return False
        
        files_to_upload = [str(f) for f in db_files]
        return self.rsync_client.upload(files_to_upload, self.output_dir)
    
    def _get_all_local_packages(self) -> List[str]:
        """Get ALL package files from local output directory (mirrored + newly built)"""
        self.logger.info("\n🔍 Getting complete package list from local directory...")
        
        local_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not local_files:
            self.logger.info("ℹ️ No package files found locally")
            return []
        
        local_filenames = [f.name for f in local_files]
        
        self.logger.info(f"📊 Local package count: {len(local_filenames)}")
        self.logger.info(f"Sample packages: {local_filenames[:10]}")
        
        return local_filenames
    
    def get_database_files(self) -> List[Path]:
        """Get list of generated database files"""
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
            for file_path in self.output_dir.glob(pattern):
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