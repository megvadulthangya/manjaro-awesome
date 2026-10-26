"""
Link Module - Git commit + push with PAT to trigger build workflows

Link is the transporter: he carries Keymaker's forged keys to the remote,
and his push event (with a PAT, not GITHUB_TOKEN) triggers the build.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


class Link:
    """
    Link transports changes to the remote and triggers builds.

    Uses a PAT (LINK_PUSH_TOKEN) so the push event's actor is not
    'github-actions[bot]' and thus the build workflow's guard passes.
    """

    LINK_NAME = "Link"
    LINK_EMAIL = "link@matrix.bot"

    def __init__(self, repo_root: Path, token: str = None):
        self.repo_root = repo_root
        self.token = token or os.getenv('LINK_PUSH_TOKEN')

    def push(self, bumped: List[Tuple[str, Path]]) -> bool:
        """
        Commit Keymaker's bumps and push with PAT.

        Args:
            bumped: List of (pkg_name, pkgbuild_path) tuples

        Returns:
            True if push succeeded (or nothing to do), False on failure
        """
        if not self.token:
            logger.error("LINK_PUSH_FAIL reason=no_token (LINK_PUSH_TOKEN env var not set)")
            return False

        if not bumped:
            logger.info("LINK_PUSH_SKIP reason=no_bumps")
            return True

        # ---------------------------------------------------------------
        # DIAGNOSTIC: verify .git exists before any git operation.
        # "fatal: not in a git directory" means git could not find .git
        # via discovery from repo_root. Log the actual state so the root
        # cause is visible in the run log (missing .git vs. broken
        # ownership vs. symlink resolution issue).
        # ---------------------------------------------------------------
        git_marker = self.repo_root / '.git'
        if not git_marker.exists():
            try:
                entries = sorted(p.name for p in self.repo_root.iterdir())
            except Exception as e:
                entries = [f"<iterdir failed: {e}>"]
            logger.error(
                f"LINK_NO_GIT_DIR path={self.repo_root} entries={entries[:40]}"
            )
            return False

        if git_marker.is_file():
            # Worktree / submodule gitfile
            try:
                target = git_marker.read_text(encoding='utf-8', errors='replace').strip()
                logger.info(f"LINK_GIT_DIR_IS_FILE target={target[:200]}")
            except Exception as e:
                logger.warning(f"LINK_GIT_DIR_READ_FAIL error={e}")

        # Ownership-agnostic access: allow any user (root / builder / etc.)
        # to operate on this repository regardless of who ran checkout.
        try:
            subprocess.run(
                ['git', 'config', '--global', '--add', 'safe.directory', str(self.repo_root)],
                check=False, capture_output=True, text=True, timeout=10
            )
        except Exception as e:
            logger.warning(f"LINK_SAFE_DIRECTORY_WARN error={e}")

        try:
            subprocess.run(
                ['git', '-C', str(self.repo_root), 'config', 'user.name', self.LINK_NAME],
                check=True, capture_output=True, text=True
            )
            subprocess.run(
                ['git', '-C', str(self.repo_root), 'config', 'user.email', self.LINK_EMAIL],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"LINK_GIT_CONFIG_FAIL error={(e.stderr or '')[:300]}")
            return False

        paths_to_add = []
        for _pkg_name, pkgbuild_path in bumped:
            try:
                rel = pkgbuild_path.relative_to(self.repo_root)
                paths_to_add.append(str(rel))
            except ValueError:
                paths_to_add.append(str(pkgbuild_path))

        pending_dir = self.repo_root / ".pending"
        if pending_dir.exists():
            paths_to_add.append(".pending")

        if not paths_to_add:
            logger.info("LINK_PUSH_SKIP reason=no_paths")
            return True

        try:
            subprocess.run(
                ['git', '-C', str(self.repo_root), 'add'] + paths_to_add,
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"LINK_GIT_ADD_FAIL error={(e.stderr or '')[:200]}")
            return False

        diff_result = subprocess.run(
            ['git', '-C', str(self.repo_root), 'diff', '--cached', '--quiet'],
            capture_output=True, text=True
        )
        if diff_result.returncode == 0:
            logger.info("LINK_PUSH_SKIP reason=nothing_staged")
            return True

        pkg_names = [name for name, _ in bumped]
        commit_msg = f"[Keymaker -> Link] bumped and pushed: {', '.join(pkg_names)}"

        try:
            subprocess.run(
                ['git', '-C', str(self.repo_root), 'commit', '-m', commit_msg],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"LINK_GIT_COMMIT_FAIL error={(e.stderr or '')[:200]}")
            return False

        repo_slug = os.getenv('GITHUB_REPOSITORY')
        if repo_slug:
            auth_url = f"https://x-access-token:{self.token}@github.com/{repo_slug}.git"
            try:
                subprocess.run(
                    ['git', '-C', str(self.repo_root), 'remote', 'set-url', 'origin', auth_url],
                    check=False, capture_output=True, text=True
                )
            except Exception as e:
                logger.warning(f"LINK_REMOTE_SETURL_WARN error={e}")

        try:
            push_result = subprocess.run(
                ['git', '-C', str(self.repo_root), 'push', 'origin', 'HEAD'],
                capture_output=True, text=True, timeout=120
            )
            if push_result.returncode != 0:
                logger.error(f"LINK_PUSH_FAIL error={(push_result.stderr or '')[:300]}")
                return False
        except Exception as e:
            logger.error(f"LINK_PUSH_EXCEPTION error={e}")
            return False

        logger.info(f"LINK_PUSHED pkgs={pkg_names} msg={commit_msg}")
        return True