"""
SSH client for remote operations
"""

import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class SSHClient:
    """Handles SSH operations to VPS"""
    
    def __init__(self, config):
        self.config = config
        self.debug_mode = config.get('debug_mode', False)
        
        # Setup SSH key
        self._setup_ssh_key()
    
    def _setup_ssh_key(self):
        """Setup SSH key for authentication"""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)
        
        # Write SSH config
        config_content = f"""Host {self.config['vps_host']}
  HostName {self.config['vps_host']}
  User {self.config['vps_user']}
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
        
        # Write SSH key
        ssh_key = self.config.get('ssh_key', '')
        if ssh_key:
            ssh_key_path = ssh_dir / "id_ed25519"
            with open(ssh_key_path, "w") as f:
                f.write(ssh_key)
            ssh_key_path.chmod(0o600)
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] SSH setup complete", flush=True)
        else:
            logger.info("SSH setup complete")
    
    def execute_command(self, command):
        """Execute command on remote VPS"""
        ssh_cmd = [
            "ssh",
            f"{self.config['vps_user']}@{self.config['vps_host']}",
            command
        ]
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] Executing remote command: {command}", flush=True)
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Command executed successfully", flush=True)
                else:
                    logger.info("Command executed successfully")
                return result.stdout
            else:
                if self.debug_mode:
                    print(f"❌ [DEBUG] Command failed: {result.stderr}", flush=True)
                else:
                    logger.error(f"Command failed: {result.stderr}")
                return None
                
        except Exception as e:
            if self.debug_mode:
                print(f"❌ [DEBUG] SSH execution error: {e}", flush=True)
            else:
                logger.error(f"SSH execution error: {e}")
            return None