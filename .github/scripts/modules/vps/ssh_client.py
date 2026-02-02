# FILE: .github/scripts/modules/vps/ssh_client.py
"""
SSH Client Module - Handles SSH connectivity and remote file inventory

This module provides a small, reliable SSH wrapper used by the package builder
to validate the VPS connection and inspect the remote repository directory.

Design goals:
- Deterministic, CI-friendly behavior (GitHub Actions containers)
- No interactive prompts (StrictHostKeyChecking disabled by default)
- Clear logging and safe timeouts
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


logger = logging.getLogger(__name__)


@dataclass
class SSHResult:
    returncode: int
    stdout: str
    stderr: str


class SSHClient:
    """
    Lightweight SSH client for the VPS repo host.

    Expected config keys (typically passed in from orchestrator config):
    - vps_user: str
    - vps_host: str
    - remote_dir: str (full path of repo dir on VPS, e.g. /var/www/repo/NAME/x86_64)
    - ssh_key: Optional[str] (path to private key file in the runner)
    - ssh_port: Optional[int] (defaults to 22)
    """

    def __init__(
        self,
        vps_user: str,
        vps_host: str,
        remote_dir: str,
        ssh_key: Optional[str] = None,
        ssh_port: int = 22,
        connect_timeout: int = 15,
        command_timeout: int = 60,
    ) -> None:
        self.vps_user = vps_user
        self.vps_host = vps_host
        self.remote_dir = remote_dir
        self.ssh_key = ssh_key
        self.ssh_port = int(ssh_port)
        self.connect_timeout = int(connect_timeout)
        self.command_timeout = int(command_timeout)

    # -----------------------------
    # Setup / basic connectivity
    # -----------------------------
    def setup_ssh_config(self, ssh_key_path: str) -> None:
        """
        Ensure the SSH key has correct permissions and store it for later SSH calls.

        This does not require writing ~/.ssh/config, but it ensures that the key
        is usable in CI (OpenSSH refuses overly-permissive key files).
        """
        self.ssh_key = ssh_key_path

        key = Path(ssh_key_path)
        if not key.exists():
            raise FileNotFoundError(f"SSH key not found: {ssh_key_path}")

        try:
            # Ensure key permissions: 600
            os.chmod(key, 0o600)
        except PermissionError:
            # In some CI setups chmod may fail; we still try to continue.
            logger.warning("Could not chmod SSH key to 600 (permission error). Continuing...")

        # Also ensure ~/.ssh exists with safe perms (useful if other steps write known_hosts)
        ssh_dir = Path.home() / ".ssh"
        try:
            ssh_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(ssh_dir, 0o700)
        except Exception:
            # Non-fatal
            pass

        logger.info("SSH key configured for VPS access.")

    def test_ssh_connection(self) -> bool:
        """
        Test SSH connectivity to the VPS.
        Returns True on success.
        """
        result = self.run_remote_command("echo OK", timeout=self.connect_timeout)
        ok = result.returncode == 0 and "OK" in result.stdout
        if ok:
            logger.info("SSH connection OK.")
        else:
            logger.error("SSH connection failed: %s", result.stderr.strip()[:300])
        return ok

    # -----------------------------
    # Remote repo directory helpers
    # -----------------------------
    def check_repository_exists_on_vps(self) -> bool:
        """
        Check whether remote_dir exists on the VPS.
        """
        cmd = f'test -d {shlex.quote(self.remote_dir)} && echo EXISTS || echo MISSING'
        result = self.run_remote_command(cmd, timeout=self.connect_timeout)
        return result.returncode == 0 and "EXISTS" in result.stdout

    def ensure_remote_directory(self) -> bool:
        """
        Ensure remote_dir exists (mkdir -p).
        Returns True if the command succeeds.
        """
        cmd = f'mkdir -p {shlex.quote(self.remote_dir)}'
        result = self.run_remote_command(cmd, timeout=self.command_timeout)
        if result.returncode == 0:
            logger.info("Remote directory ensured: %s", self.remote_dir)
            return True
        logger.error("Failed to ensure remote directory: %s", result.stderr.strip()[:300])
        return False

    def list_remote_packages(self) -> List[str]:
        """
        List files in remote_dir relevant for the repo, returning full paths.

        Includes:
        - packages (*.pkg.tar.zst, *.pkg.tar.xz)
        - signatures (*.sig)
        - repo databases (*.db, *.db.tar.gz, *.files, *.files.tar.gz, *.abs.tar.gz)

        Returns:
            List[str]: full remote file paths (one per line)
        """
        # IMPORTANT:
        # - Use a raw string for the literal \( \) in the find expression (avoid invalid escapes)
        # - Keep \n as a literal for tools that interpret it (find -printf, printf, etc.)
        remote_find_cmd = (
            f'find {shlex.quote(self.remote_dir)} -maxdepth 1 -type f '
            r'\( -name "*.pkg.tar.zst" -o -name "*.pkg.tar.xz" -o -name "*.sig" '
            r'-o -name "*.db" -o -name "*.db.tar.gz" -o -name "*.files" -o -name "*.files.tar.gz" '
            r'-o -name "*.abs.tar.gz" \) '
            r'-print 2>/dev/null || true'
        )

        result = self.run_remote_command(remote_find_cmd, timeout=self.command_timeout)
        if result.returncode != 0:
            logger.warning("Could not list remote files: %s", result.stderr.strip()[:300])
            return []

        files_raw = result.stdout.strip()
        if not files_raw:
            return []

        return [line.strip() for line in files_raw.splitlines() if line.strip()]

    # -----------------------------
    # Core execution helper
    # -----------------------------
    def run_remote_command(self, command: str, timeout: Optional[int] = None) -> SSHResult:
        """
        Run a shell command on the VPS via SSH (non-interactive).

        Args:
            command: shell command to run on remote host
            timeout: seconds; if None uses self.command_timeout

        Returns:
            SSHResult(returncode, stdout, stderr)
        """
        if timeout is None:
            timeout = self.command_timeout

        ssh_cmd = self._build_ssh_base_cmd() + [
            # Run via bash -lc for consistent quoting and to allow compound commands
            "bash",
            "-lc",
            command,
        ]

        try:
            proc = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
            return SSHResult(proc.returncode, proc.stdout or "", proc.stderr or "")
        except subprocess.TimeoutExpired:
            return SSHResult(124, "", f"SSH command timed out after {timeout}s")
        except Exception as e:
            return SSHResult(1, "", f"SSH execution error: {e}")

    def _build_ssh_base_cmd(self) -> List[str]:
        """
        Build the base ssh command with safe, CI-friendly options.
        """
        cmd: List[str] = [
            "ssh",
            "-p",
            str(self.ssh_port),
            "-o",
            "BatchMode=yes",
            "-o",
            f"ConnectTimeout={self.connect_timeout}",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
        ]

        if self.ssh_key:
            cmd += ["-i", self.ssh_key]

        cmd.append(f"{self.vps_user}@{self.vps_host}")
        return cmd
