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
from typing import Tuple, Optional, Any

class VersionManager:
    """Manages package version extraction, comparison, and parsing"""
    
    def __init__(self, shell_executor: Any, logger: Optional[logging.Logger] = None):
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

    def update_pkgbuild_version(self, pkg_dir: Path, new_pkgver: str, new_pkgrel: str = "1") -> bool:
        """Update pkgver and pkgrel in PKGBUILD file using regex"""
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return False
            
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            # Handle variable substitution or direct assignment
            content = re.sub(r'(^|\s)pkgver=[^\s]*', f'\\1pkgver={new_pkgver}', content)
            content = re.sub(r'(^|\s)pkgrel=[^\s]*', f'\\1pkgrel={new_pkgrel}', content)
            
            with open(pkgbuild_path, 'w') as f:
                f.write(content)
                
            self.logger.info(f"✅ Updated PKGBUILD to {new_pkgver}-{new_pkgrel}")
            
            # Update checksums
            self.logger.info("🔄 Updating checksums...")
            try:
                subprocess.run(["updpkgsums"], cwd=pkg_dir, check=False)
            except Exception:
                pass
                
            return True
        except Exception as e:
            self.logger.error(f"Failed to update PKGBUILD: {e}")
            return False

    def get_full_version_string(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> str:
        """Construct full version string"""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"

    def check_upstream_version(self, pkg_name: str, current_version: str) -> Tuple[bool, Optional[str]]:
        """Check AUR RPC for updates"""
        try:
            url = f"https://aur.archlinux.org/rpc/?v=5&type=info&arg[]={pkg_name}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data['resultcount'] > 0:
                    result = data['results'][0]
                    aur_version = result['Version']
                    
                    # Compare
                    if aur_version != current_version:
                        cmp_res = subprocess.run(
                            ['vercmp', aur_version, current_version],
                            capture_output=True, text=True, check=False
                        )
                        if cmp_res.returncode == 0 and int(cmp_res.stdout.strip()) > 0:
                            return True, aur_version
            
            return False, None
        except Exception:
            return False, None

    def get_local_git_version(self, pkg_dir: Path) -> Optional[str]:
        """
        Run pkgver() function if it exists to get dynamic version.
        Useful for -git packages.
        """
        try:
            # Check if PKGBUILD has pkgver() function
            with open(pkg_dir / "PKGBUILD", 'r') as f:
                if "pkgver()" not in f.read():
                    return None
            
            # Run makepkg -od to download sources (needed for pkgver())
            subprocess.run(
                ["makepkg", "-od", "--noconfirm"], 
                cwd=pkg_dir, check=False, capture_output=True
            )
            
            # Run makepkg --printsrcinfo again to get dynamic version
            # This triggers pkgver() execution
            res = subprocess.run(
                ["makepkg", "--printsrcinfo"],
                cwd=pkg_dir, capture_output=True, text=True, check=False
            )
            
            if res.returncode == 0:
                ver, rel, ep = self._parse_srcinfo_content(res.stdout)
                return self.get_full_version_string(ver, rel, ep)
            return None
        except Exception:
            return None