"""
AUR package builder module
"""

import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class AurBuilder:
    """Builds AUR packages"""
    
    def __init__(self, config, shell_executor, artifact_manager):
        self.config = config
        self.shell = shell_executor
        self.artifacts = artifact_manager
        self.debug_mode = config.get('debug_mode', False)
    
    def build(self, pkg_name):
        """Build an AUR package"""
        aur_dir = Path(self.config['aur_build_dir'])
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] Cloning {pkg_name} from AUR...", flush=True)
        else:
            logger.info(f"Cloning {pkg_name} from AUR...")
        
        # Try different AUR URLs
        clone_success = False
        for aur_url_template in self.config['aur_urls']:
            aur_url = aur_url_template.format(pkg_name=pkg_name)
            
            if self.debug_mode:
                print(f"🔧 [DEBUG] Trying AUR URL: {aur_url}", flush=True)
            else:
                logger.info(f"Trying AUR URL: {aur_url}")
            
            result = self.shell.run(
                f"git clone --depth 1 {aur_url} {pkg_dir}",
                check=False,
                log_cmd=self.debug_mode
            )
            
            if result and result.returncode == 0:
                clone_success = True
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Successfully cloned {pkg_name}", flush=True)
                else:
                    logger.info(f"Successfully cloned {pkg_name}")
                break
        
        if not clone_success:
            if self.debug_mode:
                print(f"❌ [DEBUG] Failed to clone {pkg_name} from any AUR URL", flush=True)
            else:
                logger.error(f"Failed to clone {pkg_name}")
            return False
        
        # Set correct permissions
        self.shell.run(f"chown -R builder:builder {pkg_dir}", check=False)
        
        # Check for PKGBUILD
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            if self.debug_mode:
                print(f"❌ [DEBUG] No PKGBUILD found for {pkg_name}", flush=True)
            else:
                logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
        
        # Build the package
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
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            # Build package
            build_result = self.shell.run(
                f"makepkg -si --noconfirm --clean --nocheck",
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
                    
                    # Clean up
                    self.artifacts.cleanup_directory(pkg_dir)
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
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
                
        except Exception as e:
            if self.debug_mode:
                print(f"❌ [DEBUG] Error building {pkg_name}: {e}", flush=True)
            else:
                logger.error(f"Error building {pkg_name}: {e}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False