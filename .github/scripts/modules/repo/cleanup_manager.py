"""
Cleanup Manager Module - Handles Zero-Residue policy and server cleanup ONLY

CRITICAL: Version cleanup logic has been moved to SmartCleanup.
This module now handles ONLY:
- Server cleanup (VPS zombie package removal)
- Database file cleanup
- Orphan/unsigned signature enforcement
"""

import os
import subprocess
import shutil
import hashlib
import logging
import shlex
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class CleanupManager:
    """
    Manages server-side cleanup operations ONLY.

    This module handles:
    1. Server cleanup (removing zombie packages / orphaned signatures from VPS)
    2. Database file maintenance
    3. Signature hygiene enforcement (optional strict mode)
    """

    def __init__(self, config: dict):
        """
        Initialize CleanupManager with configuration

        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory
                - remote_dir: Remote directory on VPS
                - mirror_temp_dir: Temporary mirror directory
                - vps_user: VPS username
                - vps_host: VPS hostname

            Optional:
                - require_signatures: bool (default True)
                - keep_remote_files: list[str] (filenames to never delete on VPS)
        """
        self.repo_name = config["repo_name"]
        self.output_dir = Path(config["output_dir"])
        self.remote_dir = config["remote_dir"]
        self.mirror_temp_dir = Path(config.get("mirror_temp_dir", "/tmp/repo_mirror"))
        self.vps_user = config["vps_user"]
        self.vps_host = config["vps_host"]

        # Policy knobs
        self.require_signatures = bool(config.get("require_signatures", True))

        # Files to keep on VPS even if not in local output_dir (e.g. repo public key)
        default_keep = {f"{self.repo_name}.pub"}
        extra_keep = set(config.get("keep_remote_files", []) or [])
        self.keep_remote_files = default_keep | extra_keep

    # -----------------------------
    # Local-side hygiene (output_dir)
    # -----------------------------

    def revalidate_output_dir_before_database(self, allowlist: Optional[Set[str]] = None):
        """
        🚨 PRE-DATABASE VALIDATION: Remove outdated package versions and orphaned signatures.
        Operates ONLY on output_dir.

        Enforces:
        - Only the latest version of each package remains.
        - Orphaned .sig files (without a package) are removed.
        - Packages not in allowlist are removed (if allowlist provided).

        Additionally (if require_signatures=True):
        - Fails fast if there are unsigned packages in output_dir.

        Args:
            allowlist: Set of valid package names from PKGBUILD extraction (optional)
        """
        logger.info("🚨 PRE-DATABASE VALIDATION: Starting output_dir revalidation...")

        # Import SmartCleanup here to avoid circular imports
        from modules.repo.smart_cleanup import SmartCleanup

        smart_cleanup = SmartCleanup(self.repo_name, self.output_dir)

        # Step 1: Remove old package versions (keep only newest per package)
        smart_cleanup.remove_old_package_versions()

        # Step 2: Remove packages not in allowlist (if allowlist provided)
        if allowlist:
            smart_cleanup.remove_packages_not_in_allowlist(allowlist)

        # Step 3: Remove orphaned .sig files in output_dir
        self._remove_orphaned_signatures_local()

        # Step 4: Enforce signature policy locally (fail fast)
        if self.require_signatures:
            self._assert_all_local_packages_signed()

        logger.info("✅ PRE-DATABASE VALIDATION: Output directory revalidated successfully.")

    def _remove_orphaned_signatures_local(self):
        """Remove orphaned .sig files in output_dir that don't have a corresponding package"""
        logger.info("🔍 Checking for orphaned signature files in output_dir...")

        orphaned_count = 0
        for sig_file in self.output_dir.glob("*.sig"):
            # Corresponding file is sig without trailing ".sig"
            pkg_file = Path(str(sig_file)[:-4])
            if not pkg_file.exists():
                try:
                    sig_file.unlink()
                    logger.info(f"Removed orphaned signature (local): {sig_file.name}")
                    orphaned_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete orphaned signature {sig_file}: {e}")

        if orphaned_count > 0:
            logger.info(f"✅ Removed {orphaned_count} orphaned local signature files")
        else:
            logger.info("✅ No orphaned local signature files found")

    def _assert_all_local_packages_signed(self):
        """
        If require_signatures=True, ensure every package in output_dir has a .sig next to it.
        This prevents deploying unsigned packages.
        """
        pkgs = list(self.output_dir.glob("*.pkg.tar.zst")) + list(self.output_dir.glob("*.pkg.tar.xz"))
        if not pkgs:
            logger.info("No local packages found to enforce signing on.")
            return

        missing = []
        for pkg in pkgs:
            sig = Path(str(pkg) + ".sig")
            if not sig.exists():
                missing.append(pkg.name)

        if missing:
            logger.error("❌ UNSIGNED LOCAL PACKAGES DETECTED (missing .sig):")
            for n in missing[:50]:
                logger.error(f"  - {n}")
            if len(missing) > 50:
                logger.error(f"  ... plus {len(missing) - 50} more")
            raise RuntimeError(
                "Signature policy violation: some packages in output_dir are missing .sig. "
                "Fix signing step; refusing to proceed."
            )

    # -----------------------------
    # VPS cleanup (Zero-residue mirroring)
    # -----------------------------

    def cleanup_vps_orphaned_signatures(self) -> Tuple[int, int, int]:
        """
        🚨 VPS ORPHAN SIGNATURE SWEEP: Delete signature files without corresponding packages on VPS.

        Returns:
            Tuple of (package_count, signature_count, deleted_orphan_count)
        """
        remote_dir_hash = hashlib.sha256(self.remote_dir.encode()).hexdigest()[:8]
        logger.info(f"Starting VPS orphan signature sweep (remote_dir_hash: {remote_dir_hash})...")

        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory")
            return 0, 0, 0

        if not vps_files:
            logger.info("No files found on VPS")
            return 0, 0, 0

        package_files = set()
        signature_files = []

        for vps_file in vps_files:
            filename = Path(vps_file).name
            if filename.endswith(".sig"):
                signature_files.append(vps_file)
            elif filename.endswith((".pkg.tar.zst", ".pkg.tar.xz")):
                package_files.add(filename)

        orphaned = []
        for sig_path in signature_files:
            sig_name = Path(sig_path).name
            pkg_name = sig_name[:-4]
            if pkg_name.endswith((".pkg.tar.zst", ".pkg.tar.xz")) and pkg_name not in package_files:
                orphaned.append(sig_path)

        if not orphaned:
            logger.info("✅ No orphaned signatures found on VPS")
            return len(package_files), len(signature_files), 0

        logger.info(f"Found {len(orphaned)} orphaned signatures to delete on VPS")
        deleted = 0
        for i in range(0, len(orphaned), 50):
            batch = orphaned[i : i + 50]
            if self._delete_files_remote(batch):
                deleted += len(batch)

        logger.info(f"✅ Deleted {deleted} orphaned signatures from VPS")
        return len(package_files), len(signature_files), deleted

    def server_cleanup(self, version_tracker):
        """
        🚨 ZERO-RESIDUE SERVER CLEANUP: VPS should mirror local output_dir AFTER SmartCleanup.

        What it does:
        - Deletes VPS package files not present in local output_dir.
        - Deletes VPS signature files not present in local output_dir.
        - Deletes orphaned VPS signatures (no package).
        - Optionally enforces signing on VPS: deletes unsigned packages (no .sig on VPS).

        NOTE:
        - Database / files index artifacts are NOT touched here (handled elsewhere).
        - "keep_remote_files" are never deleted (e.g. repo public key).
        """
        logger.info("🚨 Server cleanup: Zero-residue mirroring VPS to local output_dir state...")

        if not self.output_dir.exists():
            logger.warning(f"Local output_dir does not exist: {self.output_dir} - skipping server cleanup")
            return

        # Desired state (local)
        local_packages = set(p.name for p in self.output_dir.glob("*.pkg.tar.zst")) | set(
            p.name for p in self.output_dir.glob("*.pkg.tar.xz")
        )
        local_sigs = set(s.name for s in self.output_dir.glob("*.pkg.tar.zst.sig")) | set(
            s.name for s in self.output_dir.glob("*.pkg.tar.xz.sig")
        )

        logger.info(f"Local desired state: {len(local_packages)} packages, {len(local_sigs)} signatures")

        # VPS inventory
        vps_files = self._get_vps_file_inventory()
        if vps_files is None:
            logger.error("Failed to get VPS file inventory - aborting server cleanup")
            return

        if not vps_files:
            logger.info("No files found on VPS - nothing to clean up")
            return

        # Build VPS sets
        vps_packages = set()
        vps_sigs = set()
        vps_pkg_paths = {}
        vps_sig_paths = {}

        for path in vps_files:
            name = Path(path).name

            # Always keep explicit keep list
            if name in self.keep_remote_files:
                continue

            # Ignore db/files artifacts here (they are regenerated elsewhere)
            if name.endswith((".db", ".db.tar.gz", ".files", ".files.tar.gz", ".abs.tar.gz", ".sig")):
                # NOTE: package sigs handled below; db/files sigs should not be deleted here
                # We'll only treat package sigs as deletable later (those end with .pkg.tar.*.sig)
                pass

            if name.endswith((".pkg.tar.zst", ".pkg.tar.xz")):
                vps_packages.add(name)
                vps_pkg_paths[name] = path
            elif name.endswith((".pkg.tar.zst.sig", ".pkg.tar.xz.sig")):
                vps_sigs.add(name)
                vps_sig_paths[name] = path

        files_to_delete: List[str] = []

        # 1) Delete orphaned sigs on VPS (sig without corresponding package on VPS)
        for sig_name in sorted(vps_sigs):
            pkg_name = sig_name[:-4]  # remove .sig
            if pkg_name not in vps_packages:
                files_to_delete.append(vps_sig_paths[sig_name])
                logger.info(f"Marking orphaned VPS signature for deletion: {sig_name} (missing {pkg_name})")

        # 2) Delete VPS packages not present locally
        for pkg_name in sorted(vps_packages):
            if pkg_name not in local_packages:
                files_to_delete.append(vps_pkg_paths[pkg_name])
                logger.info(f"Marking VPS package for deletion: {pkg_name} (not present locally)")

        # 3) Delete VPS package signatures not present locally
        for sig_name in sorted(vps_sigs):
            if sig_name not in local_sigs:
                # If it's already slated for deletion (orphan), no harm in re-adding check via set later
                files_to_delete.append(vps_sig_paths[sig_name])
                logger.info(f"Marking VPS signature for deletion: {sig_name} (not present locally)")

        # 4) Enforce signature policy on VPS (optional): delete unsigned packages on VPS
        if self.require_signatures:
            for pkg_name in sorted(vps_packages):
                sig_name = pkg_name + ".sig"
                if sig_name not in vps_sigs:
                    # If package remains on VPS unsigned, enforce by deleting it.
                    files_to_delete.append(vps_pkg_paths[pkg_name])
                    logger.info(f"Marking UNSIGNED VPS package for deletion: {pkg_name} (missing {sig_name} on VPS)")

        # Deduplicate preserving order
        seen = set()
        deduped = []
        for f in files_to_delete:
            if f not in seen:
                seen.add(f)
                deduped.append(f)
        files_to_delete = deduped

        if not files_to_delete:
            logger.info("✅ VPS is already consistent with local desired state (no deletions needed)")
            return

        logger.info(f"🚨 VPS cleanup: Deleting {len(files_to_delete)} files to enforce zero-residue policy")

        deleted_count = 0
        for i in range(0, len(files_to_delete), 50):
            batch = files_to_delete[i : i + 50]
            if self._delete_files_remote(batch):
                deleted_count += len(batch)

        logger.info(f"✅ Server cleanup complete: Deleted {deleted_count} files from VPS")

        # Final orphan sweep (in case deleting packages created new orphan sigs)
        try:
            _, _, orphan_deleted = self.cleanup_vps_orphaned_signatures()
            if orphan_deleted:
                logger.info(f"✅ Post-cleanup orphan sweep deleted {orphan_deleted} additional signatures")
        except Exception as e:
            logger.warning(f"Post-cleanup orphan sweep failed (non-fatal): {e}")

    # -----------------------------
    # VPS helpers
    # -----------------------------

    def _get_vps_file_inventory(self) -> Optional[List[str]]:
        """Get complete inventory of all relevant files on VPS"""
        logger.info("Getting complete VPS file inventory...")

        remote_cmd = rf"""
        find "{self.remote_dir}" -maxdepth 1 -type f \( \
            -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" -o \
            -name "*.pkg.tar.zst.sig" -o -name "*.pkg.tar.xz.sig" -o \
            -name "*.db" -o -name "*.db.tar.gz" -o -name "*.db.sig" -o -name "*.db.tar.gz.sig" -o \
            -name "*.files" -o -name "*.files.tar.gz" -o -name "*.files.sig" -o -name "*.files.tar.gz.sig" -o \
            -name "*.abs.tar.gz" -o -name "*.pub" \
        \) 2>/dev/null
        """

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
                logger.warning(f"Could not list VPS files: {result.stderr[:200]}")
                return None

            raw = result.stdout.strip()
            if not raw:
                logger.info("No files found on VPS")
                return []

            vps_files = [f.strip() for f in raw.split("\n") if f.strip()]
            logger.info(f"Found {len(vps_files)} files on VPS")
            return vps_files

        except subprocess.TimeoutExpired:
            logger.error("SSH timeout getting VPS file inventory")
            return None
        except Exception as e:
            logger.error(f"Error getting VPS file inventory: {e}")
            return None

    def _delete_files_remote(self, files_to_delete: List[str]) -> bool:
        """Delete files from remote server"""
        if not files_to_delete:
            return True

        # Robust quoting
        quoted = " ".join(shlex.quote(f) for f in files_to_delete)
        delete_cmd = f"rm -fv {quoted}"

        logger.info(f"Executing deletion command for {len(files_to_delete)} files")

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
                logger.info(f"Deletion successful for batch of {len(files_to_delete)} files")
                return True
            else:
                logger.error(f"Deletion failed: {result.stderr[:500]}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("SSH command timed out - aborting cleanup for safety")
            return False
        except Exception as e:
            logger.error(f"Error during deletion: {e}")
            return False

    # -----------------------------
    # Database cleanup (local)
    # -----------------------------

    def cleanup_database_files(self):
        """Clean up old database files from output directory"""
        logger.info("Cleaning up old database files...")

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

        deleted_count = 0
        for pattern in db_patterns:
            db_file = self.output_dir / pattern
            if db_file.exists():
                try:
                    db_file.unlink()
                    logger.info(f"Removed database file: {pattern}")
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Could not delete {pattern}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old database files")
        else:
            logger.info("No old database files to clean up")
