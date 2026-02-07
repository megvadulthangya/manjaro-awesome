"""
Hokibot Module - Handles automatic version bumping for local packages
WITH NON-BLOCKING FAIL-SAFE SEMANTICS AND ROBUST AUTH DETECTION
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
        
        # Initialize auth state
        self.auth_mode = "none"
        self.token_source = "none"
        self.normalized_ssh_key = None
        self.token = None
        self.repo_owner = None
        self.repo_name = None
        
        # Track temporary files for cleanup
        self._ssh_key_file = None
        self._clone_dir = None
        
        # Register cleanup
        atexit.register(self._cleanup)
    
    def _log_env_presence(self):
        """Log grep-safe environment presence proof line without leaking values"""
        env_vars = {
            'CI_PUSH_SSH_KEY': os.getenv('CI_PUSH_SSH_KEY'),
            'CI_PUSH_SSH_PRIVATE_KEY': os.getenv('CI_PUSH_SSH_PRIVATE_KEY'),
            'CI_SSH_KEY': os.getenv('CI_SSH_KEY'),
            'HOKIBOT_SSH_KEY': os.getenv('HOKIBOT_SSH_KEY'),
            'CI_PUSH_TOKEN': os.getenv('CI_PUSH_TOKEN'),
            'GITHUB_TOKEN': os.getenv('GITHUB_TOKEN'),
            'SSH_REPO_URL': self.ssh_repo_url
        }
        
        # Create presence flags (0/1)
        presence = {k: 1 if v and v.strip() else 0 for k, v in env_vars.items()}
        
        # Log the grep-safe line
        logger.info(f"HOKIBOT_ENV_PRESENT: CI_PUSH_SSH_KEY={presence['CI_PUSH_SSH_KEY']} "
                   f"CI_PUSH_TOKEN={presence['CI_PUSH_TOKEN']} "
                   f"GITHUB_TOKEN={presence['GITHUB_TOKEN']} "
                   f"SSH_REPO_URL={presence['SSH_REPO_URL']}")
    
    def _get_ssh_key_from_env(self) -> Optional[str]:
        """Get SSH key from environment with multiple alternate names"""
        env_names = [
            'CI_PUSH_SSH_KEY',
            'CI_PUSH_SSH_PRIVATE_KEY', 
            'CI_SSH_KEY',
            'HOKIBOT_SSH_KEY'
        ]
        
        for env_name in env_names:
            key = os.getenv(env_name)
            if key and key.strip():
                logger.info(f"Found SSH key in {env_name}")
                return key.strip()
        
        return None
    
    def _normalize_ssh_key(self, raw_key: str) -> Optional[str]:
        """
        Robust SSH key normalization with multiple format support
        
        Args:
            raw_key: Raw SSH key content
            
        Returns:
            Normalized SSH key or None if invalid
        """
        if not raw_key or not isinstance(raw_key, str):
            return None
        
        # Step 1: Strip whitespace
        normalized = raw_key.strip()
        
        # Step 2: Handle literal "\n" strings (common in GitHub secrets)
        if '\\n' in normalized:
            normalized = normalized.replace('\\n', '\n')
        
        # Step 3: Handle base64 encoded keys
        # Check if it looks like base64 (alphanumeric, +, /, =, no spaces)
        clean_for_b64 = normalized.replace('\n', '').replace('\r', '').strip()
        is_base64_candidate = (
            len(clean_for_b64) > 100 and 
            all(c.isalnum() or c in '+/=' for c in clean_for_b64) and
            '-----BEGIN' not in normalized
        )
        
        if is_base64_candidate:
            try:
                decoded = base64.b64decode(clean_for_b64, validate=True)
                decoded_str = decoded.decode('utf-8', errors='ignore')
                
                # Check if decoded contains SSH key markers
                if any(marker in decoded_str for marker in [
                    '-----BEGIN',
                    'OPENSSH PRIVATE KEY',
                    'openssh-key-v1'
                ]):
                    normalized = decoded_str
                    logger.info("Decoded base64 SSH key successfully")
            except Exception as e:
                logger.debug(f"Base64 decode failed: {e}")
                # Continue with original content
        
        # Step 4: Normalize line endings
        normalized = normalized.replace('\r\n', '\n')
        
        # Step 5: Validate SSH key format
        # Check for OpenSSH format
        has_begin = '-----BEGIN' in normalized
        has_openssh = 'OPENSSH PRIVATE KEY' in normalized
        has_openssh_v1 = normalized.startswith('openssh-key-v1')
        
        # If it's short and doesn't look like a key, treat as token
        if len(normalized) < 100 and not has_begin and not has_openssh and not has_openssh_v1:
            logger.info("Content too short and no SSH markers - not a key")
            return None
        
        # Must have proper markers to be considered a key
        if not has_begin and not has_openssh_v1:
            logger.info("No SSH key markers found")
            return None
        
        # Ensure proper line endings and trailing newline
        if not normalized.endswith('\n'):
            normalized += '\n'
        
        logger.info(f"SSH key normalized: begin={has_begin}, openssh={has_openssh}, v1={has_openssh_v1}, length={len(normalized)}")
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
                return True
            else:
                logger.warning(f"ssh-keygen validation failed: {result.stderr[:200]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("ssh-keygen validation timed out")
            return False
        except Exception as e:
            logger.warning(f"ssh-keygen validation error: {e}")
            return False
    
    def _get_token_from_env(self) -> Tuple[Optional[str], Optional[str]]:
        """Get token from environment with source tracking"""
        # Check CI_PUSH_TOKEN first
        token = os.getenv('CI_PUSH_TOKEN')
        if token and token.strip():
            return token.strip(), 'CI_PUSH_TOKEN'
        
        # Fallback to GITHUB_TOKEN
        token = os.getenv('GITHUB_TOKEN')
        if token and token.strip():
            return token.strip(), 'GITHUB_TOKEN'
        
        return None, None
    
    def _parse_repo_owner_and_name(self) -> bool:
        """Parse repository owner and name from SSH_REPO_URL or GITHUB_REPOSITORY"""
        # Try SSH_REPO_URL first (git@github.com:owner/repo.git)
        if self.ssh_repo_url:
            match = re.match(r'git@github\.com:([^/]+)/([^/.]+)(?:\.git)?', self.ssh_repo_url)
            if match:
                self.repo_owner = match.group(1)
                self.repo_name = match.group(2)
                logger.info(f"Parsed repo from SSH URL: {self.repo_owner}/{self.repo_name}")
                return True
        
        # Fallback to GITHUB_REPOSITORY environment variable
        github_repo = os.getenv('GITHUB_REPOSITORY')
        if github_repo and '/' in github_repo:
            parts = github_repo.split('/')
            if len(parts) >= 2:
                self.repo_owner = parts[0]
                self.repo_name = parts[1]
                logger.info(f"Parsed repo from GITHUB_REPOSITORY: {self.repo_owner}/{self.repo_name}")
                return True
        
        logger.warning("Could not parse repository owner/name")
        return False
    
    def _detect_auth_mode(self) -> bool:
        """
        Detect authentication mode based on available credentials.
        Sets self.auth_mode and self.token_source or self.normalized_ssh_key
        
        Returns:
            True if any auth mode detected, False if none
        """
        # Log environment presence
        self._log_env_presence()
        
        # Try SSH key first
        raw_ssh_key = self._get_ssh_key_from_env()
        if raw_ssh_key:
            normalized_key = self._normalize_ssh_key(raw_ssh_key)
            if normalized_key:
                # Test the key by writing to temp file and validating
                try:
                    with tempfile.NamedTemporaryFile(mode='w', suffix='_ssh_key', delete=False) as tmp:
                        tmp.write(normalized_key)
                        tmp_path = Path(tmp.name)
                    
                    # Validate with ssh-keygen
                    if self._validate_ssh_key_with_ssh_keygen(tmp_path):
                        self.normalized_ssh_key = normalized_key
                        self.auth_mode = "ssh"
                        logger.info("HOKIBOT_AUTH_MODE=ssh")
                        
                        # Clean up temp file
                        try:
                            tmp_path.unlink()
                        except:
                            pass
                        
                        return True
                    else:
                        logger.warning("SSH key failed validation with ssh-keygen")
                except Exception as e:
                    logger.warning(f"SSH key validation error: {e}")
                finally:
                    # Clean up temp file if still exists
                    try:
                        if 'tmp_path' in locals() and tmp_path.exists():
                            tmp_path.unlink()
                    except:
                        pass
        
        # Try token if SSH failed
        token, token_source = self._get_token_from_env()
        if token:
            self.token = token
            self.token_source = token_source
            self.auth_mode = "token"
            logger.info(f"HOKIBOT_AUTH_MODE=token")
            logger.info(f"HOKIBOT_TOKEN_SOURCE={token_source}")
            return True
        
        # No usable auth found
        self.auth_mode = "none"
        self.token_source = "none"
        logger.info("HOKIBOT_AUTH_MODE=none")
        logger.info("HOKIBOT_TOKEN_SOURCE=none")
        return False
    
    def _write_ssh_key_file(self) -> Optional[Path]:
        """Write normalized SSH key to temporary file"""
        if not self.normalized_ssh_key:
            return None
        
        try:
            # Create temporary directory for SSH key
            ssh_dir = Path("/tmp/hokibot_ssh")
            ssh_dir.mkdir(exist_ok=True, mode=0o700)
            ssh_key_path = ssh_dir / "id_ed25519"
            
            # Write key file
            with open(ssh_key_path, 'w', encoding='utf-8') as f:
                f.write(self.normalized_ssh_key)
            
            # Set strict permissions
            ssh_key_path.chmod(0o600)
            
            self._ssh_key_file = ssh_key_path
            logger.info(f"SSH key written to: {ssh_key_path}")
            return ssh_key_path
            
        except Exception as e:
            logger.warning(f"Failed to write SSH key file: {e}")
            return None
    
    def _setup_git_ssh_command(self, ssh_key_path: Path) -> str:
        """Create GIT_SSH_COMMAND with proper options."""
        ssh_cmd = f"ssh -i {ssh_key_path} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        return ssh_cmd
    
    def _clone_with_ssh(self, clone_dir: Path) -> bool:
        """Clone repository using SSH key"""
        if not self.ssh_repo_url:
            logger.warning("No SSH_REPO_URL for SSH clone")
            return False
        
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
            logger.warning("No SSH key file for clone")
            return False
        
        try:
            # Create GIT_SSH_COMMAND
            git_ssh_cmd = self._setup_git_ssh_command(ssh_key_path)
            
            # Set environment for git command
            env = os.environ.copy()
            env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
            # Clone command
            clone_cmd = f"git clone --depth 1 {self.ssh_repo_url} {clone_dir}"
            
            logger.info(f"Cloning with SSH: {self.ssh_repo_url}")
            
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
                logger.info(f"SSH clone successful: {clone_dir}")
                self._clone_dir = clone_dir
                return True
            else:
                logger.warning(f"SSH clone failed: {result.stderr[:200]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("SSH clone timed out")
            return False
        except Exception as e:
            logger.warning(f"SSH clone error: {e}")
            return False
    
    def _clone_with_token(self, clone_dir: Path) -> bool:
        """Clone repository using HTTPS with token"""
        if not self._parse_repo_owner_and_name():
            logger.warning("Cannot parse repo owner/name for token clone")
            return False
        
        if not self.token:
            logger.warning("No token for token clone")
            return False
        
        try:
            # Construct HTTPS URL with token (sanitized for logging)
            https_url = f"https://x-access-token:{self.token}@github.com/{self.repo_owner}/{self.repo_name}.git"
            sanitized_url = f"https://x-access-token:***@github.com/{self.repo_owner}/{self.repo_name}.git"
            
            logger.info(f"Cloning with token: {sanitized_url}")
            
            # Clone command
            clone_cmd = f"git clone --depth 1 {https_url} {clone_dir}"
            
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
                logger.info(f"Token clone successful: {clone_dir}")
                self._clone_dir = clone_dir
                return True
            else:
                # Don't log full error as it may contain token
                logger.warning("Token clone failed (error hidden for security)")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("Token clone timed out")
            return False
        except Exception as e:
            logger.warning(f"Token clone error: {e}")
            return False
    
    def _git_commit_with_skip_token(self, clone_dir: Path, message: str) -> bool:
        """Commit changes with [skip ci] token."""
        try:
            # Add [skip ci] prefix to commit message
            full_message = f"[skip ci] {message}"
            
            # Sanitize for logging (first line only)
            first_line = full_message.split('\n')[0][:100]
            logger.info(f"Commit message: {first_line}")
            
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
                logger.warning(f"git add failed: {result.stderr[:200]}")
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
                logger.info("Commit successful")
                return True
            elif "nothing to commit" in result.stderr:
                logger.info("Nothing to commit")
                return False
            else:
                logger.warning(f"git commit failed: {result.stderr[:200]}")
                return False
                
        except Exception as e:
            logger.warning(f"Commit error: {e}")
            return False
    
    def _push_with_ssh(self, clone_dir: Path) -> bool:
        """Push changes using SSH key"""
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
            logger.warning("No SSH key file for push")
            return False
        
        try:
            # Create GIT_SSH_COMMAND
            git_ssh_cmd = self._setup_git_ssh_command(ssh_key_path)
            
            # Set environment
            env = os.environ.copy()
            env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
            # Push command
            push_cmd = f"git -C {clone_dir} push"
            
            logger.info("Pushing with SSH...")
            
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
                logger.info("SSH push successful")
                return True
            else:
                logger.warning(f"SSH push failed: {result.stderr[:200]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("SSH push timed out")
            return False
        except Exception as e:
            logger.warning(f"SSH push error: {e}")
            return False
    
    def _push_with_token(self, clone_dir: Path) -> bool:
        """Push changes using HTTPS with token"""
        if not self._parse_repo_owner_and_name():
            logger.warning("Cannot parse repo owner/name for token push")
            return False
        
        if not self.token:
            logger.warning("No token for token push")
            return False
        
        try:
            # Construct HTTPS URL with token
            https_url = f"https://x-access-token:{self.token}@github.com/{self.repo_owner}/{self.repo_name}.git"
            
            # Push command
            push_cmd = f"git -C {clone_dir} push {https_url}"
            
            logger.info("Pushing with token...")
            
            result = subprocess.run(
                push_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=120
            )
            
            if result.returncode == 0:
                logger.info("Token push successful")
                return True
            else:
                # Don't log full error as it may contain token
                logger.warning("Token push failed (error hidden for security)")
                return False
                
        except subprocess.TimeoutExpired:
            logger.warning("Token push timed out")
            return False
        except Exception as e:
            logger.warning(f"Token push error: {e}")
            return False
    
    def run(self, hokibot_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run hokibot action: update PKGBUILD versions and push changes
        WITH NON-BLOCKING FAIL-SAFE SEMANTICS
        
        Args:
            hokibot_data: List of package metadata from BuildTracker
            
        Returns:
            Dictionary with results: {changed: int, committed: bool, pushed: bool, failsafe: bool, reason: str}
        """
        # Initialize result with default values
        result = {
            "changed": 0,
            "committed": False,
            "pushed": False,
            "failsafe": False,
            "reason": ""
        }
        
        try:
            # Log data count
            data_count = len(hokibot_data)
            logger.info(f"HOKIBOT_DATA_COUNT={data_count}")
            
            if data_count == 0:
                result["reason"] = "no_data"
                logger.info("HOKIBOT_ACTION=SKIP (no data)")
                return result
            
            logger.info("HOKIBOT_PHASE_RAN=1")
            
            # Step 1: Detect authentication mode
            if not self._detect_auth_mode():
                result["failsafe"] = True
                result["reason"] = "no_auth"
                logger.info("HOKIBOT_ACTION=SKIP (no auth)")
                logger.info("HOKIBOT_FAILSAFE=1 reason=no_auth")
                return result
            
            # Step 2: Check for repository URL
            if not self.ssh_repo_url:
                result["failsafe"] = True
                result["reason"] = "no_repo_url"
                logger.info("HOKIBOT_ACTION=SKIP (no repo URL)")
                logger.info("HOKIBOT_FAILSAFE=1 reason=no_repo_url")
                return result
            
            logger.info("HOKIBOT_ACTION=PROCESS")
            
            # Step 3: Generate unique run ID for temp directory
            import time
            run_id = int(time.time())
            clone_dir = Path(f"/tmp/hokibot_{run_id}")
            logger.info(f"HOKIBOT_CLONE_DIR={clone_dir}")
            
            # Step 4: Clone repository based on auth mode
            clone_success = False
            if self.auth_mode == "ssh":
                clone_success = self._clone_with_ssh(clone_dir)
            elif self.auth_mode == "token":
                clone_success = self._clone_with_token(clone_dir)
            
            if not clone_success:
                result["failsafe"] = True
                result["reason"] = "clone_failed"
                logger.info("HOKIBOT_ACTION=SKIP (clone failed)")
                logger.info(f"HOKIBOT_FAILSAFE=1 reason=clone_failed auth={self.auth_mode}")
                return result
            
            # Step 5: Update PKGBUILD files for each package
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
                result["reason"] = "no_changes"
                logger.info("HOKIBOT_ACTION=SKIP (no changes)")
                self._cleanup_clone_dir(clone_dir)
                return result
            
            result["changed"] = len(changed_packages)
            
            # Step 6: Commit changes with [skip ci]
            commit_message = f"hokibot: bump pkgver for {len(changed_packages)} packages\n\n"
            commit_message += "\n".join([f"- {pkg}" for pkg in changed_packages])
            
            if not self._git_commit_with_skip_token(clone_dir, commit_message):
                result["failsafe"] = True
                result["reason"] = "commit_failed"
                logger.info("HOKIBOT_ACTION=SKIP (commit failed)")
                logger.info(f"HOKIBOT_FAILSAFE=1 reason=commit_failed")
                self._cleanup_clone_dir(clone_dir)
                return result
            
            result["committed"] = True
            
            # Step 7: Push changes based on auth mode
            push_success = False
            if self.auth_mode == "ssh":
                push_success = self._push_with_ssh(clone_dir)
            elif self.auth_mode == "token":
                push_success = self._push_with_token(clone_dir)
            
            if push_success:
                result["pushed"] = True
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=yes auth={self.auth_mode}")
                logger.info("HOKIBOT_FAILSAFE=0")
            else:
                result["failsafe"] = True
                result["reason"] = "push_failed"
                logger.info("HOKIBOT_ACTION=SKIP (push failed)")
                logger.info(f"HOKIBOT_FAILSAFE=1 reason=push_failed auth={self.auth_mode}")
                logger.info(f"HOKIBOT_SUMMARY changed={len(changed_packages)} committed=yes pushed=no auth={self.auth_mode}")
            
            return result
            
        except Exception as e:
            result["failsafe"] = True
            result["reason"] = f"exception: {str(e)[:100]}"
            logger.warning(f"Hokibot phase exception - skipping: {e}")
            logger.info(f"HOKIBOT_FAILSAFE=1 reason=exception")
            return result
        finally:
            # Always clean up
            if 'clone_dir' in locals():
                self._cleanup_clone_dir(clone_dir)
    
    def _update_pkgbuild(self, pkgbuild_path: Path, pkgver: str, pkgrel: str, epoch: Optional[str] = None) -> bool:
        """Update PKGBUILD file with new version, release, and optionally epoch"""
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
            logger.warning(f"Failed to update PKGBUILD {pkgbuild_path}: {e}")
            return False
    
    def _cleanup_clone_dir(self, clone_dir: Path):
        """Cleanup temporary clone directory"""
        try:
            if clone_dir and clone_dir.exists():
                import shutil
                shutil.rmtree(clone_dir, ignore_errors=True)
        except Exception:
            pass
    
    def _cleanup(self):
        """Cleanup SSH key file on exit"""
        try:
            if self._ssh_key_file and self._ssh_key_file.exists():
                self._ssh_key_file.unlink(missing_ok=True)
        except Exception:
            pass