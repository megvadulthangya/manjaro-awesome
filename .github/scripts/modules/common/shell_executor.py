"""
Shell command execution with comprehensive logging, timeout, and debug mode support
Extracted from PackageBuilder._run_cmd with enhanced features
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Dict, List, Optional, Union, Any


class ShellExecutor:
    """
    Executes shell commands with comprehensive logging, timeout handling,
    and optional debug mode for CI/CD output
    """
    
    def __init__(self, debug_mode: bool = False, default_timeout: int = 1800):
        """
        Initialize ShellExecutor
        
        Args:
            debug_mode: If True, bypass logger and print directly to stdout for CI/CD visibility
            default_timeout: Default command timeout in seconds
        """
        self.debug_mode = debug_mode
        self.default_timeout = default_timeout
        self.logger = logging.getLogger(__name__)
    
    def run(
        self,
        cmd: Union[str, List[str]],
        cwd: Optional[Union[str, Path]] = None,
        capture: bool = True,
        check: bool = True,
        shell: bool = True,
        user: Optional[str] = None,
        log_cmd: bool = False,
        timeout: Optional[int] = None,
        extra_env: Optional[Dict[str, str]] = None,
        **kwargs  # Accept any additional kwargs like 'text', 'capture_output', etc.
    ) -> subprocess.CompletedProcess:
        """
        Run command with comprehensive logging and timeout
        
        Args:
            cmd: Command to execute (string or list)
            cwd: Working directory
            capture: Capture stdout/stderr (alias for capture_output)
            check: Raise CalledProcessError on non-zero exit code
            shell: Use shell execution
            user: Run as specified user (requires sudo)
            log_cmd: Log command details
            timeout: Command timeout in seconds (defaults to self.default_timeout)
            extra_env: Additional environment variables
            **kwargs: Additional arguments passed to subprocess.run (text, capture_output, etc.)
        
        Returns:
            subprocess.CompletedProcess
        
        Raises:
            subprocess.TimeoutExpired: Command timed out
            subprocess.CalledProcessError: Command failed and check=True
        """
        if timeout is None:
            timeout = self.default_timeout
        
        # Convert cmd to string if it's a list (for logging)
        cmd_str = cmd if isinstance(cmd, str) else ' '.join(cmd)
        
        # Log command if requested
        if log_cmd or self.debug_mode:
            self._log_command(cmd_str, log_cmd)
        
        # Prepare working directory
        cwd_path = Path(cwd) if cwd else Path.cwd()
        
        # Prepare environment
        env = os.environ.copy()
        env['LC_ALL'] = 'C'  # Ensure consistent locale for command output
        
        if extra_env:
            env.update(extra_env)
        
        # Handle subprocess arguments with proper defaults
        subprocess_kwargs = {
            'cwd': cwd_path,
            'shell': shell,
            'env': env,
            'timeout': timeout,
            'check': check,
            'capture_output': capture,
            'text': True,  # Always return strings by default
        }
        
        # Override defaults with any kwargs provided by caller
        subprocess_kwargs.update(kwargs)
        
        # Prepare command based on user
        if user:
            return self._run_as_user(cmd_str, user, subprocess_kwargs, log_cmd)
        else:
            return self._run_direct(cmd_str, subprocess_kwargs, log_cmd)
    
    def _log_command(self, cmd: str, log_cmd: bool) -> None:
        """Log command execution details"""
        if self.debug_mode:
            print(f"🔧 [DEBUG] RUNNING COMMAND: {cmd}", flush=True)
        elif log_cmd:
            self.logger.info(f"RUNNING COMMAND: {cmd}")
    
    def _log_output(self, result: subprocess.CompletedProcess, log_cmd: bool) -> None:
        """Log command output based on debug mode"""
        # Ensure output is string for logging
        stdout = self._ensure_string(result.stdout)
        stderr = self._ensure_string(result.stderr)
        
        if self.debug_mode:
            if stdout:
                print(f"🔧 [DEBUG] STDOUT:\n{stdout}", flush=True)
            if stderr:
                print(f"🔧 [DEBUG] STDERR:\n{stderr}", flush=True)
            print(f"🔧 [DEBUG] EXIT CODE: {result.returncode}", flush=True)
        elif log_cmd:
            if stdout:
                self.logger.info(f"STDOUT: {stdout[:500]}")
            if stderr:
                self.logger.info(f"STDERR: {stderr[:500]}")
            self.logger.info(f"EXIT CODE: {result.returncode}")
        
        # Critical: If command failed and we're in debug mode, print full output
        if result.returncode != 0 and self.debug_mode:
            print(f"❌ [DEBUG] COMMAND FAILED: {result.cmd if hasattr(result, 'cmd') else 'unknown'}", flush=True)
            if stdout and len(stdout) > 500:
                print(f"❌ [DEBUG] FULL STDOUT (truncated):\n{stdout[:2000]}", flush=True)
            if stderr and len(stderr) > 500:
                print(f"❌ [DEBUG] FULL STDERR (truncated):\n{stderr[:2000]}", flush=True)
    
    def _ensure_string(self, value: Any) -> str:
        """Ensure value is string, decoding bytes if necessary"""
        if value is None:
            return ""
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8', errors='ignore')
            except UnicodeDecodeError:
                return str(value)
        return str(value)
    
    def _run_as_user(
        self,
        cmd: str,
        user: str,
        subprocess_kwargs: Dict[str, Any],
        log_cmd: bool
    ) -> subprocess.CompletedProcess:
        """Run command as specified user"""
        # Set up environment for the user
        env = subprocess_kwargs.get('env', os.environ.copy())
        env['HOME'] = f'/home/{user}'
        env['USER'] = user
        subprocess_kwargs['env'] = env
        
        try:
            # Build sudo command
            shell = subprocess_kwargs.get('shell', True)
            cwd = subprocess_kwargs.get('cwd', Path.cwd())
            
            if shell:
                sudo_cmd = ['sudo', '-u', user, 'bash', '-c', f'cd "{cwd}" && {cmd}']
            else:
                sudo_cmd = ['sudo', '-u', user] + cmd.split() if isinstance(cmd, str) else ['sudo', '-u', user] + cmd
            
            # Remove shell and cwd from kwargs since we're handling them in sudo command
            subprocess_kwargs_copy = subprocess_kwargs.copy()
            subprocess_kwargs_copy.pop('shell', None)
            subprocess_kwargs_copy.pop('cwd', None)
            
            result = subprocess.run(sudo_cmd, **subprocess_kwargs_copy)
            
            # Ensure stdout/stderr are strings
            if isinstance(result.stdout, bytes):
                result.stdout = self._ensure_string(result.stdout)
            if isinstance(result.stderr, bytes):
                result.stderr = self._ensure_string(result.stderr)
            
            if log_cmd or self.debug_mode:
                self._log_output(result, log_cmd)
            
            return result
            
        except subprocess.TimeoutExpired as e:
            error_msg = f"⚠️ Command timed out after {subprocess_kwargs.get('timeout', 1800)} seconds: {cmd}"
            if self.debug_mode:
                print(f"❌ [DEBUG] {error_msg}", flush=True)
            self.logger.error(error_msg)
            raise
        except subprocess.CalledProcessError as e:
            # Ensure exception stdout/stderr are strings
            if hasattr(e, 'stdout') and isinstance(e.stdout, bytes):
                e.stdout = self._ensure_string(e.stdout)
            if hasattr(e, 'stderr') and isinstance(e.stderr, bytes):
                e.stderr = self._ensure_string(e.stderr)
            
            if log_cmd or self.debug_mode:
                error_msg = f"Command failed: {cmd}"
                if self.debug_mode:
                    print(f"❌ [DEBUG] {error_msg}", flush=True)
                    if hasattr(e, 'stdout') and e.stdout:
                        print(f"❌ [DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                    if hasattr(e, 'stderr') and e.stderr:
                        print(f"❌ [DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                else:
                    self.logger.error(error_msg)
            if subprocess_kwargs.get('check', True):
                raise
            return e
    
    def _run_direct(
        self,
        cmd: Union[str, List[str]],
        subprocess_kwargs: Dict[str, Any],
        log_cmd: bool
    ) -> subprocess.CompletedProcess:
        """Run command directly (no user switch)"""
        try:
            result = subprocess.run(cmd, **subprocess_kwargs)
            
            # Ensure stdout/stderr are strings
            if isinstance(result.stdout, bytes):
                result.stdout = self._ensure_string(result.stdout)
            if isinstance(result.stderr, bytes):
                result.stderr = self._ensure_string(result.stderr)
            
            if log_cmd or self.debug_mode:
                self._log_output(result, log_cmd)
            
            return result
            
        except subprocess.TimeoutExpired as e:
            error_msg = f"⚠️ Command timed out after {subprocess_kwargs.get('timeout', 1800)} seconds: {cmd}"
            if self.debug_mode:
                print(f"❌ [DEBUG] {error_msg}", flush=True)
            self.logger.error(error_msg)
            raise
        except subprocess.CalledProcessError as e:
            # Ensure exception stdout/stderr are strings
            if hasattr(e, 'stdout') and isinstance(e.stdout, bytes):
                e.stdout = self._ensure_string(e.stdout)
            if hasattr(e, 'stderr') and isinstance(e.stderr, bytes):
                e.stderr = self._ensure_string(e.stderr)
            
            if log_cmd or self.debug_mode:
                error_msg = f"Command failed: {cmd}"
                if self.debug_mode:
                    print(f"❌ [DEBUG] {error_msg}", flush=True)
                    if hasattr(e, 'stdout') and e.stdout:
                        print(f"❌ [DEBUG] EXCEPTION STDOUT:\n{e.stdout}", flush=True)
                    if hasattr(e, 'stderr') and e.stderr:
                        print(f"❌ [DEBUG] EXCEPTION STDERR:\n{e.stderr}", flush=True)
                else:
                    self.logger.error(error_msg)
            if subprocess_kwargs.get('check', True):
                raise
            return e
    
    def simple_run(self, cmd: str, check: bool = True, **kwargs) -> subprocess.CompletedProcess:
        """
        Simplified run command for common use cases
        
        Args:
            cmd: Command to execute
            check: Raise on error
            **kwargs: Additional arguments passed to run()
        
        Returns:
            subprocess.CompletedProcess
        """
        return self.run(cmd, check=check, log_cmd=False, **kwargs)