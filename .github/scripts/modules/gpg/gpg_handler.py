"""
GPG Handler Module
Handles GPG key import, signing, and pacman-key operations.
Implements 'Secret Sauce' legacy logic for proper key trust injection.
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
        
        # Base environment with LC_ALL=C
        self.base_env = os.environ.copy()
        self.base_env['LC_ALL'] = 'C'
    
    def import_gpg_key(self) -> bool:
        """
        Import GPG private key into isolated keyring AND system pacman keyring.
        Sets up the environment for subsequent signing operations.
        """
        if not self.gpg_enabled:
            self.logger.info("GPG Key not detected. Skipping signing setup.")
            return False
        
        self.logger.info("🔐 Importing GPG private key...")
        
        # Handle key data
        key_data = self.gpg_private_key
        if isinstance(key_data, bytes):
            key_data = key_data.decode('utf-8')
        else:
            key_data = str(key_data)
        
        if not key_data or '-----BEGIN PGP PRIVATE KEY BLOCK-----' not in key_data:
            self.logger.error("❌ Invalid GPG private key format.")
            self.gpg_enabled = False
            return False
        
        temp_gpg_home = None
        try:
            # 1. Setup Isolated GPG Home for Signing
            temp_gpg_home = tempfile.mkdtemp(prefix="gpg_home_")
            env = self.base_env.copy()
            env['GNUPGHOME'] = temp_gpg_home
            
            key_input = key_data.encode('utf-8')
            
            # Import into temp keyring
            import_res = subprocess.run(
                ['gpg', '--batch', '--import'],
                input=key_input,
                capture_output=True,
                env=env,
                check=False
            )
            
            if import_res.returncode != 0:
                self.logger.error(f"❌ Failed to import GPG key: {import_res.stderr.decode()}")
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
                return False
                
            # Get Fingerprint
            list_res = subprocess.run(
                ['gpg', '--list-keys', '--with-colons', self.gpg_key_id],
                capture_output=True,
                text=True,
                env=env,
                check=False
            )
            
            fingerprint = None
            if list_res.returncode == 0:
                for line in list_res.stdout.split('\n'):
                    if line.startswith('fpr:'):
                        parts = line.split(':')
                        if len(parts) > 9:
                            fingerprint = parts[9]
                            # Set ownertrust in temp keyring
                            subprocess.run(
                                ['gpg', '--import-ownertrust'],
                                input=f"{fingerprint}:6:\n".encode('utf-8'),
                                capture_output=True,
                                env=env,
                                check=False
                            )
                            break
            
            if not fingerprint:
                self.logger.error("❌ Could not determine GPG fingerprint")
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
                return False

            # 2. Integrate with Pacman Keyring (Legacy Secret Sauce)
            self._setup_pacman_key(fingerprint, key_input, env)
            
            self.gpg_home = temp_gpg_home
            self.gpg_env = env
            self.logger.info("✅ GPG key imported and trusted in pacman keyring")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Error importing GPG key: {e}")
            if temp_gpg_home and os.path.exists(temp_gpg_home):
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
            return False

    def _setup_pacman_key(self, fingerprint: str, key_bytes: bytes, env: Dict[str, str]):
        """
        Add key to pacman keyring and set trust.
        Critical for avoiding 'invalid or corrupted database' errors.
        """
        self.logger.info("🔐 integrating key into pacman keyring...")
        
        pub_key_path = None
        trust_path = None
        
        try:
            # Export public key
            with tempfile.NamedTemporaryFile(mode='w', suffix='.asc', delete=False) as f:
                pub_key_path = f.name
                subprocess.run(
                    ['gpg', '--armor', '--export', fingerprint],
                    stdout=f,
                    env=env,
                    check=True
                )
            
            # Add to pacman-key
            subprocess.run(
                ['sudo', 'LC_ALL=C', 'pacman-key', '--add', pub_key_path],
                capture_output=True,
                check=False
            )
            
            # Create trust file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.trust', delete=False) as f:
                f.write(f"{fingerprint}:6:\n")
                trust_path = f.name
            
            # Import trust into /etc/pacman.d/gnupg
            subprocess.run(
                [
                    'sudo', 'LC_ALL=C', 'gpg', 
                    '--homedir', '/etc/pacman.d/gnupg', 
                    '--batch', 
                    '--import-ownertrust', 
                    trust_path
                ],
                capture_output=True,
                check=False
            )
            
            # Refresh pacman-key
            subprocess.run(
                ['sudo', 'LC_ALL=C', 'pacman-key', '--updatedb'],
                capture_output=True,
                check=False
            )
            
        except Exception as e:
            self.logger.warning(f"⚠️ Pacman key setup warning: {e}")
        finally:
            if pub_key_path and os.path.exists(pub_key_path):
                os.unlink(pub_key_path)
            if trust_path and os.path.exists(trust_path):
                os.unlink(trust_path)

    def sign_repository_files(self, repo_name: str, output_dir: str) -> bool:
        """
        Sign repository database files (.db and .files).
        Used AFTER repo-add to manually apply signatures.
        """
        if not self.gpg_enabled or not self.gpg_env:
            self.logger.warning("⚠️ GPG not enabled or env missing, skipping signing")
            return False
            
        try:
            output_path = Path(output_dir)
            # Standard repo-add output files
            targets = [
                output_path / f"{repo_name}.db",
                output_path / f"{repo_name}.files"
            ]
            
            signed_count = 0
            for target in targets:
                if not target.exists():
                    # It might be that repo-add only created the archives, check for .tar.gz and sign that too if symlink fails
                    target_archive = target.with_suffix('.tar.gz')
                    if target_archive.exists():
                        target = target_archive
                    else:
                        continue
                
                sig_file = target.with_suffix(target.suffix + '.sig')
                if sig_file.exists():
                    sig_file.unlink()
                
                self.logger.info(f"✍️ Signing {target.name}...")
                
                res = subprocess.run(
                    [
                        'gpg', '--detach-sign', 
                        '--default-key', self.gpg_key_id, 
                        '--output', str(sig_file), 
                        str(target)
                    ],
                    capture_output=True,
                    env=self.gpg_env,
                    check=False
                )
                
                if res.returncode == 0:
                    signed_count += 1
                else:
                    self.logger.error(f"❌ Failed to sign {target.name}: {res.stderr.decode()}")

            return signed_count > 0
            
        except Exception as e:
            self.logger.error(f"❌ Signing error: {e}")
            return False

    def cleanup(self):
        """Clean up GPG home"""
        if self.gpg_home and os.path.exists(self.gpg_home):
            shutil.rmtree(self.gpg_home, ignore_errors=True)