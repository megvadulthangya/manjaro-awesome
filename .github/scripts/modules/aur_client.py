"""
AUR RPC API Client - Fetch package metadata without cloning
"""

import requests
import logging
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


class AURClient:
    """AUR RPC API client for metadata-based package comparison"""
    
    def __init__(self):
        self.base_url = "https://aur.archlinux.org/rpc/?v=5"
        
    def get_package_info(self, package_name: str) -> Optional[Dict]:
        """
        Fetch package info from AUR RPC API
        
        Args:
            package_name: Package name
            
        Returns:
            Dictionary with package info or None if not found
        """
        url = f"{self.base_url}&type=info&arg[]={package_name}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if data.get("resultcount", 0) > 0:
                package_info = data["results"][0]
                
                # Convert LastModified timestamp to datetime
                if "LastModified" in package_info:
                    try:
                        last_modified = int(package_info["LastModified"])
                        package_info["LastModified"] = datetime.fromtimestamp(last_modified)
                    except (ValueError, TypeError):
                        package_info["LastModified"] = None
                
                logger.debug(f"✅ Fetched AUR metadata for {package_name}: {package_info.get('Version')}")
                return package_info
            else:
                logger.warning(f"⚠️ AUR package not found: {package_name}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ AUR RPC request failed for {package_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching AUR info for {package_name}: {e}")
            return None
    
    def get_package_version(self, package_name: str) -> Optional[str]:
        """
        Get current version of an AUR package
        
        Args:
            package_name: Package name
            
        Returns:
            Version string or None
        """
        info = self.get_package_info(package_name)
        if info:
            return info.get("Version")
        return None
    
    def get_multiple_packages(self, package_names: List[str]) -> Dict[str, Dict]:
        """
        Fetch multiple packages in a single request
        
        Args:
            package_names: List of package names
            
        Returns:
            Dictionary mapping package name to info
        """
        if not package_names:
            return {}
        
        # AUR RPC accepts multiple args
        args = "&".join([f"arg[]={pkg}" for pkg in package_names])
        url = f"{self.base_url}&type=info&{args}"
        
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()
            
            results = {}
            for package_info in data.get("results", []):
                pkg_name = package_info.get("Name")
                if pkg_name:
                    results[pkg_name] = package_info
            
            logger.info(f"✅ Fetched metadata for {len(results)}/{len(package_names)} AUR packages")
            return results
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ AUR RPC bulk request failed: {e}")
            return {}
    
    def is_update_available(self, package_name: str, current_version: str) -> bool:
        """
        Check if an update is available for an AUR package
        
        Args:
            package_name: Package name
            current_version: Current version string (from state)
            
        Returns:
            True if AUR version > current version
        """
        aur_info = self.get_package_info(package_name)
        if not aur_info:
            logger.warning(f"⚠️ Could not fetch AUR info for {package_name}")
            return False
        
        aur_version = aur_info.get("Version")
        if not aur_version:
            return False
        
        # Simple version comparison (for demonstration)
        # In production, use vercmp or similar
        try:
            # Parse versions (simplified)
            def parse_version(v):
                # Remove epoch if present
                if ':' in v:
                    v = v.split(':', 1)[1]
                return v
            
            current_clean = parse_version(current_version)
            aur_clean = parse_version(aur_version)
            
            if current_clean != aur_clean:
                logger.info(f"ℹ️ {package_name}: State {current_version} vs AUR {aur_version}")
                # Assume newer if different (simplified)
                # In reality, use proper version comparison
                return True
            else:
                logger.debug(f"✅ {package_name}: Up to date ({current_version})")
                return False
                
        except Exception as e:
            logger.error(f"❌ Version comparison failed for {package_name}: {e}")
            return False