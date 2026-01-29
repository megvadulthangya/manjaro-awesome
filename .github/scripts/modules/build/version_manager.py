"""
Version management for package building
Handles version extraction, comparison, PKGBUILD updates, and Upstream Checks.
"""

import re
import os
import subprocess
import logging
import requests
from pathlib import Path
from typing import Tuple, Optional, List

class VersionManager:
    """Manages package version extraction, comparison, and parsing"""
    
    def __init__(self, shell_executor, logger: Optional[logging.Logger] = None):
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)

    def extract_from_pkgbuild(self, pkg_dir: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract version from PKGBUILD using makepkg --printsrcinfo"""
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
            
            return None, None, None
        except Exception as e:
            self.logger.error(f"Error extracting version: {e}")
            return None, None, None

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

    def extract_dependencies(self, pkg_dir: Path) -> List[str]:
        """Extract depends and makedepends from SRCINFO"""
        deps = []
        try:
            # We assume makepkg --printsrcinfo works even if deps are missing
            result = subprocess.run(
                ['makepkg', '--printsrcinfo'],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if '=' in line:
                        key, val = line.split('=', 1)
                        key = key.strip()
                        val = val.strip()
                        if key in ('depends', 'makedepends'):
                            # Remove version constraints (e.g., 'gtk3>=3.0')
                            pkg_name = re.split(r'[<>=]', val)[0]
                            if pkg_name:
                                deps.append(pkg_name)
        except Exception as e:
            self.logger.error(f"Failed to extract dependencies: {e}")
            
        return deps

    def get_full_version_string(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> str:
        """Construct full version string"""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"

    def check_upstream_version(self, pkg_name: str) -> Optional[str]:
        """Check AUR RPC for version string"""
        try:
            url = f"https://aur.archlinux.org/rpc/?v=5&type=info&arg[]={pkg_name}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data['resultcount'] > 0:
                    result = data['results'][0]
                    return result['Version']
            return None
        except Exception:
            return None

    def get_local_git_version(self, pkg_dir: Path) -> Optional[str]:
        """
        Run pkgver() function if it exists to get dynamic version.
        Useful for -git packages.
        """
        try:
            if not (pkg_dir / "PKGBUILD").exists():
                return None

            with open(pkg_dir / "PKGBUILD", 'r') as f:
                if "pkgver()" not in f.read():
                    return None
            
            # Download sources to calculate version
            subprocess.run(
                ["makepkg", "-od", "--noconfirm", "--noprepare"], 
                cwd=pkg_dir, check=False, capture_output=True
            )
            
            # Run printsrcinfo to get dynamic version
            res = subprocess.run(
                ["makepkg", "--printsrcinfo"],
                cwd=pkg_dir, capture_output=True, text=True, check=False
            )
            
            if res.returncode == 0:
                ver, rel, ep = self._parse_srcinfo_content(res.stdout)
                if ver and rel:
                    return self.get_full_version_string(ver, rel, ep)
            return None
        except Exception:
            return None

    def compare_versions(self, ver_a: str, ver_b: str) -> int:
        """
        Compare two versions using vercmp.
        Returns: >0 if a > b, <0 if a < b, 0 if equal
        """
        if not ver_a: return -1
        if not ver_b: return 1
        if ver_a == ver_b: return 0
        
        try:
            res = subprocess.run(
                ['vercmp', ver_a, ver_b],
                capture_output=True, text=True, check=False
            )
            if res.returncode == 0:
                return int(res.stdout.strip())
        except Exception:
            pass
            
        # Fallback simple string compare
        return 1 if ver_a != ver_b else 0