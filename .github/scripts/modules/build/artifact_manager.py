"""
Artifact manager - handles package files and artifacts
"""

import shutil
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class ArtifactManager:
    """Manages package artifacts and files"""
    
    def __init__(self, output_dir, debug_mode=False):
        self.output_dir = Path(output_dir)
        self.debug_mode = debug_mode
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(exist_ok=True)
    
    def move_built_packages(self, source_dir, package_name):
        """Move built packages from source directory to output directory"""
        moved_files = []
        
        for pkg_file in Path(source_dir).glob("*.pkg.tar.*"):
            dest = self.output_dir / pkg_file.name
            shutil.move(str(pkg_file), str(dest))
            
            if self.debug_mode:
                print(f"🔧 [DEBUG] Moved package: {pkg_file.name} -> {dest}", flush=True)
            else:
                logger.info(f"Moved package: {pkg_file.name}")
            
            moved_files.append(str(dest))
        
        return moved_files
    
    def cleanup_directory(self, directory):
        """Clean up a directory"""
        try:
            if Path(directory).exists():
                shutil.rmtree(directory, ignore_errors=True)
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Cleaned directory: {directory}", flush=True)
                else:
                    logger.info(f"Cleaned directory: {directory}")
        except Exception as e:
            if self.debug_mode:
                print(f"🔧 [DEBUG] Failed to clean directory {directory}: {e}", flush=True)
            else:
                logger.warning(f"Failed to clean directory {directory}: {e}")
    
    def get_local_packages(self):
        """Get all package files from local output directory"""
        return list(self.output_dir.glob("*.pkg.tar.*"))