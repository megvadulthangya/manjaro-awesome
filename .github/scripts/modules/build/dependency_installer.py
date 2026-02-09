"""
Dependency Installer Module - Handles dependency installation with conflict resolution
"""

import re
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class DependencyInstaller:
    """Handles dependency installation with conflict detection and resolution"""
    
    def __init__(self, shell_executor, debug_mode: bool = False):
        self.shell_executor = shell_executor
        self.debug_mode = debug_mode
    
    def _detect_conflict(self, output: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Detect package conflict from pacman/yay output.
        
        Args:
            output: Command stdout/stderr output
            
        Returns:
            Tuple of (is_conflict: bool, conflict_line: str, remove_candidate: str)
        """
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Pattern 1: "X and Y are in conflict. Remove Y? [y/N]"
            conflict_match = re.search(r'(.+?) and (.+?) are in conflict\. Remove (\S+)\? \[y/N\]', line)
            if conflict_match:
                pkg1, pkg2, remove_candidate = conflict_match.groups()
                logger.info(f"CONFLICT_DETECTED=1 pkg1={pkg1} pkg2={pkg2} remove_candidate={remove_candidate}")
                return True, line, remove_candidate
            
            # Pattern 2: "unresolvable package conflicts detected" (no specific candidate)
            if "unresolvable package conflicts detected" in line:
                logger.info("CONFLICT_DETECTED=1 type=unresolvable")
                return True, line, None
        
        return False, None, None
    
    def _check_conflict_allowed(self, deps: List[str], remove_candidate: str, allowlist: dict) -> Tuple[bool, Optional[str]]:
        """
        Check if a conflict removal is allowed by the allowlist.
        
        Args:
            deps: List of dependencies being installed
            remove_candidate: Package suggested for removal
            allowlist: Conflict resolution allowlist from config
            
        Returns:
            Tuple of (allowed: bool, trigger_pkg: str)
        """
        if not allowlist:
            return False, None
        
        # Check if any dependency being installed is a trigger in the allowlist
        for dep in deps:
            # Clean dependency name (remove version constraints)
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            
            if dep_clean in allowlist:
                # Check if the remove candidate is in the allowed list for this trigger
                if remove_candidate in allowlist[dep_clean]:
                    logger.info(f"CONFLICT_ALLOWLIST_MATCH=1 trigger={dep_clean} candidate={remove_candidate}")
                    return True, dep_clean
        
        logger.info(f"CONFLICT_ALLOWLIST_MATCH=0 candidate={remove_candidate} reason=not_allowlisted")
        return False, None
    
    def _remove_conflicting_package(self, pkg_name: str) -> bool:
        """
        Remove a conflicting package using pacman -R --noconfirm.
        
        Args:
            pkg_name: Package to remove
            
        Returns:
            True if removal successful, False otherwise
        """
        logger.info(f"CONFLICT_AUTO_REMOVE_START=1 candidate={pkg_name}")
        
        cmd = f"sudo LC_ALL=C pacman -R --noconfirm {pkg_name}"
        result = self.shell_executor.run_command(
            cmd, 
            log_cmd=True, 
            check=False, 
            timeout=300
        )
        
        if result.returncode == 0:
            logger.info(f"CONFLICT_AUTO_REMOVE_SUCCESS=1 candidate={pkg_name}")
            return True
        else:
            logger.error(f"CONFLICT_AUTO_REMOVE_FAILED=1 candidate={pkg_name} exitcode={result.returncode}")
            return False
    
    def install_with_conflict_resolution(self, deps: List[str], allowlist: dict) -> bool:
        """
        Install dependencies with conflict resolution.
        
        Args:
            deps: List of dependencies to install
            allowlist: Conflict resolution allowlist from config
            
        Returns:
            True if installation successful, False otherwise
        """
        if not deps:
            return True
        
        # Clean dependency names
        clean_deps = []
        for dep in deps:
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            if dep_clean and dep_clean.strip() and not any(x in dep_clean for x in ['$', '{', '}', '(', ')', '[', ']']):
                if re.search(r'[a-zA-Z0-9]', dep_clean):
                    # Filter out phantom package 'lgi'
                    if dep_clean == 'lgi':
                        logger.warning("⚠️ Found phantom package 'lgi' - will be replaced with 'lua-lgi'")
                        continue
                    clean_deps.append(dep_clean)
        
        # Ensure 'lua-lgi' is present if we removed 'lgi'
        if 'lgi' in deps and 'lua-lgi' not in clean_deps:
            clean_deps.append('lua-lgi')
        
        # Remove duplicates
        clean_deps = list(dict.fromkeys(clean_deps))
        
        if not clean_deps:
            logger.info("No valid dependencies to install after cleaning")
            return True
        
        logger.info(f"Installing {len(clean_deps)} dependencies: {clean_deps}")
        
        # Convert to string for command
        deps_str = ' '.join(clean_deps)
        
        # --- FIRST ATTEMPT: Try pacman ---
        logger.info("CONFLICT_RESOLUTION_ATTEMPT=1 manager=pacman")
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {deps_str}"
        result = self.shell_executor.run_command(
            cmd, 
            log_cmd=True, 
            check=False, 
            timeout=1200
        )
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        # Check if this is a conflict failure
        combined_output = result.stdout + "\n" + result.stderr
        is_conflict, conflict_line, remove_candidate = self._detect_conflict(combined_output)
        
        if is_conflict and remove_candidate:
            # Check if this conflict is allowed
            allowed, trigger_pkg = self._check_conflict_allowed(clean_deps, remove_candidate, allowlist)
            
            if allowed:
                # Auto-remove the conflicting package and retry
                if self._remove_conflicting_package(remove_candidate):
                    logger.info("CONFLICT_RETRY_INSTALL=1 manager=pacman")
                    
                    # Retry pacman installation
                    cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {deps_str}"
                    retry_result = self.shell_executor.run_command(
                        cmd,
                        log_cmd=True,
                        check=False,
                        timeout=1200
                    )
                    
                    if retry_result.returncode == 0:
                        logger.info("✅ Dependencies installed via pacman after conflict resolution")
                        return True
                    else:
                        logger.warning(f"⚠️ Pacman still failed after conflict resolution: {retry_result.returncode}")
                        # Fall through to yay
                else:
                    logger.error("❌ Failed to auto-remove conflicting package")
                    # Fall through to yay
            else:
                logger.info(f"CONFLICT_BLOCKED=1 candidate={remove_candidate} reason=not_allowlisted")
                # Don't attempt auto-removal, fall through to yay
        else:
            # Not a conflict or no specific candidate
            logger.warning(f"⚠️ Pacman failed (not a conflict or no candidate): exit code {result.returncode}")
        
        # --- SECOND ATTEMPT: Fallback to yay ---
        logger.info("CONFLICT_RESOLUTION_ATTEMPT=2 manager=yay")
        cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
        result = self.shell_executor.run_command(
            cmd,
            log_cmd=True,
            check=False,
            user="builder",
            timeout=1800
        )
        
        if result.returncode == 0:
            logger.info("✅ Dependencies installed via yay")
            return True
        
        # Check if yay also has a conflict
        combined_output = result.stdout + "\n" + result.stderr
        is_conflict, conflict_line, remove_candidate = self._detect_conflict(combined_output)
        
        if is_conflict and remove_candidate:
            # Check if this conflict is allowed (same allowlist applies)
            allowed, trigger_pkg = self._check_conflict_allowed(clean_deps, remove_candidate, allowlist)
            
            if allowed:
                # Auto-remove the conflicting package and retry yay
                if self._remove_conflicting_package(remove_candidate):
                    logger.info("CONFLICT_RETRY_INSTALL=1 manager=yay")
                    
                    # Retry yay installation
                    cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
                    retry_result = self.shell_executor.run_command(
                        cmd,
                        log_cmd=True,
                        check=False,
                        user="builder",
                        timeout=1800
                    )
                    
                    if retry_result.returncode == 0:
                        logger.info("✅ Dependencies installed via yay after conflict resolution")
                        return True
                    else:
                        logger.error("❌ Yay failed after conflict resolution")
                        return False
                else:
                    logger.error("❌ Failed to auto-remove conflicting package for yay")
                    return False
            else:
                logger.info(f"CONFLICT_BLOCKED=1 candidate={remove_candidate} reason=not_allowlisted")
                return False
        
        # Final failure
        logger.error("❌ Both pacman and yay failed for dependencies")
        return False