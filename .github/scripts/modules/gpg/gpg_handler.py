"""
GPG Handler Module
Handles GPG key import, signing, and pacman-key operations
"""

import os
import subprocess
import shutil
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional

class GPGHandler:
    """Handles GPG key import, repository signing, and pacman-key operations"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize GPGHandler with configuration
        
        Args:
            config: Configuration dictionary
        """
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        self.gpg_private_key = config.get('gpg_private_key', '')
        self.gpg_key_id = config.get('gpg_key_id', '')
        self.gpg_enabled = bool(self.gpg_private_key and self.gpg_key_id)
        self.gpg_home = None
        self.gpg_env = None
        
        # Safe logging - no sensitive information
        if self.gpg_key_id:
            self.logger.info(f"GPG Check: Key ID: YES, Key Data: {'YES' if self.gpg_private_key else 'NO'}")
        else:
            self.logger.info("GPG Check: No Key ID configured")
    
    def import_gpg_key(self) -> bool:
        """Import GPG private key and set trust level"""
        if not self.gpg_enabled:
            self.logger.info("GPG Key not detected. Skipping signing.")
            return False
        
        self.logger.info("Importing GPG private key...")
        
        # Handle both string and bytes
        key_data = self.gpg_private_key
        if isinstance(key_data, bytes):
            key_data_str = key_data.decode('utf-8')
        else:
            key_data_str = str(key_data)
        
        if not key_data_str or '-----BEGIN PGP PRIVATE KEY BLOCK-----' not in key_data_str:
            self.logger.error("❌ Invalid GPG private key format.")
            self.gpg_enabled = False
            return False
        
        try:
            temp_gpg_home = tempfile.mkdtemp(prefix="gpg_home_")
            env = os.environ.copy()
            env['GNUPGHOME'] = temp_gpg_home
            
            key_input = key_data if isinstance(key_data, bytes) else key_data.encode('utf-8')
            
            import_process = subprocess.run(
                ['gpg', '--batch', '--import'],
                input=key_input,
                capture_output=True,
                env=env,
                check=False
            )
            
            if import_process.returncode != 0:
                self.logger.error(f"Failed to import GPG key: {import_process.stderr}")
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
                return False
            
            # Get fingerprint and set trust
            list_process = subprocess.run(
                ['gpg', '--list-keys', '--with-colons', self.gpg_key_id],
                capture_output=True,
                text=True,
                env=env,
                check=False
            )
            
            fingerprint = None
            if list_process.returncode == 0:
                for line in list_process.stdout.split('\n'):
                    if line.startswith('fpr:'):
                        parts = line.split(':')
                        if len(parts) > 9:
                            fingerprint = parts[9]
                            subprocess.run(
                                ['gpg', '--import-ownertrust'],
                                input=f"{fingerprint}:6:\n".encode('utf-8'),
                                capture_output=True,
                                env=env,
                                check=False
                            )
                            break
            
            if fingerprint:
                self._setup_pacman_key(fingerprint, env)
            
            self.gpg_home = temp_gpg_home
            self.gpg_env = env
            return True
            
        except Exception as e:
            self.logger.error(f"Error importing GPG key: {e}")
            if 'temp_gpg_home' in locals():
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
            return False

    def _setup_pacman_key(self, fingerprint: str, env: Dict[str, str]):
        """Helper to add key to pacman keyring"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.asc', delete=False) as pub_key_file:
                # FIX: Removed capture_output=True because stdout is redirected to file
                subprocess.run(
                    ['gpg', '--armor', '--export', fingerprint],
                    text=True,
                    env=env,
                    check=True,
                    stdout=pub_key_file
                )
                pub_key_path = pub_key_file.name
            
            subprocess.run(
                ['sudo', 'pacman-key', '--add', pub_key_path],
                capture_output=True,
                check=False
            )
            
            with tempfile.NamedTemporaryFile(mode='w', suffix='.trust', delete=False) as trust_file:
                trust_file.write(f"{fingerprint}:6:\n")
                trust_path = trust_file.name
                
            subprocess.run(
                ['sudo', 'gpg', '--homedir', '/etc/pacman.d/gnupg', '--batch', '--import-ownertrust', trust_path],
                capture_output=True,
                check=False
            )
            
            os.unlink(pub_key_path)
            os.unlink(trust_path)
            
        except Exception as e:
            self.logger.warning(f"Pacman key setup warning: {e}")

    def sign_repository_files(self, repo_name: str, output_dir: str) -> bool:
        """Sign repository database files"""
        if not self.gpg_enabled or not self.gpg_env:
            return False
            
        try:
            output_path = Path(output_dir)
            files = [output_path / f"{repo_name}.db", output_path / f"{repo_name}.files"]
            
            signed = 0
            for f in files:
                if not f.exists(): continue
                
                sig_file = f.with_suffix(f.suffix + '.sig')
                res = subprocess.run(
                    ['gpg', '--detach-sign', '--default-key', self.gpg_key_id, '--output', str(sig_file), str(f)],
                    capture_output=True,
                    env=self.gpg_env,
                    check=False
                )
                if res.returncode == 0:
                    signed += 1
            
            return signed > 0
        except Exception as e:
            self.logger.warning(f"Signing error: {e}")
            return False

    def cleanup(self):
        """Clean up GPG home"""
        if self.gpg_home:
            shutil.rmtree(self.gpg_home, ignore_errors=True)