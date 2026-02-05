"""
Local Builder Module - Handles local package building logic
"""

import subprocess
import logging
from modules.common.shell_executor import ShellExecutor

logger = logging.getLogger(__name__)


class LocalBuilder:
    """Handles local package building operations"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
    
    def run_makepkg(self, pkg_dir: str, packager_id: str, flags: str = "-si --noconfirm --clean", timeout: int = 3600) -> subprocess.CompletedProcess:
        """Run makepkg command with specified flags"""
        cmd = f"makepkg {flags}"
        
        logger.info("SHELL_EXECUTOR_USED=1")
        if self.debug_mode:
            print(f"🔧 [DEBUG] Running makepkg in {pkg_dir}: {cmd}", flush=True)
        
        try:
            result = self.shell_executor.run_command(
                cmd,
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=timeout,
                extra_env={"PACKAGER": packager_id},
                log_cmd=self.debug_mode
            )
            
            if self.debug_mode:
                if result.stdout:
                    print(f"🔧 [DEBUG] MAKEPKG STDOUT:\n{result.stdout}", flush=True)
                if result.stderr:
                    print(f"🔧 [DEBUG] MAKEPKG STDERR:\n{result.stderr}", flush=True)
                print(f"🔧 [DEBUG] MAKEPKG EXIT CODE: {result.returncode}", flush=True)
            
            return result
        except Exception as e:
            logger.error(f"Error running makepkg: {e}")
            raise
