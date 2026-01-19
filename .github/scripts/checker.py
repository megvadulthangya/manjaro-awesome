#!/usr/bin/env python3
"""
Syntax and environment checker for CI/CD workflow.
Checks Python syntax, YAML syntax, and ENV variable consistency.
"""

import os
import sys
import ast
import yaml
import re
from pathlib import Path
from typing import List, Dict, Tuple, Set, Any, Optional


class CodeChecker:
    """Main checker class for syntax and environment validation."""
    
    def __init__(self, debug: bool = False):
        self.debug = debug
        self.root_dir = Path.cwd()
        self.errors = []
        self.warnings = []
        self.python_files_scanned = 0
        self.yaml_files_scanned = 0
        self.referenced_env_vars = set()
        self.env_references = []  # (var_name, file, line)
        
    def log_debug(self, message: str):
        """Print debug message if debug mode is enabled."""
        if self.debug:
            print(f"DEBUG: {message}")
    
    def log_error(self, error_type: str, file_path: Path, line: Optional[int], message: str):
        """Record an error."""
        self.errors.append({
            'type': error_type,
            'file': str(file_path),
            'line': line,
            'message': message
        })
    
    def check_python_syntax(self):
        """Check syntax of all Python files in the repository."""
        self.log_debug("Starting Python syntax check...")
        
        # Find all Python files
        python_files = list(self.root_dir.rglob("*.py"))
        self.python_files_scanned = len(python_files)
        
        for py_file in python_files:
            self.log_debug(f"Checking {py_file.relative_to(self.root_dir)}")
            
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Parse Python syntax
                ast.parse(content, filename=str(py_file))
                
                # Extract ENV variable references from Python files
                self._extract_env_from_python(content, py_file)
                
            except SyntaxError as e:
                self.log_error("Python Syntax", py_file, e.lineno, str(e.msg))
            except Exception as e:
                self.log_error("Python Read Error", py_file, None, f"Could not read file: {str(e)}")
    
    def _extract_env_from_python(self, content: str, file_path: Path):
        """Extract environment variable references from Python code."""
        # Patterns to match environment variable access
        patterns = [
            r'os\.getenv\([\'"]([^\'"]+)[\'"]\)',
            r'os\.environ\.get\([\'"]([^\'"]+)[\'"]\)',
            r'os\.environ\[[\'"]([^\'"]+)[\'"]\]',
            r'os\.environ\.get\([\'"]([^\'"]+)[\'"]',
            r'= os\.getenv\([\'"]([^\'"]+)[\'"]\)',
            r'\$\{([A-Za-z0-9_]+)\}',  # ${VAR} pattern
        ]
        
        for line_num, line in enumerate(content.split('\n'), 1):
            # Skip comments
            clean_line = re.sub(r'#.*$', '', line)
            
            # Check for os.environ or os.getenv
            if 'os.environ' in clean_line or 'os.getenv' in clean_line:
                for pattern in patterns:
                    matches = re.findall(pattern, clean_line)
                    for var in matches:
                        if var and var.isupper():  # Likely an environment variable
                            self.referenced_env_vars.add(var)
                            self.env_references.append((var, file_path, line_num))
            
            # Check for $VAR or ${VAR} patterns
            elif '$' in clean_line:
                # Match $VAR or ${VAR}
                var_matches = re.findall(r'\$([A-Za-z_][A-Za-z0-9_]*)|\$\{([A-Za-z_][A-Za-z0-9_]*)\}', clean_line)
                for match in var_matches:
                    var = match[0] or match[1]
                    if var and var.isupper():
                        self.referenced_env_vars.add(var)
                        self.env_references.append((var, file_path, line_num))
    
    def check_yaml_syntax(self):
        """Check syntax of all YAML files in .github/workflows/."""
        workflow_dir = self.root_dir / ".github" / "workflows"
        
        if not workflow_dir.exists():
            self.log_debug(f"Workflow directory not found: {workflow_dir}")
            return
        
        yaml_files = list(workflow_dir.glob("*.yaml")) + list(workflow_dir.glob("*.yml"))
        self.yaml_files_scanned = len(yaml_files)
        
        for yaml_file in yaml_files:
            self.log_debug(f"Checking {yaml_file.relative_to(self.root_dir)}")
            
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    yaml.safe_load(content)
                
                # Extract ENV variable references from YAML
                self._extract_env_from_yaml(content, yaml_file)
                
            except yaml.YAMLError as e:
                line = e.problem_mark.line + 1 if hasattr(e, 'problem_mark') and e.problem_mark else None
                self.log_error("YAML Syntax", yaml_file, line, str(e.problem))
            except Exception as e:
                self.log_error("YAML Read Error", yaml_file, None, f"Could not read file: {str(e)}")
    
    def _extract_env_from_yaml(self, content: str, file_path: Path):
        """Extract environment variable references from YAML files."""
        # Patterns for GitHub Actions env/secrets references
        patterns = [
            r'\$\{\{\s*env\.([A-Za-z0-9_]+)\s*\}\}',
            r'\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}',
            r'\$\{\{\s*vars\.([A-Za-z0-9_]+)\s*\}\}',
        ]
        
        for line_num, line in enumerate(content.split('\n'), 1):
            for pattern in patterns:
                matches = re.findall(pattern, line)
                for var in matches:
                    if var:
                        self.referenced_env_vars.add(var)
                        self.env_references.append((var, file_path, line_num))
            
            # Also look for simple $VAR patterns in YAML
            if '$' in line and '{{' not in line:  # Skip GitHub expressions
                var_matches = re.findall(r'\$([A-Za-z_][A-Za-z0-9_]*)', line)
                for var in var_matches:
                    if var and var.isupper():
                        self.referenced_env_vars.add(var)
                        self.env_references.append((var, file_path, line_num))
    
    def check_env_consistency(self, workflow_yaml_path: Path):
        """Check if referenced ENV variables are defined in workflow."""
        if not workflow_yaml_path.exists():
            self.log_debug(f"Workflow YAML not found: {workflow_yaml_path}")
            return
        
        try:
            with open(workflow_yaml_path, 'r', encoding='utf-8') as f:
                workflow_data = yaml.safe_load(f)
            
            # Extract defined environment variables from workflow
            defined_env_vars = set()
            
            # Check job-level env
            for job_name, job_config in workflow_data.get('jobs', {}).items():
                if isinstance(job_config, dict) and 'env' in job_config:
                    defined_env_vars.update(job_config['env'].keys())
            
            # Check for missing env variables
            for var in sorted(self.referenced_env_vars):
                if var not in defined_env_vars:
                    # Find where this variable is referenced
                    references = [(f, ln) for v, f, ln in self.env_references if v == var]
                    
                    for ref_file, ref_line in references[:1]:  # Show first occurrence
                        rel_path = Path(ref_file).relative_to(self.root_dir)
                        self.log_error(
                            "Missing ENV Variable",
                            ref_file,
                            ref_line,
                            f"Variable '{var}' is referenced but not defined in workflow env section"
                        )
        
        except Exception as e:
            self.log_error("Workflow Parse Error", workflow_yaml_path, None, f"Could not parse workflow: {str(e)}")
    
    def print_report(self):
        """Print the final report."""
        print("\n" + "="*60)
        print("CHECKER REPORT")
        print("="*60)
        
        print(f"\n📊 Summary:")
        print(f"  Python files scanned: {self.python_files_scanned}")
        print(f"  YAML files scanned: {self.yaml_files_scanned}")
        
        if self.errors:
            print(f"\n❌ Errors found: {len(self.errors)}")
            
            # Group errors by type
            error_types = {}
            for error in self.errors:
                error_type = error['type']
                if error_type not in error_types:
                    error_types[error_type] = []
                error_types[error_type].append(error)
            
            for error_type, errors in error_types.items():
                print(f"\n  {error_type} Errors:")
                for error in errors:
                    line_info = f":{error['line']}" if error['line'] else ""
                    print(f"    {error['file']}{line_info}: {error['message']}")
        else:
            print("\n✅ No errors found!")
        
        if self.warnings:
            print(f"\n⚠️  Warnings: {len(self.warnings)}")
            for warning in self.warnings:
                print(f"  {warning}")
        
        print("\n" + "="*60)
        
        return len(self.errors) == 0
    
    def run(self):
        """Run all checks."""
        self.log_debug(f"Starting checks in directory: {self.root_dir}")
        
        # Check for debug mode from config.py
        if not self.debug:
            config_file = self.root_dir / "config.py"
            if config_file.exists():
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if 'DEBUG = True' in content or 'DEBUG=True' in content:
                            self.debug = True
                            self.log_debug("Debug mode enabled via config.py")
                except:
                    pass
        
        # Run checks
        self.check_python_syntax()
        self.check_yaml_syntax()
        
        # Find the main workflow YAML (the one with "MPB - with diagnostic")
        workflow_dir = self.root_dir / ".github" / "workflows"
        main_workflow = None
        
        if workflow_dir.exists():
            for yaml_file in workflow_dir.glob("*.yaml"):
                try:
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    if 'MPB - with diagnostic' in content:
                        main_workflow = yaml_file
                        break
                except:
                    continue
        
        if main_workflow:
            self.check_env_consistency(main_workflow)
        else:
            self.log_debug("Could not find main workflow YAML")
        
        # Print final report
        success = self.print_report()
        return 0 if success else 1


def main():
    """Main entry point."""
    # Check for debug mode from environment variable
    debug = os.environ.get('DEBUG', '').lower() in ('1', 'true', 'yes', 'on')
    
    checker = CodeChecker(debug=debug)
    sys.exit(checker.run())


if __name__ == "__main__":
    main()