"""
Git and SSH synchronization module for Manjaro Package Builder
Extracted from package_builder.py monolith for temporary clone management
"""

import os
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime

from modules.common.shell_executor import ShellExecutor


class GitSyncManager:
    """Manages Git and SSH operations for temporary repository clones"""
    
    def __init__(self, shell_executor: Optional[ShellExecutor] = None,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize GitSyncManager
        
        Args:
            shell_executor: ShellExecutor instance for command execution
            logger: Optional logger instance
        """
        self.shell_executor = shell_executor or ShellExecutor()
        self.logger = logger or logging.getLogger(__name__)
        
        # State management
        self._temp_clone_dir: Optional[Path] = None
        self._build_tracking_dir: Optional[Path] = None
        self._git_ssh_temp_key: Optional[Path] = None
        self._git_ssh_env: Optional[Dict[str, str]] = None
        self._ssh_repo_url: Optional[str] = None
        self._packager_identity: Optional[str] = None
        
    def setup_temp_clone(self, config: Dict, ssh_key: str) -> bool:
        """
        Set up temporary repository clone with SSH authentication
        
        Args:
            config: Configuration dictionary containing:
                - ssh_repo_url: SSH URL for Git repository
                - sync_clone_dir: Base directory for clones (defaults to /tmp/manjaro-awesome-gitclone)
                - packager_env: Packager identity for Git commits
            ssh_key: SSH private key content for authentication
        
        Returns:
            True if successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("GIT SYNC: Setting up temporary repository clone")
        self.logger.info("=" * 60)
        
        # Extract configuration
        self._ssh_repo_url = config.get('ssh_repo_url', 'git@github.com:megvadulthangya/manjaro-awesome.git')
        self._packager_identity = config.get('packager_env', 'Maintainer <no-reply@gshoots.hu>')
        
        # Setup Git SSH authentication
        if not self._setup_git_ssh(ssh_key):
            self.logger.error("❌ Failed to setup Git SSH authentication")
            return False
        
        # Get clone directory from config
        clone_dir_config = config.get('sync_clone_dir', '/tmp/manjaro-awesome-gitclone')
        
        # Add timestamp for uniqueness
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._temp_clone_dir = Path(f"{clone_dir_config}-{timestamp}")
        
        # Clean up existing temp clone if exists
        if self._temp_clone_dir.exists():
            self.logger.info("🧹 Cleaning existing temporary clone...")
            try:
                shutil.rmtree(self._temp_clone_dir, ignore_errors=True)
                self.logger.info("✅ Existing clone removed")
            except Exception as e:
                self.logger.error(f"Failed to remove existing clone: {e}")
                return False
        
        self.logger.info(f"📥 Cloning repository from {self._ssh_repo_url}...")
        self.logger.info(f"Clone directory: {self._temp_clone_dir}")
        
        try:
            # Use git command directly with SSH environment
            clone_cmd = [
                'git', 'clone',
                '--depth', '1',
                self._ssh_repo_url,
                str(self._temp_clone_dir)
            ]
            
            # Run git clone with SSH environment
            result = subprocess.run(
                clone_cmd,
                env=self._git_ssh_env,
                capture_output=True,
                text=True,
                timeout=300,
                check=False
            )
            
            if result.returncode == 0:
                self.logger.info(f"✅ Repository cloned to {self._temp_clone_dir}")
                
                # Verify clone integrity
                git_dir = self._temp_clone_dir / ".git"
                if not git_dir.exists():
                    self.logger.error("❌ Git directory not found after clone")
                    return False
                
                # Setup build tracking directory in temp clone
                self._build_tracking_dir = self._temp_clone_dir / ".build_tracking"
                self._build_tracking_dir.mkdir(exist_ok=True)
                
                self.logger.info(f"📁 Build tracking directory: {self._build_tracking_dir}")
                
                # Configure git user for commits
                self._configure_git_identity()
                
                return True
            else:
                self.logger.error(f"❌ Failed to clone repository (exit code: {result.returncode})")
                if result.stderr:
                    self.logger.error(f"Error: {result.stderr[:500]}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("❌ Git clone timed out after 5 minutes")
            return False
        except Exception as e:
            self.logger.error(f"❌ Clone operation failed: {e}")
            return False
    
    def _setup_git_ssh(self, ssh_key: str) -> bool:
        """
        Setup Git SSH authentication using provided SSH key
        
        Args:
            ssh_key: SSH private key content
        
        Returns:
            True if successful
        """
        if not ssh_key:
            self.logger.error("❌ SSH key not provided")
            return False
        
        try:
            # Create temporary directory for SSH key
            temp_ssh_dir = Path(tempfile.mkdtemp(prefix="git_ssh_"))
            self._git_ssh_temp_key = temp_ssh_dir / "id_ed25519"
            
            # Write SSH key to file
            with open(self._git_ssh_temp_key, 'w') as f:
                f.write(ssh_key)
            
            # Set proper permissions
            self._git_ssh_temp_key.chmod(0o600)
            
            # Create known_hosts with github.com key
            known_hosts = temp_ssh_dir / "known_hosts"
            ssh_keyscan_cmd = [
                "ssh-keyscan",
                "-t", "ed25519",
                "github.com"
            ]
            
            result = subprocess.run(
                ssh_keyscan_cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            if result.returncode == 0 and result.stdout:
                with open(known_hosts, 'w') as f:
                    f.write(result.stdout)
                known_hosts.chmod(0o644)
            else:
                # Fallback: accept host key without verification
                with open(known_hosts, 'w') as f:
                    f.write("github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl")
            
            # Create Git SSH command
            git_ssh_cmd = (
                f"ssh -o IdentitiesOnly=yes "
                f"-o IdentityFile={self._git_ssh_temp_key} "
                f"-o UserKnownHostsFile={known_hosts} "
                f"-o StrictHostKeyChecking=yes "
                f"-o ConnectTimeout=30"
            )
            
            self._git_ssh_env = os.environ.copy()
            self._git_ssh_env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
            self.logger.info("✅ Git SSH authentication configured")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to setup Git SSH: {e}")
            return False
    
    def _configure_git_identity(self):
        """Configure git user identity for commits"""
        if not self._temp_clone_dir or not self._temp_clone_dir.exists():
            return
        
        try:
            # Extract email from packager identity
            email = "no-reply@gshoots.hu"
            if '<' in self._packager_identity and '>' in self._packager_identity:
                # Extract email from format: "Maintainer <no-reply@gshoots.hu>"
                email_part = self._packager_identity.split('<')[1].split('>')[0]
                if '@' in email_part:
                    email = email_part
            
            # Configure git user
            subprocess.run(
                ['git', 'config', 'user.email', email],
                cwd=self._temp_clone_dir,
                capture_output=True,
                check=False
            )
            
            subprocess.run(
                ['git', 'config', 'user.name', 'Manjaro Awesome Builder'],
                cwd=self._temp_clone_dir,
                capture_output=True,
                check=False
            )
            
            self.logger.info("✅ Git identity configured")
            
        except Exception as e:
            self.logger.warning(f"Could not configure git identity: {e}")
    
    def commit_changes(self, changes_dict: Optional[Dict] = None) -> bool:
        """
        Commit changes in temporary clone
        
        Args:
            changes_dict: Dictionary of changes (optional, for future use)
        
        Returns:
            True if successful
        """
        if not self._temp_clone_dir:
            self.logger.error("Temporary clone not set up")
            return False
        
        if not self._git_ssh_env:
            self.logger.error("Git SSH environment not configured")
            return False
        
        self.logger.info("\n" + "=" * 60)
        self.logger.info("GIT: Committing changes")
        self.logger.info("=" * 60)
        
        old_cwd = os.getcwd()
        os.chdir(self._temp_clone_dir)
        
        try:
            # Check if there are any changes
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                env=self._git_ssh_env,
                capture_output=True,
                text=True,
                check=False
            )
            
            if status_result.returncode != 0:
                self.logger.error(f"Git status failed: {status_result.stderr}")
                return False
            
            if not status_result.stdout.strip():
                self.logger.info("ℹ️ No changes to commit")
                return True
            
            self.logger.info("📋 Changes detected:")
            for line in status_result.stdout.strip().splitlines():
                self.logger.info(f"  {line}")
            
            # Add all changes including build tracking
            self.logger.info("➕ Adding changes...")
            add_result = subprocess.run(
                ['git', 'add', '.'],
                env=self._git_ssh_env,
                capture_output=True,
                text=True,
                check=False
            )
            
            if add_result.returncode != 0:
                self.logger.error(f"Git add failed: {add_result.stderr}")
                return False
            
            # Commit changes
            commit_message = f"update: Packages built {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.logger.info(f"💾 Committing: {commit_message}")
            
            commit_result = subprocess.run(
                ['git', 'commit', '-m', commit_message],
                env=self._git_ssh_env,
                capture_output=True,
                text=True,
                check=False
            )
            
            if commit_result.returncode != 0:
                self.logger.error(f"Git commit failed: {commit_result.stderr}")
                # Check if it's just an empty commit
                if "nothing to commit" not in commit_result.stderr.lower():
                    return False
                self.logger.info("ℹ️ No changes to commit")
                return True
            
            self.logger.info("✅ Changes committed successfully")
            return True
                
        except Exception as e:
            self.logger.error(f"Git commit operation failed: {e}")
            return False
        finally:
            os.chdir(old_cwd)
    
    def push_changes(self) -> bool:
        """
        Push committed changes to remote repository
        
        Returns:
            True if successful
        """
        if not self._temp_clone_dir:
            self.logger.error("Temporary clone not set up")
            return False
        
        if not self._git_ssh_env:
            self.logger.error("Git SSH environment not configured")
            return False
        
        self.logger.info("\n📤 Pushing to remote...")
        
        old_cwd = os.getcwd()
        os.chdir(self._temp_clone_dir)
        
        try:
            # Check if we have commits to push
            status_result = subprocess.run(
                ['git', 'status', '--porcelain', '-b'],
                env=self._git_ssh_env,
                capture_output=True,
                text=True,
                check=False
            )
            
            if "ahead" not in status_result.stdout:
                self.logger.info("ℹ️ No commits to push (already up-to-date)")
                return True
            
            # Push changes to main branch
            self.logger.info("📤 Pushing to remote...")
            push_result = subprocess.run(
                ['git', 'push', 'origin', 'main'],
                env=self._git_ssh_env,
                capture_output=True,
                text=True,
                check=False,
                timeout=300
            )
            
            if push_result.returncode == 0:
                self.logger.info("✅ Changes pushed successfully")
                return True
            else:
                self.logger.error(f"Git push failed: {push_result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self.logger.error("❌ Git push timed out after 5 minutes")
            return False
        except Exception as e:
            self.logger.error(f"Git push operation failed: {e}")
            return False
        finally:
            os.chdir(old_cwd)
    
    def cleanup(self):
        """Clean up temporary clone and SSH key"""
        self._cleanup_temp_clone()
        self._cleanup_git_ssh()
    
    def _cleanup_temp_clone(self):
        """Clean up temporary clone directory"""
        if self._temp_clone_dir and self._temp_clone_dir.exists():
            try:
                shutil.rmtree(self._temp_clone_dir, ignore_errors=True)
                self.logger.debug(f"🧹 Cleaned up temporary clone: {self._temp_clone_dir}")
                self._temp_clone_dir = None
                self._build_tracking_dir = None
            except Exception as e:
                self.logger.warning(f"Could not clean temporary clone: {e}")
    
    def _cleanup_git_ssh(self):
        """Clean up temporary Git SSH key"""
        if self._git_ssh_temp_key and self._git_ssh_temp_key.exists():
            try:
                temp_dir = self._git_ssh_temp_key.parent
                shutil.rmtree(temp_dir, ignore_errors=True)
                self._git_ssh_temp_key = None
                self._git_ssh_env = None
                self.logger.debug("🧹 Cleaned up Git SSH temporary files")
            except Exception as e:
                self.logger.warning(f"Failed to cleanup Git SSH: {e}")
    
    @property
    def temp_clone_dir(self) -> Optional[Path]:
        """Get the temporary clone directory"""
        return self._temp_clone_dir
    
    @property
    def build_tracking_dir(self) -> Optional[Path]:
        """Get the build tracking directory"""
        return self._build_tracking_dir
    
    @property
    def git_ssh_env(self) -> Optional[Dict[str, str]]:
        """Get the Git SSH environment"""
        return self._git_ssh_env
    
    def get_file_list(self, pattern: str = "*") -> List[Path]:
        """
        Get list of files in temporary clone matching pattern
        
        Args:
            pattern: Glob pattern to match
        
        Returns:
            List of matching file paths
        """
        if not self._temp_clone_dir or not self._temp_clone_dir.exists():
            return []
        
        return list(self._temp_clone_dir.rglob(pattern))
    
    def copy_file_to_temp_clone(self, source: Path, relative_dest: Path) -> bool:
        """
        Copy a file to the temporary clone directory
        
        Args:
            source: Source file path
            relative_dest: Destination path relative to temp clone
        
        Returns:
            True if successful
        """
        if not self._temp_clone_dir or not self._temp_clone_dir.exists():
            self.logger.error("Temporary clone not set up")
            return False
        
        if not source.exists():
            self.logger.error(f"Source file does not exist: {source}")
            return False
        
        dest_path = self._temp_clone_dir / relative_dest
        
        try:
            # Create parent directories if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy the file
            shutil.copy2(source, dest_path)
            self.logger.debug(f"Copied {source} to {dest_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to copy file {source}: {e}")
            return False