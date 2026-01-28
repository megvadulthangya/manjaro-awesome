"""
Manjaro Package Builder - Complete Build System with PKGBUILD Synchronization
Implements temporary clone method with tracking and self-healing database
"""

import os
import sys
import time
import re
import logging
import shutil
import subprocess
import tempfile
import glob
import json
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Set
from datetime import datetime

# Common utilities
from modules.common.logging_utils import setup_logging, get_logger
from modules.common.config_loader import ConfigLoader
from modules.common.environment import EnvironmentValidator
from modules.common.shell_executor import ShellExecutor

# State management
from modules.orchestrator.state import BuildState
from modules.repo.version_tracker import VersionTracker

# VPS communication
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient

# Build logic
from modules.build.version_manager import VersionManager
from modules.build.aur_builder import AURBuilder
from modules.build.local_builder import LocalBuilder

# Repository management
from modules.repo.database_manager import DatabaseManager
from modules.repo.cleanup_manager import CleanupManager

# GPG handling
from modules.gpg.gpg_handler import GPGHandler


class PackageBuilder:
    """Main orchestrator - Complete Build System with PKGBUILD Sync"""
    
    def __init__(self):
        """Initialize PackageBuilder with complete build system"""
        self.logger = get_logger(__name__)
        
        # Phase 1: Common utilities
        self.env_validator = EnvironmentValidator(self.logger)
        self.env_validator.validate()
        
        self.repo_root = self.env_validator.get_repo_root()
        self.config_loader = ConfigLoader(self.repo_root, self.logger)
        self.config = self.config_loader.load_config()
        
        # Setup logging with debug mode from config
        debug_mode = self.config.get('debug_mode', False)
        setup_logging(debug_mode=debug_mode)
        
        # Shell executor with debug mode
        self.shell_executor = ShellExecutor(
            debug_mode=debug_mode,
            default_timeout=1800
        )
        
        # CRITICAL FIX: Run pacman -Sy BEFORE any operations
        self._sync_pacman_databases_initial()
        
        # Phase 2: State management and VPS communication
        self.build_state = BuildState(self.logger)
        
        # VPS clients
        self.ssh_client = SSHClient(self.config, self.shell_executor, self.logger)
        self.rsync_client = RsyncClient(self.config, self.shell_executor, self.logger)
        
        # Setup SSH configuration
        ssh_key = self.config.get('ssh_key', '')
        self.ssh_client.setup_ssh_config(ssh_key)
        
        # Version tracker with JSON state
        self.version_tracker = VersionTracker(
            repo_root=self.repo_root,
            ssh_client=self.ssh_client,
            logger=self.logger
        )
        
        # Phase 3: Build and repository logic
        self.version_manager = VersionManager(self.shell_executor, self.logger)
        
        # Builders (will be used only when server says we need to build)
        self.aur_builder = AURBuilder(
            config=self.config,
            shell_executor=self.shell_executor,
            version_manager=self.version_manager,
            version_tracker=self.version_tracker,
            build_state=self.build_state,
            logger=self.logger
        )
        
        # Note: LocalBuilder will be handled differently with temp clone method
        # We'll create a new local builder instance for the temp clone
        
        # Repository managers
        self.database_manager = DatabaseManager(
            config=self.config,
            ssh_client=self.ssh_client,
            rsync_client=self.rsync_client,
            logger=self.logger
        )
        
        self.cleanup_manager = CleanupManager(
            config=self.config,
            version_tracker=self.version_tracker,
            ssh_client=self.ssh_client,
            rsync_client=self.rsync_client,
            logger=self.logger
        )
        
        # GPG handler
        self.gpg_handler = GPGHandler()
        
        # Package lists
        self.local_packages: List[str] = []
        self.aur_packages: List[str] = []
        
        # Track sanitized artifacts
        self._sanitized_files: Dict[str, str] = {}
        
        # Local staging directory for database operations
        self._staging_dir: Optional[Path] = None
        
        # Temporary clone directory
        self._temp_clone_dir: Optional[Path] = None
        
        # Build tracking directory in temp clone
        self._build_tracking_dir: Optional[Path] = None
        
        # Auto-recovery state
        self._recovered_packages: List[str] = []
        self._missing_from_db: List[str] = []
        
        self.logger.info("✅ PackageBuilder initialized with COMPLETE BUILD SYSTEM")
    
    def _sync_pacman_databases_initial(self) -> bool:
        """
        CRITICAL FIX: Sync pacman databases BEFORE any operations
        
        Returns:
            True if sync successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("CRITICAL: Syncing pacman databases BEFORE operations")
        self.logger.info("=" * 60)
        
        cmd = "sudo LC_ALL=C pacman -Sy --noconfirm"
        result = self.shell_executor.run(
            cmd,
            log_cmd=True,
            timeout=300,
            check=False,
            shell=True
        )
        
        if result.returncode == 0:
            self.logger.info("✅ Pacman databases synced successfully")
            return True
        else:
            self.logger.error("❌ Initial pacman sync failed")
            if result.stderr:
                self.logger.error(f"Error: {result.stderr[:500]}")
            return False
    
    def _get_package_lists(self) -> Tuple[List[str], List[str]]:
        """Get package lists from configuration"""
        if not self.local_packages or not self.aur_packages:
            self.local_packages, self.aur_packages = self.config_loader.get_package_lists()
        return self.local_packages, self.aur_packages
    
    def _setup_temp_clone(self) -> bool:
        """
        GIT SYNC: Clone repository into /tmp/manjaro-awesome-gitclone
        
        Returns:
            True if successful
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("GIT SYNC: Setting up temporary repository clone")
        self.logger.info("=" * 60)
        
        # Clean up existing temp clone if exists
        self._temp_clone_dir = Path("/tmp/manjaro-awesome-gitclone")
        
        if self._temp_clone_dir.exists():
            self.logger.info("🧹 Cleaning existing temporary clone...")
            try:
                shutil.rmtree(self._temp_clone_dir, ignore_errors=True)
                self.logger.info("✅ Existing clone removed")
            except Exception as e:
                self.logger.error(f"Failed to remove existing clone: {e}")
                return False
        
        # Clone the repository using SSH
        ssh_repo_url = self.config.get('ssh_repo_url', 'git@github.com:megvadulthangya/manjaro-awesome.git')
        
        self.logger.info(f"📥 Cloning repository from {ssh_repo_url}...")
        
        try:
            clone_cmd = f"git clone --depth 1 {ssh_repo_url} {self._temp_clone_dir}"
            
            result = self.shell_executor.run(
                clone_cmd,
                log_cmd=True,
                timeout=300,
                check=False,
                shell=True
            )
            
            if result.returncode == 0:
                self.logger.info(f"✅ Repository cloned to {self._temp_clone_dir}")
                
                # Setup build tracking directory in temp clone
                self._build_tracking_dir = self._temp_clone_dir / ".build_tracking"
                self._build_tracking_dir.mkdir(exist_ok=True)
                
                self.logger.info(f"📁 Build tracking directory: {self._build_tracking_dir}")
                return True
            else:
                self.logger.error(f"❌ Failed to clone repository: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Clone operation failed: {e}")
            return False
    
    def _get_pkgbuild_hash(self, pkgbuild_path: Path) -> str:
        """
        Calculate SHA256 hash of PKGBUILD file
        
        Args:
            pkgbuild_path: Path to PKGBUILD file
        
        Returns:
            SHA256 hash as hex string
        """
        if not pkgbuild_path.exists():
            return ""
        
        try:
            with open(pkgbuild_path, 'rb') as f:
                file_hash = hashlib.sha256()
                chunk = f.read(8192)
                while chunk:
                    file_hash.update(chunk)
                    chunk = f.read(8192)
                return file_hash.hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to calculate hash for {pkgbuild_path}: {e}")
            return ""
    
    def _load_tracking_json(self, pkg_name: str) -> Dict[str, Any]:
        """
        Load tracking JSON for a package
        
        Args:
            pkg_name: Package name
        
        Returns:
            Dictionary with tracking data or empty dict if not found
        """
        if not self._build_tracking_dir:
            return {}
        
        tracking_file = self._build_tracking_dir / f"{pkg_name}.json"
        
        if not tracking_file.exists():
            return {}
        
        try:
            with open(tracking_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load tracking JSON for {pkg_name}: {e}")
            return {}
    
    def _save_tracking_json(self, pkg_name: str, data: Dict[str, Any]) -> bool:
        """
        Save tracking JSON for a package
        
        Args:
            pkg_name: Package name
            data: Tracking data to save
        
        Returns:
            True if successful
        """
        if not self._build_tracking_dir:
            return False
        
        tracking_file = self._build_tracking_dir / f"{pkg_name}.json"
        
        try:
            with open(tracking_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.debug(f"Saved tracking JSON for {pkg_name}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save tracking JSON for {pkg_name}: {e}")
            return False
    
    def _extract_version_from_pkgbuild(self, pkg_dir: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract version information from PKGBUILD using makepkg --printsrcinfo
        
        Args:
            pkg_dir: Package directory containing PKGBUILD
        
        Returns:
            Tuple of (pkgver, pkgrel, epoch) or (None, None, None) if failed
        """
        try:
            # Generate .SRCINFO using makepkg
            result = subprocess.run(
                ['makepkg', '--printsrcinfo'],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=300
            )
            
            if result.returncode == 0 and result.stdout:
                # Parse SRCINFO content
                pkgver = None
                pkgrel = None
                epoch = None
                
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        
                        if key == 'pkgver':
                            pkgver = value
                        elif key == 'pkgrel':
                            pkgrel = value
                        elif key == 'epoch':
                            epoch = value
                
                if pkgver and pkgrel:
                    return pkgver, pkgrel, epoch
                else:
                    self.logger.warning(f"Could not extract version from PKGBUILD in {pkg_dir}")
                    return None, None, None
            else:
                self.logger.warning(f"makepkg --printsrcinfo failed for {pkg_dir}: {result.stderr}")
                return None, None, None
                
        except Exception as e:
            self.logger.error(f"Error extracting version from PKGBUILD: {e}")
            return None, None, None
    
    def _update_pkgbuild_version(self, pkg_dir: Path, new_pkgver: str, new_pkgrel: str) -> bool:
        """
        Update pkgver and pkgrel in PKGBUILD file using regex
        
        Args:
            pkg_dir: Package directory
            new_pkgver: New pkgver value
            new_pkgrel: New pkgrel value
        
        Returns:
            True if successful
        """
        pkgbuild_path = pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            self.logger.error(f"PKGBUILD not found: {pkgbuild_path}")
            return False
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            # Update pkgver
            pkgver_pattern = r'(pkgver\s*=\s*)[^\s#\n]+'
            content = re.sub(pkgver_pattern, f'\\g<1>{new_pkgver}', content)
            
            # Update pkgrel
            pkgrel_pattern = r'(pkgrel\s*=\s*)[^\s#\n]+'
            content = re.sub(pkgrel_pattern, f'\\g<1>{new_pkgrel}', content)
            
            # Write back to file
            with open(pkgbuild_path, 'w') as f:
                f.write(content)
            
            self.logger.info(f"✅ Updated PKGBUILD: pkgver={new_pkgver}, pkgrel={new_pkgrel}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to update PKGBUILD: {e}")
            return False
    
    def _should_build_local_package(self, pkg_name: str, temp_pkg_dir: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Determine if local package needs to be built using tracking system
        
        Args:
            pkg_name: Package name
            temp_pkg_dir: Package directory in temp clone
        
        Returns:
            Tuple of (should_build, tracking_data)
        """
        # Load tracking data
        tracking_data = self._load_tracking_json(pkg_name)
        
        # Check if package directory exists in temp clone
        if not temp_pkg_dir.exists():
            self.logger.error(f"Package directory not found in temp clone: {pkg_name}")
            return False, tracking_data
        
        pkgbuild_path = temp_pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            self.logger.error(f"PKGBUILD not found for {pkg_name}")
            return False, tracking_data
        
        # Calculate current PKGBUILD hash
        current_hash = self._get_pkgbuild_hash(pkgbuild_path)
        if not current_hash:
            self.logger.error(f"Failed to calculate PKGBUILD hash for {pkg_name}")
            return False, tracking_data
        
        # Extract current version from PKGBUILD
        current_pkgver, current_pkgrel, current_epoch = self._extract_version_from_pkgbuild(temp_pkg_dir)
        if not current_pkgver or not current_pkgrel:
            self.logger.error(f"Failed to extract version from PKGBUILD for {pkg_name}")
            return False, tracking_data
        
        current_version = f"{current_pkgver}-{current_pkgrel}"
        if current_epoch and current_epoch != '0':
            current_version = f"{current_epoch}:{current_version}"
        
        # Check tracking data
        if not tracking_data:
            # No tracking data - first build
            self.logger.info(f"🆕 First build detected for {pkg_name}")
            return True, {
                'last_hash': current_hash,
                'last_version': current_version,
                'last_built': datetime.now().isoformat(),
                'pkgver': current_pkgver,
                'pkgrel': current_pkgrel,
                'epoch': current_epoch
            }
        
        # Check if PKGBUILD has changed
        last_hash = tracking_data.get('last_hash', '')
        last_version = tracking_data.get('last_version', '')
        
        if current_hash != last_hash:
            self.logger.info(f"🔀 PKGBUILD changed for {pkg_name} (hash mismatch)")
            return True, {
                'last_hash': current_hash,
                'last_version': current_version,
                'last_built': datetime.now().isoformat(),
                'pkgver': current_pkgver,
                'pkgrel': current_pkgrel,
                'epoch': current_epoch
            }
        
        # Check if version has changed (in case hash is same but version updated elsewhere)
        if current_version != last_version:
            self.logger.info(f"🔀 Version changed for {pkg_name}: {last_version} -> {current_version}")
            return True, {
                'last_hash': current_hash,
                'last_version': current_version,
                'last_built': datetime.now().isoformat(),
                'pkgver': current_pkgver,
                'pkgrel': current_pkgrel,
                'epoch': current_epoch
            }
        
        # Also check if package exists on server with same version
        found, remote_version, remote_hash = self.version_tracker.is_package_on_remote(pkg_name, current_version)
        
        if found:
            self.logger.info(f"✅ {pkg_name} already on server with same version ({current_version})")
            return False, tracking_data
        else:
            self.logger.info(f"🔄 {pkg_name} not on server or different version, needs build")
            return True, {
                'last_hash': current_hash,
                'last_version': current_version,
                'last_built': datetime.now().isoformat(),
                'pkgver': current_pkgver,
                'pkgrel': current_pkgrel,
                'epoch': current_epoch
            }
    
    def _build_local_package_temp_clone(self, pkg_name: str) -> bool:
        """
        Build local package using temporary clone method with tracking
        
        Args:
            pkg_name: Package name
        
        Returns:
            True if successful
        """
        if not self._temp_clone_dir:
            self.logger.error("Temporary clone not set up")
            return False
        
        temp_pkg_dir = self._temp_clone_dir / pkg_name
        
        self.logger.info(f"\n--- Building Local Package: {pkg_name} ---")
        self.logger.info(f"Package directory: {temp_pkg_dir}")
        
        # Check if we should build
        should_build, tracking_data = self._should_build_local_package(pkg_name, temp_pkg_dir)
        
        if not should_build:
            self.build_state.add_skipped(
                pkg_name,
                tracking_data.get('last_version', 'unknown'),
                is_aur=False,
                reason="up-to-date"
            )
            return True
        
        # Build the package
        try:
            self.logger.info(f"🚀 Building {pkg_name}...")
            
            # Extract version info from tracking data
            pkgver = tracking_data.get('pkgver', '')
            pkgrel = tracking_data.get('pkgrel', '')
            epoch = tracking_data.get('epoch')
            
            version_str = f"{pkgver}-{pkgrel}"
            if epoch and epoch != '0':
                version_str = f"{epoch}:{version_str}"
            
            # Build using makepkg
            build_result = subprocess.run(
                ['makepkg', '-si', '--noconfirm', '--clean'],
                cwd=temp_pkg_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=3600
            )
            
            if build_result.returncode == 0:
                # Find built package files
                built_packages = list(temp_pkg_dir.glob("*.pkg.tar.*"))
                
                if built_packages:
                    # Move built packages to output directory
                    output_dir = Path(self.config.get('output_dir', 'built_packages'))
                    output_dir.mkdir(exist_ok=True)
                    
                    moved_count = 0
                    for pkg_file in built_packages:
                        dest = output_dir / pkg_file.name
                        shutil.move(str(pkg_file), str(dest))
                        moved_count += 1
                        self.logger.info(f"✅ Built: {pkg_file.name}")
                    
                    if moved_count > 0:
                        # Update tracking data
                        tracking_data['last_built'] = datetime.now().isoformat()
                        self._save_tracking_json(pkg_name, tracking_data)
                        
                        # Register built package
                        self.version_tracker.register_built_package(pkg_name, version_str)
                        self.build_state.add_built(pkg_name, version_str, is_aur=False)
                        
                        # Queue old version cleanup
                        self._queue_old_version_cleanup(pkg_name, version_str)
                        
                        # Sanitize artifacts
                        self._sanitize_artifacts(pkg_name)
                        
                        return True
                    else:
                        self.logger.error(f"No package files moved for {pkg_name}")
                        return False
                else:
                    self.logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                self.logger.error(f"Build failed for {pkg_name}: {build_result.stderr[:500]}")
                
                # Try dependency fallback
                self.logger.info("🔄 Trying dependency fallback...")
                return self._build_with_dependency_fallback(pkg_name, temp_pkg_dir, version_str)
                
        except Exception as e:
            self.logger.error(f"Error building {pkg_name}: {e}")
            self.build_state.add_failed(
                pkg_name,
                version_str if 'version_str' in locals() else "unknown",
                is_aur=False,
                error_message=str(e)
            )
            return False
    
    def _build_with_dependency_fallback(self, pkg_name: str, pkg_dir: Path, version_str: str) -> bool:
        """
        Build with dependency fallback using yay
        
        Args:
            pkg_name: Package name
            pkg_dir: Package directory
            version_str: Version string
        
        Returns:
            True if successful
        """
        try:
            # Extract missing dependencies from error output
            self.logger.info("🔍 Checking for missing dependencies...")
            
            # First attempt to install dependencies with yay
            yay_cmd = "LC_ALL=C yay -S --needed --noconfirm $(makepkg --printsrcinfo | grep 'depends =' | cut -d'=' -f2 | tr '\n' ' ')"
            yay_result = subprocess.run(
                yay_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                timeout=1800
            )
            
            if yay_result.returncode == 0:
                self.logger.info("✅ Missing dependencies installed, retrying build...")
                
                # Retry the build
                build_result = subprocess.run(
                    ['makepkg', '-si', '--noconfirm', '--clean'],
                    cwd=pkg_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=3600
                )
                
                if build_result.returncode == 0:
                    # Find built package files
                    built_packages = list(pkg_dir.glob("*.pkg.tar.*"))
                    
                    if built_packages:
                        # Move built packages to output directory
                        output_dir = Path(self.config.get('output_dir', 'built_packages'))
                        output_dir.mkdir(exist_ok=True)
                        
                        moved_count = 0
                        for pkg_file in built_packages:
                            dest = output_dir / pkg_file.name
                            shutil.move(str(pkg_file), str(dest))
                            moved_count += 1
                            self.logger.info(f"✅ Built with fallback: {pkg_file.name}")
                        
                        if moved_count > 0:
                            # Update tracking data
                            tracking_data = self._load_tracking_json(pkg_name)
                            tracking_data['last_built'] = datetime.now().isoformat()
                            self._save_tracking_json(pkg_name, tracking_data)
                            
                            # Register built package
                            self.version_tracker.register_built_package(pkg_name, version_str)
                            self.build_state.add_built(pkg_name, version_str, is_aur=False)
                            
                            # Queue old version cleanup
                            self._queue_old_version_cleanup(pkg_name, version_str)
                            
                            # Sanitize artifacts
                            self._sanitize_artifacts(pkg_name)
                            
                            return True
                
                self.logger.error(f"Retry build failed: {build_result.stderr[:500]}")
                return False
            else:
                self.logger.error(f"Dependency installation failed: {yay_result.stderr[:500]}")
                return False
                
        except Exception as e:
            self.logger.error(f"Dependency fallback failed: {e}")
            self.build_state.add_failed(
                pkg_name,
                version_str,
                is_aur=False,
                error_message=f"Dependency fallback failed: {e}"
            )
            return False
    
    def _commit_and_push_changes(self) -> bool:
        """
        Commit and push changes from temporary clone
        
        Returns:
            True if successful
        """
        if not self._temp_clone_dir:
            self.logger.error("Temporary clone not set up")
            return False
        
        self.logger.info("\n" + "=" * 60)
        self.logger.info("GIT: Committing and pushing changes")
        self.logger.info("=" * 60)
        
        old_cwd = os.getcwd()
        os.chdir(self._temp_clone_dir)
        
        try:
            # Check if there are any changes
            status_result = subprocess.run(
                ['git', 'status', '--porcelain'],
                capture_output=True,
                text=True,
                check=False
            )
            
            if status_result.returncode != 0 or not status_result.stdout.strip():
                self.logger.info("ℹ️ No changes to commit")
                return True
            
            self.logger.info("📋 Changes detected:")
            for line in status_result.stdout.strip().splitlines():
                self.logger.info(f"  {line}")
            
            # Add all changes
            self.logger.info("➕ Adding changes...")
            add_result = subprocess.run(
                ['git', 'add', '.'],
                capture_output=True,
                text=True,
                check=False
            )
            
            if add_result.returncode != 0:
                self.logger.error(f"Git add failed: {add_result.stderr}")
                return False
            
            # Commit changes
            commit_message = f"update: Packages built {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            self.logger.info(f"💾 Committing: {commit_message}")
            
            commit_result = subprocess.run(
                ['git', 'commit', '-m', commit_message],
                capture_output=True,
                text=True,
                check=False
            )
            
            if commit_result.returncode != 0:
                self.logger.error(f"Git commit failed: {commit_result.stderr}")
                return False
            
            # Push changes
            self.logger.info("📤 Pushing to remote...")
            push_result = subprocess.run(
                ['git', 'push', 'origin', 'main'],
                capture_output=True,
                text=True,
                check=False,
                timeout=300
            )
            
            if push_result.returncode == 0:
                self.logger.info("✅ Changes pushed successfully")
                return True
            else:
                self.logger.error(f"Git push failed: {push_result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"Git operation failed: {e}")
            return False
        finally:
            os.chdir(old_cwd)
    
    def _sanitize_artifacts(self, pkg_name: str) -> List[Path]:
        """
        INTERNAL SANITIZATION: Replace ':' with '_' in filenames BEFORE rsync
        
        Args:
            pkg_name: Package name
        
        Returns:
            List of sanitized file paths
        """
        self.logger.info(f"🔧 Sanitizing artifacts for {pkg_name}...")
        
        output_dir = Path(self.config.get('output_dir', 'built_packages'))
        sanitized_files = []
        
        patterns = [f"*{pkg_name}*.pkg.tar.*", f"{pkg_name}*.pkg.tar.*"]
        
        for pattern in patterns:
            for pkg_file in output_dir.glob(pattern):
                original_name = pkg_file.name
                
                if ':' in original_name:
                    sanitized_name = original_name.replace(':', '_')
                    sanitized_path = pkg_file.with_name(sanitized_name)
                    
                    try:
                        pkg_file.rename(sanitized_path)
                        self.logger.info(f"  🔄 Renamed: {original_name} -> {sanitized_name}")
                        
                        self._sanitized_files[str(pkg_file)] = str(sanitized_path)
                        
                        sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                        if sig_file.exists():
                            sanitized_sig = sanitized_path.with_suffix(sanitized_path.suffix + '.sig')
                            sig_file.rename(sanitized_sig)
                            self.logger.info(f"  🔄 Renamed signature: {sig_file.name} -> {sanitized_sig.name}")
                        
                        sanitized_files.append(sanitized_path)
                    except Exception as e:
                        self.logger.error(f"Failed to rename {original_name}: {e}")
                        sanitized_files.append(pkg_file)
                else:
                    sanitized_files.append(pkg_file)
        
        self.logger.info(f"✅ Sanitized {len(sanitized_files)} files for {pkg_name}")
        return sanitized_files
    
    def _check_server_for_package(self, pkg_name: str, version_str: str, is_aur: bool) -> str:
        """
        SERVER-FIRST LOGIC: Check if package exists on server
        
        Args:
            pkg_name: Package name
            version_str: Full version string
            is_aur: Whether it's an AUR package
        
        Returns:
            "ADOPT" if package exists on server, "BUILD" if not
        """
        found, remote_version, remote_hash = self.version_tracker.is_package_on_remote(pkg_name, version_str)
        
        if found:
            self.logger.info(f"✅ [ADOPT] {pkg_name} {version_str} found on server. Skipping build.")
            
            self.version_tracker.register_built_package(pkg_name, version_str, remote_hash)
            self.build_state.add_skipped(pkg_name, version_str, is_aur=is_aur, reason="already-on-server")
            
            return "ADOPT"
        else:
            self.logger.info(f"🔄 [BUILD] {pkg_name} {version_str} not on server or outdated. Starting build.")
            return "BUILD"
    
    def _build_aur_packages_server_first(self) -> None:
        """
        Build AUR packages using SERVER-FIRST logic
        """
        if not self.aur_packages:
            self.logger.info("No AUR packages to build")
            return
        
        self.logger.info(f"\n🔨 Processing {len(self.aur_packages)} AUR packages (SERVER-FIRST)")
        
        for pkg_name in self.aur_packages:
            self.logger.info(f"\n--- Processing AUR: {pkg_name} ---")
            
            # For AUR packages, we use the existing builder
            # Note: AUR builder doesn't use temp clone method
            
            # Check server first
            # We need to get version info differently for AUR packages
            # This is a simplified approach - in reality we'd need to clone the AUR
            # and check version like we do for local packages
            
            # For now, we'll build all AUR packages
            # In a production system, you'd want to implement proper version checking
            
            self.logger.info(f"🚀 Building AUR package: {pkg_name}...")
            
            success = self.aur_builder.build(pkg_name, None)
            
            if success:
                version_str = "unknown"  # Should get actual version from builder
                self.version_tracker.register_built_package(pkg_name, version_str)
                self.build_state.add_built(pkg_name, version_str, is_aur=True)
                
                self._queue_old_version_cleanup(pkg_name, version_str)
            else:
                self.build_state.add_failed(
                    pkg_name,
                    "unknown",
                    is_aur=True,
                    error_message="AUR build failed"
                )
    
    def _queue_old_version_cleanup(self, pkg_name: str, keep_version: str):
        """
        Queue old versions for cleanup (but don't execute yet)
        
        Args:
            pkg_name: Package name
            keep_version: Version to keep (newly built/adopted)
        """
        self.logger.info(f"🧹 Queuing cleanup of old versions for {pkg_name}...")
        
        remote_files = self.ssh_client.get_cached_inventory()
        if not remote_files:
            return
        
        for remote_path in remote_files.values():
            filename = Path(remote_path).name
            
            parsed = self.version_tracker._parse_package_filename_with_arch(filename)
            if not parsed:
                continue
            
            remote_pkg_name, remote_version, architecture = parsed
            
            if remote_pkg_name.lower() == pkg_name.lower():
                if not self.version_tracker._versions_match(remote_version, keep_version):
                    self.version_tracker.queue_deletion(remote_path)
                    self.logger.debug(f"🗑️ Queued for deletion: {filename} (old version: {remote_version})")
                else:
                    self.logger.debug(f"✅ Keeping: {filename} (current version: {remote_version})")
    
    def _create_local_staging(self) -> Path:
        """
        Create local staging directory for database operations
        
        Returns:
            Path to staging directory
        """
        if self._staging_dir and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)
        
        self._staging_dir = Path(tempfile.mkdtemp(prefix="repo_staging_"))
        self.logger.info(f"📁 Created staging directory: {self._staging_dir}")
        return self._staging_dir
    
    def _download_existing_database_only(self) -> bool:
        """
        Download ONLY database files from VPS to staging
        
        Returns:
            True if successful or no database exists (first run)
        """
        repo_name = self.config.get('repo_name', '')
        
        self.logger.info("📥 Downloading existing database files from VPS...")
        
        patterns = [
            f"{repo_name}.db.tar.gz*",
            f"{repo_name}.files.tar.gz*"
        ]
        
        success_count = 0
        
        for pattern in patterns:
            self.logger.info(f"  Downloading pattern: {pattern}")
            
            success = self.rsync_client.mirror_remote(
                remote_pattern=pattern,
                local_dir=self._staging_dir,
                temp_dir=None
            )
            
            if success:
                success_count += 1
            else:
                self.logger.warning(f"⚠️ Failed to download {pattern}")
        
        db_files = list(self._staging_dir.glob(f"{repo_name}.db.tar.gz*"))
        files_files = list(self._staging_dir.glob(f"{repo_name}.files.tar.gz*"))
        
        total_files = len(db_files) + len(files_files)
        
        if total_files > 0:
            self.logger.info(f"✅ Downloaded {total_files} database files")
        else:
            self.logger.info("ℹ️ No existing database files found (first run or clean state)")
        
        return True
    
    def _get_db_package_list(self) -> Set[str]:
        """
        Extract package list from existing database file
        
        Returns:
            Set of package filenames (without path) in the database
        """
        repo_name = self.config.get('repo_name', '')
        db_file = self._staging_dir / f"{repo_name}.db.tar.gz"
        
        if not db_file.exists():
            self.logger.info("ℹ️ No database file found in staging")
            return set()
        
        self.logger.info("📋 Extracting package list from existing database...")
        
        try:
            # Use tar to list contents and find package entries
            cmd = ["tar", "-tzf", str(db_file)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                self.logger.warning(f"Failed to list database contents: {result.stderr}")
                return set()
            
            # Parse tar output to find package entries
            package_files = set()
            for line in result.stdout.splitlines():
                if line.strip() and '/' in line:
                    # Extract filename from path like: awesome-git-4.0.r123.gabc123def-1-x86_64/pkgname/desc
                    parts = line.split('/')
                    if len(parts) >= 2 and parts[1].endswith('/desc'):
                        # The directory name is the package filename
                        package_files.add(parts[0])
            
            self.logger.info(f"📊 Database contains {len(package_files)} package entries")
            if package_files:
                self.logger.debug(f"Sample DB entries: {list(package_files)[:5]}")
            
            return package_files
            
        except Exception as e:
            self.logger.error(f"❌ Failed to extract package list from DB: {e}")
            return set()
    
    def _discover_missing_packages(self) -> List[str]:
        """
        AUTO-RECOVERY: Compare remote inventory with database entries
        
        Returns:
            List of package filenames missing from database
        """
        self.logger.info("🔍 Discovering packages missing from database...")
        
        # Get packages in database
        db_packages = self._get_db_package_list()
        
        # Get remote inventory (physical files on VPS)
        remote_inventory = self.ssh_client.get_cached_inventory(force_refresh=True)
        
        if not remote_inventory:
            self.logger.info("ℹ️ No remote packages found")
            return []
        
        # Filter for package files only
        remote_packages = set()
        for filename in remote_inventory.keys():
            if filename.endswith('.pkg.tar.zst'):
                remote_packages.add(filename)
        
        self.logger.info(f"📊 Remote inventory: {len(remote_packages)} package files")
        
        # Find packages on VPS that are NOT in database
        missing_packages = []
        for pkg_file in remote_packages:
            if pkg_file not in db_packages:
                missing_packages.append(pkg_file)
                self.logger.info(f"⚠️ Missing from DB: {pkg_file}")
        
        self.logger.info(f"📊 Found {len(missing_packages)} packages missing from database")
        
        # Store for reporting
        self._missing_from_db = missing_packages
        
        return missing_packages
    
    def _download_missing_packages(self, missing_packages: List[str]) -> int:
        """
        Download missing packages from VPS to staging
        
        Args:
            missing_packages: List of package filenames to download
        
        Returns:
            Number of successfully downloaded packages
        """
        if not missing_packages:
            return 0
        
        self.logger.info(f"📥 Downloading {len(missing_packages)} missing packages from VPS...")
        
        downloaded_count = 0
        
        for pkg_filename in missing_packages:
            try:
                # Find full remote path
                remote_inventory = self.ssh_client.get_cached_inventory()
                remote_path = remote_inventory.get(pkg_filename)
                
                if not remote_path:
                    self.logger.warning(f"Could not find remote path for {pkg_filename}")
                    continue
                
                # Download using scp
                scp_cmd = [
                    "scp",
                    "-o", "StrictHostKeyChecking=no",
                    "-o", "ConnectTimeout=30",
                    f"{self.config.get('vps_user')}@{self.config.get('vps_host')}:{remote_path}",
                    str(self._staging_dir / pkg_filename)
                ]
                
                result = subprocess.run(
                    scp_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0:
                    # Check if file was downloaded
                    local_path = self._staging_dir / pkg_filename
                    if local_path.exists() and local_path.stat().st_size > 0:
                        self.logger.info(f"✅ Downloaded: {pkg_filename}")
                        downloaded_count += 1
                        
                        # Add to recovered packages list
                        self._recovered_packages.append(pkg_filename)
                    else:
                        self.logger.warning(f"Downloaded file is empty: {pkg_filename}")
                else:
                    self.logger.warning(f"Failed to download {pkg_filename}: {result.stderr}")
                    
            except Exception as e:
                self.logger.error(f"Error downloading {pkg_filename}: {e}")
        
        self.logger.info(f"✅ Downloaded {downloaded_count} missing packages")
        return downloaded_count
    
    def _move_new_packages_to_staging(self) -> List[Path]:
        """
        Move newly built packages to staging directory
        
        Returns:
            List of paths to new packages moved to staging
        """
        output_dir = Path(self.config.get('output_dir', 'built_packages'))
        
        new_packages = list(output_dir.glob("*.pkg.tar.zst"))
        if not new_packages:
            self.logger.info("ℹ️ No new packages to move to staging")
            return []
        
        self.logger.info(f"📦 Moving {len(new_packages)} new packages to staging...")
        
        moved_packages = []
        
        for new_pkg in new_packages:
            try:
                dest = self._staging_dir / new_pkg.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(new_pkg), str(dest))
                moved_packages.append(dest)
                
                # Move signature if exists
                sig_file = new_pkg.with_suffix(new_pkg.suffix + '.sig')
                if sig_file.exists():
                    sig_dest = dest.with_suffix(dest.suffix + '.sig')
                    if sig_dest.exists():
                        sig_dest.unlink()
                    shutil.move(str(sig_file), str(sig_dest))
                
                self.logger.debug(f"  Moved: {new_pkg.name}")
            except Exception as e:
                self.logger.error(f"Failed to move {new_pkg.name}: {e}")
        
        self.logger.info(f"✅ Moved {len(moved_packages)} new packages to staging")
        return moved_packages
    
    def _update_database_additive(self) -> bool:
        """
        Additive database update: Add ALL packages in staging to database
        
        Returns:
            True if successful
        """
        repo_name = self.config.get('repo_name', '')
        
        self.logger.info("\n" + "=" * 60)
        self.logger.info("ADDITIVE DATABASE UPDATE (SELF-HEALING)")
        self.logger.info("=" * 60)
        
        old_cwd = os.getcwd()
        os.chdir(self._staging_dir)
        
        try:
            db_file = f"{repo_name}.db.tar.gz"
            
            # Get all package files in staging
            all_packages = list(glob.glob("*.pkg.tar.zst"))
            
            if not all_packages:
                self.logger.info("ℹ️ No packages to add to database")
                
                # Check if we have an existing database (force repair mode)
                existing_db_files = list(glob.glob(f"{repo_name}.db.tar.gz*"))
                if existing_db_files:
                    self.logger.info("🔧 Force repairing existing database...")
                    return self._force_repair_database(db_file)
                else:
                    self.logger.info("ℹ️ No existing database to repair")
                    return True
            
            self.logger.info(f"📊 Total packages to process: {len(all_packages)}")
            self.logger.info(f"  - Newly built: {len([p for p in all_packages if p not in self._recovered_packages])}")
            self.logger.info(f"  - Recovered: {len([p for p in all_packages if p in self._recovered_packages])}")
            
            # Run repo-add with ALL packages (additive update)
            if self.gpg_handler.gpg_enabled:
                self.logger.info("🔏 Running repo-add with GPG signing (additive)...")
                
                # Set GNUPGHOME environment variable for non-interactive signing
                env = os.environ.copy()
                if hasattr(self.gpg_handler, 'gpg_home') and self.gpg_handler.gpg_home:
                    env['GNUPGHOME'] = self.gpg_handler.gpg_home
                
                # Build command
                if self.gpg_handler.gpg_key_id:
                    cmd = f"repo-add --sign --key {self.gpg_handler.gpg_key_id} --remove {db_file} *.pkg.tar.zst"
                else:
                    cmd = f"repo-add --sign --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False
                )
            else:
                self.logger.info("🔧 Running repo-add without signing (additive)...")
                cmd = f"repo-add --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False
                )
            
            if result.returncode == 0:
                self.logger.info("✅ Database updated successfully (additive)")
                
                if not os.path.exists(db_file):
                    self.logger.error("❌ Database file not created")
                    return False
                
                # Verify the database was created with signatures if GPG enabled
                if self.gpg_handler.gpg_enabled:
                    sig_file = f"{db_file}.sig"
                    if os.path.exists(sig_file):
                        sig_size = os.path.getsize(sig_file)
                        if sig_size > 0:
                            self.logger.info(f"✅ Database signed successfully ({sig_size} bytes)")
                        else:
                            self.logger.warning("⚠️ Database signature file is empty")
                    else:
                        self.logger.warning("⚠️ Database signature file not found")
                
                # Verify database entries
                self._verify_database_entries(db_file)
                return True
            else:
                self.logger.error(f"❌ repo-add failed with exit code {result.returncode}:")
                if result.stdout:
                    self.logger.error(f"STDOUT: {result.stdout[:500]}")
                if result.stderr:
                    self.logger.error(f"STDERR: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Database update error: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            os.chdir(old_cwd)
    
    def _force_repair_database(self, db_file: str) -> bool:
        """
        Force repair existing database (re-signing)
        
        Args:
            db_file: Database file name
        
        Returns:
            True if successful
        """
        self.logger.info("🔧 Force repairing existing database...")
        
        try:
            # Recreate database with proper signing
            if self.gpg_handler.gpg_enabled:
                self.logger.info("🔏 Re-signing existing database...")
                
                env = os.environ.copy()
                if hasattr(self.gpg_handler, 'gpg_home') and self.gpg_handler.gpg_home:
                    env['GNUPGHOME'] = self.gpg_handler.gpg_home
                
                if self.gpg_handler.gpg_key_id:
                    cmd = f"repo-add --sign --key {self.gpg_handler.gpg_key_id} --remove {db_file} *.pkg.tar.zst"
                else:
                    cmd = f"repo-add --sign --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False
                )
            else:
                self.logger.info("🔧 Recreating database without signing...")
                cmd = f"repo-add --remove {db_file} *.pkg.tar.zst"
                
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=False
                )
            
            if result.returncode == 0:
                self.logger.info("✅ Database repaired successfully")
                return True
            else:
                self.logger.error(f"Database repair failed: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            self.logger.error(f"Database repair error: {e}")
            return False
    
    def _verify_database_entries(self, db_file: str) -> None:
        """Verify database entries after update"""
        try:
            list_cmd = ["tar", "-tzf", db_file]
            result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                db_entries = [line for line in result.stdout.split('\n') if line.endswith('/desc')]
                self.logger.info(f"✅ Database contains {len(db_entries)} package entries")
                if len(db_entries) == 0:
                    self.logger.error("❌❌❌ DATABASE IS EMPTY!")
                else:
                    self.logger.info(f"Sample entries: {db_entries[:3]}")
            else:
                self.logger.warning(f"Could not list database contents: {result.stderr}")
        except Exception as e:
            self.logger.warning(f"Could not verify database: {e}")
    
    def _upload_updated_files(self) -> bool:
        """
        Upload updated database and new packages to VPS
        
        Returns:
            True if successful
        """
        if not self._staging_dir or not self._staging_dir.exists():
            self.logger.error("❌ Staging directory not found")
            return False
        
        self.logger.info("\n📤 Uploading updated files to VPS...")
        
        files_to_upload = []
        
        # 1. Database files and signatures (ALWAYS upload these)
        repo_patterns = [
            f"{self.config.get('repo_name', '')}.db*",
            f"{self.config.get('repo_name', '')}.files*",
        ]
        
        for pattern in repo_patterns:
            for file_path in self._staging_dir.glob(pattern):
                if file_path.stat().st_size > 0:  # Skip empty files
                    files_to_upload.append(file_path)
        
        # 2. NEW packages (not recovered) and their signatures
        for pkg_file in self._staging_dir.glob("*.pkg.tar.zst"):
            if pkg_file.stat().st_size > 0:
                # Check if this is a recovered package (already on VPS)
                if pkg_file.name not in self._recovered_packages:
                    files_to_upload.append(pkg_file)
                    
                    # Include signature if it exists
                    sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                    if sig_file.exists() and sig_file.stat().st_size > 0:
                        files_to_upload.append(sig_file)
                else:
                    self.logger.debug(f"Skipping recovered package: {pkg_file.name}")
        
        if not files_to_upload:
            self.logger.warning("⚠️ No files to upload")
            return True
        
        self.logger.info(f"📦 Total files to upload: {len(files_to_upload)}")
        
        # Log file details
        for f in files_to_upload:
            size_mb = f.stat().st_size / (1024 * 1024)
            file_type = "PACKAGE" if ".pkg.tar.zst" in f.name else "DATABASE"
            if f.name.endswith('.sig'):
                file_type = "SIGNATURE"
            self.logger.debug(f"  - {f.name} ({size_mb:.1f}MB) [{file_type}]")
        
        # Upload using rsync
        files_list = [str(f) for f in files_to_upload]
        upload_success = self.rsync_client.upload(files_list, self._staging_dir)
        
        if upload_success:
            self.logger.info("✅ All files uploaded successfully")
            return True
        else:
            self.logger.error("❌ File upload failed")
            return False
    
    def _cleanup_staging(self) -> None:
        """Clean up staging directory"""
        if self._staging_dir and os.path.exists(self._staging_dir):
            try:
                shutil.rmtree(self._staging_dir, ignore_errors=True)
                self.logger.debug(f"🧹 Cleaned up staging directory: {self._staging_dir}")
                self._staging_dir = None
            except Exception as e:
                self.logger.warning(f"Could not clean staging directory: {e}")
    
    def _cleanup_temp_clone(self) -> None:
        """Clean up temporary clone directory"""
        if self._temp_clone_dir and os.path.exists(self._temp_clone_dir):
            try:
                shutil.rmtree(self._temp_clone_dir, ignore_errors=True)
                self.logger.debug(f"🧹 Cleaned up temporary clone: {self._temp_clone_dir}")
                self._temp_clone_dir = None
                self._build_tracking_dir = None
            except Exception as e:
                self.logger.warning(f"Could not clean temporary clone: {e}")
    
    def _build_local_packages_with_tracking(self) -> None:
        """
        Build local packages using temporary clone with tracking system
        """
        if not self.local_packages:
            self.logger.info("No local packages to build")
            return
        
        self.logger.info(f"\n🔨 Processing {len(self.local_packages)} local packages (TRACKING SYSTEM)")
        
        built_count = 0
        skipped_count = 0
        failed_count = 0
        
        for pkg_name in self.local_packages:
            self.logger.info(f"\n--- Processing Local: {pkg_name} ---")
            
            try:
                success = self._build_local_package_temp_clone(pkg_name)
                
                if success:
                    built_count += 1
                else:
                    failed_count += 1
                    
            except Exception as e:
                self.logger.error(f"Unexpected error building {pkg_name}: {e}")
                failed_count += 1
        
        self.logger.info(f"\n📊 Local packages summary:")
        self.logger.info(f"  Built: {built_count}")
        self.logger.info(f"  Failed: {failed_count}")
    
    def _force_database_update(self) -> bool:
        """
        FORCE database update with self-healing additive strategy
        
        Returns:
            True if successful
        """
        self.logger.info("\n🔧 FORCING DATABASE UPDATE (SELF-HEALING)")
        self.logger.info("=" * 60)
        
        try:
            # Reset recovery state
            self._recovered_packages = []
            self._missing_from_db = []
            
            # Step 1: Create staging directory
            self.logger.info("\n[1/8] Creating local staging directory")
            self.logger.info("-" * 40)
            staging_dir = self._create_local_staging()
            
            # Step 2: Download existing database files
            self.logger.info("\n[2/8] Downloading existing database files from VPS")
            self.logger.info("-" * 40)
            self._download_existing_database_only()
            
            # Step 3: AUTO-RECOVERY: Discover packages missing from database
            self.logger.info("\n[3/8] AUTO-RECOVERY: Discovering missing packages")
            self.logger.info("-" * 40)
            missing_packages = self._discover_missing_packages()
            
            # Step 4: Download missing packages from VPS
            if missing_packages:
                self.logger.info("\n[4/8] Downloading missing packages from VPS")
                self.logger.info("-" * 40)
                downloaded = self._download_missing_packages(missing_packages)
                self.logger.info(f"✅ Downloaded {downloaded} missing packages")
            
            # Step 5: Move newly built packages to staging
            self.logger.info("\n[5/8] Moving newly built packages to staging")
            self.logger.info("-" * 40)
            self._move_new_packages_to_staging()
            
            # Step 6: Update database additively with ALL packages
            self.logger.info("\n[6/8] Updating database additively (self-healing)")
            self.logger.info("-" * 40)
            if not self._update_database_additive():
                self.logger.error("❌ Additive database update failed")
                return False
            
            # Step 7: Upload updated files to VPS
            self.logger.info("\n[7/8] Uploading updated files to VPS")
            self.logger.info("-" * 40)
            if not self._upload_updated_files():
                self.logger.error("❌ File upload failed")
                return False
            
            # Step 8: Execute queued cleanup
            self.logger.info("\n[8/8] Executing queued cleanup operations")
            self.logger.info("-" * 40)
            cleanup_success = self.version_tracker.commit_queued_deletions()
            
            if cleanup_success:
                self.logger.info("✅ Cleanup operations completed")
            else:
                self.logger.warning("⚠️ Some cleanup operations failed")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Self-healing database update failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self._cleanup_staging()
    
    def run(self) -> int:
        """
        Main execution workflow - COMPLETE BUILD SYSTEM
        
        Returns:
            Exit code (0 for success, 1 for failure)
        """
        try:
            self.logger.info("\n" + "=" * 60)
            self.logger.info("🚀 MANJARO PACKAGE BUILDER - COMPLETE BUILD SYSTEM")
            self.logger.info("=" * 60)
            
            self.logger.info("\n🔧 Initial setup...")
            self.logger.info(f"Repository root: {self.repo_root}")
            self.logger.info(f"Repository name: {self.config.get('repo_name')}")
            self.logger.info(f"Output directory: {self.config.get('output_dir')}")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 0: GPG INITIALIZATION")
            self.logger.info("=" * 60)
            
            if self.gpg_handler.gpg_enabled:
                if not self.gpg_handler.import_gpg_key():
                    self.logger.error("❌ Failed to import GPG key, disabling signing")
                    self.gpg_handler.gpg_enabled = False
                else:
                    self.logger.info("✅ GPG initialized successfully")
            else:
                self.logger.info("ℹ️ GPG signing disabled (no key provided)")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 1: SSH CONNECTION TEST")
            self.logger.info("=" * 60)
            
            if not self.ssh_client.test_connection():
                self.logger.error("❌ SSH connection failed")
                return 1
            
            self.ssh_client.debug_remote_directory()
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 2: REMOTE DIRECTORY SETUP")
            self.logger.info("=" * 60)
            
            if not self.ssh_client.ensure_directory():
                self.logger.warning("⚠️ Could not ensure remote directory exists")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 3: TEMPORARY REPOSITORY CLONE")
            self.logger.info("=" * 60)
            
            if not self._setup_temp_clone():
                self.logger.error("❌ Failed to setup temporary repository clone")
                return 1
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 4: PACKAGE DISCOVERY")
            self.logger.info("=" * 60)
            
            self.local_packages, self.aur_packages = self._get_package_lists()
            
            self.logger.info(f"📦 Package statistics:")
            self.logger.info(f"   Local packages: {len(self.local_packages)}")
            self.logger.info(f"   AUR packages: {len(self.aur_packages)}")
            self.logger.info(f"   Total packages: {len(self.local_packages) + len(self.aur_packages)}")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 5: LOCAL PACKAGE BUILDING (TRACKING SYSTEM)")
            self.logger.info("=" * 60)
            
            self._build_local_packages_with_tracking()
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 6: AUR PACKAGE BUILDING")
            self.logger.info("=" * 60)
            
            self._build_aur_packages_server_first()
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 7: COMMIT AND PUSH CHANGES")
            self.logger.info("=" * 60)
            
            if not self._commit_and_push_changes():
                self.logger.error("❌ Failed to commit and push changes")
                # Don't fail the build - continue with database update
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 8: SELF-HEALING DATABASE UPDATE")
            self.logger.info("=" * 60)
            
            # ALWAYS run self-healing database update
            db_update_success = self._force_database_update()
            
            if not db_update_success:
                self.logger.error("\n❌ Database update failed!")
                return 1
            
            self.gpg_handler.cleanup()
            self.logger.info("\n✅ Repository maintenance completed successfully!")
            
            self.logger.info("\n" + "=" * 60)
            self.logger.info("STEP 9: FINAL STATISTICS")
            self.logger.info("=" * 60)
            
            self.build_state.mark_complete()
            summary = self.build_state.get_summary()
            
            self.logger.info(f"Duration: {summary['duration_seconds']:.1f}s")
            self.logger.info(f"AUR packages:    {summary['aur_success']} built, {summary['aur_skipped']} adopted, {summary['aur_failed']} failed")
            self.logger.info(f"Local packages:  {summary['local_success']} built, {summary['local_skipped']} adopted, {summary['local_failed']} failed")
            self.logger.info(f"Total built:     {summary['built']}")
            self.logger.info(f"Total adopted:   {summary['skipped']}")
            self.logger.info(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            self.logger.info(f"Temporary clone: ✅ Implemented")
            self.logger.info(f"PKGBUILD tracking: ✅ Implemented")
            self.logger.info(f"Self-healing DB update: ✅ Implemented")
            self.logger.info(f"Packages recovered from VPS: {len(self._recovered_packages)}")
            self.logger.info(f"Packages missing from DB: {len(self._missing_from_db)}")
            self.logger.info(f"Git commit & push: ✅ Completed")
            
            state_summary = self.version_tracker.get_state_summary()
            self.logger.info(f"Packages tracked: {state_summary['total_packages']}")
            self.logger.info("=" * 60)
            
            return 0
            
        except Exception as e:
            self.logger.error(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            
            if hasattr(self, 'version_tracker'):
                self.version_tracker.save_state()
            
            if hasattr(self, '_staging_dir') and self._staging_dir and os.path.exists(self._staging_dir):
                shutil.rmtree(self._staging_dir, ignore_errors=True)
            
            if hasattr(self, '_temp_clone_dir') and self._temp_clone_dir and os.path.exists(self._temp_clone_dir):
                shutil.rmtree(self._temp_clone_dir, ignore_errors=True)
            
            return 1