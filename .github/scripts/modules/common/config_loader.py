"""
Configuration loader
Strictly loads configuration from config.py and merges with environment variables.
NO default paths or business logic allowed here.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional

class ConfigLoader:
    """
    Loads configuration from config module.
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
        self._config_cache: Dict[str, Any] = {}

    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from config.py
        
        Returns:
            Dictionary with configuration values
        """
        config_dict = {}
        
        # Add script directory to sys.path to find config.py
        script_dir = self.repo_root / ".github" / "scripts"
        if script_dir.exists():
            sys.path.insert(0, str(script_dir))
            
        try:
            import config
            
            # Map config module attributes to dict
            # We explicitly map known keys to ensure structure
            
            # Repository
            config_dict['repo_name'] = getattr(config, 'REPO_NAME', '')
            config_dict['repo_db_name'] = getattr(config, 'REPO_DB_NAME', '')
            config_dict['github_repo'] = getattr(config, 'GITHUB_REPO', '')
            
            # Paths
            config_dict['output_dir'] = self.repo_root / getattr(config, 'OUTPUT_DIR', 'built_packages')
            config_dict['build_tracking_dir'] = self.repo_root / getattr(config, 'BUILD_TRACKING_DIR', '.build_tracking')
            config_dict['aur_build_dir'] = self.repo_root / getattr(config, 'AUR_BUILD_DIR', 'build_aur')
            config_dict['mirror_temp_dir'] = Path(getattr(config, 'MIRROR_TEMP_DIR', '/tmp/repo_mirror'))
            config_dict['sync_clone_dir'] = Path(getattr(config, 'SYNC_CLONE_DIR', '/tmp/repo_gitclone'))
            config_dict['repo_root'] = self.repo_root
            
            # Secrets / Env
            config_dict['vps_user'] = getattr(config, 'VPS_USER', '')
            config_dict['vps_host'] = getattr(config, 'VPS_HOST', '')
            config_dict['vps_ssh_key'] = getattr(config, 'VPS_SSH_KEY', '')
            config_dict['remote_dir'] = getattr(config, 'REMOTE_DIR', '')
            config_dict['ci_push_ssh_key'] = getattr(config, 'CI_PUSH_SSH_KEY', '')
            config_dict['ssh_repo_url'] = getattr(config, 'SSH_REPO_URL', '')
            
            # GPG
            config_dict['gpg_private_key'] = getattr(config, 'GPG_PRIVATE_KEY', '')
            config_dict['gpg_key_id'] = getattr(config, 'GPG_KEY_ID', '')
            
            # Identity
            config_dict['packager_env'] = getattr(config, 'PACKAGER_ID', '')
            config_dict['packager_id'] = getattr(config, 'PACKAGER_ID', '') # Alias
            
            # Build Settings
            config_dict['ssh_options'] = getattr(config, 'SSH_OPTIONS', [])
            config_dict['aur_urls'] = getattr(config, 'AUR_URLS', [])
            config_dict['makepkg_timeout'] = getattr(config, 'MAKEPKG_TIMEOUT', {})
            config_dict['debug_mode'] = getattr(config, 'DEBUG_MODE', False)
            
            self.logger.info("🔧 Configuration loaded from config.py")
            self.logger.debug(f"Repo Name: {config_dict['repo_name']}")
            self.logger.debug(f"Remote Dir: {config_dict['remote_dir']}")
            
            return config_dict
            
        except ImportError as e:
            self.logger.error(f"❌ Could not import config.py: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"❌ Error loading config: {e}")
            sys.exit(1)

    def get_package_lists(self) -> Any:
        """
        Get package lists from packages.py
        """
        try:
            import packages
            return packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
        except ImportError:
            self.logger.error("❌ Could not import packages.py")
            sys.exit(1)