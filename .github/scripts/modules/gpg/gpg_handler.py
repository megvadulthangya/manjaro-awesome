"""
GPG Handler Module - Handles GPG key import, signing, and pacman-key operations
"""

import os
import subprocess
import shutil
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GPGHandler:
    """Handles GPG key import, repository signing, and pacman-key operations"""
    
    def __init__(self, config):
        """
        Initialize GPGHandler with configuration
        
        Args:
            config: Dictionary containing gpg configuration
        """
        self.gpg_private_key = config.get('gpg_private_key', '')
        self.gpg_key_id = config.get('gpg_key_id', '')
        self.gpg_enabled = bool(self.gpg_private_key and self.gpg_key_id)
        self.gpg_home = None
        self.gpg_env = None
        self.debug_mode = config.get('debug_mode', False)
        
        # Safe logging - no sensitive information
        if self.gpg_key_id:
            if self.debug_mode:
                print(f"🔧 [DEBUG] GPG Environment Check: Key ID found: YES, Key data found: {'YES' if self.gpg_private_key else 'NO'}", flush=True)
            else:
                logger.info(f"GPG Environment Check: Key ID found: YES, Key data found: {'YES' if self.gpg_private_key else 'NO'}")
        else:
            if self.debug_mode:
                print(f"🔧 [DEBUG] GPG Environment Check: No GPG key ID configured", flush=True)
            else:
                logger.info("GPG Environment Check: No GPG key ID configured")
    
    def import_gpg_key(self) -> bool:
        """Import GPG private key and set trust level WITHOUT interactive terminal (container-safe)"""
        if not self.gpg_enabled:
            if self.debug_mode:
                print(f"🔧 [DEBUG] GPG Key not detected. Skipping repository signing.", flush=True)
            else:
                logger.info("GPG Key not detected. Skipping repository signing.")
            return False
        
        if self.debug_mode:
            print(f"🔧 [DEBUG] GPG Key detected. Importing private key...", flush=True)
        else:
            logger.info("GPG Key detected. Importing private key...")
        
        # Handle both string and bytes for the private key
        key_data = self.gpg_private_key
        if isinstance(key_data, bytes):
            key_data_str = key_data.decode('utf-8')
        else:
            key_data_str = str(key_data)
        
        # Validate private key format before attempting import
        if not key_data_str or '-----BEGIN PGP PRIVATE KEY BLOCK-----' not in key_data_str:
            if self.debug_mode:
                print(f"❌ [DEBUG] CRITICAL: Invalid GPG private key format.", flush=True)
                print(f"❌ [DEBUG] Disabling GPG signing for this build.", flush=True)
            else:
                logger.error("❌ CRITICAL: Invalid GPG private key format.")
                logger.error("Disabling GPG signing for this build.")
            self.gpg_enabled = False
            return False
        
        try:
            # Create a temporary GPG home directory
            temp_gpg_home = tempfile.mkdtemp(prefix="gpg_home_")
            
            # Set environment for GPG
            env = os.environ.copy()
            env['GNUPGHOME'] = temp_gpg_home
            
            # Import the private key
            if isinstance(self.gpg_private_key, bytes):
                key_input = self.gpg_private_key
            else:
                key_input = self.gpg_private_key.encode('utf-8')
            
            import_process = subprocess.run(
                ['gpg', '--batch', '--import'],
                input=key_input,
                capture_output=True,
                text=False,
                env=env,
                check=False
            )
            
            if import_process.returncode != 0:
                stderr = import_process.stderr.decode('utf-8') if isinstance(import_process.stderr, bytes) else import_process.stderr
                if self.debug_mode:
                    print(f"❌ [DEBUG] Failed to import GPG key: {stderr}", flush=True)
                else:
                    logger.error(f"Failed to import GPG key: {stderr}")
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
                return False
            
            if self.debug_mode:
                print(f"🔧 [DEBUG] GPG key imported successfully", flush=True)
            else:
                logger.info("✅ GPG key imported successfully")
            
            # Get fingerprint and set ultimate trust
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
                            # Set ultimate trust (6 = ultimate)
                            trust_process = subprocess.run(
                                ['gpg', '--import-ownertrust'],
                                input=f"{fingerprint}:6:\n".encode('utf-8'),
                                capture_output=True,
                                text=False,
                                env=env,
                                check=False
                            )
                            if trust_process.returncode == 0:
                                if self.debug_mode:
                                    print(f"🔧 [DEBUG] Set ultimate trust for GPG key", flush=True)
                                else:
                                    logger.info("✅ Set ultimate trust for GPG key")
                            break
            
            # Export public key and add to pacman-key WITHOUT interactive terminal
            if fingerprint:
                try:
                    # Export public key to a temporary file
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.asc', delete=False) as pub_key_file:
                        export_process = subprocess.run(
                            ['gpg', '--armor', '--export', fingerprint],
                            capture_output=True,
                            text=True,
                            env=env,
                            check=True
                        )
                        pub_key_file.write(export_process.stdout)
                        pub_key_path = pub_key_file.name
                    
                    # Add to pacman-key WITH SUDO
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Adding GPG key to pacman-key...", flush=True)
                    else:
                        logger.info("Adding GPG key to pacman-key...")
                    
                    add_process = subprocess.run(
                        ['sudo', 'pacman-key', '--add', pub_key_path],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if add_process.returncode != 0:
                        if self.debug_mode:
                            print(f"❌ [DEBUG] Failed to add key to pacman-key: {add_process.stderr}", flush=True)
                        else:
                            logger.error(f"Failed to add key to pacman-key: {add_process.stderr}")
                    else:
                        if self.debug_mode:
                            print(f"🔧 [DEBUG] Key added to pacman-key", flush=True)
                        else:
                            logger.info("✅ Key added to pacman-key")
                    
                    # Import ownertrust into pacman keyring
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Setting ultimate trust in pacman keyring...", flush=True)
                    else:
                        logger.info("Setting ultimate trust in pacman keyring...")
                    
                    ownertrust_content = f"{fingerprint}:6:\n"
                    
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.trust', delete=False) as trust_file:
                        trust_file.write(ownertrust_content)
                        trust_file_path = trust_file.name
                    
                    trust_cmd = [
                        'sudo', 'gpg',
                        '--homedir', '/etc/pacman.d/gnupg',
                        '--batch',
                        '--import-ownertrust',
                        trust_file_path
                    ]
                    
                    try:
                        trust_process = subprocess.run(
                            trust_cmd,
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if trust_process.returncode == 0:
                            if self.debug_mode:
                                print(f"🔧 [DEBUG] Set ultimate trust for key in pacman keyring", flush=True)
                            else:
                                logger.info("✅ Set ultimate trust for key in pacman keyring")
                        else:
                            if self.debug_mode:
                                print(f"⚠️ [DEBUG] Failed to set trust with gpg: {trust_process.stderr[:200]}", flush=True)
                            else:
                                logger.warning(f"⚠️ Failed to set trust with gpg: {trust_process.stderr[:200]}")
                    except Exception as e:
                        if self.debug_mode:
                            print(f"⚠️ [DEBUG] Error setting trust with gpg: {e}", flush=True)
                        else:
                            logger.warning(f"⚠️ Error setting trust with gpg: {e}")
                    finally:
                        os.unlink(trust_file_path)
                        os.unlink(pub_key_path)
                    
                except Exception as e:
                    if self.debug_mode:
                        print(f"❌ [DEBUG] Error during pacman-key setup: {e}", flush=True)
                    else:
                        logger.error(f"Error during pacman-key setup: {e}")
            
            # Store the GPG home directory for later use
            self.gpg_home = temp_gpg_home
            self.gpg_env = env
            
            return True
            
        except Exception as e:
            if self.debug_mode:
                print(f"❌ [DEBUG] Error importing GPG key: {e}", flush=True)
            else:
                logger.error(f"Error importing GPG key: {e}")
            if 'temp_gpg_home' in locals():
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
            return False
    
    def sign_repository_files(self, repo_name: str, output_dir: str) -> bool:
        """Sign repository database files with GPG"""
        if not self.gpg_enabled:
            if self.debug_mode:
                print(f"🔧 [DEBUG] GPG signing disabled - skipping repository signing", flush=True)
            else:
                logger.info("GPG signing disabled - skipping repository signing")
            return False
        
        if not hasattr(self, 'gpg_home') or not hasattr(self, 'gpg_env'):
            if self.debug_mode:
                print(f"❌ [DEBUG] GPG key not imported. Cannot sign repository files.", flush=True)
            else:
                logger.error("GPG key not imported. Cannot sign repository files.")
            return False
        
        try:
            output_path = Path(output_dir)
            files_to_sign = [
                output_path / f"{repo_name}.db",
                output_path / f"{repo_name}.files"
            ]
            
            signed_count = 0
            failed_count = 0
            
            for file_to_sign in files_to_sign:
                if not file_to_sign.exists():
                    if self.debug_mode:
                        print(f"⚠️ [DEBUG] Repository file not found for signing: {file_to_sign.name}", flush=True)
                    else:
                        logger.warning(f"Repository file not found for signing: {file_to_sign.name}")
                    continue
                
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Signing repository database: {file_to_sign.name}", flush=True)
                else:
                    logger.info(f"Signing repository database: {file_to_sign.name}")
                
                # Create detached signature
                sig_file = file_to_sign.with_suffix(file_to_sign.suffix + '.sig')
                
                sign_process = subprocess.run(
                    [
                        'gpg', '--detach-sign',
                        '--default-key', self.gpg_key_id,
                        '--output', str(sig_file),
                        str(file_to_sign)
                    ],
                    capture_output=True,
                    text=True,
                    env=self.gpg_env,
                    check=False
                )
                
                if sign_process.returncode == 0:
                    if self.debug_mode:
                        print(f"🔧 [DEBUG] Created signature: {sig_file.name}", flush=True)
                    else:
                        logger.info(f"✅ Created signature: {sig_file.name}")
                    signed_count += 1
                else:
                    if self.debug_mode:
                        print(f"⚠️ [DEBUG] Failed to sign {file_to_sign.name}: {sign_process.stderr[:200]}", flush=True)
                    else:
                        logger.warning(f"⚠️ Failed to sign {file_to_sign.name}: {sign_process.stderr[:200]}")
                    failed_count += 1
            
            if signed_count > 0:
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Successfully signed {signed_count} repository file(s)", flush=True)
                else:
                    logger.info(f"✅ Successfully signed {signed_count} repository file(s)")
                
                # CRITICAL FIX: Minor warnings should not block the build
                if failed_count > 0:
                    if self.debug_mode:
                        print(f"⚠️ [DEBUG] {failed_count} file(s) failed to sign, but continuing anyway", flush=True)
                    else:
                        logger.warning(f"⚠️ {failed_count} file(s) failed to sign, but continuing anyway")
                return True
            else:
                if self.debug_mode:
                    print(f"❌ [DEBUG] Failed to sign any repository files", flush=True)
                    print(f"⚠️ [DEBUG] Continuing build without GPG signatures", flush=True)
                else:
                    logger.error("Failed to sign any repository files")
                    logger.warning("⚠️ Continuing build without GPG signatures")
                return False
                
        except Exception as e:
            if self.debug_mode:
                print(f"❌ [DEBUG] Error signing repository files: {e}", flush=True)
                print(f"⚠️ [DEBUG] Continuing build without GPG signatures due to error", flush=True)
            else:
                logger.error(f"Error signing repository files: {e}")
                logger.warning("⚠️ Continuing build without GPG signatures due to error")
            return False
    
    def cleanup(self):
        """Clean up temporary GPG home directory"""
        if hasattr(self, 'gpg_home'):
            try:
                shutil.rmtree(self.gpg_home, ignore_errors=True)
                if self.debug_mode:
                    print(f"🔧 [DEBUG] Cleaned up temporary GPG home directory", flush=True)
                else:
                    logger.debug("Cleaned up temporary GPG home directory")
            except Exception as e:
                if self.debug_mode:
                    print(f"⚠️ [DEBUG] Could not clean up GPG directory: {e}", flush=True)
                else:
                    logger.warning(f"Could not clean up GPG directory: {e}")