"""
Git Client Module - Handles Git operations
"""

import subprocess
import logging

logger = logging.getLogger(__name__)


class GitClient:
    """Handles Git operations for repository management"""
    
    def __init__(self, repo_url: str, ssh_options: list = None):
        self.repo_url = repo_url
        self.ssh_options = ssh_options or []
    
    def clone_repository(self, target_dir: str, depth: int = 1) -> bool:
        """Clone a Git repository"""
        cmd = ["git", "clone", "--depth", str(depth)]
        
        # Add SSH options if provided
        if self.ssh_options:
            ssh_cmd = " ".join(self.ssh_options)
            cmd.extend(["-c", f"core.sshCommand=ssh {ssh_cmd}"])
        
        cmd.extend([self.repo_url, target_dir])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                logger.info(f"✅ Successfully cloned repository to {target_dir}")
                return True
            else:
                logger.error(f"❌ Failed to clone repository: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error cloning repository: {e}")
            return False
    
    def pull_latest(self, repo_dir: str) -> bool:
        """Pull latest changes from remote repository"""
        cmd = ["git", "-C", repo_dir, "pull"]
        
        # Add SSH options if provided
        if self.ssh_options:
            ssh_cmd = " ".join(self.ssh_options)
            cmd.extend(["-c", f"core.sshCommand=ssh {ssh_cmd}"])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                logger.info("✅ Successfully pulled latest changes")
                return True
            else:
                logger.error(f"❌ Failed to pull latest changes: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error pulling latest changes: {e}")
            return False