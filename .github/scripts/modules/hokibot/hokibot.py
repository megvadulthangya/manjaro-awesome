"""
Hokibot Module - Handles automatic version bumping for local packages
"""

import os
import re
import tempfile
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from modules.scm.git_client import GitClient
from modules.common.config_loader import ConfigLoader

logger = logging.getLogger(__name__)


class HokibotRunner:
    """Handles automatic version bumping for local packages"""
    
    def __init__(self, debug_mode: bool = False):
        """
        Initialize HokibotRunner
        
        Args:
            debug_mode: Enable debug logging
        """
        self.debug_mode = debug_mode
        self.config_loader = ConfigLoader()
        
        # Get SSH_REPO_URL from config.py
        try:
            import config
            self.ssh_repo_url = getattr(config, 'SSH_REPO_URL', None)
        except ImportError:
            # Fallback to environment variable or default
            self.ssh_repo_url = os.getenv('SSH_REPO_URL')
        
        # Get CI_PUSH_SSH_KEY from environment
        self.ci_push_ssh_key = os.getenv('CI_PUSH_SSH_KEY')
        
        if not self.ssh_repo_url:
            logger.error("SSH_REPO_URL not configured in config.py or environment")
        if not self.ci_push_ssh_key:
            logger.error("CI_PUSH_SSH_KEY not configured in environment")
    
    def run(self, hokibot_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run hokibot action: update PKGBUILD versions and push changes
        
        Args:
            hokibot_data: List of package metadata from BuildTracker
            
        Returns:
            Dictionary with results: {changed: int, committed: bool, pushed: bool}
        """
        if not hokibot_data:
            logger.info("HOKIBOT_PHASE_RAN=0 (no hokibot data)")
            return {"changed": 0, "committed": False, "pushed": False}
        
        if not self.ssh_repo_url or not self.ci_push_ssh_key:
            logger.error("HOKIBOT_PHASE_RAN=0 (missing configuration)")
            return {"changed": 0, "committed": False, "pushed": False}
        
        logger.info("HOKIBOT_PHASE_RAN=1")
        logger.info(f"Processing {len(hokibot_data)} packages for version updates")
        
        # Generate unique run ID for temp directory
        import time
        run_id = int(time.time())
        clone_dir = Path(f"/tmp/hokibot_{run_id}")
        
        try:
            # Step 1: Clone repository with SSH key
            logger.info(f"Cloning repository to {clone_dir}")
            
            # Initialize GitClient with SSH key
            git_client = GitClient(repo_url=self.ssh_repo_url, debug_mode=self.debug_mode)
            
            # Clone repository
            if not git_client.clone_with_ssh_key(str(clone_dir), self.ci_push_ssh_key, depth=1):
                logger.error("Failed to clone repository")
                return {"changed": 0, "committed": False, "pushed": False}
            
            # Step 2: Update PKGBUILD files for each package
            changed_packages = []
            for entry in hokibot_data:
                pkg_name = entry.get('name')
                pkgver = entry.get('pkgver')
                pkgrel = entry.get('pkgrel')
                epoch = entry.get('epoch')
                
                if not pkg_name or not pkgver or not pkgrel:
                    logger.warning(f"Skipping invalid entry: {entry}")
                    continue
                
                # Find PKGBUILD
                pkgbuild_path = clone_dir / pkg_name / "PKGBUILD"
                if not pkgbuild_path.exists():
                    logger.warning(f"PKGBUILD not found for {pkg_name}")
                    continue
                
                # Update PKGBUILD
                if self._update_pkgbuild(pkgbuild_path, pkgver, pkgrel, epoch):
                    changed_packages.append(pkg_name)
                    logger.info(f"Updated {pkg_name}: pkgver={pkgver}, pkgrel={pkgrel}" + 
                               (f", epoch={epoch}" if epoch and epoch != '0' else ""))
            
            if not changed_packages:
                logger.info("No packages updated")
                return {"changed": 0, "committed": False, "pushed": False}
            
            # Step 3: Commit changes
            commit_message = f"hokibot: update {len(changed_packages)} packages\n\n"
            commit_message += "\n".join([f"- {pkg}" for pkg in changed_packages])
            
            logger.info(f"Committing changes: {len(changed_packages)} packages")
            
            # Add all changed files
            for pkg_name in changed_packages:
                pkg_dir = clone_dir / pkg_name
                if pkg_dir.exists():
                    git_client.add_files(str(pkg_dir))
            
            # Commit
            if not git_client.commit(commit_message):
                logger.error("Failed to commit changes")
                return {"changed": len(changed_packages), "committed": False, "pushed": False}
            
            # Step 4: Push changes
            logger.info("Pushing changes to repository")
            if git_client.push():
                logger.info("HOKIBOT_PUSH_OK=1")
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=yes")
                return {"changed": len(changed_packages), "committed": True, "pushed": True}
            else:
                logger.error("HOKIBOT_PUSH_OK=0")
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=no")
                return {"changed": len(changed_packages), "committed": True, "pushed": False}
            
        except Exception as e:
            logger.error(f"Hokibot phase failed: {e}")
            logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages) if 'changed_packages' in locals() else 0} committed=no pushed=no")
            return {"changed": len(changed_packages) if 'changed_packages' in locals() else 0, 
                    "committed": False, "pushed": False}
        finally:
            # Step 5: Cleanup
            self._cleanup_clone_dir(clone_dir)
    
    def _update_pkgbuild(self, pkgbuild_path: Path, pkgver: str, pkgrel: str, epoch: Optional[str] = None) -> bool:
        """
        Update PKGBUILD file with new version, release, and optionally epoch
        
        Args:
            pkgbuild_path: Path to PKGBUILD file
            pkgver: New package version
            pkgrel: New package release
            epoch: New epoch (optional)
            
        Returns:
            True if updated, False otherwise
        """
        try:
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Update pkgver
            content = re.sub(
                r'^(\s*pkgver\s*=).*$',
                r'\1 ' + pkgver,
                content,
                flags=re.MULTILINE
            )
            
            # Update pkgrel
            content = re.sub(
                r'^(\s*pkgrel\s*=).*$',
                r'\1 ' + pkgrel,
                content,
                flags=re.MULTILINE
            )
            
            # Update epoch if provided and not '0'
            if epoch and epoch != '0':
                # Check if epoch line exists
                if re.search(r'^\s*epoch\s*=.*$', content, re.MULTILINE):
                    # Update existing epoch
                    content = re.sub(
                        r'^(\s*epoch\s*=).*$',
                        r'\1 ' + epoch,
                        content,
                        flags=re.MULTILINE
                    )
                else:
                    # Add epoch after pkgrel
                    content = re.sub(
                        r'^(\s*pkgrel\s*=.*)$',
                        r'\1\nepoch=' + epoch,
                        content,
                        flags=re.MULTILINE
                    )
            
            # Write updated content
            with open(pkgbuild_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update PKGBUILD {pkgbuild_path}: {e}")
            return False
    
    def _cleanup_clone_dir(self, clone_dir: Path):
        """Cleanup temporary clone directory"""
        try:
            if clone_dir.exists():
                import shutil
                shutil.rmtree(clone_dir, ignore_errors=True)
                logger.debug(f"Cleaned up temporary directory: {clone_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temporary directory: {e}")