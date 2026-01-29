#!/usr/bin/env python3
"""
Entry point
"""
import sys
import os

# Ensure modules are in path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "modules"))
sys.path.insert(0, script_dir)

from modules.orchestrator.package_builder import PackageBuilder

def main():
    builder = PackageBuilder()
    return builder.run()

if __name__ == "__main__":
    sys.exit(main())