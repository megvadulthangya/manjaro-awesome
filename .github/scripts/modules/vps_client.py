"""
VPS Client Module - Handles SSH, Rsync, and remote operations
"""

import os
import subprocess
import shutil
import time
import logging
from pathlib import Path
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class VPSClient:
    """Handles SSH, Rsync, and remote VPS operations"""
    
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
    
    def mirror_remote_packages(self, mirror_temp_dir: Path, output_dir: Path) -> bool:
        """
        Download ALL remote package files to local directory
        
        Returns:
            True if successful, False otherwise
        """
        print("\n" + "=" * 60)
        print("MANDATORY STEP: Mirroring remote packages locally")
        print("=" * 60)
        
        # Ensure remote directory exists first
        self.ensure_remote_directory()
        
        # Create a temporary local repository directory
        if mirror_temp_dir.exists():
            shutil.rmtree(mirror_temp_dir, ignore_errors=True)
        mirror_temp_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created local mirror directory: {mirror_temp_dir}")
        
        # Use rsync to download ALL package files from server
        print("📥 Downloading ALL remote package files to local mirror...")
        
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60" \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/*.pkg.tar.*' \
          '{mirror_temp_dir}/' 2>/dev/null || true
        """
        
        logger.info(f"RUNNING RSYNC MIRROR COMMAND:")
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
                for line in result.stdout.splitlines()[-20:]:
                    if line.strip():
                        logger.info(f"RSYNC MIRROR: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip() and "No such file or directory" not in line:
                        logger.error(f"RSYNC MIRROR ERR: {line}")
            
            # List downloaded files
            downloaded_files = list(mirror_temp_dir.glob("*.pkg.tar.*"))
            file_count = len(downloaded_files)
            
            if file_count > 0:
                logger.info(f"✅ Successfully mirrored {file_count} package files ({duration} seconds)")
                logger.info(f"Sample mirrored files: {[f.name for f in downloaded_files[:5]]}")
                
                # Verify file integrity and copy to output directory
                valid_files = []
                for pkg_file in downloaded_files:
                    if pkg_file.stat().st_size > 0:
                        valid_files.append(pkg_file)
                    else:
                        logger.warning(f"⚠️ Empty file: {pkg_file.name}")
                
                logger.info(f"Valid mirrored packages: {len(valid_files)}/{file_count}")
                
                # Copy mirrored packages to output directory
                print(f"📋 Copying {len(valid_files)} mirrored packages to output directory...")
                copied_count = 0
                for pkg_file in valid_files:
                    dest = output_dir / pkg_file.name
                    if not dest.exists():  # Don't overwrite newly built packages
                        shutil.copy2(pkg_file, dest)
                        copied_count += 1
                
                logger.info(f"Copied {copied_count} mirrored packages to output directory")
                
                # Clean up mirror directory
                shutil.rmtree(mirror_temp_dir, ignore_errors=True)
                
                return True
            else:
                logger.info("ℹ️ No package files were mirrored (repository is empty or permission issue)")
                shutil.rmtree(mirror_temp_dir, ignore_errors=True)
                return True
                
        except Exception as e:
            logger.error(f"RSYNC mirror execution error: {e}")
            if mirror_temp_dir.exists():
                shutil.rmtree(mirror_temp_dir, ignore_errors=True)
            return False
    
    def upload_files(self, files_to_upload: List[str], output_dir: Path) -> bool:
        """
        Upload files to server using RSYNC WITHOUT --delete flag
        
        Returns:
            True if successful, False otherwise
        """
        # Ensure remote directory exists first
        self.ensure_remote_directory()
        
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