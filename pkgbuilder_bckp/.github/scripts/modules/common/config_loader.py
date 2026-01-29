"""
Configuration loading from environment, config files, and package definitions
Extracted from PackageBuilder._load_config and get_package_lists
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import logging


class ConfigLoader:
    """
    Loads configuration from environment variables, config files,
    and package definitions
    """
    
    def __init__(self, repo_root: Path, logger: Optional[logging.Logger] = None):
        """
        Initialize ConfigLoader
        
        Args:
            repo_root: Repository root directory
            logger: Optional logger instance
        """
        self.repo_root = repo_root
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize config state
        self._config_cache: Dict[str, Any] = {}
        self._packages_cache: Optional[Tuple[List[str], List[str]]] = None
        
        # Try to import config files
        self.has_config_files = self._try_import_config()
    
    def _try_import_config(self) -> bool:
        """Try to import config and packages modules"""
        try:
            # Add the script directory to sys.path for imports
            script_dir = self.repo_root / ".github" / "scripts"
            if script_dir.exists():
                sys.path.insert(0, str(script_dir))
            
            # Try to import config
            try:
                import config
                self._config_cache['config_module'] = config
                self.logger.debug("✅ Config module imported")
            except ImportError:
                self.logger.warning("⚠️ Could not import config module")
                self._config_cache['config_module'] = None
            
            # Try to import packages
            try:
                import packages
                self._config_cache['packages_module'] = packages
                self.logger.debug("✅ Packages module imported")
            except ImportError:
                self.logger.warning("⚠️ Could not import packages module")
                self._config_cache['packages_module'] = None
            
            return bool(self._config_cache.get('config_module'))
            
        except Exception as e:
            self.logger.warning(f"⚠️ Error importing config files: {e}")
            return False
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from environment and config files
        
        Returns:
            Dictionary with configuration values
        """
        config = {}
        
        # Required environment variables (secrets)
        config['vps_user'] = os.getenv('VPS_USER', '')
        config['vps_host'] = os.getenv('VPS_HOST', '')
        config['ssh_key'] = os.getenv('VPS_SSH_KEY', '')
        
        # Optional environment variables (overrides)
        config['repo_server_url'] = os.getenv('REPO_SERVER_URL', '')
        config['remote_dir'] = os.getenv('REMOTE_DIR', '')
        
        # Repository name from environment
        config['repo_name'] = os.getenv('REPO_NAME', '')
        
        # Load from config.py if available
        if self.has_config_files and self._config_cache.get('config_module'):
            config_module = self._config_cache['config_module']
            
            # Directories
            config['output_dir'] = getattr(config_module, 'OUTPUT_DIR', 'built_packages')
            config['build_tracking_dir'] = getattr(config_module, 'BUILD_TRACKING_DIR', '.build_tracking')
            config['mirror_temp_dir'] = Path(getattr(config_module, 'MIRROR_TEMP_DIR', '/tmp/repo_mirror'))
            config['sync_clone_dir'] = Path(getattr(config_module, 'SYNC_CLONE_DIR', '/tmp/manjaro-awesome-gitclone'))
            config['aur_build_dir'] = self.repo_root / getattr(config_module, 'AUR_BUILD_DIR', 'build_aur')
            
            # AUR and SSH
            config['aur_urls'] = getattr(config_module, 'AUR_URLS', [
                "https://aur.archlinux.org/{pkg_name}.git",
                "git://aur.archlinux.org/{pkg_name}.git"
            ])
            config['ssh_options'] = getattr(config_module, 'SSH_OPTIONS', [
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=30",
                "-o", "BatchMode=yes"
            ])
            
            # GitHub and packager
            config['github_repo'] = os.getenv('GITHUB_REPO', 
                                            getattr(config_module, 'GITHUB_REPO', 'megvadulthangya/manjaro-awesome.git'))
            config['packager_id'] = getattr(config_module, 'PACKAGER_ID', 'Maintainer <no-reply@gshoots.hu>')
            
            # Debug mode
            config['debug_mode'] = getattr(config_module, 'DEBUG_MODE', False)
        else:
            # Default values if config.py not available
            config['output_dir'] = 'built_packages'
            config['build_tracking_dir'] = '.build_tracking'
            config['mirror_temp_dir'] = Path('/tmp/repo_mirror')
            config['sync_clone_dir'] = Path('/tmp/manjaro-awesome-gitclone')
            config['aur_build_dir'] = self.repo_root / 'build_aur'
            config['aur_urls'] = [
                "https://aur.archlinux.org/{pkg_name}.git",
                "git://aur.archlinux.org/{pkg_name}.git"
            ]
            config['ssh_options'] = [
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=30",
                "-o", "BatchMode=yes"
            ]
            config['github_repo'] = os.getenv('GITHUB_REPO', 'megvadulthangya/manjaro-awesome.git')
            config['packager_id'] = 'Maintainer <no-reply@gshoots.hu>'
            config['debug_mode'] = False
        
        # Convert string paths to Path objects
        config['output_dir'] = self.repo_root / config['output_dir']
        config['build_tracking_dir'] = self.repo_root / config['build_tracking_dir']
        
        # Log configuration (without secrets)
        self.logger.info("🔧 Configuration loaded:")
        self.logger.info(f"   SSH user: {config['vps_user']}")
        self.logger.info(f"   VPS host: {config['vps_host']}")
        self.logger.info(f"   Remote directory: {config['remote_dir']}")
        self.logger.info(f"   Repository name: {config['repo_name']}")
        if config['repo_server_url']:
            self.logger.info(f"   Repository URL: {config['repo_server_url']}")
        self.logger.info(f"   Config files loaded: {self.has_config_files}")
        self.logger.info(f"   Debug mode: {config['debug_mode']}")
        
        return config
    
    def get_package_lists(self) -> Tuple[List[str], List[str]]:
        """
        Get package lists from packages.py or exit if not available
        
        Returns:
            Tuple of (local_packages_list, aur_packages_list)
        
        Raises:
            SystemExit: If package lists cannot be loaded
        """
        if self._packages_cache is not None:
            return self._packages_cache
        
        packages_module = self._config_cache.get('packages_module')
        
        if packages_module and hasattr(packages_module, 'LOCAL_PACKAGES') and hasattr(packages_module, 'AUR_PACKAGES'):
            self.logger.info("📦 Using package lists from packages.py")
            local_packages_list = packages_module.LOCAL_PACKAGES
            aur_packages_list = packages_module.AUR_PACKAGES
            
            total_packages = len(local_packages_list) + len(aur_packages_list)
            self.logger.debug(f">>> DEBUG: Found {total_packages} packages to check")
            
            self._packages_cache = (local_packages_list, aur_packages_list)
            return self._packages_cache
        else:
            self.logger.error("❌ Cannot load package lists from packages.py")
            self.logger.error("Please ensure packages.py exists and contains LOCAL_PACKAGES and AUR_PACKAGES lists")
            sys.exit(1)
    
    def get_packager_id(self) -> str:
        """
        Get PACKAGER_ID from config or environment
        
        Returns:
            PACKAGER_ID string
        """
        # Try environment variable first
        packager_env = os.getenv('PACKAGER_ENV')
        if packager_env:
            return packager_env
        
        # Fall back to config
        if self.has_config_files and self._config_cache.get('config_module'):
            config_module = self._config_cache['config_module']
            return getattr(config_module, 'PACKAGER_ID', 'Maintainer <no-reply@gshoots.hu>')
        
        return 'Maintainer <no-reply@gshoots.hu>'
    
    def get_config_value(self, key: str, default: Any = None) -> Any:
        """
        Get a specific configuration value
        
        Args:
            key: Configuration key
            default: Default value if key not found
        
        Returns:
            Configuration value or default
        """
        # Try config module first
        if self.has_config_files and self._config_cache.get('config_module'):
            config_module = self._config_cache['config_module']
            if hasattr(config_module, key):
                return getattr(config_module, key)
        
        # Fall back to environment
        env_value = os.getenv(key.upper())
        if env_value is not None:
            return env_value
        
        return default