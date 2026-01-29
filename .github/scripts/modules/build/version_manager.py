"""
Version management for package building
Handles version extraction, comparison, PKGBUILD updates, and Upstream Checks.
"""

import re
import os
import subprocess
import logging
import requests
import json
from pathlib import Path
from typing import Tuple, Optional, Any, Dict

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
        """
        srcinfo_path = pkg_dir / ".SRCINFO"
        
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    return self._parse_srcinfo_content(f.read())
            except Exception:
                pass
        
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

    def update_pkgbuild_version(self, pkg_dir: Path, new_pkgver: str, new_pkgrel: str = "1") -> bool:
        """
        Update pkgver and pkgrel in PKGBUILD file using regex and update checksums
        """
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return False
            
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            # Update pkgver
            content = re.sub(r'(pkgver\s*=\s*)[^\s#\n]+', f'\\g<1>{new_pkgver}', content)
            # Reset pkgrel to 1 or specified value
            content = re.sub(r'(pkgrel\s*=\s*)[^\s#\n]+', f'\\g<1>{new_pkgrel}', content)
            
            with open(pkgbuild_path, 'w') as f:
                f.write(content)
                
            self.logger.info(f"✅ Updated PKGBUILD to version {new_pkgver}-{new_pkgrel}")
            
            # Update checksums
            self.logger.info("🔄 Updating checksums...")
            try:
                upd_res = self.shell_executor.run(
                    ["updpkgsums"], 
                    cwd=pkg_dir, 
                    check=False,
                    log_cmd=False
                )
                if upd_res.returncode == 0:
                    self.logger.info("✅ Checksums updated")
                else:
                    self.logger.warning("⚠️ updpkgsums failed, build might fail on validity check")
            except Exception:
                self.logger.warning("⚠️ updpkgsums not available or failed")
                
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
        """
        Check if upstream (AUR) has a newer version.
        
        Args:
            pkg_name: Package name
            current_version: Current known version (local or remote)
            
        Returns:
            Tuple (has_update, new_version)
        """
        try:
            # RPC call to AUR
            url = f"https://aur.archlinux.org/rpc/?v=5&type=info&arg[]={pkg_name}"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data['resultcount'] > 0:
                    result = data['results'][0]
                    aur_version = result['Version']
                    
                    # Compare
                    if aur_version != current_version:
                        # Use vercmp to be sure it's newer
                        cmp_res = self.shell_executor.run(
                            ['vercmp', aur_version, current_version],
                            capture=True, check=False, log_cmd=False
                        )
                        if cmp_res.returncode == 0 and int(cmp_res.stdout.strip()) > 0:
                            self.logger.info(f"🆕 Upstream update found: {aur_version} > {current_version}")
                            return True, aur_version
                        else:
                            self.logger.info(f"ℹ️ Upstream ({aur_version}) is not newer than {current_version}")
                            return False, aur_version
            
            return False, None
            
        except Exception as e:
            self.logger.warning(f"⚠️ Failed to check upstream for {pkg_name}: {e}")
            return False, None

    def get_git_latest_tag(self, repo_url: str) -> Optional[str]:
        """Get latest tag from a git repo (for VCS packages if needed)"""
        try:
            res = self.shell_executor.run(
                ["git", "ls-remote", "--tags", "--refs", "--sort=-v:refname", repo_url],
                capture=True, check=False
            )
            if res.returncode == 0 and res.stdout:
                # Get first tag line
                lines = res.stdout.strip().splitlines()
                if lines:
                    # format: hash refs/tags/v1.0.0
                    tag_ref = lines[0].split('\t')[-1]
                    tag = tag_ref.replace('refs/tags/', '')
                    return tag
            return None
        except Exception:
            return None