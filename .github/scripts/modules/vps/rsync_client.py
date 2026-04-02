"""
Rsync Client Module - Handles file transfers using Rsync
WITH STAGING UPLOAD SUPPORT FOR ATOMIC PUBLISH
AND DELTA-EFFICIENT STAGING USING --link-dest
"""

import os
import subprocess
import shutil
import time
import logging
from pathlib import Path
from typing import List, Optional

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
    
    def _is_staging_path(self, remote_path: Optional[str]) -> bool:
        """
        Determine if the remote_path points to a staging directory under
        the main remote_dir, i.e. contains '/.staging/' after the base.
        """
        if remote_path is None:
            return False
        # remote_path must start with self.remote_dir to be under it
        if not remote_path.startswith(self.remote_dir):
            return False
        suffix = remote_path[len(self.remote_dir):]
        # After the base, there should be exactly '/.staging/' followed by something
        return suffix.startswith('/.staging/')
    
    def _get_relative_link_dest(self, staging_path: str) -> str:
        """
        Compute relative path from staging_path to self.remote_dir.
        Example: staging_path = /repo/.staging/run_123
                 self.remote_dir = /repo
                 Returns '../..'
        """
        # Normalize paths (remove trailing slash)
        staging = staging_path.rstrip('/')
        live = self.remote_dir.rstrip('/')
        # Compute relative path from staging directory to live directory
        rel = os.path.relpath(live, start=staging)
        # Ensure it's not empty (should be at least '..' or '../..')
        if rel == '.':
            rel = ''
        return rel
    
    def _remote_dir_exists(self, remote_path: str) -> bool:
        """Check if remote directory exists via SSH."""
        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}",
                   f"test -d '{remote_path}' && echo 'EXISTS' || echo 'NOT_EXISTS'"]
        try:
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0 and 'EXISTS' in result.stdout
        except Exception:
            return False
    
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
    
    def upload_files(self, files_to_upload: List[str], output_dir: Path, cleanup_manager=None, remote_path: Optional[str] = None) -> bool:
        """
        Upload files to remote server using RSYNC.
        
        CRITICAL: This is transport-only. Deletions are handled separately.
        Supports staging by specifying remote_path (e.g., staging directory).
        For staging uploads (remote_path under .staging/), adds --link-dest
        to avoid re‑uploading files already present in the live REMOTE_DIR.
        
        Args:
            files_to_upload: List of file paths to upload
            output_dir: Output directory (unused, kept for backward compatibility)
            cleanup_manager: Ignored (kept for backward compatibility only)
            remote_path: Remote destination path (defaults to self.remote_dir)
            
        Returns:
            True if rsync transport succeeded, False otherwise
        """
        if not files_to_upload:
            logger.warning("No files to upload")
            return False
        
        # Determine remote destination
        dest_path = remote_path if remote_path is not None else self.remote_dir
        
        # Log files to upload (safe - only filenames, not paths)
        logger.info(f"Files to upload ({len(files_to_upload)}) to {dest_path}:")
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
        
        # Check if this is a staging upload (target is under .staging/)
        is_staging = self._is_staging_path(dest_path)
        
        # Helper to run a command and return success/failure
        def run_rsync(cmd_str: str, attempt_label: str) -> bool:
            logger.info(f"RUNNING RSYNC COMMAND {attempt_label}")
            start_time = time.time()
            try:
                result = subprocess.run(
                    cmd_str,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False
                )
                end_time = time.time()
                duration = int(end_time - start_time)
                
                logger.info(f"EXIT CODE {attempt_label}: {result.returncode}")
                if result.stdout:
                    for line in result.stdout.splitlines():
                        if line.strip():
                            logger.info(f"RSYNC {attempt_label}: {line}")
                if result.stderr:
                    for line in result.stderr.splitlines():
                        if line.strip() and "No such file or directory" not in line:
                            logger.error(f"RSYNC ERR {attempt_label}: {line}")
                
                if result.returncode == 0:
                    logger.info(f"RSYNC upload successful {attempt_label}! ({duration} seconds)")
                    return True
                else:
                    logger.warning(f"RSYNC attempt {attempt_label} failed (code: {result.returncode})")
                    return False
            except Exception as e:
                logger.error(f"RSYNC execution error {attempt_label}: {e}")
                return False
        
        # =====================================================================
        # STAGING UPLOAD – incremental with --link-dest, NO fallback to full upload
        # =====================================================================
        if is_staging:
            logger.info("STAGING_UPLOAD: preparing incremental upload with --link-dest")
            
            # 1. Validate that live reference directory exists on VPS
            if not self._remote_dir_exists(self.remote_dir):
                raise RuntimeError(
                    f"CRITICAL: Live reference directory does not exist on VPS: {self.remote_dir}. "
                    f"Cannot perform incremental staging upload."
                )
            logger.info(f"STAGING_UPLOAD: live reference directory exists: {self.remote_dir}")
            
            # 2. Compute relative link-dest path
            rel_link_dest = self._get_relative_link_dest(dest_path)
            if not rel_link_dest:
                # If dest_path equals remote_dir (shouldn't happen for staging), fallback to '.'
                rel_link_dest = '.'
            logger.info(f"STAGING_UPLOAD: link-dest relative path = '{rel_link_dest}'")
            
            # 3. Build rsync command with --link-dest
            files_str = ' '.join(f"'{f}'" for f in files_to_upload)
            ssh_part = "-e \"ssh " + " ".join(self.ssh_options) + "\""
            rsync_cmd = (
                f"rsync -avz --progress --stats "
                f"--link-dest='{rel_link_dest}' "
                f"{ssh_part} "
                f"{files_str} "
                f"'{self.vps_user}@{self.vps_host}:{dest_path}/'"
            )
            logger.info(f"STAGING_UPLOAD: rsync command (link-dest={rel_link_dest})")
            
            # 4. Execute rsync once – if it fails, hard fail the pipeline
            if run_rsync(rsync_cmd, "STAGING (with --link-dest)"):
                return True
            else:
                # Log the failure and abort – no fallback
                logger.error("STAGING_UPLOAD: --link-dest attempt failed, aborting to prevent full re-upload")
                raise RuntimeError("CRITICAL: --link-dest failed, aborting to prevent full re-upload")
        
        # =====================================================================
        # NON‑STAGING UPLOAD – original two‑attempt logic (no --link-dest)
        # =====================================================================
        logger.info("NON_STAGING_UPLOAD: using standard upload (no --link-dest)")
        
        def build_cmd(extra_ssh_options: str = "") -> str:
            ssh_part = f"-e \"ssh {extra_ssh_options}\"" if extra_ssh_options else ""
            return f"""
            rsync -avz \
              --progress \
              --stats \
              {ssh_part} \
              {" ".join(f"'{f}'" for f in files_to_upload)} \
              '{self.vps_user}@{self.vps_host}:{dest_path}/'
            """
        
        # FIRST ATTEMPT (default SSH options)
        cmd1 = build_cmd(extra_ssh_options="")
        if run_rsync(cmd1, "ATTEMPT 1"):
            return True
        
        # SECOND ATTEMPT (with different SSH options)
        logger.info("Retrying with different SSH options...")
        time.sleep(5)
        cmd2 = build_cmd(
            extra_ssh_options="-o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=30 -o ServerAliveCountMax=3"
        )
        if run_rsync(cmd2, "ATTEMPT 2"):
            return True
        
        logger.error("RSYNC upload failed on both attempts!")
        return False
