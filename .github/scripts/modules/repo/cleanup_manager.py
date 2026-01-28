"""
Zero-Residue cleanup protocol and atomic path management
Ensures /tmp directories and sensitive build artifacts are securely removed
"""

import os
import shutil
import logging
import atexit
import signal
import tempfile
from pathlib import Path
from typing import List, Set, Optional, Dict, Any
from contextlib import contextmanager

from modules.repo.version_tracker import VersionTracker
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient


class CleanupManager:
    """Manages Zero-Residue cleanup operations with atomic path tracking"""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 version_tracker: Optional[VersionTracker] = None,
                 ssh_client: Optional[SSHClient] = None,
                 rsync_client: Optional[RsyncClient] = None,
                 logger: Optional[logging.Logger] = None):
        """
        Initialize CleanupManager with optional dependencies
        
        Args:
            config: Configuration dictionary (optional)
            version_tracker: VersionTracker instance (optional)
            ssh_client: SSHClient instance (optional)
            rsync_client: RsyncClient instance (optional)
            logger: Optional logger instance
        """
        self.config = config or {}
        self.version_tracker = version_tracker
        self.ssh_client = ssh_client
        self.rsync_client = rsync_client
        self.logger = logger or logging.getLogger(__name__)
        
        # Track temporary paths for zero-residue cleanup
        self._temp_paths: Set[Path] = set()
        self._temp_files: Set[Path] = set()
        
        # Register cleanup on exit
        self._register_exit_handlers()
        
        # Upload success flag for safety valve
        self._upload_successful = False
        
        self.logger.info("🧹 Zero-Residue CleanupManager initialized")
    
    def _register_exit_handlers(self):
        """Register cleanup handlers for exit signals"""
        # Register for normal exit
        atexit.register(self._atexit_cleanup)
        
        # Register for interrupt signals
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.debug("Exit handlers registered")
    
    def _atexit_cleanup(self):
        """Cleanup function called at exit"""
        if self._temp_paths or self._temp_files:
            self.logger.info("🔄 Performing automatic cleanup on exit...")
            self.perform_cleanup(force=True)
    
    def _signal_handler(self, signum, frame):
        """Handle interrupt signals"""
        self.logger.warning(f"🚨 Received signal {signum}, performing emergency cleanup...")
        self.perform_cleanup(force=True)
        exit(130 if signum == signal.SIGINT else 1)
    
    def register_temp_path(self, path: Path) -> bool:
        """
        Register a temporary path for automatic cleanup
        
        Args:
            path: Path to track (file or directory)
        
        Returns:
            True if path registered successfully
        """
        try:
            path = Path(path).resolve()
            
            # Only register paths that exist and are in temporary locations
            if not path.exists():
                self.logger.debug(f"Path does not exist, not registering: {path}")
                return False
            
            # Safety check: only register paths under /tmp or tempfile directories
            if not self._is_safe_temp_path(path):
                self.logger.warning(f"⚠️ Path not in safe temp location, skipping: {path}")
                return False
            
            if path.is_dir():
                self._temp_paths.add(path)
                self.logger.debug(f"📁 Registered temp directory: {path}")
            else:
                self._temp_files.add(path)
                self.logger.debug(f"📄 Registered temp file: {path}")
            
            return True
            
        except Exception as e:
            self.logger.warning(f"Failed to register temp path {path}: {e}")
            return False
    
    def _is_safe_temp_path(self, path: Path) -> bool:
        """
        Check if path is in a safe temporary location
        
        Args:
            path: Path to check
        
        Returns:
            True if path is in a safe temporary location
        """
        path_str = str(path)
        safe_patterns = [
            '/tmp/',
            tempfile.gettempdir(),
            '/var/tmp/',
        ]
        
        # Also check for project-specific temp directories
        if self.config:
            sync_clone_dir = self.config.get('sync_clone_dir', '')
            if sync_clone_dir and sync_clone_dir in path_str:
                return True
            
            mirror_temp_dir = self.config.get('mirror_temp_dir', '')
            if mirror_temp_dir and mirror_temp_dir in path_str:
                return True
        
        return any(pattern in path_str for pattern in safe_patterns if pattern)
    
    @contextmanager
    def temporary_directory(self, prefix: str = "builder_", suffix: str = "") -> Path:
        """
        Context manager for creating temporary directories with automatic cleanup
        
        Args:
            prefix: Directory name prefix
            suffix: Directory name suffix
        
        Yields:
            Path to created temporary directory
        """
        temp_dir = None
        try:
            temp_dir = Path(tempfile.mkdtemp(prefix=prefix, suffix=suffix))
            self.register_temp_path(temp_dir)
            self.logger.debug(f"📁 Created temporary directory: {temp_dir}")
            yield temp_dir
        finally:
            if temp_dir and temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    self._temp_paths.discard(temp_dir)
                    self.logger.debug(f"🧹 Cleaned temporary directory: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean temp dir {temp_dir}: {e}")
    
    @contextmanager
    def temporary_file(self, prefix: str = "builder_", suffix: str = ".tmp") -> Path:
        """
        Context manager for creating temporary files with automatic cleanup
        
        Args:
            prefix: File name prefix
            suffix: File name suffix
        
        Yields:
            Path to created temporary file
        """
        temp_file = None
        try:
            with tempfile.NamedTemporaryFile(prefix=prefix, suffix=suffix, delete=False) as f:
                temp_file = Path(f.name)
            self.register_temp_path(temp_file)
            self.logger.debug(f"📄 Created temporary file: {temp_file}")
            yield temp_file
        finally:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink(missing_ok=True)
                    self._temp_files.discard(temp_file)
                    self.logger.debug(f"🧹 Cleaned temporary file: {temp_file}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean temp file {temp_file}: {e}")
    
    def perform_cleanup(self, force: bool = False) -> Dict[str, int]:
        """
        Perform comprehensive zero-residue cleanup
        
        Args:
            force: If True, force cleanup even if upload was not successful
        
        Returns:
            Dictionary with cleanup statistics
        """
        if not force and not self._upload_successful:
            self.logger.warning("⚠️ Upload not marked successful, skipping cleanup for safety")
            return {'cleaned': 0, 'failed': 0}
        
        self.logger.info("🧹 Performing Zero-Residue cleanup...")
        
        stats = {
            'directories_cleaned': 0,
            'files_cleaned': 0,
            'directories_failed': 0,
            'files_failed': 0
        }
        
        # Clean temporary directories
        for temp_dir in list(self._temp_paths):
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    stats['directories_cleaned'] += 1
                    self.logger.debug(f"🧹 Cleaned directory: {temp_dir}")
                except Exception as e:
                    stats['directories_failed'] += 1
                    self.logger.warning(f"Failed to clean directory {temp_dir}: {e}")
            self._temp_paths.remove(temp_dir)
        
        # Clean temporary files
        for temp_file in list(self._temp_files):
            if temp_file.exists():
                try:
                    temp_file.unlink(missing_ok=True)
                    stats['files_cleaned'] += 1
                    self.logger.debug(f"🧹 Cleaned file: {temp_file}")
                except Exception as e:
                    stats['files_failed'] += 1
                    self.logger.warning(f"Failed to clean file {temp_file}: {e}")
            self._temp_files.remove(temp_file)
        
        # Clean SSH keys and agents if SSH client available
        if self.ssh_client:
            self._clean_ssh_resources()
        
        # Clean configuration-specific temp directories
        self._clean_config_temp_dirs()
        
        # Clear caches
        if self.version_tracker:
            self.version_tracker.clear_remote_inventory()
        
        # Report statistics
        total_cleaned = stats['directories_cleaned'] + stats['files_cleaned']
        total_failed = stats['directories_failed'] + stats['files_failed']
        
        if total_cleaned > 0:
            self.logger.info(f"✅ Zero-Residue cleanup: {total_cleaned} items cleaned")
        
        if total_failed > 0:
            self.logger.warning(f"⚠️ Cleanup failed for {total_failed} items")
        
        return stats
    
    def _clean_ssh_resources(self):
        """Clean SSH keys and agent resources"""
        try:
            # Clear SSH client cache
            if hasattr(self.ssh_client, 'clear_cache'):
                self.ssh_client.clear_cache()
            
            # Try to kill SSH agent if we started one
            ssh_auth_sock = os.environ.get('SSH_AUTH_SOCK')
            if ssh_auth_sock and os.path.exists(ssh_auth_sock):
                try:
                    # This is a socket file, not a regular file
                    os.unlink(ssh_auth_sock)
                    self.logger.debug("🧹 Cleaned SSH auth socket")
                except:
                    pass
            
            # Clean known SSH key files in /tmp
            for temp_dir in Path('/tmp').glob('git_ssh_*'):
                if temp_dir.is_dir():
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        self.logger.debug(f"🧹 Cleaned SSH temp dir: {temp_dir}")
                    except:
                        pass
            
            self.logger.debug("SSH resources cleaned")
            
        except Exception as e:
            self.logger.warning(f"Failed to clean SSH resources: {e}")
    
    def _clean_config_temp_dirs(self):
        """Clean configuration-specific temporary directories"""
        if not self.config:
            return
        
        temp_dirs = []
        
        # Add config-defined temp directories
        if 'sync_clone_dir' in self.config:
            temp_dirs.append(Path(self.config['sync_clone_dir']))
        
        if 'mirror_temp_dir' in self.config:
            temp_dirs.append(Path(self.config['mirror_temp_dir']))
        
        # Clean each directory
        for temp_dir in temp_dirs:
            if temp_dir.exists():
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    self.logger.debug(f"🧹 Cleaned config temp dir: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean config temp dir {temp_dir}: {e}")
    
    def set_upload_successful(self, successful: bool):
        """Set the upload success flag for safety valve"""
        self._upload_successful = successful
        if successful:
            self.logger.debug("✅ Upload marked successful, cleanup enabled")
        else:
            self.logger.warning("⚠️ Upload marked unsuccessful, cleanup disabled")
    
    def get_tracked_paths(self) -> Dict[str, List[str]]:
        """Get currently tracked temporary paths"""
        return {
            'directories': sorted([str(p) for p in self._temp_paths]),
            'files': sorted([str(p) for p in self._temp_files])
        }
    
    def clear_tracking(self):
        """Clear all tracked paths without cleaning them"""
        self._temp_paths.clear()
        self._temp_files.clear()
        self.logger.debug("🧹 Cleared path tracking (no cleanup performed)")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - always perform cleanup"""
        self.logger.debug("Context manager exiting, performing cleanup...")
        self.perform_cleanup(force=True)
        
        # Don't suppress exceptions
        return False
    
    # Legacy methods from original CleanupManager for backward compatibility
    
    def purge_old_local(self, pkg_name: str, old_version: str, target_version: Optional[str] = None):
        """
        🚨 ZERO-RESIDUE POLICY: Surgical old version removal BEFORE building
        
        Removes old versions from local output directory before new build.
        
        Args:
            pkg_name: Package name
            old_version: Version to potentially delete
            target_version: Version we want to keep (None if building new)
        """
        if not self.config:
            return
        
        # If we have a registered target version, use it
        if target_version is None and self.version_tracker:
            target_version = self.version_tracker.get_target_version(pkg_name)
        
        if target_version and old_version == target_version:
            # This is the version we want to keep
            self.logger.info(f"✅ No pre-build purge needed: {pkg_name} version {old_version} is target version")
            return
        
        # Delete old version from output directory
        self._delete_specific_version_local(pkg_name, old_version)
    
    def _delete_specific_version_local(self, pkg_name: str, version_to_delete: str):
        """Delete a specific version of a package from local output_dir"""
        if 'output_dir' not in self.config:
            return
        
        output_dir = Path(self.config['output_dir'])
        patterns = self._version_to_patterns(pkg_name, version_to_delete)
        deleted_count = 0
        
        for pattern in patterns:
            for old_file in output_dir.glob(pattern):
                try:
                    # Verify this is actually the version we want to delete
                    extracted_version = self._extract_version_from_filename(old_file.name, pkg_name)
                    if extracted_version == version_to_delete:
                        old_file.unlink()
                        self.logger.info(f"🗑️ Surgically removed local {old_file.name}")
                        deleted_count += 1
                        
                        # Also remove signature
                        sig_file = old_file.with_suffix(old_file.suffix + '.sig')
                        if sig_file.exists():
                            sig_file.unlink()
                            self.logger.info(f"🗑️ Removed local signature {sig_file.name}")
                except Exception as e:
                    self.logger.warning(f"Could not delete local {old_file}: {e}")
        
        if deleted_count > 0:
            self.logger.info(f"✅ Removed {deleted_count} local files for {pkg_name} version {version_to_delete}")
    
    def _version_to_patterns(self, pkg_name: str, version: str) -> List[str]:
        """Convert version string to filename patterns"""
        patterns = []
        
        if ':' in version:
            # Version with epoch: "2:26.1.9-1" -> "2-26.1.9-1-*.pkg.tar.*"
            epoch, rest = version.split(':', 1)
            patterns.append(f"{pkg_name}-{epoch}-{rest}-*.pkg.tar.*")
        else:
            # Standard version: "26.1.9-1" -> "*26.1.9-1-*.pkg.tar.*"
            patterns.append(f"{pkg_name}-{version}-*.pkg.tar.*")
        
        return patterns
    
    def _extract_version_from_filename(self, filename: str, pkg_name: str) -> Optional[str]:
        """
        Extract version from package filename
        
        Args:
            filename: Package filename (e.g., 'qownnotes-26.1.9-1-x86_64.pkg.tar.zst')
            pkg_name: Package name (e.g., 'qownnotes')
        
        Returns:
            Version string (e.g., '26.1.9-1') or None if cannot parse
        """
        try:
            # Remove extensions
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            
            # Find where package name ends
            for i in range(len(parts) - 2, 0, -1):
                possible_name = '-'.join(parts[:i])
                if possible_name == pkg_name or possible_name.startswith(pkg_name + '-'):
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
            self.logger.debug(f"Could not extract version from {filename}: {e}")
        
        return None