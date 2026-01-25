#!/usr/bin/env python3
"""
Main Entry Point for Package Builder
Robust path resolution and module loading for all execution contexts
"""

import os
import sys
from pathlib import Path

def main():
    """
    Main entry point with robust path resolution
    """
    # ============================================================================
    # 1. ROBUST PATH INJECTION
    # ============================================================================
    
    # Get absolute path of this script
    main_script_dir = Path(__file__).resolve().parent
    
    # Get absolute path of .github/scripts directory (where modules live)
    scripts_dir = main_script_dir
    
    # Check if we're running from .github/workflows directory
    if main_script_dir.name == 'workflows':
        scripts_dir = main_script_dir.parent / 'scripts'
    
    # Ensure scripts directory exists
    if not scripts_dir.exists():
        print(f"❌ CRITICAL: Scripts directory not found: {scripts_dir}")
        sys.exit(1)
    
    # Add scripts directory to Python path
    sys.path.insert(0, str(scripts_dir))
    
    print(f"🔧 Python path configured:")
    print(f"   Scripts directory: {scripts_dir}")
    print(f"   sys.path[0]: {sys.path[0]}")
    
    # ============================================================================
    # 2. ENVIRONMENT VALIDATION
    # ============================================================================
    
    # Check required module files exist
    required_files = ['builder.py', 'vps_client.py', 'repo_manager.py']
    missing_files = []
    
    for filename in required_files:
        file_path = scripts_dir / filename
        if not file_path.exists():
            missing_files.append(filename)
    
    if missing_files:
        print(f"❌ CRITICAL: Missing required files in {scripts_dir}:")
        for f in missing_files:
            print(f"   - {f}")
        sys.exit(1)
    
    print("✅ All required module files found")
    
    # ============================================================================
    # 3. EXECUTE BUILDER
    # ============================================================================
    
    try:
        # Import and execute builder
        from builder import PackageBuilder
        
        print("\n" + "="*60)
        print("🚀 STARTING PACKAGE BUILDER")
        print("="*60)
        
        builder = PackageBuilder()
        exit_code = builder.run()
        
        sys.exit(exit_code)
        
    except ImportError as e:
        print(f"❌ CRITICAL: Failed to import builder module: {e}")
        print(f"   scripts_dir: {scripts_dir}")
        print(f"   Current files in directory:")
        for f in scripts_dir.iterdir():
            print(f"   - {f.name}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()