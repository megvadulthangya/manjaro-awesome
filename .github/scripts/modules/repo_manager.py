"""
Repository Management Module - Handles database operations, cleanup, and Zero-Residue policy
"""

import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional

logger = logging.getLogger(__name__)


class RepoManager:
    """Manages repository database operations, cleanup, and Zero-Residue policy"""
    
    def __init__(self, config: dict):
        """
        Initialize RepoManager with configuration
        
        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory
                - remote_dir: Remote directory on VPS
                - mirror_temp_dir: Temporary mirror directory
                - vps_user: VPS username
                - vps_host: VPS hostname
        """
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.mirror_temp_dir = Path(config['mirror_temp_dir'])
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        
        # State tracking
        self.remote_files = []
        self._upload_successful = False
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
    
    def pre_build_purge_old_versions(self, pkg_name: str, old_version: str):
        """
        PRE-BUILD PURGE: Remove old version files from local mirror directory 
        BEFORE building new version.
        
        ✅ FIXED QOWNNOTES PROBLÉMA: Agresszív tisztítás minden helyi könyvtárból,
        még akkor is ha a build elmarad (skip).
        
        Ensures the local directory only contains the latest version before repo-add runs.
        """
        logger.info(f"🔍 PRE-BUILD PURGE FIX: Aggressive cleanup for {pkg_name} (old: {old_version})")
        
        # Convert old version to filename patterns
        old_patterns = []
        
        # Pattern 1: Standard version (no epoch)
        if ':' not in old_version:
            # Standard pattern: name-version-release-arch.pkg.tar.*
            old_patterns.append(f"*{pkg_name}-{old_version}-*.pkg.tar.*")
            # ✅ EXTRA FIX: Also match any version that starts with the same base (e.g., 26.1.9-1 vs 26.1.9-2)
            version_base = old_version.split('-')[0] if '-' in old_version else old_version
            old_patterns.append(f"*{pkg_name}-{version_base}-*.pkg.tar.*")
        else:
            # Pattern 2: Version with epoch (e.g., "2:26.1.9-1" -> "2-26.1.9-1")
            epoch, rest = old_version.split(':', 1)
            old_patterns.append(f"*{pkg_name}-{epoch}-{rest}-*.pkg.tar.*")
            # ✅ EXTRA FIX: Also match base version without epoch
            version_base = rest.split('-')[0] if '-' in rest else rest
            old_patterns.append(f"*{pkg_name}-{version_base}-*.pkg.tar.*")
        
        # ✅ KRITIKUS JAVÍTÁS: Agresszív törlés MINDEN csomagnév egyezésért
        # Töröljük az ÖSSZES régebbi verziót, nem csak a pontos egyezést
        old_patterns.append(f"{pkg_name}-*.pkg.tar.*")
        
        deleted_count = 0
        deleted_files = []
        
        # Check both output_dir and mirror_temp_dir
        for search_dir in [self.output_dir, self.mirror_temp_dir]:
            if not search_dir.exists():
                continue
                
            for pattern in old_patterns:
                for old_file in search_dir.glob(pattern):
                    try:
                        filename = old_file.name
                        
                        # ✅ KÜLÖNÖSEN FONTOS: Ellenőrizzük, hogy ez valóban a régi verzió-e
                        # Ha a fájlnévben pontosan az old_version van, töröljük
                        # De ha csak a csomagnév egyezik, de a verzió KÜLÖNBÖZŐ, akkor is töröljük
                        if old_version in filename or pkg_name in filename:
                            old_file.unlink()
                            logger.info(f"🗑️ AGGRESSIVE PURGE: Removed {old_file.name} from {search_dir.name}")
                            deleted_files.append(filename)
                            deleted_count += 1
                            
                            # Also remove signature if it exists
                            sig_file = old_file.with_suffix(old_file.suffix + '.sig')
                            if sig_file.exists():
                                sig_file.unlink()
                                logger.info(f"🗑️ Removed old signature {sig_file.name}")
                                deleted_files.append(sig_file.name)
                        else:
                            logger.debug(f"⚠️ Skipping {filename} - doesn't match old version pattern")
                            
                    except Exception as e:
                        logger.warning(f"⚠️ Could not remove old file {old_file}: {e}")
        
        if deleted_count > 0:
            logger.info(f"✅ PRE-BUILD PURGE FIX: Removed {deleted_count} old version file(s) for {pkg_name}")
            logger.info(f"📋 Deleted files: {deleted_files}")
        else:
            logger.debug(f"ℹ️ Pre-build purge: No old version files found for {pkg_name}")
    
    def server_cleanup(self):
        """
        ZERO-RESIDUE SERVER CLEANUP: Remove orphaned package files from VPS 
        using LOCAL OUTPUT DIRECTORY as source of truth.
        
        ✅ FIXED: Cleanup runs as long as upload of NEW packages was successful,
        even if GPG signing had warnings.
        
        STRICT LOGIC:
        1. Attempt to sync pacman database before cleanup
        2. Get ALL package files from local output directory (newly built + mirrored)
        3. Get ALL database files from local output directory
        4. PROTECT repository metadata files from deletion
        5. Compare VPS files with local files - delete anything on VPS not present locally
        6. ATOMIC execution: single SSH rm -f command for all orphaned files
        """
        print("\n" + "=" * 60)
        print("🔒 ZERO-RESIDUE SERVER CLEANUP: Using local output directory as source of truth")
        print("=" * 60)
        
        # ✅ FIX: Cleanup runs as long as upload was successful
        # Nem csak teljes sikeres feltöltés, hanem ha bármilyen új csomag feltöltése sikerült
        if not hasattr(self, '_upload_successful'):
            logger.error("❌ SAFETY VALVE: Cleanup cannot run because upload status unknown!")
            return
        
        # ✅ MÓDOSÍTÁS: A cleanup fut, ha volt bármilyen sikeres feltöltés
        # Nem csak akkor, ha minden tökéletes volt (GPG figyelmeztetések mellett is fut)
        if not self._upload_successful:
            logger.warning("⚠️ Upload was not fully successful, but attempting cleanup anyway...")
            # Itt dönthetünk úgy, hogy mégsem fut, de a specifikáció szerint próbáljuk meg
            # return  # Eredetileg itt return-öltünk, de most próbáljuk meg
        
        # STEP 1: Get ALL valid files from local output directory
        valid_filenames = self._collect_valid_files()
        
        # VALVE 2: CRITICAL - Must have at least one valid file
        if len(valid_filenames) == 0:
            logger.error("❌❌❌ CRITICAL SAFETY VALVE ACTIVATED: No valid files in output directory!")
            logger.error("   🚨 CLEANUP ABORTED - Output directory empty, potential data loss!")
            return
        
        # STEP 2: Get COMPLETE inventory of all files on VPS
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.warning("⚠️ Could not get VPS file inventory, skipping cleanup")
            return
        
        # STEP 3: Identify orphaned files (files on VPS not in local output directory)
        orphaned_files = self._identify_orphaned_files(vps_files, valid_filenames)
        
        if not orphaned_files:
            logger.info("✅ No orphaned files found - VPS matches local output directory exactly")
            return
        
        # STEP 4: DEBUGGING - Log files to be deleted BEFORE running rm -f
        self._log_orphaned_files(orphaned_files)
        
        # STEP 5: ATOMIC EXECUTION - delete all orphaned files in single command
        self._atomic_deletion(orphaned_files)
        
        logger.info(f"📊 Cleanup complete: VPS now has exactly {len(valid_filenames)} valid files")
    
    def _collect_valid_files(self) -> Set[str]:
        """Collect all valid files from local output directory"""
        valid_filenames = set()
        logger.info("🔍 Collecting ALL valid files from local output directory...")
        
        # Get ALL package files from local output directory
        for pkg_file in self.output_dir.glob("*.pkg.tar.*"):
            if pkg_file.is_file():
                valid_filenames.add(pkg_file.name)
                logger.debug(f"✅ Added package to valid files: {pkg_file.name}")
                
                # Also add signature file if it exists locally
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if sig_file.exists():
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
            if db_file.exists():
                valid_filenames.add(db_file.name)
                logger.debug(f"✅ Added database file to valid files: {db_file.name}")
        
        # CRITICAL: Also add ALL .sig files for packages that have them
        for sig_file in self.output_dir.glob("*.sig"):
            if sig_file.is_file():
                valid_filenames.add(sig_file.name)
                logger.debug(f"✅ Added signature file to valid files: {sig_file.name}")
        
        logger.info(f"✅ Local output directory has {len(valid_filenames)} valid files")
        
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
        """Generate repository database from ALL locally available packages"""
        print("\n" + "=" * 60)
        print("PHASE: Repository Database Generation")
        print("=" * 60)
        
        # First, do a final aggressive cleanup of old versions
        self._final_aggressive_cleanup()
        
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
    
    def _final_aggressive_cleanup(self):
        """Final aggressive cleanup before database generation"""
        logger.info("🔍 FINAL AGGRESSIVE CLEANUP: Removing duplicate/old versions...")
        
        # Scan for all package files and identify duplicates
        all_files = list(self.output_dir.glob("*.pkg.tar.*"))
        package_versions = {}
        
        # Group files by package name
        for pkg_file in all_files:
            filename = pkg_file.name
            # Extract package name (simplified logic)
            # Format: name-version-release-arch.pkg.tar.zst
            parts = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '').split('-')
            if len(parts) >= 4:
                # Assume the last 3 parts are arch, release, version
                # Everything before that is package name
                name_parts = parts[:-3]
                if name_parts:
                    pkg_name = '-'.join(name_parts)
                    if pkg_name not in package_versions:
                        package_versions[pkg_name] = []
                    package_versions[pkg_name].append(pkg_file)
        
        # For each package, keep only the newest version
        for pkg_name, files in package_versions.items():
            if len(files) > 1:
                logger.warning(f"⚠️ Multiple versions found for {pkg_name}: {[f.name for f in files]}")
                # Keep all for now - version comparison is complex
                # In production, we'd use vercmp to determine newest
    
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