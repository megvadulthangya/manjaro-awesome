"""
Config Loader Module - Handles configuration loading and validation
"""

import os
import sys
from pathlib import Path


class ConfigLoader:
    """Handles configuration loading and validation"""
    
    @staticmethod
    def get_repo_root():
        """Get the repository root directory reliably"""
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                return workspace_path
        
        container_workspace = Path('/__w/manjaro-awesome/manjaro-awesome')
        if container_workspace.exists():
            return container_workspace
        
        # Get script directory and go up to repo root
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent.parent.parent
        if repo_root.exists():
            return repo_root
        
        return Path.cwd()
    
    @staticmethod
    def load_environment_config():
        """Load configuration from environment variables"""
        return {
            'vps_user': os.getenv('VPS_USER'),
            'vps_host': os.getenv('VPS_HOST'),
            'ssh_key': os.getenv('VPS_SSH_KEY'),
            'repo_server_url': os.getenv('REPO_SERVER_URL', ''),
            'remote_dir': os.getenv('REMOTE_DIR'),
            'repo_name': os.getenv('REPO_NAME'),
            'gpg_key_id': os.getenv('GPG_KEY_ID'),
            'gpg_private_key': os.getenv('GPG_PRIVATE_KEY'),
        }
    
    @staticmethod
    def load_from_python_config():
        """Load configuration from config.py if available"""
        try:
            import scripts.config as config_module
            return {
                'output_dir': getattr(config_module, 'OUTPUT_DIR', 'built_packages'),
                'build_tracking_dir': getattr(config_module, 'BUILD_TRACKING_DIR', '.build_tracking'),
                'mirror_temp_dir': getattr(config_module, 'MIRROR_TEMP_DIR', '/tmp/repo_mirror'),
                'sync_clone_dir': getattr(config_module, 'SYNC_CLONE_DIR', '/tmp/manjaro-awesome-gitclone'),
                'aur_urls': getattr(config_module, 'AUR_URLS', ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]),
                'aur_build_dir': getattr(config_module, 'AUR_BUILD_DIR', 'build_aur'),
                'ssh_options': getattr(config_module, 'SSH_OPTIONS', ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]),
                'github_repo': os.getenv('GITHUB_REPO', getattr(config_module, 'GITHUB_REPO', 'megvadulthangya/manjaro-awesome.git')),
                'packager_id': getattr(config_module, 'PACKAGER_ID', 'Maintainer <no-reply@gshoots.hu>'),
                'debug_mode': getattr(config_module, 'DEBUG_MODE', False),
                'sign_packages': getattr(config_module, 'SIGN_PACKAGES', True),
            }
        except ImportError:
            return {
                'output_dir': 'built_packages',
                'build_tracking_dir': '.build_tracking',
                'mirror_temp_dir': '/tmp/repo_mirror',
                'sync_clone_dir': '/tmp/manjaro-awesome-gitclone',
                'aur_urls': ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"],
                'aur_build_dir': 'build_aur',
                'ssh_options': ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"],
                'github_repo': 'megvadulthangya/manjaro-awesome.git',
                'packager_id': 'Maintainer <no-reply@gshoots.hu>',
                'debug_mode': False,
                'sign_packages': True,
            }
