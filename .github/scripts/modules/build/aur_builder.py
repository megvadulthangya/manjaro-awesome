"""
AUR Builder Module
Handles cloning and building packages from AUR
"""
import shutil
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional
from modules.common.shell_executor import ShellExecutor

class AURBuilder:
    """Builds AUR packages"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, 
                 version_manager, version_tracker, build_state, logger: Optional[logging.Logger] = None):
        self.config = config
        self.shell_executor = shell_executor
        self.logger = logger or logging.getLogger(__name__)
        self.build_root = config.get('aur_build_dir')
        self.output_dir = config.get('output_dir')
        self.packager = config.get('packager_env', 'Unknown Packager')

    def build(self, pkg_name: str, remote_version: Optional[str] = None) -> bool:
        """
        Clone and build an AUR package
        """
        self.logger.info(f"🏗️ Building AUR Package: {pkg_name}")
        
        work_dir = self.build_root / pkg_name
        
        # 1. Clean/Prepare Directory
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
        work_dir.parent.mkdir(parents=True, exist_ok=True)

        # 2. Clone AUR Repository
        aur_url = f"https://aur.archlinux.org/{pkg_name}.git"
        clone_cmd = ["git", "clone", "--depth=1", aur_url, str(work_dir)]
        
        clone_res = self.shell_executor.run(clone_cmd, check=False)
        if clone_res.returncode != 0:
            self.logger.error(f"❌ Failed to clone AUR package {pkg_name}")
            return False

        # 3. Build using makepkg
        # Note: AUR builds often require dependency resolution handled by makepkg -s
        cmd = ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"]
        
        # 4. Environment Setup
        env = os.environ.copy()
        env['PACKAGER'] = self.packager
        env['PACMAN_OPTS'] = "--siglevel Never"  # CRITICAL: Bypass signature checks
        
        try:
            result = self.shell_executor.run(
                cmd,
                cwd=work_dir,
                check=False,
                extra_env=env,
                timeout=self.config.get('makepkg_timeout', {}).get('default', 3600),
                log_cmd=True
            )

            if result.returncode != 0:
                self.logger.error(f"❌ makepkg failed for AUR/{pkg_name} (Exit: {result.returncode})")
                if result.stderr:
                    self.logger.error(f"Build Error: {result.stderr[:1000]}")
                return False

            # 5. Verify and Move Artifacts
            built_files = list(work_dir.glob("*.pkg.tar.zst"))
            if not built_files:
                self.logger.error(f"❌ No artifacts produced for AUR/{pkg_name}")
                return False

            self.output_dir.mkdir(parents=True, exist_ok=True)
            for pkg_file in built_files:
                dest = self.output_dir / pkg_file.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(pkg_file), str(dest))
                self.logger.info(f"✅ Generated: {dest.name}")

            # Cleanup build dir to save space
            shutil.rmtree(work_dir, ignore_errors=True)
            return True

        except Exception as e:
            self.logger.error(f"❌ Exception building AUR/{pkg_name}: {e}")
            return False