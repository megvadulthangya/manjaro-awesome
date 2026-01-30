"""
Artifact Manager Module - Handles package file management and cleanup
"""

import shutil
import logging
from pathlib import Path

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