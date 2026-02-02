"""
GPG Handler - signing support for repo artifacts

This module is intentionally strict when signing is enabled:
- If signing is enabled but the key isn't available / import fails / signing fails,
  we raise or return False to stop the pipeline. Otherwise you end up with
  partially-signed repos and confusing "nothing changed" behavior on the VPS.

Expected environment variables (recommended via GitHub Actions secrets):
- GPG_PRIVATE_KEY: ASCII-armored private key (required when signing enabled)
- GPG_PASSPHRASE: passphrase for the private key (optional)
- GPG_KEY_ID: optional key id / fingerprint for logging / sanity checks
"""

import os
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GPGHandler:
    def __init__(self, sign_packages: bool, strict: bool = True):
        self.sign_packages = bool(sign_packages)
        self.strict = bool(strict)

        self.private_key = os.environ.get("GPG_PRIVATE_KEY", "").strip()
        self.passphrase = os.environ.get("GPG_PASSPHRASE", "")
        self.key_id = os.environ.get("GPG_KEY_ID", "").strip()

        self._gnupg_home: Optional[str] = None
        self._ready = False

        if not self.sign_packages:
            logger.info("GPG signing disabled (sign_packages=false).")
            return

        if not self.private_key:
            msg = "GPG signing enabled but GPG_PRIVATE_KEY is missing."
            if self.strict:
                raise RuntimeError(msg)
            logger.error(msg)
            self.sign_packages = False

    def is_ready(self) -> bool:
        return bool(self.sign_packages and self._ready)

    def setup(self) -> bool:
        """Prepare an isolated GNUPGHOME and import the private key."""
        if not self.sign_packages:
            return False

        try:
            self._gnupg_home = tempfile.mkdtemp(prefix="gnupg_")
            os.chmod(self._gnupg_home, 0o700)

            env = self._gpg_env()

            # Import private key
            import_proc = subprocess.run(
                ["gpg", "--batch", "--yes", "--import"],
                input=self.private_key,
                text=True,
                env=env,
                capture_output=True,
                check=False,
            )
            if import_proc.returncode != 0:
                msg = f"GPG key import failed: {(import_proc.stderr or '')[:300]}"
                if self.strict:
                    raise RuntimeError(msg)
                logger.error(msg)
                return False

            # Optional sanity check: list secret keys
            list_proc = subprocess.run(
                ["gpg", "--batch", "--list-secret-keys", "--with-colons"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if list_proc.returncode != 0 or not (list_proc.stdout or "").strip():
                msg = "GPG key import seems unsuccessful: no secret keys listed."
                if self.strict:
                    raise RuntimeError(msg)
                logger.error(msg)
                return False

            self._ready = True
            logger.info("GPG setup OK (secret keys available).")
            return True

        except Exception as e:
            if self.strict:
                raise
            logger.error("GPG setup failed: %s", e)
            return False

    def sign_file(self, file_path: Path) -> bool:
        """Create detached signature (file.sig) for file_path."""
        if not self.is_ready():
            msg = "Attempted to sign but GPG is not ready."
            if self.strict:
                raise RuntimeError(msg)
            logger.error(msg)
            return False

        file_path = Path(file_path)
        if not file_path.exists():
            msg = f"Cannot sign missing file: {file_path}"
            if self.strict:
                raise FileNotFoundError(msg)
            logger.error(msg)
            return False

        sig_path = Path(str(file_path) + ".sig")

        # gpg will create file.sig next to the file
        cmd = [
            "gpg",
            "--batch",
            "--yes",
            "--pinentry-mode",
            "loopback",
            "--detach-sign",
            str(file_path),
        ]

        env = self._gpg_env()
        if self.passphrase:
            cmd.extend(["--passphrase", self.passphrase])

        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        if proc.returncode != 0:
            logger.error("GPG signing failed for %s: %s", file_path.name, (proc.stderr or "")[:300])
            return False

        # Basic sanity: signature file exists and non-empty
        try:
            if not sig_path.exists() or sig_path.stat().st_size == 0:
                logger.error("GPG reported success but signature is missing/empty: %s", sig_path.name)
                return False
        except Exception as e:
            logger.error("Could not stat signature file %s: %s", sig_path, e)
            return False

        logger.info("Signed: %s", file_path.name)
        return True

    def sign_repo_artifacts(self, repo_dir: Path, repo_name: str) -> None:
        """
        Sign repo DB/files archives if they exist:
        - <repo>.db.tar.gz
        - <repo>.files.tar.gz

        Safe to call multiple times.
        """
        if not self.is_ready():
            return

        repo_dir = Path(repo_dir)

        for fname in (
            f"{repo_name}.db.tar.gz",
            f"{repo_name}.files.tar.gz",
        ):
            p = repo_dir / fname
            if p.exists():
                self.sign_file(p)

    def _gpg_env(self) -> dict:
        env = os.environ.copy()
        if self._gnupg_home:
            env["GNUPGHOME"] = self._gnupg_home
        return env
