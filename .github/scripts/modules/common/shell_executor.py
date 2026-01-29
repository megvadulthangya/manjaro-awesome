"""
Shell executor module
"""
import os
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Union, Dict, Any

class ShellExecutor:
    """Executes shell commands with logging"""
    
    def __init__(self, debug_mode: bool = False, default_timeout: int = 1800):
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
        **kwargs
    ) -> subprocess.CompletedProcess:
        
        if timeout is None:
            timeout = self.default_timeout
            
        if isinstance(cmd, list):
            cmd_str = ' '.join(cmd)
            if 'shell' not in kwargs:
                shell = False
        else:
            cmd_str = cmd
            if 'shell' not in kwargs:
                shell = True
                
        if log_cmd or self.debug_mode:
            self._log_command(cmd_str)

        cwd_path = Path(cwd) if cwd else Path.cwd()
        env = os.environ.copy()
        env['LC_ALL'] = 'C'
        if extra_env:
            env.update(extra_env)
            
        subprocess_kwargs = {
            'cwd': cwd_path,
            'shell': shell,
            'check': check,
            'env': env,
            'timeout': timeout,
            'text': True,
            'encoding': 'utf-8',
            'errors': 'ignore',
            'capture_output': capture
        }
        subprocess_kwargs.update(kwargs)
        
        # User switching logic would go here if needed (e.g. sudo)
        # For this refactor, we assume running as builder/root or handled via sudo in cmd string
        
        try:
            result = subprocess.run(cmd, **subprocess_kwargs)
            if log_cmd or self.debug_mode:
                self._log_output(result)
            return result
        except subprocess.TimeoutExpired as e:
            self.logger.error(f"Command timed out: {cmd_str}")
            raise
        except subprocess.CalledProcessError as e:
            if log_cmd or self.debug_mode:
                self.logger.error(f"Command failed: {cmd_str}")
                if e.stdout: self.logger.error(f"STDOUT: {e.stdout}")
                if e.stderr: self.logger.error(f"STDERR: {e.stderr}")
            if check:
                raise
            return subprocess.CompletedProcess(e.cmd, e.returncode, e.stdout, e.stderr)

    def _log_command(self, cmd: str):
        if self.debug_mode:
            print(f"🔧 [DEBUG] RUNNING: {cmd}")
        else:
            self.logger.info(f"RUNNING: {cmd}")

    def _log_output(self, result: subprocess.CompletedProcess):
        if self.debug_mode:
            print(f"🔧 [DEBUG] EXIT: {result.returncode}")