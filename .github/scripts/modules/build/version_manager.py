"""
Version management for package building
Handles version extraction, comparison, and PKGBUILD updates
"""

import re
import subprocess
import logging
from pathlib import Path
from typing import Tuple, Optional, Any

class VersionManager:
    """Manages package version extraction, comparison, and parsing"""
    
    def __init__(self, shell_executor: Any, logger: Optional[logging.Logger] = None):
        """
        Initialize VersionManager
        
        Args:
            shell_executor: ShellExecutor instance
            logger: Optional logger instance
        """
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
    
    def extract_from_pkgbuild(self, pkg_dir: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract version information from PKGBUILD using makepkg --printsrcinfo
        
        Args:
            pkg_dir: Package directory
            
        Returns:
            Tuple (pkgver, pkgrel, epoch)
        """
        try:
            result = subprocess.run(
                ['makepkg', '--printsrcinfo'],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=300
            )
            
            if result.returncode == 0 and result.stdout:
                return self._parse_srcinfo_content(result.stdout)
            
            self.logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
            return None, None, None
            
        except Exception as e:
            self.logger.error(f"Error extracting version: {e}")
            return None, None, None

    def extract_version_from_srcinfo(self, pkg_dir: Path) -> Tuple[str, str, Optional[str]]:
        """
        Extract version from .SRCINFO file or generate it
        
        Args:
            pkg_dir: Package directory
            
        Returns:
            Tuple (pkgver, pkgrel, epoch)
        """
        srcinfo_path = pkg_dir / ".SRCINFO"
        
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    return self._parse_srcinfo_content(f.read())
            except Exception:
                pass
        
        # Fallback to generation
        pkgver, pkgrel, epoch = self.extract_from_pkgbuild(pkg_dir)
        if pkgver and pkgrel:
            return pkgver, pkgrel, epoch
        
        raise ValueError("Could not extract version from SRCINFO or PKGBUILD")

    def _parse_srcinfo_content(self, content: str) -> Tuple[str, str, Optional[str]]:
        """Parse SRCINFO content"""
        pkgver = None
        pkgrel = None
        epoch = None
        
        for line in content.splitlines():
            line = line.strip()
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
        
        return pkgver, pkgrel, epoch

    def update_pkgbuild_version(self, pkg_dir: Path, new_pkgver: str, new_pkgrel: str) -> bool:
        """
        Update pkgver and pkgrel in PKGBUILD file using regex
        
        Args:
            pkg_dir: Package directory
            new_pkgver: New pkgver
            new_pkgrel: New pkgrel
            
        Returns:
            True if successful
        """
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return False
            
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            content = re.sub(r'(pkgver\s*=\s*)[^\s#\n]+', f'\\g<1>{new_pkgver}', content)
            content = re.sub(r'(pkgrel\s*=\s*)[^\s#\n]+', f'\\g<1>{new_pkgrel}', content)
            
            with open(pkgbuild_path, 'w') as f:
                f.write(content)
                
            self.logger.info(f"Updated PKGBUILD: {new_pkgver}-{new_pkgrel}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update PKGBUILD: {e}")
            return False

    def get_full_version_string(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> str:
        """Construct full version string"""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"

    def compare_versions(self, remote_version: Optional[str], pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        Compare versions. Returns True if local is newer (needs build).
        """
        if not remote_version:
            return True
            
        current = self.get_full_version_string(pkgver, pkgrel, epoch)
        
        try:
            res = self.shell_executor.run(
                ['vercmp', current, remote_version],
                capture=True, check=False, log_cmd=False
            )
            if res.returncode == 0:
                # 1 if current > remote
                return int(res.stdout.strip()) > 0
        except Exception:
            pass
            
        return current != remote_version