"""
Database Manager
Handles repository database operations, signing, and consistency checks.
Implements 'Zero-Residue' policy and manual signing flow.
"""
import os
import shutil
import glob
import subprocess
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient
from modules.gpg.gpg_handler import GPGHandler

class DatabaseManager:
    """Manages the Pacman repository database"""
    
    def __init__(self, config: Dict[str, Any], ssh_client: SSHClient, 
                 rsync_client: RsyncClient, gpg_handler: GPGHandler, logger: Optional[logging.Logger] = None):
        self.config = config
        self.ssh_client = ssh_client
        self.rsync_client = rsync_client
        self.gpg_handler = gpg_handler
        self.logger = logger or logging.getLogger(__name__)
        
        self.repo_name = config.get('repo_name', 'custom_repo')
        self._staging_dir: Optional[Path] = None

    def create_staging_dir(self) -> Path:
        """Create a clean staging directory"""
        import tempfile
        self._staging_dir = Path(tempfile.mkdtemp(prefix=f"{self.repo_name}_staging_"))
        return self._staging_dir

    def cleanup_staging_dir(self):
        """Remove the staging directory"""
        if self._staging_dir and self._staging_dir.exists():
            shutil.rmtree(self._staging_dir, ignore_errors=True)

    def download_existing_database(self) -> bool:
        """Download existing database files from VPS to staging"""
        if not self._staging_dir:
            return False
            
        self.logger.info("📥 Downloading existing database...")
        # We download everything to ensure we have the full state
        patterns = [
            f"{self.repo_name}.db*",
            f"{self.repo_name}.files*"
        ]
        
        for pattern in patterns:
            self.rsync_client.mirror_remote(pattern, self._staging_dir)
        
        return True

    def _parse_pkg_filename(self, filename: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse package filename into (name, full_version).
        Format: name-version-release-arch.pkg.tar.zst
        """
        if not filename.endswith('.pkg.tar.zst'):
            return None, None
            
        parts = filename.split('-')
        if len(parts) < 4:
            return None, None
            
        # arch is last, release is second to last, version is third to last
        # everything before is name
        try:
            version = parts[-3]
            release = parts[-2]
            name = "-".join(parts[:-3])
            full_version = f"{version}-{release}"
            return name, full_version
        except Exception:
            return None, None

    def _enforce_zero_residue(self):
        """
        Scan staging directory and ensure only ONE version (the latest) exists for each package.
        Deletes older duplicate versions.
        """
        if not self._staging_dir:
            return

        files = list(self._staging_dir.glob("*.pkg.tar.zst"))
        pkg_map: Dict[str, List[Tuple[str, Path]]] = {}

        # Group by package name
        for f in files:
            name, ver = self._parse_pkg_filename(f.name)
            if name and ver:
                if name not in pkg_map:
                    pkg_map[name] = []
                pkg_map[name].append((ver, f))

        # Filter duplicates
        for name, entries in pkg_map.items():
            if len(entries) > 1:
                # Sort using vercmp (external call required for accuracy)
                # We'll use a bubble sort with vercmp since list is small
                n = len(entries)
                for i in range(n):
                    for j in range(0, n-i-1):
                        v1 = entries[j][0]
                        v2 = entries[j+1][0]
                        
                        # Compare v1 and v2
                        res = subprocess.run(
                            ['vercmp', v1, v2],
                            capture_output=True, text=True, env={'LC_ALL': 'C'}
                        )
                        # if v1 > v2, swap to push larger to end
                        if res.returncode == 0 and int(res.stdout.strip()) > 0:
                            entries[j], entries[j+1] = entries[j+1], entries[j]
                
                # Keep last (highest), remove others
                keep = entries[-1]
                remove = entries[:-1]
                
                self.logger.info(f"🧹 Zero-Residue: Keeping {keep[1].name}, removing {len(remove)} old versions.")
                
                for _, f_path in remove:
                    f_path.unlink()
                    # Also remove sig if exists
                    sig = f_path.with_suffix(f_path.suffix + '.sig')
                    if sig.exists():
                        sig.unlink()

    def update_database_additive(self) -> bool:
        """
        Update the database by regenerating it from staged packages.
        1. Enforce Zero-Residue (remove duplicates).
        2. Clean old DB files.
        3. Run repo-add with shell wildcard.
        4. Manually sign files.
        """
        if not self._staging_dir:
            self.logger.error("❌ No staging directory active")
            return False
        
        cwd = os.getcwd()
        os.chdir(self._staging_dir)
        
        try:
            # 1. Enforce Zero-Residue
            self._enforce_zero_residue()
            
            # Check if any packages remain
            pkgs = list(glob.glob("*.pkg.tar.zst"))
            if not pkgs:
                self.logger.info("ℹ️ No packages found in staging. Database update skipped.")
                return True
            
            # 2. Clean Start: Remove existing database files to force regeneration
            db_files = [
                f"{self.repo_name}.db",
                f"{self.repo_name}.db.tar.gz",
                f"{self.repo_name}.files",
                f"{self.repo_name}.files.tar.gz"
            ]
            for f in db_files:
                if os.path.exists(f):
                    os.remove(f)

            # 3. Run repo-add with Wildcard Support (shell=True)
            # DO NOT use --sign here. We sign manually later.
            db_target = f"{self.repo_name}.db.tar.gz"
            cmd = f"repo-add {db_target} *.pkg.tar.zst"
            
            # Ensure proper environment
            env = os.environ.copy()
            env['LC_ALL'] = 'C'
            
            self.logger.info(f"RUNNING: {cmd}")
            
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
                env=env
            )
            
            if result.returncode != 0:
                self.logger.error("❌ repo-add failed!")
                self.logger.error(f"STDOUT: {result.stdout}")
                self.logger.error(f"STDERR: {result.stderr}")
                return False
            
            if not Path(db_target).exists():
                self.logger.error("❌ Database file was not created")
                return False
            
            # 4. Manual Signing
            if self.gpg_handler.gpg_enabled:
                self.logger.info("🔐 Manually signing database files...")
                if not self.gpg_handler.sign_repository_files(self.repo_name, str(self._staging_dir)):
                    self.logger.error("❌ Failed to sign database files")
                    return False
                self.logger.info("✅ Database signed successfully")
            else:
                self.logger.warning("⚠️ GPG disabled, database unsigned")

            self.logger.info("✅ Database regeneration complete")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Database update exception: {e}")
            return False
        finally:
            os.chdir(cwd)

    def upload_updated_files(self) -> bool:
        """Upload all files from staging to VPS"""
        if not self._staging_dir:
            return False
            
        files = glob.glob(str(self._staging_dir / "*"))
        if not files:
            return True
            
        self.logger.info(f"📤 Uploading {len(files)} files to remote...")
        return self.rsync_client.upload(files)