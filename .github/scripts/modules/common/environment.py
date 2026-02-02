"""
Environment Module - Handles environment validation and setup
"""

import os
import sys
import re
import logging

logger = logging.getLogger(__name__)


class EnvironmentValidator:
    """Handles environment validation and setup"""
    
    @staticmethod
    def validate_env() -> None:
        """Comprehensive pre-flight environment validation - check for all required variables"""
        print("\n" + "=" * 60)
        print("PRE-FLIGHT ENVIRONMENT VALIDATION")
        print("=" * 60)
        
        required_vars = [
            'REPO_NAME',
            'VPS_HOST',
            'VPS_USER',
            'VPS_SSH_KEY',
            'REMOTE_DIR',
        ]
        
        optional_but_recommended = [
            'REPO_SERVER_URL',
            'GPG_KEY_ID',
            'GPG_PRIVATE_KEY',
            'PACKAGER_ENV',
        ]
        
        # Check required variables
        missing_vars = []
        for var in required_vars:
            value = os.getenv(var)
            if not value or value.strip() == '':
                missing_vars.append(var)
                logger.error(f"[ERROR] Variable {var} is empty! Ensure it is set in GitHub Secrets.")
        
        if missing_vars:
            sys.exit(1)
        
        # Check optional variables and warn if missing
        for var in optional_but_recommended:
            value = os.getenv(var)
            if not value or value.strip() == '':
                logger.warning(f"⚠️ Optional variable {var} is empty")
        
        # ✅ BIZTONSÁGI JAVÍTÁS: NE jelenítsünk meg titkos információkat!
        logger.info("✅ Environment validation passed:")
        for var in required_vars + optional_but_recommended:
            value = os.getenv(var)
            if value and value.strip() != '':
                logger.info(f"   {var}: [LOADED]")
            else:
                logger.info(f"   {var}: [MISSING]")
        
        # Validate REPO_NAME for pacman.conf
        repo_name = os.getenv('REPO_NAME')
        if repo_name:
            if not re.match(r'^[a-zA-Z0-9_-]+$', repo_name):
                logger.error(f"[ERROR] Invalid REPO_NAME '{repo_name}'. Must contain only letters, numbers, hyphens, and underscores.")
                sys.exit(1)
            if len(repo_name) > 50:
                logger.error(f"[ERROR] REPO_NAME '{repo_name}' is too long (max 50 characters).")
                sys.exit(1)
