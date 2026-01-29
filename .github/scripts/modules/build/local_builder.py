"""
Local Builder Module
Handles building packages from the local repository source.
Implements 'Secret Sauce' legacy logic: Strict dependency resolution, Yay fallback, and robust environment setup.
"""
import shutil
import logging
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from modules.common.shell_executor import ShellExecutor

class LocalBuilder:
    """Builds local packages using makepkg with robust dependency handling"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor, 
                 version_manager, version_tracker, build_state, logger: Optional[logging.Logger] = None):
        self.config = config
        self.shell_executor = shell_executor
        self.version_manager = version_manager
        self.logger = logger or logging.getLogger(__name__)
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
        
        # We ignore return code because some deps might be AUR-only (which pacman fails on)
        # We just want to ensure native deps are handled and DB is synced.
        self.shell_executor.run(cmd, check=False, shell=True)
        return True

    def _parse_missing_deps(self, output: str) -> List[str]:
        """Extract missing package names from makepkg stderr"""
        missing = []
        patterns = [
            r"error: target not found: (\S+)",
            r"Could not find all required packages:",
            r":: Unable to find (\S+)",
            r"Missing dependencies: \n((?:\s+->\s+\S+\n)+)" # Multiline parsing often complex, sticking to simple lines
        ]
        
        for line in output.splitlines():
            for pattern in patterns:
                matches = re.findall(pattern, line)
                for m in matches:
                    if m and m.strip():
                        # Clean up punctuation if necessary
                        clean_pkg = m.strip().strip("'").strip('"')
                        missing.append(clean_pkg)
        
        return list(set(missing))

    def _install_missing_via_yay(self, deps: List[str]) -> bool:
        """Install missing dependencies using yay"""
        if not deps:
            return False
            
        self.logger.info(f"🚑 Fallback: Installing {len(deps)} missing dependencies via Yay...")
        deps_str = ' '.join(deps)
        
        # Run as builder user (assumed context), ensuring env vars
        cmd = f"LC_ALL=C yay -S --needed --noconfirm --siglevel Never {deps_str}"
        
        res = self.shell_executor.run(cmd, check=False, shell=True)
        return res.returncode == 0

    def build(self, pkg_name: str, pkg_dir: Optional[Path] = None) -> bool:
        """
        Execute build for a local package with retry logic
        """
        if not pkg_dir or not pkg_dir.exists():
            self.logger.error(f"❌ Package directory not found for {pkg_name}")
            return False

        self.logger.info(f"🏗️ Building Local Package: {pkg_name}")
        self.logger.info(f"   Directory: {pkg_dir}")

        # 1. Prepare
        self._purge_old_artifacts(pkg_dir)
        
        # 2. Strict Dependency Sync
        self._install_dependencies_strict(pkg_dir)

        # 3. Build Command
        cmd = ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"]
        env = self._get_build_env()
        
        try:
            # First Attempt
            result = self.shell_executor.run(
                cmd, 
                cwd=pkg_dir, 
                check=False,
                extra_env=env,
                timeout=self.config.get('makepkg_timeout', {}).get('default', 3600),
                log_cmd=True
            )

            # 4. Fallback Logic
            if result.returncode != 0:
                self.logger.warning(f"⚠️ First build attempt failed for {pkg_name}. Checking for missing dependencies...")
                
                # Parse stderr (or stdout) for missing deps
                output = (result.stderr or "") + "\n" + (result.stdout or "")
                missing_deps = self._parse_missing_deps(output)
                
                if missing_deps:
                    if self._install_missing_via_yay(missing_deps):
                        self.logger.info("🔄 Retrying build after Yay fallback...")
                        result = self.shell_executor.run(
                            cmd, 
                            cwd=pkg_dir, 
                            check=False,
                            extra_env=env,
                            timeout=self.config.get('makepkg_timeout', {}).get('default', 3600),
                            log_cmd=True
                        )
                    else:
                        self.logger.error("❌ Yay fallback failed to install dependencies.")
                else:
                    self.logger.warning("❌ No specific missing dependencies detected in output.")

            # 5. Final Verification
            if result.returncode != 0:
                self.logger.error(f"❌ Build failed for {pkg_name} (Exit: {result.returncode})")
                if result.stderr:
                    self.logger.error(f"Last Error: {result.stderr[:1000]}")
                return False

            built_files = list(pkg_dir.glob("*.pkg.tar.zst"))
            if not built_files:
                self.logger.error(f"❌ No artifacts found for {pkg_name}")
                return False

            # 6. Move Artifacts
            self.output_dir.mkdir(parents=True, exist_ok=True)
            for pkg_file in built_files:
                dest = self.output_dir / pkg_file.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(pkg_file), str(dest))
                self.logger.info(f"✅ Generated: {dest.name}")

            return True

        except Exception as e:
            self.logger.error(f"❌ Exception during build of {pkg_name}: {e}")
            return False