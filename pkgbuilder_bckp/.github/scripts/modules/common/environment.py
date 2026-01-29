"""
Environment validation and system path utilities
Extracted from PackageBuilder._validate_env and _get_repo_root
"""

import os
import re
import sys
import logging
from pathlib import Path
from typing import List, Tuple, Optional


class EnvironmentValidator:
    """Validates environment and provides system path utilities"""
    
    # Required environment variables
    REQUIRED_VARS = [
        'REPO_NAME',
        'VPS_HOST',
        'VPS_USER',
        'VPS_SSH_KEY',
        'REMOTE_DIR',
    ]
    
    # Optional but recommended variables
    OPTIONAL_VARS = [
        'REPO_SERVER_URL',
        'GPG_KEY_ID',
        'GPG_PRIVATE_KEY',
        'PACKAGER_ENV',
    ]
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize EnvironmentValidator
        
        Args:
            logger: Optional logger instance (creates one if not provided)
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def validate(self) -> bool:
        """
        Comprehensive pre-flight environment validation
        
        Returns:
            True if validation passed, False otherwise
        
        Note:
            Exits with sys.exit(1) on critical failures
        """
        self.logger.info("\n" + "=" * 60)
        self.logger.info("PRE-FLIGHT ENVIRONMENT VALIDATION")
        self.logger.info("=" * 60)
        
        # Check required variables
        missing_vars = []
        for var in self.REQUIRED_VARS:
            value = os.getenv(var)
            if not value or value.strip() == '':
                missing_vars.append(var)
                self.logger.error(f"[ERROR] Variable {var} is empty! Ensure it is set in GitHub Secrets.")
        
        if missing_vars:
            self.logger.error(f"Missing required variables: {', '.join(missing_vars)}")
            sys.exit(1)
        
        # Check optional variables and warn if missing
        for var in self.OPTIONAL_VARS:
            value = os.getenv(var)
            if not value or value.strip() == '':
                self.logger.warning(f"⚠️ Optional variable {var} is empty")
        
        # ✅ SECURITY FIX: DO NOT display secret information!
        self.logger.info("✅ Environment validation passed:")
        for var in self.REQUIRED_VARS + self.OPTIONAL_VARS:
            value = os.getenv(var)
            if value and value.strip() != '':
                self.logger.info(f"   {var}: [LOADED]")
            else:
                self.logger.info(f"   {var}: [MISSING]")
        
        # Validate REPO_NAME for pacman.conf
        repo_name = os.getenv('REPO_NAME')
        if repo_name:
            if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
                self.logger.error(f"[ERROR] Invalid REPO_NAME '{repo_name}'. Must contain only letters, numbers, hyphens, and underscores.")
                sys.exit(1)
            if len(repo_name) > 50:
                self.logger.error(f"[ERROR] REPO_NAME '{repo_name}' is too long (max 50 characters).")
                sys.exit(1)
        
        return True
    
    def get_repo_root(self) -> Path:
        """
        Get the repository root directory reliably
        
        Returns:
            Path to repository root
        """
        # Check GITHUB_WORKSPACE first (GitHub Actions)
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                self.logger.info(f"Using GITHUB_WORKSPACE: {workspace_path}")
                return workspace_path
        
        # Check container workspace (Docker/container specific)
        container_workspace = Path('/__w/manjaro-awesome/manjaro-awesome')
        if container_workspace.exists():
            self.logger.info(f"Using container workspace: {container_workspace}")
            return container_workspace
        
        # Get script directory and go up to repo root
        script_path = Path(__file__).resolve()
        
        # Navigate up: modules/common/environment.py -> modules/common -> modules -> scripts -> .github -> repo root
        # That's 6 levels up from this file
        potential_roots = [
            script_path.parent.parent.parent.parent.parent.parent,  # modules/common -> repo root
            script_path.parent.parent.parent.parent.parent,          # Alternative path
            Path.cwd(),                                              # Current directory
        ]
        
        for repo_root in potential_roots:
            if repo_root.exists():
                # Check for typical repository markers
                if (repo_root / '.github').exists() or (repo_root / 'README.md').exists():
                    self.logger.info(f"Using repository root: {repo_root}")
                    return repo_root
        
        # Fallback to current directory
        current_dir = Path.cwd()
        self.logger.info(f"Using current directory: {current_dir}")
        return current_dir
    
    def get_required_env(self, var_name: str, default: Optional[str] = None) -> str:
        """
        Get required environment variable
        
        Args:
            var_name: Environment variable name
            default: Default value (if not required)
        
        Returns:
            Environment variable value
        
        Raises:
            ValueError: If variable is not set and no default provided
        """
        value = os.getenv(var_name)
        if value is None or value.strip() == '':
            if default is not None:
                return default
            raise ValueError(f"Required environment variable {var_name} is not set")
        return value
    
    def get_optional_env(self, var_name: str, default: str = '') -> str:
        """
        Get optional environment variable
        
        Args:
            var_name: Environment variable name
            default: Default value if not set
        
        Returns:
            Environment variable value or default
        """
        value = os.getenv(var_name)
        if value is None or value.strip() == '':
            return default
        return value
    
    def validate_repo_name(self, repo_name: str) -> bool:
        """
        Validate repository name format
        
        Args:
            repo_name: Repository name to validate
        
        Returns:
            True if valid, False otherwise
        """
        if not repo_name:
            return False
        
        # Check format
        if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
            self.logger.error(f"Invalid REPO_NAME '{repo_name}'. Must contain only letters, numbers, hyphens, and underscores.")
            return False
        
        # Check length
        if len(repo_name) > 50:
            self.logger.error(f"REPO_NAME '{repo_name}' is too long (max 50 characters).")
            return False
        
        return True
    
    def check_environment(self) -> Tuple[bool, List[str]]:
        """
        Check environment without exiting
        
        Returns:
            Tuple of (is_valid, missing_vars)
        """
        missing_vars = []
        
        for var in self.REQUIRED_VARS:
            value = os.getenv(var)
            if not value or value.strip() == '':
                missing_vars.append(var)
        
        return (len(missing_vars) == 0, missing_vars)