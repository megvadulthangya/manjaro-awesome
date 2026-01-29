"""
Artifact Manager for handling build artifacts
Handles sanitization, staging, and file organization
"""

import shutil
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

class ArtifactManager:
    """Manages build artifacts and staging"""

    def __init__(self, config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initialize ArtifactManager
        
        Args:
            config: Configuration dictionary
            logger: Optional logger instance
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        
        self.output_dir = Path(config.get('output_dir', 'built_packages'))
        self._sanitized_files: Dict[str, str] = {}

    def get_sanitized_map(self) -> Dict[str, str]:
        """Get map of original to sanitized filenames"""
        return self._sanitized_files

    def sanitize_artifacts(self, pkg_name: str) -> List[Path]:
        """
        Sanitize artifact filenames (replace ':' with '_')
        
        Args:
            pkg_name: Package name to scan for
            
        Returns:
            List of paths to sanitized artifacts
        """
        self.logger.info(f"🔧 Sanitizing artifacts for {pkg_name}...")
        
        sanitized_files = []
        patterns = [f"*{pkg_name}*.pkg.tar.*", f"{pkg_name}*.pkg.tar.*"]
        
        for pattern in patterns:
            for pkg_file in self.output_dir.glob(pattern):
                original_name = pkg_file.name
                
                if ':' in original_name:
                    sanitized_name = original_name.replace(':', '_')
                    sanitized_path = pkg_file.with_name(sanitized_name)
                    
                    try:
                        pkg_file.rename(sanitized_path)
                        self.logger.info(f"  🔄 Renamed: {original_name} -> {sanitized_name}")
                        
                        self._sanitized_files[str(pkg_file)] = str(sanitized_path)
                        
                        sig_file = pkg_file.with_suffix(pkg_file.suffix + '.sig')
                        if sig_file.exists():
                            sanitized_sig = sanitized_path.with_suffix(sanitized_path.suffix + '.sig')
                            sig_file.rename(sanitized_sig)
                            self.logger.info(f"  🔄 Renamed signature: {sig_file.name} -> {sanitized_sig.name}")
                        
                        sanitized_files.append(sanitized_path)
                    except Exception as e:
                        self.logger.error(f"Failed to rename {original_name}: {e}")
                        sanitized_files.append(pkg_file)
                else:
                    sanitized_files.append(pkg_file)
        
        self.logger.info(f"✅ Sanitized {len(sanitized_files)} files for {pkg_name}")
        return sanitized_files

    def move_to_staging(self, staging_dir: Path) -> List[Path]:
        """
        Move all new packages from output_dir to staging_dir
        
        Args:
            staging_dir: Destination staging directory
            
        Returns:
            List of paths in staging directory
        """
        new_packages = list(self.output_dir.glob("*.pkg.tar.zst"))
        if not new_packages:
            self.logger.info("ℹ️ No new packages to move to staging")
            return []
        
        self.logger.info(f"📦 Moving {len(new_packages)} new packages to staging...")
        
        moved_packages = []
        
        for new_pkg in new_packages:
            try:
                dest = staging_dir / new_pkg.name
                if dest.exists():
                    dest.unlink()
                shutil.move(str(new_pkg), str(dest))
                moved_packages.append(dest)
                
                # Move signature if exists
                sig_file = new_pkg.with_suffix(new_pkg.suffix + '.sig')
                if sig_file.exists():
                    sig_dest = dest.with_suffix(dest.suffix + '.sig')
                    if sig_dest.exists():
                        sig_dest.unlink()
                    shutil.move(str(sig_file), str(sig_dest))
                
                self.logger.debug(f"  Moved: {new_pkg.name}")
            except Exception as e:
                self.logger.error(f"Failed to move {new_pkg.name}: {e}")
        
        self.logger.info(f"✅ Moved {len(moved_packages)} new packages to staging")
        return moved_packages