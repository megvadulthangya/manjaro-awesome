"""
SSH client for remote VPS operations
Handles SSH connections, file operations, and remote command execution
"""

import os
import shutil
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from modules.common.shell_executor import ShellExecutor


class SSHClient:
    """Handles SSH connections and remote operations on VPS with caching"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize SSHClient
        
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
        self.repo_name = config.get('repo_name', '')
        
        # SSH key path
        self.ssh_key_path = Path("/home/builder/.ssh/id_ed25519")
        
        # Add quiet flag to SSH options
        self.ssh_options_with_quiet = self.ssh_options + ["-q"]
        
        # Cache for remote operations
        self._remote_inventory_cache: Optional[Dict[str, str]] = None
        self._cache_timestamp: float = 0
        self._cache_ttl = 300  # 5 minutes
        
        # Pending operations
        self._pending_deletions: List[str] = []
    
    def get_cached_inventory(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        Get cached remote inventory with TTL
        
        Args:
            force_refresh: If True, ignore cache and refresh
            
        Returns:
            Dictionary of {filename: full_path}
        """
        current_time = time.time()
        
        if (force_refresh or 
            not self._remote_inventory_cache or 
            current_time - self._cache_timestamp > self._cache_ttl):
            
            self.logger.info("🔍 Refreshing remote inventory cache...")
            self._remote_inventory_cache = self._get_remote_file_list_optimized()
            self._cache_timestamp = current_time
            self.logger.info(f"📋 Cache updated: {len(self._remote_inventory_cache)} files")
        else:
            cache_age = int(current_time - self._cache_timestamp)
            self.logger.debug(f"📋 Using cached inventory ({cache_age}s old)")
        
        return self._remote_inventory_cache.copy()
    
    def _get_remote_file_list_optimized(self) -> Dict[str, str]:
        """
        Get optimized list of package files from remote server
        
        Returns:
            Dictionary of {filename: full_path}
        """
        remote_cmd = f"cd {self.remote_dir} && ls -1 *.pkg.tar.* 2>/dev/null || echo ''"
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,
                log_cmd=False
            )
            
            if result.returncode == 0:
                files = {}
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line and not line.startswith("Welcome") and not line.startswith("Last login"):
                        full_path = f"{self.remote_dir}/{line}"
                        files[line] = full_path
                
                return files
            else:
                self.logger.warning(f"⚠️ Failed to list remote files: {result.stderr[:200]}")
                return {}
                
        except Exception as e:
            self.logger.error(f"❌ Error listing remote files: {e}")
            return {}
    
    def batch_delete(self, file_paths: List[str], batch_size: int = 100) -> bool:
        """
        Delete multiple files in batches via single SSH session
        
        Args:
            file_paths: List of full remote paths to delete
            batch_size: Maximum files per batch to avoid command line limits
            
        Returns:
            True if all deletions successful, False otherwise
        """
        if not file_paths:
            self.logger.debug("No files to delete")
            return True
        
        self.logger.info(f"🗑️ Batch deleting {len(file_paths)} remote file(s)...")
        
        # Extract just filenames from full paths
        all_filenames = []
        for file_path in file_paths:
            filename = Path(file_path).name
            all_filenames.append(filename)
        
        # Process in batches
        success = True
        total_batches = (len(all_filenames) + batch_size - 1) // batch_size
        
        for batch_num in range(total_batches):
            batch_start = batch_num * batch_size
            batch_end = batch_start + batch_size
            batch_filenames = all_filenames[batch_start:batch_end]
            
            batch_num_display = batch_num + 1
            
            # Build delete command with proper escaping
            filenames_str = ' '.join([f"'{f}'" for f in batch_filenames])
            remote_cmd = f"cd {self.remote_dir} && rm -f {filenames_str} && echo 'BATCH_DELETE_SUCCESS_{batch_num_display}'"
            
            # Use string command with shell=True
            ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
            
            try:
                result = self.shell_executor.run(
                    ssh_cmd,
                    capture=True,
                    check=False,
                    shell=True,
                    log_cmd=False
                )
                
                if result.returncode == 0 and f"BATCH_DELETE_SUCCESS_{batch_num_display}" in result.stdout:
                    self.logger.info(f"✅ Batch {batch_num_display}/{total_batches}: Deleted {len(batch_filenames)} files")
                    
                    # Update cache by removing deleted files
                    if self._remote_inventory_cache:
                        for filename in batch_filenames:
                            self._remote_inventory_cache.pop(filename, None)
                else:
                    self.logger.warning(f"⚠️ Batch {batch_num_display} failed: {result.stderr[:200]}")
                    success = False
                    
            except Exception as e:
                self.logger.error(f"❌ Error in batch delete {batch_num_display}: {e}")
                success = False
        
        if success:
            self.logger.info(f"✅ All {len(file_paths)} files deleted successfully")
        else:
            self.logger.warning(f"⚠️ Some batch deletions failed")
        
        return success
    
    def atomic_command_sequence(self, commands: List[str], timeout: int = 60) -> Tuple[bool, str]:
        """
        Execute multiple remote commands in a single SSH session using heredoc
        
        Args:
            commands: List of shell commands to execute
            timeout: Total timeout in seconds
            
        Returns:
            Tuple of (success, combined_output)
        """
        if not commands:
            return True, "No commands to execute"
        
        self.logger.info(f"🔧 Executing {len(commands)} commands atomically...")
        
        # Build heredoc script
        heredoc_script = "set -e\n"  # Exit on error
        heredoc_script += f"cd {self.remote_dir}\n"
        
        for i, cmd in enumerate(commands):
            heredoc_script += f"echo '>>> COMMAND {i+1}: {cmd}'\n"
            heredoc_script += f"{cmd}\n"
            heredoc_script += "echo '>>> SUCCESS'\n"
        
        heredoc_script += "echo 'ATOMIC_SEQUENCE_COMPLETE'\n"
        
        # Escape for SSH
        escaped_script = heredoc_script.replace('"', '\\"').replace('$', '\\$')
        
        # Use heredoc via bash -s
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"bash -s\" << 'EOF'\n{heredoc_script}\nEOF"
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=timeout,
                shell=True,
                log_cmd=False
            )
            
            combined_output = ""
            if result.stdout:
                combined_output += result.stdout
            
            if result.returncode == 0 and "ATOMIC_SEQUENCE_COMPLETE" in result.stdout:
                self.logger.info("✅ Atomic command sequence completed successfully")
                return True, combined_output
            else:
                error_msg = result.stderr[:500] if result.stderr else "No error output"
                self.logger.error(f"❌ Atomic command sequence failed: {error_msg}")
                return False, combined_output + f"\nERROR: {error_msg}"
                
        except Exception as e:
            self.logger.error(f"❌ Atomic command sequence exception: {e}")
            return False, str(e)
    
    def queue_deletion(self, remote_path: str):
        """
        Queue a file for batch deletion
        
        Args:
            remote_path: Full remote path to delete
        """
        self._pending_deletions.append(remote_path)
    
    def commit_queued_deletions(self) -> bool:
        """
        Execute all queued deletions
        
        Returns:
            True if successful
        """
        if not self._pending_deletions:
            return True
        
        self.logger.info(f"🔧 Committing {len(self._pending_deletions)} queued deletions...")
        success = self.batch_delete(self._pending_deletions)
        
        if success:
            self._pending_deletions.clear()
        
        return success
    
    def clear_cache(self):
        """Clear the remote inventory cache"""
        self._remote_inventory_cache = None
        self._cache_timestamp = 0
        self.logger.debug("Cleared remote inventory cache")
    
    def invalidate_cache_for_file(self, filename: str):
        """Remove a specific file from cache"""
        if self._remote_inventory_cache and filename in self._remote_inventory_cache:
            del self._remote_inventory_cache[filename]
            self.logger.debug(f"Invalidated cache entry for: {filename}")
    
    # Existing methods remain unchanged but use cache where appropriate
    
    def delete_remote_files(self, file_list: List[str]) -> bool:
        """Legacy method - delegates to batch_delete"""
        return self.batch_delete(file_list)
    
    def setup_ssh_config(self, ssh_key: Optional[str] = None) -> bool:
        """
        Setup SSH config file for builder user
        
        Args:
            ssh_key: Optional SSH private key content
        
        Returns:
            True if setup successful
        """
        try:
            ssh_dir = Path("/home/builder/.ssh")
            ssh_dir.mkdir(exist_ok=True, mode=0o700)
            
            # Write SSH config file
            config_content = f"""Host {self.vps_host}
  HostName {self.vps_host}
  User {self.vps_user}
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking no
  ConnectTimeout 30
  ServerAliveInterval 15
  ServerAliveCountMax 3
"""
            
            config_file = ssh_dir / "config"
            with open(config_file, "w") as f:
                f.write(config_content)
            
            config_file.chmod(0o600)
            
            # Ensure SSH key exists and has correct permissions
            if not self.ssh_key_path.exists() and ssh_key:
                with open(self.ssh_key_path, "w") as f:
                    f.write(ssh_key)
                self.ssh_key_path.chmod(0o600)
            
            # Set ownership to builder
            try:
                shutil.chown(ssh_dir, "builder", "builder")
                for item in ssh_dir.iterdir():
                    shutil.chown(item, "builder", "builder")
            except Exception as e:
                self.logger.warning(f"Could not change SSH dir ownership: {e}")
            
            self.logger.info("✅ SSH configuration setup complete")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ SSH configuration failed: {e}")
            return False
    
    def test_connection(self) -> bool:
        """
        Test SSH connection to VPS
        
        Returns:
            True if connection successful
        """
        self.logger.info("🔍 Testing SSH connection to VPS...")
        
        ssh_test_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"cd {self.remote_dir} && echo SSH_TEST_SUCCESS\""
        
        try:
            result = self.shell_executor.run(
                ssh_test_cmd,
                capture=True,
                check=False,
                shell=True,
                log_cmd=False
            )
            
            if result and result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout:
                self.logger.info("✅ SSH connection successful")
                return True
            else:
                error_msg = result.stderr[:100] if result and result.stderr else 'No output'
                self.logger.warning(f"⚠️ SSH connection failed: {error_msg}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ SSH test exception: {e}")
            return False
    
    def get_remote_file_list(self) -> List[str]:
        """
        Get explicit list of package files from remote server (legacy)
        
        Returns:
            List of package filenames
        """
        inventory = self.get_cached_inventory()
        return list(inventory.values())
    
    def file_exists(self, remote_path: str) -> bool:
        """
        Check if a file exists on remote server
        
        Args:
            remote_path: Full remote path to check
        
        Returns:
            True if file exists
        """
        # Extract filename from path
        filename = Path(remote_path).name
        
        # Use cache first
        inventory = self.get_cached_inventory()
        if filename in inventory:
            return True
        
        # Fallback to direct check
        remote_cmd = f"cd {self.remote_dir} && test -f \"{filename}\" && echo EXISTS || echo NOT_EXISTS"
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,
                log_cmd=False
            )
            
            if result.returncode == 0 and "EXISTS" in result.stdout:
                # Update cache
                if self._remote_inventory_cache is not None:
                    self._remote_inventory_cache[filename] = remote_path
                return True
            return False
        except Exception as e:
            self.logger.warning(f"Could not check file existence {remote_path}: {e}")
            return False
    
    def get_remote_hash(self, remote_path: str) -> Optional[str]:
        """
        Get SHA256 hash of remote file
        
        Args:
            remote_path: Full remote path to file
        
        Returns:
            SHA256 hash string or None if failed
        """
        # Extract filename from path
        filename = Path(remote_path).name
        
        remote_cmd = f"cd {self.remote_dir} && sha256sum \"{filename}\" 2>/dev/null | cut -d' ' -f1"
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,
                log_cmd=False
            )
            
            if result.returncode == 0 and result.stdout.strip():
                hash_value = result.stdout.strip()
                if len(hash_value) == 64:  # SHA256 hash length
                    return hash_value
                else:
                    self.logger.warning(f"Invalid hash format for {remote_path}")
            return None
        except Exception as e:
            self.logger.warning(f"Could not get hash for {remote_path}: {e}")
            return None
    
    def ensure_directory(self) -> bool:
        """
        Ensure remote directory exists and has correct permissions
        
        Returns:
            True if directory exists or was created successfully
        """
        self.logger.info("🔧 Ensuring remote directory exists...")
        
        remote_cmd = f"""
        # Check if directory exists
        if [ ! -d "{self.remote_dir}" ]; then
            echo "Creating directory {self.remote_dir}"
            sudo mkdir -p "{self.remote_dir}"
            sudo chown -R {self.vps_user}:www-data "{self.remote_dir}"
            sudo chmod -R 755 "{self.remote_dir}"
            echo "✅ Directory created and permissions set"
        else
            echo "✅ Directory exists"
            # Ensure correct permissions
            sudo chown -R {self.vps_user}:www-data "{self.remote_dir}"
            sudo chmod -R 755 "{self.remote_dir}"
            echo "✅ Permissions verified"
        fi
        """
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,
                log_cmd=False
            )
            
            if result.returncode == 0:
                self.logger.info("✅ Remote directory verified")
                for line in result.stdout.splitlines():
                    if line.strip():
                        self.logger.debug(f"REMOTE DIR: {line}")
                return True
            else:
                self.logger.warning(f"⚠️ Could not ensure remote directory: {result.stderr[:200]}")
                return False
                
        except Exception as e:
            self.logger.warning(f"Could not ensure remote directory: {e}")
            return False
    
    def check_repository_exists(self) -> Tuple[bool, bool]:
        """
        Check if repository exists on VPS via SSH
        
        Returns:
            Tuple of (exists, has_packages)
        """
        self.logger.info("🔍 Checking if repository exists on VPS...")
        
        remote_cmd = f"""
        # Check for package files
        if cd "{self.remote_dir}" && find . -maxdepth 1 -name "*.pkg.tar.*" -type f 2>/dev/null | head -1 >/dev/null; then
            echo "REPO_EXISTS_WITH_PACKAGES"
        # Check for database files
        elif cd "{self.remote_dir}" && ([ -f "{self.repo_name}.db.tar.gz" ] || [ -f "{self.repo_name}.db" ]); then
            echo "REPO_EXISTS_WITH_DB"
        else
            echo "REPO_NOT_FOUND"
        fi
        """
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=30,
                shell=True,
                log_cmd=False
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if "REPO_EXISTS_WITH_PACKAGES" in output:
                    self.logger.info("✅ Repository exists on VPS (has package files)")
                    return True, True
                elif "REPO_EXISTS_WITH_DB" in output:
                    self.logger.info("✅ Repository exists on VPS (has database)")
                    return True, False
                else:
                    self.logger.info("ℹ️ Repository does not exist on VPS (first run)")
                    return False, False
            else:
                self.logger.warning(f"⚠️ Could not check repository existence: {result.stderr[:200]}")
                return False, False
                
        except Exception as e:
            self.logger.error(f"❌ Error checking repository: {e}")
            return False, False
    
    def list_remote_files(self, pattern: str = "*.pkg.tar.*") -> List[str]:
        """
        List files on remote server matching pattern
        
        Args:
            pattern: File pattern to match
        
        Returns:
            List of remote file paths
        """
        if pattern == "*.pkg.tar.*":
            # Use cached inventory for common pattern
            inventory = self.get_cached_inventory()
            return list(inventory.values())
        
        # For other patterns, fall back to direct query
        remote_cmd = f"cd {self.remote_dir} && find . -maxdepth 1 -type f -name '{pattern}' 2>/dev/null | sed 's|^\./||'"
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        self.logger.info(f"Listing remote files with pattern: {pattern}")
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,
                log_cmd=False
            )
            
            if result.returncode == 0:
                files = []
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line and not line.startswith("Welcome") and not line.startswith("Last login"):
                        full_path = f"{self.remote_dir}/{line}"
                        files.append(full_path)
                
                self.logger.info(f"✅ Found {len(files)} remote files")
                return files
            else:
                self.logger.warning(f"⚠️ Failed to list remote files: {result.stderr[:200]}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Error listing remote files: {e}")
            return []
    
    def execute_remote_command(self, command: str, timeout: int = 30) -> Tuple[bool, str]:
        """
        Execute a command on remote server
        
        Args:
            command: Command to execute
            timeout: Command timeout in seconds
        
        Returns:
            Tuple of (success, output)
        """
        # Prepend cd to remote_dir
        remote_cmd = f"cd {self.remote_dir} && {command}"
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=timeout,
                shell=True,
                log_cmd=False
            )
            
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip()
                
        except Exception as e:
            self.logger.error(f"❌ Remote command execution failed: {e}")
            return False, str(e)
    
    def debug_remote_directory(self) -> bool:
        """
        Debug: List remote directory contents with full details
        
        Returns:
            True if command executed successfully
        """
        self.logger.info("🔍 DEBUG: Listing remote directory contents...")
        
        remote_cmd = f"cd {self.remote_dir} && pwd && echo '=== DIRECTORY CONTENTS ===' && ls -la && echo '=== PACKAGE FILES ===' && ls -la *.pkg.tar.* 2>/dev/null || echo 'No package files found'"
        
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        self.logger.debug(f"DEBUG COMMAND: {ssh_cmd}")
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,
                log_cmd=False
            )
            
            self.logger.info("[DEBUG] REMOTE DIR CONTENT:")
            self.logger.info("=" * 60)
            if result.stdout:
                for line in result.stdout.strip().splitlines():
                    self.logger.info(f"[DEBUG] {line}")
            self.logger.info("=" * 60)
            
            if result.stderr:
                self.logger.warning(f"[DEBUG] STDERR: {result.stderr[:200]}")
            
            return result.returncode == 0
        except Exception as e:
            self.logger.error(f"[DEBUG] Error listing remote directory: {e}")
            return False