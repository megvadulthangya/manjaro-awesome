"""
Repository Management Module - Handles JSON state tracking, database operations, and Zero-Residue policy
"""

import os
import subprocess
import json
import re
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class RepoManager:
    """Manages repository database operations, JSON state tracking, and Zero-Residue policy"""
    
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
        """
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        
        # State tracking directories
        self.build_tracking_dir = self.output_dir.parent / ".build_tracking"
        self.build_tracking_dir.mkdir(exist_ok=True, parents=True)
        self.state_file = self.build_tracking_dir / "vps_state.json"
        
        # State tracking
        self.state_data: Dict[str, Dict[str, str]] = {}
        self.remote_packages_cache: List[str] = []
        self._upload_successful = False
        
        # Load existing state
        self._load_state()
    
    def _load_state(self):
        """Load JSON state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    self.state_data = json.load(f)
                logger.info(f"📊 Loaded state for {len(self.state_data)} packages")
            except json.JSONDecodeError:
                logger.warning("State file corrupted, starting fresh")
                self.state_data = {}
            except Exception as e:
                logger.warning(f"Could not load state file: {e}")
                self.state_data = {}
        else:
            logger.info("ℹ️ No state file found, starting fresh")
            self.state_data = {}
    
    def _save_state(self):
        """Save JSON state to file with human-readable indentation"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state_data, f, indent=4, sort_keys=True)
            logger.debug("✅ Saved state file with indent=4")
        except Exception as e:
            logger.error(f"❌ Failed to save state file: {e}")
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
    
    def set_remote_packages_cache(self, packages: List[str]):
        """Cache the list of remote packages for state migration"""
        self.remote_packages_cache = packages
    
    def migrate_state(self, vps_client, local_packages: List[str], aur_packages: List[str], build_engine) -> Dict[str, List[str]]:
        """
        Perform smart migration: adopt existing VPS packages into JSON state
        
        Args:
            vps_client: VPSClient instance for remote operations
            local_packages: List of local package names
            aur_packages: List of AUR package names
            build_engine: BuildEngine instance for version extraction
            
        Returns:
            Dictionary with 'adopted' and 'to_build' lists
        """
        logger.info("\n" + "=" * 60)
        logger.info("🔍 SMART STATE MIGRATION")
        logger.info("=" * 60)
        
        adopted = []
        to_build = []
        version_warnings = []
        
        # Track packages that need PKGBUILD for version extraction
        missing_pkgbuilds = []
        
        # Process each remote package
        for pkg_filename in self.remote_packages_cache:
            # Extract package name from filename
            parsed = self._parse_package_filename(pkg_filename)
            if not parsed:
                logger.warning(f"⚠️ Could not parse filename: {pkg_filename}")
                continue
            
            pkg_name, remote_version = parsed
            
            # Skip if already in state
            if pkg_name in self.state_data:
                logger.debug(f"📝 {pkg_name} already in state, skipping migration")
                continue
            
            # Check if this is a local or AUR package
            is_local = pkg_name in local_packages
            is_aur = pkg_name in aur_packages
            
            if not (is_local or is_aur):
                logger.debug(f"ℹ️ {pkg_name} not in package lists, skipping")
                continue
            
            # Determine PKGBUILD location
            pkgbuild_path = None
            if is_local:
                pkgbuild_path = self.output_dir.parent / pkg_name / "PKGBUILD"
            elif is_aur:
                # AUR packages need to be fetched first - will be handled in builder
                missing_pkgbuilds.append((pkg_name, remote_version, "aur"))
                continue
            
            # Check if PKGBUILD exists
            if pkgbuild_path and pkgbuild_path.exists():
                try:
                    # Extract version from PKGBUILD
                    pkg_dir = pkgbuild_path.parent
                    pkgver, pkgrel, epoch = build_engine.extract_version_from_srcinfo(pkg_dir)
                    local_version = build_engine.get_full_version_string(pkgver, pkgrel, epoch)
                    
                    # Compare versions - CRITICAL FIX: Don't downgrade!
                    if remote_version == local_version:
                        # Get remote hash
                        remote_hash = vps_client.get_remote_file_hash(f"{self.remote_dir}/{pkg_filename}")
                        if remote_hash:
                            # Adopt into state
                            self.state_data[pkg_name] = {
                                "version": remote_version,
                                "hash": remote_hash,
                                "filename": pkg_filename,
                                "last_verified": datetime.now().isoformat(),
                                "migrated": True
                            }
                            adopted.append(pkg_name)
                            logger.info(f"✅ Adopted {pkg_name} ({remote_version}) into state")
                        else:
                            logger.warning(f"⚠️ Could not get hash for {pkg_name}, marking for build")
                            to_build.append(pkg_name)
                    else:
                        # Check which version is newer
                        should_build = build_engine.compare_versions(remote_version, pkgver, pkgrel, epoch)
                        
                        if should_build:
                            # Local is newer than remote
                            logger.info(f"ℹ️ {pkg_name}: remote {remote_version} < local {local_version}, marking for build")
                            to_build.append(pkg_name)
                        else:
                            # Remote is newer than local - WARNING!
                            version_warnings.append(f"{pkg_name}: Remote {remote_version} > Local {local_version}")
                            logger.warning(f"⚠️ {pkg_name}: Remote version {remote_version} is NEWER than local {local_version}")
                            logger.warning(f"   This may indicate a downgrade. Will not rebuild unless forced.")
                            
                            # Still adopt the newer version, but with a warning flag
                            remote_hash = vps_client.get_remote_file_hash(f"{self.remote_dir}/{pkg_filename}")
                            if remote_hash:
                                self.state_data[pkg_name] = {
                                    "version": remote_version,
                                    "hash": remote_hash,
                                    "filename": pkg_filename,
                                    "last_verified": datetime.now().isoformat(),
                                    "migrated": True,
                                    "warning": "remote_newer_than_local"
                                }
                                adopted.append(pkg_name)
                                logger.info(f"⚠️ Adopted newer remote version of {pkg_name} ({remote_version})")
                            
                except Exception as e:
                    logger.warning(f"⚠️ Error processing {pkg_name}: {e}, marking for build")
                    to_build.append(pkg_name)
            else:
                logger.info(f"ℹ️ PKGBUILD not found for {pkg_name}, marking for build")
                to_build.append(pkg_name)
        
        # Save updated state
        self._save_state()
        
        # Log version warnings
        if version_warnings:
            logger.warning("\n" + "=" * 60)
            logger.warning("⚠️ VERSION MISMATCH WARNINGS")
            logger.warning("=" * 60)
            for warning in version_warnings:
                logger.warning(f"  {warning}")
            logger.warning("These packages have NEWER versions on VPS than locally.")
            logger.warning("They will NOT be rebuilt to avoid downgrades.")
        
        logger.info(f"📊 Migration results: {len(adopted)} adopted, {len(to_build)} to build")
        
        return {
            "adopted": adopted,
            "to_build": to_build,
            "missing_pkgbuilds": missing_pkgbuilds,
            "version_warnings": version_warnings
        }
    
    def verify_package_state(self, pkg_name: str, pkg_type: str, local_version: str, 
                           vps_client, build_engine) -> Tuple[bool, Optional[str]]:
        """
        Verify if a package is up-to-date by checking version and hash
        
        Returns:
            Tuple of (needs_build, remote_version_or_none)
        """
        # Check if package is in state
        if pkg_name in self.state_data:
            state_info = self.state_data[pkg_name]
            state_version = state_info.get("version", "")
            
            # Check for version mismatch warning
            if state_info.get("warning") == "remote_newer_than_local":
                logger.warning(f"⚠️ {pkg_name}: Remote version {state_version} is NEWER than what we would build")
                logger.warning(f"   Skipping to avoid downgrade from {state_version} to {local_version}")
                return False, state_version
            
            # Compare versions
            if state_version == local_version:
                # Verify remote hash matches
                remote_filename = state_info.get("filename", "")
                if remote_filename:
                    remote_hash = vps_client.get_remote_file_hash(f"{self.remote_dir}/{remote_filename}")
                    if remote_hash == state_info.get("hash", ""):
                        logger.info(f"✅ {pkg_name}: Version and hash verified, up-to-date")
                        return False, state_version
                    else:
                        logger.warning(f"⚠️ {pkg_name}: Hash mismatch, rebuilding")
                        return True, state_version
                else:
                    logger.warning(f"⚠️ {pkg_name}: No filename in state, rebuilding")
                    return True, state_version
            else:
                # Version mismatch, check if local is newer
                try:
                    # Parse versions for comparison
                    pkgver, pkgrel, epoch = self._parse_version_string(local_version)
                    
                    # Use build_engine to compare
                    should_build = build_engine.compare_versions(state_version, pkgver, pkgrel, epoch)
                    if should_build:
                        logger.info(f"ℹ️ {pkg_name}: Local {local_version} > Remote {state_version}, building")
                    else:
                        logger.warning(f"⚠️ {pkg_name}: Remote {state_version} > Local {local_version}, skipping")
                        logger.warning(f"   Will not downgrade from {state_version} to {local_version}")
                    
                    return should_build, state_version
                except Exception as e:
                    logger.warning(f"⚠️ {pkg_name}: Version comparison failed: {e}, rebuilding")
                    return True, state_version
        else:
            # Not in state, check if exists on VPS
            for pkg_filename in self.remote_packages_cache:
                if pkg_filename.startswith(f"{pkg_name}-"):
                    parsed = self._parse_package_filename(pkg_filename)
                    if parsed and parsed[0] == pkg_name:
                        logger.info(f"ℹ️ {pkg_name}: Found on VPS but not in state, version check needed")
                        return True, parsed[1]
            
            logger.info(f"ℹ️ {pkg_name}: Not in state or on VPS, needs build")
            return True, None
    
    def update_package_state(self, pkg_name: str, version: str, filename: str, vps_client):
        """
        Update state for a newly built package
        
        Args:
            pkg_name: Package name
            version: Package version
            filename: Package filename
            vps_client: VPSClient instance for hash calculation
        """
        # Get remote hash
        remote_hash = vps_client.get_remote_file_hash(f"{self.remote_dir}/{filename}")
        if remote_hash:
            self.state_data[pkg_name] = {
                "version": version,
                "hash": remote_hash,
                "filename": filename,
                "last_verified": datetime.now().isoformat(),
                "built_at": datetime.now().isoformat()
            }
            logger.info(f"📝 Updated state for {pkg_name} ({version})")
        else:
            logger.warning(f"⚠️ Could not get hash for {pkg_name}, state not updated")
        
        # Save state with proper indentation
        self._save_state()
    
    def _parse_package_filename(self, filename: str) -> Optional[Tuple[str, str]]:
        """Parse package filename to extract name and version"""
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            # Find where package name ends and version begins
            # Look for the pattern where version starts (contains numbers and dots)
            for i in range(len(parts) - 2, 0, -1):
                potential_name = '-'.join(parts[:i])
                remaining = parts[i:]
                
                # Check if remaining parts look like version-release-arch
                if len(remaining) >= 3:
                    # Check for epoch format (e.g., "2:26.1.9-1")
                    if ':' in remaining[0]:
                        epoch_version = remaining[0]
                        release = remaining[1]
                        version_str = f"{epoch_version}-{release}"
                        return potential_name, version_str
                    # Standard format
                    elif any(c.isdigit() or c == '.' for c in remaining[0]):
                        version_part = remaining[0]
                        release_part = remaining[1]
                        version_str = f"{version_part}-{release_part}"
                        return potential_name, version_str
        
        except Exception as e:
            logger.debug(f"Could not parse filename {filename}: {e}")
        
        return None
    
    def _parse_version_string(self, version_str: str) -> Tuple[str, str, Optional[str]]:
        """Parse version string into components"""
        epoch = None
        pkgver = ""
        pkgrel = "1"
        
        if ':' in version_str:
            epoch_part, rest = version_str.split(':', 1)
            epoch = epoch_part
            if '-' in rest:
                pkgver, pkgrel = rest.split('-', 1)
            else:
                pkgver = rest
        else:
            if '-' in version_str:
                pkgver, pkgrel = version_str.split('-', 1)
            else:
                pkgver = version_str
        
        return pkgver, pkgrel, epoch
    
    def generate_full_database(self) -> bool:
        """
        Generate repository database from ALL locally available packages
        """
        logger.info("\n" + "=" * 60)
        logger.info("📦 Repository Database Generation")
        logger.info("=" * 60)
        
        # Get all package files from local output directory
        all_packages = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not all_packages:
            logger.info("ℹ️ No packages available for database generation")
            return False
        
        logger.info(f"Generating database with {len(all_packages)} packages...")
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz", 
                      f"{self.repo_name}.files", f"{self.repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            # Generate database with repo-add using shell=True for wildcard expansion
            # Use raw string to avoid escape sequence warnings
            cmd = rf"repo-add {db_file} *.pkg.tar.zst *.pkg.tar.xz"
            
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
                    else:
                        logger.warning(f"Could not list database contents: {list_result.stderr}")
                
                return True
            else:
                logger.error(f"repo-add failed: {result.stderr[:500]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def check_database_files(self) -> Tuple[List[str], List[str]]:
        """Check if repository database files exist on server"""
        logger.info("🔍 Checking existing database files on server...")
        
        db_files = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz"
        ]
        
        existing_files = []
        missing_files = []
        
        # This is a placeholder - actual implementation should use VPSClient
        # We'll implement this properly if needed, but for now return empty lists
        return existing_files, missing_files