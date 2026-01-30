"""
Artifact Manager Module - Handles package file management and cleanup
"""

import shutil
import tarfile
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class ArtifactManager:
    """Handles package file management and workspace cleanup"""
    
    def clean_workspace(self, pkg_dir: Path):
        """Clean workspace before building to avoid contamination"""
        logger.info(f"🧹 Cleaning workspace for {pkg_dir.name}...")
        
        # Clean src/ directory if exists
        src_dir = pkg_dir / "src"
        if src_dir.exists():
            try:
                shutil.rmtree(src_dir, ignore_errors=True)
                logger.info(f"  Cleaned src/ directory")
            except Exception as e:
                logger.warning(f"  Could not clean src/: {e}")
        
        # Clean pkg/ directory if exists
        pkg_build_dir = pkg_dir / "pkg"
        if pkg_build_dir.exists():
            try:
                shutil.rmtree(pkg_build_dir, ignore_errors=True)
                logger.info(f"  Cleaned pkg/ directory")
            except Exception as e:
                logger.warning(f"  Could not clean pkg/: {e}")
        
        # Clean any leftover .tar.* files
        for leftover in pkg_dir.glob("*.pkg.tar.*"):
            try:
                leftover.unlink()
                logger.info(f"  Removed leftover package: {leftover.name}")
            except Exception as e:
                logger.warning(f"  Could not remove {leftover}: {e}")

    def create_artifact_archive(self, built_packages_path: Path, log_path: Path) -> Path:
        """
        Create a .tar.gz archive of built packages and logs to avoid colon (:) characters
        in filenames during GitHub upload.
        
        Args:
            built_packages_path: Path to directory containing built packages
            log_path: Path to log file
            
        Returns:
            Path to created archive file
        """
        logger.info("📦 Creating artifact archive to avoid colon character issues...")
        
        # Generate timestamp for archive name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"artifacts_{timestamp}.tar.gz"
        archive_path = built_packages_path.parent / archive_name
        
        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                # Add all built package files
                for pkg_file in built_packages_path.glob("*.pkg.tar.*"):
                    # Sanitize filename for tar (remove colon characters)
                    sanitized_name = pkg_file.name.replace(":", "_")
                    arcname = f"packages/{sanitized_name}"
                    tar.add(pkg_file, arcname=arcname)
                    logger.debug(f"Added to archive: {pkg_file.name} as {sanitized_name}")
                
                # Add log file if it exists
                if log_path.exists():
                    arcname = f"logs/{log_path.name}"
                    tar.add(log_path, arcname=arcname)
                    logger.debug(f"Added to archive: {log_path.name}")
                
                # Add repository database files if they exist
                for db_file in built_packages_path.glob("*.db*"):
                    arcname = f"databases/{db_file.name}"
                    tar.add(db_file, arcname=arcname)
                    logger.debug(f"Added to archive: {db_file.name}")
                
                for files_db in built_packages_path.glob("*.files*"):
                    arcname = f"databases/{files_db.name}"
                    tar.add(files_db, arcname=arcname)
                    logger.debug(f"Added to archive: {files_db.name}")
                
                # Add GPG signatures if they exist
                for sig_file in built_packages_path.glob("*.sig"):
                    arcname = f"signatures/{sig_file.name}"
                    tar.add(sig_file, arcname=arcname)
                    logger.debug(f"Added to archive: {sig_file.name}")
            
            # Verify archive was created
            if archive_path.exists():
                size_mb = archive_path.stat().st_size / (1024 * 1024)
                logger.info(f"✅ Created artifact archive: {archive_path.name} ({size_mb:.2f} MB)")
                
                # List contents for verification
                with tarfile.open(archive_path, "r:gz") as tar:
                    members = tar.getmembers()
                    logger.info(f"Archive contains {len(members)} files")
                    
                    # Group files by type for summary
                    packages = [m for m in members if m.name.startswith("packages/")]
                    logs = [m for m in members if m.name.startswith("logs/")]
                    databases = [m for m in members if m.name.startswith("databases/")]
                    signatures = [m for m in members if m.name.startswith("signatures/")]
                    
                    logger.info(f"  Packages: {len(packages)} files")
                    logger.info(f"  Logs: {len(logs)} files")
                    logger.info(f"  Databases: {len(databases)} files")
                    logger.info(f"  Signatures: {len(signatures)} files")
                
                # Clean up original files with colons after archiving
                self._cleanup_colon_files(built_packages_path)
                
                return archive_path
            else:
                logger.error("❌ Failed to create artifact archive")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error creating artifact archive: {e}")
            # Clean up partial archive if it exists
            if archive_path.exists():
                archive_path.unlink(missing_ok=True)
            return None
    
    def _cleanup_colon_files(self, directory: Path):
        """Remove files with colon characters after they've been archived"""
        logger.info("🧹 Cleaning up files with colon characters...")
        
        removed_count = 0
        for file_path in directory.glob("*.pkg.tar.*"):
            if ":" in file_path.name:
                try:
                    file_path.unlink(missing_ok=True)
                    removed_count += 1
                    logger.debug(f"Removed file with colon: {file_path.name}")
                except Exception as e:
                    logger.warning(f"Could not remove {file_path}: {e}")
        
        if removed_count > 0:
            logger.info(f"✅ Removed {removed_count} files with colon characters")