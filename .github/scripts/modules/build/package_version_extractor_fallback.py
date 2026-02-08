"""
Package Version Extractor Fallback Module - Safely extracts version from PKGBUILD without execution
"""

import re
import logging
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


class PackageVersionExtractorFallback:
    """Safely extracts version information from PKGBUILD without executing it"""
    
    @staticmethod
    def extract_version_from_pkgbuild(pkgbuild_path: Path) -> Tuple[str, str, Optional[str]]:
        """
        Extract pkgver, pkgrel, and epoch from PKGBUILD file without executing it.
        
        Args:
            pkgbuild_path: Path to PKGBUILD file
            
        Returns:
            Tuple of (pkgver, pkgrel, epoch)
            
        Raises:
            ValueError: If cannot extract pkgver and pkgrel
        """
        if not pkgbuild_path.exists():
            raise ValueError(f"PKGBUILD not found: {pkgbuild_path}")
        
        try:
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Remove comments to avoid matching commented assignments
            lines = []
            for line in content.split('\n'):
                # Remove everything after # (comments)
                if '#' in line:
                    line = line[:line.index('#')]
                lines.append(line)
            
            # Join lines back (handling line continuations)
            cleaned_content = ''
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.endswith('\\'):
                    # Continuation line
                    cleaned_content += line.rstrip('\\')
                    i += 1
                    while i < len(lines) and lines[i].endswith('\\'):
                        cleaned_content += lines[i].rstrip('\\')
                        i += 1
                    if i < len(lines):
                        cleaned_content += lines[i]
                else:
                    cleaned_content += line
                cleaned_content += '\n'
                i += 1
            
            # Look for assignments (case-insensitive, with optional whitespace)
            pkgver = None
            pkgrel = None
            epoch = None
            
            # Regex patterns for assignments (handles pkgver=value, pkgver = value, etc.)
            pkgver_pattern = re.compile(r'^\s*pkgver\s*=\s*["\']?([^"\'\n]+)["\']?', re.IGNORECASE | re.MULTILINE)
            pkgrel_pattern = re.compile(r'^\s*pkgrel\s*=\s*["\']?([^"\'\n]+)["\']?', re.IGNORECASE | re.MULTILINE)
            epoch_pattern = re.compile(r'^\s*epoch\s*=\s*["\']?([^"\'\n]+)["\']?', re.IGNORECASE | re.MULTILINE)
            
            pkgver_match = pkgver_pattern.search(cleaned_content)
            if pkgver_match:
                pkgver = pkgver_match.group(1).strip()
            
            pkgrel_match = pkgrel_pattern.search(cleaned_content)
            if pkgrel_match:
                pkgrel = pkgrel_match.group(1).strip()
            
            epoch_match = epoch_pattern.search(cleaned_content)
            if epoch_match:
                epoch_val = epoch_match.group(1).strip()
                if epoch_val != '0':
                    epoch = epoch_val
            
            if not pkgver or not pkgrel:
                raise ValueError(f"Cannot extract pkgver and pkgrel from PKGBUILD")
            
            return pkgver, pkgrel, epoch
            
        except Exception as e:
            raise ValueError(f"Failed to parse PKGBUILD: {e}")
    
    @staticmethod
    def safe_extract_version(pkg_dir: Path, pkg_name: str) -> Tuple[Optional[str], Optional[str], Optional[str], bool]:
        """
        Safely extract version with fallback, logging appropriate messages.
        
        Args:
            pkg_dir: Package directory
            pkg_name: Package name for logging
            
        Returns:
            Tuple of (pkgver, pkgrel, epoch, fallback_used)
            Returns (None, None, None, False) if extraction fails completely
        """
        try:
            # First try the normal method (makepkg --printsrcinfo)
            # Import here to avoid circular import issues
            from modules.build.version_manager import VersionManager
            vm = VersionManager()
            pkgver, pkgrel, epoch = vm.extract_version_from_srcinfo(pkg_dir)
            return pkgver, pkgrel, epoch, False
        except Exception as e:
            logger.warning(f"Primary version extraction failed for {pkg_name}: {e}")
            
            # Try fallback
            try:
                pkgbuild_path = pkg_dir / "PKGBUILD"
                pkgver, pkgrel, epoch = PackageVersionExtractorFallback.extract_version_from_pkgbuild(pkgbuild_path)
                logger.info(f"PKGBUILD_VERSION_FALLBACK_USED=1 pkg={pkg_name}")
                return pkgver, pkgrel, epoch, True
            except Exception as fallback_error:
                logger.error(f"Fallback version extraction also failed for {pkg_name}: {fallback_error}")
                logger.info(f"PKGBUILD_VERSION_FALLBACK_FAIL=1 pkg={pkg_name}")
                return None, None, None, False
