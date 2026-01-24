"""
Repository Management Module - Handles database operations, cleanup, and JSON State Tracking
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
    """Manages repository database operations, cleanup, and JSON State Tracking"""
    
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
        
        # Get repo root from GITHUB_WORKSPACE or fallback
        self.repo_root = self._get_repo_root()
        
        # State tracking directory and file
        self.build_tracking_dir = self.repo_root / ".build_tracking"
        self.build_tracking_dir.mkdir(exist_ok=True, mode=0o755)
        self.state_file = self.build_tracking_dir / "vps_state.json"
        
        # Initialize state
        self.state_changed = False
        self.state = self._load_state()
        
        # VPS client for remote operations
        self.vps_client = None  # Will be set by builder.py
        
    def set_vps_client(self, vps_client):
        """Set VPS client for remote operations"""
        self.vps_client = vps_client
    
    def _get_repo_root(self):
        """Get the repository root directory reliably"""
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                return workspace_path
        
        container_workspace = Path('/__w/manjaro-awesome/manjaro-awesome')
        if container_workspace.exists():
            return container_workspace
        
        # Get script directory and go up to repo root
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent.parent.parent
        if repo_root.exists():
            return repo_root
        
        return Path.cwd()
    
    def _load_state(self) -> Dict[str, Any]:
        """Load JSON state from file or create empty state"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                logger.info(f"✅ Loaded existing state from {self.state_file}")
                return state
            except Exception as e:
                logger.error(f"Error loading state file: {e}")
        
        # Create initial state structure
        initial_state = {
            "version": "1.0",
            "created": datetime.now().isoformat(),
            "last_updated": None,
            "packages": {},
            "repository": {
                "name": self.repo_name,
                "remote_dir": self.remote_dir,
                "exists_on_vps": False,
                "has_packages": False
            }
        }
        logger.info(f"Created initial state structure")
        return initial_state
    
    def save_state(self):
        """Save JSON state to file"""
        if not self.state_changed:
            logger.debug("State not changed, skipping save")
            return
        
        self.state["last_updated"] = datetime.now().isoformat()
        
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
            logger.info(f"✅ Saved state to {self.state_file}")
            self.state_changed = False
        except Exception as e:
            logger.error(f"Error saving state file: {e}")
    
    def migrate_state_cold_start(self, package_name: str, is_aur: bool) -> str:
        """
        Migration (Cold Start): Check VPS and adopt packages
        
        Returns:
            Package status: "adopted", "build_needed", or "error"
        """
        logger.info(f"📋 Cold start migration for {package_name}")
        
        # Get package path based on type
        if is_aur:
            package_path = self.repo_root / "build_aur" / package_name / "PKGBUILD"
        else:
            package_path = self.repo_root / package_name / "PKGBUILD"
        
        if not package_path.exists():
            logger.error(f"PKGBUILD not found at {package_path}")
            return "error"
        
        # Check if package already in state
        if package_name in self.state["packages"]:
            logger.info(f"Package {package_name} already in state, skipping migration")
            return "adopted"
        
        # Build remote package path
        remote_pkg_pattern = f"{self.remote_dir}/{package_name}-*.pkg.tar.zst"
        
        # Check if package exists on VPS
        logger.info(f"Checking VPS for {package_name}...")
        
        remote_cmd = f"find {self.remote_dir} -maxdepth 1 -type f -name '{package_name}-*.pkg.tar.zst' -o -name '{package_name}-*.pkg.tar.xz' | head -1"
        ssh_cmd = ["ssh", f"{self.vps_user}@{self.vps_host}", remote_cmd]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=False
            )
            
            if result.returncode == 0 and result.stdout.strip():
                remote_file = result.stdout.strip()
                filename = os.path.basename(remote_file)
                
                # Get remote hash
                hash_result = subprocess.run(
                    ["ssh", f"{self.vps_user}@{self.vps_host}", f"sha256sum '{remote_file}'"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False
                )
                
                if hash_result.returncode == 0:
                    hash_str = hash_result.stdout.strip().split()[0]
                    
                    # Extract version from filename
                    version = self._extract_version_from_filename(filename, package_name)
                    
                    # Add to state (adopt)
                    self.state["packages"][package_name] = {
                        "type": "aur" if is_aur else "local",
                        "current_version": version,
                        "current_hash": hash_str,
                        "remote_file": filename,
                        "last_verified": datetime.now().isoformat(),
                        "adopted": True,
                        "needs_rebuild": False
                    }
                    self.state_changed = True
                    logger.info(f"✅ Adopted {package_name} version {version} from VPS")
                    return "adopted"
            
            # Package not on VPS, mark for build
            logger.info(f"Package {package_name} not found on VPS, marking for build")
            self.state["packages"][package_name] = {
                "type": "aur" if is_aur else "local",
                "current_version": None,
                "current_hash": None,
                "remote_file": None,
                "last_verified": datetime.now().isoformat(),
                "adopted": False,
                "needs_rebuild": True
            }
            self.state_changed = True
            return "build_needed"
            
        except Exception as e:
            logger.error(f"Error during cold start migration for {package_name}: {e}")
            return "error"
    
    def verify_package(self, package_name: str, local_version: str, is_aur: bool) -> Tuple[bool, Optional[str]]:
        """
        Verify package state and determine if rebuild is needed
        
        Returns:
            Tuple of (needs_rebuild: bool, remote_version: Optional[str])
        """
        logger.info(f"🔍 Verifying {package_name} (local: {local_version})")
        
        # Check if package exists in state
        if package_name not in self.state["packages"]:
            logger.info(f"Package {package_name} not in state, needs migration")
            return True, None
        
        package_state = self.state["packages"][package_name]
        
        # If already marked for rebuild
        if package_state.get("needs_rebuild", False):
            logger.info(f"Package {package_name} already marked for rebuild")
            return True, package_state.get("current_version")
        
        # Compare versions
        stored_version = package_state.get("current_version")
        
        if stored_version != local_version:
            logger.info(f"Version mismatch: stored={stored_version}, local={local_version}")
            
            # Verify remote file still exists and matches hash
            if stored_version and self.vps_client:
                remote_file = package_state.get("remote_file")
                if remote_file:
                    remote_path = f"{self.remote_dir}/{remote_file}"
                    
                    # Check if file exists
                    if self.vps_client.check_remote_file_exists(remote_path):
                        # Get current hash
                        current_hash = self.vps_client.get_remote_file_hash(remote_path)
                        stored_hash = package_state.get("current_hash")
                        
                        if current_hash and current_hash == stored_hash:
                            logger.info(f"Remote file verified, updating state to local version")
                            # Update state to local version
                            package_state["current_version"] = local_version
                            package_state["needs_rebuild"] = True
                            self.state_changed = True
                            return True, stored_version
                        else:
                            logger.info(f"Hash mismatch or can't verify, marking for rebuild")
                            package_state["needs_rebuild"] = True
                            self.state_changed = True
                            return True, stored_version
                    else:
                        logger.info(f"Remote file missing, marking for rebuild")
                        package_state["needs_rebuild"] = True
                        self.state_changed = True
                        return True, stored_version
            
            # No remote version or can't verify, mark for rebuild
            package_state["needs_rebuild"] = True
            self.state_changed = True
            return True, stored_version
        
        # Versions match, verify remote
        logger.info(f"Versions match, verifying remote file...")
        
        if self.vps_client and package_state.get("remote_file"):
            remote_path = f"{self.remote_dir}/{package_state['remote_file']}"
            
            if not self.vps_client.check_remote_file_exists(remote_path):
                logger.info(f"Remote file missing, marking for rebuild")
                package_state["needs_rebuild"] = True
                self.state_changed = True
                return True, stored_version
            
            # Verify hash
            current_hash = self.vps_client.get_remote_file_hash(remote_path)
            stored_hash = package_state.get("current_hash")
            
            if current_hash and current_hash == stored_hash:
                logger.info(f"✅ Package {package_name} verified, no rebuild needed")
                return False, stored_version
            else:
                logger.info(f"Hash mismatch, marking for rebuild")
                package_state["needs_rebuild"] = True
                self.state_changed = True
                return True, stored_version
        
        logger.info(f"✅ Package {package_name} appears up to date")
        return False, stored_version
    
    def update_package_state(self, package_name: str, version: str, filename: str, file_hash: str, is_aur: bool):
        """Update package state after successful build"""
        logger.info(f"📝 Updating state for {package_name} ({version})")
        
        self.state["packages"][package_name] = {
            "type": "aur" if is_aur else "local",
            "current_version": version,
            "current_hash": file_hash,
            "remote_file": filename,
            "last_verified": datetime.now().isoformat(),
            "adopted": False,
            "needs_rebuild": False,
            "last_built": datetime.now().isoformat()
        }
        self.state_changed = True
    
    def mark_package_skipped(self, package_name: str, version: str, is_aur: bool):
        """Mark package as skipped (already up to date)"""
        logger.info(f"📝 Marking {package_name} as skipped (version: {version})")
        
        # Ensure package is in state
        if package_name not in self.state["packages"]:
            self.state["packages"][package_name] = {
                "type": "aur" if is_aur else "local",
                "current_version": version,
                "current_hash": None,
                "remote_file": None,
                "last_verified": datetime.now().isoformat(),
                "adopted": False,
                "needs_rebuild": False,
                "skipped": True
            }
        else:
            self.state["packages"][package_name].update({
                "current_version": version,
                "needs_rebuild": False,
                "skipped": True
            })
        
        self.state_changed = True
    
    def _extract_version_from_filename(self, filename: str, package_name: str) -> Optional[str]:
        """Extract version from package filename"""
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            # Find where package name ends
            for i in range(len(parts) - 2, 0, -1):
                possible_name = '-'.join(parts[:i])
                if possible_name == package_name or possible_name.startswith(package_name + '-'):
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
    
    # Legacy methods (kept for compatibility)
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        pass  # No longer used but kept for compatibility
    
    def register_package_target_version(self, pkg_name: str, target_version: str):
        """
        Register the target version for a package.
        
        Args:
            pkg_name: Package name
            target_version: The version we want to keep (either built or latest from server)
        """
        pass  # Now handled by JSON state
    
    def register_skipped_package(self, pkg_name: str, remote_version: str):
        """
        Register a package that was skipped because it's up-to-date.
        
        Args:
            pkg_name: Package name
            remote_version: The remote version that should be kept (not deleted)
        """
        self.mark_package_skipped(pkg_name, remote_version, False)
    
    def pre_build_purge_old_versions(self, pkg_name: str, old_version: str, target_version: Optional[str] = None):
        """
        🚨 ZERO-RESIDUE POLICY: Surgical old version removal BEFORE building
        """
        pass  # Now handled by state tracking
    
    def generate_full_database(self) -> bool:
        """
        Generate repository database from ALL locally available packages
        
        🚨 KRITIKUS: Run final validation BEFORE repo-add
        """
        print("\n" + "=" * 60)
        print("PHASE: Repository Database Generation")
        print("=" * 60)
        
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
        """Get ALL package files from local output directory"""
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