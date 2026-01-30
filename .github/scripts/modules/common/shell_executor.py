"""
Shell command executor with comprehensive logging and timeout handling
"""

import os
import subprocess
import logging

logger = logging.getLogger(__name__)

class ShellExecutor:
    """Execute shell commands with comprehensive logging"""
    
    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
    
    def run(self, cmd, cwd=None, capture=True, check=True, shell=True, 
            user=None, log_cmd=False, timeout=1800, extra_env=None):
        """Run command with comprehensive logging, timeout, and optional extra environment variables"""
        if log_cmd or self.debug_mode:
            if self.debug_mode:
                print(f"🔧 [DEBUG] RUNNING COMMAND: {cmd}", flush=True)
            else:
                logger.info(f"RUNNING COMMAND: {cmd}")
        
        if cwd is None:
            cwd = os.getcwd()
        
        # Prepare environment
        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)
        env['LC_ALL'] = 'C'
        
        if user:
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            
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
                
                self._log_result(cmd, result)
                return result
                
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                self._log_error(error_msg, None)
                raise
            except subprocess.CalledProcessError as e:
                self._log_result(cmd, e)
                if check:
                    raise
                return e
        else:
            try:
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
                
                self._log_result(cmd, result)
                return result
                
            except subprocess.TimeoutExpired as e:
                error_msg = f"⚠️ Command timed out after {timeout} seconds: {cmd}"
                self._log_error(error_msg, None)
                raise
            except subprocess.CalledProcessError as e:
                self._log_result(cmd, e)
                if check:
                    raise
                return e
    
    def _log_result(self, cmd, result):
        """Log command result"""
        if self.debug_mode:
            if hasattr(result, 'stdout') and result.stdout:
                print(f"🔧 [DEBUG] STDOUT:\n{result.stdout}", flush=True)
            if hasattr(result, 'stderr') and result.stderr:
                print(f"🔧 [DEBUG] STDERR:\n{result.stderr}", flush=True)
            if hasattr(result, 'returncode'):
                print(f"🔧 [DEBUG] EXIT CODE: {result.returncode}", flush=True)
            
            # If command failed and we're in debug mode, print full output
            if hasattr(result, 'returncode') and result.returncode != 0:
                print(f"❌ [DEBUG] COMMAND FAILED: {cmd}", flush=True)
                if hasattr(result, 'stdout') and result.stdout and len(result.stdout) > 500:
                    print(f"❌ [DEBUG] FULL STDOUT (truncated):\n{result.stdout[:2000]}", flush=True)
                if hasattr(result, 'stderr') and result.stderr and len(result.stderr) > 500:
                    print(f"❌ [DEBUG] FULL STDERR (truncated):\n{result.stderr[:2000]}", flush=True)
        else:
            if hasattr(result, 'stdout') and result.stdout:
                logger.info(f"STDOUT: {result.stdout[:500]}")
            if hasattr(result, 'stderr') and result.stderr:
                logger.info(f"STDERR: {result.stderr[:500]}")
            if hasattr(result, 'returncode'):
                logger.info(f"EXIT CODE: {result.returncode}")
    
    def _log_error(self, error_msg, result):
        """Log error message"""
        if self.debug_mode:
            print(f"❌ [DEBUG] {error_msg}", flush=True)
        else:
            logger.error(error_msg)
        
        if result and hasattr(result, 'stderr') and result.stderr:
            if self.debug_mode:
                print(f"❌ [DEBUG] ERROR DETAILS: {result.stderr[:500]}", flush=True)
            else:
                logger.error(f"Error details: {result.stderr[:500]}")