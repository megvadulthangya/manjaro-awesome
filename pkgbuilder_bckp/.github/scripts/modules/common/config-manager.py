"""
Centralized configuration manager for Manjaro Package Builder
Handles environment variables, config files, and default values with validation
"""

import os
import sys
import re
from pathlib import Path
from typing import Dict, Any, Optional, Union, List, Set
import logging

# Try to import config module if available
try:
    from modules.config import ConfigModule
    HAS_CONFIG_MODULE = True
except ImportError:
    # Create a dummy class for type hints
    class ConfigModule:
        pass
    HAS_CONFIG_MODULE = False


class ConfigManager:
    """
    Singleton configuration manager with priority logic:
    Environment Variables > config.py values > Default values
    """
    
    _instance = None
    _initialized = False
    
    # Default configuration values
    _DEFAULTS = {
        # Repository configuration
        'REPO_NAME': 'manjaro-awesome',
        'REPO_DB_NAME': 'manjaro-awesome',
        'OUTPUT_DIR': 'built_packages',
        'BUILD_TRACKING_DIR': '.build_tracking',
        
        # SSH and VPS configuration
        'SSH_REPO_URL': 'git@github.com:megvadulthangya/manjaro-awesome.git',
        'SSH_OPTIONS': ['-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=30', '-o', 'BatchMode=yes'],
        'VPS_HOST': '',
        'VPS_USER': '',
        'VPS_SSH_KEY': '',
        'REMOTE_DIR': '/var/www/repo',
        
        # Build configuration
        'PACKAGER_ID': 'Maintainer <no-reply@gshoots.hu>',
        'DEBUG_MODE': False,
        'DEFAULT_TIMEOUT': 1800,
        
        # Paths and directories
        'MIRROR_TEMP_DIR': '/tmp/repo_mirror',
        'SYNC_CLONE_DIR': '/tmp/manjaro-awesome-gitclone',
        'AUR_BUILD_DIR': 'build_aur',
        
        # AUR configuration
        'AUR_URLS': [
            'https://aur.archlinux.org/{pkg_name}.git',
            'git://aur.archlinux.org/{pkg_name}.git'
        ],
        
        # GitHub configuration
        'GITHUB_REPO': 'megvadulthangya/manjaro-awesome.git',
        
        # GPG configuration
        'GPG_KEY_ID': '',
        'GPG_PRIVATE_KEY': '',
        
        # Repository server
        'REPO_SERVER_URL': '',
        
        # Build timeouts
        'MAKEPKG_TIMEOUT': 3600,
        'LARGE_PACKAGE_TIMEOUT': 7200,
        'SIMPLESCREENRECORDER_TIMEOUT': 5400,
    }
    
    # Required configuration keys
    _REQUIRED_KEYS = {
        'VPS_HOST',
        'VPS_USER', 
        'VPS_SSH_KEY',
        'REPO_NAME',
        'REMOTE_DIR',
    }
    
    # Optional but recommended keys
    _RECOMMENDED_KEYS = {
        'REPO_SERVER_URL',
        'GPG_KEY_ID',
        'GPG_PRIVATE_KEY',
    }
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        if self._initialized:
            return
        
        self.logger = logger or logging.getLogger(__name__)
        self._config_cache: Dict[str, Any] = {}
        self._repo_root: Optional[Path] = None
        
        # Load configuration
        self._load_config()
        self._initialized = True
    
    def _load_config(self):
        """Load configuration from all sources"""
        self.logger.info("🔧 Loading configuration...")
        
        # Step 1: Load from environment variables
        env_config = self._load_from_environment()
        
        # Step 2: Load from config.py module
        config_module = self._load_from_config_module()
        
        # Step 3: Merge with defaults using priority
        self._merge_configurations(env_config, config_module)
        
        # Step 4: Post-process configuration
        self._post_process_config()
        
        # Step 5: Validate configuration
        self.validate()
    
    def _load_from_environment(self) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        env_config = {}
        
        # Map environment variable names to config keys
        env_mapping = {
            # VPS and SSH
            'VPS_HOST': 'VPS_HOST',
            'VPS_USER': 'VPS_USER',
            'VPS_SSH_KEY': 'VPS_SSH_KEY',
            'REMOTE_DIR': 'REMOTE_DIR',
            
            # Repository
            'REPO_NAME': 'REPO_NAME',
            'REPO_SERVER_URL': 'REPO_SERVER_URL',
            
            # GitHub
            'GITHUB_REPO': 'GITHUB_REPO',
            
            # GPG
            'GPG_KEY_ID': 'GPG_KEY_ID',
            'GPG_PRIVATE_KEY': 'GPG_PRIVATE_KEY',
            
            # Packager
            'PACKAGER_ENV': 'PACKAGER_ID',
            
            # CI/CD
            'CI_PUSH_SSH_KEY': 'CI_PUSH_SSH_KEY',
            'GITHUB_WORKSPACE': 'GITHUB_WORKSPACE',
        }
        
        for env_var, config_key in env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                env_config[config_key] = value
        
        # Handle boolean environment variables
        debug_env = os.getenv('DEBUG_MODE', '').lower()
        if debug_env in ('true', '1', 'yes', 'on'):
            env_config['DEBUG_MODE'] = True
        elif debug_env in ('false', '0', 'no', 'off'):
            env_config['DEBUG_MODE'] = False
        
        self.logger.debug(f"Loaded {len(env_config)} values from environment")
        return env_config
    
    def _load_from_config_module(self) -> Dict[str, Any]:
        """Load configuration from config.py module"""
        if not HAS_CONFIG_MODULE:
            return {}
        
        try:
            import config as config_module
            config_dict = {}
            
            # Extract all uppercase attributes from config module
            for attr_name in dir(config_module):
                if attr_name.isupper() and not attr_name.startswith('_'):
                    attr_value = getattr(config_module, attr_name)
                    config_dict[attr_name] = attr_value
            
            self.logger.debug(f"Loaded {len(config_dict)} values from config.py")
            return config_dict
            
        except Exception as e:
            self.logger.warning(f"Failed to load config.py: {e}")
            return {}
    
    def _merge_configurations(self, env_config: Dict[str, Any], config_module: Dict[str, Any]):
        """
        Merge configurations with priority:
        1. Environment variables (highest)
        2. config.py values (medium)
        3. Default values (lowest)
        """
        # Start with defaults
        self._config_cache = self._DEFAULTS.copy()
        
        # Apply config.py values (override defaults)
        for key, value in config_module.items():
            if key in self._config_cache:
                self._config_cache[key] = value
            else:
                # Warn about unrecognized config keys
                self.logger.warning(f"Unrecognized config key in config.py: {key}")
        
        # Apply environment variables (highest priority)
        for key, value in env_config.items():
            if key in self._config_cache:
                self._config_cache[key] = value
            else:
                # Allow new keys from environment
                self._config_cache[key] = value
        
        self.logger.info(f"Configuration merged: {len(self._config_cache)} keys")
    
    def _post_process_config(self):
        """Post-process configuration values"""
        # Convert string paths to Path objects
        path_keys = ['OUTPUT_DIR', 'BUILD_TRACKING_DIR', 'MIRROR_TEMP_DIR', 
                    'SYNC_CLONE_DIR', 'AUR_BUILD_DIR']
        
        for key in path_keys:
            if key in self._config_cache:
                value = self._config_cache[key]
                if isinstance(value, str):
                    self._config_cache[key] = Path(value)
        
        # Ensure SSH_OPTIONS is a list
        ssh_options = self._config_cache.get('SSH_OPTIONS', [])
        if isinstance(ssh_options, str):
            # Try to parse string representation of list
            try:
                import ast
                ssh_options = ast.literal_eval(ssh_options)
            except (SyntaxError, ValueError):
                # Fallback: split by spaces
                ssh_options = ssh_options.split()
        
        if not isinstance(ssh_options, list):
            ssh_options = []
        
        self._config_cache['SSH_OPTIONS'] = ssh_options
        
        # Ensure AUR_URLS is a list
        aur_urls = self._config_cache.get('AUR_URLS', [])
        if isinstance(aur_urls, str):
            try:
                import ast
                aur_urls = ast.literal_eval(aur_urls)
            except (SyntaxError, ValueError):
                aur_urls = [aur_urls]
        
        if not isinstance(aur_urls, list):
            aur_urls = []
        
        self._config_cache['AUR_URLS'] = aur_urls
        
        # Set GPG enabled flag
        gpg_key_id = self.get_str('GPG_KEY_ID')
        gpg_private_key = self.get_str('GPG_PRIVATE_KEY')
        self._config_cache['GPG_ENABLED'] = bool(gpg_key_id and gpg_private_key)
    
    def validate(self) -> bool:
        """
        Validate configuration
        
        Returns:
            True if configuration is valid
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("CONFIGURATION VALIDATION")
        self.logger.info("=" * 60)
        
        errors = []
        warnings = []
        
        # Check required keys
        for key in self._REQUIRED_KEYS:
            value = self._config_cache.get(key)
            if not value or (isinstance(value, str) and value.strip() == ''):
                errors.append(f"Required configuration key '{key}' is missing or empty")
        
        # Check recommended keys
        for key in self._RECOMMENDED_KEYS:
            value = self._config_cache.get(key)
            if not value or (isinstance(value, str) and value.strip() == ''):
                warnings.append(f"Recommended configuration key '{key}' is missing or empty")
        
        # Validate REPO_NAME format
        repo_name = self.get_str('REPO_NAME')
        if repo_name:
            if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
                errors.append(f"Invalid REPO_NAME '{repo_name}'. Must contain only letters, numbers, hyphens, and underscores.")
            if len(repo_name) > 50:
                errors.append(f"REPO_NAME '{repo_name}' is too long (max 50 characters).")
        
        # Validate paths exist (for directories that should exist)
        if self._repo_root:
            if not self._repo_root.exists():
                warnings.append(f"Repository root directory does not exist: {self._repo_root}")
        
        # Log results
        if errors:
            self.logger.error("❌ Configuration validation failed:")
            for error in errors:
                self.logger.error(f"  - {error}")
            return False
        
        if warnings:
            self.logger.warning("⚠️ Configuration warnings:")
            for warning in warnings:
                self.logger.warning(f"  - {warning}")
        
        self.logger.info("✅ Configuration validation passed")
        
        # Log configuration summary (without sensitive data)
        self.logger.info("📋 Configuration summary:")
        for key in sorted(self._config_cache.keys()):
            if key in ['VPS_SSH_KEY', 'GPG_PRIVATE_KEY', 'CI_PUSH_SSH_KEY']:
                self.logger.info(f"  {key}: [REDACTED]")
            elif key == 'SSH_OPTIONS':
                self.logger.info(f"  {key}: {len(self._config_cache[key])} options")
            elif key == 'AUR_URLS':
                self.logger.info(f"  {key}: {len(self._config_cache[key])} URLs")
            else:
                value = self._config_cache[key]
                if isinstance(value, Path):
                    self.logger.info(f"  {key}: {value}")
                elif isinstance(value, list):
                    self.logger.info(f"  {key}: [list of {len(value)} items]")
                elif isinstance(value, dict):
                    self.logger.info(f"  {key}: [dict with {len(value)} keys]")
                else:
                    self.logger.info(f"  {key}: {value}")
        
        return True
    
    # Type-safe getter methods
    
    def get_str(self, key: str, default: str = '') -> str:
        """Get configuration value as string"""
        value = self._config_cache.get(key, default)
        if value is None:
            return default
        return str(value)
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Get configuration value as integer"""
        value = self._config_cache.get(key, default)
        if value is None:
            return default
        
        try:
            return int(value)
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert '{key}' value '{value}' to integer, using default {default}")
            return default
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get configuration value as boolean"""
        value = self._config_cache.get(key, default)
        if value is None:
            return default
        
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            value_lower = value.lower()
            if value_lower in ('true', 'yes', '1', 'on', 'enabled'):
                return True
            elif value_lower in ('false', 'no', '0', 'off', 'disabled'):
                return False
        
        try:
            return bool(int(value))
        except (ValueError, TypeError):
            self.logger.warning(f"Could not convert '{key}' value '{value}' to boolean, using default {default}")
            return default
    
    def get_path(self, key: str, default: Optional[Path] = None) -> Path:
        """Get configuration value as Path object"""
        value = self._config_cache.get(key)
        
        if value is None:
            return default or Path()
        
        if isinstance(value, Path):
            return value
        
        if isinstance(value, str):
            return Path(value)
        
        self.logger.warning(f"Could not convert '{key}' value '{value}' to Path, using default")
        return default or Path()
    
    def get_list(self, key: str, default: Optional[List] = None) -> List:
        """Get configuration value as list"""
        value = self._config_cache.get(key, default or [])
        
        if value is None:
            return default or []
        
        if isinstance(value, list):
            return value
        
        # Try to convert string to list
        if isinstance(value, str):
            try:
                import ast
                return ast.literal_eval(value)
            except (SyntaxError, ValueError):
                # Fallback: split by commas
                return [item.strip() for item in value.split(',') if item.strip()]
        
        # Return as single-item list
        return [value]
    
    def get_dict(self, key: str, default: Optional[Dict] = None) -> Dict:
        """Get configuration value as dictionary"""
        value = self._config_cache.get(key, default or {})
        
        if value is None:
            return default or {}
        
        if isinstance(value, dict):
            return value
        
        self.logger.warning(f"Could not convert '{key}' value '{value}' to dict, using default")
        return default or {}
    
    def set_repo_root(self, repo_root: Path):
        """Set the repository root directory"""
        self._repo_root = repo_root.resolve()
        self.logger.info(f"Repository root set to: {self._repo_root}")
        
        # Update path configurations relative to repo root
        output_dir = self.get_path('OUTPUT_DIR')
        if not output_dir.is_absolute():
            self._config_cache['OUTPUT_DIR'] = self._repo_root / output_dir
        
        build_tracking_dir = self.get_path('BUILD_TRACKING_DIR')
        if not build_tracking_dir.is_absolute():
            self._config_cache['BUILD_TRACKING_DIR'] = self._repo_root / build_tracking_dir
        
        aur_build_dir = self.get_path('AUR_BUILD_DIR')
        if not aur_build_dir.is_absolute():
            self._config_cache['AUR_BUILD_DIR'] = self._repo_root / aur_build_dir
    
    def get_repo_root(self) -> Optional[Path]:
        """Get the repository root directory"""
        return self._repo_root
    
    def get_full_path(self, relative_path: Union[str, Path]) -> Path:
        """Get full path relative to repository root"""
        if self._repo_root is None:
            return Path(relative_path)
        
        return self._repo_root / Path(relative_path)
    
    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values (excluding sensitive data)"""
        # Create a copy without sensitive data
        safe_config = {}
        for key, value in self._config_cache.items():
            if key in ['VPS_SSH_KEY', 'GPG_PRIVATE_KEY', 'CI_PUSH_SSH_KEY']:
                safe_config[key] = '[REDACTED]'
            else:
                safe_config[key] = value
        
        return safe_config
    
    def is_set(self, key: str) -> bool:
        """Check if a configuration key is set (not None or empty string)"""
        value = self._config_cache.get(key)
        if value is None:
            return False
        
        if isinstance(value, str):
            return value.strip() != ''
        
        return True
    
    def override(self, key: str, value: Any):
        """Override a configuration value (for testing or runtime changes)"""
        old_value = self._config_cache.get(key)
        self._config_cache[key] = value
        self.logger.info(f"Configuration override: {key} = {value} (was: {old_value})")
    
    def reload(self):
        """Reload configuration from all sources"""
        self.logger.info("Reloading configuration...")
        self._config_cache.clear()
        self._load_config()