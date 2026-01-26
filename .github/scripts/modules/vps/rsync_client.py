"""
Rsync client for efficient file transfer between local and remote systems
Handles uploads, downloads, and mirroring operations
"""

import os
import shutil
import time
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

from modules.common.shell_executor import ShellExecutor


class RsyncClient:
    """Handles rsync operations for file transfer between local and remote"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize RsyncClient
        
        Args:
            config: Configuration dictionary with VPS settings
            shell_executor: ShellExecutor instance for command execution
            logger: Optional logger instance
        """
        self.config = config
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
        
        # Extract VPS configuration
        self.vps_user = config.get('vps_user', '')
        self.vps_host = config.get('vps_host', '')
        self.remote_dir = config.get('remote_dir', '')
        self.ssh_options = config.get('ssh_options', [])
        
        # Build SSH options string for rsync
        self.ssh_opts_str = ' '.join(self.ssh_options)
    
    def upload(self, local_files: List[str], local_base_dir: Optional[Path] = None) -> bool:
        """
        Upload files to server using RSYNC WITHOUT --delete flag
        
        Args:
            local_files: List of local file paths to upload
            local_base_dir: Base directory for relative paths
        
        Returns:
            True if upload successful
        """
        if not local_files:
            self.logger.warning("No files to upload")
            return False
        
        # Log files to upload (safe - only filenames, not paths)
        self.logger.info(f"Files to upload ({len(local_files)}):")
        for file_path in local_files:
            try:
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
                filename = os.path.basename(file_path)
                file_type = "PACKAGE"
                if self.config.get('repo_name', '') in filename:
                    file_type = "DATABASE" if not file_path.endswith('.sig') else "SIGNATURE"
                self.logger.info(f"  - {filename} ({size_mb:.1f}MB) [{file_type}]")
            except Exception:
                self.logger.info(f"  - {os.path.basename(file_path)} [UNKNOWN SIZE]")
        
        # Build RSYNC command WITHOUT --delete
        rsync_cmd = self._build_rsync_command(local_files, local_base_dir, delete=False)
        
        self.logger.info(f"RUNNING RSYNC COMMAND WITHOUT --delete:")
        self.logger.info(rsync_cmd.strip())
        
        # FIRST ATTEMPT
        start_time = time.time()
        
        try:
            result = self.shell_executor.run(
                rsync_cmd,
                shell=True,
                capture=True,
                text=True,
                check=False,
                log_cmd=True
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            self.logger.info(f"EXIT CODE (attempt 1): {result.returncode}")
            
            if result.returncode == 0:
                self._log_rsync_output(result, "RSYNC")
                self.logger.info(f"✅ RSYNC upload successful! ({duration} seconds)")
                return True
            else:
                self.logger.warning(f"⚠️ First RSYNC attempt failed (code: {result.returncode})")
                
        except Exception as e:
            self.logger.error(f"RSYNC execution error: {e}")
        
        # SECOND ATTEMPT (with different SSH options)
        self.logger.info("⚠️ Retrying with different SSH options...")
        time.sleep(5)
        
        rsync_cmd_retry = self._build_rsync_command(
            local_files, 
            local_base_dir, 
            delete=False,
            enhanced_ssh=True
        )
        
        self.logger.info(f"RUNNING RSYNC RETRY COMMAND WITHOUT --delete:")
        self.logger.info(rsync_cmd_retry.strip())
        
        start_time = time.time()
        
        try:
            result = self.shell_executor.run(
                rsync_cmd_retry,
                shell=True,
                capture=True,
                text=True,
                check=False,
                log_cmd=True
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            self.logger.info(f"EXIT CODE (attempt 2): {result.returncode}")
            
            if result.returncode == 0:
                self._log_rsync_output(result, "RSYNC RETRY")
                self.logger.info(f"✅ RSYNC upload successful on retry! ({duration} seconds)")
                return True
            else:
                self.logger.error(f"❌ RSYNC upload failed on both attempts!")
                return False
                
        except Exception as e:
            self.logger.error(f"RSYNC retry execution error: {e}")
            return False
    
    def mirror_remote(self, remote_pattern: str, local_dir: Path, 
                      temp_dir: Optional[Path] = None) -> bool:
        """
        Download remote files to local directory (mirror)
        
        Args:
            remote_pattern: Remote file pattern to download
            local_dir: Local directory to save files
            temp_dir: Temporary directory for download (optional)
        
        Returns:
            True if mirror successful
        """
        if temp_dir is None:
            temp_dir = Path("/tmp/repo_mirror")
        
        # Create temporary local repository directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"Created local mirror directory: {temp_dir}")
        
        # Use rsync to download files from server
        self.logger.info(f"📥 Downloading remote files to local mirror...")
        
        # Build rsync command for mirroring
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60" \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/{remote_pattern}' \
          '{temp_dir}/' 2>/dev/null || true
        """
        
        self.logger.info(f"RUNNING RSYNC MIRROR COMMAND:")
        self.logger.info(rsync_cmd.strip())
        
        start_time = time.time()
        
        try:
            result = self.shell_executor.run(
                rsync_cmd,
                shell=True,
                capture=True,
                text=True,
                check=False,
                log_cmd=True
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            self.logger.info(f"EXIT CODE: {result.returncode}")
            self._log_rsync_output(result, "RSYNC MIRROR")
            
            # List downloaded files
            downloaded_files = list(temp_dir.glob("*"))
            file_count = len(downloaded_files)
            
            if file_count > 0:
                self.logger.info(f"✅ Successfully mirrored {file_count} files ({duration} seconds)")
                self.logger.info(f"Sample mirrored files: {[f.name for f in downloaded_files[:5]]}")
                
                # Verify file integrity and copy to target directory
                valid_files = []
                for file_path in downloaded_files:
                    if file_path.stat().st_size > 0:
                        valid_files.append(file_path)
                    else:
                        self.logger.warning(f"⚠️ Empty file: {file_path.name}")
                
                self.logger.info(f"Valid mirrored files: {len(valid_files)}/{file_count}")
                
                # Copy mirrored files to target directory
                self.logger.info(f"📋 Copying {len(valid_files)} mirrored files to target directory...")
                copied_count = 0
                for file_path in valid_files:
                    dest = local_dir / file_path.name
                    if not dest.exists():  # Don't overwrite existing files
                        shutil.copy2(file_path, dest)
                        copied_count += 1
                
                self.logger.info(f"Copied {copied_count} mirrored files to target directory")
                
                # Clean up temporary directory
                shutil.rmtree(temp_dir, ignore_errors=True)
                
                return True
            else:
                self.logger.info("ℹ️ No files were mirrored")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return True
                
        except Exception as e:
            self.logger.error(f"RSYNC mirror execution error: {e}")
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            return False
    
    def _build_rsync_command(self, local_files: List[str], local_base_dir: Optional[Path],
                            delete: bool = False, enhanced_ssh: bool = False) -> str:
        """
        Build rsync command
        
        Args:
            local_files: List of local file paths
            local_base_dir: Base directory for relative paths
            delete: Whether to add --delete flag
            enhanced_ssh: Whether to use enhanced SSH options
        
        Returns:
            Rsync command string
        """
        # Build file list
        if local_base_dir:
            # Use relative paths from base directory
            file_args = []
            for file_path in local_files:
                rel_path = os.path.relpath(file_path, local_base_dir)
                file_args.append(f"'{rel_path}'")
        else:
            # Use absolute paths
            file_args = [f"'{f}'" for f in local_files]
        
        file_args_str = ' '.join(file_args)
        
        # Build SSH options
        if enhanced_ssh:
            ssh_opts = '-e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=30 -o ServerAliveCountMax=3"'
        else:
            ssh_opts = f'-e "ssh {self.ssh_opts_str}"' if self.ssh_opts_str else ''
        
        # Build delete flag
        delete_flag = '--delete' if delete else ''
        
        # Build command
        if local_base_dir:
            # Change to base directory and use relative paths
            cmd = f"""
            cd '{local_base_dir}' && rsync -avz \
              --progress \
              --stats \
              {delete_flag} \
              {ssh_opts} \
              {file_args_str} \
              '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
            """
        else:
            # Use absolute paths
            cmd = f"""
            rsync -avz \
              --progress \
              --stats \
              {delete_flag} \
              {ssh_opts} \
              {file_args_str} \
              '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
            """
        
        return cmd.strip()
    
    def _log_rsync_output(self, result: Any, prefix: str = "RSYNC") -> None:
        """Log rsync output"""
        if result.stdout:
            for line in result.stdout.splitlines():
                if line.strip():
                    self.logger.debug(f"{prefix}: {line}")
        if result.stderr:
            for line in result.stderr.splitlines():
                if line.strip() and "No such file or directory" not in line:
                    self.logger.error(f"{prefix} ERR: {line}")
    
    def sync_directories(self, local_dir: Path, remote_subdir: str = "", 
                        delete: bool = False) -> bool:
        """
        Sync entire directories
        
        Args:
            local_dir: Local directory to sync
            remote_subdir: Remote subdirectory (optional)
            delete: Whether to delete extra files on remote
        
        Returns:
            True if sync successful
        """
        remote_target = f"{self.remote_dir}/{remote_subdir}" if remote_subdir else self.remote_dir
        
        # Build rsync command for directory sync
        delete_flag = '--delete' if delete else ''
        
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          {delete_flag} \
          -e "ssh {self.ssh_opts_str}" \
          '{local_dir}/' \
          '{self.vps_user}@{self.vps_host}:{remote_target}/'
        """
        
        self.logger.info(f"Syncing directory {local_dir} to {remote_target}")
        self.logger.debug(f"RSYNC command: {rsync_cmd.strip()}")
        
        try:
            result = self.shell_executor.run(
                rsync_cmd,
                shell=True,
                capture=True,
                text=True,
                check=False,
                log_cmd=True
            )
            
            if result.returncode == 0:
                self.logger.info("✅ Directory sync successful")
                return True
            else:
                self.logger.error(f"❌ Directory sync failed: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Directory sync error: {e}")
            return False