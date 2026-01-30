"""
State Module - Manages application state and configuration
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class BuildState:
    """Represents the current build state"""
    repo_root: Path
    repo_name: str
    output_dir: Path
    build_tracking_dir: Path
    mirror_temp_dir: Path
    sync_clone_dir: Path
    aur_build_dir: Path
    packager_id: str
    debug_mode: bool
    
    # Remote state
    remote_files: List[str] = None
    repo_exists: bool = False
    has_packages: bool = False
    
    # Build results
    built_packages: List[str] = None
    skipped_packages: List[str] = None
    rebuilt_local_packages: List[str] = None
    
    def __post_init__(self):
        if self.remote_files is None:
            self.remote_files = []
        if self.built_packages is None:
            self.built_packages = []
        if self.skipped_packages is None:
            self.skipped_packages = []
        if self.rebuilt_local_packages is None:
            self.rebuilt_local_packages = []
    
    def add_remote_file(self, filename: str):
        """Add a remote file to the state"""
        self.remote_files.append(filename)
    
    def add_built_package(self, pkg_name: str, version: str):
        """Add a built package to the state"""
        self.built_packages.append(f"{pkg_name} ({version})")
    
    def add_skipped_package(self, pkg_name: str, version: str):
        """Add a skipped package to the state"""
        self.skipped_packages.append(f"{pkg_name} ({version})")
    
    def add_rebuilt_local_package(self, pkg_name: str):
        """Add a rebuilt local package to the state"""
        self.rebuilt_local_packages.append(pkg_name)