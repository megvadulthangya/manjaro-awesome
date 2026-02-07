"""
Hokibot Module - Handles automatic version bumping for local packages
WITH ROBUST SSH KEY HANDLING AND SELF-DIAGNOSIS
"""

import os
import re
import tempfile
import logging
import subprocess
import base64
import atexit
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from modules.scm.git_client import GitClient
from modules.common.config_loader import ConfigLoader

logger = logging.getLogger(__name__)


class HokibotRunner:
    """Handles automatic version bumping for local packages with robust SSH key handling"""
    
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
        
        # Initialize GitClient (will be configured later)
        self.git_client = GitClient(repo_url=self.ssh_repo_url, debug_mode=debug_mode)
        
        # Track temporary SSH key file for cleanup
        self._ssh_key_file = None
        self._clone_dir = None
        
        # Register cleanup
        atexit.register(self._cleanup)
        
        if not self.ssh_repo_url:
            logger.error("SSH_REPO_URL not configured in config.py or environment")
        if not self.ci_push_ssh_key:
            logger.error("CI_PUSH_SSH_KEY not configured in environment")
    
    def _analyze_ssh_key_format(self, key_content: str) -> Dict[str, Any]:
        """
        Analyze SSH key format and extract metadata without exposing key content.
        
        Args:
            key_content: Raw key content (may be encoded)
            
        Returns:
            Dictionary with analysis metadata
        """
        meta = {
            'length': len(key_content),
            'has_begin': 0,
            'has_end': 0,
            'newline_count': key_content.count('\n'),
            'contains_backslash_n': 1 if '\\n' in key_content else 0,
            'contains_crlf': 1 if '\r\n' in key_content else 0,
            'is_base64_candidate': 0,
            'validated': 0
        }
        
        # Check for SSH key headers (case-insensitive)
        key_lower = key_content.lower()
        has_begin = any(header in key_lower for header in [
            'begin openssh private key',
            'begin rsa private key', 
            'begin private key',
            '-----begin '
        ])
        has_end = any(footer in key_lower for footer in [
            'end openssh private key',
            'end rsa private key',
            'end private key',
            '-----end '
        ])
        
        meta['has_begin'] = 1 if has_begin else 0
        meta['has_end'] = 1 if has_end else 0
        
        # Check if it looks like base64 (alphanumeric, +, /, = padding, no spaces)
        # Simple heuristic: if no header and looks like base64
        if not has_begin and not has_end:
            clean_content = key_content.strip().replace('\n', '').replace('\r', '')
            if len(clean_content) >= 40 and all(c.isalnum() or c in '+/=' for c in clean_content):
                # Check if it's valid base64 by attempting decode
                try:
                    decoded = base64.b64decode(clean_content, validate=True)
                    # Check if decoded contains SSH key headers
                    decoded_str = decoded.decode('utf-8', errors='ignore').lower()
                    if any(header in decoded_str for header in [
                        'begin openssh private key',
                        'begin rsa private key',
                        'begin private key'
                    ]):
                        meta['is_base64_candidate'] = 1
                except Exception:
                    pass
        
        return meta
    
    def _normalize_ssh_key_content(self, key_content: str) -> Optional[str]:
        """
        Normalize SSH key content, handling multiple formats.
        
        Args:
            key_content: Raw key content
            
        Returns:
            Normalized key content or None if invalid
        """
        if not key_content or not isinstance(key_content, str):
            logger.error("Empty or non-string SSH key")
            return None
        
        # Step 1: Handle escaped newlines (common in GitHub secrets)
        if '\\n' in key_content:
            # Replace literal \n sequences with actual newlines
            normalized = key_content.replace('\\n', '\n')
            logger.debug("Converted escaped \\n to actual newlines")
        else:
            normalized = key_content
        
        # Step 2: Handle base64 encoded keys
        if not any(header in normalized.lower() for header in [
            'begin openssh private key',
            'begin rsa private key',
            'begin private key'
        ]):
            # Might be base64 encoded, try to decode
            try:
                # Remove whitespace for base64 decode
                clean = normalized.strip().replace('\n', '').replace('\r', '')
                if len(clean) >= 40 and all(c.isalnum() or c in '+/=' for c in clean):
                    decoded = base64.b64decode(clean, validate=True)
                    decoded_str = decoded.decode('utf-8')
                    if any(header in decoded_str.lower() for header in [
                        'begin openssh private key',
                        'begin rsa private key',
                        'begin private key'
                    ]):
                        normalized = decoded_str
                        logger.debug("Successfully decoded base64 SSH key")
            except Exception as e:
                logger.debug(f"Base64 decode attempt failed: {e}")
        
        # Step 3: Normalize line endings (CRLF -> LF)
        if '\r\n' in normalized:
            normalized = normalized.replace('\r\n', '\n')
            logger.debug("Normalized CRLF to LF")
        
        # Step 4: Ensure trailing newline
        if not normalized.endswith('\n'):
            normalized += '\n'
            logger.debug("Added trailing newline")
        
        # Step 5: Final validation - must contain proper SSH key headers
        if not any(header in normalized.lower() for header in [
            'begin openssh private key',
            'begin rsa private key',
            'begin private key'
        ]):
            logger.error("SSH key missing BEGIN header after normalization")
            return None
        
        if not any(footer in normalized.lower() for footer in [
            'end openssh private key',
            'end rsa private key',
            'end private key'
        ]):
            logger.error("SSH key missing END footer after normalization")
            return None
        
        return normalized
    
    def _validate_ssh_key_with_ssh_keygen(self, key_path: Path) -> bool:
        """
        Validate SSH key using ssh-keygen -y command.
        
        Args:
            key_path: Path to SSH key file
            
        Returns:
            True if key is valid, False otherwise
        """
        try:
            cmd = ['ssh-keygen', '-y', '-f', str(key_path)]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )
            
            if result.returncode == 0:
                logger.info(f"SSH key validation passed: {result.stdout[:50]}...")
                return True
            else:
                logger.error(f"SSH key validation failed: {result.stderr[:200]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("SSH key validation timeout")
            return False
        except Exception as e:
            logger.error(f"SSH key validation error: {e}")
            return False
    
    def _write_ssh_key_file(self) -> Optional[Path]:
        """
        Write SSH key to temporary file with robust format detection and validation.
        
        Returns:
            Path to SSH key file or None on failure
        """
        if not self.ci_push_ssh_key:
            logger.error("No CI_PUSH_SSH_KEY available")
            logger.info("HOKIBOT_SSH_KEY_INVALID=1 reason=empty_key")
            return None
        
        try:
            # Analyze key format
            meta = self._analyze_ssh_key_format(self.ci_push_ssh_key)
            
            # Log metadata (safe - no key content)
            logger.info(f"HOKIBOT_SSH_KEY_META=length={meta['length']} "
                       f"has_begin={meta['has_begin']} has_end={meta['has_end']} "
                       f"newline_count={meta['newline_count']} "
                       f"contains_backslash_n={meta['contains_backslash_n']} "
                       f"is_base64_candidate={meta['is_base64_candidate']}")
            
            # Normalize key content
            normalized_key = self._normalize_ssh_key_content(self.ci_push_ssh_key)
            if not normalized_key:
                logger.error("Failed to normalize SSH key")
                logger.info("HOKIBOT_SSH_KEY_INVALID=1 reason=normalization_failed")
                return None
            
            # Create temporary directory for SSH key
            ssh_dir = Path("/tmp/hokibot_ssh")
            ssh_dir.mkdir(exist_ok=True, mode=0o700)
            ssh_key_path = ssh_dir / "id_ed25519"
            
            # Write key file
            with open(ssh_key_path, 'w', encoding='utf-8') as f:
                f.write(normalized_key)
            
            # Set strict permissions
            ssh_key_path.chmod(0o600)
            
            # Validate key with ssh-keygen BEFORE using it
            logger.info("Validating SSH key with ssh-keygen...")
            if not self._validate_ssh_key_with_ssh_keygen(ssh_key_path):
                logger.error("SSH key failed validation")
                # Clean up invalid key file
                try:
                    ssh_key_path.unlink(missing_ok=True)
                except Exception:
                    pass
                logger.info("HOKIBOT_SSH_KEY_INVALID=1 reason=ssh_keygen_validation_failed")
                return None
            
            self._ssh_key_file = ssh_key_path
            logger.info(f"HOKIBOT_SSH_KEY_WRITTEN=1 path={ssh_key_path} validated=1")
            return ssh_key_path
            
        except Exception as e:
            logger.error(f"Failed to write SSH key file: {e}")
            logger.info(f"HOKIBOT_FAILSAFE=1 error=ssh_key_write")
            return None
    
    def _setup_git_ssh_command(self, ssh_key_path: Path) -> str:
        """
        Create GIT_SSH_COMMAND with proper options.
        
        Args:
            ssh_key_path: Path to SSH key file
            
        Returns:
            GIT_SSH_COMMAND string
        """
        ssh_cmd = f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        logger.info(f"HOKIBOT_SSH_CMD={ssh_cmd}")
        return ssh_cmd
    
    def _clone_with_ssh(self, clone_dir: Path) -> bool:
        """
        Clone repository using SSH key with robust validation.
        
        Args:
            clone_dir: Directory to clone into
            
        Returns:
            True if successful, False otherwise
        """
        if not self.ssh_repo_url:
            logger.error("No SSH_REPO_URL configured")
            logger.info(f"HOKIBOT_FAILSAFE=1 error=no_repo_url")
            return False
        
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
            # Key validation already failed in _write_ssh_key_file
            logger.info(f"HOKIBOT_FAILSAFE=1 error=invalid_ssh_key")
            return False
        
        try:
            # Create GIT_SSH_COMMAND
            git_ssh_cmd = self._setup_git_ssh_command(ssh_key_path)
            
            # Set environment for git command
            env = os.environ.copy()
            env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
            # Clone command
            clone_cmd = f"git clone --depth 1 {self.ssh_repo_url} {clone_dir}"
            
            logger.info(f"HOKIBOT_CLONE_START=1 url={self.ssh_repo_url} dir={clone_dir}")
            
            # Run clone
            result = subprocess.run(
                clone_cmd,
                shell=True,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info(f"HOKIBOT_CLONE_SUCCESS=1 dir={clone_dir}")
                self._clone_dir = clone_dir
                return True
            else:
                logger.error(f"Clone failed: {result.stderr[:200]}")
                logger.info(f"HOKIBOT_FAILSAFE=1 error=clone_failed")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Clone timeout")
            logger.info(f"HOKIBOT_FAILSAFE=1 error=clone_timeout")
            return False
        except Exception as e:
            logger.error(f"Clone error: {e}")
            logger.info(f"HOKIBOT_FAILSAFE=1 error=clone_exception")
            return False
    
    def _git_commit_with_skip_token(self, clone_dir: Path, message: str) -> bool:
        """
        Commit changes with [skip ci] token.
        
        Args:
            clone_dir: Repository directory
            message: Commit message (will be prefixed with [skip ci])
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Add [skip ci] prefix to commit message
            full_message = f"[skip ci] {message}"
            
            # Sanitize for logging (first line only)
            first_line = full_message.split('\n')[0][:100]
            logger.info(f"HOKIBOT_COMMIT_MSG={first_line}")
            
            # Add all changes
            add_cmd = f"git -C {clone_dir} add ."
            result = subprocess.run(
                add_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                logger.error(f"Add failed: {result.stderr[:200]}")
                return False
            
            # Commit
            commit_cmd = f"git -C {clone_dir} commit -m '{full_message}'"
            result = subprocess.run(
                commit_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("HOKIBOT_COMMIT_SUCCESS=1")
                return True
            elif "nothing to commit" in result.stderr:
                logger.info("HOKIBOT_COMMIT_SKIP=1 (nothing to commit)")
                return False
            else:
                logger.error(f"Commit failed: {result.stderr[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"Commit error: {e}")
            return False
    
    def _git_push_with_ssh(self, clone_dir: Path) -> bool:
        """
        Push changes using SSH key.
        
        Args:
            clone_dir: Repository directory
            
        Returns:
            True if successful, False otherwise
        """
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
            # Key validation already failed in _write_ssh_key_file
            logger.info(f"HOKIBOT_FAILSAFE=1 error=invalid_ssh_key")
            return False
        
        try:
            # Create GIT_SSH_COMMAND
            git_ssh_cmd = self._setup_git_ssh_command(ssh_key_path)
            
            # Set environment
            env = os.environ.copy()
            env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
            # Push command
            push_cmd = f"git -C {clone_dir} push"
            
            logger.info("HOKIBOT_PUSH_START=1")
            
            result = subprocess.run(
                push_cmd,
                shell=True,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info("HOKIBOT_PUSH_SUCCESS=1")
                logger.info("HOKIBOT_PUSH=1")
                return True
            else:
                logger.error(f"Push failed: {result.stderr[:200]}")
                logger.info(f"HOKIBOT_FAILSAFE=1 error=push_failed")
                logger.info("HOKIBOT_PUSH=0")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Push timeout")
            logger.info(f"HOKIBOT_FAILSAFE=1 error=push_timeout")
            logger.info("HOKIBOT_PUSH=0")
            return False
        except Exception as e:
            logger.error(f"Push error: {e}")
            logger.info(f"HOKIBOT_FAILSAFE=1 error=push_exception")
            logger.info("HOKIBOT_PUSH=0")
            return False
    
    def run(self, hokibot_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run hokibot action: update PKGBUILD versions and push changes
        WITH FAIL-SAFE SEMANTICS
        
        Args:
            hokibot_data: List of package metadata from BuildTracker
            
        Returns:
            Dictionary with results: {changed: int, committed: bool, pushed: bool}
        """
        # Log data count
        data_count = len(hokibot_data)
        logger.info(f"HOKIBOT_DATA_COUNT={data_count}")
        
        if data_count == 0:
            logger.info("HOKIBOT_ACTION=SKIP")
            logger.info("No hokibot data to process")
            return {"changed": 0, "committed": False, "pushed": False}
        
        logger.info("HOKIBOT_ACTION=PROCESS")
        
        # Generate unique run ID for temp directory
        import time
        run_id = int(time.time())
        clone_dir = Path(f"/tmp/hokibot_{run_id}")
        logger.info(f"HOKIBOT_CLONE_DIR={clone_dir}")
        
        try:
            # Step 1: Clone repository with SSH key (includes key validation)
            logger.info(f"Cloning repository to {clone_dir}")
            
            if not self._clone_with_ssh(clone_dir):
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
            
            # Step 3: Commit changes with [skip ci]
            commit_message = f"hokibot: bump pkgver for {len(changed_packages)} packages\n\n"
            commit_message += "\n".join([f"- {pkg}" for pkg in changed_packages])
            
            logger.info(f"Committing changes: {len(changed_packages)} packages")
            
            if not self._git_commit_with_skip_token(clone_dir, commit_message):
                logger.error("Failed to commit changes")
                # Fail-safe: Don't fail the build
                logger.info("HOKIBOT_FAILSAFE=1 error=commit_failed")
                return {"changed": len(changed_packages), "committed": False, "pushed": False}
            
            # Step 4: Push changes (includes key re-validation)
            logger.info("Pushing changes to repository")
            push_success = self._git_push_with_ssh(clone_dir)
            
            if push_success:
                logger.info("Hokibot push successful")
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=yes")
                return {"changed": len(changed_packages), "committed": True, "pushed": True}
            else:
                # Fail-safe: Push failed but don't fail the build
                logger.error("Hokibot push failed (fail-safe)")
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=no")
                return {"changed": len(changed_packages), "committed": True, "pushed": False}
            
        except Exception as e:
            logger.error(f"Hokibot phase failed: {e}")
            logger.info(f"HOKIBOT_FAILSAFE=1 error=exception")
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
    
    def _cleanup(self):
        """Cleanup SSH key file on exit"""
        try:
            if self._ssh_key_file and self._ssh_key_file.exists():
                self._ssh_key_file.unlink(missing_ok=True)
        except Exception:
            pass
