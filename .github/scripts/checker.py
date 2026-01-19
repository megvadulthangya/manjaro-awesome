import os
import sys
import yaml
import traceback

class PreflightChecker:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.debug = self._get_debug_mode()
        
    def _get_debug_mode(self):
        """Get debug mode from environment or config"""
        debug_env = os.environ.get('DEBUG', '').lower()
        if debug_env in ('true', '1', 'yes'):
            return True
        
        # Try to get from config.py if it exists
        config_path = '.github/scripts/config.py'
        if os.path.exists(config_path):
            try:
                # Minimal import just to check for DEBUG flag
                import importlib.util
                spec = importlib.util.spec_from_file_location("config", config_path)
                config = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config)
                return getattr(config, 'DEBUG', False)
            except:
                # If we can't import, continue without debug
                pass
        return False
    
    def log_debug(self, msg):
        """Log only in debug mode"""
        if self.debug:
            print(f"[DEBUG] {msg}")
    
    def check_python_syntax(self, filepath):
        """Validate Python file syntax"""
        if not os.path.exists(filepath):
            self.errors.append((filepath, 0, f"File not found: {filepath}"))
            return
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Compile to check syntax
            compile(content, filepath, 'exec')
            self.log_debug(f"✓ Python syntax OK: {filepath}")
            
        except SyntaxError as e:
            self.errors.append((filepath, e.lineno or 1, f"Syntax error: {e.msg}"))
        except Exception as e:
            self.errors.append((filepath, 0, f"Error reading file: {str(e)}"))
    
    def check_yaml_syntax(self, filepath):
        """Validate YAML file syntax"""
        if not os.path.exists(filepath):
            self.errors.append((filepath, 0, f"File not found: {filepath}"))
            return
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                yaml.safe_load(f)
            self.log_debug(f"✓ YAML syntax OK: {filepath}")
            
        except yaml.YAMLError as e:
            line = 1
            if hasattr(e, 'problem_mark'):
                line = e.problem_mark.line + 1
            self.errors.append((filepath, line, f"YAML syntax error: {str(e).split('\n')[0]}"))
        except Exception as e:
            self.errors.append((filepath, 0, f"Error reading YAML: {str(e)}"))
    
    def check_env_vars(self):
        """Check required environment variables"""
        required_vars = [
            'VPS_USER',
            'VPS_HOST', 
            'VPS_SSH_KEY',
            'REPO_SERVER_URL',
            'REMOTE_DIR',
            'REPO_NAME',
            'CI_PUSH_SSH_KEY'
        ]
        
        for var in required_vars:
            value = os.environ.get(var)
            if value is None or value.strip() == '':
                self.errors.append(('ENV', 0, f"Required environment variable not set: {var}"))
            else:
                self.log_debug(f"✓ ENV {var} is set")
    
    def find_workflow_file(self):
        """Find the main workflow YAML file"""
        workflow_dir = '.github/workflows'
        if os.path.exists(workflow_dir):
            for file in os.listdir(workflow_dir):
                if file.endswith(('.yml', '.yaml')):
                    return os.path.join(workflow_dir, file)
        
        # Fallback: check root directory
        for file in os.listdir('.'):
            if file.endswith(('.yml', '.yaml')):
                return file
        
        return None
    
    def run_checks(self):
        """Run all checks"""
        self.log_debug("Starting preflight checks...")
        
        # Check Python files
        python_files = [
            '.github/scripts/builder.py',
            '.github/scripts/config.py',
            '.github/scripts/packages.py'
        ]
        
        for py_file in python_files:
            self.check_python_syntax(py_file)
        
        # Check YAML workflow
        workflow_file = self.find_workflow_file()
        if workflow_file:
            self.check_yaml_syntax(workflow_file)
        else:
            self.errors.append(('WORKFLOW', 0, "No workflow YAML file found"))
        
        # Check environment variables
        self.check_env_vars()
        
        # Print results
        self.print_summary()
        
        return len(self.errors) == 0
    
    def print_summary(self):
        """Print validation summary"""
        print("\n" + "="*60)
        print("PREFLIGHT VALIDATION SUMMARY")
        print("="*60)
        
        if self.errors:
            print("\n❌ ERRORS FOUND:")
            print("-"*40)
            for filename, line, message in self.errors:
                if line and line > 0:
                    print(f"{filename}:{line} - {message}")
                else:
                    print(f"{filename} - {message}")
        
        if self.warnings:
            print("\n⚠️  WARNINGS:")
            print("-"*40)
            for filename, line, message in self.warnings:
                if line and line > 0:
                    print(f"{filename}:{line} - {message}")
                else:
                    print(f"{filename} - {message}")
        
        if not self.errors and not self.warnings:
            print("\n✅ All checks passed!")
        
        print("\n" + "="*60)
        print(f"Total errors: {len(self.errors)}")
        print(f"Total warnings: {len(self.warnings)}")
        print("="*60)

def main():
    checker = PreflightChecker()
    success = checker.run_checks()
    
    if success:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()