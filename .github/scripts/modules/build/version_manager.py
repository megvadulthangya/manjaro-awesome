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
    
    def compare_versions(self, remote_version: Optional[str], pkgver: str, pkgrel: str, epoch: Optional[str], pkg_dir: Optional[Path] = None) -> bool:
        """
        Compare versions using vercmp-style logic with canonical normalization
        AND VCS placeholder override.
        
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
                    return False
                else:
                    # Remote is newer - check for VCS placeholder override
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
