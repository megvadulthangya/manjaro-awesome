#!/usr/bin/env python3
"""
Manjaro Package Builder - Refactored Modular Architecture with Zero-Residue Policy
Main orchestrator that coordinates between modules
"""

print(">>> DEBUG: Script started")

import os
import sys

# Add the script directory to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

print(f">>> DEBUG: Script directory: {script_dir}")
print(f">>> DEBUG: sys.path: {sys.path}")

# Import our modules
try:
    # Adjust imports to work from the script directory
    from modules.orchestrator.package_builder import PackageBuilder
    MODULES_LOADED = True
    print(">>> DEBUG: PackageBuilder imported successfully")
except ImportError as e:
    print(f"❌ CRITICAL: Failed to import modules: {e}")
    print(f"❌ sys.path: {sys.path}")
    print(f"❌ Current directory: {os.getcwd()}")
    print(f"❌ Script directory: {script_dir}")
    MODULES_LOADED = False
    sys.exit(1)

if __name__ == "__main__":
    # Run the builder
    print(">>> DEBUG: Starting PackageBuilder...")
    sys.exit(PackageBuilder().run())