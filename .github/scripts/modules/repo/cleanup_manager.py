"""
Cleanup manager for Zero-Residue policy
Handles surgical removal of old package versions from local and remote systems
Extracted from RepoManager with enhanced precision
"""

import os
import shutil
import subprocess
import re
import logging
from pathlib import Path
from typing import Dict, Any, List, Set, Optional, Tuple

from modules.repo.version_tracker import VersionTracker
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient


class CleanupManager:
    """Manages Zero-Residue cleanup operations for local and remote systems"""
    
    def __init__(self, config: Dict[str, Any], version_tracker: VersionTracker,
                 ssh_client: SSHClient, rsync_client: RsyncClient,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize CleanupManager
        
        Args:
            config: Configuration dictionary
            version_tracker: VersionTracker instance
            ssh_client: SSHClient instance
            rsync_client: RsyncClient instance
            logger: Optional logger instance
        """
        self.config = config
        self.version_tracker = version_tracker
        self.ssh_client = ssh_client
        self.rsync_client = rsync_client
        self.logger = logger or logging.getLogger(__name__)
        
        # Extract configuration
        self.repo_name = config.get('repo_name', '')
        self.output_dir = Path(config.get('output_dir', 'built_packages'))
        self.remote_dir = config.get('remote_dir', '')
        
        # Upload success flag for safety valve
        self._upload_successful = False
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
    
    def purge_old_local(self, pkg_name: str, old_version: str, target_version: Optional[str] = None):
        """
        🚨 ZERO-RESIDUE POLICY: Surgical old version removal BEFORE building
        
        Removes old versions from local output directory before new build.
        
        Args:
            pkg_name: Package name
            old_version: Version to potentially delete
            target_version: Version we want to keep (None if building new)
        """
        # If we have a registered target version, use it
        if target_version is None:
            target_version = self.version_tracker.get_target_version(pkg_name)
        
        if target_version and old_version == target_version:
            # This is the version we want to keep
            self.logger.info(f"✅ No pre-build purge needed: {pkg_name} version {old_version} is target version")
            return
        
        # Delete old version from output directory
        self._delete_specific_version_local(pkg_name, old_version)
    
    def _delete_specific_version_local(self, pkg_name: str, version_to_delete: str):
        """Delete a specific version of a package from local output_dir"""
        patterns = self._version_to_patterns(pkg_name, version_to_delete)
        deleted_count = 0
        
        for pattern in patterns:
            for old_file in self.output_dir.glob(pattern):
                try:
                    # Verify this is actually the version we want to delete
                    extracted_version = self._extract_version_from_filename(old_file.name, pkg_name)
                    if extracted_version == version_to_delete:
                        old_file.unlink()
                        self.logger.info(f"🗑️ Surgically removed local {old_file.name}")
                        deleted_count += 1
                        
                        # Also remove signature
                        sig_file = old_file.with_suffix(old_file.suffix + '.sig')
                        if sig_file.exists():
                            sig_file.unlink()
                            self.logger.info(f"🗑️ Removed local signature {sig_file.name}")
                except Exception as e:
                    self.logger.warning(f"Could not delete local {old_file}: {e}")
        
        if deleted_count > 0:
            self.logger.info(f"✅ Removed {deleted_count} local files for {pkg_name} version {version_to_delete}")
    
    def validate_output_dir(self):
        """
        🔥 ZOMBIE PROTECTION: Final validation before database generation
        
        Enhanced to recognize skipped packages as legitimate (not zombies)
        
        Scans output_dir and ensures:
        1. Only one version per package exists
        2. If multiple versions exist, keep only the target version
        3. Delete any "zombie" files (old versions that shouldn't be there)
        
        This is the LAST CHANCE to clean up before repo-add runs.
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("🚨 FINAL VALIDATION: Removing zombie packages from output_dir")
        self.logger.info("=" * 60)
        
        # Get all package files in output_dir
        package_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not package_files:
            self.logger.info("ℹ️ No package files in output_dir to validate")
            return
        
        self.logger.info(f"🔍 Validating {len(package_files)} package files in output_dir...")
        
        # Group files by package name
        packages_dict: Dict[str, List[Tuple[str, Path]]] = {}
        
        for pkg_file in package_files:
            # Extract package name and version from filename
            extracted = self._parse_package_filename(pkg_file.name)
            if extracted:
                pkg_name, version_str = extracted
                if pkg_name not in packages_dict:
                    packages_dict[pkg_name] = []
                packages_dict[pkg_name].append((version_str, pkg_file))
        
        # Process each package
        total_deleted = 0
        
        for pkg_name, files in packages_dict.items():
            if len(files) > 1:
                self.logger.warning(f"⚠️ Multiple versions found for {pkg_name}: {[v[0] for v in files]}")
                
                # Check if we have a registered target version
                target_version = self.version_tracker.get_target_version(pkg_name)
                
                if target_version:
                    # Keep only the target version
                    kept = False
                    for version_str, file_path in files:
                        if version_str == target_version:
                            self.logger.info(f"✅ Keeping target version: {file_path.name} ({version_str})")
                            kept = True
                        else:
                            try:
                                file_path.unlink()
                                self.logger.info(f"🗑️ Removing non-target version: {file_path.name}")
                                total_deleted += 1
                            except Exception as e:
                                self.logger.warning(f"Could not delete {file_path}: {e}")
                    
                    if not kept:
                        self.logger.error(f"❌ Target version {target_version} for {pkg_name} not found in output_dir!")
                else:
                    # No target version registered, keep the latest
                    self.logger.warning(f"⚠️ No target version registered for {pkg_name}, using version comparison")
                    latest_version = self._find_latest_version([v[0] for v in files])
                    for version_str, file_path in files:
                        if version_str == latest_version:
                            self.logger.info(f"✅ Keeping latest version: {file_path.name} ({version_str})")
                        else:
                            try:
                                file_path.unlink()
                                self.logger.info(f"🗑️ Removing older version: {file_path.name}")
                                total_deleted += 1
                            except Exception as e:
                                self.logger.warning(f"Could not delete {file_path}: {e}")
        
        if total_deleted > 0:
            self.logger.info(f"🎯 Final validation: Removed {total_deleted} zombie package files")
        else:
            self.logger.info("✅ Output_dir validation passed - no zombie packages found")
    
    def cleanup_server(self):
        """
        🚨 ZERO-RESIDUE SERVER CLEANUP: Remove zombie packages from VPS 
        using TARGET VERSIONS as SOURCE OF TRUTH.
        
        Only keeps packages that match registered target versions.
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("🔒 ZERO-RESIDUE SERVER CLEANUP: Target Versions are Source of Truth")
        self.logger.info("=" * 60)
        
        # VALVE: Check if we have any target versions registered
        if not self.version_tracker.has_packages():
            self.logger.warning("⚠️ No target versions registered - skipping server cleanup")
            return
        
        self.logger.info(f"🔄 Zero-Residue cleanup initiated with {len(self.version_tracker.get_target_packages())} target versions")
        
        # STEP 1: Get ALL files from VPS
        vps_files = self.ssh_client.get_file_inventory()
        if not vps_files:
            self.logger.info("ℹ️ No files found on VPS - nothing to clean up")
            return
        
        # Update version tracker with remote inventory
        self.version_tracker.set_remote_inventory(vps_files)
        
        # STEP 2: Determine files to delete based on target versions
        files_to_delete = self.version_tracker.get_files_to_delete()
        
        if not files_to_delete:
            self.logger.info("✅ No zombie packages found on VPS")
            return
        
        self.logger.warning(f"🚨 Identified {len(files_to_delete)} zombie packages for deletion")
        
        # STEP 3: Execute deletion
        deleted_count = 0
        batch_size = 50
        
        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i:i + batch_size]
            if self.ssh_client.delete_remote_files(batch):
                deleted_count += len(batch)
        
        self.logger.info(f"📊 Server cleanup complete: Deleted {deleted_count} zombie packages")
    
    def _parse_package_filename(self, filename: str) -> Optional[Tuple[str, str]]:
        """Parse package filename to extract name and version"""
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            # The package name is everything before the last 3 parts (version-release-arch)
            # or last 4 parts (epoch-version-release-arch)
            if len(parts) >= 4:
                # Try to find where package name ends
                for i in range(len(parts) - 3, 0, -1):
                    potential_name = '-'.join(parts[:i])
                    
                    # Check if remaining parts look like version-release-arch
                    remaining = parts[i:]
                    if len(remaining) >= 3:
                        # Check for epoch format (e.g., "2-26.1.9-1-x86_64")
                        if remaining[0].isdigit() and '-' in '-'.join(remaining[1:]):
                            epoch = remaining[0]
                            version_part = remaining[1]
                            release_part = remaining[2]
                            version_str = f"{epoch}:{version_part}-{release_part}"
                            return potential_name, version_str
                        # Standard format (e.g., "26.1.9-1-x86_64")
                        elif any(c.isdigit() for c in remaining[0]) and remaining[1].isdigit():
                            version_part = remaining[0]
                            release_part = remaining[1]
                            version_str = f"{version_part}-{release_part}"
                            return potential_name, version_str
        except Exception as e:
            self.logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None
    
    def _version_to_patterns(self, pkg_name: str, version: str) -> List[str]:
        """Convert version string to filename patterns"""
        patterns = []
        
        if ':' in version:
            # Version with epoch: "2:26.1.9-1" -> "2-26.1.9-1-*.pkg.tar.*"
            epoch, rest = version.split(':', 1)
            patterns.append(f"{pkg_name}-{epoch}-{rest}-*.pkg.tar.*")
        else:
            # Standard version: "26.1.9-1" -> "*26.1.9-1-*.pkg.tar.*"
            patterns.append(f"{pkg_name}-{version}-*.pkg.tar.*")
        
        return patterns
    
    def _extract_version_from_filename(self, filename: str, pkg_name: str) -> Optional[str]:
        """
        Extract version from package filename
        
        Args:
            filename: Package filename (e.g., 'qownnotes-26.1.9-1-x86_64.pkg.tar.zst')
            pkg_name: Package name (e.g., 'qownnotes')
        
        Returns:
            Version string (e.g., '26.1.9-1') or None if cannot parse
        """
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            # Find where package name ends
            for i in range(len(parts) - 2, 0, -1):
                possible_name = '-'.join(parts[:i])
                if possible_name == pkg_name or possible_name.startswith(pkg_name + '-'):
                    # Remaining parts: version-release-architecture
                    if len(parts) >= i + 3:
                        version_part = parts[i]
                        release_part = parts[i+1]
                        
                        # Check for epoch (e.g., "2-26.1.9-1" -> "2:26.1.9-1")
                        if i + 2 < len(parts) and parts[i].isdigit():
                            epoch_part = parts[i]
                            version_part = parts[i+1]
                            release_part = parts[i+2]
                            return f"{epoch_part}:{version_part}-{release_part}"
                        else:
                            return f"{version_part}-{release_part}"
        except Exception as e:
            self.logger.debug(f"Could not extract version from {filename}: {e}")
        
        return None
    
    def _find_latest_version(self, versions: List[str]) -> str:
        """
        Find the latest version from a list using vercmp
        
        Args:
            versions: List of version strings
        
        Returns:
            The latest version string
        """
        if not versions:
            return ""
        
        if len(versions) == 1:
            return versions[0]
        
        # Try to use vercmp for accurate comparison
        try:
            latest = versions[0]
            for i in range(1, len(versions)):
                result = subprocess.run(
                    ['vercmp', versions[i], latest],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0:
                    cmp_result = int(result.stdout.strip())
                    if cmp_result > 0:
                        latest = versions[i]
            
            return latest
        except Exception as e:
            # Fallback: use string comparison (less accurate but works for simple cases)
            self.logger.warning(f"vercmp failed, using fallback version comparison: {e}")
            return max(versions)
    
    def cleanup_temp_directories(self):
        """Clean up temporary directories"""
        temp_dirs = [
            Path(self.config.get('mirror_temp_dir', '/tmp/repo_mirror')),
            Path(self.config.get('sync_clone_dir', '/tmp/manjaro-awesome-gitclone')),
        ]
        
        for temp_dir in temp_dirs:
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    self.logger.debug(f"Cleaned up temporary directory: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"Could not clean up {temp_dir}: {e}")