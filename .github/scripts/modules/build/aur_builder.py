"""
AUR Builder Module
Handles cloning and building packages from AUR.
Implements 'Secret Sauce' legacy logic: Strict dependency resolution, Yay fallback, and robust environment setup.
"""
import shutil
import logging
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from modules.common.shell_executor import ShellExecutor

class AURBuilder:
    """Builds AUR packages using makepkg with robust dependency handling"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, 
                 version_manager, version_tracker, build_state, logger: Optional[logging.Logger] = None):
        self.config = config
        self.shell_executor = shell_executor
        self.version_manager = version_manager
        self.logger = logger or logging.getLogger(__name__)
        self.build_root = config.get('aur_build_dir')
        self.output_dir = config.get('output_dir')
        self.packager = config.get('packager_env', 'Unknown Packager')

    def _get_build_env(self) -> Dict[str, str]:
        """Prepare environment with strict locale and packager settings"""
        env = os.environ.copy()
        env['LC_ALL'] = 'C'
        env['PACKAGER'] = self.packager
        env['PACMAN_OPTS'] = "--siglevel Never"  # Bypass signature checks
        return env

    def _purge_old_artifacts(self, pkg_dir: Path):
        """Clean up old build artifacts before starting"""
        for f in pkg_dir.glob("*.pkg.tar.zst"):
            try:
                f.unlink()
            except Exception:
                pass
        for f in pkg_dir.glob("*.sig"):
            try:
                f.unlink()
            except Exception:
                pass

    def _install_dependencies_strict(self, pkg_dir: Path) -> bool:
        """
        Pre-install dependencies using pacman to ensure DB is fresh.
        """
        deps = self.version_manager.extract_dependencies(pkg_dir)
        if not deps:
            return True

        self.logger.info(f"📦 Pre-installing {len(deps)} dependencies via Pacman...")
        deps_str = ' '.join(deps)
        
        # Sync DB and install available native deps
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm {deps_str}"
        self.shell_executor.run(cmd, check=False, shell=True)
        return True

    def _parse_missing_deps(self, output: str) -> List[str]:
        """Extract missing package names from makepkg stderr"""
        missing = []
        patterns = [
            r"error: target not found: (\S+)",
            r"Could not find all required packages:",
            r":: Unable to find (\S+)"
        ]
        
        for line in output.splitlines():
            for pattern in patterns:
                matches = re.findall(pattern, line)
                for m in matches:
                    if m and m.strip():
                        clean_pkg = m.strip().strip("'").strip('"')
                        missing.append(clean_pkg)
        
        return list(set(missing))

    def _install_missing_via_yay(self, deps: List[str]) -> bool:
        """Install missing dependencies using yay"""
        if not deps:
            return False
            
        self.logger.info(f"🚑 Fallback: Installing {len(deps)} missing dependencies via Yay...")
        deps_str = ' '.join(deps)
        
        cmd = f"LC_ALL=C yay -S --needed --noconfirm --siglevel Never {deps_str}"
        res = self.shell_executor.run(cmd, check=False, shell=True)
        return res.returncode == 0

    def build(self, pkg_name: str, remote_version: Optional[str] = None) -> bool:
        """
        Clone and build an AUR package with retry logic
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

        # 3. Pre-build Setup
        self._purge_old_artifacts(work_dir)
        self._install_dependencies_strict(work_dir)

        # 4. Build Command
        cmd = ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"]
        env = self._get_build_env()
        
        try:
            # First Attempt
            result = self.shell_executor.run(
                cmd,
                cwd=work_dir,
                check=False,
                extra_env=env,
                timeout=self.config.get('makepkg_timeout', {}).get('default', 3600),
                log_cmd=True
            )

            # 5. Fallback Logic
            if result.returncode != 0:
                self.logger.warning(f"⚠️ First build attempt failed for AUR/{pkg_name}. Checking dependencies...")
                
                output = (result.stderr or "") + "\n" + (result.stdout or "")
                missing_deps = self._parse_missing_deps(output)
                
                if missing_deps:
                    if self._install_missing_via_yay(missing_deps):
                        self.logger.info("🔄 Retrying build after Yay fallback...")
                        result = self.shell_executor.run(
                            cmd,
                            cwd=work_dir,
                            check=False,
                            extra_env=env,
                            timeout=self.config.get('makepkg_timeout', {}).get('default', 3600),
                            log_cmd=True
                        )
                    else:
                        self.logger.error("❌ Yay fallback failed.")
                else:
                    self.logger.warning("❌ No specific missing dependencies detected.")

            # 6. Final Verification
            if result.returncode != 0:
                self.logger.error(f"❌ makepkg failed for AUR/{pkg_name} (Exit: {result.returncode})")
                if result.stderr:
                    self.logger.error(f"Last Error: {result.stderr[:1000]}")
                return False

            built_files = list(work_dir.glob("*.pkg.tar.zst"))
            if not built_files:
                self.logger.error(f"❌ No artifacts produced for AUR/{pkg_name}")
                return False

            # 7. Move Artifacts
            self.output_dir.mkdir(parents=True, exist_ok=True)
            for pkg_file in built_files:
                dest = self.output_dir / pkg_file.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(pkg_file), str(dest))
                self.logger.info(f"✅ Generated: {dest.name}")

            shutil.rmtree(work_dir, ignore_errors=True)
            return True

        except Exception as e:
            self.logger.error(f"❌ Exception building AUR/{pkg_name}: {e}")
            return False