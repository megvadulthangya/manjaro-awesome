import os
import subprocess
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
import logging

# Import required modules
from modules.repo.manifest_factory import ManifestFactory
from modules.gpg.gpg_handler import GPGHandler
from modules.build.version_manager import VersionManager

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
        debug_mode: bool = False
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
        """
        self.version_manager = version_manager
        self.gpg_handler = gpg_handler
        self.packager_id = packager_id
        self.output_dir = output_dir
        self.version_tracker = version_tracker  # Store version tracker
        self.debug_mode = debug_mode
        
        # Ensure output directory exists
        self.output_dir.mkdir(exist_ok=True, parents=True)
    
    def audit_and_build_local(
        self,
        pkg_dir: Path,
        remote_version: Optional[str],
        skip_check: bool = False
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, str]]]:
        """
        Audit and build local package.
        
        Args:
            pkg_dir: Path to local package directory
            remote_version: Current version on mirror (None if not exists)
            skip_check: Skip version check and force build (for testing)
            
        Returns:
            Tuple of (built: bool, built_version: str, metadata: dict)
        """
        logger.info(f"🔍 Auditing local package: {pkg_dir.name}")
        
        # Step 1: Extract version from PKGBUILD
        try:
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(pkg_dir)
            source_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            logger.info(f"📦 Source version: {source_version}")
            logger.info(f"📦 Remote version: {remote_version or 'Not found'}")
        except Exception as e:
            logger.error(f"❌ Failed to extract version from {pkg_dir}: {e}")
            return False, None, None
        
        # Step 2: Version comparison (skip if forced)
        if not skip_check and remote_version:
            should_build = self.version_manager.compare_versions(
                remote_version, pkgver, pkgrel, epoch
            )
            if not should_build:
                logger.info(f"✅ {pkg_dir.name}: Up to date ({remote_version})")
                # REGISTER SKIPPED PACKAGE
                self.version_tracker.register_skipped_package(pkg_dir.name, remote_version)
                return False, source_version, {
                    "pkgver": pkgver,
                    "pkgrel": pkgrel,
                    "epoch": epoch
                }
        
        # Step 3: Build package
        logger.info(f"🔨 Building {pkg_dir.name} ({source_version})...")
        built = self._build_local_package(pkg_dir, source_version)
        
        if built:
            # Step 4: Sign the built package immediately
            self._sign_new_packages(pkg_dir.name, source_version)
            
            return True, source_version, {
                "pkgver": pkgver,
                "pkgrel": pkgrel,
                "epoch": epoch
            }
        
        return False, source_version, None
    
    def audit_and_build_aur(
        self,
        aur_package_name: str,
        remote_version: Optional[str],
        aur_build_dir: Path,
        skip_check: bool = False
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, str]]]:
        """
        Audit and build AUR package.
        
        Args:
            aur_package_name: AUR package name
            remote_version: Current version on mirror (None if not exists)
            aur_build_dir: Directory for AUR builds
            skip_check: Skip version check and force build (for testing)
            
        Returns:
            Tuple of (built: bool, built_version: str, metadata: dict)
        """
        logger.info(f"🔍 Auditing AUR package: {aur_package_name}")
        
        # Step 1: Clone AUR package
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp(prefix=f"aur_{aur_package_name}_")
            temp_path = Path(temp_dir)
            
            # Clone AUR package
            clone_success = self._clone_aur_package(aur_package_name, temp_path)
            if not clone_success:
                logger.error(f"❌ Failed to clone AUR package: {aur_package_name}")
                return False, None, None
            
            # Step 2: Extract version from PKGBUILD
            pkgver, pkgrel, epoch = self.version_manager.extract_version_from_srcinfo(temp_path)
            source_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)
            
            logger.info(f"📦 AUR source version: {source_version}")
            logger.info(f"📦 Remote version: {remote_version or 'Not found'}")
            
            # Step 3: Version comparison (skip if forced)
            if not skip_check and remote_version:
                should_build = self.version_manager.compare_versions(
                    remote_version, pkgver, pkgrel, epoch
                )
                if not should_build:
                    logger.info(f"✅ {aur_package_name}: Up to date ({remote_version})")
                    # REGISTER SKIPPED PACKAGE
                    self.version_tracker.register_skipped_package(aur_package_name, remote_version)
                    return False, source_version, {
                        "pkgver": pkgver,
                        "pkgrel": pkgrel,
                        "epoch": epoch
                    }
            
            # Step 4: Build package
            logger.info(f"🔨 Building AUR {aur_package_name} ({source_version})...")
            built = self._build_aur_package(temp_path, aur_package_name, source_version)
            
            if built:
                # Step 5: Sign the built package immediately
                self._sign_new_packages(aur_package_name, source_version)
                
                return True, source_version, {
                    "pkgver": pkgver,
                    "pkgrel": pkgrel,
                    "epoch": epoch
                }
            
            return False, source_version, None
            
        except Exception as e:
            logger.error(f"❌ Error building AUR package {aur_package_name}: {e}")
            return False, None, None
        finally:
            # Cleanup temporary directory
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    def _clone_aur_package(self, pkg_name: str, target_dir: Path) -> bool:
        """Clone AUR package from Arch Linux AUR."""
        # Try different AUR URLs
        aur_urls = [
            f"https://aur.archlinux.org/{pkg_name}.git",
            f"git://aur.archlinux.org/{pkg_name}.git"
        ]
        
        for aur_url in aur_urls:
            try:
                logger.info(f"📥 Cloning {pkg_name} from {aur_url}")
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", aur_url, str(target_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=300
                )
                
                if result.returncode == 0:
                    logger.info(f"✅ Successfully cloned {pkg_name}")
                    return True
                else:
                    logger.warning(f"⚠️ Failed to clone from {aur_url}: {result.stderr}")
            except Exception as e:
                logger.warning(f"⚠️ Error cloning from {aur_url}: {e}")
        
        logger.error(f"❌ Failed to clone {pkg_name} from any AUR URL")
        return False
    
    def _build_local_package(self, pkg_dir: Path, version: str) -> bool:
        """Build local package using makepkg."""
        try:
            # Clean workspace
            self._clean_workspace(pkg_dir)
            
            # Prepare environment
            env = os.environ.copy()
            env["PACKAGER"] = self.packager_id
            
            # Download sources
            logger.info("   Downloading sources...")
            download_result = subprocess.run(
                ["makepkg", "-od", "--noconfirm"],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=600
            )
            
            if download_result.returncode != 0:
                logger.error(f"❌ Failed to download sources: {download_result.stderr[:500]}")
                return False
            
            # Build package
            logger.info("   Building package...")
            build_flags = "-si --noconfirm --clean"
            if pkg_dir.name == "gtk2":
                build_flags += " --nocheck"
                logger.info("   Skipping check for gtk2 (long)")
            
            build_result = subprocess.run(
                ["makepkg"] + build_flags.split(),
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=3600
            )
            
            if build_result.returncode != 0:
                logger.error(f"❌ Build failed: {build_result.stderr[:500]}")
                return False
            
            # Move built packages to output directory
            moved = self._move_built_packages(pkg_dir, pkg_dir.name, version)
            
            if moved:
                logger.info(f"✅ Successfully built {pkg_dir.name}")
                return True
            else:
                logger.error(f"❌ No package files created for {pkg_dir.name}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Build timed out for {pkg_dir.name}")
            return False
        except Exception as e:
            logger.error(f"❌ Error building {pkg_dir.name}: {e}")
            return False
    
    def _build_aur_package(self, pkg_dir: Path, pkg_name: str, version: str) -> bool:
        """Build AUR package using makepkg."""
        try:
            # Clean workspace
            self._clean_workspace(pkg_dir)
            
            # Prepare environment
            env = os.environ.copy()
            env["PACKAGER"] = self.packager_id
            
            # Download sources
            logger.info("   Downloading sources...")
            download_result = subprocess.run(
                ["makepkg", "-od", "--noconfirm"],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=600
            )
            
            if download_result.returncode != 0:
                logger.error(f"❌ Failed to download sources: {download_result.stderr[:500]}")
                return False
            
            # Build package
            logger.info("   Building package...")
            build_result = subprocess.run(
                ["makepkg", "-si", "--noconfirm", "--clean", "--nocheck"],
                cwd=pkg_dir,
                capture_output=True,
                text=True,
                env=env,
                check=False,
                timeout=3600
            )
            
            if build_result.returncode != 0:
                logger.error(f"❌ Build failed: {build_result.stderr[:500]}")
                return False
            
            # Move built packages to output directory
            moved = self._move_built_packages(pkg_dir, pkg_name, version)
            
            if moved:
                logger.info(f"✅ Successfully built AUR {pkg_name}")
                return True
            else:
                logger.error(f"❌ No package files created for {pkg_name}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"❌ Build timed out for {pkg_name}")
            return False
        except Exception as e:
            logger.error(f"❌ Error building {pkg_name}: {e}")
            return False
    
    def _clean_workspace(self, pkg_dir: Path):
        """Clean workspace before building."""
        # Clean src/ directory
        src_dir = pkg_dir / "src"
        if src_dir.exists():
            shutil.rmtree(src_dir, ignore_errors=True)
        
        # Clean pkg/ directory
        pkg_build_dir = pkg_dir / "pkg"
        if pkg_build_dir.exists():
            shutil.rmtree(pkg_build_dir, ignore_errors=True)
        
        # Clean leftover package files
        for leftover in pkg_dir.glob("*.pkg.tar.*"):
            leftover.unlink(missing_ok=True)
    
    def _move_built_packages(self, source_dir: Path, pkg_name: str, version: str) -> bool:
        """Move built packages to output directory."""
        moved = False
        
        for pkg_file in source_dir.glob("*.pkg.tar.*"):
            dest = self.output_dir / pkg_file.name
            try:
                shutil.move(str(pkg_file), str(dest))
                logger.info(f"   Moved: {pkg_file.name}")
                moved = True
            except Exception as e:
                logger.error(f"   Failed to move {pkg_file.name}: {e}")
        
        return moved
    
    def _sign_new_packages(self, pkg_name: str, version: str):
        """Sign newly built packages using gpg_handler."""
        logger.info(f"🔐 Signing new packages for {pkg_name}...")
        
        # Find package files for this version
        signed_count = 0
        for pkg_file in self.output_dir.glob("*.pkg.tar.*"):
            # Check if this file belongs to our package
            if pkg_name in pkg_file.name and version.replace(':', '-') in pkg_file.name:
                if self.gpg_handler.sign_package(str(pkg_file)):
                    signed_count += 1
                    logger.info(f"✅ Signed: {pkg_file.name}")
                else:
                    logger.error(f"❌ Failed to sign: {pkg_file.name}")
        
        if signed_count > 0:
            logger.info(f"✅ Signed {signed_count} packages for {pkg_name}")
        else:
            logger.warning(f"⚠️ No packages signed for {pkg_name}")
    
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
                built, version, metadata = self.audit_and_build_local(
                    pkg_dir, remote_version
                )
                
                if built:
                    built_packages.append(f"{pkg_dir.name} ({version})")
                    # Register target version for cleanup
                    self.version_tracker.register_package_target_version(pkg_dir.name, version)
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
                built, version, metadata = self.audit_and_build_aur(
                    aur_name, remote_version, aur_build_dir
                )
                
                if built:
                    built_packages.append(f"{aur_name} ({version})")
                    # Register target version for cleanup
                    self.version_tracker.register_package_target_version(aur_name, version)
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
    version_tracker = None  # Added: VersionTracker for skipped package registration
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
        debug_mode=debug_mode
    )
