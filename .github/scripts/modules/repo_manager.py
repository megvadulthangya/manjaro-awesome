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
        
        # 🚨 ZERO-RESIDUE POLICY: Explicit version tracking
        self._skipped_packages: Dict[str, str] = {}  # {pkg_name: remote_version} - packages skipped as up-to-date
        self._package_target_versions: Dict[str, str] = {}  # {pkg_name: target_version} - versions we want to keep
        self._built_packages: Dict[str, str] = {}  # {pkg_name: built_version} - packages we just built
    
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
        logger.info(f"📝 Registered target version for {pkg_name}: {target_version}")
    
    def register_skipped_package(self, pkg_name: str, remote_version: str):
        """
        Register a package that was skipped because it's up-to-date.
        
        Args:
            pkg_name: Package name
            remote_version: The remote version that should be kept (not deleted)
        """
        # Store in skipped registry
        self._skipped_packages[pkg_name] = remote_version
        
        # 🚨 CRITICAL: Explicitly set target version to remote version
        self._package_target_versions[pkg_name] = remote_version
        
        logger.info(f"📝 Registered SKIPPED package: {pkg_name} (remote: {remote_version}, target: {remote_version})")
    
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
        if pkg_name in self._package_target_versions:
            target_version = self._package_target_versions[pkg_name]
        
        if target_version and old_version == target_version:
            # This is the version we want to keep
            logger.info(f"✅ No pre-build purge needed: {pkg_name} version {old_version} is target version")
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
                    logger.warning(f"⚠️ No target version registered for {pkg_name}, using version comparison")
                    latest_version = self._find_latest_version([v[0] for v in files])
                    for version_str, file_path in files:
                        if version_str == latest_version:
                            logger.info(f"✅ Keeping latest version: {file_path.name} ({version_str})")
                        else:
                            try:
                                file_path.unlink()
                                logger.info(f"🗑️ Removing older version: {file_path.name}")
                                total_deleted += 1
                            except Exception as e:
                                logger.warning(f"Could not delete {file_path}: {e}")
        
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
    
    def server_cleanup(self):
        """
        🚨 ZERO-RESIDUE SERVER CLEANUP: Remove zombie packages from VPS 
        using TARGET VERSIONS as SOURCE OF TRUTH.
        
        Only keeps packages that match registered target versions.
        """
        print("\n" + "=" * 60)
        print("🔒 ZERO-RESIDUE SERVER CLEANUP: Target Versions are Source of Truth")
        print("=" * 60)
        
        # VALVE: Check if we have any target versions registered
        if not self._package_target_versions:
            logger.warning("⚠️ No target versions registered - skipping server cleanup")
            return
        
        logger.info(f"🔄 Zero-Residue cleanup initiated with {len(self._package_target_versions)} target versions")
        
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
            if pkg_name in self._package_target_versions:
                target_version = self._package_target_versions[pkg_name]
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
                if pkg_name in self._skipped_packages:
                    skipped_version = self._skipped_packages[pkg_name]
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