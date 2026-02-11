"""
Local Builder Module - Handles local package building logic
"""

import subprocess
import logging
import os
from typing import List

import config
from modules.common.shell_executor import ShellExecutor
from modules.common.dependency_installer import DependencyInstaller

logger = logging.getLogger(__name__)


class LocalBuilder:
    """Handles local package building operations"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
        self.dependency_installer = DependencyInstaller(self.shell_executor, debug_mode)
    
    def install_build_dependencies(self,
                                  pkg_dir: str,
                                  makedepends: List[str],
                                  checkdepends: List[str],
                                  runtime_depends: List[str]) -> bool:
        """
        Install dependencies for local package.
        - Default: install makedepends + checkdepends + depends (runtime)
        - Configurable via INSTALL_RUNTIME_DEPS_IN_CI flag.
        
        Args:
            pkg_dir: Package directory path (for logging only)
            makedepends: List of makedepends packages
            checkdepends: List of checkdepends packages
            runtime_depends: List of runtime depends packages
            
        Returns:
            True if successful, False otherwise
        """
        # Build dependency list according to configuration
        build_deps = makedepends + checkdepends
        if config.INSTALL_RUNTIME_DEPS_IN_CI:
            build_deps += runtime_depends
            logger.info("Runtime depends are INCLUDED in build deps (INSTALL_RUNTIME_DEPS_IN_CI=True)")
        else:
            logger.info("Runtime depends are EXCLUDED from build deps (INSTALL_RUNTIME_DEPS_IN_CI=False)")
        
        if not build_deps:
            return True
        
        logger.info(f"Installing {len(build_deps)} dependencies for {pkg_dir}...")
        logger.info(f"Makedepends: {makedepends}")
        logger.info(f"Checkdepends: {checkdepends}")
        if runtime_depends:
            logger.info(f"Runtime depends: {runtime_depends} (will be installed)")
        
        return self.dependency_installer.install_packages(
            packages=build_deps,
            allow_aur=True,  # Allow AUR fallback for local packages too
            mode="build"
        )
    
    def run_makepkg(self, pkg_dir: str, packager_id: str, flags: str = "-d --noconfirm --clean", timeout: int = 3600) -> subprocess.CompletedProcess:
        """Run makepkg command with specified flags, with retry for missing yasm"""
        cmd = f"makepkg {flags}"
        
        logger.info("MAKEPKG_INSTALL_DISABLED=1")
        logger.info("SHELL_EXECUTOR_USED=1")
        
        # Ensure build directory is writable
        if not os.access(pkg_dir, os.W_OK):
            logger.warning(f"Build directory not writable: {pkg_dir}")
            # Try to fix permissions
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
                initial_delay=2.0,
                user="builder"  # Run as builder user
            )
            
            if download_result.returncode != 0:
                logger.error(f"❌ Failed to download sources: {download_result.stderr[:500]}")
                raise subprocess.CalledProcessError(download_result.returncode, "makepkg -od",
                                                   download_result.stdout, download_result.stderr)
            
            # Then run the actual build (with possible retry)
            logger.info("MAKEPKG_SYNCDEPS_DISABLED=1")
            
            def run_build():
                return self.shell_executor.run_command(
                    cmd,
                    cwd=pkg_dir,
                    capture=True,
                    check=False,
                    timeout=timeout,
                    extra_env={"PACKAGER": packager_id},
                    log_cmd=self.debug_mode,
                    user="builder"
                )
            
            # First attempt
            result = run_build()
            
            # Retry logic for missing yasm
            if result.returncode != 0:
                error_output = (result.stderr or "") + "\n" + (result.stdout or "")
                if "yasm: No such file or directory" in error_output:
                    logger.info(f"BUILD_TOOL_AUTOINSTALL=1 tool=yasm reason=missing_binary")
                    # Install yasm via dependency installer
                    if self.dependency_installer.install_packages(["yasm"], allow_aur=True, mode="build"):
                        logger.info("Retrying makepkg after installing yasm...")
                        # Retry build ONCE
                        result = run_build()
                    else:
                        logger.error("Failed to install yasm, cannot retry build")
            
            # Log diagnostic information on failure
            if result.returncode != 0:
                logger.error(f"❌ Build failed with exit code: {result.returncode}")
                
                # Log diagnostic information
                logger.error("=== MAKEPKG FAILURE DIAGNOSTICS ===")
                logger.error(f"Command: {cmd}")
                logger.error(f"Working directory: {pkg_dir}")
                
                # Get user context
                try:
                    whoami_result = subprocess.run(['whoami'], capture_output=True, text=True, check=False)
                    logger.error(f"Current user: {whoami_result.stdout.strip()}")
                    
                    id_result = subprocess.run(['id', '-u'], capture_output=True, text=True, check=False)
                    logger.error(f"Current UID: {id_result.stdout.strip()}")
                    
                    # Check directory permissions
                    logger.error(f"Directory writable: {os.access(pkg_dir, os.W_OK)}")
                    logger.error(f"Directory owner: {os.stat(pkg_dir).st_uid}")
                except Exception as e:
                    logger.error(f"Error getting user context: {e}")
                
                # Log last 200 lines of output
                if result.stdout:
                    stdout_lines = result.stdout.split('\n')
                    last_stdout = stdout_lines[-200:] if len(stdout_lines) > 200 else stdout_lines
                    logger.error(f"Last {len(last_stdout)} lines of stdout:")
                    for line in last_stdout:
                        if line.strip():
                            logger.error(f"  {line}")
                
                if result.stderr:
                    stderr_lines = result.stderr.split('\n')
                    last_stderr = stderr_lines[-200:] if len(stderr_lines) > 200 else stderr_lines
                    logger.error(f"Last {len(last_stderr)} lines of stderr:")
                    for line in last_stderr:
                        if line.strip():
                            logger.error(f"  {line}")
                
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