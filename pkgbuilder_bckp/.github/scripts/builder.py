#!/usr/bin/env python3
"""
Manjaro Package Builder - Refactored Modular Architecture with Zero-Residue Policy
Main entry point for the refactored modular system
"""

import os
import sys
import traceback

# Add the modules directory to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
modules_dir = os.path.join(script_dir, "modules")
sys.path.insert(0, modules_dir)

# Try to import from the new modular structure
try:
    from modules.orchestrator.package_builder import PackageBuilder
    print(">>> DEBUG: Successfully imported PackageBuilder from modular system")
    MODULES_LOADED = True
except ImportError as e:
    print(f"❌ CRITICAL: Failed to import PackageBuilder: {e}")
    print(f"❌ Please ensure modules are in: {modules_dir}/")
    print(f"❌ Current sys.path: {sys.path}")
    MODULES_LOADED = False
    sys.exit(1)
except Exception as e:
    print(f"❌ CRITICAL: Error importing PackageBuilder: {e}")
    MODULES_LOADED = False
    sys.exit(1)


def main() -> int:
    """
    Main entry point for the package builder
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        if not MODULES_LOADED:
            print("❌ Modules not loaded, cannot proceed")
            return 1
        
        print(">>> DEBUG: Starting PackageBuilder.run()")
        builder = PackageBuilder()
        return builder.run()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Build interrupted by user")
        return 130  # Standard exit code for Ctrl+C
    except SystemExit as e:
        # Re-raise system exit to preserve exit code
        raise e
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR in main(): {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())