"""
Cleanup Manager Module - Handles Zero-Residue policy and server cleanup ONLY

CRITICAL: Version cleanup logic has been moved to SmartCleanup.
This module now handles ONLY:
- Server cleanup (VPS zombie package + orphan signature removal)
- Database file cleanup

Design principle:
- **Local output_dir is the source of truth.**
- VPS repo directory should be *mirrored* to match output_dir, except for repo DB/files artifacts
  that are regenerated.
"""

import subprocess
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class CleanupManager:
    """
    Manages server-side cleanup operations ONLY.

    This module only handles:
    1. VPS cleanup (make VPS mirror local output_dir packages + their signatures)
    2. Database file maintenance (local output_dir)
    """

    DB_SUFFIXES = (
        ".db",
        ".db.tar.gz",
        ".files",
        ".files.tar.gz",
        ".abs.tar.gz",
    )

    PKG_SUFFIXES = (
        ".pkg.tar.zst",
        ".pkg.tar.xz",
    )

    def __init__(self, config: dict):
        """
        Initialize CleanupManager with configuration.

        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory
                - remote_dir: Remote directory on VPS
                - mirror_temp_dir: Temporary mirror directory
                - vps_user: VPS username
                - vps_host: VPS hostname
        """
        self.repo_name = config["repo_name"]
        self.output_dir = Path(config["output_dir"])
        self.remote_dir = config["remote_dir"]
        self.mirror_temp_dir = Path(config.get("mirror_temp_dir", "/tmp/repo_mirror"))
        self.vps_user = config["vps_user"]
        self.vps_host = config["vps_host"]

    # ---------------------------
    # Local output_dir maintenance
    # ---------------------------

    def revalidate_output_dir_before_database(self, allowlist: Optional[Set[str]] = None) -> None:
        """
        🚨 PRE-DATABASE VALIDATION: Remove outdated package versions and orphaned signatures.
        Operates ONLY on output_dir.

        Enforces:
        - Only the latest version of each package remains.
        - Orphaned .sig files (without a package) are removed.
        - Packages not in allowlist are removed (if allowlist provided).

        Args:
            allowlist: Set of valid package names from PKGBUILD extraction (optional)
        """
        logger.info("🚨 PRE-DATABASE VALIDATION: Starting output_dir revalidation...")

        # Import SmartCleanup here to avoid circular imports
        from modules.repo.smart_cleanup import SmartCleanup

        smart_cleanup = SmartCleanup(self.repo_name, self.output_dir)

        # 1) Keep only newest per package
        smart_cleanup.remove_old_package_versions()

        # 2) Remove packages not in allowlist (if provided)
        if allowlist:
            smart_cleanup.remove_packages_not_in_allowlist(allowlist)

        # 3) Remove orphaned .sig files locally
        self._remove_orphaned_signatures_local()

        logger.info("✅ PRE-DATABASE VALIDATION: Output directory revalidated successfully.")

    def _remove_orphaned_signatures_local(self) -> None:
        """Remove orphaned .sig files in output_dir that don't have a corresponding package"""
        logger.info("🔍 Checking for orphaned signature files in output_dir...")

        orphaned = 0
        for sig_file in self.output_dir.glob("*.sig"):
            base_file = sig_file.with_suffix("")  # remove .sig
            if not base_file.exists():
                try:
                    sig_file.unlink()
                    logger.info("Removed orphaned signature: %s", sig_file.name)
                    orphaned += 1
                except Exception as e:
                    logger.warning("Could not delete orphaned signature %s: %s", sig_file, e)

        if orphaned:
            logger.info("✅ Removed %d orphaned signature files from output_dir", orphaned)
        else:
            logger.info("✅ No orphaned signatures found in output_dir")

    def cleanup_database_files(self) -> None:
        """Clean up old database files from output_dir"""
        logger.info("Cleaning up old database files from output_dir...")

        db_patterns = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz",
            f"{self.repo_name}.db.sig",
            f"{self.repo_name}.db.tar.gz.sig",
            f"{self.repo_name}.files.sig",
            f"{self.repo_name}.files.tar.gz.sig",
        ]

        deleted = 0
        for pattern in db_patterns:
            p = self.output_dir / pattern
            if p.exists():
                try:
                    p.unlink()
                    logger.info("Removed database file: %s", pattern)
                    deleted += 1
                except Exception as e:
                    logger.warning("Could not delete %s: %s", pattern, e)

        if deleted:
            logger.info("Cleaned up %d old database files", deleted)
        else:
            logger.info("No old database files to clean up")

    # ---------------------------
    # VPS cleanup (mirror output_dir)
    # ---------------------------

    def server_cleanup(self, version_tracker=None) -> Tuple[int, int]:
        """
        🚨 ZERO-RESIDUE SERVER CLEANUP (VPS):
        Make the VPS repo directory match local output_dir:

        - Delete any VPS package files that are not present locally (post SmartCleanup).
        - Delete any VPS .sig files that do not have a corresponding local file (package or db artifact).
        - Keep database/files artifacts (they will be regenerated) and the public key.

        Why this solves your current issues:
        - Orphaned .sig on VPS get deleted automatically (e.g. geany-plugin-preview...sig).
        - Old versions on VPS get deleted when a new version exists locally (e.g. qownnotes old versions).
        - Nothing is kept "just because it's on VPS" — VPS mirrors local state.

        Returns:
            (deleted_count, kept_count) based on VPS inventory.
        """
        logger.info("Server cleanup: Mirroring VPS to local output_dir state...")

        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory")
            return 0, 0

        if not vps_files:
            logger.info("No files found on VPS - nothing to clean up")
            return 0, 0

        # Local source of truth:
        local_files = set(p.name for p in self.output_dir.glob("*"))

        # Always keep the public key if present on VPS
        always_keep_names = {f"{self.repo_name}.pub", "manjaro-awesome.pub"}  # tolerate legacy name

        files_to_delete: List[str] = []
        kept = 0

        for vps_path in vps_files:
            name = Path(vps_path).name

            # Keep repo public key
            if name in always_keep_names or name.endswith(".pub"):
                kept += 1
                continue

            # Keep (or regenerate) DB/files artifacts - we do not delete these here
            if any(name.endswith(sfx) for sfx in self.DB_SUFFIXES) or any(
                name.endswith(sfx + ".sig") for sfx in self.DB_SUFFIXES
            ):
                kept += 1
                continue

            # For signatures: keep only if the corresponding base file exists locally
            if name.endswith(".sig"):
                base = name[:-4]
                if base in local_files:
                    kept += 1
                else:
                    files_to_delete.append(vps_path)
                    logger.info("Marking orphan signature for deletion: %s", name)
                continue

            # For packages: keep only if the package exists locally
            if any(name.endswith(sfx) for sfx in self.PKG_SUFFIXES):
                if name in local_files:
                    kept += 1
                else:
                    files_to_delete.append(vps_path)
                    logger.info("Marking package for deletion (not in local output): %s", name)
                continue

            # Any other file types: if not in local, delete (safe default)
            if name in local_files:
                kept += 1
            else:
                files_to_delete.append(vps_path)
                logger.info("Marking unknown extra file for deletion: %s", name)

        if not files_to_delete:
            logger.info("✅ VPS already matches local output_dir (no deletions required).")
            return 0, kept

        logger.info("VPS cleanup: %d files to delete, %d to keep", len(files_to_delete), kept)

        # Delete in batches
        batch_size = 50
        deleted = 0
        failures = 0

        for i in range(0, len(files_to_delete), batch_size):
            batch = files_to_delete[i : i + batch_size]
            if self._delete_files_remote(batch):
                deleted += len(batch)
            else:
                failures += len(batch)

        if failures:
            logger.error("❌ VPS cleanup had failures: failed_batches=%d", (failures + batch_size - 1) // batch_size)

        # Final orphan sweep (belt-and-suspenders)
        self.cleanup_vps_orphaned_signatures()

        logger.info("✅ Server cleanup complete: deleted=%d, kept=%d", deleted, kept)
        return deleted, kept

    def cleanup_vps_orphaned_signatures(self) -> Tuple[int, int, int]:
        """
        🚨 VPS ORPHAN SIGNATURE SWEEP:
        Delete signature files without corresponding packages on VPS.

        Returns:
            (package_count, signature_count, deleted_orphan_count)
        """
        remote_dir_hash = hashlib.sha256(self.remote_dir.encode()).hexdigest()[:8]
        logger.info("Starting VPS orphan signature sweep (remote_dir_hash: %s)...", remote_dir_hash)

        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory")
            return 0, 0, 0

        if not vps_files:
            logger.info("No files found on VPS")
            return 0, 0, 0

        package_files = set()
        signature_paths: List[str] = []

        for vps_path in vps_files:
            name = Path(vps_path).name
            if name.endswith(".sig"):
                signature_paths.append(vps_path)
            elif name.endswith(self.PKG_SUFFIXES):
                package_files.add(name)

        orphaned: List[str] = []
        for sig_path in signature_paths:
            sig_name = Path(sig_path).name
            base = sig_name[:-4]
            if base.endswith(self.PKG_SUFFIXES) and base not in package_files:
                orphaned.append(sig_path)

        if not orphaned:
            logger.info("✅ No orphaned signatures found on VPS")
            return len(package_files), len(signature_paths), 0

        logger.info("Found %d orphaned signatures to delete", len(orphaned))

        batch_size = 50
        deleted = 0
        for i in range(0, len(orphaned), batch_size):
            batch = orphaned[i : i + batch_size]
            if self._delete_files_remote(batch):
                deleted += len(batch)

        logger.info(
            "VPS orphan sweep complete: remote_dir_hash=%s packages=%d signatures=%d deleted_orphans=%d",
            remote_dir_hash,
            len(package_files),
            len(signature_paths),
            deleted,
        )
        return len(package_files), len(signature_paths), deleted

    # ---------------------------
    # Remote helpers
    # ---------------------------

    def _get_vps_file_inventory(self) -> Optional[List[str]]:
        """Get complete inventory of relevant files on VPS"""
        logger.info("Getting complete VPS file inventory...")

        remote_cmd = rf'''
        find "{self.remote_dir}" -maxdepth 1 -type f \
          \( -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" -o -name "*.sig" \
             -o -name "*.db" -o -name "*.db.tar.gz" -o -name "*.files" -o -name "*.files.tar.gz" \
             -o -name "*.abs.tar.gz" -o -name "*.pub" \) 2>/dev/null
        '''.strip()

        ssh_cmd = ["ssh", f"{self.vps_user}@{self.vps_host}", remote_cmd]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            if result.returncode != 0:
                logger.warning("Could not list VPS files: %s", (result.stderr or "")[:200])
                return None

            raw = (result.stdout or "").strip()
            if not raw:
                logger.info("No files found on VPS")
                return []

            vps_files = [line.strip() for line in raw.splitlines() if line.strip()]
            logger.info("Found %d files on VPS", len(vps_files))
            return vps_files

        except subprocess.TimeoutExpired:
            logger.error("SSH timeout getting VPS file inventory")
            return None
        except Exception as e:
            logger.error("Error getting VPS file inventory: %s", e)
            return None

    def _delete_files_remote(self, files_to_delete: List[str]) -> bool:
        """Delete files from remote server"""
        if not files_to_delete:
            return True

        # Quote each path for safety (paths come from find output)
        quoted = []
        for p in files_to_delete:
            p = str(p)
            # Safest: single-quote wrap, escape embedded quotes if any
            quoted.append("'" + p.replace("'", "'\\''") + "'")

        delete_cmd = "rm -fv " + " ".join(quoted)

        logger.info("Executing deletion command for %d files", len(files_to_delete))

        ssh_delete = ["ssh", f"{self.vps_user}@{self.vps_host}", delete_cmd]

        try:
            result = subprocess.run(
                ssh_delete,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )

            if result.returncode == 0:
                logger.info("Deletion successful for batch of %d files", len(files_to_delete))
                return True

            logger.error("Deletion failed: %s", (result.stderr or "")[:500])
            return False

        except subprocess.TimeoutExpired:
            logger.error("SSH command timed out - aborting cleanup for safety")
            return False
        except Exception as e:
            logger.error("Error during deletion: %s", e)
            return False
