# .github/scripts/checker.py
#!/usr/bin/env python3
"""Preflight checker for GitHub Actions workflow."""

import os
import sys
import yaml
import py_compile
import subprocess
from pathlib import Path

REQUIRED_ENV_VARS = [
    'VPS_USER',
    'VPS_HOST', 
    'VPS_SSH_KEY',
    'REPO_SERVER_URL',
    'REMOTE_DIR',
    'REPO_NAME'
]

PYTHON_FILES = [
    '.github/scripts/builder.py',
    '.github/scripts/config.py', 
    '.github/scripts/packages.py'
]

WORKFLOW_PATH = '.github/workflows/workflow.yaml'

class PreflightChecker:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.debug = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes')

    def log(self, msg):
        if self.debug:
            print(f"[DEBUG] {msg}")

    def check_python_files(self):
        """Validate Python syntax using py_compile."""
        self.log("Checking Python files...")
        for py_file in PYTHON_FILES:
            if not Path(py_file).exists():
                self.errors.append(f"Python file not found: {py_file}")
                continue
            try:
                py_compile.compile(py_file, doraise=True)
                self.log(f"✓ {py_file} - Syntax OK")
            except py_compile.PyCompileError as e:
                self.errors.append(f"Python syntax error in {py_file}: {e}")

    def check_yaml_syntax(self):
        """Validate YAML syntax of workflow file."""
        self.log(f"Checking YAML syntax for {WORKFLOW_PATH}...")
        if not Path(WORKFLOW_PATH).exists():
            self.errors.append(f"Workflow file not found: {WORKFLOW_PATH}")
            return
        try:
            with open(WORKFLOW_PATH, 'r') as f:
                yaml.safe_load(f)
            self.log("✓ Workflow YAML syntax OK")
        except yaml.YAMLError as e:
            self.errors.append(f"YAML syntax error in {WORKFLOW_PATH}: {e}")

    def check_env_vars(self):
        """Check if required environment variables are set."""
        self.log("Checking environment variables...")
        for var in REQUIRED_ENV_VARS:
            value = os.environ.get(var)
            if value is None or str(value).strip() == '':
                self.errors.append(f"Required env var not set: {var}")
            else:
                self.log(f"✓ {var} = [SET]")

    def run(self):
        """Execute all checks and print summary."""
        print("🧪 Running preflight checks...")
        
        self.check_python_files()
        self.check_yaml_syntax()
        self.check_env_vars()
        
        print("\n" + "="*50)
        print("PREFLIGHT CHECK SUMMARY")
        print("="*50)
        
        if self.warnings:
            print("\n⚠️  WARNINGS:")
            for warning in self.warnings:
                print(f"   • {warning}")
        
        if self.errors:
            print("\n❌ ERRORS:")
            for error in self.errors:
                print(f"   • {error}")
            print(f"\n❌ Preflight check FAILED with {len(self.errors)} error(s)")
            return 1
        else:
            print("\n✅ All preflight checks passed!")
            return 0

if __name__ == "__main__":
    checker = PreflightChecker()
    sys.exit(checker.run())