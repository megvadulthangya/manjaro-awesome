"""
Git Client Module - Handles Git operations
"""

import subprocess
import logging
from modules.common.shell_executor import ShellExecutor

logger = logging.getLogger(__name__)


class GitClient:
    """Handles Git operations for repository management"""
    
    def __init__(self, repo_url: str = None, ssh_options: list = None, debug_mode: bool = False):
        self.repo_url = repo_url
        self.ssh_options = ssh_options or []
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
    
    def clone_repository(self, target_dir: str, depth: int = 1, repo_url: str = None) -> bool:
        """Clone a Git repository"""
        url = repo_url or self.repo_url
        if not url:
            logger.error("No repository URL provided")
            return False
        
        cmd = ["git", "clone", "--depth", str(depth), url, target_dir]
        
        # Add SSH options if provided
        if self.ssh_options:
            ssh_cmd = " ".join(self.ssh_options)
            cmd_str = f"git -c core.sshCommand='ssh {ssh_cmd}' clone --depth {depth} {url} {target_dir}"
        else:
            cmd_str = f"git clone --depth {depth} {url} {target_dir}"
        
        logger.info("SHELL_EXECUTOR_USED=1")
        try:
            result = self.shell_executor.run_command(cmd_str, capture=True, check=False)
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
        cmd = f"git -C {repo_dir} pull"
        
        # Add SSH options if provided
        if self.ssh_options:
            ssh_cmd = " ".join(self.ssh_options)
            cmd = f"git -c core.sshCommand='ssh {ssh_cmd}' -C {repo_dir} pull"
        
        logger.info("SHELL_EXECUTOR_USED=1")
        try:
            result = self.shell_executor.run_command(cmd, capture=True, check=False)
            if result.returncode == 0:
                logger.info("✅ Successfully pulled latest changes")
                return True
            else:
                logger.error(f"❌ Failed to pull latest changes: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error pulling latest changes: {e}")
            return False
