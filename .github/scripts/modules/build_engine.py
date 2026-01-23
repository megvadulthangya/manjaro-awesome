"""
Build Engine Module - Handles AUR, makepkg, and package building logic
"""

import os
import re
import sys
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Import config for DEBUG_MODE
try:
    import config
    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False


class BuildEngine:
    """Handles AUR package building, version comparison, and dependency resolution"""
    
    def __init__(self, config_dict: dict):
        """
        Initialize BuildEngine with configuration
        
        Args:
            config_dict: Dictionary containing:
                - repo_root: Repository root directory
                - output_dir: Output directory for built packages
                - aur_build_dir: AUR build directory
                - aur_urls: AUR URL templates
                - repo_name: Repository name
        """
        self.repo_root = Path(config_dict['repo_root'])
        self.output_dir = Path(config_dict['output_dir'])
        self.aur_build_dir = Path(config_dict['aur_build_dir'])
        self.aur_urls = config_dict['aur_urls']
        self.repo_name = config_dict.get('repo_name', '')
        
        # State
        self.hokibot_data = []
        self.rebuilt_local_packages = []
        self.skipped_packages = []
        self.built_packages = []
        
        # Statistics
        self.stats = {
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
        }
        
        # Debug mode from config
        self.debug_mode = HAS_CONFIG and getattr(config, 'DEBUG_MODE', False)
    
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
    
    def compare_versions(self, remote_version: Optional[str], pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        Compare versions using vercmp-style logic
        
        Returns:
            True if AUR_VERSION > REMOTE_VERSION (should build), False otherwise
        """
        # If no remote version exists, we should build
        if not remote_version:
            logger.info(f"[DEBUG] Comparing Package: Remote(NONE) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (no remote)")
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
            result = subprocess.run(['vercmp', new_version_str, remote_version_str], 
                                  capture_output=True, text=True, check=False)
            if result.returncode == 0:
                cmp_result = int(result.stdout.strip())
                
                if cmp_result > 0:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> BUILD TRIGGERED (new version is newer)")
                    return True
                elif cmp_result == 0:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (versions identical)")
                    return False
                else:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({pkgver}-{pkgrel}) -> SKIP (remote version is newer)")
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
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (epoch {epoch_int} > {remote_epoch_int})")
                    return True
                else:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch {epoch_int} <= {remote_epoch_int})")
                    return False
            except ValueError:
                if epoch != remote_epoch:
                    logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (epoch string mismatch)")
                    return False
        
        # Compare pkgver
        if pkgver != remote_pkgver:
            logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgver different)")
            return True
        
        # Compare pkgrel
        try:
            remote_pkgrel_int = int(remote_pkgrel)
            pkgrel_int = int(pkgrel)
            if pkgrel_int > remote_pkgrel_int:
                logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> BUILD TRIGGERED (pkgrel {pkgrel_int} > {remote_pkgrel_int})")
                return True
            else:
                logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel {pkgrel_int} <= {remote_pkgrel_int})")
                return False
        except ValueError:
            if pkgrel != remote_pkgrel:
                logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (pkgrel string mismatch)")
                return False
        
        # Versions are identical
        logger.info(f"[DEBUG] Comparing Package: Remote({remote_version}) vs New({epoch or ''}{pkgver}-{pkgrel}) -> SKIP (versions identical)")
        return False
    
    def clean_workspace(self, pkg_dir: Path):
        """Clean workspace before building to avoid contamination"""
        logger.info(f"🧹 Cleaning workspace for {pkg_dir.name}...")
        
        # Clean src/ directory if exists
        src_dir = pkg_dir / "src"
        if src_dir.exists():
            try:
                shutil.rmtree(src_dir, ignore_errors=True)
                logger.info(f"  Cleaned src/ directory")
            except Exception as e:
                logger.warning(f"  Could not clean src/: {e}")
        
        # Clean pkg/ directory if exists
        pkg_build_dir = pkg_dir / "pkg"
        if pkg_build_dir.exists():
            try:
                shutil.rmtree(pkg_build_dir, ignore_errors=True)
                logger.info(f"  Cleaned pkg/ directory")
            except Exception as e:
                logger.warning(f"  Could not clean pkg/: {e}")
        
        # Clean any leftover .tar.* files
        for leftover in pkg_dir.glob("*.pkg.tar.*"):
            try:
                leftover.unlink()
                logger.info(f"  Removed leftover package: {leftover.name}")
            except Exception as e:
                logger.warning(f"  Could not remove {leftover}: {e}")
    
    def install_dependencies_strict(self, deps: List[str]) -> bool:
        """STRICT dependency resolution: pacman first, then yay"""
        if not deps:
            return True
        
        print(f"\nInstalling {len(deps)} dependencies...")
        logger.info(f"Dependencies to install: {deps}")
        
        # Clean dependency names
        clean_deps = []
        phantom_packages = set()
        
        for dep in deps:
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            if dep_clean and dep_clean.strip() and not any(x in dep_clean for x in ['$', '{', '}', '(', ')', '[', ']']):
                if re.search(r'[a-zA-Z0-9]', dep_clean):
                    # FIX: Hard-filter out phantom package 'lgi'
                    if dep_clean == 'lgi':
                        phantom_packages.add('lgi')
                        logger.warning(f"⚠️ Found phantom package 'lgi' - will be replaced with 'lua-lgi'")
                        continue
                    clean_deps.append(dep_clean)
        
        # Remove any duplicate entries
        clean_deps = list(dict.fromkeys(clean_deps))
        
        # FIX: If we removed 'lgi', ensure 'lua-lgi' is present
        if 'lgi' in phantom_packages and 'lua-lgi' not in clean_deps:
            logger.info("Adding 'lua-lgi' to replace phantom package 'lgi'")
            clean_deps.append('lua-lgi')
        
        if not clean_deps:
            logger.info("No valid dependencies to install after cleaning")
            return True
        
        logger.info(f"Valid dependencies to install: {clean_deps}")
        if phantom_packages:
            logger.info(f"Phantom packages removed: {', '.join(phantom_packages)}")
        
        # Try pacman first - ensure pacman databases are synced
        deps_str = ' '.join(clean_deps)
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {deps_str}"
        result = self._run_cmd(cmd, log_cmd=True, check=False, timeout=1200)
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        logger.warning(f"⚠️ pacman failed for some dependencies (exit code: {result.returncode})")
        
        # Fallback to AUR (yay) WITHOUT sudo - but first sync pacman
        cmd = f"sudo LC_ALL=C pacman -Sy && LC_ALL=C yay -S --needed --noconfirm {deps_str}"
        result = self._run_cmd(cmd, log_cmd=True, check=False, user="builder", timeout=1800)
        
        if result.returncode == 0:
            logger.info("✅ Dependencies installed via yay")
            return True
        
        logger.error(f"❌ Both pacman and yay failed for dependencies")
        return False
    
    def _run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, log_cmd=False, timeout=1800):
        """
        Run command with comprehensive logging and timeout.
        
        CRITICAL FIX: When DEBUG_MODE is True, bypass logger and print directly to stdout
        to ensure output appears in CI/CD console.
        """
        if log_cmd:
            if self.debug_mode:
                print(f"🔧 [DEBUG] RUNNING COMMAND: {cmd}", flush=True)
            else:
                logger.info(f"RUNNING COMMAND: {cmd}")
        
        if cwd is None:
            cwd = self.repo_root
        
        if user:
            env = os.environ.copy()
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            env['LC_ALL'] = 'C'
            
            try:
                sudo_cmd = ['sudo', '-u', user]
                if shell:
                    sudo_cmd.extend(['bash', '-c', f'cd "{cwd}" && {cmd}'])
                else:
                    sudo_cmd.extend(cmd)
                
                result = subprocess.run(
                    sudo_cmd,
                    capture_output=capture,
                    text=True,
                    check=check,
                    env=env,
                    timeout=timeout
                )
                
                # CRITICAL: When in debug mode, bypass logger and print directly
                if log_cmd or self.debug_mode:
                    if self.debug_mode:
                        if result.stdout:
                            print(f"🔧 [DEBUG] STDOUT:\n{result.stdout}", flush=True)
                        if result.stderr:
                            print(f"🔧 [DEBUG] STDERR:\n{result.stderr}", flush=True)
                        print(f"🔧 [DEBUG] EXIT CODE: {result.returncode}", flush=True)
                    else:
                        if result.stdout:
                            logger.info(f"STDOUT: {result.stdout[:500]}")
                        if result.stderr:
                            logger.info(f"STDERR: {result.stderr[:500]}")
                        logger.info(f"EXIT CODE: {result.returncode}")
                
                # CRITICAL: If command failed and we're in debug mode, print full output
                if result.returncode != 0 and self.debug_mode:
                    print(f"❌ [DEBUG] COMMAND FAILED: {cmd}", flush=True)
                    if result.stdout and len(result.stdout) > 500:
                        print(f"❌ [DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                    if result.stderr and len(result.stderr) > 500:
                        print(f"❌ [DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)
                
                return result
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                if self.debug_mode:
                    print(f"❌ [DEBUG] {error_msg}", flush=True)
                logger.error(error_msg)
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd or self.debug_mode:
                    error_msg = f"Command failed: {cmd}"
                    if self.debug_mode:
                        print(f"❌ [DEBUG] {error_msg}", flush=True)
                        if hasattr(e, 'stdout') and e.stdout:
                            print(f"❌ [DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                        if hasattr(e, 'stderr') and e.stderr:
                            print(f"❌ [DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                    else:
                        logger.error(error_msg)
                if check:
                    raise
                return e
        else:
            try:
                env = os.environ.copy()
                env['LC_ALL'] = 'C'
                
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    shell=shell,
                    capture_output=capture,
                    text=True,
                    check=check,
                    env=env,
                    timeout=timeout
                )
                
                # CRITICAL: When in debug mode, bypass logger and print directly
                if log_cmd or self.debug_mode:
                    if self.debug_mode:
                        if result.stdout:
                            print(f"🔧 [DEBUG] STDOUT:\n{result.stdout}", flush=True)
                        if result.stderr:
                            print(f"🔧 [DEBUG] STDERR:\n{result.stderr}", flush=True)
                        print(f"🔧 [DEBUG] EXIT CODE: {result.returncode}", flush=True)
                    else:
                        if result.stdout:
                            logger.info(f"STDOUT: {result.stdout[:500]}")
                        if result.stderr:
                            logger.info(f"STDERR: {result.stderr[:500]}")
                        logger.info(f"EXIT CODE: {result.returncode}")
                
                # CRITICAL: If command failed and we're in debug mode, print full output
                if result.returncode != 0 and self.debug_mode:
                    print(f"❌ [DEBUG] COMMAND FAILED: {cmd}", flush=True)
                    if result.stdout and len(result.stdout) > 500:
                        print(f"❌ [DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                    if result.stderr and len(result.stderr) > 500:
                        print(f"❌ [DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)
                
                return result
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                if self.debug_mode:
                    print(f"❌ [DEBUG] {error_msg}", flush=True)
                logger.error(error_msg)
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd or self.debug_mode:
                    error_msg = f"Command failed: {cmd}"
                    if self.debug_mode:
                        print(f"❌ [DEBUG] {error_msg}", flush=True)
                        if hasattr(e, 'stdout') and e.stdout:
                            print(f"❌ [DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                        if hasattr(e, 'stderr') and e.stderr:
                            print(f"❌ [DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                    else:
                        logger.error(error_msg)
                if check:
                    raise
                return e