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
        
        # Ensure output directory exists with proper ownership and permissions
        self._ensure_output_directory()
    
    def _ensure_output_directory(self):
        """
        CRITICAL: Ensure output directory exists and is writable before any makepkg invocation.
        This prevents makepkg exit code 8 (E_MISSING_PKGDIR).
        """
        try:
            # Create directory with parents if needed
            self.output_dir.mkdir(exist_ok=True, parents=True)
            
            # Set proper permissions (read/write/execute for owner, read/execute for group/others)
            self.output_dir.chmod(0o755)
            
            # Check if we can write to the directory
            test_file = self.output_dir / ".write_test"
            try:
                test_file.touch()
                test_file.unlink()
                writable = True
            except (IOError, OSError):
                writable = False
            
            # Log directory status
            logger.info(f"OUTPUT_DIR_EXISTS=1 path={self.output_dir} writable={writable}")
            
            if not writable:
                logger.error(f"CRITICAL: Output directory is not writable: {self.output_dir}")
                # Try to fix permissions
                try:
                    import subprocess
                    subprocess.run(['chmod', '755', str(self.output_dir)], check=False)
                    subprocess.run(['chown', '-R', 'builder:builder', str(self.output_dir)], check=False)
                    logger.info("Attempted to fix permissions on output directory")
                except Exception as e:
                    logger.error(f"Failed to fix permissions: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to ensure output directory exists: {e}")
            raise
    
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
                remote_version, pkgver, pkgrel, epoch, pkg_dir  # Pass pkg_dir for VCS detection
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
        
        # Step 4: Install build dependencies only (CI-safe)
        logger.info(f"🔧 Installing build dependencies for {pkg_dir.name}...")
        if not self.local_builder.install_build_dependencies(str(pkg_dir)):
            logger.error(f"❌ Failed to install build dependencies for {pkg_dir.name}")
            return False, source_version, None, None
        
        # Step 5: Build package
        logger.info(f"🔨 Building {pkg_dir.name} ({source_version})...")
        logger.info("LOCAL_BUILDER_USED=1")
        built_files, build_output = self._build_local_package(pkg_dir, source_version)
        
        if built_files:
            # Step 6: Extract ACTUAL artifact versions from built files
            # NEW: Prefer built_files-based helper first
            artifact_versions = self.version_manager.extract_artifact_versions_from_files(built_files, pkg_names)
            
            # Fallback to output_dir scan if built_files didn't yield versions
            if not artifact_versions:
                artifact_versions = self.version_manager.extract_artifact_versions(self.output_dir, pkg_names)
                
                # Additional fallback: try to extract from makepkg output if artifact parsing fails
                if not artifact_versions and build_output:
                    artifact_version = self.version_manager.get_artifact_version_from_makepkg(build_output)
                    if artifact_version:
                        for pkg_name in pkg_names:
                            artifact_versions[pkg_name] = artifact_version
            
            # Step 7: Determine which version to use (artifact truth vs PKGBUILD)
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
            
            # Step 8: Sign ALL built package files (including split packages)
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
                    remote_version, pkgver, pkgrel, epoch, temp_path  # Pass temp_path for VCS detection
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
            
            # Step 5: Build package (dependencies are installed inside build_aur_package)
            logger.info(f"🔨 Building AUR {aur_package_name} ({source_version})...")
            logger.info("AUR_BUILDER_USED=1")
            built_files, build_output = self._build_aur_package(temp_path, aur_package_name, source_version)
            
            if built_files:
                # Step 6: Extract ACTUAL artifact versions from built files
                # NEW: Prefer built_files-based helper first
                artifact_versions = self.version_manager.extract_artifact_versions_from_files(built_files, pkg_names)
                
                # Fallback to output_dir scan if built_files didn't yield versions
                if not artifact_versions:
                    artifact_versions = self.version_manager.extract_artifact_versions(self.output_dir, pkg_names)
                    
                    # Additional fallback: try to extract from makepkg output if artifact parsing fails
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
    
    def _check_split_package_completeness(self, pkgbuild_name: str, pkg_names: List[str], pkgver: str, pkgrel: str, epoch: Optional[str]) -> bool:
        """
        NEW: Check if ALL split package artifacts exist on VPS.
        
        Args:
            pkgbuild_name: Name of the PKGBUILD (for logging)
            pkg_names: List of package names produced by the PKGBUILD
            pkgver: Package version
            pkgrel: Package release
            epoch: Package epoch (optional)
            
        Returns:
            True if all expected artifacts exist on VPS, False otherwise
        """
        if not self.vps_files:
            logger.warning(f"No VPS file inventory available for {pkgbuild_name} - skipping completeness verification")
            return True  # Fail-safe: If we can't verify, assume complete
        
        missing_artifacts = []
        
        for pkg_name in pkg_names:
            # FIXED: Build correct version segment with colon for epoch
            if epoch and epoch != '0':
                version_segment = f"{epoch}:{pkgver}-{pkgrel}"
            else:
                version_segment = f"{pkgver}-{pkgrel}"
            
            # Build base pattern with correct version formatting
            base_pattern = f"{pkg_name}-{version_segment}"
            
            # Check for package files (any architecture, any compression)
            package_found = False
            for vps_file in self.vps_files:
                # Check if file starts with base_pattern and has package extension
                if vps_file.startswith(base_pattern) and (vps_file.endswith('.pkg.tar.zst') or vps_file.endswith('.pkg.tar.xz')):
                    package_found = True
                    # Check for corresponding signature
                    sig_file = vps_file + '.sig'
                    if sig_file not in self.vps_files:
                        missing_artifacts.append(f"{vps_file}.sig")
                    break
            
            if not package_found:
                missing_artifacts.append(f"{base_pattern}-*.pkg.tar.*")
        
        if missing_artifacts:
            example = missing_artifacts[0] if missing_artifacts else "unknown"
            logger.warning(f"FORCE BUILD (incomplete VPS): {pkgbuild_name} missing {len(missing_artifacts)} artifacts, e.g. {example}")
            return False
        
        logger.info(f"SKIP OK (complete VPS): {pkgbuild_name} all split artifacts present")
        return True
    
    def _extract_package_names(self, pkg_dir: Path) -> List[str]:
        """
        Extract all package names from PKGBUILD.
        
        Args:
            pkg_dir: Path to package directory
            
        Returns:
            List of package names (single or multiple for split packages)
        """
        try:
            pkgbuild_content = ManifestFactory.get_pkgbuild(str(pkg_dir))
            if pkgbuild_content:
                pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)
                if pkg_names:
                    return pkg_names
        except Exception as e:
            logger.warning(f"Could not extract package names from {pkg_dir}: {e}")
        
        # Fallback: use directory name
        return [pkg_dir.name]
    
    def _clone_aur_package(self, pkg_name: str, target_dir: Path) -> bool:
        """Clone AUR package from Arch Linux AUR using GitClient."""
        logger.info(f"📥 Cloning {pkg_name} from AUR")
        
        # Try different AUR URLs
        aur_urls = [
            f"https://aur.archlinux.org/{pkg_name}.git",
            f"git://aur.archlinux.org/{pkg_name}.git"
        ]
        
        for aur_url in aur_urls:
            try:
                # Use GitClient to clone
                self.git_client.repo_url = aur_url
                if self.git_client.clone_repository(str(target_dir), depth=1):
                    logger.info(f"✅ Successfully cloned {pkg_name}")
                    return True
                else:
                    logger.warning(f"⚠️ Failed to clone from {aur_url}")
            except Exception as e:
                logger.warning(f"⚠️ Error cloning from {aur_url}: {e}")
        
        logger.error(f"❌ Failed to clone {pkg_name} from any AUR URL")
        return False
    
    def _build_local_package(self, pkg_dir: Path, version: str) -> Tuple[List[str], str]:
        """Build local package using LocalBuilder and return list of built files and output."""
        try:
            # Clean workspace using ArtifactManager
            self.artifact_manager.clean_workspace(pkg_dir)
            
            # Ensure output directory exists before building
            self._ensure_output_directory()
            
            # Download sources is now handled inside LocalBuilder.run_makepkg with retry
            
            # Build package using LocalBuilder
            logger.info("   Building package...")
            logger.info("LOCAL_BUILDER_USED=1")
            build_flags = "-s --noconfirm --clean"
            if pkg_dir.name == "gtk2":
                build_flags += " --nocheck"
                logger.info("   Skipping check for gtk2 (long)")
            
            build_result = self.local_builder.run_makepkg(
                pkg_dir=str(pkg_dir),
                packager_id=self.packager_id,
                flags=build_flags,
                timeout=3600
            )
            
            build_output = build_result.stdout if build_result else ""
            
            if build_result.returncode != 0:
                logger.error(f"❌ Build failed: {build_result.stderr[:500]}")
                return [], build_output
            
            # Move built packages to output directory and return list
            built_files = self._move_built_packages(pkg_dir, pkg_dir.name, version)
            
            if built_files:
                logger.info(f"✅ Successfully built {pkg_dir.name}")
                return built_files, build_output
            else:
                logger.error(f"❌ No package files created for {pkg_dir.name}")
                return [], build_output
                
        except Exception as e:
            logger.error(f"❌ Error building {pkg_dir.name}: {e}")
            return [], ""
    
    def _build_aur_package(self, pkg_dir: Path, pkg_name: str, version: str) -> Tuple[List[str], str]:
        """Build AUR package using AURBuilder and return list of built files and output."""
        try:
            # Clean workspace using ArtifactManager
            self.artifact_manager.clean_workspace(pkg_dir)
            
            # Ensure output directory exists before building
            self._ensure_output_directory()
            
            # Build package using AURBuilder
            logger.info("   Building package...")
            logger.info("AUR_BUILDER_USED=1")
            
            # Use AURBuilder for the entire build process
            built_files = self.aur_builder.build_aur_package(
                pkg_name=pkg_name,
                target_dir=pkg_dir,
                packager_id=self.packager_id,
                build_flags="-s --noconfirm --clean --nocheck",
                timeout=3600
            )
            
            build_output = ""  # AURBuilder doesn't return output, would need to modify
            
            if built_files:
                # Move built packages to output directory and return list
                moved_files = self._move_built_packages(pkg_dir, pkg_name, version)
                return moved_files, build_output
            else:
                logger.error(f"❌ No package files created for {pkg_name}")
                return [], build_output
                
        except Exception as e:
            logger.error(f"❌ Error building {pkg_name}: {e}")
            return [], ""
    
    def _move_built_packages(self, source_dir: Path, pkg_name: str, version: str) -> List[str]:
        """Move built packages to output directory and return list of moved files."""
        moved_files = []
        
        for pkg_file in source_dir.glob("*.pkg.tar.*"):
            # Skip signature files
            if pkg_file.suffix == '.sig':
                continue
                
            dest = self.output_dir / pkg_file.name
            try:
                shutil.move(str(pkg_file), str(dest))
                logger.info(f"   Moved: {pkg_file.name}")
                moved_files.append(pkg_file.name)
                
                # Also track for signing
                self._recently_built_files.append(pkg_file.name)
            except Exception as e:
                logger.error(f"   Failed to move {pkg_file.name}: {e}")
        
        return moved_files
    
    def _sign_built_packages(self, built_files: List[str], version: str):
        """
        Sign ALL built package files from a build session.
        
        FIX: Sign all package files produced by the build, not just those
        matching the main package name. This handles split/multi-package PKGBUILDs.
        """
        if not self.gpg_handler.sign_packages_enabled:
            logger.info(f"Package signing disabled, skipping signing for version {version}")
            return
        
        logger.info(f"🔐 Signing ALL built packages for version {version}...")
        
        # Build version string for filename matching (epoch:version -> epoch-version)
        version_in_filename = version.replace(':', '-')
        
        signed_count = 0
        failed_count = 0
        
        # First, sign the files we just built
        for built_file in built_files:
            pkg_file = self.output_dir / built_file
            if pkg_file.exists():
                if self.gpg_handler.sign_package(str(pkg_file)):
                    signed_count += 1
                    logger.info(f"✅ Signed built package: {built_file}")
                else:
                    failed_count += 1
                    logger.error(f"❌ Failed to sign built package: {built_file}")
            else:
                logger.warning(f"Built file not found in output_dir: {built_file}")
        
        # Second, check for any other packages with this version that might be missing signatures
        # This catches cached/mirrored packages that were skipped but need signatures
        for pkg_file in self.output_dir.glob("*.pkg.tar.*"):
            # Skip signature files
            if pkg_file.suffix == '.sig':
                continue
            
            # Check if this file has the version we just built/skipped
            if version_in_filename in pkg_file.name:
                sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                if not sig_file.exists():
                    # This is a package with our version but no signature
                    if pkg_file.name not in built_files:  # Not already signed above
                        if self.gpg_handler.sign_package(str(pkg_file)):
                            signed_count += 1
                            logger.info(f"✅ Signed existing package: {pkg_file.name}")
                        else:
                            failed_count += 1
                            logger.error(f"❌ Failed to sign existing package: {pkg_file.name}")
        
        if signed_count > 0:
            logger.info(f"✅ Signed {signed_count} packages for version {version}")
        else:
            logger.info(f"ℹ️ No packages needed signing for version {version}")
        
        if failed_count > 0:
            logger.warning(f"⚠️ Failed to sign {failed_count} packages for version {version}")
    
    def get_package_metadata(self, pkg_dir: Path) -> Optional[Dict[str, Any]]:
        """
        Extract package metadata from PKGBUILD.
        
        Args:
            pkg_dir: Path to package directory
            
        Returns:
            Dictionary with package metadata or None
        """
        try:
            # Use ManifestFactory to get pkgname values
            pkgbuild_content = ManifestFactory.get_pkgbuild(str(pkg_dir))
            if not pkgbuild_content:
                return None
            
            # Extract pkgname(s)
            pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)
            if not pkg_names:
                return None
            
            # Extract version
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
            
            return {
                "pkgnames": pkg_names,
                "pkgver": pkgver,
                "pkgrel": pkgrel,
                "epoch": epoch,
                "full_version": self.version_manager.get_full_version_string(pkgver, pkgrel, epoch),
                "source_dir": pkg_dir
            }
            
        except Exception as e:
            logger.error(f"Error extracting package metadata from {pkg_dir}: {e}")
            return None
    
    def batch_audit_and_build(
        self,
        local_packages: List[Tuple[Path, Optional[str]]],
        aur_packages: List[Tuple[str, Optional[str]]],
        aur_build_dir: Optional[Path] = None
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Batch audit and build multiple packages.
        
        Args:
            local_packages: List of (pkg_dir, remote_version) tuples
            aur_packages: List of (aur_name, remote_version) tuples
            aur_build_dir: Directory for AUR builds (creates temp if None)
            
        Returns:
            Tuple of (built_packages, skipped_packages, failed_packages)
        """
        built_packages = []
        skipped_packages = []
        failed_packages = []
        
        # Create AUR build directory if needed
        if aur_build_dir is None:
            aur_build_dir = Path(tempfile.mkdtemp(prefix="aur_build_"))
        aur_build_dir.mkdir(exist_ok=True, parents=True)
        
        # Process local packages
        logger.info(f"📦 Auditing {len(local_packages)} local packages...")
        for pkg_dir, remote_version in local_packages:
            try:
                built, version, metadata, artifact_versions = self.audit_and_build_local(
                    pkg_dir, remote_version
                )
                
                if built:
                    built_packages.append(f"{pkg_dir.name} ({version})")
                    # Note: Target versions are now registered in audit_and_build_local
                elif version:
                    skipped_packages.append(f"{pkg_dir.name} ({version})")
                    # Note: Skipped packages are now registered in audit_and_build_local
                else:
                    failed_packages.append(pkg_dir.name)
                    
            except Exception as e:
                logger.error(f"❌ Error processing local package {pkg_dir.name}: {e}")
                failed_packages.append(pkg_dir.name)
        
        # Process AUR packages
        logger.info(f"📦 Auditing {len(aur_packages)} AUR packages...")
        for aur_name, remote_version in aur_packages:
            try:
                built, version, metadata, artifact_versions = self.audit_and_build_aur(
                    aur_name, remote_version, aur_build_dir
                )
                
                if built:
                    built_packages.append(f"{aur_name} ({version})")
                    # Note: Target versions are now registered in audit_and_build_aur
                elif version:
                    skipped_packages.append(f"{aur_name} ({version})")
                    # Note: Skipped packages are now registered in audit_and_build_aur
                else:
                    failed_packages.append(aur_name)
                    
            except Exception as e:
                logger.error(f"❌ Error processing AUR package {aur_name}: {e}")
                failed_packages.append(aur_name)
        
        # Cleanup temporary AUR build directory
        try:
            if aur_build_dir.exists():
                shutil.rmtree(aur_build_dir, ignore_errors=True)
        except Exception:
            pass
        
        return built_packages, skipped_packages, failed_packages


# Helper function for easy integration
def create_package_builder(
    packager_id: str,
    output_dir: Path,
    gpg_key_id: Optional[str] = None,
    gpg_private_key: Optional[str] = None,
    sign_packages: bool = True,
    debug_mode: bool = False,
    version_tracker = None,  # Added: VersionTracker for skipped package registration
    vps_files: Optional[List[str]] = None,  # NEW: VPS file inventory for completeness check
    build_tracker = None  # NEW: BuildTracker for hokibot data
) -> PackageBuilder:
    """
    Create a PackageBuilder instance with all dependencies.
    
    Args:
        packager_id: Packager identity string
        output_dir: Directory for built packages
        gpg_key_id: GPG key ID for signing (optional)
        gpg_private_key: GPG private key (optional)
        sign_packages: Enable package signing
        debug_mode: Enable debug logging
        version_tracker: VersionTracker instance for tracking skipped packages
        vps_files: VPS file inventory for completeness check
        build_tracker: BuildTracker instance for hokibot data
        
    Returns:
        PackageBuilder instance
    """
    # Initialize version manager
    version_manager = VersionManager()
    
    # Initialize GPG handler
    gpg_handler = GPGHandler(sign_packages=sign_packages)
    if gpg_key_id:
        gpg_handler.gpg_key_id = gpg_key_id
    if gpg_private_key:
        gpg_handler.gpg_private_key = gpg_private_key
    
    # Create package builder
    return PackageBuilder(
        version_manager=version_manager,
        gpg_handler=gpg_handler,
        packager_id=packager_id,
        output_dir=output_dir,
        version_tracker=version_tracker,  # Pass version tracker
        debug_mode=debug_mode,
        vps_files=vps_files,  # NEW: Pass VPS file inventory
        build_tracker=build_tracker  # NEW: Pass build tracker
    )
