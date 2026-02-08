"""
Version Manager Module - Handles version extraction, comparison, and management
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Tuple, Optional

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
        import re
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
    
    def compare_versions(self, remote_version: Optional[str], pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        Compare versions using vercmp-style logic with canonical normalization
        
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
        
        # Use vercmp for proper version comparison
        try:
            result = subprocess.run(['vercmp', norm_source, norm_remote], 
                                  capture_output=True, text=True, check=False)
            if result.returncode == 0:
                cmp_result = int(result.stdout.strip())
                
                if cmp_result > 0:
                    logger.info(f"[DEBUG] Comparing Package: Remote(raw={remote_version}, norm={norm_remote}) vs New(raw={source_version}, norm={norm_source}) -> BUILD TRIGGERED (new version is newer)")
                    return True
                elif cmp_result == 0:
                    logger.info(f"[DEBUG] Comparing Package: Remote(raw={remote_version}, norm={norm_remote}) vs New(raw={source_version}, norm={norm_source}) -> SKIP (versions identical)")
                    return False
                else:
                    logger.info(f"[DEBUG] Comparing Package: Remote(raw={remote_version}, norm={norm_remote}) vs New(raw={source_version}, norm={norm_source}) -> SKIP (remote version is newer)")
                    return False
            else:
                # Fallback to simple comparison if vercmp fails
                logger.warning("vercmp failed, using fallback comparison")
                return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
                
        except Exception as e:
            logger.warning(f"vercmp comparison failed: {e}, using fallback")
            return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
    
    def _fallback_version_comparison(self, remote_version: str, pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """Fallback version comparison when vercmp is not available"""
        # Normalize versions for fallback comparison too
        source_version = self.get_full_version_string(pkgver, pkgrel, epoch)
        norm_remote = self.normalize_version_string(remote_version)
        norm_source = self.normalize_version_string(source_version)
        
        logger.info(f"[DEBUG] Fallback comparison: Remote(norm={norm_remote}) vs New(norm={norm_source})")
        
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
                    logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> BUILD TRIGGERED (epoch {epoch_int} > {remote_epoch_int})")
                    return True
                else:
                    logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> SKIP (epoch {epoch_int} <= {remote_epoch_int})")
                    return False
            except ValueError:
                if source_epoch != remote_epoch:
                    logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> SKIP (epoch string mismatch)")
                    return False
        
        # Compare pkgver
        if source_pkgver != remote_pkgver:
            logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> BUILD TRIGGERED (pkgver different)")
            return True
        
        # Compare pkgrel
        try:
            remote_pkgrel_int = int(remote_pkgrel)
            pkgrel_int = int(source_pkgrel)
            if pkgrel_int > remote_pkgrel_int:
                logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> BUILD TRIGGERED (pkgrel {pkgrel_int} > {remote_pkgrel_int})")
                return True
            else:
                logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})")
                return False
        except ValueError:
            if source_pkgrel != remote_pkgrel:
                logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> SKIP (pkgrel string mismatch)")
                return False
        
        # Versions are identical
        logger.info(f"[DEBUG] Comparing Package: Remote(norm={norm_remote}) vs New(norm={norm_source}) -> SKIP (versions identical)")
        return False
