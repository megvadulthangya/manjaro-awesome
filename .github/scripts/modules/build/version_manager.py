"""
Version Manager Module - Handles version extraction, comparison, and management
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Tuple, Optional, List, Dict
import re

logger = logging.getLogger(__name__)


class VersionManager:
    """Handles package version extraction, comparison, and management"""
    
    def is_vcs_package(self, pkg_dir: Path) -> Tuple[bool, str]:
        """
        Detect if a package is a VCS package without network calls.
        
        Args:
            pkg_dir: Path to package directory
            
        Returns:
            Tuple of (is_vcs: bool, reason: str)
        """
        try:
            # First try to read PKGBUILD
            pkgbuild_path = pkg_dir / "PKGBUILD"
            if not pkgbuild_path.exists():
                # Fallback to .SRCINFO
                srcinfo_path = pkg_dir / ".SRCINFO"
                if srcinfo_path.exists():
                    with open(srcinfo_path, 'r') as f:
                        content = f.read()
                    return self._detect_vcs_from_content(content)
                return False, "no_pkgbuild_or_srcinfo"
            
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            return self._detect_vcs_from_content(content)
            
        except Exception as e:
            logger.warning(f"VCS detection failed for {pkg_dir}: {e}")
            return False, f"error: {e}"
    
    def _detect_vcs_from_content(self, content: str) -> Tuple[bool, str]:
        """
        Detect VCS package from PKGBUILD or .SRCINFO content.
        
        Args:
            content: Content of PKGBUILD or .SRCINFO
            
        Returns:
            Tuple of (is_vcs: bool, reason: str)
        """
        # Check for pkgver() function definition
        if re.search(r'^\s*pkgver\s*\(\)', content, re.MULTILINE):
            return True, "pkgver_function"
        
        # Check for VCS source URLs
        vcs_patterns = [
            r'git\+',           # git+https://
            r'git://',          # git://
            r'\.git\b',         # .git extension
            r'svn\+',           # svn+https://
            r'hg\+',            # hg+https://
            r'bzr\+',           # bzr+https://
            r'cvs\+',           # cvs+https://
        ]
        
        for pattern in vcs_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True, f"vcs_source_{pattern.rstrip('+').rstrip('\\\\')}"
        
        return False, "none"
    
    def is_placeholder_version(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        Detect if version is a placeholder.
        
        Args:
            pkgver: Package version
            pkgrel: Package release
            epoch: Package epoch (optional)
            
        Returns:
            True if version is a placeholder, False otherwise
        """
        # Build full version string
        full_version = self.get_full_version_string(pkgver, pkgrel, epoch)
        
        # Common placeholders for VCS packages
        placeholder_patterns = [
            # Exact matches
            r'^0-1$',              # 0-1
            r'^0:0-1$',           # 0:0-1 (with epoch)
            r'^9999-1$',          # 9999-1
            r'^0:9999-1$',        # 0:9999-1 (with epoch)
            r'^0\.0\.0-1$',       # 0.0.0-1
            r'^0:0\.0\.0-1$',     # 0:0.0.0-1 (with epoch)
            
            # Common VCS placeholders (conservative)
            r'^\d+\.\d+\.\d+\.r\d+\.\w+-1$',  # git snapshot versions
            r'^r\d+-1$',                      # r1234-1
            r'^\d{8}-1$',                     # 20230101-1 (date snapshots)
        ]
        
        for pattern in placeholder_patterns:
            if re.match(pattern, full_version):
                return True
        
        # Additional conservative checks
        if pkgver in ["0", "9999", "0.0.0", "0.0", "0.0.0.0"] and pkgrel == "1":
            return True
        
        # Check if pkgver looks like a git commit hash (hexadecimal, 7+ chars)
        if re.match(r'^[0-9a-f]{7,}$', pkgver, re.IGNORECASE) and pkgrel == "1":
            return True
        
        return False
    
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
    
    def extract_artifact_versions(self, output_dir: Path, pkg_names: List[str]) -> Dict[str, str]:
        """
        Extract actual built versions from artifact filenames.
        
        Args:
            output_dir: Directory containing built artifacts
            pkg_names: List of package names to look for
            
        Returns:
            Dictionary mapping pkg_name -> actual built version
        """
        artifact_versions = {}
        
        for pkg_name in pkg_names:
            # Look for artifacts matching this package name
            for artifact in output_dir.glob(f"{pkg_name}-*.pkg.tar.*"):
                # Skip signature files
                if artifact.name.endswith('.sig'):
                    continue
                
                # Parse version from filename
                match = re.match(rf'^{re.escape(pkg_name)}-(.+?)-(?:x86_64|any|i686|aarch64|armv7h|armv6h)\.pkg\.tar\.(?:zst|xz)$', artifact.name)
                if match:
                    version = match.group(1)
                    artifact_versions[pkg_name] = version
                    logger.info(f"Extracted artifact version for {pkg_name}: {version}")
                    break
        
        return artifact_versions
    
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
    
    def compare_versions(self, pkg_dir: Path, remote_version: Optional[str], pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        Compare versions using vercmp-style logic with canonical normalization
        and VCS placeholder override.
        
        Args:
            pkg_dir: Path to package directory (for VCS detection)
            remote_version: Remote version from VPS
            pkgver: Source package version
            pkgrel: Source package release
            epoch: Source package epoch (optional)
            
        Returns:
            True if AUR_VERSION > REMOTE_VERSION (should build), False otherwise
        """
        # VCS detection
        is_vcs, vcs_reason = self.is_vcs_package(pkg_dir)
        logger.info(f"VCS_DETECTED={1 if is_vcs else 0} pkg={pkg_dir.name} reason={vcs_reason}")
        
        # Placeholder detection
        is_placeholder = self.is_placeholder_version(pkgver, pkgrel, epoch)
        source_version = self.get_full_version_string(pkgver, pkgrel, epoch)
        logger.info(f"VCS_PLACEHOLDER={1 if is_placeholder else 0} pkg={pkg_dir.name} source_version={source_version}")
        
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
        
        # Check for VCS placeholder override BEFORE version comparison
        if is_vcs and is_placeholder:
            logger.info(f"VCS_PLACEHOLDER_OVERRIDE=1 pkg={pkg_dir.name} source={source_version} remote={remote_version}")
            logger.info(f"[VERSION_COMPARE] VCS placeholder detected - forcing BUILD regardless of version comparison")
            return True
        
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
                    return False
                else:
                    logger.info(f"[VERSION_COMPARE] Result: SKIP (remote version is newer)")
                    return False
            else:
                # Fallback to simple comparison if vercmp fails
                logger.warning("vercmp failed, using fallback comparison")
                return self._fallback_version_comparison(pkg_dir, remote_version, pkgver, pkgrel, epoch)
                
        except Exception as e:
            logger.warning(f"vercmp comparison failed: {e}, using fallback")
            return self._fallback_version_comparison(pkg_dir, remote_version, pkgver, pkgrel, epoch)
    
    def _fallback_version_comparison(self, pkg_dir: Path, remote_version: str, pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """Fallback version comparison when vercmp is not available"""
        # VCS detection for fallback
        is_vcs, vcs_reason = self.is_vcs_package(pkg_dir)
        is_placeholder = self.is_placeholder_version(pkgver, pkgrel, epoch)
        
        # Check for VCS placeholder override in fallback
        if is_vcs and is_placeholder:
            source_version = self.get_full_version_string(pkgver, pkgrel, epoch)
            logger.info(f"VCS_PLACEHOLDER_OVERRIDE=1 pkg={pkg_dir.name} source={source_version} remote={remote_version}")
            logger.info(f"[FALLBACK_COMPARE] VCS placeholder detected - forcing BUILD")
            return True
        
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
                logger.info(f"[FALLBACK_COMPARE] SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})")
                return False
        except ValueError:
            if source_pkgrel != remote_pkgrel:
                logger.info(f"[FALLBACK_COMPARE] SKIP (pkgrel string mismatch)")
                return False
        
        # Versions are identical
        logger.info(f"[FALLBACK_COMPARE] SKIP (versions identical)")
        return False
