#!/usr/bin/env python3

import os
import sys
import py_compile
import yaml

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

def check_yaml_file(file_path):
    """Basic YAML syntax check"""
    try:
        with open(file_path, 'r') as f:
            yaml.safe_load(f)
        print(f"[PASS] YAML syntax: {file_path}")
        return True
    except yaml.YAMLError as e:
        print(f"[FAIL] YAML syntax: {file_path} - {e}")
        return False
    except FileNotFoundError:
        print(f"[FAIL] YAML syntax: {file_path} - File not found")
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
    
    # Check Python files
    python_files = [
        '.github/scripts/builder.py',
        '.github/scripts/config.py',
        '.github/scripts/packages.py'
    ]
    
    for py_file in python_files:
        if not check_python_file(py_file):
            all_checks_passed = False
    
    # Check workflow YAML
    workflow_yaml = '.github/workflows/workflow.yaml'
    if not check_yaml_file(workflow_yaml):
        all_checks_passed = False
    
    # Check required environment variables
    required_vars = ['VPS_USER', 'VPS_HOST', 'VPS_SSH_KEY', 'REPO_SERVER_URL']
    if not check_env_vars(required_vars):
        all_checks_passed = False
    
    print("=" * 30)
    
    if all_checks_passed:
        print("✅ All preflight checks passed")
        sys.exit(0)
    else:
        print("❌ One or more preflight checks failed")
        sys.exit(1)

if __name__ == '__main__':
    main()