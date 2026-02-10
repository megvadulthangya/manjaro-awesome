"""
Dependency Installer Module - CI-safe dependency installation with fallback
"""

import re
import time
import logging
from typing import List, Tuple, Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)


class DependencyInstaller:
    """CI-safe dependency installer with pacman -> yay fallback"""
    
    def __init__(self, shell_executor, debug_mode: bool = False):
        self.shell_executor = shell_executor
        self.debug_mode = debug_mode
    
    def _detect_failure_reason(self, output: str) -> str:
        """Detect the reason for pacman failure"""
        output_lower = output.lower()
        
        if "target not found" in output_lower or "could not find" in output_lower:
            return "target_not_found"
        elif "could not resolve" in output_lower:
            return "could_not_resolve"
        elif "failed to prepare transaction" in output_lower:
            return "failed_to_prepare_transaction"
        elif "unresolvable package conflicts detected" in output_lower:
            return "unresolvable_conflict"
        elif "are in conflict" in output_lower:
            return "package_conflict"
        else:
            return "unknown"
    
    def _clean_package_names(self, packages: List[str]) -> List[str]:
        """Clean and validate package names"""
        clean_deps = []
        
        for dep in packages:
            # Remove version constraints
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            
            # Skip empty or malformed
            if not dep_clean or not dep_clean.strip():
                continue
            
            # Skip package references with special characters
            if any(x in dep_clean for x in ['$', '{', '}', '(', ')', '[', ']']):
                continue
            
            # Must contain at least one alphanumeric character
            if not re.search(r'[a-zA-Z0-9]', dep_clean):
                continue
            
            # Handle known phantom packages
            if dep_clean == 'lgi':
                logger.warning("⚠️ Found phantom package 'lgi' - will be replaced with 'lua-lgi'")
                if 'lua-lgi' not in clean_deps:
                    clean_deps.append('lua-lgi')
                continue
            
            clean_deps.append(dep_clean)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_deps = []
        for dep in clean_deps:
            if dep not in seen:
                seen.add(dep)
                unique_deps.append(dep)
        
        return unique_deps
    
    def install_packages(self, packages: List[str], allow_aur: bool = True, mode: str = "build") -> bool:
        """
        Install packages with pacman -> yay fallback
        
        Args:
            packages: List of package names to install
            allow_aur: Whether to allow fallback to AUR (yay)
            mode: Installation mode ("build" for makedepends/checkdepends, "runtime" for depends)
            
        Returns:
            True if installation successful, False otherwise
        """
        if not packages:
            return True
        
        clean_packages = self._clean_package_names(packages)
        
        if not clean_packages:
            logger.info("No valid packages to install after cleaning")
            return True
        
        logger.info(f"DEP_INSTALL_START=1 count={len(clean_packages)} mode={mode}")
        
        # Convert to string for command
        pkgs_str = ' '.join(clean_packages)
        
        # --- FIRST ATTEMPT: Try pacman ---
        logger.info(f"DEP_INSTALL_ATTEMPT=1 manager=pacman")
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {pkgs_str}"
        
        result = self.shell_executor.run_command(
            cmd,
            log_cmd=True,
            check=False,
            timeout=1200
        )
        
        if result.returncode == 0:
            logger.info(f"DEP_INSTALL_OK=1 manager=pacman count={len(clean_packages)}")
            return True
        
        # Analyze failure
        combined_output = result.stdout + "\n" + result.stderr
        failure_reason = self._detect_failure_reason(combined_output)
        
        logger.warning(f"DEP_INSTALL_PACMAN_FAIL=1 reason={failure_reason} exitcode={result.returncode}")
        
        # Don't fallback to yay if AUR not allowed
        if not allow_aur:
            logger.error("DEP_INSTALL_YAY_SKIP=1 reason=aur_not_allowed")
            return False
        
        # --- SECOND ATTEMPT: Fallback to yay ---
        logger.info(f"DEP_INSTALL_ATTEMPT=2 manager=yay")
        
        # Use yay with --noconfirm to avoid prompts
        cmd = f"LC_ALL=C yay -S --needed --noconfirm {pkgs_str}"
        
        result = self.shell_executor.run_command(
            cmd,
            log_cmd=True,
            check=False,
            user="builder",
            timeout=1800
        )
        
        if result.returncode == 0:
            logger.info(f"DEP_INSTALL_OK=1 manager=yay count={len(clean_packages)}")
            return True
        
        # Analyze yay failure
        yay_output = result.stdout + "\n" + result.stderr
        yay_failure_reason = self._detect_failure_reason(yay_output)
        
        logger.error(f"DEP_INSTALL_YAY_FAIL=1 reason={yay_failure_reason} exitcode={result.returncode}")
        return False
    
    def extract_dependencies(self, pkg_dir: Path) -> Tuple[List[str], List[str], List[str]]:
        """
        Extract dependencies from .SRCINFO or PKGBUILD
        
        Args:
            pkg_dir: Path to package directory
            
        Returns:
            Tuple of (makedepends, checkdepends, depends)
        """
        srcinfo_path = pkg_dir / ".SRCINFO"
        srcinfo_content = None
        
        # First try to read existing .SRCINFO
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    srcinfo_content = f.read()
            except Exception as e:
                logger.warning(f"Failed to read existing .SRCINFO: {e}")
        
        # Generate .SRCINFO if not available
        if not srcinfo_content:
            try:
                result = self.shell_executor.run_command(
                    'makepkg --printsrcinfo',
                    cwd=pkg_dir,
                    capture=True,
                    check=False,
                    timeout=60
                )
                
                if result.returncode == 0 and result.stdout:
                    srcinfo_content = result.stdout
                    # Also write to .SRCINFO for future use
                    with open(srcinfo_path, 'w') as f:
                        f.write(srcinfo_content)
                else:
                    logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
                    return [], [], []
            except Exception as e:
                logger.warning(f"Error running makepkg --printsrcinfo: {e}")
                return [], [], []
        
        # Parse dependencies from SRCINFO content
        lines = srcinfo_content.strip().split('\n')
        
        makedepends = []
        checkdepends = []
        depends = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for dependency fields
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Extract all types of dependencies
                if key == 'makedepends':
                    makedepends.append(value)
                elif key == 'checkdepends':
                    checkdepends.append(value)
                elif key == 'depends':
                    depends.append(value)
        
        return makedepends, checkdepends, depends