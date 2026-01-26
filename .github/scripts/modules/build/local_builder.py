"""
Local package builder with SRCINFO-based version comparison and dependency fallback
Extracted from PackageBuilder._build_local_package
"""

import os
import shutil
import re
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

from modules.common.shell_executor import ShellExecutor
from modules.build.version_manager import VersionManager


class LocalBuilder:
    """Handles local package building with version comparison and dependency resolution"""
    
    def __init__(self, config: Dict[str, Any], shell_executor: ShellExecutor,
                 version_manager: VersionManager, version_tracker,
                 build_state, logger: Optional[logging.Logger] = None):
        """
        Initialize LocalBuilder
        
        Args:
            config: Configuration dictionary
            shell_executor: ShellExecutor instance
            version_manager: VersionManager instance
            version_tracker: VersionTracker instance
            build_state: BuildState instance
            logger: Optional logger instance
        """
        self.config = config
        self.shell_executor = shell_executor
        self.version_manager = version_manager
        self.version_tracker = version_tracker
        self.build_state = build_state
        self.logger = logger or logging.getLogger(__name__)
        
        # Extract configuration
        self.repo_root = Path(config.get('repo_root', '.'))
        self.output_dir = Path(config.get('output_dir', 'built_packages'))
        self.packager_id = config.get('packager_id', 'Maintainer <no-reply@gshoots.hu>')
        self.repo_name = config.get('repo_name', '')
        
        # HOKIBOT data collection
        self.hokibot_data = []
    
    def build(self, pkg_name: str, remote_version: Optional[str] = None) -> bool:
        """
        Build local package with SRCINFO-based version comparison and dependency fallback
        
        Args:
            pkg_name: Package name
            remote_version: Optional remote version for comparison
        
        Returns:
            True if build successful or skipped (up-to-date), False on failure
        """
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            self.logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            self.logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        # Extract version info from SRCINFO (not regex)
        try:
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
            version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            # DECISION LOGIC: Only build if AUR_VERSION > REMOTE_VERSION
            if remote_version and not self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch):
                self.logger.info(f"✅ {pkg_name} already up to date on server ({remote_version}) - skipping")
                self.build_state.add_skipped(pkg_name, version, is_aur=False, reason="up-to-date")
                
                # ZERO-RESIDUE FIX: Register the target version for this skipped package
                self.version_tracker.register_skipped_package(pkg_name, remote_version)
                
                return True  # Skipped is considered successful for workflow
            
            if remote_version:
                self.logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
                
                # PRE-BUILD PURGE: Remove old version files BEFORE building new version
                self._pre_build_purge(pkg_name, remote_version)
            else:
                self.logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
                
        except Exception as e:
            self.logger.error(f"Failed to extract version for {pkg_name}: {e}")
            version = "unknown"
        
        # Attempt build
        build_success = self._execute_build(pkg_name, pkg_dir, version, pkgver, pkgrel, epoch)
        
        if build_success:
            # ZERO-RESIDUE FIX: Register the target version for this built package
            self.version_tracker.register_built_package(pkg_name, version)
            self.build_state.add_built(pkg_name, version, is_aur=False)
        
        return build_success
    
    def _pre_build_purge(self, pkg_name: str, old_version: str):
        """Purge old version before building new one"""
        # This is a placeholder - actual cleanup is handled by CleanupManager
        self.logger.debug(f"Would purge old version {old_version} of {pkg_name}")
    
    def _execute_build(self, pkg_name: str, pkg_dir: Path, version: str,
                      pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """Execute the actual build process"""
        try:
            self.logger.info(f"Building {pkg_name} ({version})...")
            
            # Clean workspace before building
            self._clean_workspace(pkg_dir)
            
            self.logger.info("Downloading sources...")
            source_result = self.shell_executor.run(
                f"makepkg -od --noconfirm",
                cwd=pkg_dir,
                check=False,
                capture=True,
                timeout=600,
                extra_env={"PACKAGER": self.packager_id},
                log_cmd=False
            )
            
            if source_result.returncode != 0:
                self.logger.error(f"Failed to download sources for {pkg_name}")
                return False
            
            # CRITICAL FIX: Install dependencies with AUR fallback
            self.logger.info("Installing dependencies with AUR fallback...")
            
            # First attempt: Standard makepkg with appropriate flags
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                self.logger.info("GTK2: Skipping check step (long)")
            
            self.logger.info("Building package (first attempt)...")
            build_result = self.shell_executor.run(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600,
                extra_env={"PACKAGER": self.packager_id},
                log_cmd=True
            )
            
            # If first attempt fails, try yay fallback for missing dependencies
            if build_result.returncode != 0:
                self.logger.warning(f"First build attempt failed for {pkg_name}, trying AUR dependency fallback...")
                
                # Extract missing dependencies from error output
                error_output = build_result.stderr if build_result.stderr else build_result.stdout
                missing_deps = self._extract_missing_dependencies(error_output)
                
                if missing_deps:
                    self.logger.info(f"Found missing dependencies: {missing_deps}")
                    
                    # Try to install missing dependencies with yay
                    deps_str = ' '.join(missing_deps)
                    yay_cmd = f"LC_ALL=C yay -S --needed --noconfirm {deps_str}"
                    yay_result = self.shell_executor.run(
                        yay_cmd,
                        log_cmd=True,
                        check=False,
                        user="builder",
                        timeout=1800
                    )
                    
                    if yay_result.returncode == 0:
                        self.logger.info("✅ Missing dependencies installed via yay, retrying build...")
                        
                        # Retry the build
                        build_result = self.shell_executor.run(
                            f"makepkg {makepkg_flags}",
                            cwd=pkg_dir,
                            capture=True,
                            check=False,
                            timeout=3600,
                            extra_env={"PACKAGER": self.packager_id},
                            log_cmd=True
                        )
                    else:
                        self.logger.error(f"❌ Failed to install missing dependencies with yay")
                        return False
            
            if build_result.returncode == 0:
                moved = False
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    self.logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                    built_files.append(str(dest))
                
                if moved:
                    # Collect metadata for hokibot
                    if built_files:
                        # Simplified metadata extraction
                        self.hokibot_data.append({
                            'name': pkg_name,
                            'built_version': version,
                            'pkgver': pkgver,
                            'pkgrel': pkgrel,
                            'epoch': epoch
                        })
                        self.logger.info(f"📝 HOKIBOT observed: {pkg_name} -> {version}")
                    
                    return True
                else:
                    self.logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                self.logger.error(f"Failed to build {pkg_name}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error building {pkg_name}: {e}")
            return False
    
    def _clean_workspace(self, pkg_dir: Path):
        """Clean workspace before building to avoid contamination"""
        self.logger.info(f"🧹 Cleaning workspace for {pkg_dir.name}...")
        
        # Clean src/ directory if exists
        src_dir = pkg_dir / "src"
        if src_dir.exists():
            try:
                shutil.rmtree(src_dir, ignore_errors=True)
                self.logger.info(f"  Cleaned src/ directory")
            except Exception as e:
                self.logger.warning(f"  Could not clean src/: {e}")
        
        # Clean pkg/ directory if exists
        pkg_build_dir = pkg_dir / "pkg"
        if pkg_build_dir.exists():
            try:
                shutil.rmtree(pkg_build_dir, ignore_errors=True)
                self.logger.info(f"  Cleaned pkg/ directory")
            except Exception as e:
                self.logger.warning(f"  Could not clean pkg/: {e}")
        
        # Clean any leftover .tar.* files
        for leftover in pkg_dir.glob("*.pkg.tar.*"):
            try:
                leftover.unlink()
                self.logger.info(f"  Removed leftover package: {leftover.name}")
            except Exception as e:
                self.logger.warning(f"  Could not remove {leftover}: {e}")
    
    def _extract_missing_dependencies(self, error_output: str) -> List[str]:
        """Extract missing dependencies from error output"""
        missing_deps = []
        
        # Look for patterns like "error: target not found: <package>"
        missing_patterns = [
            r"error: target not found: (\S+)",
            r"Could not find all required packages:",
            r":: Unable to find (\S+)",
        ]
        
        for pattern in missing_patterns:
            matches = re.findall(pattern, error_output)
            if matches:
                missing_deps.extend(matches)
        
        # Also look for specific makepkg dependency errors
        if "makepkg: cannot find the" in error_output:
            lines = error_output.split('\n')
            for line in lines:
                if "makepkg: cannot find the" in line:
                    # Extract package name from line like "makepkg: cannot find the 'gcc14' package"
                    dep_match = re.search(r"cannot find the '([^']+)'", line)
                    if dep_match:
                        missing_deps.append(dep_match.group(1))
        
        # Remove duplicates
        missing_deps = list(set(missing_deps))
        return missing_deps
    
    def get_hokibot_data(self):
        """Get collected hokibot data"""
        return self.hokibot_data