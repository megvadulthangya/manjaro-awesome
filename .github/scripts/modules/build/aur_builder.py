"""
AUR Builder Module - Handles AUR package building logic
"""

import re
import subprocess
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class AURBuilder:
    """Handles AUR package building and dependency resolution"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self._pacman_initialized = False
    
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
        result = self._run_cmd(cmd, log_cmd=True, check=False, timeout=300)
        
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
        result = self._run_cmd(cmd, log_cmd=True, check=False, timeout=300)
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
        result = self._run_cmd(cmd, log_cmd=True, check=False, timeout=1200)
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        logger.warning(f"⚠️ pacman failed for some dependencies (exit code: {result.returncode})")
        
        # REQUIRED POLICY: Fallback to AUR (yay) if pacman fails
        # CRITICAL: This fallback MUST NOT be removed, simplified, or replaced
        cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
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
            cwd = Path.cwd()
        
        if user:
            import os
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
                import os
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