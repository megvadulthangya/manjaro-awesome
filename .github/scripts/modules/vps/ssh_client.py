"""
SSH Client Module - Handles SSH connections and remote operations
"""

import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class SSHClient:
    """Handles SSH connections and remote VPS operations"""
    
    def __init__(self, config: dict):
        """
        Initialize SSHClient with configuration
        
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
            shutil.chown(ssh_dir, "builder", "builder")
            for item in ssh_dir.iterdir():
                shutil.chown(item, "builder", "builder")
        except Exception as e:
            logger.warning(f"Could not change SSH dir ownership: {e}")
    
    def test_ssh_connection(self) -> bool:
        """Test SSH connection to VPS"""
        print("\n🔍 Testing SSH connection to VPS...")
        
        ssh_test_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]
        
        result = subprocess.run(ssh_test_cmd, capture_output=True, text=True, check=False)
        if result and result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout:
            print("✅ SSH connection successful")
            return True
        else:
            print(f"⚠️ SSH connection failed: {result.stderr[:100] if result and result.stderr else 'No output'}")
            return False
    
    def ensure_remote_directory(self):
        """Ensure remote directory exists and has correct permissions"""
        print("\n🔧 Ensuring remote directory exists...")
        
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
        
        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", remote_cmd]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Remote directory verified")
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"REMOTE DIR: {line}")
            else:
                logger.warning(f"⚠️ Could not ensure remote directory: {result.stderr[:200]}")
                
        except Exception as e:
            logger.warning(f"Could not ensure remote directory: {e}")
    
    def check_repository_exists_on_vps(self) -> Tuple[bool, bool]:
        """Check if repository exists on VPS via SSH"""
        print("\n🔍 Checking if repository exists on VPS...")
        
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
        
        ssh_cmd = ["ssh", f"{self.vps_user}@{self.vps_host}", remote_cmd]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            if result.returncode == 0:
                if "REPO_EXISTS_WITH_PACKAGES" in result.stdout:
                    logger.info("✅ Repository exists on VPS (has package files)")
                    return True, True
                elif "REPO_EXISTS_WITH_DB" in result.stdout:
                    logger.info("✅ Repository exists on VPS (has database)")
                    return True, False
                else:
                    logger.info("ℹ️ Repository does not exist on VPS (first run)")
                    return False, False
            else:
                logger.warning(f"⚠️ Could not check repository existence: {result.stderr[:200]}")
                return False, False
                
        except subprocess.TimeoutExpired:
            logger.error("❌ SSH timeout checking repository existence")
            return False, False
        except Exception as e:
            logger.error(f"❌ Error checking repository: {e}")
            return False, False
    
    def list_remote_packages(self) -> List[str]:
        """List all *.pkg.tar.zst files in the remote repository directory"""
        print("\n" + "=" * 60)
        print("STEP 1: Listing remote repository packages (SSH find)")
        print("=" * 60)
        
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found at {ssh_key_path}")
            return []
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            f"find {self.remote_dir} -maxdepth 1 -type f \\( -name '*.pkg.tar.zst' -o -name '*.pkg.tar.xz' \\) 2>/dev/null || echo 'NO_FILES'"
        ]
        
        logger.info(f"RUNNING SSH COMMAND: {' '.join(ssh_cmd)}")
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.stdout:
                logger.info(f"STDOUT (first 1000 chars): {result.stdout[:1000]}")
            if result.stderr:
                logger.info(f"STDERR: {result.stderr[:500]}")
            
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip() and f.strip() != 'NO_FILES']
                file_count = len(files)
                logger.info(f"✅ SSH find returned {file_count} package files")
                if file_count > 0:
                    print(f"Sample files: {files[:5]}")
                else:
                    logger.info("ℹ️ No package files found on remote server")
                return files
            else:
                logger.warning(f"⚠️ SSH find returned error: {result.stderr[:200]}")
                return []
                
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return []