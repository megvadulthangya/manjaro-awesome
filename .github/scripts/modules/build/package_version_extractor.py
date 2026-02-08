"""
Package Version Extractor Module - Extracts authoritative version from built package artifacts
"""

import os
import re
import tarfile
import logging
from pathlib import Path
from typing import Tuple, Optional, List, Dict

logger = logging.getLogger(__name__)


class PackageVersionExtractor:
    """Extracts authoritative version information from built package artifacts"""
    
    @staticmethod
    def extract_version_from_filename(filename: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Extract version components from package filename.
        
        Pattern: <pkgname>-<pkgver>-<pkgrel>-<arch>.pkg.tar.*
        May include epoch: <pkgname>-<epoch>-<pkgver>-<pkgrel>-<arch>.pkg.tar.*
        
        Returns: (pkgver, pkgrel, epoch) or None if cannot parse
        """
        # Remove extension
        if filename.endswith('.pkg.tar.zst'):
            base = filename[:-12]
        elif filename.endswith('.pkg.tar.xz'):
            base = filename[:-11]
        else:
            return None
        
        # Split by hyphens
        parts = base.split('-')
        
        if len(parts) < 3:
            return None
        
        # Try to parse from end: architecture, pkgrel, pkgver (possibly with epoch)
        # Look for architecture pattern at the end
        arch_patterns = ['x86_64', 'any', 'i686', 'aarch64', 'armv7h', 'armv6h']
        
        # Check if last part is an architecture
        if parts[-1] in arch_patterns:
            # Format: ...-pkgver-pkgrel-arch
            if len(parts) >= 3:
                pkgrel = parts[-2]
                pkgver_part = parts[-3]
                
                # Check if pkgver_part contains epoch (e.g., "1:r157.83dee18")
                epoch = None
                if ':' in pkgver_part:
                    epoch, pkgver = pkgver_part.split(':', 1)
                else:
                    pkgver = pkgver_part
                
                return pkgver, pkgrel, epoch
        
        return None
    
    @staticmethod
    def extract_version_from_pkginfo(package_path: Path) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Extract version from .PKGINFO file inside package archive.
        More reliable than filename parsing.
        
        Returns: (pkgver, pkgrel, epoch) or None if cannot extract
        """
        try:
            with tarfile.open(package_path, 'r:*') as tar:
                # Look for .PKGINFO file
                for member in tar.getmembers():
                    if member.name.endswith('.PKGINFO'):
                        # Extract the file
                        pkginfo_file = tar.extractfile(member)
                        if pkginfo_file:
                            content = pkginfo_file.read().decode('utf-8')
                            
                            # Parse .PKGINFO content
                            pkgver = None
                            pkgrel = None
                            epoch = None
                            
                            for line in content.split('\n'):
                                line = line.strip()
                                if line.startswith('pkgver = '):
                                    pkgver = line.split(' = ', 1)[1].strip()
                                elif line.startswith('pkgrel = '):
                                    pkgrel = line.split(' = ', 1)[1].strip()
                                elif line.startswith('epoch = '):
                                    epoch_val = line.split(' = ', 1)[1].strip()
                                    if epoch_val != '0':
                                        epoch = epoch_val
                            
                            if pkgver and pkgrel:
                                return pkgver, pkgrel, epoch
            return None
        except Exception as e:
            logger.debug(f"Failed to extract .PKGINFO from {package_path}: {e}")
            return None
    
    @staticmethod
    def get_authoritative_version(package_path: Path) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Get authoritative version from package file.
        Tries .PKGINFO first, falls back to filename parsing.
        
        Returns: (pkgver, pkgrel, epoch) or None if cannot determine
        """
        # Try .PKGINFO first (most reliable)
        version = PackageVersionExtractor.extract_version_from_pkginfo(package_path)
        if version:
            logger.debug(f"Extracted version from .PKGINFO: {version}")
            return version
        
        # Fall back to filename parsing
        version = PackageVersionExtractor.extract_version_from_filename(package_path.name)
        if version:
            logger.debug(f"Extracted version from filename: {version}")
            return version
        
        logger.warning(f"Could not extract version from {package_path}")
        return None
    
    @staticmethod
    def get_authoritative_version_from_built_files(built_files: List[Path]) -> Optional[Tuple[str, str, Optional[str]]]:
        """
        Get authoritative version from list of built package files.
        For split packages, all should have same version - use first successful extraction.
        
        Returns: (pkgver, pkgrel, epoch) or None if cannot determine
        """
        for package_file in built_files:
            version = PackageVersionExtractor.get_authoritative_version(package_file)
            if version:
                return version
        
        return None