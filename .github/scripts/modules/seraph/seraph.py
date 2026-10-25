"""
Seraph Module - Orchestrates kernel change detection

Seraph watches the kernel versions in the remote repositories. When a
kernel changes, she asks Keymaker to bump the corresponding module's
pkgrel, then asks Link to push the changes (which triggers the build).
"""

import re
import time
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from modules.keymaker import Keymaker
from modules.link import Link

logger = logging.getLogger(__name__)


class Seraph:
    """
    Seraph watches and orchestrates.

    Seraph does NOT contain the logic of Keymaker or Link — she
    instantiates them and coordinates their work.
    """

    TRACKING_DIR = ".build_tracking"
    PENDING_DIR = ".pending"
    PENDING_STALE_SECONDS = 24 * 3600

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.keymaker = Keymaker(repo_root)
        self.link = Link(repo_root)
        self.tracking_dir = repo_root / self.TRACKING_DIR
        self.pending_dir = repo_root / self.PENDING_DIR

    def watch(self) -> int:
        """
        Main orchestration: detect changes, bump, push.

        Returns:
            0 on success, 1 on failure
        """
        logger.info("SERAPH_WATCH_START")

        kernel_modules = self._discover_kernel_modules()
        logger.info(f"SERAPH_DISCOVERED count={len(kernel_modules)}")

        if not kernel_modules:
            logger.info("SERAPH_NO_KERNEL_MODULES")
            return 0

        bumped = []

        for pkg_name, pkgbuild_path, kernel_pkg_name in kernel_modules:
            try:
                did_bump = self._check_and_bump(pkg_name, pkgbuild_path, kernel_pkg_name)
                if did_bump:
                    bumped.append((pkg_name, pkgbuild_path))
            except Exception as e:
                logger.error(f"SERAPH_CHECK_FAIL pkg={pkg_name} error={e}")

        if not bumped:
            logger.info("SERAPH_NO_BUMPS")
            return 0

        bumped_names = [name for name, _ in bumped]
        logger.info(f"SERAPH_BUMPS pkgs={bumped_names}")

        if not self.link.push(bumped):
            logger.error("SERAPH_PUSH_FAIL")
            return 1

        logger.info("SERAPH_WATCH_SUCCESS")
        return 0

    def _discover_kernel_modules(self) -> List[Tuple[str, Path, str]]:
        """
        Find all PKGBUILDs that build kernel modules.

        Returns:
            List of (pkg_name, pkgbuild_path, kernel_pkg_name) tuples
        """
        results = []

        for pkgbuild_path in self.repo_root.glob("*/PKGBUILD"):
            pkg_name = pkgbuild_path.parent.name

            try:
                with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                continue

            prefix_match = re.search(r'^_linuxprefix\s*=\s*([^\s#]+)', content, re.MULTILINE)
            if not prefix_match:
                continue

            kernel_pkg_name = prefix_match.group(1).strip().strip('"').strip("'")

            if pkg_name == kernel_pkg_name:
                continue

            results.append((pkg_name, pkgbuild_path, kernel_pkg_name))

        return results

    def _check_and_bump(self, pkg_name: str, pkgbuild_path: Path, kernel_pkg_name: str) -> bool:
        """
        Check one kernel module for needed rebuild and bump if needed.

        Returns:
            True if bump was performed, False otherwise
        """
        pending_marker = self.pending_dir / pkg_name
        if pending_marker.exists():
            try:
                age_seconds = time.time() - pending_marker.stat().st_mtime
                if age_seconds > self.PENDING_STALE_SECONDS:
                    logger.warning(
                        f"SERAPH_PENDING_STALE pkg={pkg_name} "
                        f"age_hours={age_seconds/3600:.1f}"
                    )
            except Exception:
                pass
            logger.info(f"SERAPH_SKIP pkg={pkg_name} reason=pending_exists")
            return False

        tracking_file = self.tracking_dir / pkg_name
        if not tracking_file.exists():
            logger.info(
                f"SERAPH_SKIP pkg={pkg_name} "
                f"reason=no_tracking (will populate on next successful build)"
            )
            return False

        try:
            built_kernel_version = tracking_file.read_text(encoding='utf-8').strip()
        except Exception as e:
            logger.warning(f"SERAPH_SKIP pkg={pkg_name} reason=tracking_read_error error={e}")
            return False

        current_kernel_version = self._query_package_version(kernel_pkg_name)
        if not current_kernel_version:
            logger.warning(
                f"SERAPH_SKIP pkg={pkg_name} "
                f"reason=kernel_query_failed kernel={kernel_pkg_name}"
            )
            return False

        if built_kernel_version == current_kernel_version:
            logger.info(
                f"SERAPH_SKIP pkg={pkg_name} "
                f"reason=up_to_date kernel={current_kernel_version}"
            )
            return False

        logger.info(
            f"SERAPH_KERNEL_CHANGED pkg={pkg_name} "
            f"kernel={kernel_pkg_name} "
            f"built={built_kernel_version} current={current_kernel_version}"
        )

        return self.keymaker.bump(pkgbuild_path, current_kernel_version)

    def _query_package_version(self, pkg_name: str) -> Optional[str]:
        """
        Query the current version of a package via pacman.

        Args:
            pkg_name: Package name (e.g. 'linux61', 'linux-next')

        Returns:
            Version string or None on failure
        """
        try:
            result = subprocess.run(
                ['pacman', '-Si', pkg_name],
                capture_output=True, text=True, check=False, timeout=30
            )
            if result.returncode != 0:
                logger.warning(
                    f"SERAPH_PACMAN_QUERY_FAIL pkg={pkg_name} "
                    f"stderr={(result.stderr or '')[:200]}"
                )
                return None

            for line in result.stdout.splitlines():
                if line.startswith('Version'):
                    return line.split(':', 1)[1].strip()

            logger.warning(f"SERAPH_PACMAN_NO_VERSION pkg={pkg_name}")
            return None
        except subprocess.TimeoutExpired:
            logger.error(f"SERAPH_PACMAN_QUERY_TIMEOUT pkg={pkg_name}")
            return None
        except Exception as e:
            logger.error(f"SERAPH_PACMAN_QUERY_EXCEPTION pkg={pkg_name} error={e}")
            return None