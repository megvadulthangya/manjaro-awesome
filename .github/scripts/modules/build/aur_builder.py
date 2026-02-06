"""
AUR Builder Module - Handles AUR package building logic
"""

import re
import logging
from pathlib import Path
from typing import List, Optional
from modules.common.shell_executor import ShellExecutor

logger = logging.getLogger(__name__)


class AURBuilder:
    """Handles AUR package building and dependency resolution"""
    
    def __init__(self, debug_mode: bool = False):
        self.debug_mode = debug_mode
        self._pacman_initialized = False
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
    
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
    
    def _extract_dependencies_from_srcinfo(self, pkg_dir: Path) -> List[str]:
        """
        Extract dependencies from .SRCINFO or PKGBUILD.
        
        Args:
            pkg_dir: Path to package directory
            
        Returns:
            List of dependency strings
        """
        deps = []
        
        # First try to read existing .SRCINFO
        srcinfo_path = pkg_dir / ".SRCINFO"
        srcinfo_content = None
        
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    srcinfo_content = f.read()
            except Exception as e:
                logger.warning(f"Failed to read existing .SRCINFO: {e}")
        
        # Generate .SRCINFO if not available
        if not srcinfo_content:
            try:
                logger.info("SHELL_EXECUTOR_USED=1")
                result = self.shell_executor.run_command(
                    'makepkg --printsrcinfo',
                    cwd=pkg_dir,
                    capture=True,
                    check=False,
                    timeout=60
                )
                
                if result.returncode == 0 and result.stdout:
                    srcinfo_content = result.stdout
                    # Also write to .SRCINFO for future use
                    with open(srcinfo_path, 'w') as f:
                        f.write(srcinfo_content)
                else:
                    logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
                    return []
            except Exception as e:
                logger.warning(f"Error running makepkg --printsrcinfo: {e}")
                return []
        
        # Parse dependencies from SRCINFO content
        lines = srcinfo_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for dependency fields
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()
                
                # Extract all types of dependencies
                if key in ['depends', 'makedepends', 'checkdepends']:
                    deps.append(value)
        
        return deps
    
    def install_dependencies_strict(self, deps: List[str]) -> bool:
        """STRICT dependency resolution: pacman first, then yay"""
        if not deps:
            return True
        
        print(f"\nInstalling {len(deps)} dependencies...")
        logger.info(f"Dependencies to install: {deps}")
        
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
        
        # Clean dependency names
        clean_deps = []
        phantom_packages = set()
        
        for dep in deps:
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            if dep_clean and dep_clean.strip() and not any(x in dep_clean for x in ['$', '{', '}', '(', ')', '[', ']']):
                if re.search(r'[a-zA-Z0-9]', dep_clean):
                    # FIX: Hard-filter out phantom package 'lgi'
                    if dep_clean == 'lgi':
                        phantom_packages.add('lgi')
                        logger.warning(f"⚠️ Found phantom package 'lgi' - will be replaced with 'lua-lgi'")
                        continue
                    clean_deps.append(dep_clean)
        
        # Remove any duplicate entries
        clean_deps = list(dict.fromkeys(clean_deps))
        
        # FIX: If we removed 'lgi', ensure 'lua-lgi' is present
        if 'lgi' in phantom_packages and 'lua-lgi' not in clean_deps:
            logger.info("Adding 'lua-lgi' to replace phantom package 'lgi'")
            clean_deps.append('lua-lgi')
        
        if not clean_deps:
            logger.info("No valid dependencies to install after cleaning")
            return True
        
        logger.info(f"Valid dependencies to install: {clean_deps}")
        if phantom_packages:
            logger.info(f"Phantom packages removed: {', '.join(phantom_packages)}")
        
        # REQUIRED POLICY: First try pacman with Sy (not Syy to avoid double refresh)
        deps_str = ' '.join(clean_deps)
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {deps_str}"
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, timeout=1200)
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        logger.warning(f"⚠️ pacman failed for some dependencies (exit code: {result.returncode})")
        
        # REQUIRED POLICY: Fallback to AUR (yay) if pacman fails
        # CRITICAL: This fallback MUST NOT be removed, simplified, or replaced
        cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
        logger.info("SHELL_EXECUTOR_USED=1")
        result = self.shell_executor.run_command(cmd, log_cmd=True, check=False, user="builder", timeout=1800)
        
        if result.returncode == 0:
            logger.info("✅ Dependencies installed via yay")
            return True
        
        logger.error(f"❌ Both pacman and yay failed for dependencies")
        return False
    
    def build_aur_package(self, pkg_name: str, target_dir: Path, packager_id: str, 
                          build_flags: str = "-si --noconfirm --clean --nocheck", 
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
        
        # Extract dependencies from PKGBUILD/.SRCINFO
        logger.info(f"📦 Extracting dependencies for {pkg_name}...")
        deps = self._extract_dependencies_from_srcinfo(target_dir)
        
        if deps:
            logger.info(f"📦 Found {len(deps)} dependencies for {pkg_name}")
            # Install dependencies
            if not self.install_dependencies_strict(deps):
                logger.error(f"❌ Failed to install dependencies for {pkg_name}")
                return []
        else:
            logger.info(f"📦 No dependencies found for {pkg_name}")
        
        # Download sources
        logger.info("   Downloading sources...")
        logger.info("SHELL_EXECUTOR_USED=1")
        download_result = self.shell_executor.run_command(
            "makepkg -od --noconfirm",
            cwd=target_dir,
            capture=True,
            check=False,
            timeout=600,
            extra_env={"PACKAGER": packager_id}
        )
        
        if download_result.returncode != 0:
            logger.error(f"❌ Failed to download sources: {download_result.stderr[:500]}")
            return []
        
        # Build package
        logger.info(f"   Building with flags: {build_flags}")
        logger.info("SHELL_EXECUTOR_USED=1")
        cmd = f"makepkg {build_flags}"
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] Running makepkg in {target_dir}: {cmd}", flush=True)
        
        try:
            build_result = self.shell_executor.run_command(
                cmd,
                cwd=target_dir,
                capture=True,
                check=False,
                timeout=timeout,
                extra_env={"PACKAGER": packager_id},
                log_cmd=self.debug_mode
            )
            
            if self.debug_mode:
                if build_result.stdout:
                    print(f"🔧 [DEBUG] MAKEPKG STDOUT:\n{build_result.stdout}", flush=True)
                if build_result.stderr:
                    print(f"🔧 [DEBUG] MAKEPKG STDERR:\n{build_result.stderr}", flush=True)
                print(f"🔧 [DEBUG] MAKEPKG EXIT CODE: {build_result.returncode}", flush=True)
            
            if build_result.returncode != 0:
                logger.error(f"❌ Build failed: {build_result.stderr[:500]}")
                return []
            
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