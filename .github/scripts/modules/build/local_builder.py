"""
Local Builder Module - Handles local package building logic
"""

import subprocess
import logging

logger = logging.getLogger(__name__)


class LocalBuilder:
    """Handles local package building operations"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
    
    def run_makepkg(self, pkg_dir: str, packager_id: str, flags: str = "-si --noconfirm --clean", timeout: int = 3600) -> subprocess.CompletedProcess:
        """Run makepkg command with specified flags"""
        cmd = f"makepkg {flags}"
        
        import os
        extra_env = {"PACKAGER": packager_id}
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] Running makepkg in {pkg_dir}: {cmd}", flush=True)
        
        try:
            result = subprocess.run(
                cmd,
                cwd=pkg_dir,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
                env={**os.environ, **extra_env}
            )
            
            if self.debug_mode:
                if result.stdout:
                    print(f"🔧 [DEBUG] MAKEPKG STDOUT:\n{result.stdout}", flush=True)
                if result.stderr:
                    print(f"🔧 [DEBUG] MAKEPKG STDERR:\n{result.stderr}", flush=True)
                print(f"🔧 [DEBUG] MAKEPKG EXIT CODE: {result.returncode}", flush=True)
            
            return result
        except subprocess.TimeoutExpired as e:
            logger.error(f"makepkg timed out after {timeout} seconds")
            raise
        except Exception as e:
            logger.error(f"Error running makepkg: {e}")
            raise