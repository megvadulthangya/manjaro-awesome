"""
Version Manager Module - Handles version extraction, comparison, and management
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Tuple, Optional, List, Dict
import re
import urllib.parse

logger = logging.getLogger(__name__)


class VersionManager:
    """Handles package version extraction, comparison, and management"""
    
    def extract_version_from_srcinfo(self, pkg_dir: Path) -> Tuple[str, str, Optional[str]]:
        """Extract pkgver, pkgrel, and epoch from .SRCINFO or makepkg --printsrcinfo output"""
        srcinfo_path = pkg_dir / ".SRCINFO"
        
        # First try to read existing .SRCINFO
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    srcinfo_content = f.read()
                return self._parse_srcinfo_content(srcinfo_content)
            except Exception as e:
                logger.warning(f"Failed to parse existing .SRCINFO: {e}")
        
        # Generate .SRCINFO using makepkg --printsrcinfo
        try:
            result = subprocess.run(
                ['makepkg', '--printsrcinfo'],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0 and result.stdout:
                # Also write to .SRCINFO for future use
                with open(srcinfo_path, 'w') as f:
                    f.write(result.stdout)
                return self._parse_srcinfo_content(result.stdout)
            else:
                logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
                raise RuntimeError(f"Failed to generate .SRCINFO: {result.stderr}")
                
        except Exception as e:
            logger.error(f"Error running makepkg --printsrcinfo: {e}")
            raise
    
    def _parse_srcinfo_content(self, srcinfo_content: str) -> Tuple[str, str, Optional[str]]:
        """Parse SRCINFO content to extract version information"""
        pkgver = None
        pkgrel = None
        epoch = None
        
        lines = srcinfo_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Handle key-value pairs
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                if key == 'pkgver':
                    pkgver = value
                elif key == 'pkgrel':
                    pkgrel = value
                elif key == 'epoch':
                    epoch = value
        
        if not pkgver or not pkgrel:
            raise ValueError("Could not extract pkgver and pkgrel from .SRCINFO")
        
        return pkgver, pkgrel, epoch
    
    def get_full_version_string(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> str:
        """Construct full version string from components"""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"
    
    def normalize_version_string(self, version_string: str) -> str:
        """
        Canonical version normalization: strip architecture suffix and ensure epoch format.
        
        Args:
            version_string: Raw version string that may include architecture suffix
            
        Returns:
            Normalized version string in format epoch:pkgver-pkgrel
        """
        if not version_string:
            return version_string
            
        # Remove known architecture suffixes from the end
        # These are only stripped if they appear as the final token
        arch_patterns = [r'-x86_64$', r'-any$', r'-i686$', r'-aarch64$', r'-armv7h$', r'-armv6h$']
        for pattern in arch_patterns:
            version_string = re.sub(pattern, '', version_string)
        
        # Ensure epoch format: if no epoch, prepend "0:"
        if ':' not in version_string:
            # Check if there's already a dash in the version part
            if '-' in version_string:
                # Already in pkgver-pkgrel format, add epoch
                version_string = f"0:{version_string}"
            else:
                # No dash, assume it's just pkgver, add default pkgrel
                version_string = f"0:{version_string}-1"
        
        return version_string
    
    def extract_artifact_versions_from_files(self, built_files: List[str], pkg_names: List[str]) -> Dict[str, str]:
        """
        Extract actual built versions from the provided built_files list (files created/moved in this run).
        
        Args:
            built_files: List of built package filenames
            pkg_names: List of package names to look for
            
        Returns:
            Dictionary mapping pkg_name -> actual built version
        """
        artifact_versions = {}
        
        for pkg_name in pkg_names:
            for built_file in built_files:
                # Skip signature files
                if built_file.endswith('.sig'):
                    continue
                
                # Parse version from filename
                match = re.match(rf'^{re.escape(pkg_name)}-(.+?)-(?:x86_64|any|i686|aarch64|armv7h|armv6h)\.pkg\.tar\.(?:zst|xz)$', built_file)
                if match:
                    version = match.group(1)
                    artifact_versions[pkg_name] = version
                    logger.info(f"ARTIFACT_FROM_BUILT_FILES pkg={pkg_name} ver={version}")
                    break  # Found a version for this package
        
        return artifact_versions
    
    def extract_artifact_versions(self, output_dir: Path, pkg_names: List[str]) -> Dict[str, str]:
        """
        Extract actual built versions from artifact filenames in output_dir.
        Collects ALL matching artifacts per package and chooses the newest version.
        
        Args:
            output_dir: Directory containing built artifacts
            pkg_names: List of package names to look for
            
        Returns:
            Dictionary mapping pkg_name -> actual built version (newest found)
        """
        artifact_versions = {}
        
        for pkg_name in pkg_names:
            # Collect ALL matching artifacts for this package
            candidates = []
            bad_candidates = 0
            
            for artifact in output_dir.glob(f"{pkg_name}-*.pkg.tar.*"):
                # Skip signature files
                if artifact.name.endswith('.sig'):
                    continue
                
                # Parse version from filename
                match = re.match(rf'^{re.escape(pkg_name)}-(.+?)-(?:x86_64|any|i686|aarch64|armv7h|armv6h)\.pkg\.tar\.(?:zst|xz)$', artifact.name)
                if match:
                    version = match.group(1)
                    candidates.append((artifact, version))
                else:
                    bad_candidates += 1
            
            # Log bad candidates if any
            if bad_candidates > 0:
                logger.info(f"ARTIFACT_BAD_CANDIDATES pkg={pkg_name} count={bad_candidates}")
            
            if candidates:
                # Choose the newest version using version comparison
                if len(candidates) == 1:
                    # Only one candidate
                    chosen_artifact, chosen_version = candidates[0]
                else:
                    # Multiple candidates, find newest
                    newest_artifact, newest_version = candidates[0]
                    for artifact, version in candidates[1:]:
                        if self._version_cmp(version, newest_version) > 0:
                            newest_artifact, newest_version = artifact, version
                    chosen_artifact, chosen_version = newest_artifact, newest_version
                
                artifact_versions[pkg_name] = chosen_version
                logger.info(f"ARTIFACT_FROM_OUTPUT_DIR pkg={pkg_name} chosen={chosen_version} candidates={len(candidates)}")
        
        return artifact_versions
    
    def _version_cmp(self, v1: str, v2: str) -> int:
        """
        Compare two version strings using vercmp.
        Returns negative if v1 < v2, zero if v1 == v2, positive if v1 > v2.
        
        Args:
            v1: First version string
            v2: Second version string
            
        Returns:
            Comparison result
        """
        try:
            result = subprocess.run(
                ['vercmp', v1, v2],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception as e:
            logger.warning(f"vercmp failed: {e}")
        
        # Fallback: simple string comparison
        return 1 if v1 > v2 else -1 if v1 < v2 else 0
    
    def get_artifact_version_from_makepkg(self, makepkg_output: str) -> Optional[str]:
        """
        Extract built version from makepkg output.
        
        Args:
            makepkg_output: Output from makepkg command
            
        Returns:
            Version string if found, None otherwise
        """
        # Look for lines indicating package creation
        lines = makepkg_output.split('\n')
        for line in lines:
            if '==> Finished making:' in line or '==> Finished creating package' in line:
                # Extract package filename and parse version
                match = re.search(r'([a-zA-Z0-9_.-]+-([0-9]+:)?[a-zA-Z0-9_.+-]+-(?:x86_64|any|i686|aarch64|armv7h|armv6h)\.pkg\.tar\.(?:zst|xz))', line)
                if match:
                    filename = match.group(1)
                    # Parse version from filename
                    name_version = filename.rsplit('-', 3)[0]  # Remove architecture and extension
                    version_part = name_version.split('-', 1)[1] if '-' in name_version else name_version
                    return version_part
        
        return None
    
    def detect_vcs_package(self, pkg_dir: Path) -> Tuple[bool, str]:
        """
        Detect if a package is a VCS package using only local PKGBUILD content.
        
        Args:
            pkg_dir: Path to package directory
            
        Returns:
            Tuple of (is_vcs: bool, reason: str)
        """
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return False, "no_pkgbuild"
        
        try:
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                pkgbuild_content = f.read()
            
            # Check for pkgver() function
            if re.search(r'^\s*pkgver\s*\(\)\s*\{', pkgbuild_content, re.MULTILINE):
                return True, "pkgver_function"
            
            # Check for VCS-like sources
            lines = pkgbuild_content.split('\n')
            for line in lines:
                line = line.strip()
                if line.startswith('source=') or line.startswith('_source='):
                    # Check for VCS URLs
                    if any(vcs in line for vcs in ['git+', 'git://', '.git', 'svn+', 'hg+', 'bzr+']):
                        return True, "vcs_source"
            
            return False, "none"
        except Exception as e:
            logger.warning(f"Error detecting VCS for {pkg_dir}: {e}")
            return False, f"error: {str(e)[:50]}"
    
    def detect_placeholder_version(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        Detect if a version is a placeholder (common in VCS packages).
        
        Args:
            pkgver: Package version
            pkgrel: Package release
            epoch: Package epoch (optional)
            
        Returns:
            True if version is a common VCS placeholder, False otherwise
        """
        # Build full version string
        if epoch and epoch != '0':
            full_version = f"{epoch}:{pkgver}-{pkgrel}"
        else:
            full_version = f"{pkgver}-{pkgrel}"
        
        # Common VCS placeholder patterns (conservative)
        placeholder_patterns = [
            "0-1",
            "0:0-1",
            "9999-1",
            "0:9999-1",
            "99999999-1",
            "0:99999999-1",
            "0.0.0-1",
            "0:0.0.0-1",
            "0-0",
            "0:0-0"
        ]
        
        if full_version in placeholder_patterns:
            return True
        
        # Additional checks for common placeholders
        if pkgver in ["0", "9999", "99999999", "0.0.0"] and pkgrel in ["1", "0"]:
            return True
        
        return False
    
    def _parse_git_source_from_pkgbuild(self, pkgbuild_content: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Parse git source URL, branch, and commit from PKGBUILD content.
        
        Args:
            pkgbuild_content: PKGBUILD content as string
            
        Returns:
            Tuple of (git_url, branch, commit_hash)
        """
        try:
            lines = pkgbuild_content.split('\n')
            
            for line in lines:
                line = line.strip()
                if line.startswith('source=') or line.startswith('_source='):
                    if '=' not in line:
                        continue
                    
                    value = line.split('=', 1)[1].strip()
                    # Remove array parentheses if present
                    if value.startswith('(') and value.endswith(')'):
                        value = value[1:-1].strip()
                    
                    # Remove quotes and split by spaces
                    parts = re.findall(r'[\"\']([^\"\']+)[\"\']', value)
                    if not parts:
                        continue
                    
                    for part in parts:
                        # Check for git URLs
                        if 'git+' in part or '.git' in part or 'git://' in part:
                            # Parse URL and fragments
                            url_parts = part.split('#')
                            git_url = url_parts[0]
                            
                            branch = None
                            commit_hash = None
                            
                            # Parse fragments
                            if len(url_parts) > 1:
                                fragment = url_parts[1]
                                # Look for branch= or tag=
                                if 'branch=' in fragment:
                                    branch = fragment.split('branch=')[1].split('&')[0].split('#')[0]
                                elif 'tag=' in fragment:
                                    branch = fragment.split('tag=')[1].split('&')[0].split('#')[0]
                                # Look for commit hash (40 chars or 7+ chars)
                                elif re.search(r'[0-9a-f]{7,40}', fragment):
                                    commit_hash_match = re.search(r'([0-9a-f]{7,40})', fragment)
                                    if commit_hash_match:
                                        commit_hash = commit_hash_match.group(1)
                            
                            return git_url, branch, commit_hash
            
            return None, None, None
        except Exception as e:
            logger.warning(f"Error parsing git source from PKGBUILD: {e}")
            return None, None, None
    
    def _normalize_git_url(self, git_url: str) -> str:
        """
        Normalize git URL for git commands by stripping known prefixes.
        
        Args:
            git_url: Git repository URL with possible prefixes
            
        Returns:
            Normalized URL suitable for git ls-remote
        """
        original_url = git_url
        
        # Strip makepkg-style "name::" prefix first
        # Example: "${pkgname}::git+https://..." -> "git+https://..."
        # But preserve "git::" transport prefix which will be handled later
        if '::' in git_url:
            prefix, rest = git_url.split('::', 1)
            # Only strip if prefix is not "git" (special transport prefix)
            if prefix != 'git':
                git_url = rest
        
        # Remove git+ prefix
        if git_url.startswith('git+https://'):
            git_url = git_url[4:]  # Remove 'git+'
        elif git_url.startswith('git+http://'):
            git_url = git_url[4:]
        elif git_url.startswith('git+ssh://'):
            git_url = git_url[4:]
        elif git_url.startswith('git+git://'):
            git_url = git_url[4:]
        
        # Handle git:: transport prefix
        if git_url.startswith('git::https://'):
            git_url = git_url[5:]  # Remove 'git::'
        elif git_url.startswith('git::http://'):
            git_url = git_url[5:]
        elif git_url.startswith('git::ssh://'):
            git_url = git_url[5:]
        elif git_url.startswith('git::git://'):
            git_url = git_url[5:]
        
        # Remove other VCS prefixes
        if git_url.startswith('bzr+'):
            git_url = git_url[4:]
        elif git_url.startswith('hg+'):
            git_url = git_url[3:]
        elif git_url.startswith('svn+'):
            git_url = git_url[4:]
        
        return git_url
    
    def _get_upstream_head_commit(self, git_url: str, pkg_name: str, branch: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Get upstream HEAD commit hash using git ls-remote.
        
        Args:
            git_url: Git repository URL
            pkg_name: Package name for logging
            branch: Optional branch name (defaults to HEAD)
            
        Returns:
            Tuple of (full_commit_hash, short_commit_hash) or (None, None) if failed
        """
        try:
            # Normalize URL for git commands
            normalized_url = self._normalize_git_url(git_url)
            if normalized_url != git_url:
                logger.info(f"VCS_URL_NORMALIZED=1 pkg={pkg_name} from={self._sanitize_git_url(git_url)} to={self._sanitize_git_url(normalized_url)}")
            
            # Sanitize URL for logging
            sanitized_url = self._sanitize_git_url(normalized_url)
            
            # Determine ref to query
            ref = branch or "HEAD"
            if branch and not branch.startswith("refs/"):
                if branch == "HEAD":
                    ref = "HEAD"
                else:
                    ref = f"refs/heads/{branch}"
            
            logger.info(f"VCS_GIT_LS_REMOTE_START pkg={pkg_name} url={sanitized_url} ref={ref}")
            logger.info(f"VCS_UPSTREAM_CHECK=1 pkg={pkg_name} url={sanitized_url} ref={ref}")
            
            # Run git ls-remote with timeout
            cmd = ["git", "ls-remote", normalized_url, ref]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=20,
                check=False
            )
            
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line:
                        parts = line.split()
                        if len(parts) >= 1:
                            full_hash = parts[0].strip()
                            if len(full_hash) == 40:  # Valid SHA-1
                                short_hash = full_hash[:8]
                                return full_hash, short_hash
            
            # If that failed, try without ref to get HEAD
            if ref != "HEAD":
                logger.info(f"VCS_UPSTREAM_CHECK=1 pkg={pkg_name} url={sanitized_url} ref=HEAD")
                cmd = ["git", "ls-remote", normalized_url, "HEAD"]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if line:
                            parts = line.split()
                            if len(parts) >= 1:
                                full_hash = parts[0].strip()
                                if len(full_hash) == 40:
                                    short_hash = full_hash[:8]
                                    return full_hash, short_hash
            
            # Log detailed failure information
            stderr_snip = result.stderr[:160] if result.stderr else ''
            logger.warning(f"VCS_GIT_LS_REMOTE_FAIL pkg={pkg_name} rc={result.returncode} stderr_snip={stderr_snip} url={sanitized_url}")
            logger.warning(f"VCS_UPSTREAM_CHECK=0 pkg={pkg_name} url={sanitized_url} reason=ls_remote_failed")
            return None, None
            
        except subprocess.TimeoutExpired:
            logger.warning(f"VCS_UPSTREAM_CHECK=0 pkg={pkg_name} url={sanitized_url} reason=timeout")
            return None, None
        except Exception as e:
            logger.warning(f"VCS_UPSTREAM_CHECK=0 pkg={pkg_name} url={sanitized_url} reason=exception:{str(e)[:50]}")
            return None, None
    
    def _extract_git_hash_from_version_string(self, version_string: str) -> Optional[str]:
        """
        Extract git hash from Arch VCS package version string.
        Returns the full hash string (7-40 hex characters) as found, without truncation.
        
        Args:
            version_string: Version string (e.g., "4.3.1711.gcab3e81dc-1")
            
        Returns:
            Full git hash string or None if not found
        """
        # Patterns for Arch VCS packages:
        # 1. .g<short_hash> (e.g., 4.3.1711.gcab3e81dc-1)
        # 2. -g<short_hash> (e.g., r1234.gcab3e81dc-1)
        # 3. .r<num>.<short_hash> (e.g., 1.0.r123.abc12345-1)
        
        patterns = [
            r'\.g([0-9a-f]{7,})',      # .g<short_hash>
            r'-g([0-9a-f]{7,})',       # -g<short_hash>
            r'\.r[0-9]+\.([0-9a-f]{7,})', # .r123.<short_hash>
            r'-r[0-9]+\.([0-9a-f]{7,})',  # -r123.<short_hash>
        ]
        
        for pattern in patterns:
            match = re.search(pattern, version_string)
            if match:
                # Return full matched hash (no truncation)
                return match.group(1)
        
        return None
    
    def _get_pinned_hash_from_pkgbuild(self, pkg_dir: Path, pkgver: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Get pinned hash from PKGBUILD (from source URL or pkgver).
        Returns the exact hash string as found, without truncation.
        
        Args:
            pkg_dir: Package directory
            pkgver: Package version from PKGBUILD
            
        Returns:
            Tuple of (hash_source, full_hash) where full_hash is the exact
            hash string (7-40 hex characters) from the PKGBUILD.
        """
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return None, None
        
        try:
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                pkgbuild_content = f.read()
            
            # First, check source URL for commit hash
            git_url, branch, commit_hash = self._parse_git_source_from_pkgbuild(pkgbuild_content)
            if commit_hash:
                # Return full commit hash as found
                return "source_url", commit_hash
            
            # Next, check if pkgver contains a git hash
            pkgver_hash = self._extract_git_hash_from_version_string(pkgver)
            if pkgver_hash:
                return "pkgver", pkgver_hash
            
            return None, None
        except Exception as e:
            logger.warning(f"Error getting pinned hash from PKGBUILD {pkg_dir}: {e}")
            return None, None
    
    def _sanitize_git_url(self, url: str) -> str:
        """Sanitize git URL for logging (remove credentials)."""
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.username or parsed.password:
                # Rebuild URL without credentials
                netloc = parsed.hostname
                if parsed.port:
                    netloc = f"{parsed.hostname}:{parsed.port}"
                return urllib.parse.urlunparse((
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment
                ))
        except:
            pass
        
        return url
    
    def _check_vcs_upstream_for_identical_versions(self, pkg_dir: Path, pkgver: str, remote_version: str) -> Tuple[bool, str]:
        """
        Check if upstream has changed for VCS packages with identical versions.
        Uses strict prefix matching: if upstream_full.startswith(pinned_hash) -> SAME commit.
        
        Args:
            pkg_dir: Package directory
            pkgver: Local package version
            remote_version: Remote package version
            
        Returns:
            Tuple of (should_build: bool, reason: str)
        """
        pkg_name = pkg_dir.name
        
        try:
            pkgbuild_path = pkg_dir / "PKGBUILD"
            if not pkgbuild_path.exists():
                return False, "no_pkgbuild"
            
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                pkgbuild_content = f.read()
            
            # Parse git source from PKGBUILD
            git_url, branch, commit_hash = self._parse_git_source_from_pkgbuild(pkgbuild_content)
            if not git_url:
                return False, "no_git_source"
            
            # Get upstream HEAD commit (full 40-char SHA)
            upstream_full, upstream_short = self._get_upstream_head_commit(git_url, pkg_name, branch)
            if not upstream_full:
                logger.info(f"VCS_UPSTREAM_CHECK=0 pkg={pkg_name} reason=ls_remote_failed fallback=version_compare")
                return False, "upstream_check_failed"
            
            # Get pinned hash from PKGBUILD (source URL or pkgver) - full, not truncated
            hash_source, pinned_hash = self._get_pinned_hash_from_pkgbuild(pkg_dir, pkgver)
            logger.info(f"VCS_PINNED_SHA={pinned_hash or 'none'} pkg={pkg_name} source_version={pkgver} hash_source={hash_source or 'none'}")
            
            # Get hash from remote version (full hash, no truncation)
            remote_full = self._extract_git_hash_from_version_string(remote_version)
            logger.info(f"VCS_REMOTE_SHA={remote_full or 'none'} pkg={pkg_name}")
            logger.info(f"VCS_UPSTREAM_SHA={upstream_full} pkg={pkg_name}")  # log full 40-char SHA
            
            # --- Prefix matching logic ---
            if pinned_hash:
                # Compare pinned hash against upstream full SHA using startswith
                if upstream_full.startswith(pinned_hash):
                    logger.info(f"VCS_UPSTREAM_OVERRIDE=1 pkg={pkg_name} decision=SKIP reason=upstream_unchanged_prefix "
                              f"pinned={pinned_hash} upstream={upstream_full}")
                    return False, "upstream_unchanged"
                else:
                    logger.info(f"VCS_UPSTREAM_OVERRIDE=1 pkg={pkg_name} decision=BUILD reason=head_changed_prefix "
                              f"pinned={pinned_hash} upstream={upstream_full}")
                    return True, "head_changed"
            
            # If no pinned hash but remote version has hash, compare remote hash
            if remote_full:
                if upstream_full.startswith(remote_full):
                    logger.info(f"VCS_UPSTREAM_OVERRIDE=1 pkg={pkg_name} decision=SKIP reason=upstream_unchanged_prefix "
                              f"remote={remote_full} upstream={upstream_full}")
                    return False, "upstream_unchanged"
                else:
                    logger.info(f"VCS_UPSTREAM_OVERRIDE=1 pkg={pkg_name} decision=BUILD reason=head_changed_prefix "
                              f"remote={remote_full} upstream={upstream_full}")
                    return True, "head_changed"
            
            # No hashes to compare
            logger.info(f"VCS_UPSTREAM_CHECK=0 pkg={pkg_name} reason=no_pinned_sha fallback=version_compare")
            return False, "no_pinned_sha"
            
        except Exception as e:
            logger.warning(f"VCS upstream check error for {pkg_name}: {e}")
            logger.info(f"VCS_UPSTREAM_CHECK=0 pkg={pkg_name} reason=exception:{str(e)[:50]} fallback=version_compare")
            return False, f"exception:{str(e)[:50]}"
    
    def compare_versions(self, remote_version: Optional[str], pkgver: str, pkgrel: str, epoch: Optional[str], pkg_dir: Optional[Path] = None) -> bool:
        """
        Compare versions using vercmp-style logic with canonical normalization
        AND VCS upstream check for identical versions.
        
        Returns:
            True if AUR_VERSION > REMOTE_VERSION (should build), False otherwise
        """
        # If no remote version exists, we should build
        if not remote_version:
            norm_remote = "None"
            norm_source = self.get_full_version_string(pkgver, pkgrel, epoch)
            norm_source = self.normalize_version_string(norm_source)
            logger.info(f"[DEBUG] Comparing Package: Remote({norm_remote}) vs New({norm_source}) -> BUILD TRIGGERED (no remote)")
            return True
        
        # Build source version string
        source_version = self.get_full_version_string(pkgver, pkgrel, epoch)
        
        # Normalize both versions
        norm_remote = self.normalize_version_string(remote_version)
        norm_source = self.normalize_version_string(source_version)
        
        # Log for debugging
        logger.info(f"[VERSION_COMPARE] PKGBUILD source: {source_version} (norm={norm_source})")
        logger.info(f"[VERSION_COMPARE] Remote version: {remote_version} (norm={norm_remote})")
        
        # Use vercmp for proper version comparison
        try:
            result = subprocess.run(['vercmp', norm_source, norm_remote], 
                                  capture_output=True, text=True, check=False)
            if result.returncode == 0:
                cmp_result = int(result.stdout.strip())
                
                if cmp_result > 0:
                    logger.info(f"[VERSION_COMPARE] Result: BUILD (new version is newer)")
                    return True
                elif cmp_result == 0:
                    logger.info(f"[VERSION_COMPARE] Result: SKIP (versions identical)")
                    
                    # Check for VCS upstream change for identical versions
                    if pkg_dir:
                        is_vcs, vcs_reason = self.detect_vcs_package(pkg_dir)
                        logger.info(f"VCS_DETECTED={1 if is_vcs else 0} pkg={pkg_dir.name} reason={vcs_reason}")
                        
                        if is_vcs:
                            should_build, upstream_reason = self._check_vcs_upstream_for_identical_versions(pkg_dir, pkgver, remote_version)
                            if should_build:
                                logger.info(f"[VERSION_COMPARE] Override: BUILD (VCS upstream changed: {upstream_reason})")
                                return True
                    
                    return False
                else:
                    logger.info(f"[VERSION_COMPARE] Result: SKIP (remote version is newer)")
                    
                    # Check if this is a VCS package with placeholder version
                    if pkg_dir:
                        is_vcs, vcs_reason = self.detect_vcs_package(pkg_dir)
                        is_placeholder = self.detect_placeholder_version(pkgver, pkgrel, epoch)
                        
                        if is_vcs and is_placeholder:
                            logger.info(f"VCS_DETECTED=1 pkg={pkg_dir.name} reason={vcs_reason}")
                            logger.info(f"VCS_PLACEHOLDER=1 pkg={pkg_dir.name} source_version={source_version}")
                            logger.info(f"VCS_PLACEHOLDER_OVERRIDE=1 pkg={pkg_dir.name} source={source_version} remote={remote_version}")
                            logger.info(f"[VERSION_COMPARE] Override: BUILD (VCS package with placeholder version)")
                            return True
                    
                    return False
            else:
                # Fallback to simple comparison if vercmp fails
                logger.warning("vercmp failed, using fallback comparison")
                return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch, pkg_dir)
                
        except Exception as e:
            logger.warning(f"vercmp comparison failed: {e}, using fallback")
            return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch, pkg_dir)
    
    def _fallback_version_comparison(self, remote_version: str, pkgver: str, pkgrel: str, epoch: Optional[str], pkg_dir: Optional[Path] = None) -> bool:
        """Fallback version comparison when vercmp is not available"""
        # Normalize versions for fallback comparison too
        source_version = self.get_full_version_string(pkgver, pkgrel, epoch)
        norm_remote = self.normalize_version_string(remote_version)
        norm_source = self.normalize_version_string(source_version)
        
        logger.info(f"[FALLBACK_COMPARE] Remote(norm={norm_remote}) vs New(norm={norm_source})")
        
        # Parse normalized remote version
        remote_epoch = None
        remote_pkgver = None
        remote_pkgrel = None
        
        if ':' in norm_remote:
            remote_epoch_str, rest = norm_remote.split(':', 1)
            remote_epoch = remote_epoch_str
            if '-' in rest:
                remote_pkgver, remote_pkgrel = rest.split('-', 1)
            else:
                remote_pkgver = rest
                remote_pkgrel = "1"
        else:
            if '-' in norm_remote:
                remote_pkgver, remote_pkgrel = norm_remote.split('-', 1)
            else:
                remote_pkgver = norm_remote
                remote_pkgrel = "1"
        
        # Parse normalized source version
        source_epoch = None
        source_pkgver = None
        source_pkgrel = None
        
        if ':' in norm_source:
            source_epoch_str, rest = norm_source.split(':', 1)
            source_epoch = source_epoch_str
            if '-' in rest:
                source_pkgver, source_pkgrel = rest.split('-', 1)
            else:
                source_pkgver = rest
                source_pkgrel = "1"
        else:
            if '-' in norm_source:
                source_pkgver, source_pkgrel = norm_source.split('-', 1)
            else:
                source_pkgver = norm_source
                source_pkgrel = "1"
        
        # Compare epochs first
        if source_epoch != remote_epoch:
            try:
                epoch_int = int(source_epoch or 0)
                remote_epoch_int = int(remote_epoch or 0)
                if epoch_int > remote_epoch_int:
                    logger.info(f"[FALLBACK_COMPARE] BUILD (epoch {epoch_int} > {remote_epoch_int})")
                    return True
                else:
                    # Remote is newer - check for VCS placeholder override
                    if pkg_dir:
                        is_vcs, vcs_reason = self.detect_vcs_package(pkg_dir)
                        is_placeholder = self.detect_placeholder_version(pkgver, pkgrel, epoch)
                        
                        if is_vcs and is_placeholder:
                            logger.info(f"VCS_DETECTED=1 pkg={pkg_dir.name} reason={vcs_reason}")
                            logger.info(f"VCS_PLACEHOLDER=1 pkg={pkg_dir.name} source_version={source_version}")
                            logger.info(f"VCS_PLACEHOLDER_OVERRIDE=1 pkg={pkg_dir.name} source={source_version} remote={remote_version}")
                            logger.info(f"[FALLBACK_COMPARE] Override: BUILD (VCS package with placeholder version)")
                            return True
                    
                    logger.info(f"[FALLBACK_COMPARE] SKIP (epoch {epoch_int} <= {remote_epoch_int})")
                    return False
            except ValueError:
                if source_epoch != remote_epoch:
                    logger.info(f"[FALLBACK_COMPARE] SKIP (epoch string mismatch)")
                    return False
        
        # Compare pkgver
        if source_pkgver != remote_pkgver:
            logger.info(f"[FALLBACK_COMPARE] BUILD (pkgver different)")
            return True
        
        # Compare pkgrel
        try:
            remote_pkgrel_int = int(remote_pkgrel)
            pkgrel_int = int(source_pkgrel)
            if pkgrel_int > remote_pkgrel_int:
                logger.info(f"[FALLBACK_COMPARE] BUILD (pkgrel {pkgrel_int} > {remote_pkgrel_int})")
                return True
            else:
                # Check for identical versions with VCS upstream change
                if pkgrel_int == remote_pkgrel_int and pkg_dir:
                    # Versions are identical, check for VCS upstream change
                    is_vcs, vcs_reason = self.detect_vcs_package(pkg_dir)
                    logger.info(f"VCS_DETECTED={1 if is_vcs else 0} pkg={pkg_dir.name} reason={vcs_reason}")
                    
                    if is_vcs:
                        should_build, upstream_reason = self._check_vcs_upstream_for_identical_versions(pkg_dir, pkgver, remote_version)
                        if should_build:
                            logger.info(f"[FALLBACK_COMPARE] Override: BUILD (VCS upstream changed: {upstream_reason})")
                            return True
                
                # Remote is newer or equal - check for VCS placeholder override
                if pkg_dir and pkgrel_int < remote_pkgrel_int:  # Only override if remote is actually newer
                    is_vcs, vcs_reason = self.detect_vcs_package(pkg_dir)
                    is_placeholder = self.detect_placeholder_version(pkgver, pkgrel, epoch)
                    
                    if is_vcs and is_placeholder:
                        logger.info(f"VCS_DETECTED=1 pkg={pkg_dir.name} reason={vcs_reason}")
                        logger.info(f"VCS_PLACEHOLDER=1 pkg={pkg_dir.name} source_version={source_version}")
                        logger.info(f"VCS_PLACEHOLDER_OVERRIDE=1 pkg={pkg_dir.name} source={source_version} remote={remote_version}")
                        logger.info(f"[FALLBACK_COMPARE] Override: BUILD (VCS package with placeholder version)")
                        return True
                
                logger.info(f"[FALLBACK_COMPARE] SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})")
                return False
        except ValueError:
            if source_pkgrel != remote_pkgrel:
                logger.info(f"[FALLBACK_COMPARE] SKIP (pkgrel string mismatch)")
                return False
        
        # Versions are identical
        logger.info(f"[FALLBACK_COMPARE] SKIP (versions identical)")
        return False