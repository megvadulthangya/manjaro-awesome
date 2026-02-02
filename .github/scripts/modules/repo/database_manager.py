"""
Database Manager Module - Handles repository database operations
"""

import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages repository database operations"""
    
    def __init__(self, config: dict):
        """
        Initialize DatabaseManager with configuration
        
        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory
                - remote_dir: Remote directory on VPS
                - vps_user: VPS username
                - vps_host: VPS hostname
        """
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
    
    def generate_full_database(self, repo_name: str, output_dir: Path, cleanup_manager) -> bool:
        """
        Generate repository database from ALL locally available packages
        
        🚨 KRITIKUS: Run final validation BEFORE repo-add
        """
        print("\n" + "=" * 60)
        print("PHASE: Repository Database Generation")
        print("=" * 60)
        
        # 🚨 KRITIKUS: Final validation to remove zombie packages
        cleanup_manager.revalidate_output_dir_before_database()
        
        # Get all package files from local output directory
        all_packages = self._get_all_local_packages()
        
        if not all_packages:
            logger.info("No packages available for database generation")
            return False
        
        # Log the packages being included (first 10)
        package_names = [os.path.basename(pkg) for pkg in all_packages]
        logger.info(f"Database input packages ({len(package_names)}): {package_names[:10]}{'...' if len(package_names) > 10 else ''}")
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{repo_name}.db", f"{repo_name}.db.tar.gz", 
                      f"{repo_name}.files", f"{repo_name}.files.tar.gz"]:
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
                logger.error(f"❌ CRITICAL: {len(missing_packages)} packages missing locally:")
                for pkg in missing_packages[:5]:
                    logger.error(f"   - {pkg}")
                if len(missing_packages) > 5:
                    logger.error(f"   ... and {len(missing_packages) - 5} more")
                return False
            
            if not valid_packages:
                logger.error("No valid package files found for database generation")
                return False
            
            logger.info(f"✅ All {len(valid_packages)} package files verified locally")
            
            # Generate database with repo-add using explicit package list (NO shell=True, NO wildcards)
            repo_add_cmd = ["repo-add", db_file] + valid_packages
            
            logger.info(f"Running repo-add with explicit package list...")
            logger.info(f"Command: {' '.join(['repo-add', db_file, '...'])}")
            logger.info(f"Current directory: {os.getcwd()}")
            
            result = subprocess.run(
                repo_add_cmd,
                shell=False,  # Explicitly use shell=False for safety
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Database created successfully")
                
                # Verify the database was created
                db_path = Path(db_file)
                if db_path.exists():
                    size_mb = db_path.stat().st_size / (1024 * 1024)
                    logger.info(f"Database size: {size_mb:.2f} MB")
                    
                    # CRITICAL: Verify database entries BEFORE upload
                    logger.info("🔍 Verifying database entries before upload...")
                    list_cmd = ["tar", "-tzf", db_file]
                    list_result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
                    if list_result.returncode == 0:
                        db_entries = [line for line in list_result.stdout.split('\n') if line.endswith('/desc')]
                        logger.info(f"✅ Database contains {len(db_entries)} package entries")
                        if len(db_entries) == 0:
                            logger.error("❌❌❌ DATABASE IS EMPTY! This is the root cause of the issue.")
                            return False
                        else:
                            logger.info(f"Sample database entries: {db_entries[:5]}")
                    else:
                        logger.warning(f"Could not list database contents: {list_result.stderr}")
                
                return True
            else:
                logger.error(f"repo-add failed with exit code {result.returncode}:")
                if result.stdout:
                    logger.error(f"STDOUT: {result.stdout[:500]}")
                if result.stderr:
                    logger.error(f"STDERR: {result.stderr[:500]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def _get_all_local_packages(self) -> List[str]:
        """
        Get ALL real package files from local output directory (mirrored + newly built)
        EXCLUDES: .sig files, database artifacts
        """
        print("\n🔍 Getting complete package list from local directory...")
        
        # Get all files matching package patterns
        package_files = []
        
        # Include only real package files
        for ext in ['.pkg.tar.zst', '.pkg.tar.xz', '.pkg.tar.gz', '.pkg.tar.bz2', '.pkg.tar.lzo']:
            package_files.extend(self.output_dir.glob(f"*{ext}"))
        
        # Filter out signature files
        package_files = [f for f in package_files if not f.name.endswith('.sig')]
        
        # Filter out database artifacts (even if they somehow match patterns)
        package_files = [
            f for f in package_files 
            if not (f.name.startswith(f"{self.repo_name}.db") or f.name.startswith(f"{self.repo_name}.files"))
        ]
        
        if not package_files:
            logger.info("ℹ️ No real package files found locally (excluding .sig files and database artifacts)")
            return []
        
        local_filenames = [f.name for f in package_files]
        
        logger.info(f"📊 Local package count (excluding .sig files): {len(local_filenames)}")
        logger.info(f"Sample real packages (no .sig): {local_filenames[:10]}")
        
        return local_filenames
    
    def check_database_files(self) -> Tuple[List[str], List[str]]:
        """Check if repository database files exist on server"""
        print("\n" + "=" * 60)
        print("STEP 2: Checking existing database files on server")
        print("=" * 60)
        
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
                f"{self.vps_user}@{self.vps_host}",
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
                    logger.info(f"✅ Database file exists: {db_file}")
                else:
                    missing_files.append(db_file)
                    logger.info(f"ℹ️ Database file missing: {db_file}")
                    
            except Exception as e:
                logger.warning(f"Could not check {db_file}: {e}")
                missing_files.append(db_file)
        
        if existing_files:
            logger.info(f"Found {len(existing_files)} database files on server")
        else:
            logger.info("No database files found on server")
        
        return existing_files, missing_files
    
    def fetch_existing_database(self, existing_files: List[str]):
        """Fetch existing database files from server"""
        if not existing_files:
            return
        
        print("\n📥 Fetching existing database files from server...")
        
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
                f"{self.vps_user}@{self.vps_host}:{remote_path}",
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
                    logger.info(f"✅ Fetched: {db_file} ({size_mb:.2f} MB)")
                else:
                    logger.warning(f"⚠️ Could not fetch {db_file}")
            except Exception as e:
                logger.warning(f"Could not fetch {db_file}: {e}")
