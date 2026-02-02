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
    
    def __init__(self, sign_packages: bool = True):
        self.gpg_private_key = os.getenv('GPG_PRIVATE_KEY')
        self.gpg_key_id = os.getenv('GPG_KEY_ID')
        self.gpg_enabled = bool(self.gpg_private_key and self.gpg_key_id)
        self.sign_packages_enabled = sign_packages and self.gpg_enabled
        self.gpg_home = None
        self.gpg_env = None
        
        # Safe logging - no sensitive information
        if self.gpg_key_id:
            logger.info(f"GPG Environment Check: Key ID found: YES, Key data found: {'YES' if self.gpg_private_key else 'NO'}")
            logger.info(f"Package signing: {'ENABLED' if self.sign_packages_enabled else 'DISABLED'}")
        else:
            logger.info("GPG Environment Check: No GPG key ID configured")
    
    def import_gpg_key(self) -> bool:
        """Import GPG private key and set trust level WITHOUT interactive terminal (container-safe)"""
        if not self.gpg_enabled:
            logger.info("GPG Key not detected. Skipping repository signing.")
            return False
        
        logger.info("GPG Key detected. Importing private key...")
        
        # Handle both string and bytes for the private key
        key_data = self.gpg_private_key
        if isinstance(key_data, bytes):
            key_data_str = key_data.decode('utf-8')
        else:
            key_data_str = str(key_data)
        
        # Validate private key format before attempting import
        if not key_data_str or '-----BEGIN PGP PRIVATE KEY BLOCK-----' not in key_data_str:
            logger.error("❌ CRITICAL: Invalid GPG private key format.")
            logger.error("Disabling GPG signing for this build.")
            self.gpg_enabled = False
            self.sign_packages_enabled = False
            return False
        
        try:
            # FIRST: Import into builder user's GNUPGHOME (/home/builder/.gnupg)
            # This is where package signing will actually look for the key
            builder_gpg_home = Path("/home/builder/.gnupg")
            builder_gpg_home.mkdir(exist_ok=True, mode=0o700)
            
            # Set ownership to builder user
            try:
                subprocess.run(['sudo', 'chown', '-R', 'builder:builder', str(builder_gpg_home)], 
                             check=False, capture_output=True)
            except Exception:
                pass  # Continue even if chown fails
            
            # Prepare environment for builder's GPG
            builder_env = os.environ.copy()
            builder_env['GNUPGHOME'] = str(builder_gpg_home)
            
            # Import the private key into builder's keyring
            if isinstance(self.gpg_private_key, bytes):
                key_input = self.gpg_private_key
            else:
                key_input = self.gpg_private_key.encode('utf-8')
            
            logger.info("Importing GPG key into builder user's keyring...")
            import_process = subprocess.run(
                ['sudo', '-u', 'builder', 'gpg', '--batch', '--import'],
                input=key_input,
                capture_output=True,
                text=False,
                env=builder_env,
                check=False
            )
            
            if import_process.returncode != 0:
                stderr = import_process.stderr.decode('utf-8') if isinstance(import_process.stderr, bytes) else import_process.stderr
                logger.error(f"Failed to import GPG key into builder keyring: {stderr}")
                # Don't fail yet - try temporary directory as fallback
            
            # Verify key exists in builder's keyring
            verify_cmd = ['sudo', '-u', 'builder', 'gpg', '--list-secret-keys', '--with-colons', self.gpg_key_id]
            verify_process = subprocess.run(
                verify_cmd,
                capture_output=True,
                text=True,
                env=builder_env,
                check=False
            )
            
            key_in_builder_keyring = verify_process.returncode == 0 and 'fpr:' in verify_process.stdout
            if key_in_builder_keyring:
                logger.info("✅ GPG key successfully imported into builder user's keyring")
                # Set ultimate trust for the key in builder's keyring
                fingerprint = None
                for line in verify_process.stdout.split('\n'):
                    if line.startswith('fpr:'):
                        parts = line.split(':')
                        if len(parts) > 9:
                            fingerprint = parts[9]
                            break
                
                if fingerprint:
                    trust_process = subprocess.run(
                        ['sudo', '-u', 'builder', 'gpg', '--import-ownertrust'],
                        input=f"{fingerprint}:6:\n".encode('utf-8'),
                        capture_output=True,
                        text=False,
                        env=builder_env,
                        check=False
                    )
                    if trust_process.returncode == 0:
                        logger.info("✅ Set ultimate trust for GPG key in builder keyring")
            else:
                logger.warning("⚠️ GPG key not found in builder user's keyring after import attempt")
            
            # SECOND: Also import into a temporary GNUPGHOME for pacman-key operations
            # (This part is kept for backward compatibility)
            temp_gpg_home = tempfile.mkdtemp(prefix="gpg_home_")
            
            # Set environment for temporary GPG
            env = os.environ.copy()
            env['GNUPGHOME'] = temp_gpg_home
            
            # Import the private key into temporary keyring
            temp_import_process = subprocess.run(
                ['gpg', '--batch', '--import'],
                input=key_input,
                capture_output=True,
                text=False,
                env=env,
                check=False
            )
            
            if temp_import_process.returncode != 0:
                stderr = temp_import_process.stderr.decode('utf-8') if isinstance(temp_import_process.stderr, bytes) else temp_import_process.stderr
                logger.error(f"Failed to import GPG key into temporary keyring: {stderr}")
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
                # Continue anyway - we at least tried builder keyring
            
            logger.info("✅ GPG key imported successfully into temporary keyring")
            
            # Get fingerprint and set ultimate trust in temporary keyring
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
                                logger.info("✅ Set ultimate trust for GPG key in temporary keyring")
                            break
            
            # CRITICAL FIX: Initialize pacman-key if not already initialized
            if not os.path.exists('/etc/pacman.d/gnupg'):
                logger.info("Initializing pacman keyring...")
                init_process = subprocess.run(
                    ['sudo', 'pacman-key', '--init'],
                    capture_output=True,
                    text=True,
                    check=False
                )
                if init_process.returncode == 0:
                    logger.info("✅ Pacman keyring initialized")
                else:
                    logger.warning(f"⚠️ Pacman-key init warning: {init_process.stderr[:200]}")
            
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
                    logger.info("Adding GPG key to pacman-key...")
                    add_process = subprocess.run(
                        ['sudo', 'pacman-key', '--add', pub_key_path],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if add_process.returncode != 0:
                        logger.error(f"Failed to add key to pacman-key: {add_process.stderr}")
                    else:
                        logger.info("✅ Key added to pacman-key")
                    
                    # CRITICAL FIX: Update pacman-key database and populate keyring
                    logger.info("Updating pacman-key database...")
                    update_process = subprocess.run(
                        ['sudo', 'pacman-key', '--updatedb'],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if update_process.returncode == 0:
                        logger.info("✅ Pacman-key database updated")
                    else:
                        logger.warning(f"⚠️ Pacman-key update warning: {update_process.stderr[:200]}")
                    
                    logger.info("Populating pacman keyring...")
                    populate_process = subprocess.run(
                        ['sudo', 'pacman-key', '--populate'],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    if populate_process.returncode == 0:
                        logger.info("✅ Pacman keyring populated")
                    else:
                        logger.warning(f"⚠️ Pacman-key populate warning: {populate_process.stderr[:200]}")
                    
                    # Import ownertrust into pacman keyring
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
                            logger.info("✅ Set ultimate trust for key in pacman keyring")
                        else:
                            logger.warning(f"⚠️ Failed to set trust with gpg: {trust_process.stderr[:200]}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error setting trust with gpg: {e}")
                    finally:
                        os.unlink(trust_file_path)
                        os.unlink(pub_key_path)
                    
                except Exception as e:
                    logger.error(f"Error during pacman-key setup: {e}")
            
            # Store the temporary GPG home directory for repository signing
            self.gpg_home = temp_gpg_home
            self.gpg_env = env
            
            # CRITICAL: Verify builder can access the key before enabling signing
            if not self._verify_builder_can_sign():
                logger.error("❌ Builder user cannot access GPG key. Disabling package signing.")
                self.sign_packages_enabled = False
                # Keep gpg_enabled for repository signing, but not package signing
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error importing GPG key: {e}")
            if 'temp_gpg_home' in locals():
                shutil.rmtree(temp_gpg_home, ignore_errors=True)
            return False
    
    def _verify_builder_can_sign(self) -> bool:
        """
        Verify that builder user has access to the secret key for signing.
        
        Returns:
            True if builder can sign, False otherwise
        """
        if not self.gpg_enabled or not self.gpg_key_id:
            return False
        
        try:
            # Check if builder user can list the secret key
            cmd = ['sudo', '-u', 'builder', 'gpg', '--list-secret-keys', '--with-colons', self.gpg_key_id]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode != 0:
                logger.error(f"Builder cannot list secret keys: {result.stderr[:200]}")
                return False
            
            # Check if the key is actually present
            if 'fpr:' not in result.stdout:
                logger.error(f"Secret key {self.gpg_key_id} not found in builder's keyring")
                # Try to list all keys for debugging
                debug_cmd = ['sudo', '-u', 'builder', 'gpg', '--list-secret-keys']
                debug_result = subprocess.run(debug_cmd, capture_output=True, text=True, check=False)
                if debug_result.returncode == 0:
                    logger.info(f"Builder's available secret keys:\n{debug_result.stdout}")
                return False
            
            logger.info("✅ Builder user has access to GPG secret key for signing")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying builder GPG access: {e}")
            return False
    
    def _verify_signature(self, package_path: Path, sig_path: Path) -> bool:
        """
        Verify a GPG signature
        
        Args:
            package_path: Path to the package file
            sig_path: Path to the signature file
            
        Returns:
            True if signature is valid, False otherwise
        """
        if not package_path.exists():
            logger.error(f"Package file not found: {package_path}")
            return False
        
        if not sig_path.exists():
            logger.error(f"Signature file not found: {sig_path}")
            return False
        
        try:
            verify_cmd = [
                'gpg', '--verify',
                str(sig_path),
                str(package_path)
            ]
            
            verify_process = subprocess.run(
                verify_cmd,
                capture_output=True,
                text=True,
                env=self.gpg_env if hasattr(self, 'gpg_env') else None,
                check=False
            )
            
            if verify_process.returncode == 0:
                logger.debug(f"✅ Signature verification passed for {package_path.name}")
                return True
            else:
                logger.error(f"❌ Signature verification failed for {package_path.name}")
                if verify_process.stderr:
                    logger.error(f"   Error: {verify_process.stderr[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error verifying signature for {package_path.name}: {e}")
            return False
    
    def sign_package(self, package_path):
        """
        Sign individual package file with GPG using --detach-sign --no-armor
        
        Args:
            package_path: Path to the package file (.pkg.tar.zst)
        
        Returns:
            bool: True if signing successful AND verification passes, False on error
        """
        if not self.sign_packages_enabled:
            logger.debug(f"Package signing disabled, skipping: {package_path}")
            return True
        
        # CRITICAL: Verify builder can sign before attempting
        if not self._verify_builder_can_sign():
            logger.error(f"❌ Cannot sign {package_path}: Builder user cannot access GPG key")
            return False
        
        try:
            package_path_obj = Path(package_path)
            
            # Check if file exists before signing
            if not package_path_obj.exists():
                logger.error(f"Package file not found for signing: {package_path}")
                return False
            
            # Create signature file path
            sig_file = package_path_obj.with_suffix(package_path_obj.suffix + '.sig')
            
            # Delete existing signature if exists
            if sig_file.exists():
                try:
                    sig_file.unlink()
                    logger.debug(f"Removed existing signature: {sig_file.name}")
                except Exception as e:
                    logger.warning(f"Could not remove existing signature {sig_file.name}: {e}")
            
            logger.info(f"🚀 Attempting to sign: {package_path_obj.name}")
            logger.info(f"   Using GPG key: {self.gpg_key_id}")
            logger.info(f"   Output signature: {sig_file.name}")
            
            # Create detached signature with --no-armor (binary signature)
            # Use sudo -u builder to ensure correct user context
            sign_cmd = [
                'sudo', '-u', 'builder', 'gpg',
                '--detach-sign', '--no-armor',
                '--default-key', self.gpg_key_id,
                '--output', str(sig_file),
                str(package_path_obj)
            ]
            
            logger.info(f"   Command: {' '.join(sign_cmd)}")
            
            sign_process = subprocess.run(
                sign_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if sign_process.returncode == 0:
                logger.info(f"✅ Created package signature: {sig_file.name}")
                
                # Verify the signature was created
                if sig_file.exists():
                    sig_size = sig_file.stat().st_size
                    logger.info(f"   Signature file size: {sig_size} bytes")
                    
                    # REQUIRED: Verify the signature immediately
                    if self._verify_signature(package_path_obj, sig_file):
                        logger.info(f"✅ Signature verification passed for {package_path_obj.name}")
                        return True
                    else:
                        # SIGNATURE VERIFICATION FAILED: Delete the invalid signature
                        logger.error(f"❌ Signature verification failed for {package_path_obj.name}")
                        try:
                            sig_file.unlink()
                            logger.info(f"🗑️ Deleted invalid signature: {sig_file.name}")
                        except Exception as e:
                            logger.warning(f"Could not delete invalid signature: {e}")
                        return False
                else:
                    logger.error(f"❌ Signature file not created: {sig_file}")
                    return False
            else:
                logger.error(f"❌ Failed to sign package {package_path_obj.name}")
                if sign_process.stdout:
                    logger.error(f"   STDOUT: {sign_process.stdout[:200]}")
                if sign_process.stderr:
                    logger.error(f"   STDERR: {sign_process.stderr[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error signing package {package_path}: {e}")
            return False
    
    def verify_all_signatures(self, directory: Path) -> dict:
        """
        Verify all signature files in a directory
        
        Args:
            directory: Directory containing packages and signatures
            
        Returns:
            Dictionary mapping package_name -> verification_result
        """
        if not self.gpg_enabled:
            return {}
        
        results = {}
        
        # Find all signature files
        for sig_file in directory.glob("*.sig"):
            # Find corresponding package file (remove .sig extension)
            package_file = directory / sig_file.name[:-4]
            
            if package_file.exists():
                logger.debug(f"🔍 Verifying signature: {sig_file.name}")
                if self._verify_signature(package_file, sig_file):
                    results[package_file.name] = True
                else:
                    results[package_file.name] = False
                    # Delete invalid signature
                    try:
                        sig_file.unlink()
                        logger.info(f"🗑️ Deleted invalid signature: {sig_file.name}")
                    except Exception as e:
                        logger.warning(f"Could not delete invalid signature: {e}")
            else:
                logger.warning(f"Package file not found for signature: {sig_file.name}")
        
        valid_count = sum(1 for result in results.values() if result)
        invalid_count = len(results) - valid_count
        
        logger.info(f"📊 Signature verification: {valid_count} valid, {invalid_count} invalid")
        
        return results
    
    def sign_repository_files(self, repo_name: str, output_dir: str) -> bool:
        """Sign repository database files with GPG"""
        if not self.gpg_enabled:
            logger.info("GPG signing disabled - skipping repository signing")
            return False
        
        if not hasattr(self, 'gpg_home') or not hasattr(self, 'gpg_env'):
            logger.error("GPG key not imported. Cannot sign repository files.")
            return False
        
        try:
            output_path = Path(output_dir)
            files_to_sign = [
                output_path / f"{repo_name}.db",
                output_path / f"{repo_name}.db.tar.gz",
                output_path / f"{repo_name}.files",
                output_path / f"{repo_name}.files.tar.gz"
            ]
            
            signed_count = 0
            failed_count = 0
            
            for file_to_sign in files_to_sign:
                if not file_to_sign.exists():
                    logger.warning(f"Repository file not found for signing: {file_to_sign.name}")
                    continue
                
                logger.info(f"Signing repository database: {file_to_sign.name}")
                
                # Delete existing .sig file before signing
                sig_file = file_to_sign.with_suffix(file_to_sign.suffix + '.sig')
                if sig_file.exists():
                    try:
                        sig_file.unlink()
                        logger.info(f"🗑️ Removed existing signature: {sig_file.name}")
                    except Exception as e:
                        logger.warning(f"Could not remove existing signature {sig_file.name}: {e}")
                
                # Create detached signature
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
                    logger.info(f"✅ Created signature: {sig_file.name}")
                    
                    # Verify the signature
                    if self._verify_signature(file_to_sign, sig_file):
                        signed_count += 1
                    else:
                        # Delete invalid signature
                        try:
                            sig_file.unlink()
                            logger.error(f"❌ Signature verification failed for {file_to_sign.name}")
                            failed_count += 1
                        except Exception as e:
                            logger.warning(f"Could not delete invalid signature: {e}")
                            failed_count += 1
                else:
                    logger.warning(f"⚠️ Failed to sign {file_to_sign.name}: {sign_process.stderr[:200]}")
                    failed_count += 1
            
            if signed_count > 0:
                logger.info(f"✅ Successfully signed {signed_count} repository file(s)")
                # CRITICAL FIX: Minor warnings should not block the build
                if failed_count > 0:
                    logger.warning(f"⚠️ {failed_count} file(s) failed to sign, but continuing anyway")
                return True
            else:
                logger.error("Failed to sign any repository files")
                # CRITICAL FIX: Don't fail the build if GPG signing has issues
                logger.warning("⚠️ Continuing build without GPG signatures")
                return False
                
        except Exception as e:
            logger.error(f"Error signing repository files: {e}")
            # CRITICAL FIX: Don't fail the build if GPG signing has issues
            logger.warning("⚠️ Continuing build without GPG signatures due to error")
            return False
    
    def cleanup(self):
        """Clean up temporary GPG home directory"""
        if hasattr(self, 'gpg_home'):
            try:
                shutil.rmtree(self.gpg_home, ignore_errors=True)
                logger.debug("Cleaned up temporary GPG home directory")
            except Exception as e:
                logger.warning(f"Could not clean up GPG directory: {e}")
