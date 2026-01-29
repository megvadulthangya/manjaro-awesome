"""
Recovery Manager for Auto-Recovery and Database Reconciliation
Handles missing package discovery and downloading from VPS
"""

import subprocess
import logging
from pathlib import Path
from typing import List, Set, Optional, Dict, Any

from modules.vps.ssh_client import SSHClient

class RecoveryManager:
    """Manages auto-recovery of missing packages from VPS"""

    def __init__(self, config: Dict[str, Any], ssh_client: SSHClient, logger: Optional[logging.Logger] = None):
        """
        Initialize RecoveryManager

        Args:
            config: Configuration dictionary
            ssh_client: SSHClient instance
            logger: Optional logger instance
        """
        self.config = config
        self.ssh_client = ssh_client
        self.logger = logger or logging.getLogger(__name__)
        
        self.repo_name = config.get('repo_name', '')
        self.vps_user = config.get('vps_user', '')
        self.vps_host = config.get('vps_host', '')
        self._recovered_packages: List[str] = []
        self._missing_from_db: List[str] = []

    def get_recovered_packages(self) -> List[str]:
        """Get list of successfully recovered packages"""
        return self._recovered_packages

    def get_missing_from_db(self) -> List[str]:
        """Get list of packages identified as missing from DB"""
        return self._missing_from_db

    def reset(self):
        """Reset internal state"""
        self._recovered_packages = []
        self._missing_from_db = []

    def discover_missing(self, staging_dir: Path) -> List[str]:
        """
        Discover packages present on remote but missing from local database
        
        Args:
            staging_dir: Local staging directory containing the database
            
        Returns:
            List of missing package filenames
        """
        self.logger.info("🔍 Discovering packages missing from database...")
        
        # Get packages in database
        db_packages = self._get_db_package_list(staging_dir)
        
        # Get remote inventory (physical files on VPS)
        remote_inventory = self.ssh_client.get_cached_inventory(force_refresh=True)
        
        if not remote_inventory:
            self.logger.info("ℹ️ No remote packages found")
            return []
        
        # Filter for package files only
        remote_packages = set()
        for filename in remote_inventory.keys():
            if filename.endswith('.pkg.tar.zst'):
                remote_packages.add(filename)
        
        self.logger.info(f"📊 Remote inventory: {len(remote_packages)} package files")
        
        # Find packages on VPS that are NOT in database
        missing_packages = []
        for pkg_file in remote_packages:
            if pkg_file not in db_packages:
                missing_packages.append(pkg_file)
                self.logger.info(f"⚠️ Missing from DB: {pkg_file}")
        
        self.logger.info(f"📊 Found {len(missing_packages)} packages missing from database")
        
        # Store for reporting
        self._missing_from_db = missing_packages
        
        return missing_packages

    def download_missing(self, missing_packages: List[str], staging_dir: Path) -> int:
        """
        Download missing packages from VPS to staging
        
        Args:
            missing_packages: List of package filenames to download
            staging_dir: Local staging directory to save files
            
        Returns:
            Number of successfully downloaded packages
        """
        if not missing_packages:
            return 0
        
        self.logger.info(f"📥 Downloading {len(missing_packages)} missing packages from VPS...")
        
        downloaded_count = 0
        
        for pkg_filename in missing_packages:
            try:
                # Find full remote path
                remote_inventory = self.ssh_client.get_cached_inventory()
                remote_path = remote_inventory.get(pkg_filename)
                
                if not remote_path:
                    self.logger.warning(f"Could not find remote path for {pkg_filename}")
                    continue
                
                # Download using scp
                scp_cmd = [
                    "scp",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=30",
                    f"{self.vps_user}@{self.vps_host}:{remote_path}",
                    str(staging_dir / pkg_filename)
                ]
                
                result = subprocess.run(
                    scp_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0:
                    # Check if file was downloaded
                    local_path = staging_dir / pkg_filename
                    if local_path.exists() and local_path.stat().st_size > 0:
                        self.logger.info(f"✅ Downloaded: {pkg_filename}")
                        downloaded_count += 1
                        
                        # Add to recovered packages list
                        self._recovered_packages.append(pkg_filename)
                    else:
                        self.logger.warning(f"Downloaded file is empty: {pkg_filename}")
                else:
                    self.logger.warning(f"Failed to download {pkg_filename}: {result.stderr}")
                    
            except Exception as e:
                self.logger.error(f"Error downloading {pkg_filename}: {e}")
        
        self.logger.info(f"✅ Downloaded {downloaded_count} missing packages")
        return downloaded_count

    def _get_db_package_list(self, staging_dir: Path) -> Set[str]:
        """
        Extract package list from existing database file
        
        Args:
            staging_dir: Directory containing database file
            
        Returns:
            Set of package filenames
        """
        db_file = staging_dir / f"{self.repo_name}.db.tar.gz"
        
        if not db_file.exists():
            self.logger.info("ℹ️ No database file found in staging")
            return set()
        
        self.logger.info("📋 Extracting package list from existing database...")
        
        try:
            # Use tar to list contents and find package entries
            cmd = ["tar", "-tzf", str(db_file)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                self.logger.warning(f"Failed to list database contents: {result.stderr}")
                return set()
            
            # Parse tar output to find package entries
            package_files = set()
            for line in result.stdout.splitlines():
                if line.strip() and '/' in line:
                    # Extract filename from path like: awesome-git-4.0.r123.gabc123def-1-x86_64/pkgname/desc
                    parts = line.split('/')
                    if len(parts) >= 2 and parts[1].endswith('/desc'):
                        # The directory name is the package filename
                        package_files.add(parts[0])
            
            self.logger.info(f"📊 Database contains {len(package_files)} package entries")
            
            return package_files
            
        except Exception as e:
            self.logger.error(f"❌ Failed to extract package list from DB: {e}")
            return set()