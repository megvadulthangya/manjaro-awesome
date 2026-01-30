"""
Version management module
"""

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class VersionManager:
    """Manages package versions and comparisons"""
    
    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
    
    def extract_version_from_srcinfo(self, pkg_dir):
        """Extract pkgver, pkgrel, and epoch from .SRCINFO or makepkg --printsrcinfo output"""
        srcinfo_path = Path(pkg_dir) / ".SRCINFO"
        
        # First try to read existing .SRCINFO
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    srcinfo_content = f.read()
                return self._parse_srcinfo_content(srcinfo_content)
            except Exception as e:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Failed to parse existing .SRCINFO: {e}", flush=True)
                else:
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
                if self.debug_mode:
                    print(f"🔧 [DEBUG] makepkg --printsrcinfo failed: {result.stderr}", flush=True)
                else:
                    logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
                raise RuntimeError(f"Failed to generate .SRCINFO: {result.stderr}")
                
        except Exception as e:
            if self.debug_mode:
                print(f"🔧 [DEBUG] Error running makepkg --printsrcinfo: {e}", flush=True)
            else:
                logger.error(f"Error running makepkg --printsrcinfo: {e}")
            raise
    
    def _parse_srcinfo_content(self, srcinfo_content):
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
    
    def get_full_version_string(self, pkgver, pkgrel, epoch):
        """Construct full version string from components"""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"
    
    def compare_versions(self, remote_version, pkgver, pkgrel, epoch):
        """
        Compare versions using vercmp-style logic
        
        Returns:
            True if NEW_VERSION > REMOTE_VERSION (should build), False otherwise
        """
        # If no remote version exists, we should build
        if not remote_version:
            if self.debug_mode:
                print(f"🔧 [DEBUG] Comparing Package: Remote(NONE) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (no remote)", flush=True)
            else:
                logger.info(f"Comparing Package: Remote(NONE) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (no remote)")
            return True
        
        # Build version strings for comparison
        new_version_str = f"{epoch or '0'}:{pkgver}-{pkgrel}"
        
        # Use vercmp for proper version comparison
        try:
            result = subprocess.run(['vercmp', new_version_str, remote_version], 
                                  capture_output=True, text=True, check=False)
            if result.returncode == 0:
                cmp_result = int(result.stdout.strip())
                
                if cmp_result > 0:
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (new version is newer)", flush=True)
                    else:
                        logger.info(f"Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (new version is newer)")
                    return True
                elif cmp_result == 0:
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (versions identical)", flush=True)
                    else:
                        logger.info(f"Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (versions identical)")
                    return False
                else:
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (remote version is newer)", flush=True)
                    else:
                        logger.info(f"Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (remote version is newer)")
                    return False
            else:
                # Fallback to simple comparison if vercmp fails
                if self.debug_mode:
                    print(f"🔧 [DEBUG] vercmp failed, using fallback comparison", flush=True)
                else:
                    logger.warning("vercmp failed, using fallback comparison")
                return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
                
        except Exception as e:
            if self.debug_mode:
                print(f"🔧 [DEBUG] vercmp comparison failed: {e}, using fallback", flush=True)
            else:
                logger.warning(f"vercmp comparison failed: {e}, using fallback")
            return self._fallback_version_comparison(remote_version, pkgver, pkgrel, epoch)
    
    def _fallback_version_comparison(self, remote_version, pkgver, pkgrel, epoch):
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
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (epoch {epoch_int} > {remote_epoch_int})", flush=True)
                    else:
                        logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (epoch {epoch_int} > {remote_epoch_int})")
                    return True
                else:
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch {epoch_int} <= {remote_epoch_int})", flush=True)
                    else:
                        logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch {epoch_int} <= {remote_epoch_int})")
                    return False
            except ValueError:
                if epoch != remote_epoch:
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch string mismatch)", flush=True)
                    else:
                        logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch string mismatch)")
                    return False
        
        # Compare pkgver
        if pkgver != remote_pkgver:
            if self.debug_mode:
                print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgver different)", flush=True)
            else:
                logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgver different)")
            return True
        
        # Compare pkgrel
        try:
            remote_pkgrel_int = int(remote_pkgrel)
            pkgrel_int = int(pkgrel)
            if pkgrel_int > remote_pkgrel_int:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgrel {pkgrel_int} > {remote_pkgrel_int})", flush=True)
                else:
                    logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgrel {pkgrel_int} > {remote_pkgrel_int})")
                return True
            else:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})", flush=True)
                else:
                    logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})")
                return False
        except ValueError:
            if pkgrel != remote_pkgrel:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel string mismatch)", flush=True)
                else:
                    logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel string mismatch)")
                return False
        
        # Versions are identical
        if self.debug_mode:
            print(f"🔧 [DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (versions identical)", flush=True)
        else:
            logger.info(f"Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (versions identical)")
        return False