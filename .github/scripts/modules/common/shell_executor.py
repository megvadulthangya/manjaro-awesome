"""
Shell Executor Module - Handles shell command execution with comprehensive logging
"""

import os
import subprocess
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ShellExecutor:
    """Handles shell command execution with comprehensive logging and timeout"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
    
    def run_command_with_retry(self, cmd, max_retries: int = 5, initial_delay: float = 2.0, 
                             cwd=None, capture=True, check=True, shell=True, user=None, 
                             log_cmd=False, timeout=1800, extra_env=None, retry_errors=None):
        """
        Run command with retry logic for transient failures
        
        Args:
            cmd: Command to execute
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay between retries (doubles each retry)
            retry_errors: List of error patterns to retry on (default: internal server errors)
            Other args: Same as run_command
        
        Returns:
            Command result
        """
        if retry_errors is None:
            retry_errors = ["500 Internal Server Error", "remote: Internal Server Error", 
                           "fatal: the remote end hung up unexpectedly", "connection timed out"]
        
        last_exception = None
        delay = initial_delay
        
        for attempt in range(max_retries):
            if attempt > 0:
                logger.info(f"SRC_RETRY attempt={attempt} max={max_retries} delay={delay:.1f}s")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            
            try:
                result = self.run_command(
                    cmd=cmd,
                    cwd=cwd,
                    capture=capture,
                    check=False,  # Don't raise on error for retry logic
                    shell=shell,
                    user=user,
                    log_cmd=log_cmd,
                    timeout=timeout,
                    extra_env=extra_env
                )
                
                # Check if we should retry based on output
                should_retry = False
                retry_reason = ""
                
                if result.returncode != 0:
                    # Check stderr for retryable errors
                    error_output = (result.stderr or "") + (result.stdout or "")
                    for error_pattern in retry_errors:
                        if error_pattern in error_output:
                            should_retry = True
                            retry_reason = error_pattern
                            break
                
                if not should_retry:
                    if check and result.returncode != 0:
                        # Final failure, raise exception
                        raise subprocess.CalledProcessError(
                            result.returncode, cmd, result.stdout, result.stderr
                        )
                    return result
                
                logger.warning(f"SRC_RETRY_REASON attempt={attempt} reason={retry_reason}")
                
            except subprocess.CalledProcessError as e:
                # Check if this is a retryable error
                error_output = (e.stderr or "") + (e.stdout or "")
                should_retry = False
                retry_reason = ""
                
                for error_pattern in retry_errors:
                    if error_pattern in error_output:
                        should_retry = True
                        retry_reason = error_pattern
                        break
                
                if not should_retry or attempt == max_retries - 1:
                    raise  # Re-raise non-retryable or final failure
                
                logger.warning(f"SRC_RETRY_REASON attempt={attempt} reason={retry_reason}")
                last_exception = e
        
        # Should never reach here
        raise last_exception or RuntimeError("Max retries exceeded")
    
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