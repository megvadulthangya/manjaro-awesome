"""
AUR Builder Module - Handles AUR package building logic
"""

import logging
from pathlib import Path
from typing import List, Optional
from modules.common.shell_executor import ShellExecutor
from modules.common.dependency_installer import DependencyInstaller

logger = logging.getLogger(__name__)


class AURBuilder:
    """Handles AUR package building and dependency resolution"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self._pacman_initialized = False
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
        self.dependency_installer = DependencyInstaller(self.shell_executor, debug_mode)
    
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
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, timeout=300)
        
        if result.returncode == 0:
            logger.info("✅ Pacman database initialized successfully")
            self._pacman_initialized = True
            return True
        else:
            logger.warning(f"⚠️ Pacman database initialization warning: {result.stderr[:200]}")
            # Continue anyway - some repositories might fail but main ones should work
            self._pacman_initialized = True
            return True
    
    def install_dependencies_strict(self, makedepends: List[str], checkdepends: List[str]) -> bool:
        """
        CI-safe dependency resolution: Install only makedepends and checkdepends
        
        Args:
            makedepends: List of makedepends packages
            checkdepends: List of checkdepends packages
            
        Returns:
            True if installation successful, False otherwise
        """
        # Combine makedepends and checkdepends (build-time dependencies only)
        build_deps = makedepends + checkdepends
        
        if not build_deps:
            return True
        
        logger.info(f"Installing {len(build_deps)} build dependencies...")
        logger.info(f"Makedepends: {makedepends}")
        logger.info(f"Checkdepends: {checkdepends}")
        
        # REQUIRED PRECONDITION: Initialize pacman database FIRST
        if not self._initialize_pacman_database():
            logger.error("❌ Failed to initialize pacman database")
            # Try to continue anyway, as yay might work
        
        # CRITICAL FIX: Update pacman-key database first
        print("🔄 Updating pacman-key database...")
        cmd = "sudo pacman-key --updatedb"
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, timeout=300)
        if result.returncode != 0:
            logger.warning(f"⚠️ pacman-key --updatedb warning: {result.stderr[:200]}")
        
        # Install build dependencies with AUR fallback enabled
        return self.dependency_installer.install_packages(
            packages=build_deps,
            allow_aur=True,
            mode="build"
        )
    
    def build_aur_package(self, pkg_name: str, target_dir: Path, packager_id: str, 
                          build_flags: str = "-s --noconfirm --clean --nocheck", 
                          timeout: int = 3600) -> List[str]:
        """
        Build AUR package including dependency installation.
        
        Args:
            pkg_name: AUR package name
            target_dir: Directory containing cloned AUR package
            packager_id: Packager identity string
            build_flags: makepkg flags
            timeout: Build timeout in seconds
            
        Returns:
            List of built package filenames
        """
        logger.info(f"🔨 Building AUR package {pkg_name}...")
        
        # Extract build dependencies from PKGBUILD/.SRCINFO (makedepends + checkdepends only)
        logger.info(f"📦 Extracting build dependencies for {pkg_name}...")
        makedepends, checkdepends, runtime_depends = self.dependency_installer.extract_dependencies(target_dir)
        
        # Log runtime depends but don't install them (CI-safe)
        if runtime_depends:
            logger.info(f"📦 Runtime depends (NOT installed in CI): {runtime_depends}")
        
        if makedepends or checkdepends:
            logger.info(f"📦 Found {len(makedepends) + len(checkdepends)} build dependencies for {pkg_name}")
            # Install build dependencies only
            if not self.install_dependencies_strict(makedepends, checkdepends):
                logger.error(f"❌ Failed to install build dependencies for {pkg_name}")
                return []
        else:
            logger.info(f"📦 No build dependencies found for {pkg_name}")
        
        # Download sources with retry for transient errors
        logger.info("   Downloading sources (with retry)...")
        logger.info("SHELL_EXECUTOR_USED=1")
        
        try:
            download_result = self.shell_executor.run_command_with_retry(
                "makepkg -od --noconfirm",
                cwd=target_dir,
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
                return []
        except Exception as e:
            logger.error(f"❌ Error downloading sources: {e}")
            return []
        
        # Build package
        logger.info(f"   Building with flags: {build_flags}")
        logger.info("MAKEPKG_INSTALL_DISABLED=1")
        logger.info("SHELL_EXECUTOR_USED=1")
        cmd = f"makepkg {build_flags}"
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] Running makepkg in {target_dir}: {cmd}", flush=True)
        
        try:
            # Ensure target directory is writable
            import os
            if not os.access(target_dir, os.W_OK):
                logger.warning(f"Target directory not writable: {target_dir}")
                # Try to fix permissions
                import subprocess
                subprocess.run(['chmod', '755', str(target_dir)], check=False)
                subprocess.run(['chown', '-R', 'builder:builder', str(target_dir)], check=False)
            
            build_result = self.shell_executor.run_command(
                cmd,
                cwd=target_dir,
                capture=True,
                check=False,
                timeout=timeout,
                extra_env={"PACKAGER": packager_id},
                log_cmd=self.debug_mode,
                user="builder"  # Run as builder user
            )
            
            # Log diagnostic information on failure
            if build_result.returncode != 0:
                logger.error(f"❌ Build failed with exit code: {build_result.returncode}")
                
                # Log diagnostic information
                logger.error("=== MAKEPKG FAILURE DIAGNOSTICS ===")
                logger.error(f"Command: {cmd}")
                logger.error(f"Working directory: {target_dir}")
                
                # Get user context
                import subprocess
                try:
                    whoami_result = subprocess.run(['whoami'], capture_output=True, text=True, check=False)
                    logger.error(f"Current user: {whoami_result.stdout.strip()}")
                    
                    id_result = subprocess.run(['id', '-u'], capture_output=True, text=True, check=False)
                    logger.error(f"Current UID: {id_result.stdout.strip()}")
                    
                    # Check directory permissions
                    import os
                    logger.error(f"Directory writable: {os.access(target_dir, os.W_OK)}")
                    logger.error(f"Directory owner: {os.stat(target_dir).st_uid}")
                except Exception as e:
                    logger.error(f"Error getting user context: {e}")
                
                # Log last 200 lines of output
                if build_result.stdout:
                    stdout_lines = build_result.stdout.split('\n')
                    last_stdout = stdout_lines[-200:] if len(stdout_lines) > 200 else stdout_lines
                    logger.error(f"Last {len(last_stdout)} lines of stdout:")
                    for line in last_stdout:
                        if line.strip():
                            logger.error(f"  {line}")
                
                if build_result.stderr:
                    stderr_lines = build_result.stderr.split('\n')
                    last_stderr = stderr_lines[-200:] if len(stderr_lines) > 200 else stderr_lines
                    logger.error(f"Last {len(last_stderr)} lines of stderr:")
                    for line in last_stderr:
                        if line.strip():
                            logger.error(f"  {line}")
                
                # Don't fail on CMake deprecation warnings
                if "CMake Deprecation Warning" in build_result.stderr:
                    logger.warning("⚠️ CMake deprecation warnings detected, but continuing...")
                    # If the only error is CMake deprecation, we can continue
                    if build_result.returncode != 0:
                        # Still a real error
                        return []
                else:
                    # Real error
                    return []
            
            if self.debug_mode:
                if build_result.stdout:
                    print(f"🔧 [DEBUG] MAKEPKG STDOUT:\n{build_result.stdout}", flush=True)
                if build_result.stderr:
                    print(f"🔧 [DEBUG] MAKEPKG STDERR:\n{build_result.stderr}", flush=True)
                print(f"🔧 [DEBUG] MAKEPKG EXIT CODE: {build_result.returncode}", flush=True)
            
            # Collect built packages (skip .sig files)
            built_files = []
            for pkg_file in target_dir.glob("*.pkg.tar.*"):
                # Skip signature files
                if pkg_file.name.endswith(".sig"):
                    continue
                built_files.append(pkg_file.name)
            
            if built_files:
                logger.info(f"✅ Successfully built {pkg_name}: {len(built_files)} package(s)")
                return built_files
            else:
                logger.error(f"❌ No package files created for {pkg_name}")
                return []
                
        except Exception as e:
            logger.error(f"❌ Error building {pkg_name}: {e}")
            return []
