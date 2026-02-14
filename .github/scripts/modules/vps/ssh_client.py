"""
SSH Client Module - Handles SSH connections and remote VPS operations
WITH STAGING SUPPORT FOR ATOMIC PUBLISH AND PROMOTION LOCK
"""

import os
import subprocess
import shutil
import logging
import random
import string
import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Set

logger = logging.getLogger(__name__)


class SSHClient:
    """Handles SSH connections and remote VPS operations"""

    def __init__(self, config: dict):
        """
        Initialize SSHClient with configuration

        Args:
            config: Dictionary containing:
                - vps_user: VPS username
                - vps_host: VPS hostname
                - remote_dir: Remote directory on VPS
                - ssh_options: SSH options list
                - repo_name: Repository name
        """
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        self.remote_dir = config['remote_dir']
        self.ssh_options = config.get('ssh_options', [])
        self.repo_name = config.get('repo_name', '')

    def generate_run_id(self) -> str:
        """
        Generate a unique run ID for staging directory.
        Uses GITHUB_RUN_ID environment variable if available, otherwise timestamp + random.

        Returns:
            String identifier for the CI run
        """
        github_run_id = os.getenv('GITHUB_RUN_ID')
        if github_run_id:
            return f"run_{github_run_id}"
        else:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
            return f"{timestamp}_{suffix}"

    def ensure_staging_dir(self, run_id: str) -> bool:
        """
        Create staging directory on VPS under REMOTE_DIR/.staging/<run_id>/
        Ensures parent .staging exists and has correct permissions.

        Args:
            run_id: Unique run identifier

        Returns:
            True if directory exists/was created, False on failure
        """
        staging_parent = f"{self.remote_dir}/.staging"
        staging_dir = f"{staging_parent}/{run_id}"

        remote_cmd = f"""
        # Create staging parent if not exists
        if [ ! -d "{staging_parent}" ]; then
            mkdir -p "{staging_parent}"
            chmod 755 "{staging_parent}"
        fi
        # Create staging directory
        mkdir -p "{staging_dir}"
        chmod 755 "{staging_dir}"
        """

        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", remote_cmd]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )
            if result.returncode == 0:
                logger.info(f"STAGING_DIR_CREATED=1 path={staging_dir}")
                return True
            else:
                logger.error(f"STAGING_DIR_CREATE_FAIL path={staging_dir} error={result.stderr[:200]}")
                return False
        except Exception as e:
            logger.error(f"STAGING_DIR_CREATE_EXCEPTION path={staging_dir} error={str(e)[:200]}")
            return False

    def promote_staging(self, run_id: str) -> bool:
        """
        Atomically promote staging directory to live REMOTE_DIR.
        Acquires a remote lock before moving files to prevent concurrent promotions.
        Moves all files from staging dir to remote_dir, then removes staging dir.

        If mv fails with "are the same file" (due to --link-dest hardlinks),
        the file is skipped, the staging copy is removed, and promotion continues.

        Args:
            run_id: Unique run identifier (staging dir name)

        Returns:
            True if promotion succeeded, False otherwise.
            On failure, staging dir is left intact for debugging.
        """
        staging_dir = f"{self.remote_dir}/.staging/{run_id}"
        lock_dir = f"{self.remote_dir}/.staging/.promote.lock"

        remote_cmd = f"""
set -e
lock_dir="{lock_dir}"
if ! mkdir "$lock_dir" 2>/dev/null; then
    echo "LOCK_ACQUIRE_FAIL"
    exit 1
fi
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT

if [ ! -d "{staging_dir}" ]; then
    echo "STAGING_MISSING"
    exit 1
fi
# Move files (including hidden) but not directories
for f in "{staging_dir}"/* "{staging_dir}"/.[!.]*; do
    [ -f "$f" ] || [ -L "$f" ] || continue
    # Attempt move, capture stderr on failure
    if ! output=$(mv -f "$f" "{self.remote_dir}/" 2>&1); then
        # Check if error is due to source and destination being the same file
        if echo "$output" | grep -q "are the same file"; then
            echo "STAGING_PROMOTE_SKIP_SAME_FILE file=$(basename "$f")"
            rm -f "$f"
        else
            echo "mv failed for $(basename "$f"): $output"
            exit 1
        fi
    fi
done
# Check if any files remain (move failures)
remaining=$(ls -A "{staging_dir}" 2>/dev/null | wc -l)
if [ "$remaining" -gt 0 ]; then
    echo "PROMOTE_PARTIAL remaining=$remaining"
    exit 1
fi
# Remove empty staging dir
rmdir "{staging_dir}" 2>/dev/null
# Remove parent .staging if empty (best effort)
rmdir "{self.remote_dir}/.staging" 2>/dev/null || true
echo "PROMOTE_SUCCESS"
"""

        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", remote_cmd]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=60
            )

            if result.returncode == 0 and "PROMOTE_SUCCESS" in result.stdout:
                logger.info(f"STAGING_PROMOTE_OK run_id={run_id}")
                return True
            else:
                error_snip = result.stderr[:200] if result.stderr else "unknown"
                if "LOCK_ACQUIRE_FAIL" in result.stdout:
                    logger.error(f"STAGING_PROMOTE_LOCK_BUSY run_id={run_id}")
                else:
                    logger.error(f"STAGING_PROMOTE_FAIL run_id={run_id} error={error_snip}")
                return False

        except Exception as e:
            logger.error(f"STAGING_PROMOTE_EXCEPTION run_id={run_id} error={str(e)[:200]}")
            return False

    def cleanup_old_staging(self, max_age_hours: int = 24) -> bool:
        """
        Delete staging directories older than max_age_hours under REMOTE_DIR/.staging/.
        Only directories matching 'run_*' are considered for deletion.
        The lock directory (.promote.lock) is never deleted by this operation.
        Safe, best-effort cleanup – failures are logged but do not abort the pipeline.

        Args:
            max_age_hours: Age threshold in hours (default 24)

        Returns:
            True if the remote command executed without fatal errors, else False.
            Does not indicate whether any directories were actually deleted.
        """
        staging_parent = f"{self.remote_dir}/.staging"
        minutes = max_age_hours * 60

        remote_cmd = f"""
mkdir -p "{staging_parent}" || echo "MKDIR_FAIL"
find "{staging_parent}" -maxdepth 1 -type d -name 'run_*' -mmin +{minutes} -exec rm -rf {{}} \\; -print 2>&1 || echo "FIND_FAIL"
echo "CLEANUP_OK"
"""
        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", remote_cmd]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=60
            )
            if result.stdout:
                logger.debug(f"STALE_STAGING_CLEANUP_STDOUT: {result.stdout[:500]}")
            if result.stderr:
                logger.warning(f"STALE_STAGING_CLEANUP_STDERR: {result.stderr[:500]}")

            if result.returncode == 0 and "CLEANUP_OK" in result.stdout:
                logger.info(f"STALE_STAGING_CLEANUP: removed directories older than {max_age_hours}h")
                return True
            else:
                logger.warning(f"STALE_STAGING_CLEANUP_FAIL: rc={result.returncode} stderr={result.stderr[:200]}")
                return False
        except Exception as e:
            logger.error(f"STALE_STAGING_CLEANUP_EXCEPTION: {e}")
            return False

    def list_remote_files(self, remote_path: Optional[str] = None) -> List[str]:
        """
        List all files (regular files and symlinks) in remote_path.
        Returns basenames only.

        Args:
            remote_path: Remote directory to list (defaults to self.remote_dir)

        Returns:
            List of filenames (basenames) or empty list on failure
        """
        target = remote_path if remote_path is not None else self.remote_dir

        ssh_cmd = [
            "ssh",
            *self.ssh_options,
            f"{self.vps_user}@{self.vps_host}",
            rf'find "{target}" -maxdepth 1 \( -type f -o -type l \) -printf "%f\\n" 2>/dev/null || echo "NO_FILES"'
        ]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )

            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n')
                         if f.strip() and f.strip() != 'NO_FILES']
                logger.info(f"REMOTE_FILE_LIST path={target} count={len(files)}")
                return files
            else:
                logger.warning(f"REMOTE_FILE_LIST_FAIL path={target}")
                return []

        except Exception as e:
            logger.warning(f"REMOTE_FILE_LIST_EXCEPTION path={target} error={str(e)[:200]}")
            return []

    def verify_upload(self, expected_basenames: Set[str], remote_path: Optional[str] = None) -> Tuple[bool, List[str]]:
        """
        Verify that all expected files exist on remote server.

        Args:
            expected_basenames: Set of filenames that should be present
            remote_path: Remote directory to check (defaults to self.remote_dir)

        Returns:
            Tuple of (success: bool, missing_files: List[str])
        """
        target = remote_path if remote_path is not None else self.remote_dir
        remote_files = set(self.list_remote_files(target))

        missing = list(expected_basenames - remote_files)
        extra = list(remote_files - expected_basenames)

        logger.info(f"VERIFY_REMOTE: target={target}")
        logger.info(f"VERIFY_REMOTE: expected={len(expected_basenames)} remote={len(remote_files)}")
        logger.info(f"VERIFY_REMOTE: missing={len(missing)} extra={len(extra)}")

        if missing:
            logger.error(f"VERIFY_REMOTE: MISSING_FILES (first 20): {missing[:20]}")
        if extra:
            logger.info(f"VERIFY_REMOTE: EXTRA_FILES (first 20): {extra[:20]}")

        success = len(missing) == 0
        return success, missing

    def setup_ssh_config(self, ssh_key: Optional[str] = None):
        """Setup SSH config file for builder user - container invariant"""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)

        config_content = f"""Host {self.vps_host}
  HostName {self.vps_host}
  User {self.vps_user}
  IdentityFile ~/.ssh/id_ed25519
  StrictHostKeyChecking no
  ConnectTimeout 30
  ServerAliveInterval 15
  ServerAliveCountMax 3
"""

        config_file = ssh_dir / "config"
        with open(config_file, "w") as f:
            f.write(config_content)

        config_file.chmod(0o600)

        ssh_key_path = ssh_dir / "id_ed25519"
        if not ssh_key_path.exists() and ssh_key:
            with open(ssh_key_path, "w") as f:
                f.write(ssh_key)
            ssh_key_path.chmod(0o600)

        try:
            shutil.chown(ssh_dir, "builder", "builder")
            for item in ssh_dir.iterdir():
                shutil.chown(item, "builder", "builder")
        except Exception as e:
            logger.warning(f"Could not change SSH dir ownership: {e}")

    def test_ssh_connection(self) -> bool:
        """Test SSH connection to VPS"""
        logger.info("Testing SSH connection to VPS...")

        ssh_test_cmd = [
            "ssh",
            *self.ssh_options,
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]

        result = subprocess.run(ssh_test_cmd, capture_output=True, text=True, check=False)
        if result and result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout:
            logger.info("SSH connection successful")
            return True
        else:
            logger.warning(f"SSH connection failed: {result.stderr[:100] if result and result.stderr else 'No output'}")
            return False

    def ensure_remote_directory(self):
        """
        Ensure remote directory exists and is writable by the SSH user.
        Performs comprehensive checks and fails fast with actionable commands.
        """
        logger.info("Ensuring remote directory exists...")
        staging_parent = f"{self.remote_dir}/.staging"

        remote_cmd = f"""
set -e

# Check/create remote_dir
if [ ! -d "{self.remote_dir}" ]; then
    mkdir -p "{self.remote_dir}"
    echo "CREATED_REMOTE_DIR"
else
    echo "REMOTE_DIR_EXISTS"
fi

# Verify writable (simple)
if [ ! -w "{self.remote_dir}" ]; then
    echo "REMOTE_DIR_NOT_WRITABLE"
    exit 1
fi

# Verify writable (robust temp file)
tmpfile="{self.remote_dir}/.write_test_$(date +%s)_$$"
if ! touch "$tmpfile"; then
    echo "TMP_CREATE_FAIL"
    exit 1
fi
if ! rm -f "$tmpfile"; then
    echo "TMP_DELETE_FAIL"
    exit 1
fi

# Check/create staging parent
if [ ! -d "{staging_parent}" ]; then
    mkdir -p "{staging_parent}"
    echo "CREATED_STAGING_PARENT"
else
    echo "STAGING_PARENT_EXISTS"
fi

if [ ! -w "{staging_parent}" ]; then
    echo "STAGING_PARENT_NOT_WRITABLE"
    exit 1
fi

tmpfile="{staging_parent}/.write_test_$(date +%s)_$$"
if ! touch "$tmpfile"; then
    echo "STAGING_TMP_CREATE_FAIL"
    exit 1
fi
if ! rm -f "$tmpfile"; then
    echo "STAGING_TMP_DELETE_FAIL"
    exit 1
fi

echo "ALL_CHECKS_PASSED"
"""

        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", remote_cmd]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )

            output = (result.stdout or "").strip()

            if result.returncode != 0:
                if "REMOTE_DIR_NOT_WRITABLE" in output:
                    error_msg = "Remote directory exists but is not writable"
                elif "STAGING_PARENT_NOT_WRITABLE" in output:
                    error_msg = "Staging parent exists but is not writable"
                elif "TMP_CREATE_FAIL" in output:
                    error_msg = "Failed to create temporary file in remote_dir"
                elif "TMP_DELETE_FAIL" in output:
                    error_msg = "Failed to delete temporary file in remote_dir"
                elif "STAGING_TMP_CREATE_FAIL" in output:
                    error_msg = "Failed to create temporary file in staging parent"
                elif "STAGING_TMP_DELETE_FAIL" in output:
                    error_msg = "Failed to delete temporary file in staging parent"
                else:
                    error_msg = f"SSH command failed with exit code {result.returncode}"

                logger.error(
                    f"REMOTE_DIR_NOT_WRITABLE vps_user={self.vps_user} vps_host={self.vps_host} "
                    f"remote_dir={self.remote_dir} staging_parent={staging_parent} reason={error_msg}"
                )

                logger.error("Actionable admin commands (run on VPS):")
                logger.error(f"  mkdir -p \"{staging_parent}\"")
                logger.error(f"  chown -R \"{self.vps_user}\" \"{self.remote_dir}\"")
                logger.error(f"  find \"{self.remote_dir}\" -type d -exec chmod 755 {{}} \\;")
                logger.error(f"  find \"{self.remote_dir}\" -type f -exec chmod 644 {{}} \\;")

                raise RuntimeError(f"Remote directory not writable or setup failed: {error_msg}")

            if "ALL_CHECKS_PASSED" not in output:
                logger.error(
                    f"REMOTE_DIR_CREATE_FAIL vps_user={self.vps_user} vps_host={self.vps_host} "
                    f"remote_dir={self.remote_dir} staging_parent={staging_parent} output={output[:200]}"
                )
                raise RuntimeError("Remote directory setup incomplete")

            logger.info("Remote directory verified")

        except subprocess.TimeoutExpired:
            logger.error(
                f"REMOTE_DIR_TIMEOUT vps_user={self.vps_user} vps_host={self.vps_host} "
                f"remote_dir={self.remote_dir} staging_parent={staging_parent}"
            )
            raise RuntimeError("SSH timeout while ensuring remote directory")
        except Exception as e:
            if not isinstance(e, RuntimeError):
                logger.error(
                    f"REMOTE_DIR_EXCEPTION vps_user={self.vps_user} vps_host={self.vps_host} "
                    f"remote_dir={self.remote_dir} staging_parent={staging_parent} error={str(e)[:200]}"
                )
                raise RuntimeError(f"Unexpected error ensuring remote directory: {e}")
            raise

    def normalize_permissions(self, remote_dir: Optional[str] = None) -> bool:
        """
        Normalize permissions on remote repository directory (best effort):
        - All directories: chmod 755
        - All files: chmod 644

        NOTE: Must not block publish after promotion. Always returns True.
        """
        target_dir = remote_dir or self.remote_dir

        logger.info(f"VPS_PERMS_NORMALIZE_START dir={target_dir}")

        remote_cmd = f"""
find "{target_dir}" -type d -exec chmod 755 {{}} \\;
find "{target_dir}" -type f -exec chmod 644 {{}} \\;
"""

        ssh_cmd = ["ssh", *self.ssh_options, f"{self.vps_user}@{self.vps_host}", remote_cmd]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=60
            )

            stderr_snippet = (result.stderr or "").strip()[:200]

            if result.returncode != 0:
                logger.warning(
                    f"VPS_PERMS_NORMALIZE_WARN dir={target_dir} rc={result.returncode} stderr_snippet={stderr_snippet or 'No stderr'}"
                )
                logger.warning("Actionable admin commands (run on VPS):")
                logger.warning(f"  chown -R \"{self.vps_user}\" \"{target_dir}\"")
                logger.warning(f"  find \"{target_dir}\" -type d -exec chmod 755 {{}} \\;")
                logger.warning(f"  find \"{target_dir}\" -type f -exec chmod 644 {{}} \\;")
                return True

            # Even if rc==0, stderr may contain warnings like "Permission denied"
            if stderr_snippet and ("permission denied" in stderr_snippet.lower() or "cannot access" in stderr_snippet.lower()):
                logger.warning(
                    f"VPS_PERMS_NORMALIZE_WARN dir={target_dir} rc=0 stderr_snippet={stderr_snippet}"
                )
                logger.warning("Actionable admin commands (run on VPS):")
                logger.warning(f"  chown -R \"{self.vps_user}\" \"{target_dir}\"")
                logger.warning(f"  find \"{target_dir}\" -type d -exec chmod 755 {{}} \\;")
                logger.warning(f"  find \"{target_dir}\" -type f -exec chmod 644 {{}} \\;")
                return True

            logger.info("VPS_PERMS_NORMALIZE_OK")
            return True

        except subprocess.TimeoutExpired:
            logger.warning(f"VPS_PERMS_NORMALIZE_WARN dir={target_dir} stderr_snippet=Timeout after 60 seconds")
            return True
        except Exception as e:
            logger.warning(f"VPS_PERMS_NORMALIZE_WARN dir={target_dir} exception={str(e)[:200]}")
            return True

    def check_repository_exists_on_vps(self) -> Tuple[bool, bool]:
        """Check if repository exists on VPS via SSH"""
        logger.info("Checking if repository exists on VPS...")

        remote_cmd = f"""
        # Check for package files
        if find "{self.remote_dir}" -name "*.pkg.tar.*" -type f 2>/dev/null | head -1 >/dev/null; then
            echo "REPO_EXISTS_WITH_PACKAGES"
        # Check for database files
        elif [ -f "{self.remote_dir}/{self.repo_name}.db.tar.gz" ] || [ -f "{self.remote_dir}/{self.repo_name}.db" ]; then
            echo "REPO_EXISTS_WITH_DB"
        else
            echo "REPO_NOT_FOUND"
        fi
        """

        ssh_cmd = ["ssh", f"{self.vps_user}@{self.vps_host}", remote_cmd]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30
            )

            if result.returncode == 0:
                if "REPO_EXISTS_WITH_PACKAGES" in result.stdout:
                    logger.info("Repository exists on VPS (has package files)")
                    return True, True
                elif "REPO_EXISTS_WITH_DB" in result.stdout:
                    logger.info("Repository exists on VPS (has database)")
                    return True, False
                else:
                    logger.info("Repository does not exist on VPS (first run)")
                    return False, False
            else:
                logger.warning(f"Could not check repository existence: {result.stderr[:200]}")
                return False, False

        except subprocess.TimeoutExpired:
            logger.error("SSH timeout checking repository existence")
            return False, False
        except Exception as e:
            logger.error(f"Error checking repository: {e}")
            return False, False

    def list_remote_packages(self) -> List[str]:
        """List all *.pkg.tar.zst and *.pkg.tar.xz files in the remote repository directory (basenames only)"""
        logger.info("Listing remote repository packages (SSH find)...")

        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found")
            return []

        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            rf'find "{self.remote_dir}" -maxdepth 1 -type f \( -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" \) -printf "%f\\n" 2>/dev/null || echo "NO_FILES"'
        ]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip() and f.strip() != 'NO_FILES']
                logger.info(f"Found {len(files)} package files on remote server")
                return files
            else:
                logger.warning(f"SSH find returned error")
                return []

        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return []
