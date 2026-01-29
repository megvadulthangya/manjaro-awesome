"""
Environment validation
"""
import os
import sys
import logging
from pathlib import Path
from typing import Optional

class EnvironmentValidator:
    """Validates required environment variables"""
    
    REQUIRED_VARS = [
        'REPO_NAME',
        'VPS_HOST',
        'VPS_USER',
        'VPS_SSH_KEY',
        'REMOTE_DIR',
    ]

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def validate(self) -> bool:
        """Check for required secrets"""
        self.logger.info("Validating environment...")
        missing = []
        for var in self.REQUIRED_VARS:
            val = os.getenv(var)
            if not val or not val.strip():
                missing.append(var)
        
        if missing:
            self.logger.error(f"Missing required variables: {', '.join(missing)}")
            sys.exit(1)
            
        self.logger.info("✅ Environment validation passed")
        return True

    def get_repo_root(self) -> Path:
        """Find repo root"""
        # Logic to find .github folder
        path = Path(__file__).resolve()
        for _ in range(6): # Climb up
            if (path / '.github').exists():
                return path
            path = path.parent
        return Path.cwd()