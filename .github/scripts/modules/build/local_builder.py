"""
Local Builder Module
Handles building packages from the local repository source
"""
import shutil
import glob
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from modules.common.shell_executor import ShellExecutor

class LocalBuilder:
    """Builds local packages using makepkg"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, 
                 version_manager, version_tracker, build_state, logger: Optional[logging.Logger] = None):
        self.config = config
        self.shell_executor = shell_executor
        self.version_manager = version_manager # Not strictly used for build exec but kept for sig match
        self.logger = logger or logging.getLogger(__name__)
        self.output_dir = config.get('output_dir')
        self.packager = config.get('packager_env', 'Unknown Packager')

    def build(self, pkg_name: str, pkg_dir: Optional[Path] = None) -> bool:
        """
        Execute build for a local package
        
        Args:
            pkg_name: Name of the package
            pkg_dir: Path to the package directory (PKGBUILD location)
        """
        if not pkg_dir or not pkg_dir.exists():
            self.logger.error(f"❌ Package directory not found for {pkg_name}")
            return False

        self.logger.info(f"🏗️ Building Local Package: {pkg_name}")
        self.logger.info(f"   Directory: {pkg_dir}")

        # Clean previous artifacts in build dir
        for f in pkg_dir.glob("*.pkg.tar.zst"):
            try:
                f.unlink()
            except Exception:
                pass

        # 1. Build Command
        # -s: sync deps, -i: install deps, --noconfirm: no prompts, --clean: cleanup
        cmd = ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"]
        
        env = os.environ.copy()
        env['PACKAGER'] = self.packager
        
        try:
            # We must run inside the package directory
            result = self.shell_executor.run(
                cmd, 
                cwd=pkg_dir, 
                check=False,
                extra_env=env,
                timeout=self.config.get('makepkg_timeout', {}).get('default', 3600),
                log_cmd=True
            )

            if result.returncode != 0:
                self.logger.error(f"❌ makepkg failed for {pkg_name} (Exit: {result.returncode})")
                if result.stderr:
                    self.logger.error(f"Build Error: {result.stderr[:1000]}")
                return False

            # 2. Verify Artifacts
            built_files = list(pkg_dir.glob("*.pkg.tar.zst"))
            if not built_files:
                self.logger.error(f"❌ Build command succeeded but no .pkg.tar.zst found for {pkg_name}")
                return False

            # 3. Move to Output Directory
            self.output_dir.mkdir(parents=True, exist_ok=True)
            moved_count = 0
            
            for pkg_file in built_files:
                dest = self.output_dir / pkg_file.name
                # Remove destination if exists to ensure overwrite
                if dest.exists():
                    dest.unlink()
                
                shutil.move(str(pkg_file), str(dest))
                self.logger.info(f"✅ Generated: {dest.name}")
                moved_count += 1

            return moved_count > 0

        except Exception as e:
            self.logger.error(f"❌ Exception during build of {pkg_name}: {e}")
            return False