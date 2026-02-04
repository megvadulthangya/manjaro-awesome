#!/usr/bin/env python3

import os
import sys
import py_compile
import yaml
import warnings
import ast


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


def check_python_warnings_invalid_escape(file_path):
    """Fail only on invalid escape sequence warnings (Python 3.12+ safe)."""
    try:
        source = _read_text_file_with_fallback(file_path)

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

            for w in captured:
                try:
                    category = w.category
                    msg = str(w.message)
                except Exception:
                    continue

                msg_l = msg.lower()
                is_syntax = isinstance(category, type) and issubclass(category, SyntaxWarning)
                is_depr = isinstance(category, type) and issubclass(category, DeprecationWarning)

                # Fail ONLY on invalid escape sequences
                if (is_syntax or is_depr) and ("invalid escape sequence" in msg_l):
                    lineno = getattr(w, "lineno", None)
                    line_info = f" (line {lineno})" if lineno is not None else ""

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


# ---- Advisory regex checks (WARN by default, FAIL only if STRICT_REGEX=1) ----

_REGEX_META_CHARS = set("^$[](){}*+?|")


def _looks_regexy(s: str) -> bool:
    """Heuristic: contains typical regex metacharacters (no backslash required)."""
    return any(ch in _REGEX_META_CHARS for ch in s)


def _is_patternish_name(name: str) -> bool:
    n = name.lower()
    return (
        "regex" in n
        or "pattern" in n
        or n.endswith("_pat")
        or n.endswith("_pattern")
        or n.endswith("_patterns")
        or n.endswith("patterns")
        or n.endswith("pattern")
    )


def _collect_regex_recommendations(file_path):
    """
    Return list of (lineno, message) recommendations where a string literal looks like a regex
    and is likely used as a regex pattern (re.* calls or pattern-ish variable assignment).
    These are recommendations only (WARN), NOT correctness issues.
    """
    source = _read_text_file_with_fallback(file_path)

    try:
        tree = ast.parse(source, filename=file_path)
    except Exception:
        # If parsing fails, py_compile already covers syntax errors; skip recommendations.
        return []

    recs = []

    # 1) Detect string literals passed into re.<fn>(pattern, ...)
    re_fns = {
        "compile", "search", "match", "fullmatch",
        "sub", "subn", "split", "findall", "finditer",
    }

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            # match re.<fn>(...)
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.value.id == "re" and fn.attr in re_fns and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        s = first.value
                        if _looks_regexy(s):
                            lineno = getattr(first, "lineno", getattr(node, "lineno", None))
                            if lineno is not None:
                                preview = s.replace("\n", "\\n")
                                if len(preview) > 120:
                                    preview = preview[:117] + "..."
                                recs.append(
                                    (lineno, f"Consider using a raw string for regex literal: {preview}")
                                )
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign):
            # Detect assignments like arch_patterns = ["-x86_64$", ...] or suffix_pattern = "-any$"
            # ONLY if target name looks pattern-ish.
            target_names = []
            for t in node.targets:
                if isinstance(t, ast.Name):
                    target_names.append(t.id)

            if not any(_is_patternish_name(n) for n in target_names):
                self.generic_visit(node)
                return

            v = node.value

            def handle_string_constant(sc: ast.Constant):
                if isinstance(sc.value, str) and _looks_regexy(sc.value):
                    lineno = getattr(sc, "lineno", getattr(node, "lineno", None))
                    if lineno is not None:
                        preview = sc.value.replace("\n", "\\n")
                        if len(preview) > 120:
                            preview = preview[:117] + "..."
                        recs.append((lineno, f"Regex-like pattern literal could be raw string: {preview}"))

            if isinstance(v, ast.Constant):
                handle_string_constant(v)
            elif isinstance(v, (ast.List, ast.Tuple, ast.Set)):
                for elt in v.elts:
                    if isinstance(elt, ast.Constant):
                        handle_string_constant(elt)

            self.generic_visit(node)

    Visitor().visit(tree)

    # De-dup by (lineno, msg)
    seen = set()
    uniq = []
    for ln, msg in recs:
        key = (ln, msg)
        if key not in seen:
            seen.add(key)
            uniq.append((ln, msg))
    return uniq


def check_regex_recommendations(file_path):
    """
    Advisory-only:
    - Print [WARN] lines for regex-like literals used in regex contexts.
    - Do NOT fail unless STRICT_REGEX=1.
    """
    strict = os.getenv("STRICT_REGEX", "").strip() in {"1", "true", "TRUE", "yes", "YES"}
    try:
        recs = _collect_regex_recommendations(file_path)
        if not recs:
            print(f"[PASS] Python regex advisory: {file_path}")
            return True

        for ln, msg in recs:
            print(f"[WARN] Python regex advisory: {file_path} (line {ln}) - {msg}")

        if strict:
            print(f"[FAIL] Python regex advisory: {file_path} - STRICT_REGEX enabled")
            return False

        return True

    except FileNotFoundError:
        print(f"[FAIL] Python regex advisory: {file_path} - File not found")
        return False
    except Exception as e:
        print(f"[FAIL] Python regex advisory: {file_path} - Unexpected error: {e}")
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

    scripts_dir = ".github/scripts"
    if os.path.exists(scripts_dir):
        python_files = find_files_by_extension(scripts_dir, [".py"])

        if python_files:
            print(f"\nChecking {len(python_files)} Python file(s) in '{scripts_dir}' and subdirectories:")
            for py_file in python_files:
                syntax_ok = check_python_file(py_file)
                warnings_ok = check_python_warnings_invalid_escape(py_file)
                regex_adv_ok = check_regex_recommendations(py_file)

                if not (syntax_ok and warnings_ok and regex_adv_ok):
                    all_checks_passed = False
        else:
            print(f"[INFO] No Python files found in '{scripts_dir}'")
    else:
        print(f"[WARNING] Directory '{scripts_dir}' does not exist")

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
