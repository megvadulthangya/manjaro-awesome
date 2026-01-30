"""
Configuration loader module
Loads configuration from config.py and environment variables
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import config
script_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(script_dir))

try:
    import config
    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False
    print("⚠️ Warning: Could not import config.py")

def load_config():
    """Load configuration from config.py and environment variables"""
    if not HAS_CONFIG:
        raise RuntimeError("config.py not found")
    
    # Return a dictionary with all configuration
    config_dict = {
        # VPS configuration
        'vps_user': config.VPS_USER,
        'vps_host': config.VPS_HOST,
        'ssh_key': config.VPS_SSH_KEY,
        'remote_dir': config.REMOTE_DIR,
        
        # Repository configuration
        'repo_name': config.REPO_NAME,
        'repo_server_url': config.REPO_SERVER_URL,
        
        # Build configuration
        'output_dir': config.OUTPUT_DIR,
        'build_tracking_dir': config.BUILD_TRACKING_DIR,
        'aur_urls': config.AUR_URLS,
        'aur_build_dir': config.AUR_BUILD_DIR,
        'mirror_temp_dir': config.MIRROR_TEMP_DIR,
        'sync_clone_dir': config.SYNC_CLONE_DIR,
        'ssh_options': config.SSH_OPTIONS,
        
        # GPG configuration
        'gpg_key_id': config.GPG_KEY_ID,
        'gpg_private_key': config.GPG_PRIVATE_KEY,
        
        # Other configuration
        'packager_id': config.PACKAGER_ID,
        'debug_mode': config.DEBUG_MODE,
        
        # Special configurations
        'makepkg_timeout': config.MAKEPKG_TIMEOUT,
        'special_dependencies': config.SPECIAL_DEPENDENCIES,
        'required_build_tools': config.REQUIRED_BUILD_TOOLS,
    }
    
    # Validate required configuration
    required_configs = ['vps_user', 'vps_host', 'remote_dir', 'repo_name']
    for req in required_configs:
        if not config_dict.get(req):
            print(f"❌ Missing required configuration: {req}")
            sys.exit(1)
    
    return config_dict