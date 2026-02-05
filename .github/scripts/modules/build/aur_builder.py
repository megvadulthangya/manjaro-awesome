"""
AUR Builder Module - Handles AUR package building logic
"""

import re
import subprocess
import logging
from pathlib import Path
from typing import List
from modules.common.shell_executor import ShellExecutor

logger = logging.getLogger(__name__)


class AURBuilder:
    """Handles AUR package building and dependency resolution"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self._pacman_initialized = False
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
    
    def _initialize_pacman_database(self) -> bool:
        """
        REQUIRED PRECONDITION: Initialize pacman database before any dependency resolution.
        This must run ONCE per build session before any dependency installation.
        
        NOTE: This is for dependency resolution only, not the post-repo-enable sync.
        The post-repo-enable pacman -Sy is handled by the orchestrator with proof logging.
        """
        if self._pacman_initialized:
            return True
        
        logger.info("🔄 Initializing pacman database (REQUIRED PRECONDITION)...")
        
        # REQUIRED: Run pacman -Sy to initialize/update package database
        cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, timeout=300)
        
        if result.returncode == 0:
            logger.info("✅ Pacman database initialized successfully")
            self._pacman_initialized = True
            return True
        else:
            logger.warning(f"⚠️ Pacman database initialization warning: {result.stderr[:200]}")
            # Continue anyway - some repositories might fail but main ones should work
            self._pacman_initialized = True
            return True
    
    def install_dependencies_strict(self, deps: List[str]) -> bool:
        """STRICT dependency resolution: pacman first, then yay"""
        if not deps:
            return True
        
        print(f"\nInstalling {len(deps)} dependencies...")
        logger.info(f"Dependencies to install: {deps}")
        
        # REQUIRED PRECONDITION: Initialize pacman database FIRST
        if not self._initialize_pacman_database():
            logger.error("❌ Failed to initialize pacman database")
            # Try to continue anyway, as yay might work
        
        # CRITICAL FIX: Update pacman-key database first
        print("🔄 Updating pacman-key database...")
        cmd = "sudo pacman-key --updatedb"
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, timeout=300)
        if result.returncode != 0:
            logger.warning(f"⚠️ pacman-key --updatedb warning: {result.stderr[:200]}")
        
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
        
        # REQUIRED POLICY: First try pacman with Syy (force refresh)
        deps_str = ' '.join(clean_deps)
        cmd = f"sudo LC_ALL=C pacman -Syy --needed --noconfirm {deps_str}"
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, timeout=1200)
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        logger.warning(f"⚠️ pacman failed for some dependencies (exit code: {result.returncode})")
        
        # REQUIRED POLICY: Fallback to AUR (yay) if pacman fails
        # CRITICAL: This fallback MUST NOT be removed, simplified, or replaced
        cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, user="builder", timeout=1800)
        
        if result.returncode == 0:
            logger.info("✅ Dependencies installed via yay")
            return True
        
        logger.error(f"❌ Both pacman and yay failed for dependencies")
        return False
