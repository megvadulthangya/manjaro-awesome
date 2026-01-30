#!/usr/bin/env python3
"""
Manjaro Package Builder - Refactored Modular Architecture with Zero-Residue Policy
Main orchestrator that coordinates between modules
"""

import sys

if __name__ == "__main__":
    print(">>> DEBUG: Script started")
    
    # Import the main PackageBuilder class
    from scripts.modules.orchestrator.package_builder import PackageBuilder
    
    # Run the builder
    sys.exit(PackageBuilder().run())