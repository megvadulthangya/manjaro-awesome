"""
SSH client for remote VPS operations
Handles SSH connections, file operations, and remote command execution
"""

import os
import shutil
import logging
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

from modules.common.shell_executor import ShellExecutor


class SSHClient:
    """Handles SSH connections and remote operations on VPS"""
    
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
        
        # Add quiet flag to SSH options to suppress MOTD
        self.ssh_options_with_quiet = self.ssh_options + ["-q"]
    
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
        
        ssh_test_cmd = [
            "ssh",
            *self.ssh_options_with_quiet,  # Use quiet mode
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]
        
        try:
            result = self.shell_executor.run(
                ssh_test_cmd,
                capture=True,
                check=False,
                shell=False,
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
        
        ssh_cmd = ["ssh", *self.ssh_options_with_quiet, f"{self.vps_user}@{self.vps_host}", remote_cmd]
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
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
        if find "{self.remote_dir}" -name "*.pkg.tar.*" -type f 2>/dev/null | head -1 >/dev/null; then
            echo "REPO_EXISTS_WITH_PACKAGES"
        # Check for database files
        elif [ -f "{self.remote_dir}/{self.repo_name}.db.tar.gz" ] || [ -f "{self.remote_dir}/{self.repo_name}.db" ]; then
            echo "REPO_EXISTS_WITH_DB"
        else
            echo "REPO_NOT_FOUND"
        fi
        """
        
        ssh_cmd = ["ssh", *self.ssh_options_with_quiet, f"{self.vps_user}@{self.vps_host}", remote_cmd]
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=30,
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
            List of remote file paths (filtered to remove MOTD and non-filename lines)
        """
        remote_cmd = f"find {self.remote_dir} -maxdepth 1 -type f -name '{pattern}' 2>/dev/null"
        
        ssh_cmd = [
            "ssh",
            *self.ssh_options_with_quiet,  # Use quiet mode
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        self.logger.info(f"Listing remote files with pattern: {pattern}")
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                log_cmd=False
            )
            
            if result.returncode == 0:
                # Filter out non-filename lines (MOTD, warnings, etc.)
                files = []
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Skip common non-filename patterns
                    if any(x in line.lower() for x in [
                        'welcome', 'last login', 'system information',
                        'running', 'uptime', 'memory', 'disk', 'motd',
                        'warnings', 'secrets', 'do not share'
                    ]):
                        self.logger.debug(f"Skipping non-filename line: {line[:50]}...")
                        continue
                    
                    # Only include lines that look like file paths
                    if '/' in line and (line.endswith('.pkg.tar.zst') or line.endswith('.pkg.tar.xz')):
                        files.append(line)
                
                self.logger.info(f"✅ Found {len(files)} valid remote files (filtered)")
                return files
            else:
                self.logger.warning(f"⚠️ Failed to list remote files: {result.stderr[:200]}")
                return []
                
        except Exception as e:
            self.logger.error(f"❌ Error listing remote files: {e}")
            return []
    
    def get_file_inventory(self) -> Dict[str, str]:
        """
        Get complete inventory of all files on VPS
        
        Returns:
            Dictionary of {filename: full_path}
        """
        self.logger.info("📋 Getting complete VPS file inventory...")
        
        remote_cmd = rf"""
        # Get all package files, signatures, and database files
        find "{self.remote_dir}" -maxdepth 1 -type f \( -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" -o -name "*.sig" -o -name "*.db" -o -name "*.db.tar.gz" -o -name "*.files" -o -name "*.files.tar.gz" -o -name "*.abs.tar.gz" \) 2>/dev/null
        """
        
        ssh_cmd = [
            "ssh",
            *self.ssh_options_with_quiet,  # Use quiet mode
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=30,
                log_cmd=False
            )
            
            if result.returncode != 0:
                self.logger.warning(f"Could not list VPS files: {result.stderr[:200]}")
                return {}
            
            vps_files_raw = result.stdout.strip()
            if not vps_files_raw:
                self.logger.info("No files found on VPS")
                return {}
            
            # Filter out non-filename lines
            valid_files = []
            for line in vps_files_raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                
                # Skip non-filename lines
                if any(x in line.lower() for x in [
                    'welcome', 'last login', 'system', 'uptime',
                    'memory', 'disk', 'motd', 'warning', 'secret'
                ]):
                    continue
                
                if '/' in line and ('.pkg.tar.' in line or '.db' in line or '.sig' in line):
                    valid_files.append(line)
            
            self.logger.info(f"Found {len(valid_files)} valid files on VPS (filtered)")
            
            # Convert to filename: path dictionary
            inventory = {}
            for file_path in valid_files:
                filename = Path(file_path).name
                inventory[filename] = file_path
            
            return inventory
            
        except Exception as e:
            self.logger.error(f"❌ Error getting VPS file inventory: {e}")
            return {}
    
    def delete_remote_files(self, files_to_delete: List[str]) -> bool:
        """
        Delete files from remote server
        
        Args:
            files_to_delete: List of full paths to delete
        
        Returns:
            True if deletion successful
        """
        if not files_to_delete:
            return True
        
        # Quote each filename for safety
        quoted_files = [f"'{f}'" for f in files_to_delete]
        files_to_delete_str = ' '.join(quoted_files)
        
        delete_cmd = f"rm -fv {files_to_delete_str}"
        
        self.logger.info(f"🚀 Deleting {len(files_to_delete)} files from remote server")
        
        ssh_cmd = [
            "ssh",
            *self.ssh_options_with_quiet,  # Use quiet mode
            f"{self.vps_user}@{self.vps_host}",
            delete_cmd
        ]
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=60,
                log_cmd=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"✅ Deletion successful for {len(files_to_delete)} files")
                if result.stdout:
                    for line in result.stdout.splitlines():
                        if "removed" in line.lower() or "deleted" in line.lower():
                            self.logger.debug(f"   {line}")
                return True
            else:
                self.logger.error(f"❌ Deletion failed: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error during deletion: {e}")
            return False
    
    def execute_remote_command(self, command: str, timeout: int = 30) -> Tuple[bool, str]:
        """
        Execute a command on remote server
        
        Args:
            command: Command to execute
            timeout: Command timeout in seconds
        
        Returns:
            Tuple of (success, output)
        """
        ssh_cmd = [
            "ssh",
            *self.ssh_options_with_quiet,  # Use quiet mode
            f"{self.vps_user}@{self.vps_host}",
            command
        ]
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=timeout,
                log_cmd=False
            )
            
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip()
                
        except Exception as e:
            self.logger.error(f"❌ Remote command execution failed: {e}")
            return False, str(e)