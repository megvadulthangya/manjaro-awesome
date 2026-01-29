"""
Git client for repository synchronization and operations
Relies on system SSH agent/environment for authentication.
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any

from modules.common.shell_executor import ShellExecutor

class GitClient:
    """Handles Git operations relying on system authentication"""

    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, logger: Optional[logging.Logger] = None):
        """
        Initialize GitClient

        Args:
            config: Configuration dictionary
            shell_executor: ShellExecutor instance
            logger: Optional logger instance
        """
        self.config = config
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)

        self.repo_url = config.get('ssh_repo_url', '')
        self.clone_dir = Path(config.get('sync_clone_dir', '/tmp/manjaro-awesome-gitclone'))
        self.packager_env = config.get('packager_env', 'Maintainer <no-reply@gshoots.hu>')

    def setup_ssh(self) -> bool:
        """
        No-op: Relies on system SSH agent and environment variables.
        """
        self.logger.info("Using system SSH agent/environment for Git authentication")
        return True

    def cleanup_ssh(self):
        """
        No-op: No temporary keys to clean up.
        """
        pass

    def clone_repo(self) -> bool:
        """
        Clone the repository using system authentication
        
        Returns:
            True if successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("GIT SYNC: Cloning repository")
        self.logger.info("=" * 60)
        
        # Clean up existing temp clone if exists
        if self.clone_dir.exists():
            self.logger.info("🧹 Cleaning existing temporary clone...")
            try:
                shutil.rmtree(self.clone_dir, ignore_errors=True)
                self.logger.info("✅ Existing clone removed")
            except Exception as e:
                self.logger.error(f"Failed to remove existing clone: {e}")
                return False
        
        self.logger.info(f"📥 Cloning repository from {self.repo_url}...")
        self.logger.info(f"Clone directory: {self.clone_dir}")
        
        try:
            # Use git command directly with system environment
            clone_cmd = [
                'git', 'clone',
                '--depth', '1',
                self.repo_url,
                str(self.clone_dir)
            ]
            
            # Run git clone inheriting os.environ
            result = subprocess.run(
                clone_cmd,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=300,
                check=False
            )
            
            if result.returncode == 0:
                self.logger.info(f"✅ Repository cloned to {self.clone_dir}")
                
                # Verify clone integrity
                git_dir = self.clone_dir / ".git"
                if not git_dir.exists():
                    self.logger.error("❌ Git directory not found after clone")
                    return False
                
                # Configure git user for commits
                self.configure_identity()
                
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

    def configure_identity(self):
        """Configure git user identity for commits"""
        if not self.clone_dir or not self.clone_dir.exists():
            return
        
        try:
            # Configure git user
            subprocess.run(
                ['git', 'config', 'user.email', 'no-reply@gshoots.hu'],
                cwd=self.clone_dir,
                capture_output=True,
                check=False
            )
            
            subprocess.run(
                ['git', 'config', 'user.name', 'Manjaro Awesome Builder'],
                cwd=self.clone_dir,
                capture_output=True,
                check=False
            )
            
            self.logger.info("✅ Git identity configured")
            
        except Exception as e:
            self.logger.warning(f"Could not configure git identity: {e}")

    def commit_and_push(self) -> bool:
        """
        Commit and push changes from temporary clone
        
        Returns:
            True if successful
        """
        if not self.clone_dir or not self.clone_dir.exists():
            self.logger.error("Temporary clone not set up")
            return False
        
        self.logger.info("\n" + "=" * 60)
        self.logger.info("GIT: Committing and pushing changes")
        self.logger.info("=" * 60)
        
        old_cwd = os.getcwd()
        os.chdir(self.clone_dir)
        
        try:
            # Check if there are any changes
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                env=os.environ.copy(),
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
            
            # Add all changes
            self.logger.info("➕ Adding changes...")
            add_result = subprocess.run(
                ['git', 'add', '.'],
                env=os.environ.copy(),
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
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                check=False
            )
            
            if commit_result.returncode != 0:
                self.logger.error(f"Git commit failed: {commit_result.stderr}")
                if "nothing to commit" not in commit_result.stderr.lower():
                    return False
                self.logger.info("ℹ️ No changes to commit")
                return True
            
            # Push changes
            self.logger.info("📤 Pushing to remote...")
            push_result = subprocess.run(
                ['git', 'push', 'origin', 'main'],
                env=os.environ.copy(),
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
            self.logger.error(f"Git operation failed: {e}")
            return False
        finally:
            os.chdir(old_cwd)