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
        
        # Use string command with shell=True for SSH test
        ssh_test_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"cd {self.remote_dir} && echo SSH_TEST_SUCCESS\""
        
        try:
            result = self.shell_executor.run(
                ssh_test_cmd,
                capture=True,
                check=False,
                shell=True,  # Use shell=True for string command
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
        
        # Use cd into remote_dir and check file
        remote_cmd = f"cd {self.remote_dir} && test -f \"{filename}\" && echo EXISTS || echo NOT_EXISTS"
        
        # Use string command with shell=True
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,  # Use shell=True for string command
                log_cmd=False
            )
            
            if result.returncode == 0 and "EXISTS" in result.stdout:
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
        
        # Use cd into remote_dir and run sha256sum
        remote_cmd = f"cd {self.remote_dir} && sha256sum \"{filename}\" 2>/dev/null | cut -d' ' -f1"
        
        # Use string command with shell=True
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,  # Use shell=True for string command
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
        
        # Use string command with shell=True
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,  # Use shell=True for string command
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
        
        # Use string command with shell=True
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=30,
                shell=True,  # Use shell=True for string command
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
        # Use cd into remote_dir and find files
        remote_cmd = f"cd {self.remote_dir} && find . -maxdepth 1 -type f -name '{pattern}' 2>/dev/null | sed 's|^\./||'"
        
        # Use string command with shell=True
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        self.logger.info(f"Listing remote files with pattern: {pattern}")
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                shell=True,  # Use shell=True for string command
                log_cmd=False
            )
            
            if result.returncode == 0:
                # Clean output - split lines and remove empty
                files = []
                for line in result.stdout.strip().splitlines():
                    line = line.strip()
                    if line and not line.startswith("Welcome") and not line.startswith("Last login"):
                        # Construct full path
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
        
        # Use string command with shell=True
        ssh_cmd = f"ssh -q {self.vps_user}@{self.vps_host} \"{remote_cmd}\""
        
        try:
            result = self.shell_executor.run(
                ssh_cmd,
                capture=True,
                check=False,
                timeout=timeout,
                shell=True,  # Use shell=True for string command
                log_cmd=False
            )
            
            if result.returncode == 0:
                return True, result.stdout.strip()
            else:
                return False, result.stderr.strip()
                
        except Exception as e:
            self.logger.error(f"❌ Remote command execution failed: {e}")
            return False, str(e)