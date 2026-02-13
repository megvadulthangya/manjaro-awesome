"""
Config Loader Module - Handles configuration loading and validation
"""

import os
import sys
import logging
from pathlib import Path


logger = logging.getLogger(__name__)


class ConfigLoader:
    """Handles configuration loading and validation"""
    
    @staticmethod
    def _is_valid_repo_root(path: Path) -> bool:
        """
        Validate candidate repository root by checking for expected project markers.
        Conservative validation – at least one of the following must exist:
          - .github/scripts/builder.py
          - .github/scripts/packages.py
          - .git
        """
        if not path or not path.is_dir():
            return False
        
        # Prefer the explicit .github/scripts markers because the pipeline depends on that layout
        if (path / ".github" / "scripts" / "builder.py").exists():
            return True
        if (path / ".github" / "scripts" / "packages.py").exists():
            return True
        if (path / ".git").exists():
            return True
        
        return False
    
    @staticmethod
    def get_repo_root():
        """
        Get the repository root directory using a robust, validated resolution order.
        
        Resolution order:
        1. GITHUB_WORKSPACE environment variable (if set and path exists and passes validation)
        2. Current working directory (if it passes validation)
        3. Derive from __file__ location (4 levels up) (if it passes validation)
        4. Raise RuntimeError if no valid root found
        
        Returns:
            Path object representing the validated repository root.
        
        Raises:
            RuntimeError: if no valid repository root can be determined.
        """
        # --- 1) GITHUB_WORKSPACE ---
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            candidate = Path(github_workspace)
            if ConfigLoader._is_valid_repo_root(candidate):
                logger.info(f"REPO_ROOT_RESOLVED method=GITHUB_WORKSPACE path={candidate}")
                return candidate
            else:
                logger.debug(f"REPO_ROOT_REJECTED method=GITHUB_WORKSPACE path={candidate}")
        
        # --- 2) Current working directory ---
        candidate = Path.cwd()
        if ConfigLoader._is_valid_repo_root(candidate):
            logger.info(f"REPO_ROOT_RESOLVED method=CWD path={candidate}")
            return candidate
        else:
            logger.debug(f"REPO_ROOT_REJECTED method=CWD path={candidate}")
        
        # --- 3) Derive from script location (4 levels up) ---
        script_path = Path(__file__).resolve()
        candidate = script_path.parent.parent.parent.parent
        if ConfigLoader._is_valid_repo_root(candidate):
            logger.info(f"REPO_ROOT_RESOLVED method=SCRIPT_DERIVE path={candidate}")
            return candidate
        else:
            logger.debug(f"REPO_ROOT_REJECTED method=SCRIPT_DERIVE path={candidate}")
        
        # --- 4) No valid root found ---
        raise RuntimeError(
            "Cannot determine repository root. "
            "Please either:\n"
            "  - Set the GITHUB_WORKSPACE environment variable to the repository path, or\n"
            "  - Run the script from within the repository root (or a subdirectory).\n"
            "No candidate path passed validation checks (missing .github/scripts markers or .git)."
        )
    
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
        """
        Load configuration from config.py if available, with strict packager identity resolution.

        Packager identity precedence (highest to lowest):
        1. Environment variable PACKAGER_ENV
        2. Environment variable PACKAGER (legacy compatibility)
        3. config_module.PACKAGER_ID (optional local override)
        4. If still empty:
           - In GitHub Actions (GITHUB_ACTIONS == "true" or GITHUB_WORKSPACE set): raise RuntimeError
           - Else (local development): use neutral placeholder "Local Builder <builder@localhost>" and log a warning.
        """
        # Step 1: Determine packager identity and source
        packager_id = None
        source = None

        # a) env PACKAGER_ENV (preferred)
        if os.getenv('PACKAGER_ENV'):
            packager_id = os.getenv('PACKAGER_ENV')
            source = 'PACKAGER_ENV'
        # b) env PACKAGER (secondary compatibility)
        elif os.getenv('PACKAGER'):
            packager_id = os.getenv('PACKAGER')
            source = 'PACKAGER (legacy)'
        else:
            # c) config_module.PACKAGER_ID (optional local override)
            try:
                import scripts.config as config_module
                config_packager = getattr(config_module, 'PACKAGER_ID', None)
                if config_packager:
                    packager_id = config_packager
                    source = 'config.py'
            except ImportError:
                pass

        # d) if still empty, check GitHub Actions vs local dev
        if packager_id is None:
            in_github = os.getenv('GITHUB_ACTIONS') == 'true' or os.getenv('GITHUB_WORKSPACE') is not None
            if in_github:
                raise RuntimeError(
                    "PACKAGER_ENV secret must be set in GitHub Actions to define packager identity. "
                    "Please add the PACKAGER_ENV secret with a value like 'Your Name <email>'."
                )
            else:
                packager_id = "Local Builder <builder@localhost>"
                source = 'local development placeholder'
                logger.warning("PACKAGER_ENV not set, using local development placeholder: %s", packager_id)

        logger.info(f"PACKAGER_ID_SOURCE={source}")

        # Step 2: Build base configuration dictionary from config.py (if available)
        try:
            import scripts.config as config_module
            config_dict = {
                'output_dir': getattr(config_module, 'OUTPUT_DIR', 'built_packages'),
                'build_tracking_dir': getattr(config_module, 'BUILD_TRACKING_DIR', '.build_tracking'),
                'mirror_temp_dir': getattr(config_module, 'MIRROR_TEMP_DIR', '/tmp/repo_mirror'),
                'sync_clone_dir': getattr(config_module, 'SYNC_CLONE_DIR', '/tmp/repo-builder-gitclone'),
                'aur_urls': getattr(config_module, 'AUR_URLS', ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"]),
                'aur_build_dir': getattr(config_module, 'AUR_BUILD_DIR', 'build_aur'),
                'ssh_options': getattr(config_module, 'SSH_OPTIONS', ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]),
                'github_repo': os.getenv('GITHUB_REPOSITORY', getattr(config_module, 'GITHUB_REPO', '')),
                'debug_mode': getattr(config_module, 'DEBUG_MODE', False),
                'sign_packages': getattr(config_module, 'SIGN_PACKAGES', True),
            }
        except ImportError:
            # Fallback defaults when config.py is missing
            config_dict = {
                'output_dir': 'built_packages',
                'build_tracking_dir': '.build_tracking',
                'mirror_temp_dir': '/tmp/repo_mirror',
                'sync_clone_dir': '/tmp/repo-builder-gitclone',
                'aur_urls': ["https://aur.archlinux.org/{pkg_name}.git", "git://aur.archlinux.org/{pkg_name}.git"],
                'aur_build_dir': 'build_aur',
                'ssh_options': ["-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"],
                'github_repo': os.getenv('GITHUB_REPOSITORY', ''),
                'debug_mode': False,
                'sign_packages': True,
            }

        # Step 3: Override the packager_id with our computed value (no hardcoded maintainer defaults)
        config_dict['packager_id'] = packager_id

        return config_dict