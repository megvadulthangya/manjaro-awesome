import os
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import logging
import re

# Import required modules
from modules.repo.manifest_factory import ManifestFactory
from modules.gpg.gpg_handler import GPGHandler
from modules.build.version_manager import VersionManager
from modules.build.local_builder import LocalBuilder
from modules.build.aur_builder import AURBuilder
from modules.scm.git_client import GitClient
from modules.common.shell_executor import ShellExecutor
from modules.build.artifact_manager import ArtifactManager

logger = logging.getLogger(__name__)


class PackageBuilder:
    """
    Package Builder Module - Handles version audit and building logic.
    
    Core rules:
    1. Compare PKGBUILD version with mirror version
    2. Build ONLY if source version is newer
    3. Immediately sign built packages via gpg_handler
    """
    
    def __init__(
        self,
        version_manager: VersionManager,
        gpg_handler: GPGHandler,
        packager_id: str,
        output_dir: Path,
        version_tracker,  # Added: VersionTracker for skipped package registration
        debug_mode: bool = False,
        vps_files: Optional[List[str]] = None,  # NEW: VPS file inventory for completeness check
        build_tracker=None  # NEW: BuildTracker for hokibot data
    ):
        """
        Initialize PackageBuilder with dependencies.
        
        Args:
            version_manager: VersionManager instance for version comparison
            gpg_handler: GPGHandler instance for signing
            packager_id: Packager identity string
            output_dir: Directory for built packages
            version_tracker: VersionTracker instance for tracking skipped packages
            debug_mode: Enable debug logging
            vps_files: List of files on VPS for completeness check
            build_tracker: BuildTracker instance for hokibot data
        """
        self.version_manager = version_manager
        self.gpg_handler = gpg_handler
        self.packager_id = packager_id
        self.output_dir = output_dir
        self.version_tracker = version_tracker  # Store version tracker
        self.debug_mode = debug_mode
        self.vps_files = vps_files or []  # NEW: Store VPS file inventory
        self.build_tracker = build_tracker  # NEW: Store build tracker
        self._recently_built_files: List[str] = []  # NEW: Track files built in current session
        
        # Initialize modular components
        self.local_builder = LocalBuilder(debug_mode=debug_mode)
        self.aur_builder = AURBuilder(debug_mode=debug_mode)
        self.git_client = GitClient(repo_url=None)
        self.shell_executor = ShellExecutor(debug_mode=debug_mode)
        self.artifact_manager = ArtifactManager()
        
        # Ensure output directory exists
        self.output_dir.mkdir(exist_ok=True, parents=True)
    
    def set_vps_files(self, vps_files: List[str]):
        """Set VPS file inventory for completeness checks"""
        self.vps_files = vps_files
    
    def audit_and_build_local(
        self,
        pkg_dir: Path,
        remote_version: Optional[str],
        skip_check: bool = False
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, str]], Optional[Dict[str, str]]]:
        """
        Audit and build local package.
        
        Args:
            pkg_dir: Path to local package directory
            remote_version: Current version on mirror (None if not exists)
            skip_check: Skip version check and force build (for testing)
            
        Returns:
            Tuple of (built: bool, built_version: str, metadata: dict, artifact_versions: dict)
        """
        logger.info(f"🔍 Auditing local package: {pkg_dir.name}")
        
        # Step 1: Extract version from PKGBUILD
        try:
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
            source_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            logger.info(f"📦 PKGBUILD source version: {source_version}")
            logger.info(f"📦 Remote version: {remote_version or 'Not found'}")
        except Exception as e:
            logger.error(f"❌ Failed to extract version from {pkg_dir}: {e}")
            return False, None, None, None
        
        # Step 2: Extract all package names from PKGBUILD
        pkg_names = self._extract_package_names(pkg_dir)
        
        # Step 3: Version comparison (skip if forced)
        if not skip_check and remote_version:
            should_build = self.version_manager.compare_versions(
                pkg_dir, remote_version, pkgver, pkgrel, epoch
            )
            if not should_build:
                # NEW: Only check completeness if versions are equal (not when remote is newer)
                # Get full remote version string for comparison
                remote_full_version = remote_version
                source_full_version = source_version
                
                # Compare versions directly to determine if they're equal
                if remote_full_version == source_full_version:
                    # Versions are equal, check completeness
                    is_complete = self._check_split_package_completeness(pkg_dir.name, pkg_names, pkgver, pkgrel, epoch)
                    if is_complete:
                        logger.info(f"✅ {pkg_dir.name}: Up to date ({remote_version}) and all split artifacts present")
                        # Register skipped package for ALL pkgname entries
                        self.version_tracker.register_split_packages(pkg_names, remote_version, is_built=False)
                        return False, source_version, {
                            "pkgver": pkgver,
                            "pkgrel": pkgrel,
                            "epoch": epoch,
                            "pkgnames": pkg_names
                        }, None
                    else:
                        # Incomplete on VPS - force build
                        logger.info(f"🔄 {pkg_dir.name}: Version matches but VPS is incomplete - FORCING BUILD")
                else:
                    # Remote version is newer than source - skip without completeness check
                    logger.info(f"⏭️ {pkg_dir.name}: Remote version {remote_version} is newer than source {source_version}; skipping without completeness override")
                    # Register skipped package for ALL pkgname entries
                    self.version_tracker.register_split_packages(pkg_names, remote_version, is_built=False)
                    return False, source_version, {
                        "pkgver": pkgver,
                        "pkgrel": pkgrel,
                        "epoch": epoch,
                        "pkgnames": pkg_names
                    }, None
        
        # Step 4: Build package
        logger.info(f"🔨 Building {pkg_dir.name} ({source_version})...")
        logger.info("LOCAL_BUILDER_USED=1")
        built_files, build_output = self._build_local_package(pkg_dir, source_version)
        
        if built_files:
            # Step 5: Extract ACTUAL artifact versions from built files
            artifact_versions = self.version_manager.extract_artifact_versions(self.output_dir, pkg_names)
            
            # Fallback: try to extract from makepkg output if artifact parsing fails
            if not artifact_versions and build_output:
                artifact_version = self.version_manager.get_artifact_version_from_makepkg(build_output)
                if artifact_version:
                    for pkg_name in pkg_names:
                        artifact_versions[pkg_name] = artifact_version
            
            # Step 6: Determine which version to use (artifact truth vs PKGBUILD)
            actual_version = None
            if artifact_versions:
                # Use artifact version for the main package
                main_pkg = pkg_dir.name
                if main_pkg in artifact_versions:
                    actual_version = artifact_versions[main_pkg]
                    logger.info(f"[VERSION_TRUTH] PKGBUILD: {source_version}, Artifact: {actual_version}")
                    
                    # For VCS packages, update the source version with artifact truth
                    if actual_version != source_version:
                        logger.info(f"[VERSION_TRUTH] Using artifact version for VCS package: {actual_version}")
                        # Parse the artifact version to update pkgver/pkgrel/epoch
                        if ':' in actual_version:
                            epoch_part, rest = actual_version.split(':', 1)
                            if '-' in rest:
                                pkgver_actual, pkgrel_actual = rest.split('-', 1)
                            else:
                                pkgver_actual = rest
                                pkgrel_actual = "1"
                        else:
                            epoch_part = "0"
                            if '-' in actual_version:
                                pkgver_actual, pkgrel_actual = actual_version.split('-', 1)
                            else:
                                pkgver_actual = actual_version
                                pkgrel_actual = "1"
                        
                        # Update metadata with artifact truth
                        pkgver = pkgver_actual
                        pkgrel = pkgrel_actual
                        epoch = epoch_part if epoch_part != "0" else epoch
                        source_version = actual_version
            
            # Use PKGBUILD version if no artifact version found
            if not actual_version:
                actual_version = source_version
                logger.info(f"[VERSION_TRUTH] Using PKGBUILD version (no artifact found): {actual_version}")
            
            # Step 7: Sign ALL built package files (including split packages)
            self._sign_built_packages(built_files, actual_version)
            
            # NEW: Register target version for ALL pkgname entries using ACTUAL version
            self.version_tracker.register_split_packages(pkg_names, actual_version, is_built=True)
            
            # NEW: Record hokibot data for local package with ACTUAL version
            if self.build_tracker:
                self.build_tracker.add_hokibot_data(
                    pkg_name=pkg_dir.name,
                    pkgver=pkgver,
                    pkgrel=pkgrel,
                    epoch=epoch,
                    old_version=remote_version,
                    new_version=actual_version
                )
            
            # Log version truth chain
            logger.info(f"[VERSION_TRUTH_CHAIN] Package: {pkg_dir.name}")
            logger.info(f"[VERSION_TRUTH_CHAIN] PKGBUILD/.SRCINFO: {source_version}")
            logger.info(f"[VERSION_TRUTH_CHAIN] Artifact-derived: {actual_version}")
            logger.info(f"[VERSION_TRUTH_CHAIN] Registered for prune/hokibot: {actual_version}")
            
            return True, actual_version, {
                "pkgver": pkgver,
                "pkgrel": pkgrel,
                "epoch": epoch,
                "pkgnames": pkg_names
            }, artifact_versions
        
        return False, source_version, None, None
    
    def audit_and_build_aur(
        self,
        aur_package_name: str,
        remote_version: Optional[str],
        aur_build_dir: Path,
        skip_check: bool = False
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, str]], Optional[Dict[str, str]]]:
        """
        Audit and build AUR package.
        
        Args:
            aur_package_name: AUR package name
            remote_version: Current version on mirror (None if not exists)
            aur_build_dir: Directory for AUR builds
            skip_check: Skip version check and force build (for testing)
            
        Returns:
            Tuple of (built: bool, built_version: str, metadata: dict, artifact_versions: dict)
        """
        logger.info(f"🔍 Auditing AUR package: {aur_package_name}")
        
        # Step 1: Clone AUR package
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix=f"aur_{aur_package_name}_")
            temp_path = Path(temp_dir)
            
            # Clone AUR package using GitClient
            logger.info("GIT_CLIENT_USED=1")
            clone_success = self._clone_aur_package(aur_package_name, temp_path)
            if not clone_success:
                logger.error(f"❌ Failed to clone AUR package: {aur_package_name}")
                return False, None, None, None
            
            # Step 2: Extract version from PKGBUILD
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(temp_path)
            source_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            logger.info(f"📦 AUR PKGBUILD source version: {source_version}")
            logger.info(f"📦 Remote version: {remote_version or 'Not found'}")
            
            # Step 3: Extract all package names from PKGBUILD
            pkg_names = self._extract_package_names(temp_path)
            
            # Step 4: Version comparison (skip if forced)
            if not skip_check and remote_version:
                should_build = self.version_manager.compare_versions(
                    temp_path, remote_version, pkgver, pkgrel, epoch
                )
                if not should_build:
                    # NEW: Only check completeness if versions are equal (not when remote is newer)
                    # Get full remote version string for comparison
                    remote_full_version = remote_version
                    source_full_version = source_version
                    
                    # Compare versions directly to determine if they're equal
                    if remote_full_version == source_full_version:
                        # Versions are equal, check completeness
                        is_complete = self._check_split_package_completeness(aur_package_name, pkg_names, pkgver, pkgrel, epoch)
                        if is_complete:
                            logger.info(f"✅ {aur_package_name}: Up to date ({remote_version}) and all split artifacts present")
                            # Register skipped package for ALL pkgname entries
                            self.version_tracker.register_split_packages(pkg_names, remote_version, is_built=False)
                            return False, source_version, {
                                "pkgver": pkgver,
                                "pkgrel": pkgrel,
                                "epoch": epoch,
                                "pkgnames": pkg_names
                            }, None
                        else:
                            # Incomplete on VPS - force build
                            logger.info(f"🔄 {aur_package_name}: Version matches but VPS is incomplete - FORCING BUILD")
                    else:
                        # Remote version is newer than source - skip without completeness check
                        logger.info(f"⏭️ {aur_package_name}: Remote version {remote_version} is newer than source {source_version}; skipping without completeness override")
                        # Register skipped package for ALL pkgname entries
                        self.version_tracker.register_split_packages(pkg_names, remote_version, is_built=False)
                        return False, source_version, {
                            "pkgver": pkgver,
                            "pkgrel": pkgrel,
                            "epoch": epoch,
                            "pkgnames": pkg_names
                        }, None
            
            # Step 5: Build package
            logger.info(f"🔨 Building AUR {aur_package_name} ({source_version})...")
            logger.info("AUR_BUILDER_USED=1")
            built_files, build_output = self._build_aur_package(temp_path, aur_package_name, source_version)
            
            if built_files:
                # Step 6: Extract ACTUAL artifact versions from built files
                artifact_versions = self.version_manager.extract_artifact_versions(self.output_dir, pkg_names)
                
                # Fallback: try to extract from makepkg output if artifact parsing fails
                if not artifact_versions and build_output:
                    artifact_version = self.version_manager.get_artifact_version_from_makepkg(build_output)
                    if artifact_version:
                        for pkg_name in pkg_names:
                            artifact_versions[pkg_name] = artifact_version
                
                # Step 7: Determine which version to use (artifact truth vs PKGBUILD)
                actual_version = None
                if artifact_versions:
                    # Use artifact version for the main package
                    if aur_package_name in artifact_versions:
                        actual_version = artifact_versions[aur_package_name]
                        logger.info(f"[VERSION_TRUTH] PKGBUILD: {source_version}, Artifact: {actual_version}")
                        
                        # For VCS packages, update the source version with artifact truth
                        if actual_version != source_version:
                            logger.info(f"[VERSION_TRUTH] Using artifact version for VCS package: {actual_version}")
                            # Parse the artifact version to update pkgver/pkgrel/epoch
                            if ':' in actual_version:
                                epoch_part, rest = actual_version.split(':', 1)
                                if '-' in rest:
                                    pkgver_actual, pkgrel_actual = rest.split('-', 1)
                                else:
                                    pkgver_actual = rest
                                    pkgrel_actual = "1"
                            else:
                                epoch_part = "0"
                                if '-' in actual_version:
                                    pkgver_actual, pkgrel_actual = actual_version.split('-', 1)
                                else:
                                    pkgver_actual = actual_version
                                    pkgrel_actual = "1"
                            
                            # Update metadata with artifact truth
                            pkgver = pkgver_actual
                            pkgrel = pkgrel_actual
                            epoch = epoch_part if epoch_part != "0" else epoch
                            source_version = actual_version
                
                # Use PKGBUILD version if no artifact version found
                if not actual_version:
                    actual_version = source_version
                    logger.info(f"[VERSION_TRUTH] Using PKGBUILD version (no artifact found): {actual_version}")
                
                # Step 8: Sign ALL built package files (including split packages)
                self._sign_built_packages(built_files, actual_version)
                
                # NEW: Register target version for ALL pkgname entries using ACTUAL version
                self.version_tracker.register_split_packages(pkg_names, actual_version, is_built=True)
                
                # Note: AUR packages do NOT record hokibot data per requirements
                
                # Log version truth chain
                logger.info(f"[VERSION_TRUTH_CHAIN] Package: {aur_package_name}")
                logger.info(f"[VERSION_TRUTH_CHAIN] PKGBUILD/.SRCINFO: {source_version}")
                logger.info(f"[VERSION_TRUTH_CHAIN] Artifact-derived: {actual_version}")
                logger.info(f"[VERSION_TRUTH_CHAIN] Registered for prune/hokibot: {actual_version}")
                
                return True, actual_version, {
                    "pkgver": pkgver,
                    "pkgrel": pkgrel,
                    "epoch": epoch,
                    "pkgnames": pkg_names
                }, artifact_versions
            
            return False, source_version, None, None
            
        except Exception as e:
            logger.error(f"❌ Error building AUR package {aur_package_name}: {e}")
            return False, None, None, None
        finally:
            # Cleanup temporary directory
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
