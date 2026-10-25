"""
Architect Module - Records built kernel module versions to .build_tracking/

The Architect remembers: for each kernel module, which kernel version
was successfully built against. This record is the source of truth
used by Seraph to detect kernel changes.

Uses GITHUB_TOKEN (bot actor) so the resulting push does NOT re-trigger
the build workflow — avoiding infinite loops.

Push race safety: Hokibot may push commits to origin/main during the
build. Before pushing, Architect fetches and rebases onto origin/main.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)


class Architect:
    """
    The Architect records successful builds.
    """

    ARCHITECT_NAME = "Architect"
    ARCHITECT_EMAIL = "architect@matrix.bot"

    TRACKING_DIR = ".build_tracking"
    PENDING_DIR = ".pending"

    def __init__(self, repo_root: Path, token: str = None):
        self.repo_root = repo_root
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.tracking_dir = repo_root / self.TRACKING_DIR
        self.pending_dir = repo_root / self.PENDING_DIR

    def record(self, kernel_module_builds: List[Dict]) -> bool:
        """
        Record successful kernel module builds.

        Args:
            kernel_module_builds: List of dicts with keys:
                - pkg_name: Package name (e.g. 'linux61-nvidia-340xx')
                - kernel_version: Kernel version built against (e.g. '6.1.189-1')

        Returns:
            True if recording + commit + push succeeded (or nothing to do),
            False on failure
        """
        if not kernel_module_builds:
            logger.info("ARCHITECT_RECORD_SKIP reason=no_builds")
            return True

        recorded = []
        seen_pkgs = set()
        try:
            self.tracking_dir.mkdir(parents=True, exist_ok=True)
            for build in kernel_module_builds:
                pkg_name = build['pkg_name']
                kernel_version = build['kernel_version']

                # Dedup: same pkg may appear twice (success + skip paths)
                if pkg_name in seen_pkgs:
                    continue
                seen_pkgs.add(pkg_name)

                tracking_file = self.tracking_dir / pkg_name
                with open(tracking_file, 'w', encoding='utf-8') as f:
                    f.write(kernel_version + '\n')

                pending_marker = self.pending_dir / pkg_name
                if pending_marker.exists():
                    try:
                        pending_marker.unlink()
                    except Exception as e:
                        logger.warning(f"ARCHITECT_PENDING_CLEAR_FAIL pkg={pkg_name} error={e}")

                recorded.append((pkg_name, kernel_version))
                logger.info(f"ARCHITECT_RECORDED pkg={pkg_name} kernel={kernel_version}")
        except Exception as e:
            logger.error(f"ARCHITECT_RECORD_FAIL error={e}")
            return False

        if not self.token:
            logger.warning(
                "ARCHITECT_COMMIT_SKIP reason=no_token "
                "(tracking files written but not committed)"
            )
            return True

        return self._commit_and_push(recorded)

    def _commit_and_push(self, recorded: List) -> bool:
        """Commit tracking files and push with GITHUB_TOKEN."""
        try:
            subprocess.run(
                ['git', '-C', str(self.repo_root), 'config', 'user.name', self.ARCHITECT_NAME],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                ['git', '-C', str(self.repo_root), 'config', 'user.email', self.ARCHITECT_EMAIL],
                check=True, capture_output=True, text=True
            )

            # Stage tracking files (force-add to bypass any gitignore surprises)
            subprocess.run(
                ['git', '-C', str(self.repo_root), 'add', '-f', self.TRACKING_DIR],
                check=True, capture_output=True, text=True
            )
            if self.pending_dir.exists():
                subprocess.run(
                    ['git', '-C', str(self.repo_root), 'add', '-A', '-f', self.PENDING_DIR],
                    check=False, capture_output=True, text=True
                )

            diff_result = subprocess.run(
                ['git', '-C', str(self.repo_root), 'diff', '--cached', '--quiet'],
                capture_output=True, text=True
            )
            if diff_result.returncode == 0:
                logger.info("ARCHITECT_COMMIT_SKIP reason=nothing_staged")
                return True

            summary = ', '.join(f"{pkg} -> {ver}" for pkg, ver in recorded)
            commit_msg = f"[Architect] recorded {summary}"

            subprocess.run(
                ['git', '-C', str(self.repo_root), 'commit', '-m', commit_msg],
                check=True, capture_output=True, text=True
            )

            # Set auth URL for fetch/push
            repo_slug = os.getenv('GITHUB_REPOSITORY')
            if repo_slug:
                auth_url = f"https://x-access-token:{self.token}@github.com/{repo_slug}.git"
                subprocess.run(
                    ['git', '-C', str(self.repo_root), 'remote', 'set-url', 'origin', auth_url],
                    check=False, capture_output=True, text=True
                )

            # Fetch + rebase to handle race condition with Hokibot
            try:
                subprocess.run(
                    ['git', '-C', str(self.repo_root), 'fetch', 'origin', 'main'],
                    check=True, capture_output=True, text=True, timeout=60
                )
            except subprocess.CalledProcessError as e:
                logger.error(f"ARCHITECT_FETCH_FAIL error={(e.stderr or '')[:200]}")
                return False

            rebase_result = subprocess.run(
                ['git', '-C', str(self.repo_root), 'rebase', 'origin/main'],
                capture_output=True, text=True, timeout=60
            )
            if rebase_result.returncode != 0:
                logger.error(f"ARCHITECT_REBASE_FAIL error={(rebase_result.stderr or '')[:300]}")
                subprocess.run(
                    ['git', '-C', str(self.repo_root), 'rebase', '--abort'],
                    check=False, capture_output=True, text=True
                )
                return False

            push_result = subprocess.run(
                ['git', '-C', str(self.repo_root), 'push', 'origin', 'HEAD:main'],
                capture_output=True, text=True, timeout=120
            )
            if push_result.returncode != 0:
                logger.error(f"ARCHITECT_PUSH_FAIL error={(push_result.stderr or '')[:300]}")
                return False

            logger.info(f"ARCHITECT_COMMITTED_AND_PUSHED msg={commit_msg}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"ARCHITECT_GIT_FAIL error={(e.stderr or '')[:300]}")
            return False
        except Exception as e:
            logger.error(f"ARCHITECT_PUSH_EXCEPTION error={e}")
            return False