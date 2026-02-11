"""
Dependency Installer Module - CI-safe dependency installation with fallback
Now with per-package session tracking + conflict resolution.
"""

import re
import time
import logging
from typing import List, Tuple, Optional, Dict, Set
from pathlib import Path

import config  # for INSTALL_RUNTIME_DEPS_IN_CI and CONFLICT_REMOVE_ALLOWLIST

logger = logging.getLogger(__name__)


class DependencyInstaller:
    """CI-safe dependency installer with pacman -> yay fallback and session cleanup"""
    
    # Hardcoded provider map for deterministic resolution
    PROVIDER_MAP = {
        "sdl2": "sdl2-compat"
    }
    
    def __init__(self, shell_executor, debug_mode: bool = False):
        self.shell_executor = shell_executor
        self.debug_mode = debug_mode
        
        # Session tracking
        self.session_active = False
        self.session_baseline: Optional[Set[str]] = None
        self.session_pkg_name: Optional[str] = None
    
    def _snapshot_explicit(self) -> Set[str]:
        """
        Take a snapshot of currently explicitly installed packages.
        Uses: pacman -Qqe
        Returns set of package names.
        """
        cmd = "LC_ALL=C pacman -Qqe"
        result = self.shell_executor.run_command(
            cmd, log_cmd=False, check=False, timeout=60
        )
        if result.returncode == 0 and result.stdout:
            pkgs = {line.strip() for line in result.stdout.splitlines() if line.strip()}
            logger.debug(f"Explicit packages snapshot: {len(pkgs)} packages")
            return pkgs
        else:
            logger.warning("Failed to take explicit package snapshot, using empty baseline")
            return set()
    
    def begin_session(self, pkg_name: str):
        """
        Start a new dependency session for a specific package.
        Captures baseline snapshot for later cleanup.
        """
        if self.session_active:
            logger.warning(f"DEP_SESSION_ALREADY_ACTIVE pkg={self.session_pkg_name} new={pkg_name}")
            self.end_session()  # clean up previous just in case
        
        self.session_pkg_name = pkg_name
        self.session_baseline = self._snapshot_explicit()
        self.session_active = True
        
        logger.info(f"DEP_SESSION_START=1 pkg={pkg_name}")
        logger.info(f"DEP_SESSION_BASELINE_COUNT={len(self.session_baseline)}")
    
    def end_session(self):
        """
        End current dependency session and remove all explicitly installed
        packages that were added during this session (difference from baseline).
        Never removes packages that were present in baseline.
        """
        if not self.session_active:
            logger.debug("DEP_SESSION_END: no active session, skipping")
            return
        
        pkg_name = self.session_pkg_name or "unknown"
        current_explicit = self._snapshot_explicit()
        added_pkgs = current_explicit - self.session_baseline
        
        logger.info(f"DEP_SESSION_END pkg={pkg_name}")
        logger.info(f"DEP_SESSION_ADDED_COUNT={len(added_pkgs)}")
        
        if added_pkgs:
            pkgs_list = list(added_pkgs)
            logger.info(f"DEP_SESSION_REMOVE_START=1 count={len(pkgs_list)}")
            
            # Remove in batches to avoid command line length limits
            batch_size = 50
            success = True
            for i in range(0, len(pkgs_list), batch_size):
                batch = pkgs_list[i:i+batch_size]
                cmd = f"sudo LC_ALL=C pacman -R --noconfirm " + " ".join(batch)
                result = self.shell_executor.run_command(
                    cmd, log_cmd=True, check=False, timeout=300
                )
                if result.returncode != 0:
                    logger.error(f"DEP_SESSION_REMOVE_FAIL=1 pkg={pkg_name} batch={len(batch)}")
                    success = False
                else:
                    logger.info(f"DEP_SESSION_REMOVE_OK=1 pkg={pkg_name} batch={len(batch)}")
            
            if success:
                logger.info(f"DEP_SESSION_REMOVE_OK=1 pkg={pkg_name} total={len(pkgs_list)}")
            else:
                logger.error(f"DEP_SESSION_REMOVE_FAIL=1 pkg={pkg_name} total={len(pkgs_list)}")
        else:
            logger.info("DEP_SESSION_NO_ADDED_PACKAGES")
        
        # Clear session state
        self.session_active = False
        self.session_baseline = None
        self.session_pkg_name = None
    
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
    
    def _handle_conflicts(self, packages: List[str]) -> bool:
        """
        Check for known conflicts and resolve them automatically.
        Uses CONFLICT_REMOVE_ALLOWLIST from config.
        Returns True if installation should continue, False if fatal.
        Logs CONFLICT_BASELINE_BLOCK=1 when removal is blocked.
        """
        if not packages or not self.session_active:
            return True
        
        conflict_map = getattr(config, 'CONFLICT_REMOVE_ALLOWLIST', {})
        if not conflict_map:
            return True
        
        # Check if any of the packages to install are keys in the conflict map
        for pkg in packages:
            if pkg in conflict_map:
                for conflict in conflict_map[pkg]:
                    # Check if conflicting package is installed
                    check_cmd = f"pacman -Q {conflict} 2>/dev/null"
                    result = self.shell_executor.run_command(
                        check_cmd, log_cmd=False, check=False, timeout=30
                    )
                    if result.returncode == 0:
                        # Conflict package is installed
                        logger.info(f"CONFLICT_DETECTED pkg={pkg} conflict={conflict}")
                        
                        # Check if conflict is in baseline snapshot
                        if self.session_baseline and conflict in self.session_baseline:
                            logger.error(f"CONFLICT_BASELINE_BLOCK=1 pkg={pkg} conflict={conflict} reason=in_baseline")
                            logger.error(f"Cannot automatically remove {conflict} because it was present before this build session.")
                            logger.error(f"To resolve, manually remove {conflict} or adjust the conflict allowlist.")
                            return False
                        
                        # Safe to remove
                        logger.info(f"CONFLICT_REMOVE=1 pkg={pkg} conflict={conflict}")
                        remove_cmd = f"sudo LC_ALL=C pacman -R --noconfirm {conflict}"
                        remove_result = self.shell_executor.run_command(
                            remove_cmd, log_cmd=True, check=False, timeout=120
                        )
                        if remove_result.returncode == 0:
                            logger.info(f"CONFLICT_REMOVE_OK=1 pkg={pkg} conflict={conflict}")
                        else:
                            logger.error(f"CONFLICT_REMOVE_FAIL=1 pkg={pkg} conflict={conflict}")
                            return False
        
        return True
    
    def install_packages(self, packages: List[str], allow_aur: bool = True, mode: str = "build") -> bool:
        """
        Install packages with pacman -> yay fallback.
        Handles conflict resolution automatically.
        
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
        
        # --- Deterministic provider resolution ---
        # Replace any exact match from PROVIDER_MAP
        resolved_packages = []
        for pkg in clean_packages:
            if pkg in self.PROVIDER_MAP:
                replacement = self.PROVIDER_MAP[pkg]
                logger.info(f"PROVIDER_RESOLVE: replacing {pkg} with {replacement}")
                resolved_packages.append(replacement)
            else:
                resolved_packages.append(pkg)
        clean_packages = resolved_packages
        # -----------------------------------------
        
        # --- Conflict resolution ---
        if not self._handle_conflicts(clean_packages):
            logger.error("Conflict resolution failed, aborting installation")
            return False
        
        logger.info(f"DEP_INSTALL_START=1 count={len(clean_packages)} mode={mode}")
        
        # Convert to string for command
        pkgs_str = ' '.join(clean_packages)
        
        # --- FIRST ATTEMPT: Try pacman ---
        logger.info(f"DEP_INSTALL_ATTEMPT=1 manager=pacman")
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm --ask=4 {pkgs_str}"
        
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