"""
SSH Client Module
"""
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from modules.common.shell_executor import ShellExecutor

class SSHClient:
    """Handles SSH operations"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, logger: Optional[logging.Logger] = None):
        self.config = config
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
        
        self.vps_user = config.get('vps_user', '')
        self.vps_host = config.get('vps_host', '')
        self.remote_dir = config.get('remote_dir', '')
        self.ssh_key_path = Path("/home/builder/.ssh/id_ed25519")
        
        self._inventory_cache: Optional[Dict[str, str]] = None

    def setup_ssh_config(self, ssh_key: str) -> bool:
        """
        Setup SSH config for builder user.
        If ssh_key is empty/None, assumes the environment is already configured (e.g., SSH Agent).
        """
        # FIX: Do not overwrite config if no key provided. Trust the shell environment.
        if not ssh_key or not ssh_key.strip():
            self.logger.info("No VPS_SSH_KEY provided. Assuming system SSH agent/config is active.")
            return True

        try:
            ssh_dir = Path("/home/builder/.ssh")
            ssh_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            
            if ssh_key:
                with open(self.ssh_key_path, "w") as f:
                    f.write(ssh_key)
                self.ssh_key_path.chmod(0o600)
            
            config_content = f"""Host {self.vps_host}
  HostName {self.vps_host}
  User {self.vps_user}
  IdentityFile {self.ssh_key_path}
  StrictHostKeyChecking no
  ConnectTimeout 30
"""
            with open(ssh_dir / "config", "w") as f:
                f.write(config_content)
            
            return True
        except Exception as e:
            self.logger.error(f"SSH setup failed: {e}")
            return False

    def test_connection(self) -> bool:
        # FIX: Use BatchMode and ConnectTimeout to fail fast if config is wrong
        cmd = f"ssh -o BatchMode=yes -o ConnectTimeout=10 -q {self.vps_host} exit"
        try:
            # We explicitly allow shell=True here to utilize the system's SSH config resolution
            res = self.shell_executor.run(cmd, shell=True, check=False)
            if res.returncode == 0:
                self.logger.info("✅ SSH connection established")
                return True
            else:
                self.logger.error(f"❌ SSH connection failed (Exit Code: {res.returncode})")
                return False
        except Exception as e:
            self.logger.error(f"SSH test exception: {e}")
            return False

    def ensure_directory(self) -> bool:
        cmd = f"ssh -o BatchMode=yes {self.vps_host} 'mkdir -p {self.remote_dir}'"
        res = self.shell_executor.run(cmd, shell=True, check=False)
        return res.returncode == 0

    def get_cached_inventory(self, force_refresh: bool = False) -> Dict[str, str]:
        if self._inventory_cache is not None and not force_refresh:
            return self._inventory_cache
            
        cmd = f"ssh -o BatchMode=yes {self.vps_host} 'ls -1 {self.remote_dir}'"
        try:
            res = self.shell_executor.run(cmd, shell=True, capture=True, check=False)
            files = {}
            if res.returncode == 0 and res.stdout:
                for line in res.stdout.splitlines():
                    name = line.strip()
                    if name:
                        files[name] = f"{self.remote_dir}/{name}"
            self._inventory_cache = files
            return files
        except Exception as e:
            self.logger.error(f"Failed to get inventory: {e}")
            return {}

    def delete_remote_files(self, paths: List[str]) -> bool:
        if not paths: return True
        # Join paths into a space separated string, quoted
        quoted = [f"'{p}'" for p in paths]
        cmd = f"ssh -o BatchMode=yes {self.vps_host} 'rm -f {' '.join(quoted)}'"
        res = self.shell_executor.run(cmd, shell=True, check=False)
        return res.returncode == 0