#!/usr/bin/env python3
"""
Repository Manager Module - Handles paths, cloning, regex updates with strict directory specs
STRICT PATH COMPLIANCE: Uses /tmp/{repo_name}_build_temp/git_workflow for cloning
"""

import os
import re
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RepoManager:
    """Manages repository operations, cloning, and PKGBUILD updates with strict paths"""
    
    def __init__(self, config: dict):
        """
        Initialize RepoManager with configuration
        
        Args:
            config: Dictionary containing:
                - ssh_repo_url: Git SSH URL (e.g., git@github.com:user/my-repo.git)
                - base_temp_dir: Base temporary directory path
                - git_workflow_dir: Git workflow directory path
                - state_tracking_dir: State tracking directory path
        """
        self.ssh_repo_url = config['ssh_repo_url']
        self.base_temp_dir = Path(config['base_temp_dir'])
        self.git_workflow_dir = Path(config['git_workflow_dir'])
        self.state_tracking_dir = Path(config['state_tracking_dir'])
        
        # Extract repo name from URL
        self.repo_name = self._extract_repo_name(self.ssh_repo_url)
        
        # Ensure directories exist (STRICT REQUIREMENT)
        self._ensure_directories()
        
        # Setup SSH for git operations
        self.setup_git_ssh()
    
    def _extract_repo_name(self, ssh_repo_url: str) -> str:
        """Extract repository name from SSH URL"""
        url = ssh_repo_url.rstrip('/')
        if url.endswith('.git'):
            url = url[:-4]
        
        # Handle both formats:
        # git@github.com:user/repo.git
        # ssh://git@github.com/user/repo.git
        if url.startswith('ssh://'):
            url = url[6:]  # Remove ssh://
        
        if ':' in url:
            # git@host:user/repo format
            repo_part = url.split(':')[-1]
        else:
            # ssh://git@host/user/repo format
            repo_part = url.split('@')[-1].split('/', 1)[-1]
        
        repo_name = repo_part.split('/')[-1]
        logger.info(f"Repository name extracted: {repo_name}")
        return repo_name
    
    def _ensure_directories(self):
        """Create required directories if they don't exist"""
        # Base temp directory
        self.base_temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured base temp directory: {self.base_temp_dir}")
        
        # Git workflow directory (will be cleaned per operation)
        if self.git_workflow_dir.exists():
            shutil.rmtree(self.git_workflow_dir, ignore_errors=True)
        self.git_workflow_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured git workflow directory: {self.git_workflow_dir}")
        
        # State tracking directory
        self.state_tracking_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured state tracking directory: {self.state_tracking_dir}")
    
    def setup_git_ssh(self):
        """Setup SSH for git operations"""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)
        
        # Create SSH config for git
        config_content = f"""Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking no
  ConnectTimeout 30
"""
        
        config_file = ssh_dir / "config"
        with open(config_file, "w") as f:
            f.write(config_content)
        config_file.chmod(0o600)
        
        # Set ownership
        try:
            shutil.chown(ssh_dir, "builder", "builder")
            for item in ssh_dir.iterdir():
                shutil.chown(item, "builder", "builder")
        except Exception as e:
            logger.warning(f"Could not change SSH dir ownership: {e}")
    
    def clone_repository(self) -> bool:
        """
        Clone repository into git_workflow directory for isolation
        
        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Cloning repository into {self.git_workflow_dir}...")
        
        # Clean directory first
        if self.git_workflow_dir.exists():
            shutil.rmtree(self.git_workflow_dir, ignore_errors=True)
        self.git_workflow_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            result = subprocess.run(
                ["git", "clone", "--depth", "1", self.ssh_repo_url, str(self.git_workflow_dir)],
                capture_output=True,
                text=True,
                check=False,
                timeout=300
            )
            
            if result.returncode == 0:
                logger.info("✅ Repository cloned successfully")
                return True
            else:
                logger.error(f"❌ Git clone failed: {result.stderr[:500]}")
                return False
        except Exception as e:
            logger.error(f"❌ Error cloning repository: {e}")
            return False
    
    def update_pkgbuild_version(self, pkg_name: str, pkg_dir: str, new_version: str) -> bool:
        """
        Update PKGBUILD version using regex
        
        Args:
            pkg_name: Package name
            pkg_dir: Relative directory containing PKGBUILD
            new_version: New version string (e.g., "1.2.3-1")
        
        Returns:
            True if successful, False otherwise
        """
        pkgbuild_path = self.git_workflow_dir / pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            logger.error(f"❌ PKGBUILD not found: {pkgbuild_path}")
            return False
        
        try:
            # Read PKGBUILD
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            # Parse version components
            if ':' in new_version:
                # Epoch:version-release format
                epoch, rest = new_version.split(':', 1)
                if '-' in rest:
                    version_part, release_part = rest.split('-', 1)
                else:
                    version_part = rest
                    release_part = "1"
            else:
                # version-release format
                if '-' in new_version:
                    version_part, release_part = new_version.split('-', 1)
                else:
                    version_part = new_version
                    release_part = "1"
            
            # Update pkgver
            pkgver_pattern = r'^(pkgver\s*=\s*)[^\s#]+'
            updated_content = re.sub(pkgver_pattern, f'\\g<1>{version_part}', content, flags=re.MULTILINE)
            
            # Update pkgrel
            pkgrel_pattern = r'^(pkgrel\s*=\s*)\d+'
            updated_content = re.sub(pkgrel_pattern, f'\\g<1>{release_part}', updated_content, flags=re.MULTILINE)
            
            # Update epoch if present
            epoch_pattern = r'^(epoch\s*=\s*)\d+'
            if 'epoch=' in content and ':' in new_version:
                updated_content = re.sub(epoch_pattern, f'\\g<1>{epoch}', updated_content, flags=re.MULTILINE)
            
            # Write updated PKGBUILD
            with open(pkgbuild_path, 'w') as f:
                f.write(updated_content)
            
            logger.info(f"✅ Updated PKGBUILD for {pkg_name}: {new_version}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error updating PKGBUILD: {e}")
            return False
    
    def commit_and_push(self, commit_message: str, branch: str = "main") -> bool:
        """
        Commit changes and push to remote repository
        
        Args:
            commit_message: Commit message
            branch: Target branch
        
        Returns:
            True if successful, False otherwise
        """
        if not self.git_workflow_dir.exists():
            logger.error("❌ Git workflow directory doesn't exist")
            return False
        
        try:
            # Change to repo directory
            original_cwd = os.getcwd()
            os.chdir(self.git_workflow_dir)
            
            # Configure git
            subprocess.run(["git", "config", "user.email", "builder@example.com"], check=False)
            subprocess.run(["git", "config", "user.name", "Package Builder"], check=False)
            
            # Add all changes
            add_result = subprocess.run(
                ["git", "add", "."],
                capture_output=True,
                text=True,
                check=False
            )
            
            if add_result.returncode != 0:
                logger.error(f"❌ Git add failed: {add_result.stderr}")
                os.chdir(original_cwd)
                return False
            
            # Commit
            commit_result = subprocess.run(
                ["git", "commit", "-m", commit_message],
                capture_output=True,
                text=True,
                check=False
            )
            
            if commit_result.returncode != 0:
                # Check if there were actual changes
                if "nothing to commit" in commit_result.stdout:
                    logger.info("ℹ️ No changes to commit")
                    os.chdir(original_cwd)
                    return True
                else:
                    logger.error(f"❌ Git commit failed: {commit_result.stderr}")
                    os.chdir(original_cwd)
                    return False
            
            # Push
            push_result = subprocess.run(
                ["git", "push", "origin", branch],
                capture_output=True,
                text=True,
                timeout=300,
                check=False
            )
            
            os.chdir(original_cwd)
            
            if push_result.returncode == 0:
                logger.info("✅ Changes pushed successfully")
                return True
            else:
                logger.error(f"❌ Git push failed: {push_result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during git operations: {e}")
            return False
    
    def cleanup(self):
        """Clean up git workflow directory"""
        if self.git_workflow_dir.exists():
            try:
                shutil.rmtree(self.git_workflow_dir, ignore_errors=True)
                logger.info("✅ Cleaned up git workflow directory")
            except Exception as e:
                logger.warning(f"⚠️ Could not clean up git workflow directory: {e}")
    
    def find_pkgbuild_dirs(self) -> List[Tuple[str, str]]:
        """
        Find all PKGBUILD directories in the cloned repository
        
        Returns:
            List of (package_name, relative_directory) tuples
        """
        if not self.git_workflow_dir.exists():
            logger.error("❌ Repository not cloned")
            return []
        
        pkgbuilds = []
        for pkgbuild_path in self.git_workflow_dir.rglob("PKGBUILD"):
            rel_path = pkgbuild_path.relative_to(self.git_workflow_dir)
            pkg_dir = str(rel_path.parent)
            
            # Try to extract package name from PKGBUILD
            try:
                with open(pkgbuild_path, 'r') as f:
                    content = f.read()
                
                # Look for pkgname= line
                match = re.search(r'^pkgname\s*=\s*(\S+)', content, re.MULTILINE)
                if match:
                    pkg_name = match.group(1)
                else:
                    # Use directory name as fallback
                    pkg_name = rel_path.parent.name
                
                pkgbuilds.append((pkg_name, pkg_dir))
            except Exception as e:
                logger.warning(f"Could not read PKGBUILD at {pkgbuild_path}: {e}")
        
        logger.info(f"Found {len(pkgbuilds)} PKGBUILD directories")
        return pkgbuilds
    
    def get_current_version(self, pkg_dir: str) -> Optional[str]:
        """
        Get current version from PKGBUILD
        
        Args:
            pkg_dir: Relative directory containing PKGBUILD
        
        Returns:
            Version string or None if not found
        """
        pkgbuild_path = self.git_workflow_dir / pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            return None
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            # Extract pkgver
            pkgver_match = re.search(r'^pkgver\s*=\s*(\S+)', content, re.MULTILINE)
            if not pkgver_match:
                return None
            
            pkgver = pkgver_match.group(1)
            
            # Extract pkgrel
            pkgrel_match = re.search(r'^pkgrel\s*=\s*(\d+)', content, re.MULTILINE)
            pkgrel = pkgrel_match.group(1) if pkgrel_match else "1"
            
            # Extract epoch if present
            epoch_match = re.search(r'^epoch\s*=\s*(\d+)', content, re.MULTILINE)
            
            if epoch_match and epoch_match.group(1) != "0":
                return f"{epoch_match.group(1)}:{pkgver}-{pkgrel}"
            else:
                return f"{pkgver}-{pkgrel}"
                
        except Exception as e:
            logger.error(f"Error reading version from PKGBUILD: {e}")
            return None