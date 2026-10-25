"""
Keymaker Module - PKGBUILD version bumping for kernel modules

The Keymaker forges keys: when the kernel changes, the module's pkgrel
must be incremented so the build system recognizes a rebuild is needed.
"""

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Keymaker:
    """
    The Keymaker forges the keys that unlock rebuilds.

    Responsibilities:
      - Parse PKGBUILD for pkgrel
      - Increment pkgrel (integer: +1; decimal: +0.1)
      - Write back PKGBUILD (with revert on marker-creation failure)
      - Create .pending/<pkg> marker to prevent double-bumping
    """

    PENDING_DIR = ".pending"

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.pending_dir = repo_root / self.PENDING_DIR

    def bump(self, pkgbuild_path: Path, target_kernel_version: str) -> bool:
        """
        Bump pkgrel in PKGBUILD and create .pending marker.

        Args:
            pkgbuild_path: Path to PKGBUILD
            target_kernel_version: Kernel version that triggered this bump
                                   (stored in .pending/<pkg> for debugging)

        Returns:
            True if bump was performed, False if skipped or failed
        """
        if not pkgbuild_path.exists():
            logger.warning(f"KEYMAKER_BUMP_SKIP pkgbuild_missing path={pkgbuild_path}")
            return False

        pkg_name = pkgbuild_path.parent.name

        pending_marker = self.pending_dir / pkg_name
        if pending_marker.exists():
            logger.info(f"KEYMAKER_BUMP_SKIP pkg={pkg_name} reason=pending_exists")
            return False

        try:
            with open(pkgbuild_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            logger.error(f"KEYMAKER_BUMP_FAIL pkg={pkg_name} reason=read_error error={e}")
            return False

        pkgrel_match = re.search(r'^pkgrel\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$', content, re.MULTILINE)
        if not pkgrel_match:
            logger.warning(f"KEYMAKER_BUMP_SKIP pkg={pkg_name} reason=pkgrel_not_found")
            return False

        old_pkgrel_str = pkgrel_match.group(1)

        if '.' in old_pkgrel_str:
            old_pkgrel = float(old_pkgrel_str)
            new_pkgrel = round(old_pkgrel + 0.1, 1)
            new_pkgrel_str = f"{new_pkgrel:.1f}".rstrip('0').rstrip('.')
            if new_pkgrel_str == '':
                new_pkgrel_str = '0'
        else:
            new_pkgrel = int(old_pkgrel_str) + 1
            new_pkgrel_str = str(new_pkgrel)

        new_content = (
            content[:pkgrel_match.start(1)]
            + new_pkgrel_str
            + content[pkgrel_match.end(1):]
        )

        try:
            with open(pkgbuild_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        except Exception as e:
            logger.error(f"KEYMAKER_BUMP_FAIL pkg={pkg_name} reason=write_error error={e}")
            return False

        try:
            self.pending_dir.mkdir(parents=True, exist_ok=True)
            with open(pending_marker, 'w', encoding='utf-8') as f:
                f.write(target_kernel_version + '\n')
        except Exception as e:
            logger.error(f"KEYMAKER_PENDING_CREATE_FAIL pkg={pkg_name} error={e}")
            try:
                with open(pkgbuild_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logger.info(f"KEYMAKER_BUMP_REVERTED pkg={pkg_name}")
            except Exception as revert_err:
                logger.error(f"KEYMAKER_REVERT_FAIL pkg={pkg_name} error={revert_err}")
            return False

        logger.info(
            f"KEYMAKER_BUMPED pkg={pkg_name} "
            f"pkgrel={old_pkgrel_str}->{new_pkgrel_str} "
            f"target_kernel={target_kernel_version}"
        )
        return True