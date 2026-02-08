"""
Hokibot Module - Handles automatic version bumping for local packages
WITH NON-BLOCKING FAIL-SAFE SEMANTICS AND TOKEN-BASED GIT AUTH
AND PKGBUILD REWRITE VALIDATION
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
        
        # Get hokibot git identity from config
        try:
            import config
            self.git_user_name = getattr(config, 'HOKIBOT_GIT_USER_NAME', 'hokibot')
            self.git_user_email = getattr(config, 'HOKIBOT_GIT_USER_EMAIL', 'hokibot@users.noreply.github.com')
        except ImportError:
            self.git_user_name = 'hokibot'
            self.git_user_email = 'hokibot@users.noreply.github.com'
        
        # Track temporary SSH key file for cleanup
        self._ssh_key_file = None
        self._clone_dir = None
        
        # Register cleanup
        atexit.register(self._cleanup)
    
    def _set_git_identity(self, clone_dir: Path) -> bool:
        """
        Set git user identity for the repository.
        
        Args:
            clone_dir: Repository directory
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Set user name
            name_cmd = f"git -C {clone_dir} config user.name \"{self.git_user_name}\""
            name_result = subprocess.run(
                name_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            # Set user email
            email_cmd = f"git -C {clone_dir} config user.email \"{self.git_user_email}\""
            email_result = subprocess.run(
                email_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if name_result.returncode == 0 and email_result.returncode == 0:
                logger.info(f"HOKIBOT_GIT_IDENTITY_SET=1 name={self.git_user_name} email={self.git_user_email}")
                return True
            else:
                logger.warning(f"HOKIBOT_GIT_IDENTITY_SET=0 name_rc={name_result.returncode} email_rc={email_result.returncode}")
                return False
                
        except Exception as e:
            logger.warning(f"HOKIBOT_GIT_IDENTITY_SET=0 error={str(e)[:100]}")
            return False
    
    def _get_current_branch(self, clone_dir: Path) -> str:
        """
        Get current branch name.
        
        Args:
            clone_dir: Repository directory
            
        Returns:
            Branch name or empty string if cannot determine
        """
        try:
            # Try to get current branch
            branch_cmd = f"git -C {clone_dir} branch --show-current"
            result = subprocess.run(
                branch_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0 and result.stdout.strip():
                branch = result.stdout.strip()
                logger.info(f"HOKIBOT_BRANCH={branch}")
                return branch
            
            # Fallback: try to get default branch from origin/HEAD
            default_cmd = f"git -C {clone_dir} symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@'"
            result = subprocess.run(
                default_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0 and result.stdout.strip():
                branch = result.stdout.strip()
                logger.info(f"HOKIBOT_BRANCH={branch} (from origin/HEAD)")
                return branch
            
            # Last resort: try main or master
            for test_branch in ['main', 'master']:
                test_cmd = f"git -C {clone_dir} show-ref --verify --quiet refs/heads/{test_branch} 2>/dev/null"
                if subprocess.run(test_cmd, shell=True, check=False).returncode == 0:
                    logger.info(f"HOKIBOT_BRANCH={test_branch} (assumed)")
                    return test_branch
            
            logger.warning("HOKIBOT_BRANCH=unknown")
            return ""
                
        except Exception:
            logger.warning("HOKIBOT_BRANCH=unknown")
            return ""
    
    def _git_status_porcelain(self, clone_dir: Path) -> Tuple[int, List[str]]:
        """
        Get git status in porcelain format.
        
        Args:
            clone_dir: Repository directory
            
        Returns:
            Tuple of (count, first_5_lines)
        """
        try:
            status_cmd = f"git -C {clone_dir} status --porcelain"
            result = subprocess.run(
                status_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
                count = len(lines)
                sample = lines[:5]
                logger.info(f"HOKIBOT_GIT_STATUS_PORCELAIN_COUNT={count}")
                logger.info(f"HOKIBOT_GIT_STATUS_PORCELAIN_SAMPLE={','.join(sample) if sample else 'none'}")
                return count, lines
            else:
                logger.info("HOKIBOT_GIT_STATUS_PORCELAIN_COUNT=0")
                logger.info("HOKIBOT_GIT_STATUS_PORCELAIN_SAMPLE=none")
                return 0, []
                
        except Exception:
            logger.info("HOKIBOT_GIT_STATUS_PORCELAIN_COUNT=0")
            logger.info("HOKIBOT_GIT_STATUS_PORCELAIN_SAMPLE=none")
            return 0, []
    
    def _git_diff_name_only(self, clone_dir: Path) -> List[str]:
        """
        Get list of changed files.
        
        Args:
            clone_dir: Repository directory
            
        Returns:
            List of changed filenames
        """
        try:
            diff_cmd = f"git -C {clone_dir} diff --name-only"
            result = subprocess.run(
                diff_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                files = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
                sample = files[:10]
                logger.info(f"HOKIBOT_GIT_DIFF_NAME_ONLY={','.join(sample) if sample else 'none'}")
                return files
            else:
                logger.info("HOKIBOT_GIT_DIFF_NAME_ONLY=none")
                return []
                
        except Exception:
            logger.info("HOKIBOT_GIT_DIFF_NAME_ONLY=none")
            return []
    
    def _stage_changed_files(self, clone_dir: Path, changed_files: List[str]) -> bool:
        """
        Stage only changed files.
        
        Args:
            clone_dir: Repository directory
            changed_files: List of files to stage
            
        Returns:
            True if successful, False otherwise
        """
        if not changed_files:
            return True
        
        try:
            # Quote each filename for safety
            quoted_files = [f"'{f}'" for f in changed_files]
            files_str = ' '.join(quoted_files)
            
            # Use git add with specific files
            add_cmd = f"git -C {clone_dir} add {files_str}"
            result = subprocess.run(
                add_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info(f"HOKIBOT_GIT_ADD_SUCCESS=1 count={len(changed_files)}")
                return True
            else:
                logger.warning(f"HOKIBOT_GIT_ADD_SUCCESS=0 error={result.stderr[:100]}")
                return False
                
        except Exception as e:
            logger.warning(f"HOKIBOT_GIT_ADD_SUCCESS=0 error={str(e)[:100]}")
            return False
    
    def _git_commit_with_skip_token(self, clone_dir: Path, message: str, changed_files: List[str]) -> Tuple[bool, Optional[str]]:
        """
        Commit changes with [skip ci] token and robust error handling.
        
        Args:
            clone_dir: Repository directory
            message: Commit message (will be prefixed with [skip ci])
            changed_files: List of files that were changed
            
        Returns:
            Tuple of (success: bool, error_snippet: Optional[str])
        """
        try:
            # Add [skip ci] prefix to commit message
            full_message = f"[skip ci] {message}"
            
            # Sanitize for logging (first line only)
            first_line = full_message.split('\n')[0][:100]
            logger.info(f"HOKIBOT_COMMIT_MSG={first_line}")
            
            # Stage only changed files
            if not self._stage_changed_files(clone_dir, changed_files):
                return False, "Failed to stage files"
            
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
                return True, None
            elif "nothing to commit" in result.stderr:
                logger.info("HOKIBOT_COMMIT_SKIP=1 (nothing to commit)")
                return False, None
            else:
                # Extract error snippet (first 3 lines)
                error_lines = result.stderr.strip().split('\n')[:3]
                error_snippet = '; '.join([line[:100] for line in error_lines if line.strip()])
                logger.info(f"HOKIBOT_COMMIT_ERROR_SNIPPET={error_snippet}")
                return False, error_snippet
                
        except Exception as e:
            error_msg = str(e)[:100]
            logger.info(f"HOKIBOT_COMMIT_ERROR_SNIPPET={error_msg}")
            return False, error_msg
    
    # The following methods remain unchanged except for docstrings
    def _get_auth_token(self) -> Optional[str]:
        """Get authentication token in priority order."""
        for token_name, token in [
            ('GITHUB_TOKEN', self.github_token),
            ('CI_PUSH_TOKEN', self.ci_push_token),
            ('CI_PUSH_SSH_KEY', self.ci_push_ssh_key)
        ]:
            if token and token.strip():
                if (token.startswith('ghp_') or 
                    token.startswith('github_pat_') or 
                    token.startswith('gho_') or
                    len(token) >= 36):
                    logger.info(f"HOKIBOT_AUTH_SOURCE={token_name}")
                    logger.info(f"HOKIBOT_TOKEN_PRESENT=1 source={token_name} length={len(token)}")
                    return token
        
        logger.info("HOKIBOT_TOKEN_PRESENT=0")
        return None
    
    def _get_token_based_repo_url(self) -> Optional[str]:
        """Get HTTPS repository URL with token authentication."""
        token = self._get_auth_token()
        if not token:
            return None
        
        if not self.github_repository:
            logger.warning("GITHUB_REPOSITORY environment variable not set")
            return None
        
        repo_url = f"https://x-access-token:{token}@github.com/{self.github_repository}.git"
        redacted_url = f"https://x-access-token:***REDACTED***@github.com/{self.github_repository}.git"
        logger.info(f"HOKIBOT_HTTPS_URL={redacted_url}")
        
        return repo_url
    
    def _clone_with_auth(self, clone_dir: Path) -> bool:
        """Clone repository using authentication (token preferred, SSH fallback)."""
        token_url = self._get_token_based_repo_url()
        if token_url:
            logger.info("HOKIBOT_CLONE_MODE=token")
            return self._clone_with_token(token_url, clone_dir)
        
        if self.ssh_repo_url:
            logger.info("HOKIBOT_CLONE_MODE=ssh")
            return self._clone_with_ssh_fallback(clone_dir)
        
        logger.warning("No authentication method available for cloning")
        return False
    
    def _clone_with_token(self, token_url: str, clone_dir: Path) -> bool:
        """Clone repository using token-based HTTPS authentication."""
        try:
            clone_cmd = f"git clone --depth 1 {token_url} {clone_dir}"
            logger.info(f"HOKIBOT_CLONE_START=1 url=***REDACTED*** dir={clone_dir}")
            
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
        """Clone repository using SSH key (fallback method)."""
        if not self.ssh_repo_url:
            return False
        
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
            return False
        
        try:
            git_ssh_cmd = self._setup_git_ssh_command(ssh_key_path)
            env = os.environ.copy()
            env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
            clone_cmd = f"git clone --depth 1 {self.ssh_repo_url} {clone_dir}"
            logger.info(f"HOKIBOT_CLONE_START=1 url={self.ssh_repo_url} dir={clone_dir}")
            
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
    
    def _git_push_with_auth(self, clone_dir: Path) -> Tuple[bool, Optional[str]]:
        """
        Push changes using authentication (token preferred, SSH fallback).
        
        Returns:
            Tuple of (success: bool, error_snippet: Optional[str])
        """
        token = self._get_auth_token()
        if token:
            logger.info("HOKIBOT_PUSH_MODE=token")
            return self._git_push_with_token(clone_dir, token)
        
        logger.info("HOKIBOT_PUSH_MODE=ssh")
        return self._git_push_with_ssh_fallback(clone_dir)
    
    def _git_push_with_token(self, clone_dir: Path, token: str) -> Tuple[bool, Optional[str]]:
        """Push changes using token-based authentication."""
        try:
            token_url = f"https://x-access-token:{token}@github.com/{self.github_repository}.git"
            remote_cmd = f"git -C {clone_dir} remote set-url origin {token_url}"
            subprocess.run(remote_cmd, shell=True, capture_output=True, text=True, check=False)
            
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
                return True, None
            else:
                error_lines = result.stderr.strip().split('\n')[:3]
                error_snippet = '; '.join([line[:100] for line in error_lines if line.strip()])
                logger.info(f"HOKIBOT_PUSH_ERROR_SNIPPET={error_snippet}")
                logger.info("HOKIBOT_PUSH=0")
                return False, error_snippet
                
        except subprocess.TimeoutExpired:
            logger.info("HOKIBOT_PUSH=0")
            return False, "Push timeout"
        except Exception as e:
            logger.info("HOKIBOT_PUSH=0")
            return False, str(e)[:100]
    
    def _git_push_with_ssh_fallback(self, clone_dir: Path) -> Tuple[bool, Optional[str]]:
        """Push changes using SSH key (fallback method)."""
        ssh_key_path = self._write_ssh_key_file()
        if not ssh_key_path:
            return False, "No SSH key available"
        
        try:
            git_ssh_cmd = self._setup_git_ssh_command(ssh_key_path)
            env = os.environ.copy()
            env['GIT_SSH_COMMAND'] = git_ssh_cmd
            
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
                return True, None
            else:
                error_lines = result.stderr.strip().split('\n')[:3]
                error_snippet = '; '.join([line[:100] for line in error_lines if line.strip()])
                logger.info(f"HOKIBOT_PUSH_ERROR_SNIPPET={error_snippet}")
                logger.info("HOKIBOT_PUSH=0")
                return False, error_snippet
                
        except subprocess.TimeoutExpired:
            logger.info("HOKIBOT_PUSH=0")
            return False, "Push timeout"
        except Exception:
            logger.info("HOKIBOT_PUSH=0")
            return False, "SSH push exception"
    
    def _update_pkgbuild(self, pkgbuild_path: Path, pkgver: str, pkgrel: str, epoch: Optional[str] = None) -> Tuple[bool, bool, Optional[str]]:
        """
        Update PKGBUILD file with new version, release, and optionally epoch.
        FIX: Remove space after '=' in assignments.
        Returns: (content_changed: bool, success: bool, validation_error: Optional[str])
        """
        try:
            # Read current content
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                current_content = f.read()
            
            # Store original for backup
            original_content = current_content
            
            # AUDIT: Log pkgver/pkgrel lines in the PKGBUILD before update
            logger.info(f"HOKIBOT_PKGBUILD_AUDIT_BEFORE: {pkgbuild_path.parent.name}")
            for line_num, line in enumerate(current_content.split('\n'), 1):
                if line.strip().startswith('pkgver=') or line.strip().startswith('pkgrel='):
                    logger.info(f"  line {line_num}: {repr(line[:80])}")
            
            # Fix I3: Remove spaces after '=' in assignments
            # We need to update pkgver, pkgrel, and optionally epoch
            lines = current_content.split('\n')
            new_lines = []
            pkgver_updated = False
            pkgrel_updated = False
            epoch_updated = False
            
            for line in lines:
                original_line = line
                stripped = line.strip()
                
                # Handle pkgver assignment - FIX: Remove space after '='
                if stripped.startswith('pkgver=') and not pkgver_updated:
                    line = f"pkgver={pkgver}"
                    pkgver_updated = True
                    logger.info(f"HOKIBOT_PKGBUILD_UPDATE: {pkgbuild_path.parent.name} pkgver: {original_line} -> {line}")
                
                # Handle pkgrel assignment - FIX: Remove space after '='
                elif stripped.startswith('pkgrel=') and not pkgrel_updated:
                    line = f"pkgrel={pkgrel}"
                    pkgrel_updated = True
                    logger.info(f"HOKIBOT_PKGBUILD_UPDATE: {pkgbuild_path.parent.name} pkgrel: {original_line} -> {line}")
                
                # Handle epoch assignment - FIX: Remove space after '='
                elif stripped.startswith('epoch=') and epoch and epoch != '0' and not epoch_updated:
                    line = f"epoch={epoch}"
                    epoch_updated = True
                    logger.info(f"HOKIBOT_PKGBUILD_UPDATE: {pkgbuild_path.parent.name} epoch: {original_line} -> {line}")
                
                new_lines.append(line)
            
            # If pkgver or pkgrel not found, we need to insert them
            # This is a safety fallback - should not happen with valid PKGBUILDs
            if not pkgver_updated or not pkgrel_updated:
                logger.warning(f"PKGBUILD missing required fields: pkgver_updated={pkgver_updated}, pkgrel_updated={pkgrel_updated}")
                # We'll skip this PKGBUILD to avoid corruption
                return False, False, "Missing required pkgver/pkgrel fields"
            
            # If epoch needs to be added and wasn't found
            if epoch and epoch != '0' and not epoch_updated:
                # Find where to insert epoch (typically before pkgver)
                for i, line in enumerate(new_lines):
                    if line.strip().startswith('pkgver='):
                        # Insert epoch line before pkgver
                        new_lines.insert(i, f"epoch={epoch}")
                        epoch_updated = True
                        logger.info(f"HOKIBOT_PKGBUILD_INSERT: {pkgbuild_path.parent.name} added epoch={epoch}")
                        break
            
            new_content = '\n'.join(new_lines)
            
            # Check if content actually changed
            if new_content == current_content:
                return False, True, None  # No change, but operation successful
            
            # AUDIT: Log git diff for this PKGBUILD before validation
            pkg_dir = pkgbuild_path.parent
            try:
                diff_cmd = f"git -C {pkg_dir} diff --no-ext-diff {pkgbuild_path.name} 2>/dev/null || true"
                diff_result = subprocess.run(
                    diff_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False
                )
                if diff_result.returncode == 0 and diff_result.stdout.strip():
                    diff_lines = diff_result.stdout.strip().split('\n')
                    logger.info(f"HOKIBOT_PKGBUILD_GIT_DIFF: {pkgbuild_path.parent.name} (first 80 lines)")
                    for i, line in enumerate(diff_lines[:80]):
                        logger.info(f"  diff line {i+1}: {repr(line[:100])}")
            except Exception as e:
                logger.warning(f"Could not get git diff for audit: {e}")
            
            # Write new content
            with open(pkgbuild_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # Validate the PKGBUILD
            validation_error = self._validate_pkgbuild(pkgbuild_path)
            if validation_error:
                # Revert changes
                with open(pkgbuild_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)
                logger.warning(f"HOKIBOT_PKGBUILD_VALIDATION_FAILED: {pkgbuild_path.parent.name} - {validation_error}")
                
                # AUDIT: Log revert happened and check git status
                logger.info(f"HOKIBOT_REVERT_HAPPENED: {pkgbuild_path.parent.name}")
                try:
                    # Check git diff after revert (should be empty)
                    diff_cmd = f"git -C {pkg_dir} diff --no-ext-diff {pkgbuild_path.name} 2>/dev/null || true"
                    diff_result = subprocess.run(
                        diff_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if diff_result.returncode == 0:
                        if diff_result.stdout.strip():
                            logger.info(f"HOKIBOT_REVERT_DIFF_NON_EMPTY: {pkgbuild_path.parent.name}")
                            for i, line in enumerate(diff_result.stdout.strip().split('\n')[:20]):
                                logger.info(f"  revert diff line {i+1}: {repr(line[:100])}")
                        else:
                            logger.info(f"HOKIBOT_REVERT_DIFF_EMPTY: {pkgbuild_path.parent.name}")
                    
                    # Check git status porcelain count after revert
                    status_cmd = f"git -C {pkg_dir} status --porcelain {pkgbuild_path.name} 2>/dev/null | wc -l || echo 0"
                    status_result = subprocess.run(
                        status_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if status_result.returncode == 0:
                        count = status_result.stdout.strip()
                        logger.info(f"HOKIBOT_REVERT_STATUS_COUNT: {pkgbuild_path.parent.name} count={count}")
                except Exception as e:
                    logger.warning(f"Could not audit revert: {e}")
                
                return False, False, validation_error
            
            logger.info(f"HOKIBOT_PKGBUILD_VALIDATION_SUCCESS: {pkgbuild_path.parent.name}")
            return True, True, None
            
        except Exception as e:
            logger.error(f"HOKIBOT_PKGBUILD_UPDATE_ERROR: {pkgbuild_path} - {e}")
            return False, False, str(e)
    
    def _validate_pkgbuild(self, pkgbuild_path: Path) -> Optional[str]:
        """
        Validate PKGBUILD by running makepkg --printsrcinfo.
        
        Args:
            pkgbuild_path: Path to PKGBUILD file
            
        Returns:
            Error message if validation fails, None if successful
        """
        try:
            pkg_dir = pkgbuild_path.parent
            
            # Run makepkg --printsrcinfo to validate PKGBUILD
            cmd = ["makepkg", "--printsrcinfo"]
            result = subprocess.run(
                cmd,
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            # AUDIT: Log makepkg --printsrcinfo results
            logger.info(f"HOKIBOT_MAKEPKG_SRCINFO_AUDIT: {pkgbuild_path.parent.name}")
            logger.info(f"  exit_code={result.returncode}")
            logger.info(f"  stdout_length={len(result.stdout)}")
            logger.info(f"  stderr_length={len(result.stderr)}")
            logger.info(f"  stdout_first_80_chars={repr(result.stdout[:80])}")
            
            # Bounded output logs
            if result.stdout:
                stdout_lines = result.stdout.strip().split('\n')
                logger.info(f"  stdout_first_50_lines:")
                for i, line in enumerate(stdout_lines[:50]):
                    logger.info(f"    line {i+1}: {repr(line[:200])}")
            
            if result.stderr:
                stderr_lines = result.stderr.strip().split('\n')
                logger.info(f"  stderr_first_20_lines:")
                for i, line in enumerate(stderr_lines[:20]):
                    logger.info(f"    line {i+1}: {repr(line[:200])}")
            
            # Diagnostic regex checks (do not change pass/fail)
            pkgver_pattern = r'(^|\n)\s*pkgver\s*=\s*'
            pkgrel_pattern = r'(^|\n)\s*pkgrel\s*=\s*'
            
            pkgver_match = re.search(pkgver_pattern, result.stdout) is not None
            pkgrel_match = re.search(pkgrel_pattern, result.stdout) is not None
            
            logger.info(f"  pkgver_regex_match={pkgver_match}")
            logger.info(f"  pkgrel_regex_match={pkgrel_match}")
            
            if result.returncode != 0:
                error_msg = result.stderr[:500] if result.stderr else "Unknown error"
                return f"makepkg --printsrcinfo failed: {error_msg}"
            
            # Also check that we can parse the output
            if not result.stdout.strip():
                return "makepkg --printsrcinfo produced empty output"
            
            # Check for key fields in the output
            required_fields = ['pkgver', 'pkgrel']
            srcinfo_content = result.stdout
            for field in required_fields:
                if f"\n{field} = " not in srcinfo_content:
                    return f"Missing {field} in generated .SRCINFO"
            
            return None  # Validation successful
            
        except subprocess.TimeoutExpired:
            return "makepkg --printsrcinfo timeout"
        except Exception as e:
            return f"Validation exception: {str(e)}"
    
    def run(self, hokibot_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run hokibot action: update PKGBUILD versions and push changes
        WITH NON-BLOCKING FAIL-SAFE SEMANTICS AND PKGBUILD VALIDATION
        """
        data_count = len(hokibot_data)
        logger.info(f"HOKIBOT_DATA_COUNT={data_count}")
        
        if data_count == 0:
            logger.info("HOKIBOT_ACTION=SKIP")
            logger.info("HOKIBOT_FAILSAFE=0")
            logger.info("HOKIBOT_PHASE_RAN=0")
            logger.info("No hokibot data to process")
            return {"changed": 0, "committed": False, "pushed": False, "validation_errors": 0}
        
        logger.info("HOKIBOT_PHASE_RAN=1")
        
        # Check for required configuration
        if not self.github_repository:
            logger.info("HOKIBOT_ACTION=SKIP")
            logger.info("HOKIBOT_FAILSAFE=1")
            logger.info("HOKIBOT_SKIP_REASON=missing_repository")
            logger.warning("GITHUB_REPOSITORY not configured - hokibot skipping")
            return {"changed": 0, "committed": False, "pushed": False, "validation_errors": 0}
        
        # Check for any authentication method
        token = self._get_auth_token()
        if not token and not self.ssh_repo_url:
            logger.info("HOKIBOT_ACTION=SKIP")
            logger.info("HOKIBOT_FAILSAFE=1")
            logger.info("HOKIBOT_SKIP_REASON=no_auth_method")
            logger.warning("No authentication method available - hokibot skipping")
            return {"changed": 0, "committed": False, "pushed": False, "validation_errors": 0}
        
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
                return {"changed": 0, "committed": False, "pushed": False, "validation_errors": 0}
            
            # Step 2: Set git identity
            if not self._set_git_identity(clone_dir):
                logger.warning("Failed to set git identity, continuing anyway")
            
            # Step 3: Get current branch
            self._get_current_branch(clone_dir)
            
            # Step 4: Update PKGBUILD files for each package WITH VALIDATION
            actually_changed_packages = []
            changed_files = []
            validation_errors = 0
            
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
                    logger.warning(f"PKGBUILD not found for {pkg_name}")
                    continue
                
                # Update PKGBUILD with validation
                content_changed, success, validation_error = self._update_pkgbuild(pkgbuild_path, pkgver, pkgrel, epoch)
                
                if validation_error:
                    validation_errors += 1
                    logger.warning(f"HOKIBOT_PKGBUILD_VALIDATION_SKIP: {pkg_name} - {validation_error}")
                    # Skip this package - PKGBUILD remains unchanged
                    continue
                
                if success and content_changed:
                    actually_changed_packages.append(pkg_name)
                    changed_files.append(f"{pkg_name}/PKGBUILD")
                    logger.info(f"HOKIBOT_PKGBUILD_UPDATED: {pkg_name} pkgver={pkgver} pkgrel={pkgrel} epoch={epoch or 'none'}")
            
            # Step 5: Run git diagnostics
            status_count, status_lines = self._git_status_porcelain(clone_dir)
            diff_files = self._git_diff_name_only(clone_dir)
            
            # Step 6: Check if there are actual changes
            if status_count == 0:
                logger.info("HOKIBOT_ACTION=SKIP")
                logger.info("HOKIBOT_SKIP_REASON=no_changes")
                logger.info("HOKIBOT_FAILSAFE=0")
                logger.info(f"HOKIBOT_VALIDATION_ERRORS={validation_errors}")
                logger.info("No changes detected in working tree")
                return {"changed": 0, "committed": False, "pushed": False, "validation_errors": validation_errors}
            
            # Step 7: Commit changes with [skip ci]
            commit_message = f"hokibot: bump pkgver for {len(actually_changed_packages)} packages\n\n"
            commit_message += "\n".join([f"- {pkg}" for pkg in actually_changed_packages])
            
            commit_success, commit_error = self._git_commit_with_skip_token(clone_dir, commit_message, changed_files)
            
            if not commit_success:
                if commit_error:
                    logger.info("HOKIBOT_FAILSAFE=1")
                    logger.info("HOKIBOT_SKIP_REASON=commit_failed")
                    logger.warning(f"Failed to commit changes: {commit_error}")
                else:
                    # No error means nothing to commit (clean tree after staging)
                    logger.info("HOKIBOT_FAILSAFE=0")
                    logger.info("HOKIBOT_SKIP_REASON=no_changes_after_staging")
                logger.info(f"HOKIBOT_VALIDATION_ERRORS={validation_errors}")
                return {"changed": len(actually_changed_packages), "committed": False, "pushed": False, "validation_errors": validation_errors}
            
            # Step 8: Push changes with authentication
            push_success, push_error = self._git_push_with_auth(clone_dir)
            
            if push_success:
                logger.info("HOKIBOT_FAILSAFE=0")
                logger.info(f"HOKIBOT_SUMMARY changed={len(actually_changed_packages)} committed=yes pushed=yes validation_errors={validation_errors}")
                return {"changed": len(actually_changed_packages), "committed": True, "pushed": True, "validation_errors": validation_errors}
            else:
                logger.info("HOKIBOT_FAILSAFE=1")
                logger.info("HOKIBOT_SKIP_REASON=push_failed")
                if push_error:
                    logger.warning(f"Push failed: {push_error}")
                else:
                    logger.warning("Push failed")
                logger.info(f"HOKIBOT_SUMMARY changed={len(actually_changed_packages)} committed=yes pushed=no validation_errors={validation_errors}")
                return {"changed": len(actually_changed_packages), "committed": True, "pushed": False, "validation_errors": validation_errors}
            
        except Exception as e:
            logger.info("HOKIBOT_FAILSAFE=1")
            logger.info("HOKIBOT_SKIP_REASON=exception")
            logger.warning(f"Hokibot phase exception - skipping: {e}")
            return {"changed": 0, "committed": False, "pushed": False, "validation_errors": validation_errors}
        finally:
            # Step 9: Cleanup
            self._cleanup_clone_dir(clone_dir)
    
    # The following methods remain unchanged
    def _analyze_ssh_key_format(self, key_content: str) -> Dict[str, Any]:
        """Analyze SSH key format and extract metadata without exposing key content."""
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
