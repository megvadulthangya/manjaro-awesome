"""
Version management for package building
Handles version extraction, comparison, and SRCINFO parsing
Extracted from build_engine.py with enhanced functionality
"""

import re
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any


class VersionManager:
    """Manages package version extraction, comparison, and parsing"""
    
    def __init__(self, shell_executor, logger: Optional[logging.Logger] = None):
        """
        Initialize VersionManager
        
        Args:
            shell_executor: ShellExecutor instance for command execution
            logger: Optional logger instance
        """
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
    
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
                self.logger.warning(f"Failed to parse existing .SRCINFO: {e}")
        
        # Generate .SRCINFO using makepkg --printsrcinfo
        try:
            result = self.shell_executor.run(
                ['makepkg', '--printsrcinfo'],
                cwd=pkg_dir,
                capture=True,
                text=True,
                check=False,
                log_cmd=False
            )
            
            if result.returncode == 0 and result.stdout:
                # Also write to .SRCINFO for future use
                with open(srcinfo_path, 'w') as f:
                    f.write(result.stdout)
                return self._parse_srcinfo_content(result.stdout)
            else:
                self.logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
                raise RuntimeError(f"Failed to generate .SRCINFO: {result.stderr}")
                
        except Exception as e:
            self.logger.error(f"Error running makepkg --printsrcinfo: {e}")
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
    
    def compare_versions(self, remote_version: Optional[str], pkgver: str, pkgrel: str, 
                        epoch: Optional[str]) -> bool:
        """
        Compare versions using vercmp-style logic
        
        Returns:
            True if AUR_VERSION > REMOTE_VERSION (should build), False otherwise
        """
        # If no remote version exists, we should build
        if not remote_version:
            self.logger.debug(f"[DEBUG] Comparing Package: Remote(NONE) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (no remote)")
            return True
        
        # Parse remote version
        remote_epoch = None
        remote_pkgver = None
        remote_pkgrel = None
        
        # Check if remote has epoch
        if ':' in remote_version:
            remote_epoch_str, rest = remote_version.split(':', 1)
            remote_epoch = remote_epoch_str
            if '-' in rest:
                remote_pkgver, remote_pkgrel = rest.split('-', 1)
            else:
                remote_pkgver = rest
                remote_pkgrel = "1"
        else:
            if '-' in remote_version:
                remote_pkgver, remote_pkgrel = remote_version.split('-', 1)
            else:
                remote_pkgver = remote_version
                remote_pkgrel = "1"
        
        # Build version strings for comparison
        new_version_str = f"{epoch or '0'}:{pkgver}-{pkgrel}"
        remote_version_str = f"{remote_epoch or '0'}:{remote_pkgver}-{remote_pkgrel}"
        
        # Use vercmp for proper version comparison
        try:
            result = self.shell_executor.run(
                ['vercmp', new_version_str, remote_version_str], 
                capture=True,
                text=True,
                check=False,
                log_cmd=False
            )
            
            if result.returncode == 0:
                cmp_result = int(result.stdout.strip())
                
                if cmp_result > 0:
                    self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (new version is newer)")
                    return True
                elif cmp_result == 0:
                    self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (versions identical)")
                    return False
                else:
                    self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (remote version is newer)")
                    return False
            else:
                # Fallback to simple comparison if vercmp fails
                self.logger.warning("vercmp failed, using fallback comparison")
                return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
                
        except Exception as e:
            self.logger.warning(f"vercmp comparison failed: {e}, using fallback")
            return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
    
    def _fallback_version_comparison(self, remote_version: str, pkgver: str, pkgrel: str, 
                                   epoch: Optional[str]) -> bool:
        """Fallback version comparison when vercmp is not available"""
        # Parse remote version
        remote_epoch = None
        remote_pkgver = None
        remote_pkgrel = None
        
        if ':' in remote_version:
            remote_epoch_str, rest = remote_version.split(':', 1)
            remote_epoch = remote_epoch_str
            if '-' in rest:
                remote_pkgver, remote_pkgrel = rest.split('-', 1)
            else:
                remote_pkgver = rest
                remote_pkgrel = "1"
        else:
            if '-' in remote_version:
                remote_pkgver, remote_pkgrel = remote_version.split('-', 1)
            else:
                remote_pkgver = remote_version
                remote_pkgrel = "1"
        
        # Compare epochs first
        if epoch != remote_epoch:
            try:
                epoch_int = int(epoch or 0)
                remote_epoch_int = int(remote_epoch or 0)
                if epoch_int > remote_epoch_int:
                    self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (epoch {epoch_int} > {remote_epoch_int})")
                    return True
                else:
                    self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch {epoch_int} <= {remote_epoch_int})")
                    return False
            except ValueError:
                if epoch != remote_epoch:
                    self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch string mismatch)")
                    return False
        
        # Compare pkgver
        if pkgver != remote_pkgver:
            self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgver different)")
            return True
        
        # Compare pkgrel
        try:
            remote_pkgrel_int = int(remote_pkgrel)
            pkgrel_int = int(pkgrel)
            if pkgrel_int > remote_pkgrel_int:
                self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgrel {pkgrel_int} > {remote_pkgrel_int})")
                return True
            else:
                self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})")
                return False
        except ValueError:
            if pkgrel != remote_pkgrel:
                self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel string mismatch)")
                return False
        
        # Versions are identical
        self.logger.debug(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (versions identical)")
        return False
    
    def parse_package_filename(self, filename: str) -> Optional[Tuple[str, str]]:
        """Parse package filename to extract name and version"""
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            if len(parts) < 4:
                return None
            
            # Try to find where package name ends
            for i in range(len(parts) - 3, 0, -1):
                potential_name = '-'.join(parts[:i])
                remaining = parts[i:]
                
                if len(remaining) >= 3:
                    # Check for epoch format (e.g., "2-26.1.9-1")
                    if remaining[0].isdigit() and '-' in '-'.join(remaining[1:]):
                        epoch = remaining[0]
                        version_part = remaining[1]
                        release_part = remaining[2]
                        version_str = f"{epoch}:{version_part}-{release_part}"
                        return potential_name, version_str
                    # Standard format (e.g., "26.1.9-1")
                    elif any(c.isdigit() for c in remaining[0]) and remaining[1].isdigit():
                        version_part = remaining[0]
                        release_part = remaining[1]
                        version_str = f"{version_part}-{release_part}"
                        return potential_name, version_str
        
        except Exception as e:
            self.logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None