#!/usr/bin/env python3

import os
import sys
import py_compile
import yaml
import warnings
import ast
import tokenize
import io


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


def _has_backslash(s: str) -> bool:
    """Only flag regex literals that contain backslash, because those are riskier."""
    return "\\" in s


def _string_token_prefix_and_quote_index(token_text: str):
    """
    Return (prefix_lower, quote_index) for a Python string token like r"..." or '...'.
    Works for normal, triple-quoted, and prefixed strings.
    """
    s = token_text
    if not s:
        return "", -1

    qpos_single = s.find("'")
    qpos_double = s.find('"')

    if qpos_single == -1 and qpos_double == -1:
        return "", -1

    if qpos_single == -1:
        qpos = qpos_double
    elif qpos_double == -1:
        qpos = qpos_single
    else:
        qpos = min(qpos_single, qpos_double)

    prefix = s[:qpos].lower()
    return prefix, qpos


def _build_string_prefix_map(source: str):
    """
    Build mapping from (lineno, col) -> prefix_lower for STRING tokens.
    This preserves raw-prefix information (r/R, rf/fr, etc.) that AST does not retain.
    """
    prefix_map = {}
    reader = io.StringIO(source).readline
    for tok in tokenize.generate_tokens(reader):
        if tok.type != tokenize.STRING:
            continue
        prefix, qidx = _string_token_prefix_and_quote_index(tok.string)
        if qidx >= 0:
            prefix_map[(tok.start[0], tok.start[1])] = prefix
    return prefix_map


def _node_is_raw_string_literal(node, prefix_map) -> bool:
    """
    Determine if an AST string Constant node originated from a raw-prefixed literal.
    Accept r/R and combined prefixes like rf/fr (any order, any case).
    """
    lineno = getattr(node, "lineno", None)
    col = getattr(node, "col_offset", None)
    if lineno is None or col is None:
        return False
    prefix = prefix_map.get((lineno, col), "")
    return "r" in prefix  # covers r, R, rf, fr, rF, etc.


def _collect_regex_recommendations(file_path):
    """
    Return list of (lineno, message) recommendations where a string literal is likely a regex
    AND contains backslashes (\\) AND is NOT already a raw string literal.

    We only warn when:
      - a string literal is passed as the pattern argument to re.<fn>(...), or
      - a string literal is assigned into a pattern-ish variable (e.g. *_pattern, *_patterns, regex)
    AND the literal contains a backslash
    AND the literal is not raw (r/R/rf/fr/...).
    """
    source = _read_text_file_with_fallback(file_path)
    prefix_map = _build_string_prefix_map(source)

    try:
        tree = ast.parse(source, filename=file_path)
    except Exception:
        return []

    recs = []

    re_fns = {
        "compile", "search", "match", "fullmatch",
        "sub", "subn", "split", "findall", "finditer",
    }

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                if fn.value.id == "re" and fn.attr in re_fns and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        s = first.value
                        if _has_backslash(s) and not _node_is_raw_string_literal(first, prefix_map):
                            lineno = getattr(first, "lineno", getattr(node, "lineno", None))
                            if lineno is not None:
                                preview = s.replace("\n", "\\n")
                                if len(preview) > 120:
                                    preview = preview[:117] + "..."
                                recs.append(
                                    (lineno, f"Regex literal contains backslash; consider raw string: {preview}")
                                )
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign):
            target_names = []
            for t in node.targets:
                if isinstance(t, ast.Name):
                    target_names.append(t.id)

            if not any(_is_patternish_name(n) for n in target_names):
                self.generic_visit(node)
                return

            v = node.value

            def handle_string_constant(sc: ast.Constant):
                if isinstance(sc.value, str) and _has_backslash(sc.value):
                    if _node_is_raw_string_literal(sc, prefix_map):
                        return
                    lineno = getattr(sc, "lineno", getattr(node, "lineno", None))
                    if lineno is not None:
                        preview = sc.value.replace("\n", "\\n")
                        if len(preview) > 120:
                            preview = preview[:117] + "..."
                        recs.append((lineno, f"Pattern literal contains backslash; consider raw string: {preview}"))

            if isinstance(v, ast.Constant):
                handle_string_constant(v)
            elif isinstance(v, (ast.List, ast.Tuple, ast.Set)):
                for elt in v.elts:
                    if isinstance(elt, ast.Constant):
                        handle_string_constant(elt)

            self.generic_visit(node)

    Visitor().visit(tree)

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
    - Print [WARN] lines ONLY for non-raw regex literals that contain backslashes.
    - Do NOT fail unless STRICT_REGEX=1.
    """
    strict = os.getenv("STRICT_REGEX", "").strip().lower() in {"1", "true", "yes"}
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
