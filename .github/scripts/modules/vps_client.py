"""
VPS Client Module - State-First Initialization
"""

import os
import subprocess
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class VPSClient:
    """Handles SSH, remote VPS operations, and State-First initialization"""
    
    def __init__(self, config: dict):
        """
        Initialize VPSClient with configuration
        
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
        
        # Convert ssh_options list to string for use in commands
        self.ssh_options_str = ' '.join(self.ssh_options)
        
    def setup_ssh_config(self, ssh_key: Optional[str] = None):
        """Setup SSH config file for builder user - container invariant"""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)
        
        # Write SSH config file using environment variables
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
        ssh_key_path = ssh_dir / "id_ed25519"
        if not ssh_key_path.exists() and ssh_key:
            with open(ssh_key_path, "w") as f:
                f.write(ssh_key)
            ssh_key_path.chmod(0o600)
        
        # Set ownership to builder
        try:
            import shutil
            shutil.chown(ssh_dir, "builder", "builder")
            for item in ssh_dir.iterdir():
                shutil.chown(item, "builder", "builder")
        except Exception as e:
            logger.warning(f"Could not change SSH dir ownership: {e}")
    
    def _run_ssh_command(self, command: str, timeout: int = 30) -> Tuple[int, str, str]:
        """Run a command via SSH and return results"""
        ssh_cmd = [
            "ssh",
            *self.ssh_options,
            f"{self.vps_user}@{self.vps_host}",
            command
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except subprocess.TimeoutExpired:
            logger.error(f"SSH command timed out: {command[:100]}...")
            return -1, "", "SSH command timed out"
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return -1, "", str(e)
    
    def test_ssh_connection(self) -> bool:
        """Test SSH connection to VPS"""
        returncode, stdout, stderr = self._run_ssh_command("echo SSH_TEST_SUCCESS")
        return returncode == 0 and "SSH_TEST_SUCCESS" in stdout
    
    def ensure_remote_directory(self) -> bool:
        """Ensure remote directory exists and has correct permissions"""
        remote_cmd = rf"""
        if [ ! -d "{self.remote_dir}" ]; then
            sudo mkdir -p "{self.remote_dir}"
            sudo chown -R {self.vps_user}:www-data "{self.remote_dir}"
            sudo chmod -R 755 "{self.remote_dir}"
            echo "DIRECTORY_CREATED"
        else
            echo "DIRECTORY_EXISTS"
        fi
        """
        
        returncode, stdout, stderr = self._run_ssh_command(remote_cmd, timeout=60)
        return returncode == 0
    
    def check_remote_file_exists(self, path: str) -> bool:
        """Check if a file exists on the remote server"""
        remote_cmd = rf'test -f "{path}" && echo "EXISTS" || echo "MISSING"'
        returncode, stdout, stderr = self._run_ssh_command(remote_cmd)
        return returncode == 0 and "EXISTS" in stdout
    
    def get_remote_file_hash(self, path: str) -> Optional[str]:
        """Get SHA256 hash of a remote file"""
        remote_cmd = rf'''
        if [ -f "{path}" ]; then
            sha256sum "{path}" | cut -d' ' -f1
        else
            echo "FILE_NOT_FOUND"
        fi
        '''
        
        returncode, stdout, stderr = self._run_ssh_command(remote_cmd)
        if returncode == 0 and stdout and "FILE_NOT_FOUND" not in stdout:
            return stdout.strip()
        return None
    
    def get_remote_package_list_for_state(self) -> Dict[str, Dict[str, str]]:
        """
        Get ALL remote packages for initial state creation
        
        Returns:
            Dictionary mapping package_name -> {version, hash, filename}
        """
        logger.info("📋 Fetching remote package list for state initialization...")
        
        remote_cmd = rf'''
        cd "{self.remote_dir}" 2>/dev/null || exit 1
        for pkg in *.pkg.tar.*; do
            if [ -f "$pkg" ]; then
                # Extract package name and version
                pkg_base=$(echo "$pkg" | sed 's/\.pkg\.tar\..*$//')
                # Get hash
                hash=$(sha256sum "$pkg" 2>/dev/null | cut -d' ' -f1)
                if [ -n "$hash" ]; then
                    echo "$pkg_base:$hash:$pkg"
                fi
            fi
        done
        '''
        
        returncode, stdout, stderr = self._run_ssh_command(remote_cmd, timeout=60)
        if returncode != 0 or not stdout:
            logger.info("ℹ️ No remote packages found or error fetching")
            return {}
        
        packages = {}
        for line in stdout.split('\n'):
            if not line.strip():
                continue
            
            try:
                pkg_base, pkg_hash, pkg_file = line.split(':', 2)
                
                # Parse package name and version from pkg_base
                # Format: name-version-release-arch
                parts = pkg_base.split('-')
                if len(parts) >= 3:
                    # Find where version starts
                    for i in range(len(parts) - 2, 0, -1):
                        potential_name = '-'.join(parts[:i])
                        remaining = parts[i:]
                        
                        if len(remaining) >= 2:
                            # Handle epoch:version-release
                            if ':' in remaining[0]:
                                version = f"{remaining[0]}-{remaining[1]}"
                            else:
                                version = f"{remaining[0]}-{remaining[1]}"
                            
                            packages[potential_name] = {
                                "version": version,
                                "hash": pkg_hash,
                                "filename": pkg_file,
                                "last_verified": None
                            }
                            break
            except Exception as e:
                logger.debug(f"Could not parse package line: {line} - {e}")
        
        logger.info(f"✅ Found {len(packages)} remote packages for state")
        return packages
    
    def download_state_file(self, local_path: Path) -> bool:
        """Download the JSON state file from VPS"""
        remote_state_path = f"{self.remote_dir}/.build_tracking/vps_state.json"
        
        if not self.check_remote_file_exists(remote_state_path):
            logger.info("ℹ️ No state file exists on VPS (first run or reset)")
            return False
        
        scp_cmd = [
            "scp",
            *self.ssh_options,
            f"{self.vps_user}@{self.vps_host}:{remote_state_path}",
            str(local_path)
        ]
        
        try:
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Downloaded state file from VPS")
                return True
            else:
                logger.warning(f"⚠️ Failed to download state file: {result.stderr[:200]}")
                return False
                
        except Exception as e:
            logger.warning(f"Could not download state file: {e}")
            return False
    
    def upload_state_file(self, local_path: Path) -> bool:
        """Upload the JSON state file to VPS"""
        if not local_path.exists():
            logger.error("❌ Local state file doesn't exist")
            return False
        
        ensure_cmd = rf'mkdir -p "{self.remote_dir}/.build_tracking"'
        returncode, stdout, stderr = self._run_ssh_command(ensure_cmd)
        if returncode != 0:
            logger.error(f"❌ Failed to create remote .build_tracking directory: {stderr}")
            return False
        
        scp_cmd = [
            "scp",
            *self.ssh_options,
            str(local_path),
            f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/.build_tracking/vps_state.json"
        ]
        
        try:
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Uploaded state file to VPS")
                return True
            else:
                logger.error(f"❌ Failed to upload state file: {result.stderr[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Upload state file error: {e}")
            return False
    
    def check_repository_exists_on_vps(self) -> Tuple[bool, bool]:
        """Check if repository exists on VPS via SSH"""
        # Check for package files
        remote_cmd = rf'find "{self.remote_dir}" -maxdepth 1 -name "*.pkg.tar.*" -type f 2>/dev/null | head -1'
        returncode, stdout, stderr = self._run_ssh_command(remote_cmd)
        has_packages = returncode == 0 and bool(stdout.strip())
        
        # Check for database files
        db_exists = False
        for db_file in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz"]:
            if self.check_remote_file_exists(f"{self.remote_dir}/{db_file}"):
                db_exists = True
                break
        
        repo_exists = has_packages or db_exists
        return repo_exists, has_packages
    
    def upload_files(self, files_to_upload: List[str], output_dir: Path) -> bool:
        """Upload files to server using rsync WITHOUT --delete flag"""
        if not self.ensure_remote_directory():
            logger.error("❌ Failed to ensure remote directory exists")
            return False
        
        if not files_to_upload:
            logger.warning("No files to upload")
            return False
        
        files_str = ' '.join([rf"'{f}'" for f in files_to_upload])
        rsync_cmd = rf'''
        rsync -avz \
          --progress \
          --stats \
          -e "ssh {self.ssh_options_str}" \
          {files_str} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        '''
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Files uploaded successfully")
                return True
            else:
                logger.error(f"❌ Upload failed: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Upload error: {e}")
            return False