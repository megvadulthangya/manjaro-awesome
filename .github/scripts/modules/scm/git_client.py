"""
Git Client Module - Handles Git operations
"""

import os
import subprocess
import tempfile
import logging
from pathlib import Path
from modules.common.shell_executor import ShellExecutor

logger = logging.getLogger(__name__)


class GitClient:
    """Handles Git operations for repository management"""
    
    def __init__(self, repo_url: str = None, ssh_options: list = None, debug_mode: bool = False):
        self.repo_url = repo_url
        self.ssh_options = ssh_options or []
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
        self.current_dir = None
    
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
                self.current_dir = target_dir
                return True
            else:
                logger.error(f"❌ Failed to clone repository: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error cloning repository: {e}")
            return False
    
    def clone_with_ssh_key(self, target_dir: str, ssh_key: str, depth: int = 1, repo_url: str = None) -> bool:
        """
        Clone repository using provided SSH key
        
        Args:
            target_dir: Directory to clone into
            ssh_key: SSH private key content
            depth: Clone depth
            repo_url: Repository URL (uses self.repo_url if None)
            
        Returns:
            True if successful, False otherwise
        """
        url = repo_url or self.repo_url
        if not url:
            logger.error("No repository URL provided")
            return False
        
        # Create temporary SSH key file
        ssh_dir = Path("/tmp/git_ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)
        ssh_key_path = ssh_dir / "id_ed25519"
        
        try:
            # Write SSH key
            with open(ssh_key_path, 'w') as f:
                f.write(ssh_key)
            ssh_key_path.chmod(0o600)
            
            # Create SSH command with key
            ssh_cmd = f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=no -o ConnectTimeout=30"
            
            # Clone using SSH key
            cmd = f"git -c core.sshCommand='{ssh_cmd}' clone --depth {depth} {url} {target_dir}"
            
            logger.info("SHELL_EXECUTOR_USED=1")
            result = self.shell_executor.run_command(cmd, capture=True, check=False)
            
            if result.returncode == 0:
                logger.info(f"✅ Successfully cloned repository with SSH key to {target_dir}")
                self.current_dir = target_dir
                return True
            else:
                logger.error(f"❌ Failed to clone repository with SSH key: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error cloning repository with SSH key: {e}")
            return False
        finally:
            # Cleanup SSH key file
            try:
                if ssh_key_path.exists():
                    ssh_key_path.unlink()
            except Exception:
                pass
    
    def set_ssh_command(self, ssh_command: str) -> bool:
        """
        Set SSH command for Git operations
        
        Args:
            ssh_command: SSH command string
            
        Returns:
            True if successful, False otherwise
        """
        if not self.current_dir:
            logger.error("No repository directory set")
            return False
        
        cmd = f"git -C {self.current_dir} config core.sshCommand '{ssh_command}'"
        
        logger.info("SHELL_EXECUTOR_USED=1")
        try:
            result = self.shell_executor.run_command(cmd, capture=True, check=False)
            if result.returncode == 0:
                logger.info("✅ Set SSH command for Git")
                return True
            else:
                logger.error(f"❌ Failed to set SSH command: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error setting SSH command: {e}")
            return False
    
    def add_files(self, file_pattern: str = ".") -> bool:
        """
        Add files to Git staging
        
        Args:
            file_pattern: File pattern to add (default: all files)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.current_dir:
            logger.error("No repository directory set")
            return False
        
        cmd = f"git -C {self.current_dir} add {file_pattern}"
        
        logger.info("SHELL_EXECUTOR_USED=1")
        try:
            result = self.shell_executor.run_command(cmd, capture=True, check=False)
            if result.returncode == 0:
                logger.info(f"✅ Added files: {file_pattern}")
                return True
            else:
                logger.error(f"❌ Failed to add files: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error adding files: {e}")
            return False
    
    def commit(self, message: str) -> bool:
        """
        Commit staged changes
        
        Args:
            message: Commit message
            
        Returns:
            True if successful, False otherwise
        """
        if not self.current_dir:
            logger.error("No repository directory set")
            return False
        
        # Escape quotes in message
        message = message.replace("'", "'\"'\"'")
        cmd = f"git -C {self.current_dir} commit -m '{message}'"
        
        logger.info("SHELL_EXECUTOR_USED=1")
        try:
            result = self.shell_executor.run_command(cmd, capture=True, check=False)
            if result.returncode == 0:
                logger.info(f"✅ Committed changes: {message[:50]}...")
                return True
            elif "nothing to commit" in result.stderr:
                logger.info("ℹ️ Nothing to commit")
                return False
            else:
                logger.error(f"❌ Failed to commit: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error committing: {e}")
            return False
    
    def push(self) -> bool:
        """
        Push changes to remote repository
        
        Returns:
            True if successful, False otherwise
        """
        if not self.current_dir:
            logger.error("No repository directory set")
            return False
        
        cmd = f"git -C {self.current_dir} push"
        
        logger.info("SHELL_EXECUTOR_USED=1")
        try:
            result = self.shell_executor.run_command(cmd, capture=True, check=False)
            if result.returncode == 0:
                logger.info("✅ Pushed changes to remote")
                return True
            else:
                logger.error(f"❌ Failed to push: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"❌ Error pushing: {e}")
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