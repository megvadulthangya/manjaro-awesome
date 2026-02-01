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
    
    def mirror_remote_packages(self, mirror_temp_dir: Path, output_dir: Path, vps_file_list: List[str]) -> bool:
        """
        Download ALL remote package files to local directory with proper sync logic
        
        CRITICAL FIX: Mirror directory must reflect VPS state exactly
        - Files deleted on VPS must be deleted from mirror
        - New files on VPS must be downloaded to mirror
        - Cache is preserved but VPS state overrides mirror content
        
        Args:
            mirror_temp_dir: Temporary directory for mirror
            output_dir: Output directory for built packages
            vps_file_list: List of package filenames currently on VPS (obtained via SSH)
            
        Returns:
            True if successful, False otherwise
        """
        print("\n" + "=" * 60)
        print("CRITICAL PHASE: Mirror Synchronization with VPS State")
        print("=" * 60)
        
        # Convert VPS file list to set for fast lookup
        vps_files_set = set(vps_file_list)
        logger.info(f"VPS state: {len(vps_files_set)} package files")
        
        # Create a temporary local repository directory
        if mirror_temp_dir.exists():
            # First, check what's in the mirror directory (from cache)
            cached_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
            cached_file_names = set(f.name for f in cached_files)
            
            logger.info(f"Cache state: {len(cached_file_names)} package files in mirror directory")
            
            # Step 1: Delete files from mirror that are NOT on VPS
            files_to_delete = cached_file_names - vps_files_set
            if files_to_delete:
                logger.info(f"🗑️ Deleting {len(files_to_delete)} files from mirror (not on VPS):")
                for file_name in sorted(files_to_delete)[:10]:  # Show first 10
                    logger.info(f"  - {file_name}")
                
                for file_name in files_to_delete:
                    file_path = mirror_temp_dir / file_name
                    try:
                        if file_path.exists():
                            file_path.unlink()
                            logger.debug(f"Removed from mirror: {file_name}")
                    except Exception as e:
                        logger.warning(f"Could not remove {file_name}: {e}")
            
            # Step 2: Identify files on VPS that are NOT in mirror
            files_to_download = vps_files_set - cached_file_names
            if files_to_download:
                logger.info(f"📥 Need to download {len(files_to_download)} new files from VPS:")
                for file_name in sorted(files_to_download)[:10]:  # Show first 10
                    logger.info(f"  - {file_name}")
        else:
            # Mirror directory doesn't exist, create it
            mirror_temp_dir.mkdir(parents=True, exist_ok=True)
            files_to_download = vps_files_set
            if files_to_download:
                logger.info(f"📥 Mirror directory empty, downloading {len(files_to_download)} files from VPS")
        
        # If there are files to download, use rsync with specific file list
        if files_to_download:
            # Build rsync command with specific files
            download_list = []
            for file_name in files_to_download:
                remote_path = f"{self.remote_dir}/{file_name}"
                download_list.append(f"'{self.vps_user}@{self.vps_host}:{remote_path}'")
            
            if download_list:
                files_str = ' '.join(download_list)
                rsync_cmd = f"""
                rsync -avz \
                  --progress \
                  --stats \
                  -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60" \
                  {files_str} \
                  '{mirror_temp_dir}/' 2>/dev/null || true
                """
                
                logger.info(f"RUNNING RSYNC DOWNLOAD COMMAND for {len(download_list)} files:")
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
                        for line in result.stdout.splitlines()[-10:]:
                            if line.strip():
                                logger.info(f"RSYNC: {line}")
                    
                    # Verify downloaded files
                    downloaded_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
                    actual_downloaded = len(downloaded_files) - (len(cached_file_names) if 'cached_file_names' in locals() else 0)
                    
                    logger.info(f"✅ Downloaded {actual_downloaded} new package files ({duration} seconds)")
                    
                except Exception as e:
                    logger.error(f"RSYNC download execution error: {e}")
                    return False
        
        # Step 3: Sync output directory with mirror (but preserve newly built packages)
        # Only copy from mirror to output_dir if file doesn't exist in output_dir
        # Never delete from output_dir as it may contain newly built packages
        
        mirror_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
        output_files = set(f.name for f in output_dir.glob("*.pkg.tar.*"))
        
        copied_count = 0
        for mirror_file in mirror_files:
            dest = output_dir / mirror_file.name
            if not dest.exists():
                try:
                    shutil.copy2(mirror_file, dest)
                    copied_count += 1
                    logger.debug(f"Copied to output_dir: {mirror_file.name}")
                except Exception as e:
                    logger.warning(f"Could not copy {mirror_file.name}: {e}")
        
        if copied_count > 0:
            logger.info(f"📋 Copied {copied_count} mirrored packages to output directory")
        
        # Verify final state
        final_mirror_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
        logger.info(f"📊 Mirror synchronization complete:")
        logger.info(f"  - Mirror now has {len(final_mirror_files)} files")
        logger.info(f"  - VPS has {len(vps_files_set)} files")
        logger.info(f"  - Output directory has {len(output_files) + copied_count} files")
        
        # CRITICAL VALIDATION: Ensure mirror matches VPS state
        mirror_file_names = set(f.name for f in final_mirror_files)
        if mirror_file_names != vps_files_set:
            missing_in_mirror = vps_files_set - mirror_file_names
            extra_in_mirror = mirror_file_names - vps_files_set
            
            if missing_in_mirror:
                logger.error(f"❌ CRITICAL: Mirror missing {len(missing_in_mirror)} files from VPS")
                for file_name in sorted(missing_in_mirror)[:5]:
                    logger.error(f"  - {file_name}")
            
            if extra_in_mirror:
                logger.error(f"❌ CRITICAL: Mirror has {len(extra_in_mirror)} extra files not on VPS")
                for file_name in sorted(extra_in_mirror)[:5]:
                    logger.error(f"  - {file_name}")
            
            return False
        
        logger.info("✅ Mirror perfectly synchronized with VPS state")
        
        # Clean up mirror directory after use (it will be recreated from cache next time)
        try:
            shutil.rmtree(mirror_temp_dir, ignore_errors=True)
            logger.info("🧹 Cleaned up temporary mirror directory")
        except Exception as e:
            logger.warning(f"Could not clean up mirror directory: {e}")
        
        return True
    
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
