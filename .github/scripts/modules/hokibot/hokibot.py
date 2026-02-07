"""
Hokibot Module - Handles automatic version bumping for local packages
WITH NON-BLOCKING FAIL-SAFE SEMANTICS AND TOKEN-BASED GIT AUTH
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
    """Handles automatic version bumping for local packages with non-blocking fail-safe"""
    
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
        
        # Get authentication tokens from environment (token mode preferred)
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.ci_push_token = os.getenv('CI_PUSH_TOKEN')
        self.ci_push_ssh_key = os.getenv('CI_PUSH_SSH_KEY')
        
        # Get GitHub repository from environment
        self.github_repository = os.getenv('GITHUB_REPOSITORY')
        
        # Track temporary SSH key file for cleanup
        self._ssh_key_file = None
        self._clone_dir = None
        
        # Register cleanup
        atexit.register(self._cleanup)
    
    def _get_auth_token(self) -> Optional[str]:
        """
        Get authentication token in priority order:
        1. GITHUB_TOKEN (preferred for token-based auth)
        2. CI_PUSH_TOKEN
        3. CI_PUSH_SSH_KEY (if it's a token, not an SSH key)
        
        Returns:
            Token string or None if no valid token found
        """
        # Check for tokens in priority order
        for token_name, token in [
            ('GITHUB_TOKEN', self.github_token),
            ('CI_PUSH_TOKEN', self.ci_push_token),
            ('CI_PUSH_SSH_KEY', self.ci_push_ssh_key)
        ]:
            if token and token.strip():
                # Basic validation: check if it's likely a GitHub token
                # GitHub tokens typically start with 'ghp_' or 'github_pat_'
                if (token.startswith('ghp_') or 
                    token.startswith('github_pat_') or 
                    token.startswith('gho_') or
                    len(token) >= 36):  # Generic token length check
                    logger.info(f"HOKIBOT_AUTH_SOURCE={token_name}")
                    # Never log the actual token
                    logger.info(f"HOKIBOT_TOKEN_PRESENT=1 source={token_name} length={len(token)}")
                    return token
        
        logger.info("HOKIBOT_TOKEN_PRESENT=0")
        return None
    
    def _get_token_based_repo_url(self) -> Optional[str]:
        """
        Get HTTPS repository URL with token authentication.
        
        Returns:
            HTTPS URL with token or None if missing required information
        """
        token = self._get_auth_token()
        if not token:
            return None
        
        if not self.github_repository:
            logger.warning("GITHUB_REPOSITORY environment variable not set")
            return None
        
        # Build HTTPS URL with token (redacted for logging)
        repo_url = f"https://x-access-token:{token}@github.com/{self.github_repository}.git"
        
        # Log redacted URL (without token)
        redacted_url = f"https://x-access-token:***REDACTED***@github.com/{self.github_repository}.git"
        logger.info(f"HOKIBOT_HTTPS_URL={redacted_url}")
        
        return repo_url
    
    def _clone_with_auth(self, clone_dir: Path) -> bool:
        """
        Clone repository using authentication (token preferred, SSH fallback).
        
        Args:
            clone_dir: Directory to clone into
            
        Returns:
            True if successful, False otherwise
        """
        # Try token-based HTTPS first
        token_url = self._get_token_based_repo_url()
        if token_url:
            logger.info("HOKIBOT_CLONE_MODE=token")
            return self._clone_with_token(token_url, clone_dir)
        
        # Fallback to SSH if SSH URL is available
        if self.ssh_repo_url:
            logger.info("HOKIBOT_CLONE_MODE=ssh")
            return self._clone_with_ssh_fallback(clone_dir)
        
        logger.warning("No authentication method available for cloning")
        return False
    
    def _clone_with_token(self, token_url: str, clone_dir: Path) -> bool:
        """
        Clone repository using token-based HTTPS authentication.
        
        Args:
            token_url: HTTPS URL with token
            clone_dir: Directory to clone into
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Clone command with token URL
            clone_cmd = f"git clone --depth 1 {token_url} {clone_dir}"
            
            logger.info(f"HOKIBOT_CLONE_START=1 url=***REDACTED*** dir={clone_dir}")
            
            # Run clone
            result = subprocess.run(
                clone_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info(f"HOKIBOT_CLONE_SUCCESS=1 dir={clone_dir}")
                self._clone_dir = clone_dir
                return True
            else:
                # Log error without exposing token
                error_msg = result.stderr.replace(self._get_auth_token(), '***REDACTED***') if self._get_auth_token() else result.stderr
                logger.error(f"Token clone failed: {error_msg[:200]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("Token clone timeout")
            return False
        except Exception as e:
            logger.error(f"Token clone exception: {e}")
            return False
    
    def _clone_with_ssh_fallback(self, clone_dir: Path) -> bool:
        """
        Clone repository using SSH key (fallback method).
        
        Args:
            clone_dir: Directory to clone into
            
        Returns:
            True if successful, False otherwise
        """
        if not self.ssh_repo_url:
            return False
        
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
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
                return False
                
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
    
    def _git_push_with_auth(self, clone_dir: Path) -> bool:
        """
        Push changes using authentication (token preferred, SSH fallback).
        
        Args:
            clone_dir: Repository directory
            
        Returns:
            True if successful, False otherwise
        """
        # Try token-based push first
        token = self._get_auth_token()
        if token:
            logger.info("HOKIBOT_PUSH_MODE=token")
            return self._git_push_with_token(clone_dir, token)
        
        # Fallback to SSH
        logger.info("HOKIBOT_PUSH_MODE=ssh")
        return self._git_push_with_ssh_fallback(clone_dir)
    
    def _git_push_with_token(self, clone_dir: Path, token: str) -> bool:
        """
        Push changes using token-based authentication.
        
        Args:
            clone_dir: Repository directory
            token: GitHub token
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Set remote URL with token
            token_url = f"https://x-access-token:{token}@github.com/{self.github_repository}.git"
            
            # Update remote URL
            remote_cmd = f"git -C {clone_dir} remote set-url origin {token_url}"
            result = subprocess.run(
                remote_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                logger.warning("Failed to update remote URL")
            
            # Push command
            push_cmd = f"git -C {clone_dir} push"
            
            logger.info("HOKIBOT_PUSH_START=1 mode=token")
            
            result = subprocess.run(
                push_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info("HOKIBOT_PUSH_SUCCESS=1")
                logger.info("HOKIBOT_PUSH=1")
                return True
            else:
                # Log error without exposing token
                error_msg = result.stderr.replace(token, '***REDACTED***')
                logger.error(f"Token push failed: {error_msg[:200]}")
                logger.info("HOKIBOT_PUSH=0")
                return False
                
        except subprocess.TimeoutExpired:
            logger.info("HOKIBOT_PUSH=0")
            return False
        except Exception as e:
            logger.error(f"Token push exception: {e}")
            logger.info("HOKIBOT_PUSH=0")
            return False
    
    def _git_push_with_ssh_fallback(self, clone_dir: Path) -> bool:
        """
        Push changes using SSH key (fallback method).
        
        Args:
            clone_dir: Repository directory
            
        Returns:
            True if successful, False otherwise
        """
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
            return False
        
        try:
            # Create GIT_SSH_COMMAND
            git_ssh_cmd = self._setup_git_ssh_command(ssh_key_path)
            
            # Set environment
            env = os.environ.copy()
            env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
            # Push command
            push_cmd = f"git -C {clone_dir} push"
            
            logger.info("HOKIBOT_PUSH_START=1 mode=ssh")
            
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
                logger.info("HOKIBOT_PUSH=0")
                return False
                
        except subprocess.TimeoutExpired:
            logger.info("HOKIBOT_PUSH=0")
            return False
        except Exception:
            logger.info("HOKIBOT_PUSH=0")
            return False
    
    def run(self, hokibot_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run hokibot action: update PKGBUILD versions and push changes
        WITH NON-BLOCKING FAIL-SAFE SEMANTICS
        
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
            logger.info("HOKIBOT_FAILSAFE=0")
            logger.info("HOKIBOT_PHASE_RAN=0")
            logger.info("No hokibot data to process")
            return {"changed": 0, "committed": False, "pushed": False}
        
        logger.info("HOKIBOT_PHASE_RAN=1")
        
        # Check for required configuration
        if not self.github_repository:
            logger.info("HOKIBOT_ACTION=SKIP")
            logger.info("HOKIBOT_FAILSAFE=1")
            logger.info("HOKIBOT_SKIP_REASON=missing_repository")
            logger.warning("GITHUB_REPOSITORY not configured - hokibot skipping")
            return {"changed": 0, "committed": False, "pushed": False}
        
        # Check for any authentication method
        token = self._get_auth_token()
        if not token and not self.ssh_repo_url:
            logger.info("HOKIBOT_ACTION=SKIP")
            logger.info("HOKIBOT_FAILSAFE=1")
            logger.info("HOKIBOT_SKIP_REASON=no_auth_method")
            logger.warning("No authentication method available - hokibot skipping")
            return {"changed": 0, "committed": False, "pushed": False}
        
        logger.info("HOKIBOT_ACTION=PROCESS")
        
        # Generate unique run ID for temp directory
        import time
        run_id = int(time.time())
        clone_dir = Path(f"/tmp/hokibot_{run_id}")
        logger.info(f"HOKIBOT_CLONE_DIR={clone_dir}")
        
        try:
            # Step 1: Clone repository with authentication
            if not self._clone_with_auth(clone_dir):
                logger.info("HOKIBOT_ACTION=SKIP")
                logger.info("HOKIBOT_FAILSAFE=1")
                logger.info("HOKIBOT_SKIP_REASON=clone_failed")
                logger.warning("Failed to clone repository - hokibot skipping")
                return {"changed": 0, "committed": False, "pushed": False}
            
            # Step 2: Update PKGBUILD files for each package
            changed_packages = []
            for entry in hokibot_data:
                pkg_name = entry.get('name')
                pkgver = entry.get('pkgver')
                pkgrel = entry.get('pkgrel')
                epoch = entry.get('epoch')
                
                if not pkg_name or not pkgver or not pkgrel:
                    continue
                
                # Find PKGBUILD
                pkgbuild_path = clone_dir / pkg_name / "PKGBUILD"
                if not pkgbuild_path.exists():
                    continue
                
                # Update PKGBUILD
                if self._update_pkgbuild(pkgbuild_path, pkgver, pkgrel, epoch):
                    changed_packages.append(pkg_name)
            
            if not changed_packages:
                logger.info("No packages updated")
                return {"changed": 0, "committed": False, "pushed": False}
            
            # Step 3: Commit changes with [skip ci]
            commit_message = f"hokibot: bump pkgver for {len(changed_packages)} packages\n\n"
            commit_message += "\n".join([f"- {pkg}" for pkg in changed_packages])
            
            if not self._git_commit_with_skip_token(clone_dir, commit_message):
                logger.info("HOKIBOT_FAILSAFE=1")
                logger.info("HOKIBOT_SKIP_REASON=commit_failed")
                logger.warning("Failed to commit changes - hokibot skipping")
                return {"changed": len(changed_packages), "committed": False, "pushed": False}
            
            # Step 4: Push changes with authentication
            push_success = self._git_push_with_auth(clone_dir)
            
            if push_success:
                logger.info("HOKIBOT_FAILSAFE=0")
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=yes")
                return {"changed": len(changed_packages), "committed": True, "pushed": True}
            else:
                logger.info("HOKIBOT_FAILSAFE=1")
                logger.info("HOKIBOT_SKIP_REASON=push_failed")
                logger.warning("Push failed - hokibot skipping")
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=no")
                return {"changed": len(changed_packages), "committed": True, "pushed": False}
            
        except Exception as e:
            logger.info("HOKIBOT_FAILSAFE=1")
            logger.info("HOKIBOT_SKIP_REASON=exception")
            logger.warning(f"Hokibot phase exception - skipping: {e}")
            return {"changed": 0, "committed": False, "pushed": False}
        finally:
            # Step 5: Cleanup
            self._cleanup_clone_dir(clone_dir)
    
    # The following methods remain unchanged from the original except for docstrings
    def _analyze_ssh_key_format(self, key_content: str) -> Dict[str, Any]:
        """Analyze SSH key format and extract metadata without exposing key content."""
        # ... existing implementation ...
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
        
        if not has_begin and not has_end:
            clean_content = key_content.strip().replace('\n', '').replace('\r', '')
            if len(clean_content) >= 40 and all(c.isalnum() or c in '+/=' for c in clean_content):
                try:
                    decoded = base64.b64decode(clean_content, validate=True)
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
        """Normalize SSH key content, handling multiple formats."""
        if not key_content or not isinstance(key_content, str):
            logger.warning("Empty or non-string SSH key")
            return None
        
        if '\\n' in key_content:
            normalized = key_content.replace('\\n', '\n')
        else:
            normalized = key_content
        
        if not any(header in normalized.lower() for header in [
            'begin openssh private key',
            'begin rsa private key',
            'begin private key'
        ]):
            try:
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
            except Exception:
                pass
        
        if '\r\n' in normalized:
            normalized = normalized.replace('\r\n', '\n')
        
        if not normalized.endswith('\n'):
            normalized += '\n'
        
        if not any(header in normalized.lower() for header in [
            'begin openssh private key',
            'begin rsa private key',
            'begin private key'
        ]):
            return None
        
        if not any(footer in normalized.lower() for footer in [
            'end openssh private key',
            'end rsa private key',
            'end private key'
        ]):
            return None
        
        return normalized
    
    def _validate_ssh_key_with_ssh_keygen(self, key_path: Path) -> bool:
        """Validate SSH key using ssh-keygen -y command."""
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
                return True
            else:
                return False
                
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False
    
    def _write_ssh_key_file(self) -> Optional[Path]:
        """Write SSH key to temporary file with robust format detection and validation."""
        if not self.ci_push_ssh_key:
            return None
        
        try:
            meta = self._analyze_ssh_key_format(self.ci_push_ssh_key)
            
            logger.info(f"HOKIBOT_SSH_KEY_META=length={meta['length']} "
                       f"has_begin={meta['has_begin']} has_end={meta['has_end']} "
                       f"newline_count={meta['newline_count']} "
                       f"contains_backslash_n={meta['contains_backslash_n']} "
                       f"is_base64_candidate={meta['is_base64_candidate']}")
            
            normalized_key = self._normalize_ssh_key_content(self.ci_push_ssh_key)
            if not normalized_key:
                logger.info("HOKIBOT_SSH_KEY_INVALID=1 reason=normalization_failed")
                return None
            
            ssh_dir = Path("/tmp/hokibot_ssh")
            ssh_dir.mkdir(exist_ok=True, mode=0o700)
            ssh_key_path = ssh_dir / "id_ed25519"
            
            with open(ssh_key_path, 'w', encoding='utf-8') as f:
                f.write(normalized_key)
            
            ssh_key_path.chmod(0o600)
            
            if not self._validate_ssh_key_with_ssh_keygen(ssh_key_path):
                try:
                    ssh_key_path.unlink(missing_ok=True)
                except Exception:
                    pass
                logger.info("HOKIBOT_SSH_KEY_INVALID=1 reason=ssh_keygen_validation_failed")
                return None
            
            self._ssh_key_file = ssh_key_path
            logger.info(f"HOKIBOT_SSH_KEY_WRITTEN=1 path={ssh_key_path} validated=1")
            return ssh_key_path
            
        except Exception:
            return None
    
    def _setup_git_ssh_command(self, ssh_key_path: Path) -> str:
        """Create GIT_SSH_COMMAND with proper options."""
        ssh_cmd = f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        logger.info(f"HOKIBOT_SSH_CMD={ssh_cmd}")
        return ssh_cmd
    
    def _git_commit_with_skip_token(self, clone_dir: Path, message: str) -> bool:
        """Commit changes with [skip ci] token."""
        try:
            full_message = f"[skip ci] {message}"
            
            first_line = full_message.split('\n')[0][:100]
            logger.info(f"HOKIBOT_COMMIT_MSG={first_line}")
            
            add_cmd = f"git -C {clone_dir} add ."
            result = subprocess.run(
                add_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                return False
            
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
                return False
                
        except Exception:
            return False
    
    def _update_pkgbuild(self, pkgbuild_path: Path, pkgver: str, pkgrel: str, epoch: Optional[str] = None) -> bool:
        """Update PKGBUILD file with new version, release, and optionally epoch."""
        try:
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            content = re.sub(
                r'^(\s*pkgver\s*=).*$',
                r'\1 ' + pkgver,
                content,
                flags=re.MULTILINE
            )
            
            content = re.sub(
                r'^(\s*pkgrel\s*=).*$',
                r'\1 ' + pkgrel,
                content,
                flags=re.MULTILINE
            )
            
            if epoch and epoch != '0':
                if re.search(r'^\s*epoch\s*=.*$', content, re.MULTILINE):
                    content = re.sub(
                        r'^(\s*epoch\s*=).*$',
                        r'\1 ' + epoch,
                        content,
                        flags=re.MULTILINE
                    )
                else:
                    content = re.sub(
                        r'^(\s*pkgrel\s*=.*)$',
                        r'\1\nepoch=' + epoch,
                        content,
                        flags=re.MULTILINE
                    )
            
            with open(pkgbuild_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return True
            
        except Exception:
            return False
    
    def _cleanup_clone_dir(self, clone_dir: Path):
        """Cleanup temporary clone directory."""
        try:
            if clone_dir.exists():
                import shutil
                shutil.rmtree(clone_dir, ignore_errors=True)
        except Exception:
            pass
    
    def _cleanup(self):
        """Cleanup SSH key file on exit."""
        try:
            if self._ssh_key_file and self._ssh_key_file.exists():
                self._ssh_key_file.unlink(missing_ok=True)
        except Exception:
            pass
