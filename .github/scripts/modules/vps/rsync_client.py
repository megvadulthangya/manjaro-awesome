"""
Rsync Client Module - Handles file transfers using Rsync
"""

import os
import subprocess
import shutil
import time
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class RsyncClient:
    """Handles Rsync file transfers and remote operations"""
    
    def __init__(self, config: dict):
        """
        Initialize RsyncClient with configuration
        
        Args:
            config: Dictionary containing:
                - vps_user: VPS username
                - vps_host: VPS hostname
                - remote_dir: Remote directory on VPS
                - ssh_options: SSH options list
                - repo_name: Repository name
        """
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        self.remote_dir = config['remote_dir']
        self.ssh_options = config.get('ssh_options', [])
        self.repo_name = config.get('repo_name', '')
    
    def mirror_remote_packages(self, mirror_temp_dir: Path, output_dir: Path) -> bool:
        """
        Download ALL remote package files to local directory
        
        Returns:
            True if successful, False otherwise
        """
        print("\n" + "=" * 60)
        print("MANDATORY STEP: Mirroring remote packages locally")
        print("=" * 60)
        
        # Ensure remote directory exists first
        # Note: This requires SSHClient, will be called from PackageBuilder
        
        # Create a temporary local repository directory
        if mirror_temp_dir.exists():
            shutil.rmtree(mirror_temp_dir, ignore_errors=True)
        mirror_temp_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created local mirror directory: {mirror_temp_dir}")
        
        # Use rsync to download ALL package files from server
        print("📥 Downloading ALL remote package files to local mirror...")
        
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60" \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/*.pkg.tar.*' \
          '{mirror_temp_dir}/' 2>/dev/null || true
        """
        
        logger.info(f"RUNNING RSYNC MIRROR COMMAND:")
        logger.info(rsync_cmd.strip())
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines()[-20:]:
                    if line.strip():
                        logger.info(f"RSYNC MIRROR: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip() and "No such file or directory" not in line:
                        logger.error(f"RSYNC MIRROR ERR: {line}")
            
            # List downloaded files
            downloaded_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
            file_count = len(downloaded_files)
            
            if file_count > 0:
                logger.info(f"✅ Successfully mirrored {file_count} package files ({duration} seconds)")
                logger.info(f"Sample mirrored files: {[f.name for f in downloaded_files[:5]]}")
                
                # Verify file integrity and copy to output directory
                valid_files = []
                for pkg_file in downloaded_files:
                    if pkg_file.stat().st_size > 0:
                        valid_files.append(pkg_file)
                    else:
                        logger.warning(f"⚠️ Empty file: {pkg_file.name}")
                
                logger.info(f"Valid mirrored packages: {len(valid_files)}/{file_count}")
                
                # Copy mirrored packages to output directory
                print(f"📋 Copying {len(valid_files)} mirrored packages to output directory...")
                copied_count = 0
                for pkg_file in valid_files:
                    dest = output_dir / pkg_file.name
                    if not dest.exists():  # Don't overwrite newly built packages
                        shutil.copy2(pkg_file, dest)
                        copied_count += 1
                
                logger.info(f"Copied {copied_count} mirrored packages to output directory")
                
                # Clean up mirror directory
                shutil.rmtree(mirror_temp_dir, ignore_errors=True)
                
                return True
            else:
                logger.info("ℹ️ No package files were mirrored (repository is empty or permission issue)")
                shutil.rmtree(mirror_temp_dir, ignore_errors=True)
                return True
                
        except Exception as e:
            logger.error(f"RSYNC mirror execution error: {e}")
            if mirror_temp_dir.exists():
                shutil.rmtree(mirror_temp_dir, ignore_errors=True)
            return False
    
    def upload_files(self, files_to_upload: List[str], output_dir: Path) -> bool:
        """
        Upload files to server using RSYNC WITHOUT --delete flag
        
        Returns:
            True if successful, False otherwise
        """
        # Ensure remote directory exists first
        # Note: This requires SSHClient, will be called from PackageBuilder
        
        if not files_to_upload:
            logger.warning("No files to upload")
            return False
        
        # Log files to upload (safe - only filenames, not paths)
        logger.info(f"Files to upload ({len(files_to_upload)}):")
        for f in files_to_upload:
            try:
                size_mb = os.path.getsize(f) / (1024 * 1024)
                filename = os.path.basename(f)
                file_type = "PACKAGE"
                if self.repo_name in filename:
                    file_type = "DATABASE" if not f.endswith('.sig') else "SIGNATURE"
                logger.info(f"  - {filename} ({size_mb:.1f}MB) [{file_type}]")
            except Exception:
                logger.info(f"  - {os.path.basename(f)} [UNKNOWN SIZE]")
        
        # Build RSYNC command WITHOUT --delete
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        logger.info(f"RUNNING RSYNC COMMAND WITHOUT --delete:")
        logger.info(rsync_cmd.strip())
        
        # FIRST ATTEMPT
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE (attempt 1): {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"RSYNC: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip() and "No such file or directory" not in line:
                        logger.error(f"RSYNC ERR: {line}")
            
            if result.returncode == 0:
                logger.info(f"✅ RSYNC upload successful! ({duration} seconds)")
                return True
            else:
                logger.warning(f"⚠️ First RSYNC attempt failed (code: {result.returncode})")
                
        except Exception as e:
            logger.error(f"RSYNC execution error: {e}")
        
        # SECOND ATTEMPT (with different SSH options)
        logger.info("⚠️ Retrying with different SSH options...")
        time.sleep(5)
        
        rsync_cmd_retry = f"""
        rsync -avz \
          --progress \
          --stats \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=30 -o ServerAliveCountMax=3" \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        logger.info(f"RUNNING RSYNC RETRY COMMAND WITHOUT --delete:")
        logger.info(rsync_cmd_retry.strip())
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd_retry,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE (attempt 2): {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"RSYNC RETRY: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip() and "No such file or directory" not in line:
                        logger.error(f"RSYNC RETRY ERR: {line}")
            
            if result.returncode == 0:
                logger.info(f"✅ RSYNC upload successful on retry! ({duration} seconds)")
                return True
            else:
                logger.error(f"❌ RSYNC upload failed on both attempts!")
                return False
                
        except Exception as e:
            logger.error(f"RSYNC retry execution error: {e}")
            return False