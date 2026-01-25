#!/usr/bin/env python3
"""
VPS Client Module - Handles SSH, remote execution, state syncing with Zero-Download Policy
STRICT PATH COMPLIANCE: Uses /tmp/{repo_name}_build_temp/.build_tracking for state files
"""

import os
import subprocess
import json
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class VPSClient:
    """Handles SSH, Rsync, and remote VPS operations with Zero-Download Policy"""
    
    def __init__(self, config: dict):
        """
        Initialize VPSClient with configuration
        
        Args:
            config: Dictionary containing:
                - vps_user: VPS username
                - vps_host: VPS hostname
                - ssh_key: SSH private key content
                - remote_dir: Remote directory on VPS
                - ssh_options: SSH options list
                - state_tracking_dir: Path to state tracking directory (MANDATORY)
        """
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        self.ssh_key = config.get('ssh_key')
        self.remote_dir = config['remote_dir']
        self.ssh_options = config.get('ssh_options', [])
        self.state_tracking_dir = Path(config['state_tracking_dir'])
        
        # State file location (STRICT REQUIREMENT)
        self.state_file = self.state_tracking_dir / "vps_state.json"
        
        # Ensure state tracking directory exists
        self.state_tracking_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup SSH
        self.setup_ssh_config()
    
    def extract_repo_name_from_url(self, ssh_repo_url: str) -> str:
        """
        Parse config.SSH_REPO_URL to extract repo name
        
        Args:
            ssh_repo_url: Git SSH URL (e.g., git@github.com:user/my-repo.git)
        
        Returns:
            Repository name (e.g., my-repo)
        """
        # Remove trailing slashes and .git suffix
        url = ssh_repo_url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        
        # Extract repo name after last slash
        repo_name = url.split('/')[-1]
        
        # Handle git@github.com:user/repo format
        if ':' in repo_name:
            repo_name = repo_name.split(':')[-1]
        
        logger.info(f"Extracted repo name '{repo_name}' from URL '{ssh_repo_url}'")
        return repo_name
    
    def setup_ssh_config(self):
        """Setup SSH config file for builder user"""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)
        
        # Write SSH key
        if self.ssh_key:
            key_path = ssh_dir / "id_ed25519"
            with open(key_path, "w") as f:
                f.write(self.ssh_key)
            key_path.chmod(0o600)
            
            # Set ownership
            try:
                shutil.chown(ssh_dir, "builder", "builder")
                for item in ssh_dir.iterdir():
                    shutil.chown(item, "builder", "builder")
            except Exception as e:
                logger.warning(f"Could not change SSH dir ownership: {e}")
        
        # Write SSH config
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
    
    def test_ssh_connection(self) -> bool:
        """Test SSH connection to VPS"""
        ssh_test_cmd = [
            "ssh", *self.ssh_options,
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]
        
        try:
            result = subprocess.run(
                ssh_test_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=10
            )
            return result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout
        except Exception as e:
            logger.error(f"SSH connection test failed: {e}")
            return False
    
    def ensure_remote_directory(self):
        """Ensure remote directory exists with correct permissions"""
        remote_cmd = f"""
        if [ ! -d "{self.remote_dir}" ]; then
            sudo mkdir -p "{self.remote_dir}"
            sudo chown -R {self.vps_user}:www-data "{self.remote_dir}"
            sudo chmod -R 755 "{self.remote_dir}"
        else
            sudo chown -R {self.vps_user}:www-data "{self.remote_dir}"
            sudo chmod -R 755 "{self.remote_dir}"
        fi
        """
        
        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", remote_cmd]
        
        try:
            subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
            logger.info("✅ Remote directory verified")
        except Exception as e:
            logger.error(f"❌ Could not ensure remote directory: {e}")
    
    def download_state_file(self) -> Optional[Dict]:
        """
        ZERO-DOWNLOAD POLICY: Step 1 - Try to download vps_state.json
        
        Returns:
            State dict if downloaded, None if file doesn't exist on VPS
        """
        logger.info("🔍 Step 1: Trying to download vps_state.json from VPS...")
        
        remote_state_path = f"{self.remote_dir}/vps_state.json"
        
        # Check if file exists on VPS
        check_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", 
                    f"test -f {remote_state_path} && echo 'EXISTS' || echo 'NOT_EXISTS'"]
        
        try:
            result = subprocess.run(
                check_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=10
            )
            
            if result.returncode == 0 and "EXISTS" in result.stdout:
                # File exists, download it
                logger.info("✅ vps_state.json exists on VPS, downloading...")
                scp_cmd = [
                    "scp", *self.ssh_options,
                    f"{self.vps_user}@{self.vps_host}:{remote_state_path}",
                    str(self.state_file)
                ]
                
                subprocess.run(scp_cmd, capture_output=True, text=True, check=False)
                
                if self.state_file.exists():
                    with open(self.state_file, 'r') as f:
                        state = json.load(f)
                    logger.info(f"✅ Downloaded state file with {len(state.get('packages', []))} packages")
                    return state
                else:
                    logger.error("❌ Downloaded file not found locally")
                    return None
            else:
                # ZERO-DOWNLOAD POLICY: File doesn't exist, DO NOT download .pkg files
                logger.info("ℹ️ vps_state.json not found on VPS (first run or reset)")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error checking/downloading state file: {e}")
            return None
    
    def generate_new_state_file(self) -> Dict:
        """
        ZERO-DOWNLOAD POLICY: Step 2 - Generate new state file without downloading .pkg files
        
        Executes remote SSH command to list packages and creates state file locally
        """
        logger.info("🔧 Step 2: Generating new state file from remote package list...")
        
        # Execute remote find command to get package list (NO DOWNLOAD)
        find_cmd = f'find "{self.remote_dir}" -maxdepth 1 -type f -name "*.pkg.tar.zst" -exec basename {{}} \\; 2>/dev/null'
        
        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", find_cmd]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            packages = []
            if result.returncode == 0:
                package_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
                logger.info(f"Found {len(package_files)} package files on VPS")
                
                # Create state data
                for pkg_file in package_files:
                    # Extract package name and version from filename
                    # Format: package-name-version-release-arch.pkg.tar.zst
                    parts = pkg_file.replace('.pkg.tar.zst', '').split('-')
                    if len(parts) >= 4:
                        # Find where version starts (package name can have hyphens)
                        for i in range(len(parts) - 3, 0, -1):
                            potential_name = '-'.join(parts[:i])
                            version_part = parts[i]
                            release_part = parts[i+1]
                            
                            # Check if this looks like a version
                            if any(c.isdigit() for c in version_part) and release_part.isdigit():
                                packages.append({
                                    "filename": pkg_file,
                                    "name": potential_name,
                                    "version": f"{version_part}-{release_part}",
                                    "remote_path": f"{self.remote_dir}/{pkg_file}"
                                })
                                break
            
            state = {
                "generated_at": str(subprocess.check_output(["date", "-Iseconds"]).decode().strip()),
                "vps_host": self.vps_host,
                "remote_dir": self.remote_dir,
                "packages": packages
            }
            
            # Save locally to State Tracking Directory (STRICT REQUIREMENT)
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
            
            logger.info(f"✅ Created new state file with {len(packages)} packages")
            return state
            
        except Exception as e:
            logger.error(f"❌ Error generating state file: {e}")
            # Return empty state on error
            return {"generated_at": "error", "packages": []}
    
    def upload_state_file(self) -> bool:
        """Upload the locally created state file to VPS"""
        if not self.state_file.exists():
            logger.error("❌ No local state file to upload")
            return False
        
        scp_cmd = [
            "scp", *self.ssh_options,
            str(self.state_file),
            f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/vps_state.json"
        ]
        
        try:
            result = subprocess.run(
                scp_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            if result.returncode == 0:
                logger.info("✅ Uploaded vps_state.json to VPS")
                return True
            else:
                logger.error(f"❌ Failed to upload state file: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error uploading state file: {e}")
            return False
    
    def get_vps_state(self) -> Dict:
        """
        ZERO-DOWNLOAD POLICY: Complete workflow for getting VPS state
        
        Returns:
            State dictionary (either downloaded or newly generated)
        """
        # Step 1: Try to download existing state
        state = self.download_state_file()
        
        if state is not None:
            return state
        
        # Step 2: Generate new state from remote package list (NO .pkg download)
        state = self.generate_new_state_file()
        
        # Step 3: Upload new state to establish baseline
        if self.upload_state_file():
            logger.info("✅ Baseline state established on VPS")
        else:
            logger.warning("⚠️ Could not upload state file to VPS")
        
        return state
    
    def execute_remote_command(self, command: str, timeout: int = 60) -> Tuple[bool, str]:
        """Execute a command on the remote VPS via SSH"""
        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", command]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout
            )
            
            success = result.returncode == 0
            output = result.stdout if success else result.stderr
            
            return success, output
        except subprocess.TimeoutExpired:
            return False, "Command timed out"
        except Exception as e:
            return False, str(e)
    
    def upload_files(self, files: List[str], local_base_dir: Path) -> bool:
        """Upload files to VPS using rsync (without --delete)"""
        if not files:
            logger.warning("No files to upload")
            return False
        
        # Ensure remote directory exists
        self.ensure_remote_directory()
        
        # Build file list for rsync
        file_args = []
        for file_path in files:
            file_path_obj = Path(file_path)
            if file_path_obj.is_absolute():
                file_args.append(str(file_path_obj))
            else:
                file_args.append(str(local_base_dir / file_path))
        
        # Rsync command WITHOUT --delete
        rsync_cmd = [
            "rsync", "-avz",
            "--progress",
            *file_args,
            f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/"
        ]
        
        logger.info(f"Uploading {len(files)} files to VPS...")
        
        try:
            result = subprocess.run(
                rsync_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300
            )
            
            if result.returncode == 0:
                logger.info("✅ Files uploaded successfully")
                return True
            else:
                logger.error(f"❌ Rsync failed: {result.stderr[:500]}")
                return False
        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
            return False
    
    def list_remote_packages(self) -> List[str]:
        """List package files on remote VPS"""
        find_cmd = f'find "{self.remote_dir}" -maxdepth 1 -type f \\( -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" \\) -exec basename {{}} \\; 2>/dev/null'
        
        success, output = self.execute_remote_command(find_cmd)
        
        if success and output:
            return [line.strip() for line in output.split('\n') if line.strip()]
        return []