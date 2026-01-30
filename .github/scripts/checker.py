#!/usr/bin/env python3

import os
import sys
import py_compile
import yaml

def find_files_by_extension(root_dir, extensions):
    """Find all files with given extensions recursively"""
    matched_files = []
    for root, dirs, files in os.walk(root_dir):
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                matched_files.append(os.path.join(root, file))
    return matched_files

def check_python_file(file_path):
    """Check Python file syntax using py_compile"""
    try:
        py_compile.compile(file_path, doraise=True)
        print(f"[PASS] Python syntax: {file_path}")
        return True
    except py_compile.PyCompileError as e:
        print(f"[FAIL] Python syntax: {file_path} - {e}")
        return False
    except FileNotFoundError:
        print(f"[FAIL] Python syntax: {file_path} - File not found")
        return False
    except Exception as e:
        print(f"[FAIL] Python syntax: {file_path} - Unexpected error: {e}")
        return False

def check_yaml_file(file_path):
    """Basic YAML syntax check"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            yaml.safe_load(f)
        print(f"[PASS] YAML syntax: {file_path}")
        return True
    except yaml.YAMLError as e:
        print(f"[FAIL] YAML syntax: {file_path} - {e}")
        return False
    except FileNotFoundError:
        print(f"[FAIL] YAML syntax: {file_path} - File not found")
        return False
    except Exception as e:
        print(f"[FAIL] YAML syntax: {file_path} - Unexpected error: {e}")
        return False

def check_env_vars(vars_list):
    """Check that environment variables are not empty"""
    all_passed = True
    for var in vars_list:
        value = os.getenv(var, '')
        if value and value.strip():
            print(f"[PASS] ENV variable: {var}")
        else:
            print(f"[FAIL] ENV variable: {var} - Empty or not set")
            all_passed = False
    return all_passed

def main():
    print("=== Running Preflight Checker ===")
    
    # Track overall status
    all_checks_passed = True
    
    # Check Python files in .github/scripts/ and subdirectories
    scripts_dir = '.github/scripts'
    if os.path.exists(scripts_dir):
        python_files = find_files_by_extension(scripts_dir, ['.py'])
        
        if python_files:
            print(f"\nChecking {len(python_files)} Python file(s) in '{scripts_dir}' and subdirectories:")
            for py_file in python_files:
                if not check_python_file(py_file):
                    all_checks_passed = False
        else:
            print(f"[INFO] No Python files found in '{scripts_dir}'")
    else:
        print(f"[WARNING] Directory '{scripts_dir}' does not exist")
    
    # Check YAML files in .github/workflows/
    workflows_dir = '.github/workflows'
    if os.path.exists(workflows_dir):
        yaml_files = find_files_by_extension(workflows_dir, ['.yaml', '.yml', '.bckp'])
        
        if yaml_files:
            print(f"\nChecking {len(yaml_files)} YAML file(s) in '{workflows_dir}' and subdirectories:")
            for yaml_file in yaml_files:
                if not check_yaml_file(yaml_file):
                    all_checks_passed = False
        else:
            print(f"[INFO] No YAML files found in '{workflows_dir}'")
    else:
        print(f"[WARNING] Directory '{workflows_dir}' does not exist")
    
    # Check required environment variables
    print("\nChecking environment variables:")
    required_vars = ['VPS_USER', 'VPS_HOST', 'VPS_SSH_KEY', 'REPO_SERVER_URL']
    if not check_env_vars(required_vars):
        all_checks_passed = False
    
    print("\n" + "=" * 30)
    
    if all_checks_passed:
        print("✅ All preflight checks passed")
        sys.exit(0)
    else:
        print("❌ One or more preflight checks failed")
        sys.exit(1)

if __name__ == '__main__':
    main()