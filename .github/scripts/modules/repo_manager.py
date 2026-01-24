"""
Repository Management Module - Handles database operations with remote state verification
"""

import os
import json
import subprocess
import shutil
import re
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class RepoManager:
    """Manages repository database operations with remote state verification"""
    
    def __init__(self, config: dict):
        """
        Initialize RepoManager with configuration
        
        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory
                - remote_dir: Remote directory on VPS
                - vps_user: VPS username
                - vps_host: VPS hostname
                - repo_root: Repository root directory
        """
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        self.repo_root = Path(config['repo_root'])
        
        # Build tracking directory - use existing .build_tracking folder in repo root
        self.build_tracking_dir = self.repo_root / ".build_tracking"
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # VPS state file
        self.vps_state_file = self.build_tracking_dir / "vps_state.json"
        self.vps_state = self._load_vps_state()
        
        # Initialize vps_client for remote operations
        self.vps_client = None
        
        # State tracking
        self.remote_files = []
        self._upload_successful = False
        self._state_changed = False
        
        # ZERO-RESIDUE POLICY: Explicit version tracking
        self._skipped_packages: Dict[str, str] = {}
        self._package_target_versions: Dict[str, str] = {}
        self._built_packages: Dict[str, str] = {}
    
    def set_vps_client(self, vps_client):
        """Set VPS client for remote operations"""
        self.vps_client = vps_client
    
    def _load_vps_state(self) -> Dict[str, Any]:
        """Load VPS state from JSON file"""
        if self.vps_state_file.exists():
            try:
                with open(self.vps_state_file, 'r') as f:
                    state = json.load(f)
                logger.info(f"✅ Loaded VPS state from {self.vps_state_file} ({len(state)} packages)")
                return state
            except Exception as e:
                logger.error(f"Failed to load VPS state: {e}")
                return {}
        else:
            logger.info("ℹ️ No VPS state file found, starting fresh")
            return {}
    
    def _save_vps_state(self):
        """Save VPS state to JSON file"""
        try:
            with open(self.vps_state_file, 'w') as f:
                json.dump(self.vps_state, f, indent=2)
            self._state_changed = True
            logger.debug(f"✅ Saved VPS state to {self.vps_state_file}")
        except Exception as e:
            logger.error(f"Failed to save VPS state: {e}")
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
    
    def get_state_changed(self) -> bool:
        """Check if VPS state has changed"""
        return self._state_changed
    
    def reset_state_changed(self):
        """Reset the state changed flag"""
        self._state_changed = False
    
    def register_package_target_version(self, pkg_name: str, target_version: str):
        """
        Register the target version for a package.
        
        Args:
            pkg_name: Package name
            target_version: The version we want to keep
        """
        self._package_target_versions[pkg_name] = target_version
        logger.info(f"📝 Registered target version for {pkg_name}: {target_version}")
    
    def register_skipped_package(self, pkg_name: str, remote_version: str):
        """
        Register a package that was skipped because it's up-to-date.
        
        Args:
            pkg_name: Package name
            remote_version: The remote version that should be kept
        """
        self._skipped_packages[pkg_name] = remote_version
        self._package_target_versions[pkg_name] = remote_version
        logger.info(f"📝 Registered SKIPPED package: {pkg_name} (remote: {remote_version})")
    
    def is_package_up_to_date(self, pkg_name: str, local_version: str, 
                            pkgver: str, pkgrel: str, epoch: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Check if a package is up-to-date using remote state verification.
        
        Args:
            pkg_name: Package name
            local_version: Local version string
            pkgver: Package version
            pkgrel: Package release
            epoch: Epoch (optional)
        
        Returns:
            Tuple of (is_up_to_date, remote_version)
        """
        # Get full version string
        full_version = self._get_full_version_string(pkgver, pkgrel, epoch)
        
        logger.info(f"🔍 Checking package: {pkg_name} (local: {full_version})")
        
        # Check VPS state for this package
        if pkg_name in self.vps_state:
            state_entry = self.vps_state[pkg_name]
            stored_version = state_entry.get('version')
            stored_hash = state_entry.get('hash')
            stored_filename = state_entry.get('filename')
            
            logger.info(f"  Found in VPS state: version={stored_version}, hash={stored_hash[:8] if stored_hash else 'N/A'}")
            
            # Check if versions match
            if stored_version == full_version:
                # Versions match, verify remote integrity
                if stored_filename:
                    remote_path = f"{self.remote_dir}/{stored_filename}"
                    
                    # Check if file exists on VPS
                    if self.vps_client and self.vps_client.check_remote_file_exists(remote_path):
                        # Get remote hash
                        remote_hash = self.vps_client.get_remote_file_hash(remote_path)
                        
                        if remote_hash and remote_hash == stored_hash:
                            logger.info(f"✅ {pkg_name} is up-to-date (version {full_version}, hash matches)")
                            return True, stored_version
                        else:
                            logger.warning(f"⚠️ {pkg_name} version matches but hash mismatch")
                            logger.info(f"   Stored hash: {stored_hash[:8] if stored_hash else 'N/A'}")
                            logger.info(f"   Remote hash: {remote_hash[:8] if remote_hash else 'N/A'}")
                            return False, stored_version
                    else:
                        logger.warning(f"⚠️ {pkg_name} version in state but file missing on VPS")
                        return False, stored_version
                else:
                    logger.warning(f"⚠️ {pkg_name} in state but no filename recorded")
                    return False, stored_version
            else:
                # Versions don't match
                logger.info(f"  Version mismatch: local={full_version}, remote={stored_version}")
                
                # Check if we should adopt the remote version (if it's newer)
                if self._should_adopt_remote_version(pkg_name, full_version, stored_version):
                    logger.info(f"  Adopting remote version {stored_version} for {pkg_name}")
                    # Update local state to match remote
                    self.register_skipped_package(pkg_name, stored_version)
                    return True, stored_version
                else:
                    return False, stored_version
        else:
            # Package not in VPS state - cold start / migration
            logger.info(f"  Package {pkg_name} not in VPS state")
            
            # Check if package exists on VPS
            remote_filename = self._find_remote_package(pkg_name)
            if remote_filename:
                logger.info(f"  Found on VPS: {remote_filename}")
                
                # Extract version from filename
                remote_version = self._extract_version_from_filename(remote_filename, pkg_name)
                if remote_version:
                    # Get remote hash and adopt into state
                    remote_path = f"{self.remote_dir}/{remote_filename}"
                    remote_hash = self.vps_client.get_remote_file_hash(remote_path) if self.vps_client else None
                    
                    # Adopt the package into state
                    self._adopt_package_to_state(pkg_name, remote_version, remote_hash, remote_filename)
                    
                    # Check if we should adopt this version
                    if self._should_adopt_remote_version(pkg_name, full_version, remote_version):
                        logger.info(f"  Adopting existing remote version {remote_version}")
                        self.register_skipped_package(pkg_name, remote_version)
                        return True, remote_version
                    else:
                        logger.info(f"  Remote version {remote_version} is older, need to build")
                        return False, remote_version
                else:
                    logger.warning(f"  Could not extract version from {remote_filename}")
                    return False, None
            else:
                logger.info(f"  Package {pkg_name} not found on VPS - needs build")
                return False, None
    
    def _should_adopt_remote_version(self, pkg_name: str, local_version: str, remote_version: str) -> bool:
        """
        Check if we should adopt the remote version (if it's newer or same)
        
        Returns:
            True if remote version is newer or same as local
        """
        if not remote_version:
            return False
        
        try:
            # Use vercmp for proper version comparison
            result = subprocess.run(['vercmp', remote_version, local_version], 
                                  capture_output=True, text=True, check=False)
            if result.returncode == 0:
                cmp_result = int(result.stdout.strip())
                if cmp_result >= 0:  # Remote is newer or same
                    return True
                else:
                    return False
        except Exception as e:
            logger.warning(f"vercmp failed for {pkg_name}: {e}, using fallback")
        
        # Fallback: simple string comparison
        return remote_version >= local_version
    
    def _adopt_package_to_state(self, pkg_name: str, version: str, 
                              file_hash: Optional[str], filename: str):
        """
        Adopt a package from VPS into the state tracking
        """
        self.vps_state[pkg_name] = {
            'version': version,
            'hash': file_hash,
            'filename': filename,
            'adopted_at': datetime.now().isoformat(),
            'last_verified': datetime.now().isoformat()
        }
        self._save_vps_state()
        logger.info(f"✅ Adopted {pkg_name} {version} into VPS state")
    
    def update_package_state(self, pkg_name: str, version: str, 
                           local_filename: str, built_files: List[Path]):
        """
        Update VPS state after building a package
        
        Args:
            pkg_name: Package name
            version: Package version
            local_filename: Primary package filename
            built_files: List of built package files
        """
        # Calculate hash of the built package
        if built_files and built_files[0].exists():
            try:
                import hashlib
                with open(built_files[0], 'rb') as f:
                    file_hash = hashlib.sha256(f.read()).hexdigest()
                
                self.vps_state[pkg_name] = {
                    'version': version,
                    'hash': file_hash,
                    'filename': local_filename,
                    'built_at': datetime.now().isoformat(),
                    'last_verified': datetime.now().isoformat(),
                    'files': [f.name for f in built_files]
                }
                self._save_vps_state()
                logger.info(f"📝 Updated VPS state for {pkg_name} {version} (hash: {file_hash[:8]}...)")
            except Exception as e:
                logger.error(f"Failed to calculate hash for {pkg_name}: {e}")
                # Still save state without hash
                self.vps_state[pkg_name] = {
                    'version': version,
                    'filename': local_filename,
                    'built_at': datetime.now().isoformat(),
                    'last_verified': datetime.now().isoformat()
                }
                self._save_vps_state()
    
    def _find_remote_package(self, pkg_name: str) -> Optional[str]:
        """Find a package file on VPS by name"""
        # Try to find the package using SSH
        remote_cmd = f"find {self.remote_dir} -maxdepth 1 -type f -name '{pkg_name}-*.pkg.tar.*' 2>/dev/null | head -1"
        
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
            
            if result.returncode == 0 and result.stdout.strip():
                remote_path = result.stdout.strip()
                return Path(remote_path).name
        except Exception as e:
            logger.debug(f"Could not find remote package {pkg_name}: {e}")
        
        return None
    
    def _extract_version_from_filename(self, filename: str, pkg_name: str) -> Optional[str]:
        """Extract version from package filename"""
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
                        
                        # Check for epoch
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
    
    def _get_full_version_string(self, pkgver: str, pkgrel: str, epoch: Optional[str]) -> str:
        """Construct full version string from components"""
        if epoch and epoch != '0':
            return f"{epoch}:{pkgver}-{pkgrel}"
        return f"{pkgver}-{pkgrel}"
    
    def pre_build_purge_old_versions(self, pkg_name: str, old_version: str):
        """
        Remove old versions from local output directory before new build
        """
        patterns = self._version_to_patterns(pkg_name, old_version)
        deleted_count = 0
        
        for pattern in patterns:
            for old_file in self.output_dir.glob(pattern):
                try:
                    old_file.unlink()
                    logger.info(f"🗑️ Surgically removed local {old_file.name}")
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete local {old_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ Removed {deleted_count} local files for {pkg_name} version {old_version}")
    
    def _version_to_patterns(self, pkg_name: str, version: str) -> List[str]:
        """Convert version string to filename patterns"""
        patterns = []
        
        if ':' in version:
            epoch, rest = version.split(':', 1)
            patterns.append(f"{pkg_name}-{epoch}-{rest}-*.pkg.tar.*")
        else:
            patterns.append(f"{pkg_name}-{version}-*.pkg.tar.*")
        
        return patterns
    
    def revalidate_output_dir_before_database(self):
        """
        Final validation before database generation
        """
        print("\n" + "=" * 60)
        print("🚨 FINAL VALIDATION: Removing zombie packages from output_dir")
        print("=" * 60)
        
        package_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not package_files:
            logger.info("ℹ️ No package files in output_dir to validate")
            return
        
        logger.info(f"🔍 Validating {len(package_files)} package files in output_dir...")
        
        # Group files by package name
        packages_dict: Dict[str, List[Tuple[str, Path]]] = {}
        
        for pkg_file in package_files:
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
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            if len(parts) >= 4:
                for i in range(len(parts) - 3, 0, -1):
                    potential_name = '-'.join(parts[:i])
                    remaining = parts[i:]
                    
                    if len(remaining) >= 3:
                        if remaining[0].isdigit() and '-' in '-'.join(remaining[1:]):
                            epoch = remaining[0]
                            version_part = remaining[1]
                            release_part = remaining[2]
                            version_str = f"{epoch}:{version_part}-{release_part}"
                            return potential_name, version_str
                        elif any(c.isdigit() for c in remaining[0]) and remaining[1].isdigit():
                            version_part = remaining[0]
                            release_part = remaining[1]
                            version_str = f"{version_part}-{release_part}"
                            return potential_name, version_str
        except Exception as e:
            logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None
    
    def _find_latest_version(self, versions: List[str]) -> str:
        """Find the latest version from a list using vercmp"""
        if not versions:
            return ""
        
        if len(versions) == 1:
            return versions[0]
        
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
            logger.warning(f"vercmp failed: {e}")
            return max(versions)
    
    def server_cleanup(self):
        """Remove zombie packages from VPS using target versions"""
        if not self._package_target_versions:
            logger.warning("⚠️ No target versions registered - skipping server cleanup")
            return
        
        logger.info(f"🔄 Zero-Residue cleanup with {len(self._package_target_versions)} target versions")
        
        # Get all files from VPS
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("❌ Failed to get VPS file inventory")
            return
        
        if not vps_files:
            logger.info("ℹ️ No files found on VPS - nothing to clean up")
            return
        
        # Identify files to keep based on target versions
        files_to_keep = set()
        files_to_delete = []
        
        for vps_file in vps_files:
            filename = Path(vps_file).name
            
            # Skip database and signature files
            is_db_or_sig = any(filename.endswith(ext) for ext in ['.db', '.db.tar.gz', '.sig', '.files', '.files.tar.gz'])
            if is_db_or_sig:
                files_to_keep.add(filename)
                continue
            
            # Parse package filename
            parsed = self._parse_package_filename(filename)
            if not parsed:
                files_to_keep.add(filename)
                continue
            
            pkg_name, version_str = parsed
            
            # Check if this package has a target version
            if pkg_name in self._package_target_versions:
                target_version = self._package_target_versions[pkg_name]
                if version_str == target_version:
                    files_to_keep.add(filename)
                    logger.debug(f"✅ Keeping {filename} (matches target version {target_version})")
                else:
                    files_to_delete.append(vps_file)
                    logger.info(f"🗑️ Marking for deletion: {filename} (target is {target_version})")
            else:
                if pkg_name in self._skipped_packages:
                    skipped_version = self._skipped_packages[pkg_name]
                    if version_str == skipped_version:
                        files_to_keep.add(filename)
                    else:
                        files_to_delete.append(vps_file)
                else:
                    files_to_keep.add(filename)
                    logger.warning(f"⚠️ Keeping unknown package: {filename}")
        
        # Execute deletion
        if not files_to_delete:
            logger.info("✅ No zombie packages found on VPS")
            return
        
        logger.warning(f"🚨 Identified {len(files_to_delete)} zombie packages for deletion")
        
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
                return []
            
            return [f.strip() for f in vps_files_raw.split('\n') if f.strip()]
            
        except Exception as e:
            logger.error(f"❌ Error getting VPS file inventory: {e}")
            return None
    
    def _delete_files_remote(self, files_to_delete: List[str]) -> bool:
        """Delete files from remote server"""
        if not files_to_delete:
            return True
        
        quoted_files = [f"'{f}'" for f in files_to_delete]
        files_to_delete_str = ' '.join(quoted_files)
        
        delete_cmd = f"rm -fv {files_to_delete_str}"
        
        logger.info(f"🚀 Executing deletion command for {len(files_to_delete)} files")
        
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
                return True
            else:
                logger.error(f"❌ Deletion failed: {result.stderr[:500]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error during deletion: {e}")
            return False
    
    def generate_full_database(self) -> bool:
        """Generate repository database from ALL locally available packages"""
        print("\n" + "=" * 60)
        print("PHASE: Repository Database Generation")
        print("=" * 60)
        
        # Final validation to remove zombie packages
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
            
            # Verify each package file exists locally
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
                return False
            
            logger.info(f"✅ All {len(valid_packages)} package files verified locally")
            
            # Generate database with repo-add
            cmd = f"repo-add {db_file} *.pkg.tar.zst"
            
            logger.info(f"Running repo-add...")
            
            result = subprocess.run(
                cmd,
                shell=True,
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
                    
                    # Verify database entries
                    logger.info("🔍 Verifying database entries...")
                    list_cmd = ["tar", "-tzf", db_file]
                    list_result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
                    if list_result.returncode == 0:
                        db_entries = [line for line in list_result.stdout.split('\n') if line.endswith('/desc')]
                        logger.info(f"✅ Database contains {len(db_entries)} package entries")
                        if len(db_entries) == 0:
                            logger.error("❌ DATABASE IS EMPTY!")
                            return False
                    
                return True
            else:
                logger.error(f"repo-add failed: {result.stderr[:500]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def _get_all_local_packages(self) -> List[str]:
        """Get ALL package files from local output directory"""
        local_files = list(self.output_dir.glob("*.pkg.tar.*"))
        return [f.name for f in local_files] if local_files else []
    
    def check_database_files(self) -> Tuple[List[str], List[str]]:
        """Check if repository database files exist on server"""
        print("\n" + "=" * 60)
        print("STEP: Checking existing database files on server")
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
    
    def commit_vps_state_to_git(self):
        """Commit and push VPS state changes to git repository"""
        if not self._state_changed:
            logger.info("ℹ️ No changes to VPS state, skipping git commit")
            return
        
        try:
            # Save current directory
            original_cwd = os.getcwd()
            
            # Change to repository root where git is available
            os.chdir(self.repo_root)
            
            # Check if we're in a git repository
            check_git = subprocess.run(["git", "rev-parse", "--git-dir"], 
                                     capture_output=True, text=True, check=False)
            
            if check_git.returncode != 0:
                logger.warning("⚠️ Not in a git repository, skipping git commit")
                return
            
            # Add VPS state file to git
            vps_state_relative = self.vps_state_file.relative_to(self.repo_root)
            add_cmd = ["git", "add", str(vps_state_relative)]
            result = subprocess.run(add_cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                logger.error(f"Failed to add VPS state to git: {result.stderr}")
                return
            
            # Commit changes
            commit_msg = f"Update VPS package state - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            commit_cmd = ["git", "commit", "-m", commit_msg]
            result = subprocess.run(commit_cmd, capture_output=True, text=True, check=False)
            
            if result.returncode != 0:
                # Check if there were actually changes to commit
                if "nothing to commit" in result.stderr or "no changes added to commit" in result.stderr:
                    logger.info("ℹ️ No changes to commit in VPS state")
                else:
                    logger.warning(f"Git commit warning: {result.stderr[:200]}")
                return
            
            # Push changes (using GitHub token from environment)
            github_token = os.getenv('GITHUB_TOKEN')
            github_repo = os.getenv('GITHUB_REPOSITORY')
            
            if github_token and github_repo:
                # Configure git with token
                repo_url = f"https://x-access-token:{github_token}@github.com/{github_repo}.git"
                push_cmd = ["git", "push", repo_url, "HEAD"]
                result = subprocess.run(push_cmd, capture_output=True, text=True, check=False)
                
                if result.returncode == 0:
                    logger.info("✅ Pushed VPS state changes to repository")
                else:
                    logger.error(f"Failed to push VPS state: {result.stderr[:500]}")
            else:
                logger.warning("⚠️ GITHUB_TOKEN or GITHUB_REPOSITORY not available, cannot push VPS state")
                
        except Exception as e:
            logger.error(f"Error committing VPS state to git: {e}")
        finally:
            # Restore original directory
            os.chdir(original_cwd)