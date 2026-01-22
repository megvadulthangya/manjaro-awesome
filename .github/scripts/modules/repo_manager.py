"""
Repository Management Module - Handles database operations, cleanup, and Zero-Residue policy
"""

import os
import subprocess
import shutil
import re
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict

logger = logging.getLogger(__name__)


class RepoManager:
    """Manages repository database operations, cleanup, and Zero-Residue policy"""
    
    def __init__(self, config: dict):
        """
        Initialize RepoManager with configuration
        
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
        
        # State tracking
        self.remote_files = []
        self._upload_successful = False
        
        # 🚨 KRITIKUS: Store target versions for each package
        self._package_target_versions: Dict[str, str] = {}
        self._skipped_packages: Dict[str, str] = {}  # Track skipped packages with their remote versions
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
    
    def register_package_target_version(self, pkg_name: str, target_version: str):
        """
        Register the target version for a package.
        
        Args:
            pkg_name: Package name
            target_version: The version we want to keep (either built or latest from server)
        """
        self._package_target_versions[pkg_name] = target_version
        logger.debug(f"📝 Registered target version for {pkg_name}: {target_version}")
    
    def register_skipped_package(self, pkg_name: str, remote_version: str):
        """
        Register a package that was skipped because it's up-to-date.
        
        Args:
            pkg_name: Package name
            remote_version: The remote version that should be kept (not deleted)
        """
        self._skipped_packages[pkg_name] = remote_version
        # Set the target version to the remote version to prevent deletion
        self._package_target_versions[pkg_name] = remote_version
        logger.info(f"📝 Registered SKIPPED package: {pkg_name} (remote: {remote_version})")
    
    def intelligent_mirror_filtering(self, remote_filenames: List[str]) -> List[str]:
        """
        🔥 KRITIKUS JAVÍTÁS: Intelligently filter mirrored files
        
        When mirroring from VPS, we should:
        1. Identify which packages we care about (from packages.py)
        2. For each package, only keep the LATEST version found on VPS
        3. Discard old versions immediately to prevent "zombie packages"
        
        Args:
            remote_filenames: List of filenames found on VPS
        
        Returns:
            List of filenames to actually mirror (filtered)
        """
        if not remote_filenames:
            return []
        
        logger.info("🔍 Performing intelligent mirror filtering...")
        
        # Parse all packages from remote filenames
        package_versions: Dict[str, List[Tuple[str, str]]] = {}
        
        for filename in remote_filenames:
            # Extract package name and version from filename
            match = re.match(r'^([a-zA-Z0-9_-]+)-([0-9][^-]*(?:-[0-9]+)?)-', filename)
            if match:
                pkg_name = match.group(1)
                version_part = match.group(2)
                
                # Handle epoch format (e.g., "2-26.1.9-1" -> "2:26.1.9-1")
                if '-' in version_part and version_part[0].isdigit() and version_part.split('-')[0].isdigit():
                    epoch, rest = version_part.split('-', 1)
                    version_str = f"{epoch}:{rest}"
                else:
                    version_str = version_part
                
                if pkg_name not in package_versions:
                    package_versions[pkg_name] = []
                
                package_versions[pkg_name].append((version_str, filename))
                logger.debug(f"Found {pkg_name} version {version_str} in remote: {filename}")
        
        # For each package, keep only the latest version
        files_to_mirror = []
        removed_count = 0
        
        for pkg_name, versions in package_versions.items():
            if len(versions) > 1:
                logger.info(f"⚠️ Multiple versions found for {pkg_name}: {[v[0] for v in versions]}")
                
                # Use vercmp to find the latest version
                latest_version = self._find_latest_version(versions)
                
                for version_str, filename in versions:
                    if version_str == latest_version:
                        files_to_mirror.append(filename)
                        logger.info(f"✅ Keeping latest version: {filename} ({version_str})")
                    else:
                        logger.info(f"🗑️ Discarding old version: {filename} ({version_str})")
                        removed_count += 1
            else:
                # Single version, keep it
                files_to_mirror.append(versions[0][1])
        
        if removed_count > 0:
            logger.info(f"🎯 Intelligent filtering: Removed {removed_count} old versions, keeping {len(files_to_mirror)} files")
        
        return files_to_mirror
    
    def _find_latest_version(self, versions: List[Tuple[str, str]]) -> str:
        """
        Find the latest version from a list using vercmp
        
        Args:
            versions: List of (version_string, filename) tuples
        
        Returns:
            The latest version string
        """
        if not versions:
            return ""
        
        if len(versions) == 1:
            return versions[0][0]
        
        # Try to use vercmp for accurate comparison
        try:
            version_strings = [v[0] for v in versions]
            
            # Build vercmp comparison commands
            latest = version_strings[0]
            for i in range(1, len(version_strings)):
                result = subprocess.run(
                    ['vercmp', version_strings[i], latest],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if result.returncode == 0:
                    cmp_result = int(result.stdout.strip())
                    if cmp_result > 0:
                        latest = version_strings[i]
            
            return latest
        except Exception as e:
            # Fallback: use string comparison (less accurate but works for simple cases)
            logger.warning(f"vercmp failed, using fallback version comparison: {e}")
            return max(version_strings)
    
    def pre_build_purge_old_versions(self, pkg_name: str, old_version: str, target_version: Optional[str] = None):
        """
        🚨 KRITIKUS JAVÍTÁS: Surgical old version removal
        
        CRITICAL FIX: When build is SKIPPED, target_version must be REMOTE VERSION
        to prevent deletion of up-to-date packages.
        
        Args:
            pkg_name: Package name
            old_version: Version to potentially delete
            target_version: Version we want to keep (None if building new)
        """
        # 🚨 CRITICAL BUG FIX: Check if package was skipped
        if pkg_name in self._skipped_packages:
            # This package was skipped because it's up-to-date
            # Use the remote version as target to prevent deletion
            remote_version = self._skipped_packages[pkg_name]
            logger.info(f"🔪 Surgical purge: {pkg_name} (SKIPPED, old: {old_version}, remote: {remote_version})")
            
            if old_version != remote_version:
                # Old version doesn't match remote version - delete it
                self._delete_specific_version(pkg_name, old_version)
            else:
                # Old version matches remote version - KEEP IT
                logger.info(f"✅ KEEPING skipped package {pkg_name} (version {old_version})")
            return
        
        # Original logic for non-skipped packages
        logger.info(f"🔪 Surgical purge: {pkg_name} (old: {old_version}, target: {target_version or 'NEW_BUILD'})")
        
        if target_version and old_version != target_version:
            # We want to keep target_version, delete old_version
            self._delete_specific_version(pkg_name, old_version)
        elif not target_version:
            # We're building new version, delete old version
            self._delete_specific_version(pkg_name, old_version)
        else:
            # old_version == target_version, nothing to do
            logger.info(f"✅ No purge needed: old version ({old_version}) matches target")
    
    def _delete_specific_version(self, pkg_name: str, version_to_delete: str):
        """Delete a specific version of a package from output_dir"""
        patterns = self._version_to_patterns(pkg_name, version_to_delete)
        deleted_count = 0
        
        for pattern in patterns:
            for old_file in self.output_dir.glob(pattern):
                try:
                    # Verify this is actually the version we want to delete
                    extracted_version = self._extract_version_from_filename(old_file.name, pkg_name)
                    if extracted_version == version_to_delete:
                        old_file.unlink()
                        logger.info(f"🗑️ Surgically removed {old_file.name}")
                        deleted_count += 1
                        
                        # Also remove signature
                        sig_file = old_file.with_suffix(old_file.suffix + '.sig')
                        if sig_file.exists():
                            sig_file.unlink()
                            logger.info(f"🗑️ Removed signature {sig_file.name}")
                except Exception as e:
                    logger.warning(f"Could not delete {old_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ Removed {deleted_count} files for {pkg_name} version {version_to_delete}")
    
    def revalidate_output_dir_before_database(self):
        """
        🔥 KRITIKUS: Final validation before database generation
        
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
            # Extract package name from filename (simplified approach)
            # Format: name-version-release-arch.pkg.tar.zst
            parts = pkg_file.name.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '').split('-')
            
            # The package name is everything before the last 3 parts (version-release-arch)
            if len(parts) >= 4:
                # Try to find where package name ends
                for i in range(len(parts) - 3, 0, -1):
                    potential_name = '-'.join(parts[:i])
                    version_part = '-'.join(parts[i:i+2])  # version-release
                    
                    # Simple validation: version_part should contain numbers
                    if any(c.isdigit() for c in version_part):
                        if potential_name not in packages_dict:
                            packages_dict[potential_name] = []
                        
                        packages_dict[potential_name].append((version_part, pkg_file))
                        break
        
        # Process each package
        total_deleted = 0
        
        for pkg_name, files in packages_dict.items():
            if len(files) > 1:
                logger.warning(f"⚠️ Multiple versions found for {pkg_name}: {[v[0] for v in files]}")
                
                # Check if we have a registered target version
                target_version = self._package_target_versions.get(pkg_name)
                
                if target_version:
                    # Keep only the target version
                    kept = False
                    for version_str, file_path in files:
                        if version_str == target_version:
                            logger.info(f"✅ Keeping target version: {file_path.name} ({version_str})")
                            kept = True
                        else:
                            try:
                                file_path.unlink()
                                logger.info(f"🗑️ Removing non-target version: {file_path.name}")
                                total_deleted += 1
                            except Exception as e:
                                logger.warning(f"Could not delete {file_path}: {e}")
                    
                    if not kept:
                        logger.error(f"❌ Target version {target_version} for {pkg_name} not found in output_dir!")
                else:
                    # No target version registered, keep the latest
                    logger.warning(f"⚠️ No target version registered for {pkg_name}, keeping all versions")
        
        if total_deleted > 0:
            logger.info(f"🎯 Final validation: Removed {total_deleted} zombie package files")
        else:
            logger.info("✅ Output_dir validation passed - no zombie packages found")
    
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
    
    def server_cleanup(self):
        """
        ZERO-RESIDUE SERVER CLEANUP: Remove orphaned package files from VPS 
        using LOCAL OUTPUT DIRECTORY as SOURCE OF TRUTH.
        
        CRITICAL FIX: This runs even if GPG signing has minor warnings.
        Only requirement: upload must have been attempted.
        """
        print("\n" + "=" * 60)
        print("🔒 ZERO-RESIDUE SERVER CLEANUP: output_dir is Source of Truth")
        print("=" * 60)
        
        # VALVE 1: Check if cleanup should run at all (only if upload was attempted)
        if not hasattr(self, '_upload_successful'):
            logger.error("❌ SAFETY VALVE: Cleanup cannot run because upload was not attempted!")
            return
        
        logger.info("🔄 Zero-Residue cleanup initiated (upload was attempted)")
        
        # STEP 1: Get ALL valid files from local output directory (SOURCE OF TRUTH)
        valid_filenames = self._collect_valid_files()
        
        # VALVE 2: CRITICAL - Must have at least one valid file
        if len(valid_filenames) == 0:
            logger.error("❌❌❌ CRITICAL SAFETY VALVE ACTIVATED: No valid files in output directory!")
            logger.error("   🚨 CLEANUP ABORTED - Output directory empty, potential data loss!")
            return
        
        # STEP 2: Get COMPLETE inventory of all files on VPS
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            return
        
        # STEP 3: Identify orphaned files (files on VPS not in local output directory)
        orphaned_files = self._identify_orphaned_files(vps_files, valid_filenames)
        
        if not orphaned_files:
            logger.info("✅ No orphaned files found - VPS matches output_dir exactly")
            return
        
        # STEP 4: DEBUGGING - Log files to be deleted BEFORE running rm -f
        self._log_orphaned_files(orphaned_files)
        
        # STEP 5: ATOMIC EXECUTION - delete all orphaned files in single command
        self._atomic_deletion(orphaned_files)
        
        logger.info(f"📊 Zero-Residue cleanup complete: VPS now has exactly {len(valid_filenames)} valid files")
    
    def _collect_valid_files(self) -> Set[str]:
        """Collect all valid files from local output directory (SOURCE OF TRUTH)"""
        valid_filenames = set()
        logger.info("🔍 Collecting ALL valid files from output_dir (Source of Truth)...")
        
        # Get ALL package files from local output directory
        for pkg_file in self.output_dir.glob("*.pkg.tar.*"):
            if pkg_file.is_file() and pkg_file.stat().st_size > 0:
                valid_filenames.add(pkg_file.name)
                logger.debug(f"✅ Added package to valid files: {pkg_file.name}")
                
                # Also add signature file if it exists locally
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if sig_file.exists() and sig_file.stat().st_size > 0:
                    valid_filenames.add(sig_file.name)
                    logger.debug(f"✅ Added signature to valid files: {sig_file.name}")
        
        # Get ALL database files from local output directory
        db_patterns = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz",
            f"{self.repo_name}.abs.tar.gz",
            f"{self.repo_name}.db.sig",
            f"{self.repo_name}.db.tar.gz.sig",
            f"{self.repo_name}.files.sig",
            f"{self.repo_name}.files.tar.gz.sig",
        ]
        
        for pattern in db_patterns:
            db_file = self.output_dir / pattern
            if db_file.exists() and db_file.stat().st_size > 0:
                valid_filenames.add(db_file.name)
                logger.debug(f"✅ Added database file to valid files: {db_file.name}")
        
        # CRITICAL: Also add ALL .sig files for packages that have them
        for sig_file in self.output_dir.glob("*.sig"):
            if sig_file.is_file() and sig_file.stat().st_size > 0:
                valid_filenames.add(sig_file.name)
                logger.debug(f"✅ Added signature file to valid files: {sig_file.name}")
        
        logger.info(f"✅ Output directory (Source of Truth) has {len(valid_filenames)} valid files")
        
        # Log some sample valid filenames
        if valid_filenames:
            sample_filenames = list(valid_filenames)[:10]
            logger.info(f"Sample valid files: {sample_filenames}")
        
        return valid_filenames
    
    def _get_vps_file_inventory(self) -> Optional[List[str]]:
        """Get complete inventory of all files on VPS"""
        logger.info("📋 Getting complete VPS file inventory...")
        remote_cmd = f"""
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
    
    def _identify_orphaned_files(self, vps_files: List[str], valid_filenames: Set[str]) -> List[str]:
        """Identify orphaned files (files on VPS not in local output directory)"""
        orphaned_files = []
        protected_count = 0
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            
            # Skip repository metadata files that might not be in output directory
            protected_extensions = [
                '.db', '.db.tar.gz', '.db.sig',
                '.files', '.files.tar.gz', '.files.sig',
                '.abs.tar.gz'
            ]
            
            is_protected = any(filename.endswith(ext) for ext in protected_extensions)
            
            if is_protected:
                protected_count += 1
                logger.debug(f"🔒 Protected repository file: {filename}")
            elif filename not in valid_filenames:
                orphaned_files.append(vps_file)
                logger.info(f"🚨 Orphaned file identified: {filename}")
        
        logger.info(f"🔒 Protected {protected_count} repository metadata files from deletion")
        return orphaned_files
    
    def _log_orphaned_files(self, orphaned_files: List[str]):
        """Log orphaned files before deletion"""
        logger.warning(f"🚨 Identified {len(orphaned_files)} orphaned files for deletion")
        logger.warning("Files to be deleted:")
        for orphaned_file in orphaned_files:
            filename = Path(orphaned_file).name
            logger.warning(f"   🗑️  {filename}")
    
    def _atomic_deletion(self, orphaned_files: List[str]):
        """Execute atomic deletion of all orphaned files"""
        # Quote each filename for safety
        quoted_files = [f"'{f}'" for f in orphaned_files]
        files_to_delete = ' '.join(quoted_files)
        
        delete_cmd = f"rm -fv {files_to_delete}"
        
        logger.info(f"🚀 Executing ATOMIC deletion command:")
        logger.info(f"   SSH: {self.vps_user}@{self.vps_host}")
        logger.info(f"   COMMAND: {delete_cmd}")
        
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
                deleted_count = len(orphaned_files)
                logger.info(f"✅ ATOMIC deletion successful! Removed {deleted_count} files")
                if result.stdout:
                    for line in result.stdout.splitlines():
                        if line.strip():
                            logger.info(f"   {line}")
            else:
                logger.error(f"❌ Deletion failed: {result.stderr[:500]}")
                # Fallback: try deleting files one by one
                logger.info("⚠️ Falling back to individual file deletion...")
                self._delete_files_individually(orphaned_files)
                
        except subprocess.TimeoutExpired:
            logger.error("❌ SSH command timed out - aborting cleanup for safety")
        except Exception as e:
            logger.error(f"❌ Error during atomic deletion: {e}")
    
    def _delete_files_individually(self, orphaned_files: List[str]):
        """Fallback: Delete orphaned files one by one"""
        deleted_count = 0
        failed_count = 0
        
        for orphaned_file in orphaned_files:
            filename = Path(orphaned_file).name
            delete_cmd = f"rm -fv '{orphaned_file}'"
            
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
                    timeout=30
                )
                
                if result.returncode == 0:
                    logger.info(f"✅ Deleted: {filename}")
                    deleted_count += 1
                else:
                    logger.warning(f"⚠️ Failed to delete {filename}: {result.stderr[:200]}")
                    failed_count += 1
                    
            except Exception as e:
                logger.warning(f"⚠️ Error deleting {filename}: {e}")
                failed_count += 1
        
        logger.info(f"📊 Individual deletion: {deleted_count} deleted, {failed_count} failed")
    
    def generate_full_database(self) -> bool:
        """
        Generate repository database from ALL locally available packages
        
        🚨 KRITIKUS: Run final validation BEFORE repo-add
        """
        print("\n" + "=" * 60)
        print("PHASE: Repository Database Generation")
        print("=" * 60)
        
        # 🚨 KRITIKUS: Final validation to remove zombie packages
        self.revalidate_output_dir_before_database()
        
        # Get all package files from local output directory
        all_packages = self._get_all_local_packages()
        
        if not all_packages:
            logger.info("No packages available for database generation")
            return False
        
        logger.info(f"Generating database with {len(all_packages)} packages...")
        logger.info(f"Packages: {', '.join(all_packages[:10])}{'...' if len(all_packages) > 10 else ''}")
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz", 
                      f"{self.repo_name}.files", f"{self.repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            # Verify each package file exists locally before database generation
            missing_packages = []
            valid_packages = []
            
            for pkg_filename in all_packages:
                if Path(pkg_filename).exists():
                    valid_packages.append(pkg_filename)
                else:
                    missing_packages.append(pkg_filename)
            
            if missing_packages:
                logger.error(f"❌ CRITICAL: {len(missing_packages)} packages missing locally:")
                for pkg in missing_packages[:5]:
                    logger.error(f"   - {pkg}")
                if len(missing_packages) > 5:
                    logger.error(f"   ... and {len(missing_packages) - 5} more")
                return False
            
            if not valid_packages:
                logger.error("No valid package files found for database generation")
                return False
            
            logger.info(f"✅ All {len(valid_packages)} package files verified locally")
            
            # Generate database with repo-add using shell=True for wildcard expansion
            cmd = f"repo-add {db_file} *.pkg.tar.zst"
            
            logger.info(f"Running repo-add with shell=True to include ALL packages...")
            logger.info(f"Command: {cmd}")
            logger.info(f"Current directory: {os.getcwd()}")
            
            result = subprocess.run(
                cmd,
                shell=True,  # CRITICAL: Use shell=True for wildcard expansion
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0:
                logger.info("✅ Database created successfully")
                
                # Verify the database was created
                db_path = Path(db_file)
                if db_path.exists():
                    size_mb = db_path.stat().st_size / (1024 * 1024)
                    logger.info(f"Database size: {size_mb:.2f} MB")
                    
                    # CRITICAL: Verify database entries BEFORE upload
                    logger.info("🔍 Verifying database entries before upload...")
                    list_cmd = ["tar", "-tzf", db_file]
                    list_result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
                    if list_result.returncode == 0:
                        db_entries = [line for line in list_result.stdout.split('\n') if line.endswith('/desc')]
                        logger.info(f"✅ Database contains {len(db_entries)} package entries")
                        if len(db_entries) == 0:
                            logger.error("❌❌❌ DATABASE IS EMPTY! This is the root cause of the issue.")
                            return False
                        else:
                            logger.info(f"Sample database entries: {db_entries[:5]}")
                    else:
                        logger.warning(f"Could not list database contents: {list_result.stderr}")
                
                return True
            else:
                logger.error(f"repo-add failed with exit code {result.returncode}:")
                if result.stdout:
                    logger.error(f"STDOUT: {result.stdout[:500]}")
                if result.stderr:
                    logger.error(f"STDERR: {result.stderr[:500]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def _get_all_local_packages(self) -> List[str]:
        """Get ALL package files from local output directory (mirrored + newly built)"""
        print("\n🔍 Getting complete package list from local directory...")
        
        local_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not local_files:
            logger.info("ℹ️ No package files found locally")
            return []
        
        local_filenames = [f.name for f in local_files]
        
        logger.info(f"📊 Local package count: {len(local_filenames)}")
        logger.info(f"Sample packages: {local_filenames[:10]}")
        
        return local_filenames
    
    def check_database_files(self) -> Tuple[List[str], List[str]]:
        """Check if repository database files exist on server"""
        print("\n" + "=" * 60)
        print("STEP 2: Checking existing database files on server")
        print("=" * 60)
        
        db_files = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz"
        ]
        
        existing_files = []
        missing_files = []
        
        for db_file in db_files:
            remote_cmd = f"test -f {self.remote_dir}/{db_file} && echo 'EXISTS' || echo 'MISSING'"
            
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
                    check=False
                )
                
                if result.returncode == 0 and "EXISTS" in result.stdout:
                    existing_files.append(db_file)
                    logger.info(f"✅ Database file exists: {db_file}")
                else:
                    missing_files.append(db_file)
                    logger.info(f"ℹ️ Database file missing: {db_file}")
                    
            except Exception as e:
                logger.warning(f"Could not check {db_file}: {e}")
                missing_files.append(db_file)
        
        if existing_files:
            logger.info(f"Found {len(existing_files)} database files on server")
        else:
            logger.info("No database files found on server")
        
        return existing_files, missing_files
    
    def fetch_existing_database(self, existing_files: List[str]):
        """Fetch existing database files from server"""
        if not existing_files:
            return
        
        print("\n📥 Fetching existing database files from server...")
        
        for db_file in existing_files:
            remote_path = f"{self.remote_dir}/{db_file}"
            local_path = self.output_dir / db_file
            
            # Remove local copy if exists
            if local_path.exists():
                local_path.unlink()
            
            ssh_cmd = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=30",
                f"{self.vps_user}@{self.vps_host}:{remote_path}",
                str(local_path)
            ]
            
            try:
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0 and local_path.exists():
                    size_mb = local_path.stat().st_size / (1024 * 1024)
                    logger.info(f"✅ Fetched: {db_file} ({size_mb:.2f} MB)")
                else:
                    logger.warning(f"⚠️ Could not fetch {db_file}")
            except Exception as e:
                logger.warning(f"Could not fetch {db_file}: {e}")