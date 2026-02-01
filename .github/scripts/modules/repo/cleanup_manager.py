"""
Cleanup Manager Module - Authoritative cleanup API surface

CRITICAL:
- DatabaseManager expects CleanupManager.revalidate_output_dir_before_database()
- Cleanup decisions must be based on PKGBUILD-derived pkgname allowlist (manifest),
  plus version-based policy (keep newest per pkgname).
- VPS is mirror/target only. VPS must never expand allowlist or resurrect deletions.
- This module computes final local inventory and enforces VPS mirror deletions
  WITHOUT logging paths, usernames, IPs, or full SSH commands.
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Set, Iterable

logger = logging.getLogger(__name__)


class CleanupManager:
    """
    Authoritative cleanup API surface.

    Responsibilities:
    1) Local output_dir revalidation before database generation:
       - Version-based cleanup (keep newest per pkgname)
       - Allowlist-based cleanup (manifest derived from PKGBUILD pkgname)
       - Signature hygiene (remove orphan .sig)
       - Optional signature validation (only when verifiable; never by existence)
    2) VPS mirror enforcement (delete remote package/sig files not present locally),
       with safety valve to avoid wiping when local has no packages.
    """

    def __init__(self, config: dict):
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.mirror_temp_dir = Path(config.get('mirror_temp_dir', '/tmp/repo_mirror'))
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']

        # Manifest (PKGBUILD-derived pkgname allowlist)
        self._allowlist: Set[str] = set()

        # Optional GPG handler for signature verification (only if provided)
        self._gpg_handler = None

        # Local cleanup results
        self._last_local_deletions: List[str] = []

        # Final local inventory for VPS mirror enforcement (basenames only)
        self._final_local_inventory: Set[str] = set()

    def set_allowlist(self, allowlist: Set[str]):
        """Set PKGBUILD-derived allowlist (pkgname manifest)."""
        if allowlist:
            self._allowlist = set(allowlist)
            logger.info(f"🧾 Manifest allowlist loaded: {len(self._allowlist)} pkgnames")
        else:
            self._allowlist = set()
            logger.warning("⚠️ Manifest allowlist is empty")

    def set_gpg_handler(self, gpg_handler):
        """Optional: provide GPG handler so we can verify signatures (when possible)."""
        self._gpg_handler = gpg_handler

    def get_last_local_deletions(self) -> List[str]:
        """Get basenames deleted locally during the last revalidation run."""
        return list(self._last_local_deletions)

    def get_final_local_inventory(self) -> Set[str]:
        """Get the final local output_dir inventory basenames used for VPS mirror enforcement."""
        return set(self._final_local_inventory)

    def revalidate_output_dir_before_database(self):
        """
        🚨 PRE-DATABASE VALIDATION: Revalidate output_dir (local only).

        Enforces:
        1) Version-based cleanup (keep newest per pkgname, delete older pkg + matching .sig)
        2) Allowlist-based cleanup (delete packages whose pkgname not in allowlist)
        3) Signature hygiene (delete orphan .sig with no pkg)
        4) Optional invalid signature cleanup (only when verifiable; never by existence alone)

        Also computes:
        - final local inventory basenames for VPS mirror enforcement
        - last local deletions list (basenames only)
        """
        logger.info("🚨 PRE-DATABASE VALIDATION: Starting output_dir revalidation...")

        # Import SmartCleanup here to avoid circular imports
        from modules.repo.smart_cleanup import SmartCleanup

        smart_cleanup = SmartCleanup(self.repo_name, self.output_dir)

        deleted: List[str] = []

        # Step 1: version cleanup (evidence-based: only deletes when multiple versions exist)
        deleted.extend(smart_cleanup.remove_old_package_versions())

        # Step 2: allowlist cleanup (manifest-based; never uses VPS to expand)
        if self._allowlist:
            deleted.extend(smart_cleanup.remove_packages_not_in_allowlist(self._allowlist))
        else:
            logger.warning("⚠️ No allowlist set - skipping allowlist cleanup for safety")

        # Step 3: signature hygiene (orphan .sig)
        deleted.extend(smart_cleanup.cleanup_orphan_signatures())

        # Step 4: optional signature validation (only if verifiable)
        if self._gpg_handler:
            deleted.extend(smart_cleanup.cleanup_invalid_signatures(self._gpg_handler))

        # Store local deletions (basenames only)
        self._last_local_deletions = list(dict.fromkeys([Path(x).name for x in deleted if x]))

        # Compute final local inventory (basenames only) for mirror enforcement
        self._final_local_inventory = self._compute_local_inventory()

        # Safety log (counts only)
        pkg_count = self._count_local_packages()
        logger.info(f"✅ PRE-DATABASE VALIDATION complete: packages={pkg_count}, deleted={len(self._last_local_deletions)}")

    def server_cleanup(self, version_tracker):
        """
        🚨 VPS MIRROR ENFORCEMENT: Remove remote package/sig files that are NOT present
        in the final local output_dir inventory.

        CRITICAL:
        - Never uses VPS state to expand manifest/allowlist.
        - Does not delete database files or other non-package artifacts.
        - Safety valve: if local has zero packages, skip deletions (must not wipe repo).

        Backward-compatible behavior:
        - If final local inventory is not available, fall back to legacy target-version logic
          (but still avoids path/command logging).
        """
        # Prefer authoritative local inventory when available
        if self._final_local_inventory:
            self._server_cleanup_by_local_inventory()
            return

        # Legacy fallback (kept for backward compatibility)
        self._server_cleanup_legacy_target_versions(version_tracker)

    def _server_cleanup_by_local_inventory(self):
        """Delete remote package/sig basenames not present in local inventory (db files excluded)."""
        local_pkg_count = self._count_local_packages()
        if local_pkg_count == 0:
            logger.warning("⚠️ Safety valve: local package count is 0 - skipping VPS deletions")
            return

        remote_files = self._list_vps_basenames()
        if remote_files is None:
            logger.error("Failed to list VPS files")
            return

        if not remote_files:
            logger.info("No VPS files found - nothing to delete")
            return

        to_delete: List[str] = []

        for name in remote_files:
            if self._is_database_or_repo_artifact(name):
                continue  # never delete db/files artifacts here

            # Consider only package files and their signatures
            if self._is_package_file(name) or self._is_package_signature(name):
                if name not in self._final_local_inventory:
                    to_delete.append(name)

        if not to_delete:
            logger.info("✅ VPS mirror already matches local output_dir (no deletions needed)")
            return

        logger.info(f"🧹 VPS cleanup: deleting {len(to_delete)} obsolete files (basenames only)")
        self._delete_remote_basenames(to_delete)

    def _server_cleanup_legacy_target_versions(self, version_tracker):
        """
        Legacy cleanup logic based on target versions (kept).
        Updated to avoid logging paths/commands and to delete basenames safely.
        """
        logger.info("Legacy VPS cleanup: Removing zombie packages using target versions...")

        if not getattr(version_tracker, "_package_target_versions", None):
            logger.warning("No target versions registered - skipping legacy server cleanup")
            return

        remote_files = self._list_vps_basenames()
        if remote_files is None:
            logger.error("Failed to list VPS files")
            return

        to_delete: List[str] = []

        for filename in remote_files:
            if self._is_database_or_repo_artifact(filename):
                continue

            if not self._is_package_file(filename):
                continue

            pkg_name = self._extract_pkgname_basic(filename)
            if not pkg_name:
                continue  # keep unknowns

            if pkg_name in version_tracker._package_target_versions:
                continue
            if pkg_name in getattr(version_tracker, "_skipped_packages", {}):
                continue

            to_delete.append(filename)

            # Also delete matching signature if present remotely
            sig_name = filename + ".sig"
            if sig_name in remote_files:
                to_delete.append(sig_name)

        if not to_delete:
            logger.info("✅ Legacy VPS cleanup: no zombie files detected")
            return

        logger.info(f"🧹 Legacy VPS cleanup: deleting {len(to_delete)} files (basenames only)")
        self._delete_remote_basenames(list(dict.fromkeys(to_delete)))

    def _compute_local_inventory(self) -> Set[str]:
        """Compute local output_dir basenames for packages, signatures, and repo artifacts."""
        names: Set[str] = set()
        if not self.output_dir.exists():
            return names

        # Keep only basenames
        for p in self.output_dir.iterdir():
            if not p.is_file():
                continue
            names.add(p.name)

        return names

    def _count_local_packages(self) -> int:
        """Count local package files (used for safety valve)."""
        if not self.output_dir.exists():
            return 0
        return len(list(self.output_dir.glob("*.pkg.tar.*")))

    def _list_vps_basenames(self) -> Optional[List[str]]:
        """
        List VPS basenames in remote_dir (no paths returned).
        Includes package files, their signatures, and repo artifacts.
        """
        # Basename-only listing; no absolute paths.
        remote_cmd = r"""
        set -e
        cd "$1" 2>/dev/null || exit 0
        ls -1 2>/dev/null || true
        """
        ssh_cmd = ["ssh", f"{self.vps_user}@{self.vps_host}", "bash", "-lc", remote_cmd, "--", self.remote_dir]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            if result.returncode != 0:
                # Do not log stderr (may contain paths)
                return None

            raw = (result.stdout or "").strip()
            if not raw:
                return []

            # Filter to relevant filetypes only (basenames)
            all_names = [line.strip() for line in raw.splitlines() if line.strip()]
            relevant = []
            for name in all_names:
                if self._is_relevant_remote_file(name):
                    relevant.append(name)

            logger.info(f"📦 VPS inventory: {len(relevant)} relevant files")
            return relevant

        except subprocess.TimeoutExpired:
            logger.error("SSH timeout while listing VPS files")
            return None
        except Exception:
            logger.error("Error while listing VPS files")
            return None

    def _delete_remote_basenames(self, basenames: List[str]) -> bool:
        """
        Delete remote files by basenames only (no paths logged).
        Uses: cd remote_dir && rm -f -- <names...>
        """
        if not basenames:
            return True

        # Safety: only allow deletion of relevant file types
        safe_names = [n for n in basenames if self._is_relevant_remote_file(n)]
        if not safe_names:
            return True

        # Chunk deletions to avoid argv limits
        batch_size = 80
        ok = True

        for i in range(0, len(safe_names), batch_size):
            batch = safe_names[i:i + batch_size]
            ok = self._delete_remote_batch(batch) and ok

        return ok

    def _delete_remote_batch(self, batch: List[str]) -> bool:
        # Pass filenames as args to avoid quoting issues.
        remote_cmd = r"""
        set -e
        cd "$1" 2>/dev/null || exit 0
        shift
        rm -f -- "$@" 2>/dev/null || true
        """
        ssh_cmd = ["ssh", f"{self.vps_user}@{self.vps_host}", "bash", "-lc", remote_cmd, "--", self.remote_dir] + batch

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=60
            )
            # Do not log stdout/stderr (may include filenames/paths from shell errors)
            if result.returncode == 0:
                return True
            return False
        except subprocess.TimeoutExpired:
            logger.error("SSH timeout during VPS deletion batch")
            return False
        except Exception:
            logger.error("Error during VPS deletion batch")
            return False

    def _is_package_file(self, name: str) -> bool:
        return name.endswith((".pkg.tar.zst", ".pkg.tar.xz"))

    def _is_package_signature(self, name: str) -> bool:
        # Package signatures are "<packagefile>.sig"
        return name.endswith((".pkg.tar.zst.sig", ".pkg.tar.xz.sig"))

    def _is_database_or_repo_artifact(self, name: str) -> bool:
        return name.endswith((
            ".db", ".db.tar.gz", ".files", ".files.tar.gz",
            ".db.sig", ".db.tar.gz.sig", ".files.sig", ".files.tar.gz.sig",
            ".abs.tar.gz",
        ))

    def _is_relevant_remote_file(self, name: str) -> bool:
        if self._is_package_file(name) or self._is_package_signature(name):
            return True
        if self._is_database_or_repo_artifact(name):
            return True
        # Also include standalone .sig (e.g., legacy naming), but keep it limited
        if name.endswith(".sig"):
            return True
        return False

    def _extract_pkgname_basic(self, filename: str) -> Optional[str]:
        """
        Basic pkgname extraction from filename.
        Keeps unknowns safe by returning None on ambiguity.
        """
        try:
            base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base.split('-')
            for i in range(len(parts) - 3, 0, -1):
                potential_name = '-'.join(parts[:i])
                remaining = parts[i:]
                if len(remaining) >= 3 and (remaining[0].isdigit() or any(c.isdigit() for c in remaining[0])):
                    return potential_name
        except Exception:
            return None
        return None

    def cleanup_database_files(self):
        """Clean up old database files from local output directory (basenames only in logs)."""
        db_patterns = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz",
            f"{self.repo_name}.db.sig",
            f"{self.repo_name}.db.tar.gz.sig",
            f"{self.repo_name}.files.sig",
            f"{self.repo_name}.files.tar.gz.sig"
        ]

        deleted_count = 0
        for pattern in db_patterns:
            db_file = self.output_dir / pattern
            if db_file.exists():
                try:
                    db_file.unlink(missing_ok=True)
                    deleted_count += 1
                except Exception:
                    pass

        if deleted_count > 0:
            logger.info(f"🧹 Local DB cleanup: removed {deleted_count} files")
        else:
            logger.info("🧹 Local DB cleanup: no files removed")
