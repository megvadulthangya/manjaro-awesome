import os
import re
import shlex
import logging
from pathlib import Path
from typing import List, Set, Dict, Any, Optional
import subprocess
import tempfile
import shutil


logger = logging.getLogger(__name__)


class ManifestFactory:
    """
    Generates allowlist of valid package names from PKGBUILD files.
    Source of truth is PKGBUILD pkgname values (single or array).
    """

    # Timeout for the bash fallback. PKGBUILDs may perform network calls or
    # other slow operations at the top level (e.g. linux-next resolves its
    # commit date from kernel.googlesource.com before defining pkgname), so
    # the fallback must tolerate real work, not just a fast variable lookup.
    _BASH_FALLBACK_TIMEOUT = 90

    @staticmethod
    def get_pkgbuild(source: str) -> Optional[str]:
        """
        Load PKGBUILD file content from AUR or local path.

        Args:
            source: Either local path to PKGBUILD directory or AUR package name

        Returns:
            PKGBUILD content as string, or None if failed
        """
        try:
            # Check if source is a local directory
            pkgbuild_path = Path(source) / "PKGBUILD"

            if pkgbuild_path.exists():
                # Local PKGBUILD
                with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                # Try AUR - clone the PKGBUILD
                return ManifestFactory._fetch_aur_pkgbuild(source)

        except Exception as e:
            print(f"Error loading PKGBUILD from {source}: {e}")
            return None

    @staticmethod
    def _fetch_aur_pkgbuild(pkg_name: str) -> Optional[str]:
        """
        Fetch PKGBUILD from AUR.

        Args:
            pkg_name: AUR package name

        Returns:
            PKGBUILD content as string, or None if failed
        """
        temp_dir = None
        try:
            # Create temporary directory for cloning
            temp_dir = tempfile.mkdtemp(prefix="aur_")

            # Try different AUR URLs
            aur_urls = [
                f"https://aur.archlinux.org/{pkg_name}.git",
                f"git://aur.archlinux.org/{pkg_name}.git"
            ]

            for aur_url in aur_urls:
                try:
                    # Clone the AUR package (shallow clone)
                    result = subprocess.run(
                        ["git", "clone", "--depth", "1", aur_url, temp_dir],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                    if result.returncode == 0:
                        # Read PKGBUILD
                        pkgbuild_path = Path(temp_dir) / "PKGBUILD"
                        if pkgbuild_path.exists():
                            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            shutil.rmtree(temp_dir, ignore_errors=True)
                            return content

                except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                    continue

            return None

        except Exception as e:
            print(f"Error fetching AUR PKGBUILD for {pkg_name}: {e}")
            return None
        finally:
            # Cleanup
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _clean_pkgbuild_text(pkgbuild_text: str) -> str:
        """
        Strip comments and re-join line continuations so that static regex
        parsing sees a predictable text. Comments inside quotes are left
        untouched (rare in PKGBUILDs, but avoids corrupting quoted values).

        Args:
            pkgbuild_text: Raw PKGBUILD content

        Returns:
            Cleaned PKGBUILD content
        """
        result = []
        in_single = False
        in_double = False
        i = 0
        n = len(pkgbuild_text)

        while i < n:
            ch = pkgbuild_text[i]

            if ch == '\\' and i + 1 < n and not in_single:
                # Escape sequence — keep both characters; if the escaped
                # character is a newline, treat it as a line continuation
                # (join lines by dropping the backslash-newline pair).
                nxt = pkgbuild_text[i + 1]
                if nxt == '\n':
                    # Line continuation: drop both the backslash and newline,
                    # but insert a space to avoid gluing tokens together.
                    result.append(' ')
                    i += 2
                    continue
                result.append(ch)
                result.append(nxt)
                i += 2
                continue

            if ch == "'" and not in_double:
                in_single = not in_single
                result.append(ch)
            elif ch == '"' and not in_single:
                in_double = not in_double
                result.append(ch)
            elif ch == '#' and not in_single and not in_double:
                # Comment — skip to end of line, keep the newline.
                while i < n and pkgbuild_text[i] != '\n':
                    i += 1
                continue
            else:
                result.append(ch)

            i += 1

        return ''.join(result)

    @staticmethod
    def _extract_array_items(body: str) -> List[str]:
        """
        Parse the body of a bash array assignment.

        Handles both quoted and unquoted items, including quoted items that
        contain spaces (e.g. ``"foo bar"``). Uses ``shlex`` for POSIX-correct
        tokenization; falls back to a simple whitespace split if ``shlex``
        raises on malformed quoting.

        Args:
            body: Content inside the array parentheses, e.g. ``'\\n  a\\n  b\\n'``

        Returns:
            List of array items.
        """
        items: List[str] = []
        try:
            items = shlex.split(body, comments=False, posix=True)
        except ValueError:
            # Unbalanced quotes: fall back to naive split.
            items = body.split()

        cleaned = []
        for item in items:
            item = item.strip()
            if item:
                cleaned.append(item)
        return cleaned

    @staticmethod
    def _looks_like_unresolved_vars(names: List[str]) -> bool:
        """Return True if any name contains a shell variable reference."""
        return any(re.search(r'[$`]', name) for name in names)

    @staticmethod
    def extract_pkgnames(pkgbuild_text: str) -> List[str]:
        """
        Parse pkgname values from PKGBUILD text.

        Handles:
          - Single value: ``pkgname=foo``, ``pkgname="foo"``, ``pkgname='foo'``
          - Array (quoted or unquoted, single-line or multi-line):
            ``pkgname=(a b)``, ``pkgname=("a" "b")``, ``pkgname=(a\\n b\\n)``

        Falls back to sourcing the PKGBUILD via bash only if the regex pass
        yields no usable result (e.g. the array contains variable expansions
        that require evaluation). The bash fallback uses a generous timeout
        because PKGBUILDs may perform real work (network calls, etc.) at the
        top level before defining pkgname.

        Args:
            pkgbuild_text: PKGBUILD content as string

        Returns:
            List of package names extracted from PKGBUILD
        """
        pkg_names: List[str] = []

        cleaned_text = ManifestFactory._clean_pkgbuild_text(pkgbuild_text)

        # --- 1) Array assignment: pkgname=( ... ) ---
        array_match = re.search(
            r'(?m)^[ \t]*pkgname[ \t]*=[ \t]*\(([^)]+)\)',
            cleaned_text,
        )
        if array_match:
            body = array_match.group(1)
            pkg_names.extend(ManifestFactory._extract_array_items(body))

        # --- 2) Single value: pkgname=value / "value" / 'value' ---
        if not pkg_names:
            single_match = re.search(
                r'(?m)^[ \t]*pkgname[ \t]*=[ \t]*(?!\()(.+)$',
                cleaned_text,
            )
            if single_match:
                raw_value = single_match.group(1).strip()
                # Defensive: strip a trailing inline comment (should not
                # remain after _clean_pkgbuild_text, but cheap to handle).
                if '#' in raw_value and not (
                    raw_value.startswith('"') or raw_value.startswith("'")
                ):
                    raw_value = raw_value.split('#', 1)[0].rstrip()
                # Strip one layer of matching quotes.
                if len(raw_value) >= 2 and (
                    (raw_value[0] == '"' and raw_value[-1] == '"')
                    or (raw_value[0] == "'" and raw_value[-1] == "'")
                ):
                    raw_value = raw_value[1:-1]
                if raw_value:
                    pkg_names.append(raw_value)

        # --- 3) Reject results with unresolved variable references ---
        # (e.g. pkgname=("${_base}" "${_base}-extra") — regex cannot expand
        # shell variables, so a bash fallback is required in those cases.)
        if pkg_names and ManifestFactory._looks_like_unresolved_vars(pkg_names):
            logger.debug(
                f"pkg_names contain unresolved shell variables: {pkg_names} "
                f"— falling back to bash evaluation"
            )
            pkg_names = []

        # --- 4) Fallback: source the PKGBUILD via bash ---
        if not pkg_names:
            try:
                fallback_names = ManifestFactory._parse_with_bash(pkgbuild_text)
                if fallback_names:
                    pkg_names = fallback_names
                else:
                    logger.debug(
                        "bash fallback returned empty (PKGBUILD may exit "
                        "before defining pkgname, e.g. on network failure)"
                    )
            except subprocess.TimeoutExpired:
                logger.warning(
                    f"_parse_with_bash timed out after "
                    f"{ManifestFactory._BASH_FALLBACK_TIMEOUT}s "
                    f"(PKGBUILD performs slow top-level work)"
                )
            except Exception as e:
                logger.warning(f"_parse_with_bash failed: {e}")

        # Remove duplicates and empty strings while preserving order.
        pkg_names = list(dict.fromkeys([name for name in pkg_names if name]))

        return pkg_names

    @staticmethod
    def _parse_with_bash(pkgbuild_text: str) -> List[str]:
        """
        Parse PKGBUILD using bash to extract pkgname values.
        More reliable for complex PKGBUILDs whose pkgname uses shell
        variable expansion.

        NOTE: Sourcing executes the PKGBUILD's top-level statements, which
        may include network calls (linux-next is one such case). The fallback
        timeout is therefore large; a failing/panicking source simply yields
        an empty result, which the caller handles.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.PKGBUILD', delete=False) as tmp:
            tmp.write(pkgbuild_text)
            tmp_path = tmp.name

        try:
            # Run the sourcing in a subshell so PKGBUILD top-level `exit 1`
            # calls don't prevent us from reading pkgname if it was already
            # defined before the exit.
            script = f'''
            ( source "{tmp_path}" 2>/dev/null )
            if declare -p pkgname 2>/dev/null | grep -q "declare -a"; then
                for name in "${{pkgname[@]}}"; do
                    echo "$name"
                done
            else
                echo "$pkgname"
            fi
            '''

            result = subprocess.run(
                ["bash", "-c", script],
                capture_output=True,
                text=True,
                timeout=ManifestFactory._BASH_FALLBACK_TIMEOUT,
            )

            if result.returncode == 0:
                names = [
                    name.strip()
                    for name in result.stdout.strip().split('\n')
                    if name.strip()
                ]
                return names
            else:
                return []

        finally:
            # Cleanup
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @staticmethod
    def build_allowlist(package_sources: List[str]) -> Set[str]:
        """
        Build allowlist of valid package names from all PKGBUILDs.

        Args:
            package_sources: List of package sources (local paths or AUR package names)

        Returns:
            Set of all valid package names from all PKGBUILDs
        """
        allowlist = set()

        for source in package_sources:
            pkgbuild_content = ManifestFactory.get_pkgbuild(source)

            if pkgbuild_content:
                pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)

                if pkg_names:
                    print(f"Extracted from {source}: {pkg_names}")
                    allowlist.update(pkg_names)
                else:
                    print(f"Warning: No pkgname found in {source}")
            else:
                print(f"Warning: Could not load PKGBUILD from {source}")

        return allowlist


# Optional: Helper function for direct usage
def build_package_allowlist(package_sources: List[str]) -> Set[str]:
    """
    Convenience function to build allowlist from package sources.

    Args:
        package_sources: List of package sources (local paths or AUR package names)

    Returns:
        Set of all valid package names
    """
    factory = ManifestFactory()
    return factory.build_allowlist(package_sources)


if __name__ == "__main__":
    # Example usage
    test_sources = [
        "/path/to/local/package",  # Local directory with PKGBUILD
        "yay"  # AUR package name
    ]

    allowlist = build_package_allowlist(test_sources)
    print(f"Allowlist: {sorted(allowlist)}")