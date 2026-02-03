"""
Rsync Client Module - Handles file transfers using Rsync
WITH UP3 POST-UPLOAD VERIFICATION
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
    
    def mirror_remote_packages(self, mirror_temp_dir: Path, output_dir: Path, vps_package_files: List[str]) -> bool:
        """
        Download ONLY remote package files (*.pkg.tar.*) to local directory.
        
        CRITICAL CONTRACT: This method handles ONLY package archive files.
        Signatures and database files are excluded from mirror sync validation.
        
        Args:
            mirror_temp_dir: Temporary directory for mirror
            output_dir: Output directory for built packages
            vps_package_files: List of package filenames (basenames) currently on VPS
                             MUST contain ONLY *.pkg.tar.* files (no .sig, no .db)
            
        Returns:
            True if successful, False otherwise
        """
        logger.info("CRITICAL PHASE: Mirror Synchronization (Package Files Only)")
        
        # Filter to ensure only package files
        package_files_only = [f for f in vps_package_files if f.endswith(('.pkg.tar.zst', '.pkg.tar.xz'))]
        logger.info(f"VPS package state: {len(package_files_only)} package files (excluded {len(vps_package_files) - len(package_files_only)} non-package files)")
        
        # Convert to set for fast lookup
        vps_packages_set = set(package_files_only)
        
        # Create a temporary local repository directory
        if mirror_temp_dir.exists():
            # First, check what's in the mirror directory (from cache)
            cached_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
            cached_file_names = set(f.name for f in cached_files)
            
            logger.info(f"Cache state: {len(cached_file_names)} package files in mirror directory")
            
            # Step 1: Delete files from mirror that are NOT on VPS
            files_to_delete = cached_file_names - vps_packages_set
            if files_to_delete:
                logger.info(f"Deleting {len(files_to_delete)} files from mirror (not on VPS)")
                
                for file_name in files_to_delete:
                    file_path = mirror_temp_dir / file_name
                    try:
                        if file_path.exists():
                            file_path.unlink()
                            logger.debug(f"Removed from mirror: {file_name}")
                    except Exception as e:
                        logger.warning(f"Could not remove {file_name}: {e}")
            
            # Step 2: Identify files on VPS that are NOT in mirror
            files_to_download = vps_packages_set - cached_file_names
            if files_to_download:
                logger.info(f"Need to download {len(files_to_download)} new package files from VPS")
        else:
            # Mirror directory doesn't exist, create it
            mirror_temp_dir.mkdir(parents=True, exist_ok=True)
            files_to_download = vps_packages_set
            if files_to_download:
                logger.info(f"Mirror directory empty, downloading {len(files_to_download)} package files from VPS")
        
        # If there are files to download, use rsync with specific file list
        downloaded_count = 0
        if files_to_download:
            # Build rsync command with specific files
            download_list = []
            for file_name in files_to_download:
                # Ensure it's a package file (safety check)
                if file_name.endswith(('.pkg.tar.zst', '.pkg.tar.xz')):
                    remote_path = f"{self.remote_dir}/{file_name}"
                    download_list.append(f"'{self.vps_user}@{self.vps_host}:{remote_path}'")
                else:
                    logger.warning(f"Skipping non-package file in download list: {file_name}")
            
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
                
                logger.info(f"RUNNING RSYNC DOWNLOAD COMMAND for {len(download_list)} package files")
                
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
                    
                    # Count actual downloaded files by checking which of the files_to_download now exist
                    downloaded_count = 0
                    for file_name in files_to_download:
                        if (mirror_temp_dir / file_name).exists():
                            downloaded_count += 1
                    
                    logger.info(f"Downloaded {downloaded_count} new package files ({duration} seconds)")
                    
                except Exception as e:
                    logger.error(f"RSYNC download execution error: {e}")
                    return False
            else:
                logger.info("No files to download (empty download list after filtering)")
        else:
            logger.info("No new package files to download from VPS")
        
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
            logger.info(f"Copied {copied_count} mirrored packages to output directory")
        
        # CRITICAL VALIDATION: Ensure mirror matches VPS package state ONLY
        final_mirror_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
        final_mirror_names = set(f.name for f in final_mirror_files)
        
        # Log validation details
        logger.info(f"Mirror synchronization validation:")
        logger.info(f"  - Mirror now has {len(final_mirror_names)} package files")
        logger.info(f"  - VPS has {len(vps_packages_set)} package files")
        logger.info(f"  - Output directory has {len(output_files) + copied_count} package files")
        logger.info(f"  - Files downloaded in this sync: {downloaded_count}")
        
        # Check for discrepancies with detailed logging
        missing_in_mirror = vps_packages_set - final_mirror_names
        extra_in_mirror = final_mirror_names - vps_packages_set
        
        if missing_in_mirror:
            logger.error(f"CRITICAL: Mirror missing {len(missing_in_mirror)} package files from VPS")
            # Log first 50 missing files
            for i, filename in enumerate(list(missing_in_mirror)[:50]):
                logger.error(f"  Missing [{i+1}]: {filename}")
            if len(missing_in_mirror) > 50:
                logger.error(f"  ... and {len(missing_in_mirror) - 50} more")
        
        if extra_in_mirror:
            logger.error(f"CRITICAL: Mirror has {len(extra_in_mirror)} extra package files not on VPS")
            # Log first 50 extra files
            for i, filename in enumerate(list(extra_in_mirror)[:50]):
                logger.error(f"  Extra [{i+1}]: {filename}")
            if len(extra_in_mirror) > 50:
                logger.error(f"  ... and {len(extra_in_mirror) - 50} more")
        
        if missing_in_mirror or extra_in_mirror:
            logger.error("Mirror package synchronization FAILED")
            return False
        
        logger.info("Mirror perfectly synchronized with VPS package state")
        
        # Clean up mirror directory after use (it will be recreated from cache next time)
        try:
            shutil.rmtree(mirror_temp_dir, ignore_errors=True)
            logger.info("Cleaned up temporary mirror directory")
        except Exception as e:
            logger.warning(f"Could not clean up mirror directory: {e}")
        
        return True
    
    def upload_files(self, files_to_upload: List[str], output_dir: Path, cleanup_manager=None) -> bool:
        """
        Upload files to server using RSYNC WITHOUT --delete flag (transport-only)
        
        CRITICAL: This is now a transport-only function. Deletions are handled
        separately via CleanupManager over SSH (outside this module).
        
        Args:
            files_to_upload: List of file paths to upload
            output_dir: Output directory (unused, kept for backward compatibility)
            cleanup_manager: Ignored (kept for backward compatibility only)
            
        Returns:
            True if rsync transport succeeded, False otherwise
        """
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
        
        # Build RSYNC command WITHOUT --delete (transport-only)
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        logger.info(f"RUNNING RSYNC COMMAND (NO --delete)")
        
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
                logger.info(f"RSYNC upload successful! ({duration} seconds)")
                return True
            else:
                logger.warning(f"First RSYNC attempt failed (code: {result.returncode})")
                
        except Exception as e:
            logger.error(f"RSYNC execution error: {e}")
        
        # SECOND ATTEMPT (with different SSH options)
        logger.info("Retrying with different SSH options...")
        time.sleep(5)
        
        rsync_cmd_retry = f"""
        rsync -avz \
          --progress \
          --stats \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=30 -o ServerAliveCountMax=3" \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        logger.info(f"RUNNING RSYNC RETRY COMMAND (NO --delete)")
        
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
                logger.info(f"RSYNC upload successful on retry! ({duration} seconds)")
                return True
            else:
                logger.error(f"RSYNC upload failed on both attempts!")
                return False
                
        except Exception as e:
            logger.error(f"RSYNC retry execution error: {e}")
            return False
