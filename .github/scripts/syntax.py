#!/usr/bin/env python3

import os
import sys
import py_compile
import yaml
import warnings


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


def _read_text_file_with_fallback(file_path):
    """Read file content with UTF-8, fallback to latin-1"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(file_path, "r", encoding="latin-1") as f:
            return f.read()


def check_python_warnings(file_path):
    """Check Python file for invalid escape sequence warnings"""
    try:
        source = _read_text_file_with_fallback(file_path)

        # Capture warnings during compilation (compile only, no execution)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")

            try:
                compile(source, file_path, "exec", dont_inherit=True, optimize=0)
            except SyntaxError:
                # Syntax errors are handled by py_compile check
                pass
            except Exception as e:
                print(f"[FAIL] Python warnings: {file_path} - Unexpected error during compilation: {e}")
                return False

            # Only fail on the specific target: "invalid escape sequence"
            for w in captured:
                try:
                    category = w.category
                    msg = str(w.message)
                except Exception:
                    continue

                msg_l = msg.lower()
                is_syntax = isinstance(category, type) and issubclass(category, SyntaxWarning)
                is_depr = isinstance(category, type) and issubclass(category, DeprecationWarning)

                if (is_syntax or is_depr) and ("invalid escape sequence" in msg_l):
                    line_info = ""
                    lineno = getattr(w, "lineno", None)
                    if lineno is not None:
                        line_info = f" (line {lineno})"

                    # Optional: show the exact source line to speed up fixing
                    src_line = ""
                    if isinstance(lineno, int) and lineno >= 1:
                        try:
                            lines = source.splitlines()
                            if lineno - 1 < len(lines):
                                src_line = lines[lineno - 1].rstrip()
                        except Exception:
                            src_line = ""

                    extra = f" | {src_line}" if src_line else ""
                    print(
                        f"[FAIL] Python warnings: {file_path}{line_info} - "
                        f"{category.__name__}: {msg}{extra}"
                    )
                    return False

            print(f"[PASS] Python warnings: {file_path}")
            return True

    except FileNotFoundError:
        print(f"[FAIL] Python warnings: {file_path} - File not found")
        return False
    except Exception as e:
        print(f"[FAIL] Python warnings: {file_path} - Unexpected error: {e}")
        return False


def check_yaml_file(file_path):
    """Basic YAML syntax check"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
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
        value = os.getenv(var, "")
        if value and value.strip():
            print(f"[PASS] ENV variable: {var}")
        else:
            print(f"[FAIL] ENV variable: {var} - Empty or not set")
            all_passed = False
    return all_passed


def main():
    print("=== Running Preflight Checker ===")

    all_checks_passed = True

    # Check Python files in .github/scripts/ and subdirectories
    scripts_dir = ".github/scripts"
    if os.path.exists(scripts_dir):
        python_files = find_files_by_extension(scripts_dir, [".py"])

        if python_files:
            print(f"\nChecking {len(python_files)} Python file(s) in '{scripts_dir}' and subdirectories:")
            for py_file in python_files:
                syntax_ok = check_python_file(py_file)
                # Run warning check regardless, so you get full signal in one run
                warnings_ok = check_python_warnings(py_file)
                if not (syntax_ok and warnings_ok):
                    all_checks_passed = False
        else:
            print(f"[INFO] No Python files found in '{scripts_dir}'")
    else:
        print(f"[WARNING] Directory '{scripts_dir}' does not exist")

    # Check YAML files in .github/workflows/
    workflows_dir = ".github/workflows"
    if os.path.exists(workflows_dir):
        yaml_files = find_files_by_extension(workflows_dir, [".yaml", ".yml", ".bckp"])

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
    required_vars = ["VPS_USER", "VPS_HOST", "VPS_SSH_KEY", "REPO_SERVER_URL"]
    if not check_env_vars(required_vars):
        all_checks_passed = False

    print("\n" + "=" * 30)

    if all_checks_passed:
        print("✅ All preflight checks passed")
        sys.exit(0)
    else:
        print("❌ One or more preflight checks failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
