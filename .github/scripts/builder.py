#!/usr/bin/env python3
"""
Manjaro Package Builder - Main orchestrator
Coordinates between modules
"""

print(">>> DEBUG: Script started")

import os
import sys
import logging
from pathlib import Path

# Add the script directory to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Try to import config to check if it exists
try:
    import config
    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False
    print("❌ CRITICAL: config.py not found")
    sys.exit(1)

# Import modules from the new structure
try:
    from modules.common.config_loader import load_config
    from modules.common.environment import validate_environment, get_repo_root, setup_builder_environment
    from modules.orchestrator.package_builder import PackageBuilder
    MODULES_LOADED = True
except ImportError as e:
    print(f"❌ CRITICAL: Failed to import modules: {e}")
    print(f"❌ Please ensure modules are in: {script_dir}/modules/")
    MODULES_LOADED = False
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('builder.log')
    ]
)

if __name__ == "__main__":
    if not MODULES_LOADED:
        sys.exit(1)
    
    # Validate environment first
    validate_environment()
    
    # Setup builder environment
    setup_builder_environment()
    
    # Create builder and run
    builder = PackageBuilder()
    sys.exit(builder.run())