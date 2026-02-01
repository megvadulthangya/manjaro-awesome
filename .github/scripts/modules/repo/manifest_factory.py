import os
import re
from pathlib import Path
from typing import List, Set, Dict, Any, Optional
import subprocess
import tempfile
import shutil
import logging

logger = logging.getLogger(__name__)


class ManifestFactory:
    """
    Generates allowlist of valid package names from PKGBUILD files.
    Source of truth is PKGBUILD pkgname values (single or array).
    """

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
            pkgbuild_path = Path(source) / "PKGBUILD"

            if pkgbuild_path.exists():
                with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                return ManifestFactory._fetch_aur_pkgbuild(source)

        except Exception:
            # SECURITY: do not log paths; only log basename
            safe_name = Path(source).name if source else "unknown"
            logger.warning(f"Manifest: failed to load PKGBUILD for {safe_name}")
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
            temp_dir = tempfile.mkdtemp(prefix="aur_")

            aur_urls = [
                f"https://aur.archlinux.org/{pkg_name}.git",
                f"git://aur.archlinux.org/{pkg_name}.git"
            ]

            for aur_url in aur_urls:
                try:
                    result = subprocess.run(
                        ["git", "clone", "--depth", "1", aur_url, temp_dir],
                        capture_output=True,
                        text=True,
                        timeout=60
                    )

                    if result.returncode == 0:
                        pkgbuild_path = Path(temp_dir) / "PKGBUILD"
                        if pkgbuild_path.exists():
                            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            shutil.rmtree(temp_dir, ignore_errors=True)
                            return content

                except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                    continue

            return None

        except Exception:
            logger.warning(f"Manifest: failed to fetch AUR PKGBUILD for {pkg_name}")
            return None
        finally:
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def extract_pkgnames(pkgbuild_text: str) -> List[str]:
        """
        Parse pkgname values from PKGBUILD text.
        Handles both single values and arrays.
        """
        pkg_names = []

        lines = []
        for line in pkgbuild_text.split('\n'):
            line = line.split('#')[0].rstrip()
            if line:
                lines.append(line)

        cleaned_text = ''
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.endswith('\\'):
                cleaned_text += line.rstrip('\\')
                i += 1
                while i < len(lines) and lines[i].endswith('\\'):
                    cleaned_text += lines[i].rstrip('\\')
                    i += 1
                if i < len(lines):
                    cleaned_text += lines[i]
            else:
                cleaned_text += line
            cleaned_text += '\n'
            i += 1

        pkgname_patterns = [
            r'pkgname\s*=\s*["\']([^"\']+)["\']',
            r'pkgname\s*=\s*\(([^)]+)\)',
        ]

        for pattern in pkgname_patterns:
            matches = re.findall(pattern, cleaned_text, re.MULTILINE | re.DOTALL)
            for match in matches:
                if match.strip():
                    if '(' not in pattern:
                        pkg_names.append(match.strip())
                    else:
                        items = re.findall(r'["\']([^"\']+)["\']', match)
                        pkg_names.extend([item.strip() for item in items if item.strip()])

        if not pkg_names:
            try:
                pkg_names = ManifestFactory._parse_with_bash(pkgbuild_text)
            except Exception:
                pass

        pkg_names = list(dict.fromkeys([name for name in pkg_names if name]))
        return pkg_names

    @staticmethod
    def _parse_with_bash(pkgbuild_text: str) -> List[str]:
        """
        Parse PKGBUILD using bash to extract pkgname values.
        More reliable for complex PKGBUILDs.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.PKGBUILD', delete=False) as tmp:
            tmp.write(pkgbuild_text)
            tmp_path = tmp.name

        try:
            script = f'''
            source "{tmp_path}" 2>/dev/null
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
                timeout=10
            )

            if result.returncode == 0:
                names = [name.strip() for name in result.stdout.strip().split('\n') if name.strip()]
                return names
            return []

        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @staticmethod
    def build_allowlist(package_sources: List[str]) -> Set[str]:
        """
        Build allowlist of valid package names from all PKGBUILDs.

        SECURITY: only logs package basenames and counts.
        """
        allowlist: Set[str] = set()

        for source in package_sources:
            safe_label = Path(source).name if source and ("/" in source or "\\" in source) else (source or "unknown")

            pkgbuild_content = ManifestFactory.get_pkgbuild(source)
            if pkgbuild_content:
                pkg_names = ManifestFactory.extract_pkgnames(pkgbuild_content)
                if pkg_names:
                    allowlist.update(pkg_names)
                else:
                    logger.warning(f"Manifest: no pkgname found for {safe_label}")
            else:
                logger.warning(f"Manifest: PKGBUILD unavailable for {safe_label}")

        logger.info(f"🧾 Manifest built: {len(allowlist)} pkgnames")
        return allowlist


def build_package_allowlist(package_sources: List[str]) -> Set[str]:
    factory = ManifestFactory()
    return factory.build_allowlist(package_sources)


if __name__ == "__main__":
    test_sources = [
        "/path/to/local/package",
        "yay"
    ]

    allowlist = build_package_allowlist(test_sources)
    print(f"Allowlist: {sorted(allowlist)}")
