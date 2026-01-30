"""
Cleanup Manager Module - Handles Zero-Residue policy and package cleanup
"""

import os
import subprocess
import shutil
import re
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict

logger = logging.getLogger(__name__)


class CleanupManager:
    """Manages package cleanup and Zero-Residue policy implementation"""
    
    def __init__(self, config: dict):
        """
        Initialize CleanupManager with configuration
        
        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory (SOURCE OF TRUTH)
                - remote_dir: Remote directory on VPS
                - mirror_temp_dir: Temporary mirror directory
                - vps_user: VPS username
                - vps_host: VPS hostname
        """
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.mirror_temp_dir = Path(config.get('mirror_temp_dir', '/tmp/repo_mirror'))
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
    
    def pre_build_purge_old_versions(self, pkg_name: str, old_version: str, target_version: Optional[str] = None):
        """
        🚨 ZERO-RESIDUE POLICY: Surgical old version removal BEFORE building
        
        Removes old versions from local output directory before new build.
        
        Args:
            pkg_name: Package name
            old_version: Version to potentially delete
            target_version: Version we want to keep (None if building new)
        """
        # If we have a registered target version, use it
        # Note: This method needs access to version_tracker, will be called from PackageBuilder
        # with version_tracker passed as parameter
        pass
    
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
                        logger.info(f"🗑️ Surgically removed local {old_file.name}")
                        deleted_count += 1
                        
                        # Also remove signature
                        sig_file = old_file.with_suffix(old_file.suffix + '.sig')
                        if sig_file.exists():
                            sig_file.unlink()
                            logger.info(f"🗑️ Removed local signature {sig_file.name}")
                except Exception as e:
                    logger.warning(f"Could not delete local {old_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ Removed {deleted_count} local files for {pkg_name} version {version_to_delete}")
    
    def revalidate_output_dir_before_database(self):
        """
        🔥 ZOMBIE PROTECTION: Final validation before database generation
        
        Enhanced to recognize skipped packages as legitimate (not zombies)
        
        Scans output_dir and ensures:
        1. Only one version per package exists
        2. If multiple versions exist, keep only the target version
        3. Delete any "zombie" files (old versions that shouldn't be there)
        
        This is the LAST CHANCE to clean up before repo-add runs.
        """
        print("\n" + "=" * 60)
        print("🚨 FINAL VALIDATION: Removing zombie packages from output_dir")
        print("=" * 60)
        
        # Get all package files in output_dir
        package_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not package_files:
            logger.info("ℹ️ No package files in output_dir to validate")
            return
        
        logger.info(f"🔍 Validating {len(package_files)} package files in output_dir...")
        
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
                logger.warning(f"⚠️ Multiple versions found for {pkg_name}: {[v[0] for v in files]}")
                
                # Check if we have a registered target version
                # Note: This method needs access to version_tracker, will be called from PackageBuilder
                # with version_tracker passed as parameter
                target_version = None  # Will be set by caller
        
        if total_deleted > 0:
            logger.info(f"🎯 Final validation: Removed {total_deleted} zombie package files")
        else:
            logger.info("✅ Output_dir validation passed - no zombie packages found")
    
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
            logger.debug(f"Could not parse filename {filename}: {e}")
        
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
            logger.debug(f"Could not extract version from {filename}: {e}")
        
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
            logger.warning(f"vercmp failed, using fallback version comparison: {e}")
            return max(versions)
    
    def server_cleanup(self, version_tracker):
        """
        🚨 ZERO-RESIDUE SERVER CLEANUP: Remove zombie packages from VPS 
        using TARGET VERSIONS as SOURCE OF TRUTH.
        
        Only keeps packages that match registered target versions.
        """
        print("\n" + "=" * 60)
        print("🔒 ZERO-RESIDUE SERVER CLEANUP: Target Versions are Source of Truth")
        print("=" * 60)
        
        # VALVE: Check if we have any target versions registered
        if not version_tracker._package_target_versions:
            logger.warning("⚠️ No target versions registered - skipping server cleanup")
            return
        
        logger.info(f"🔄 Zero-Residue cleanup initiated with {len(version_tracker._package_target_versions)} target versions")
        
        # STEP 1: Get ALL files from VPS
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("❌ Failed to get VPS file inventory")
            return
        
        if not vps_files:
            logger.info("ℹ️ No files found on VPS - nothing to clean up")
            return
        
        # STEP 2: Identify files to keep based on target versions
        files_to_keep = set()
        files_to_delete = []
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            
            # Skip database and signature files from deletion logic
            is_db_or_sig = any(filename.endswith(ext) for ext in ['.db', '.db.tar.gz', '.sig', '.files', '.files.tar.gz'])
            if is_db_or_sig:
                files_to_keep.add(filename)
                continue
            
            # Parse package filename
            parsed = self._parse_package_filename(filename)
            if not parsed:
                # Can't parse, keep it to be safe
                files_to_keep.add(filename)
                continue
            
            pkg_name, version_str = parsed
            
            # Check if this package has a target version
            if pkg_name in version_tracker._package_target_versions:
                target_version = version_tracker._package_target_versions[pkg_name]
                if version_str == target_version:
                    # This is the version we want to keep
                    files_to_keep.add(filename)
                    logger.debug(f"✅ Keeping {filename} (matches target version {target_version})")
                else:
                    # This is an old version - mark for deletion
                    files_to_delete.append(vps_file)
                    logger.info(f"🗑️ Marking for deletion: {filename} (target is {target_version})")
            else:
                # No target version registered for this package
                # Check if it's in our skipped packages
                if pkg_name in version_tracker._skipped_packages:
                    skipped_version = version_tracker._skipped_packages[pkg_name]
                    if version_str == skipped_version:
                        files_to_keep.add(filename)
                        logger.debug(f"✅ Keeping {filename} (matches skipped version {skipped_version})")
                    else:
                        files_to_delete.append(vps_file)
                        logger.info(f"🗑️ Marking for deletion: {filename} (not in target versions)")
                else:
                    # Not in target versions or skipped packages - keep to be safe
                    files_to_keep.add(filename)
                    logger.warning(f"⚠️ Keeping unknown package: {filename} (not in target versions)")
        
        # STEP 3: Execute deletion
        if not files_to_delete:
            logger.info("✅ No zombie packages found on VPS")
            return
        
        logger.warning(f"🚨 Identified {len(files_to_delete)} zombie packages for deletion")
        
        # Delete files in batches to avoid command line length limits
        batch_size = 50
        deleted_count = 0
        
        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i:i + batch_size]
            if self._delete_files_remote(batch):
                deleted_count += len(batch)
        
        logger.info(f"📊 Server cleanup complete: Deleted {deleted_count} zombie packages, kept {len(files_to_keep)} files")
    
    def _get_vps_file_inventory(self) -> Optional[List[str]]:
        """Get complete inventory of all files on VPS"""
        logger.info("📋 Getting complete VPS file inventory...")
        remote_cmd = rf"""
        # Get all package files, signatures, and database files
        find "{self.remote_dir}" -maxdepth 1 -type f \( -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" -o -name "*.sig" -o -name "*.db" -o -name "*.db.tar.gz" -o -name "*.files" -o -name "*.files.tar.gz" -o -name "*.abs.tar.gz" \) 2>/dev/null
        """
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.warning(f"Could not list VPS files: {result.stderr[:200]}")
                return None
            
            vps_files_raw = result.stdout.strip()
            if not vps_files_raw:
                logger.info("No files found on VPS - nothing to clean up")
                return []
            
            vps_files = [f.strip() for f in vps_files_raw.split('\n') if f.strip()]
            logger.info(f"Found {len(vps_files)} files on VPS")
            return vps_files
            
        except subprocess.TimeoutExpired:
            logger.error("❌ SSH timeout getting VPS file inventory")
            return None
        except Exception as e:
            logger.error(f"❌ Error getting VPS file inventory: {e}")
            return None
    
    def _delete_files_remote(self, files_to_delete: List[str]) -> bool:
        """Delete files from remote server"""
        if not files_to_delete:
            return True
        
        # Quote each filename for safety
        quoted_files = [f"'{f}'" for f in files_to_delete]
        files_to_delete_str = ' '.join(quoted_files)
        
        delete_cmd = f"rm -fv {files_to_delete_str}"
        
        logger.info(f"🚀 Executing deletion command for {len(files_to_delete)} files")
        
        # Execute the deletion command
        ssh_delete = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            delete_cmd
        ]
        
        try:
            result = subprocess.run(
                ssh_delete,
                capture_output=True,
                text=True,
                check=False,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"✅ Deletion successful for batch of {len(files_to_delete)} files")
                if result.stdout:
                    for line in result.stdout.splitlines():
                        if "removed" in line.lower():
                            logger.info(f"   {line}")
                return True
            else:
                logger.error(f"❌ Deletion failed: {result.stderr[:500]}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("❌ SSH command timed out - aborting cleanup for safety")
            return False
        except Exception as e:
            logger.error(f"❌ Error during deletion: {e}")
            return False