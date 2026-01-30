"""
Local package builder module
"""

import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class LocalBuilder:
    """Builds local packages"""
    
    def __init__(self, config, shell_executor, artifact_manager):
        self.config = config
        self.shell = shell_executor
        self.artifacts = artifact_manager
        self.debug_mode = config.get('debug_mode', False)
    
    def build(self, pkg_name, repo_root):
        """Build a local package"""
        pkg_dir = Path(repo_root) / pkg_name
        
        if not pkg_dir.exists():
            if self.debug_mode:
                print(f"❌ [DEBUG] Package directory not found: {pkg_name}", flush=True)
            else:
                logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            if self.debug_mode:
                print(f"❌ [DEBUG] No PKGBUILD found for {pkg_name}", flush=True)
            else:
                logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        try:
            if self.debug_mode:
                print(f"🔧 [DEBUG] Building {pkg_name}...", flush=True)
            else:
                logger.info(f"Building {pkg_name}...")
            
            # Download sources
            source_result = self.shell.run(
                f"makepkg -od --noconfirm",
                cwd=pkg_dir,
                check=False,
                timeout=600,
                extra_env={"PACKAGER": self.config['packager_id']},
                log_cmd=self.debug_mode
            )
            
            if source_result.returncode != 0:
                if self.debug_mode:
                    print(f"❌ [DEBUG] Failed to download sources for {pkg_name}", flush=True)
                else:
                    logger.error(f"Failed to download sources for {pkg_name}")
                return False
            
            # Build package with appropriate flags
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                if self.debug_mode:
                    print(f"🔧 [DEBUG] GTK2: Skipping check step", flush=True)
                else:
                    logger.info("GTK2: Skipping check step (long)")
            
            build_result = self.shell.run(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                check=False,
                timeout=3600,
                extra_env={"PACKAGER": self.config['packager_id']},
                log_cmd=self.debug_mode
            )
            
            if build_result.returncode == 0:
                # Move built packages
                moved_files = self.artifacts.move_built_packages(pkg_dir, pkg_name)
                
                if moved_files:
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Successfully built {pkg_name}", flush=True)
                    else:
                        logger.info(f"Successfully built {pkg_name}")
                    return True
                else:
                    if self.debug_mode:
                        print(f"❌ [DEBUG] No package files created for {pkg_name}", flush=True)
                    else:
                        logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                if self.debug_mode:
                    print(f"❌ [DEBUG] Failed to build {pkg_name}", flush=True)
                else:
                    logger.error(f"Failed to build {pkg_name}")
                return False
                
        except Exception as e:
            if self.debug_mode:
                print(f"❌ [DEBUG] Error building {pkg_name}: {e}", flush=True)
            else:
                logger.error(f"Error building {pkg_name}: {e}")
            return False