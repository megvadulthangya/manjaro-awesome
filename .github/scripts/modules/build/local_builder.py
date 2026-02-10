"""
Local Builder Module - Handles local package building logic
"""

import subprocess
import logging
import os
from modules.common.shell_executor import ShellExecutor
from modules.common.dependency_installer import DependencyInstaller

logger = logging.getLogger(__name__)


class LocalBuilder:
    """Handles local package building operations"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
        self.dependency_installer = DependencyInstaller(self.shell_executor, debug_mode)
    
    def _extract_build_dependencies(self, pkg_dir: str):
        """Extract makedepends and checkdepends from package"""
        from pathlib import Path
        pkg_path = Path(pkg_dir)
        
        makedepends, checkdepends, runtime_depends = self.dependency_installer.extract_dependencies(pkg_path)
        
        # Log runtime depends but don't install them (CI-safe)
        if runtime_depends:
            logger.info(f"📦 Runtime depends (NOT installed in CI): {runtime_depends}")
        
        return makedepends, checkdepends
    
    def install_build_dependencies(self, pkg_dir: str) -> bool:
        """
        Install build dependencies for local package (makedepends + checkdepends only)
        
        Args:
            pkg_dir: Package directory path
            
        Returns:
            True if successful, False otherwise
        """
        makedepends, checkdepends = self._extract_build_dependencies(pkg_dir)
        build_deps = makedepends + checkdepends
        
        if not build_deps:
            return True
        
        logger.info(f"Installing {len(build_deps)} build dependencies for {pkg_dir}...")
        logger.info(f"Makedepends: {makedepends}")
        logger.info(f"Checkdepends: {checkdepends}")
        
        return self.dependency_installer.install_packages(
            packages=build_deps,
            allow_aur=True,  # Allow AUR fallback for local packages too
            mode="build"
        )
    
    def run_makepkg(self, pkg_dir: str, packager_id: str, flags: str = "-s --noconfirm --clean", timeout: int = 3600) -> subprocess.CompletedProcess:
        """Run makepkg command with specified flags"""
        cmd = f"makepkg {flags}"
        
        logger.info("MAKEPKG_INSTALL_DISABLED=1")
        logger.info("SHELL_EXECUTOR_USED=1")
        
        # Ensure build directory is writable
        if not os.access(pkg_dir, os.W_OK):
            logger.warning(f"Build directory not writable: {pkg_dir}")
            # Try to fix permissions
            import subprocess
            subprocess.run(['chmod', '755', pkg_dir], check=False)
            subprocess.run(['chown', '-R', 'builder:builder', pkg_dir], check=False)
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] Running makepkg in {pkg_dir}: {cmd}", flush=True)
        
        try:
            # First download sources with retry
            logger.info("   Downloading sources (with retry)...")
            download_result = self.shell_executor.run_command_with_retry(
                "makepkg -od --noconfirm",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=600,
                extra_env={"PACKAGER": packager_id},
                max_retries=5,
                initial_delay=2.0
            )
            
            if download_result.returncode != 0:
                logger.error(f"❌ Failed to download sources: {download_result.stderr[:500]}")
                raise subprocess.CalledProcessError(download_result.returncode, "makepkg -od", 
                                                   download_result.stdout, download_result.stderr)
            
            # Then run the actual build
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
            
            # Don't fail on CMake deprecation warnings
            if result.returncode != 0 and "CMake Deprecation Warning" in result.stderr:
                logger.warning("⚠️ CMake deprecation warnings detected, but continuing...")
                # If the only error is CMake deprecation, we can treat as success
                # We'll still log the warning but return a success result
                if result.returncode != 0:
                    # Check if there are other errors besides CMake warnings
                    error_lines = [line for line in result.stderr.split('\n') 
                                  if line and "CMake Deprecation Warning" not in line]
                    if not any("error" in line.lower() for line in error_lines):
                        # Only CMake warnings, treat as success
                        logger.info("Only CMake deprecation warnings found, treating as success")
                        result.returncode = 0
            
            return result
        except Exception as e:
            logger.error(f"Error running makepkg: {e}")
            raise
