"""
Environment setup and validation module
"""

import os
import sys
import re
import subprocess
import logging

logger = logging.getLogger(__name__)

def validate_environment():
    """Comprehensive pre-flight environment validation"""
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
    
    return True

def setup_builder_environment():
    """Setup builder user environment"""
    # Create builder user if it doesn't exist
    try:
        subprocess.run(['sudo', 'useradd', '-m', '-s', '/bin/bash', 'builder'], 
                      capture_output=True, check=False)
    except Exception:
        pass
    
    # Ensure builder user has passwordless sudo
    sudoers_content = "builder ALL=(ALL) NOPASSWD: ALL\n"
    with open('/etc/sudoers.d/builder', 'w') as f:
        f.write(sudoers_content)
    
    # Set proper permissions
    subprocess.run(['sudo', 'chmod', '0440', '/etc/sudoers.d/builder'], check=False)
    
    logger.info("✅ Builder environment setup complete")

def get_repo_root():
    """Get the repository root directory reliably"""
    github_workspace = os.getenv('GITHUB_WORKSPACE')
    if github_workspace:
        from pathlib import Path
        workspace_path = Path(github_workspace)
        if workspace_path.exists():
            logger.info(f"Using GITHUB_WORKSPACE: {workspace_path}")
            return workspace_path
    
    # Get script directory and go up to repo root
    from pathlib import Path
    script_path = Path(__file__).resolve()
    repo_root = script_path.parent.parent.parent.parent
    if repo_root.exists():
        logger.info(f"Using repository root from script location: {repo_root}")
        return repo_root
    
    current_dir = Path.cwd()
    logger.info(f"Using current directory: {current_dir}")
    return current_dir