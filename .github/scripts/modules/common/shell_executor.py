"""
Shell Executor Module - Handles shell command execution with comprehensive logging
"""

import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ShellExecutor:
    """Handles shell command execution with comprehensive logging and timeout"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
    
    def run_command(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, 
                   log_cmd=False, timeout=1800, extra_env=None):
        """Run command with comprehensive logging, timeout, and optional extra environment variables"""
        if log_cmd or self.debug_mode:
            if self.debug_mode:
                print(f"🔧 [SHELL DEBUG] RUNNING COMMAND: {cmd}", flush=True)
            else:
                logger.info(f"RUNNING COMMAND: {cmd}")
        
        if cwd is None:
            cwd = Path.cwd()
        
        # Prepare environment
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        
        if user:
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
                
                # CRITICAL FIX: When in debug mode, bypass logger for critical output
                if log_cmd or self.debug_mode:
                    if self.debug_mode:
                        if result.stdout:
                            print(f"🔧 [SHELL DEBUG] STDOUT:\n{result.stdout}", flush=True)
                        if result.stderr:
                            print(f"🔧 [SHELL DEBUG] STDERR:\n{result.stderr}", flush=True)
                        print(f"🔧 [SHELL DEBUG] EXIT CODE: {result.returncode}", flush=True)
                    else:
                        if result.stdout:
                            logger.info(f"STDOUT: {result.stdout[:500]}")
                        if result.stderr:
                            logger.info(f"STDERR: {result.stderr[:500]}")
                        logger.info(f"EXIT CODE: {result.returncode}")
                
                # CRITICAL: If command failed and we're in debug mode, print full output
                if result.returncode != 0 and self.debug_mode:
                    print(f"❌ [SHELL DEBUG] COMMAND FAILED: {cmd}", flush=True)
                    if result.stdout and len(result.stdout) > 500:
                        print(f"❌ [SHELL DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                    if result.stderr and len(result.stderr) > 500:
                        print(f"❌ [SHELL DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)
                
                return result
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                if self.debug_mode:
                    print(f"❌ [SHELL DEBUG] {error_msg}", flush=True)
                logger.error(error_msg)
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd or self.debug_mode:
                    error_msg = f"Command failed: {cmd}"
                    if self.debug_mode:
                        print(f"❌ [SHELL DEBUG] {error_msg}", flush=True)
                        if hasattr(e, 'stdout') and e.stdout:
                            print(f"❌ [SHELL DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                        if hasattr(e, 'stderr') and e.stderr:
                            print(f"❌ [SHELL DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                    else:
                        logger.error(error_msg)
                if check:
                    raise
                return e
        else:
            try:
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
                
                # CRITICAL FIX: When in debug mode, bypass logger for critical output
                if log_cmd or self.debug_mode:
                    if self.debug_mode:
                        if result.stdout:
                            print(f"🔧 [SHELL DEBUG] STDOUT:\n{result.stdout}", flush=True)
                        if result.stderr:
                            print(f"🔧 [SHELL DEBUG] STDERR:\n{result.stderr}", flush=True)
                        print(f"🔧 [SHELL DEBUG] EXIT CODE: {result.returncode}", flush=True)
                    else:
                        if result.stdout:
                            logger.info(f"STDOUT: {result.stdout[:500]}")
                        if result.stderr:
                            logger.info(f"STDERR: {result.stderr[:500]}")
                        logger.info(f"EXIT CODE: {result.returncode}")
                
                # CRITICAL: If command failed and we're in debug mode, print full output
                if result.returncode != 0 and self.debug_mode:
                    print(f"❌ [SHELL DEBUG] COMMAND FAILED: {cmd}", flush=True)
                    if result.stdout and len(result.stdout) > 500:
                        print(f"❌ [SHELL DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                    if result.stderr and len(result.stderr) > 500:
                        print(f"❌ [SHELL DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)
                
                return result
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                if self.debug_mode:
                    print(f"❌ [SHELL DEBUG] {error_msg}", flush=True)
                logger.error(error_msg)
                raise
            except subprocess.CalledProcessError as e:
                if log_cmd or self.debug_mode:
                    error_msg = f"Command failed: {cmd}"
                    if self.debug_mode:
                        print(f"❌ [SHELL DEBUG] {error_msg}", flush=True)
                        if hasattr(e, 'stdout') and e.stdout:
                            print(f"❌ [SHELL DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                        if hasattr(e, 'stderr') and e.stderr:
                            print(f"❌ [SHELL DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                    else:
                        logger.error(error_msg)
                if check:
                    raise
                return e