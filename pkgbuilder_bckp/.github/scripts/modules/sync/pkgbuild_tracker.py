"""
PKGBUILD change tracking and version management module
Handles hashing, version extraction, and build state persistence
"""

import os
import re
import json
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime


class PkgbuildTracker:
    """Tracks PKGBUILD changes, versions, and build state"""
    
    def __init__(self, tracking_dir: Path, logger: Optional[logging.Logger] = None):
        """
        Initialize PkgbuildTracker
        
        Args:
            tracking_dir: Directory to store tracking JSON files
            logger: Optional logger instance
        """
        self.tracking_dir = tracking_dir
        self.logger = logger or logging.getLogger(__name__)
        
        # Ensure tracking directory exists
        self.tracking_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache for tracking data
        self._tracking_cache: Dict[str, Dict[str, Any]] = {}
    
    def get_pkgbuild_hash(self, pkgbuild_path: Path) -> str:
        """
        Calculate SHA256 hash of PKGBUILD file
        
        Args:
            pkgbuild_path: Path to PKGBUILD file
        
        Returns:
            SHA256 hash as hex string, empty string if file doesn't exist
        """
        if not pkgbuild_path.exists():
            self.logger.warning(f"PKGBUILD not found: {pkgbuild_path}")
            return ""
        
        try:
            with open(pkgbuild_path, 'rb') as f:
                file_hash = hashlib.sha256()
                chunk = f.read(8192)
                while chunk:
                    file_hash.update(chunk)
                    chunk = f.read(8192)
                return file_hash.hexdigest()
        except Exception as e:
            self.logger.error(f"Failed to calculate hash for {pkgbuild_path}: {e}")
            return ""
    
    def load_tracking_data(self, pkg_name: str) -> Dict[str, Any]:
        """
        Load tracking data for a package from JSON file
        
        Args:
            pkg_name: Package name
        
        Returns:
            Dictionary with tracking data or empty dict if not found
        """
        # Check cache first
        if pkg_name in self._tracking_cache:
            return self._tracking_cache[pkg_name].copy()
        
        tracking_file = self.tracking_dir / f"{pkg_name}.json"
        
        if not tracking_file.exists():
            return {}
        
        try:
            with open(tracking_file, 'r') as f:
                data = json.load(f)
            
            # Cache the data
            self._tracking_cache[pkg_name] = data.copy()
            
            self.logger.debug(f"Loaded tracking data for {pkg_name}")
            return data
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in {tracking_file}: {e}")
            return {}
        except Exception as e:
            self.logger.error(f"Failed to load tracking data for {pkg_name}: {e}")
            return {}
    
    def save_tracking_data(self, pkg_name: str, data: Dict[str, Any]) -> bool:
        """
        Save tracking data for a package to JSON file
        
        Args:
            pkg_name: Package name
            data: Tracking data to save
        
        Returns:
            True if successful
        """
        tracking_file = self.tracking_dir / f"{pkg_name}.json"
        
        try:
            # Ensure data has required timestamp
            if 'last_updated' not in data:
                data['last_updated'] = datetime.now().isoformat()
            
            # Add creation timestamp if it's new
            if 'created' not in data:
                data['created'] = datetime.now().isoformat()
            
            with open(tracking_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Update cache
            self._tracking_cache[pkg_name] = data.copy()
            
            self.logger.debug(f"Saved tracking data for {pkg_name}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to save tracking data for {pkg_name}: {e}")
            return False
    
    def extract_version_from_pkgbuild(self, pkg_dir: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Extract version information from PKGBUILD file
        
        Args:
            pkg_dir: Package directory containing PKGBUILD
        
        Returns:
            Tuple of (pkgver, pkgrel, epoch) or (None, None, None) if failed
        """
        pkgbuild_path = pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            self.logger.error(f"PKGBUILD not found: {pkgbuild_path}")
            return None, None, None
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            # Regex patterns for extracting version information
            patterns = {
                'pkgver': r'pkgver\s*=\s*["\']?([^"\'\s#]+)',
                'pkgrel': r'pkgrel\s*=\s*["\']?([^"\'\s#]+)',
                'epoch': r'epoch\s*=\s*["\']?([^"\'\s#]+)'
            }
            
            results = {}
            for key, pattern in patterns.items():
                match = re.search(pattern, content)
                if match:
                    results[key] = match.group(1)
                else:
                    # Check for VCS-style pkgver patterns
                    if key == 'pkgver':
                        # Try alternative patterns for git packages
                        git_patterns = [
                            r'_commit\s*=\s*["\']?([^"\'\s#]+)',
                            r'pkgver\s*=\s*\$\{?_commit\}?',
                            r'pkgver\s*=\s*\$\{pkgver_prefix\}',
                        ]
                        for git_pattern in git_patterns:
                            git_match = re.search(git_pattern, content)
                            if git_match and 'group' in dir(git_match):
                                results[key] = git_match.group(1) or 'git'
                                break
            
            pkgver = results.get('pkgver')
            pkgrel = results.get('pkgrel', '1')
            epoch = results.get('epoch')
            
            if pkgver:
                self.logger.debug(f"Extracted version from {pkg_dir.name}: pkgver={pkgver}, pkgrel={pkgrel}, epoch={epoch}")
                return pkgver, pkgrel, epoch
            else:
                self.logger.warning(f"Could not extract pkgver from {pkg_dir.name}")
                return None, None, None
                
        except Exception as e:
            self.logger.error(f"Error extracting version from {pkg_dir}: {e}")
            return None, None, None
    
    def has_changed(self, pkg_name: str, pkg_dir: Path) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if PKGBUILD has changed since last build
        
        Args:
            pkg_name: Package name
            pkg_dir: Package directory containing PKGBUILD
        
        Returns:
            Tuple of (has_changed, tracking_data)
        """
        # Load existing tracking data
        tracking_data = self.load_tracking_data(pkg_name)
        
        # Get current PKGBUILD path
        pkgbuild_path = pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            self.logger.error(f"PKGBUILD not found for {pkg_name}: {pkgbuild_path}")
            return False, tracking_data
        
        # Calculate current hash
        current_hash = self.get_pkgbuild_hash(pkgbuild_path)
        if not current_hash:
            self.logger.error(f"Failed to calculate hash for {pkg_name}")
            return False, tracking_data
        
        # Extract current version
        current_pkgver, current_pkgrel, current_epoch = self.extract_version_from_pkgbuild(pkg_dir)
        if not current_pkgver:
            self.logger.error(f"Failed to extract version for {pkg_name}")
            return False, tracking_data
        
        current_version = f"{current_pkgver}-{current_pkgrel}"
        if current_epoch and current_epoch != '0':
            current_version = f"{current_epoch}:{current_version}"
        
        # Check if this is a new package
        if not tracking_data:
            self.logger.info(f"🆕 First tracking for {pkg_name}")
            new_data = {
                'last_hash': current_hash,
                'last_version': current_version,
                'last_build': datetime.now().isoformat(),
                'pkgver': current_pkgver,
                'pkgrel': current_pkgrel,
                'epoch': current_epoch,
                'build_count': 1
            }
            return True, new_data
        
        # Check if PKGBUILD has changed (hash comparison)
        last_hash = tracking_data.get('last_hash', '')
        last_version = tracking_data.get('last_version', '')
        
        if current_hash != last_hash:
            self.logger.info(f"🔀 PKGBUILD changed for {pkg_name} (hash mismatch)")
            
            # Update tracking data
            build_count = tracking_data.get('build_count', 0) + 1
            new_data = {
                'last_hash': current_hash,
                'last_version': current_version,
                'last_build': datetime.now().isoformat(),
                'pkgver': current_pkgver,
                'pkgrel': current_pkgrel,
                'epoch': current_epoch,
                'previous_hash': last_hash,
                'previous_version': last_version,
                'build_count': build_count
            }
            
            # Preserve any additional metadata
            for key in ['created', 'first_build', 'notes']:
                if key in tracking_data:
                    new_data[key] = tracking_data[key]
            
            return True, new_data
        
        # Check if version has changed (in case hash is same but version updated elsewhere)
        if current_version != last_version:
            self.logger.info(f"🔀 Version changed for {pkg_name}: {last_version} -> {current_version}")
            
            build_count = tracking_data.get('build_count', 0) + 1
            new_data = {
                'last_hash': current_hash,
                'last_version': current_version,
                'last_build': datetime.now().isoformat(),
                'pkgver': current_pkgver,
                'pkgrel': current_pkgrel,
                'epoch': current_epoch,
                'previous_version': last_version,
                'build_count': build_count
            }
            
            # Preserve metadata
            for key in ['created', 'first_build', 'notes']:
                if key in tracking_data:
                    new_data[key] = tracking_data[key]
            
            return True, new_data
        
        # No changes detected
        self.logger.debug(f"✅ {pkg_name} unchanged (hash: {current_hash[:8]}..., version: {current_version})")
        return False, tracking_data
    
    def register_build(self, pkg_name: str, pkg_dir: Path, success: bool = True, 
                      error_message: Optional[str] = None) -> bool:
        """
        Register a build attempt in tracking data
        
        Args:
            pkg_name: Package name
            pkg_dir: Package directory
            success: Whether build was successful
            error_message: Optional error message if build failed
        
        Returns:
            True if registration successful
        """
        # Get current version info
        pkgver, pkgrel, epoch = self.extract_version_from_pkgbuild(pkg_dir)
        if not pkgver:
            return False
        
        # Load existing data
        tracking_data = self.load_tracking_data(pkg_name)
        
        # Update build information
        timestamp = datetime.now().isoformat()
        
        if success:
            tracking_data.update({
                'last_successful_build': timestamp,
                'last_build_status': 'success',
                'last_build_pkgver': pkgver,
                'last_build_pkgrel': pkgrel,
                'last_build_epoch': epoch
            })
            
            # Increment success count
            success_count = tracking_data.get('success_count', 0) + 1
            tracking_data['success_count'] = success_count
        else:
            tracking_data.update({
                'last_failed_build': timestamp,
                'last_build_status': 'failed',
                'last_build_error': error_message
            })
            
            # Increment failure count
            failure_count = tracking_data.get('failure_count', 0) + 1
            tracking_data['failure_count'] = failure_count
        
        # Update build history
        build_history = tracking_data.get('build_history', [])
        build_history.append({
            'timestamp': timestamp,
            'status': 'success' if success else 'failed',
            'pkgver': pkgver,
            'pkgrel': pkgrel,
            'epoch': epoch,
            'error': error_message
        })
        
        # Keep only last 20 builds in history
        tracking_data['build_history'] = build_history[-20:]
        
        # Save updated data
        return self.save_tracking_data(pkg_name, tracking_data)
    
    def get_build_stats(self, pkg_name: str) -> Dict[str, Any]:
        """
        Get build statistics for a package
        
        Args:
            pkg_name: Package name
        
        Returns:
            Dictionary with build statistics
        """
        tracking_data = self.load_tracking_data(pkg_name)
        
        if not tracking_data:
            return {
                'package': pkg_name,
                'status': 'unknown',
                'build_count': 0,
                'success_count': 0,
                'failure_count': 0
            }
        
        stats = {
            'package': pkg_name,
            'status': tracking_data.get('last_build_status', 'unknown'),
            'build_count': tracking_data.get('build_count', 0),
            'success_count': tracking_data.get('success_count', 0),
            'failure_count': tracking_data.get('failure_count', 0),
            'last_build': tracking_data.get('last_build'),
            'last_version': tracking_data.get('last_version'),
            'current_hash': tracking_data.get('last_hash', '')[:16] + '...'
        }
        
        # Calculate success rate if we have builds
        total_builds = stats['success_count'] + stats['failure_count']
        if total_builds > 0:
            stats['success_rate'] = (stats['success_count'] / total_builds) * 100
        else:
            stats['success_rate'] = 0
        
        return stats
    
    def get_all_tracking_data(self) -> Dict[str, Dict[str, Any]]:
        """
        Get tracking data for all packages
        
        Returns:
            Dictionary of all tracking data
        """
        all_data = {}
        
        for json_file in self.tracking_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                pkg_name = json_file.stem
                all_data[pkg_name] = data
                
            except Exception as e:
                self.logger.warning(f"Failed to load {json_file}: {e}")
        
        return all_data
    
    def clear_cache(self):
        """Clear the tracking cache"""
        self._tracking_cache.clear()
        self.logger.debug("Cleared tracking cache")
    
    def cleanup_old_entries(self, max_age_days: int = 30) -> int:
        """
        Remove old tracking entries
        
        Args:
            max_age_days: Maximum age in days to keep
        
        Returns:
            Number of entries removed
        """
        removed_count = 0
        cutoff_date = datetime.now().timestamp() - (max_age_days * 24 * 60 * 60)
        
        for json_file in self.tracking_dir.glob("*.json"):
            try:
                file_mtime = json_file.stat().st_mtime
                
                if file_mtime < cutoff_date:
                    # Load data to check if package is still relevant
                    with open(json_file, 'r') as f:
                        data = json.load(f)
                    
                    # Don't remove if it has recent build history
                    last_build = data.get('last_build')
                    if last_build:
                        try:
                            last_build_date = datetime.fromisoformat(last_build.replace('Z', '+00:00'))
                            if last_build_date.timestamp() > cutoff_date:
                                continue
                        except ValueError:
                            # If date parsing fails, keep the file to be safe
                            continue
                    
                    # Remove the file
                    json_file.unlink()
                    
                    # Remove from cache
                    pkg_name = json_file.stem
                    self._tracking_cache.pop(pkg_name, None)
                    
                    removed_count += 1
                    self.logger.debug(f"Removed old tracking entry: {pkg_name}")
                    
            except Exception as e:
                self.logger.warning(f"Failed to process {json_file} for cleanup: {e}")
        
        if removed_count > 0:
            self.logger.info(f"Cleaned up {removed_count} old tracking entries")
        
        return removed_count