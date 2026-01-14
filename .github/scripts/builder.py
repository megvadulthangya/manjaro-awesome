#!/usr/bin/env python3
"""
Manjaro Package Builder - Production Version with Repository Lifecycle Management
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import hashlib
import logging
import socket
import glob
from pathlib import Path
from datetime import datetime

# Add the script directory to sys.path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

# Try to import our config files
try:
    import config
    import packages
    HAS_CONFIG_FILES = True
except ImportError as e:
    print(f"⚠️ Warning: Could not import config files: {e}")
    print("⚠️ Using default configurations")
    HAS_CONFIG_FILES = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('builder.log')
    ]
)
logger = logging.getLogger(__name__)

class PackageBuilder:
    def __init__(self):
        # Get the repository root
        self.repo_root = self._get_repo_root()
        
        # Load configuration
        self._load_config()
        
        # Setup directories
        self.output_dir = self.repo_root / getattr(config, 'OUTPUT_DIR', 'built_packages') if HAS_CONFIG_FILES else self.repo_root / "built_packages"
        self.build_tracking_dir = self.repo_root / getattr(config, 'BUILD_TRACKING_DIR', '.build_tracking') if HAS_CONFIG_FILES else self.repo_root / ".build_tracking"
        
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # State
        self.remote_files = []
        self.packages_to_clean = set()
        self.built_packages = []
        self.skipped_packages = []
        self.rebuilt_local_packages = []
        
        # Repository state
        self.repo_has_packages_pacman = None  # From pacman -Sl
        self.repo_has_packages_ssh = None     # From SSH find
        self.repo_final_state = None          # Final decision
        
        # PHASE 1 OBSERVER: hokibot data collection
        self.hokibot_data = []  # List of dicts: {name, built_version, pkgrel, epoch}
        
        # SSH options - SIMPLIFIED like in test
        self.ssh_options = [
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=30",
            "-o", "BatchMode=yes"
        ]
        
        # Setup SSH config file for builder user (CRITICAL FIX)
        self._setup_ssh_config()
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
        }
    
    def _setup_ssh_config(self):
        """Setup SSH config file for builder user - EXACTLY as in the test script"""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(exist_ok=True, mode=0o700)
        
        # Write SSH config file - CRITICAL FIX
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
        
        # Ensure SSH key exists and has correct permissions
        ssh_key_path = ssh_dir / "id_ed25519"
        if not ssh_key_path.exists():
            # Write the SSH key from environment
            ssh_key = os.getenv('VPS_SSH_KEY')
            if ssh_key:
                with open(ssh_key_path, "w") as f:
                    f.write(ssh_key)
                ssh_key_path.chmod(0o600)
        
        # Generate known_hosts if needed
        known_hosts = ssh_dir / "known_hosts"
        if not known_hosts.exists():
            try:
                subprocess.run(
                    ["ssh-keyscan", "-H", self.vps_host],
                    capture_output=True,
                    text=True,
                    stdout=open(known_hosts, "w"),
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass
        
        # Set ownership to builder
        try:
            shutil.chown(ssh_dir, "builder", "builder")
            for item in ssh_dir.iterdir():
                shutil.chown(item, "builder", "builder")
        except Exception as e:
            logger.warning(f"Could not change SSH dir ownership: {e}")
    
    def _get_repo_root(self):
        """Get the repository root directory reliably."""
        github_workspace = os.getenv('GITHUB_WORKSPACE')
        if github_workspace:
            workspace_path = Path(github_workspace)
            if workspace_path.exists():
                logger.info(f"Using GITHUB_WORKSPACE: {workspace_path}")
                return workspace_path
        
        container_workspace = Path('/__w/manjaro-awesome/manjaro-awesome')
        if container_workspace.exists():
            logger.info(f"Using container workspace: {container_workspace}")
            return container_workspace
        
        # Get script directory and go up to repo root
        script_path = Path(__file__).resolve()
        repo_root = script_path.parent.parent.parent  # .github/scripts -> .github -> repo root
        if repo_root.exists():
            logger.info(f"Using repository root from script location: {repo_root}")
            return repo_root
        
        current_dir = Path.cwd()
        logger.info(f"Using current directory: {current_dir}")
        return current_dir
    
    def _load_config(self):
        """Load configuration from environment and config files."""
        self.vps_user = os.getenv('VPS_USER')
        self.vps_host = os.getenv('VPS_HOST')
        self.ssh_key = os.getenv('VPS_SSH_KEY')
        self.repo_server_url = os.getenv('REPO_SERVER_URL', '')
        self.remote_dir = os.getenv('REMOTE_DIR', '/var/www/repo')
        
        env_repo_name = os.getenv('REPO_NAME')
        if HAS_CONFIG_FILES:
            config_repo_name = getattr(config, 'REPO_DB_NAME', 'manjaro-awesome')
            self.repo_name = env_repo_name if env_repo_name else config_repo_name
        else:
            self.repo_name = env_repo_name if env_repo_name else 'manjaro-awesome'
        
        required = ['VPS_USER', 'VPS_HOST', 'VPS_SSH_KEY']
        missing = [var for var in required if not os.getenv(var)]
        
        if missing:
            logger.error(f"❌ Missing required environment variables: {missing}")
            logger.error("Please set these in your GitHub repository secrets")
            sys.exit(1)
        
        print(f"🔧 Configuration loaded:")
        print(f"   SSH: {self.vps_user}@{self.vps_host}")
        print(f"   Remote directory: {self.remote_dir}")
        print(f"   Repository name: {self.repo_name}")
        if self.repo_server_url:
            print(f"   Repository URL: {self.repo_server_url}")
        print(f"   Config files loaded: {HAS_CONFIG_FILES}")
    
    def run_cmd(self, cmd, cwd=None, capture=True, check=True, shell=True, user=None, log_cmd=False):
        """Run command with comprehensive logging."""
        if log_cmd:
            logger.info(f"RUNNING COMMAND: {cmd}")
        
        if cwd is None:
            cwd = self.repo_root
        
        if user:
            env = os.environ.copy()
            env['HOME'] = f'/home/{user}'
            env['USER'] = user
            
            try:
                sudo_cmd = ['sudo', '-u', user]
                if shell:
                    sudo_cmd.extend(['bash', '-c', f'cd "{cwd}" && {cmd}'])
                else:
                    sudo_cmd.extend(cmd)
                
                result = subprocess.run(
                    sudo_cmd,
                    capture_output=capture,
                    text=True,
                    check=check,
                    env=env
                )
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                    logger.info(f"EXIT CODE: {result.returncode}")
                return result
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
                    if e.stdout:
                        logger.error(f"STDOUT: {e.stdout[:500]}")
                    if e.stderr:
                        logger.error(f"STDERR: {e.stderr[:500]}")
                    logger.error(f"EXIT CODE: {e.returncode}")
                if check:
                    raise
                return e
        else:
            try:
                result = subprocess.run(
                    cmd,
                    cwd=cwd,
                    shell=shell,
                    capture_output=capture,
                    text=True,
                    check=check
                )
                if log_cmd:
                    if result.stdout:
                        logger.info(f"STDOUT: {result.stdout[:500]}")
                    if result.stderr:
                        logger.info(f"STDERR: {result.stderr[:500]}")
                    logger.info(f"EXIT CODE: {result.returncode}")
                return result
            except subprocess.CalledProcessError as e:
                if log_cmd:
                    logger.error(f"Command failed: {cmd}")
                    if e.stdout:
                        logger.error(f"STDOUT: {e.stdout[:500]}")
                    if e.stderr:
                        logger.error(f"STDERR: {e.stderr[:500]}")
                    logger.error(f"EXIT CODE: {e.returncode}")
                if check:
                    raise
                return e
    
    def test_ssh_connection(self):
        """Test SSH connection to VPS."""
        print("\n🔍 Testing SSH connection to VPS...")
        
        ssh_test_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            "echo SSH_TEST_SUCCESS"
        ]
        
        result = subprocess.run(ssh_test_cmd, capture_output=True, text=True, check=False)
        if result and result.returncode == 0 and "SSH_TEST_SUCCESS" in result.stdout:
            print("✅ SSH connection successful")
            return True
        else:
            print(f"⚠️ SSH connection failed: {result.stderr[:100] if result and result.stderr else 'No output'}")
            return False
    
    def _list_remote_packages(self):
        """STEP 1: List all *.pkg.tar.zst files in the remote repository directory."""
        print("\n" + "="*60)
        print("STEP 1: Listing remote repository packages (SSH find)")
        print("="*60)
        
        ssh_key_path = "/home/builder/.ssh/id_ed25519"
        if not os.path.exists(ssh_key_path):
            logger.error(f"SSH key not found at {ssh_key_path}")
            return []
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            f"find {self.remote_dir} -maxdepth 1 -type f \\( -name '*.pkg.tar.zst' -o -name '*.pkg.tar.xz' \\) 2>/dev/null"
        ]
        
        logger.info(f"RUNNING SSH COMMAND: {' '.join(ssh_cmd)}")
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.stdout:
                logger.info(f"STDOUT (first 1000 chars): {result.stdout[:1000]}")
            if result.stderr:
                logger.info(f"STDERR: {result.stderr[:500]}")
            
            if result.returncode == 0:
                files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
                file_count = len(files)
                logger.info(f"✅ SSH find returned {file_count} package files")
                if file_count > 0:
                    print(f"Sample files: {files[:5]}")
                    self.remote_files = [os.path.basename(f) for f in files]
                else:
                    logger.info("ℹ️ No package files found on remote server")
                return files
            else:
                logger.warning(f"⚠️ SSH find returned error: {result.stderr[:200]}")
                return []
                
        except Exception as e:
            logger.error(f"SSH command failed: {e}")
            return []
    
    def _mirror_remote_packages(self):
        """CRITICAL STEP: Download ALL remote package files to local directory."""
        print("\n" + "="*60)
        print("MANDATORY STEP: Mirroring remote packages locally")
        print("="*60)
        
        # Create a temporary local repository directory
        mirror_dir = Path("/tmp/repo_mirror")
        if mirror_dir.exists():
            shutil.rmtree(mirror_dir, ignore_errors=True)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created local mirror directory: {mirror_dir}")
        
        # Use rsync to download ALL package files from server
        print("📥 Downloading ALL remote package files to local mirror...")
        
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          --include='*.pkg.tar.zst' \
          --include='*.pkg.tar.xz' \
          --exclude='*' \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60" \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/' \
          '{mirror_dir}/'
        """
        
        logger.info(f"RUNNING RSYNC MIRROR COMMAND:")
        logger.info(rsync_cmd.strip())
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines()[-20:]:  # Last 20 lines
                    if line.strip():
                        logger.info(f"RSYNC MIRROR: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip():
                        logger.error(f"RSYNC MIRROR ERR: {line}")
            
            if result.returncode == 0:
                # List downloaded files
                downloaded_files = list(mirror_dir.glob("*.pkg.tar.*"))
                file_count = len(downloaded_files)
                
                if file_count > 0:
                    logger.info(f"✅ Successfully mirrored {file_count} package files ({duration} seconds)")
                    logger.info(f"Sample mirrored files: {[f.name for f in downloaded_files[:5]]}")
                    
                    # Verify file integrity
                    valid_files = []
                    for pkg_file in downloaded_files:
                        if pkg_file.stat().st_size > 0:
                            valid_files.append(pkg_file)
                        else:
                            logger.warning(f"⚠️ Empty file: {pkg_file.name}")
                    
                    logger.info(f"Valid mirrored packages: {len(valid_files)}/{file_count}")
                    
                    # Copy mirrored packages to output directory
                    print(f"📋 Copying {len(valid_files)} mirrored packages to output directory...")
                    copied_count = 0
                    for pkg_file in valid_files:
                        dest = self.output_dir / pkg_file.name
                        if not dest.exists():  # Don't overwrite newly built packages
                            shutil.copy2(pkg_file, dest)
                            copied_count += 1
                    
                    logger.info(f"Copied {copied_count} mirrored packages to output directory")
                    
                    # Clean up mirror directory
                    shutil.rmtree(mirror_dir, ignore_errors=True)
                    
                    return True
                else:
                    logger.warning("ℹ️ No package files were mirrored (repository might be empty)")
                    shutil.rmtree(mirror_dir, ignore_errors=True)
                    return True  # Not an error, just empty repository
            else:
                logger.error(f"❌ RSYNC mirror failed with code {result.returncode}")
                shutil.rmtree(mirror_dir, ignore_errors=True)
                return False
                
        except Exception as e:
            logger.error(f"RSYNC mirror execution error: {e}")
            if mirror_dir.exists():
                shutil.rmtree(mirror_dir, ignore_errors=True)
            return False
    
    def _check_database_files(self):
        """Check if repository database files exist on server."""
        print("\n" + "="*60)
        print("STEP 2: Checking existing database files on server")
        print("="*60)
        
        db_files = [
            f"{self.repo_name}.db",
            f"{self.repo_name}.db.tar.gz",
            f"{self.repo_name}.files",
            f"{self.repo_name}.files.tar.gz"
        ]
        
        existing_files = []
        missing_files = []
        
        for db_file in db_files:
            remote_cmd = f"test -f {self.remote_dir}/{db_file} && echo 'EXISTS' || echo 'MISSING'"
            
            ssh_cmd = [
                "ssh",
                f"{self.vps_user}@{self.vps_host}",
                remote_cmd
            ]
            
            try:
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0 and "EXISTS" in result.stdout:
                    existing_files.append(db_file)
                    logger.info(f"✅ Database file exists: {db_file}")
                else:
                    missing_files.append(db_file)
                    logger.info(f"ℹ️ Database file missing: {db_file}")
                    
            except Exception as e:
                logger.warning(f"Could not check {db_file}: {e}")
                missing_files.append(db_file)
        
        if existing_files:
            logger.info(f"Found {len(existing_files)} database files on server")
        else:
            logger.info("No database files found on server")
        
        return existing_files, missing_files
    
    def _fetch_existing_database(self, existing_files):
        """Fetch existing database files from server."""
        if not existing_files:
            return
        
        print("\n📥 Fetching existing database files from server...")
        
        for db_file in existing_files:
            remote_path = f"{self.remote_dir}/{db_file}"
            local_path = self.output_dir / db_file
            
            # Remove local copy if exists
            if local_path.exists():
                local_path.unlink()
            
            ssh_cmd = [
                "scp",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=30",
                f"{self.vps_user}@{self.vps_host}:{remote_path}",
                str(local_path)
            ]
            
            try:
                result = subprocess.run(
                    ssh_cmd,
                    capture_output=True,
                    text=True,
                    check=False
                )
                
                if result.returncode == 0 and local_path.exists():
                    size_mb = local_path.stat().st_size / (1024 * 1024)
                    logger.info(f"✅ Fetched: {db_file} ({size_mb:.2f} MB)")
                else:
                    logger.warning(f"⚠️ Could not fetch {db_file}")
            except Exception as e:
                logger.warning(f"Could not fetch {db_file}: {e}")
    
    def _get_all_local_packages(self):
        """Get ALL package files from local output directory (mirrored + newly built)."""
        print("\n🔍 Getting complete package list from local directory...")
        
        local_files = list(self.output_dir.glob("*.pkg.tar.*"))
        
        if not local_files:
            logger.info("ℹ️ No package files found locally")
            return []
        
        local_filenames = [f.name for f in local_files]
        
        logger.info(f"📊 Local package count: {len(local_filenames)}")
        logger.info(f"Sample packages: {local_filenames[:10]}")
        
        return local_filenames
    
    def _generate_full_database(self):
        """Generate repository database from ALL locally available packages."""
        print("\n" + "="*60)
        print("PHASE: Repository Database Generation")
        print("="*60)
        
        # Get all package files from local output directory
        all_packages = self._get_all_local_packages()
        
        if not all_packages:
            logger.info("No packages available for database generation")
            return False
        
        logger.info(f"Generating database with {len(all_packages)} packages...")
        logger.info(f"Packages: {', '.join(all_packages[:10])}{'...' if len(all_packages) > 10 else ''}")
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz", 
                      f"{self.repo_name}.files", f"{self.repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            # Verify each package file exists locally before database generation
            missing_packages = []
            valid_packages = []
            
            for pkg_filename in all_packages:
                if Path(pkg_filename).exists():
                    valid_packages.append(pkg_filename)
                else:
                    missing_packages.append(pkg_filename)
            
            if missing_packages:
                logger.error(f"❌ CRITICAL: {len(missing_packages)} packages missing locally:")
                for pkg in missing_packages[:5]:
                    logger.error(f"   - {pkg}")
                if len(missing_packages) > 5:
                    logger.error(f"   ... and {len(missing_packages) - 5} more")
                
                logger.error("Cannot generate database without all package files present locally")
                logger.error("This indicates a failure in the package mirroring step")
                return False
            
            if not valid_packages:
                logger.error("No valid package files found for database generation")
                return False
            
            logger.info(f"✅ All {len(valid_packages)} package files verified locally")
            
            # Generate database with repo-add
            cmd = ["repo-add", db_file] + valid_packages
            
            logger.info(f"Running repo-add with {len(valid_packages)} packages...")
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                logger.info("✅ Database created successfully")
                
                # Verify the database was created
                db_path = Path(db_file)
                if db_path.exists():
                    size_mb = db_path.stat().st_size / (1024 * 1024)
                    logger.info(f"Database size: {size_mb:.2f} MB")
                    
                    # List packages in database for verification
                    list_cmd = ["tar", "-tzf", db_file]
                    list_result = subprocess.run(list_cmd, capture_output=True, text=True, check=False)
                    if list_result.returncode == 0:
                        db_entries = [line for line in list_result.stdout.split('\n') if line.endswith('/desc')]
                        logger.info(f"Database contains {len(db_entries)} package entries")
                
                return True
            else:
                logger.error(f"repo-add failed: {result.stderr}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def _sync_pacman_databases(self):
        """Sync pacman databases ONLY after repository database is guaranteed."""
        print("\n" + "="*60)
        print("FINAL STEP: Syncing pacman databases (sudo pacman -Sy --noconfirm)")
        print("="*60)
        
        cmd = "sudo pacman -Sy --noconfirm"
        result = self.run_cmd(cmd, log_cmd=True)
        
        if result.returncode != 0:
            logger.error("❌ Failed to sync pacman databases")
            return False
        
        logger.info("✅ Pacman databases synced successfully")
        return True
    
    def _apply_repository_decision(self, decision):
        """Apply repository enable/disable decision."""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found")
            return
        
        try:
            with open(pacman_conf, 'r') as f:
                content = f.read()
            
            repo_section = f"[{self.repo_name}]"
            lines = content.split('\n')
            new_lines = []
            in_our_section = False
            
            for line in lines:
                if line.strip() == repo_section:
                    if decision == "DISABLE":
                        new_lines.append(f"#{repo_section}")
                    else:
                        new_lines.append(line)
                    in_our_section = True
                elif in_our_section:
                    if line.strip().startswith('[') or line.strip() == '':
                        in_our_section = False
                        new_lines.append(line)
                    else:
                        if decision == "DISABLE":
                            new_lines.append(f"#{line}")
                        else:
                            new_lines.append(line)
                else:
                    new_lines.append(line)
            
            content = '\n'.join(new_lines)
            subprocess.run(['sudo', 'tee', str(pacman_conf)], input=content.encode(), check=True)
            
            action = "enabled" if decision == "ENABLE" else "disabled"
            logger.info(f"✅ Repository '{self.repo_name}' {action} in pacman.conf")
            
        except Exception as e:
            logger.error(f"Failed to apply repository decision: {e}")
    
    def package_exists(self, pkg_name, version=None):
        """Check if package exists on server."""
        if not self.remote_files:
            return False
        
        pattern = f"^{re.escape(pkg_name)}-"
        matches = [f for f in self.remote_files if re.match(pattern, f)]
        
        if matches:
            logger.debug(f"Package {pkg_name} exists: {matches[0]}")
            return True
        
        return False
    
    def get_remote_version(self, pkg_name):
        """Get the version of a package from remote server."""
        if not self.remote_files:
            return None
        
        pattern = f"^{re.escape(pkg_name)}-([0-9].*?)-"
        for filename in self.remote_files:
            match = re.match(pattern, filename)
            if match:
                return match.group(1)
        
        return None
    
    def get_package_lists(self):
        """Get package lists from packages.py or exit if not available."""
        if HAS_CONFIG_FILES and hasattr(packages, 'LOCAL_PACKAGES') and hasattr(packages, 'AUR_PACKAGES'):
            print("📦 Using package lists from packages.py")
            return packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
        else:
            logger.error("Cannot load package lists from packages.py. Exiting.")
            sys.exit(1)
    
    def _install_dependencies_strict(self, deps):
        """STRICT dependency resolution: pacman first, then yay."""
        if not deps:
            return True
        
        print(f"\nInstalling {len(deps)} dependencies...")
        logger.info(f"Dependencies to install: {deps}")
        
        # Clean dependency names
        clean_deps = []
        for dep in deps:
            dep_clean = re.sub(r'[<=>].*', '', dep).strip()
            if dep_clean and not any(x in dep_clean for x in ['$', '{', '}']):
                clean_deps.append(dep_clean)
        
        if not clean_deps:
            return True
        
        # STEP 1: Try system packages FIRST with sudo
        print("STEP 1: Trying pacman (sudo)...")
        deps_str = ' '.join(clean_deps)
        cmd = f"sudo pacman -S --needed --noconfirm {deps_str}"
        result = self.run_cmd(cmd, log_cmd=True, check=False)
        
        if result.returncode == 0:
            logger.info("✅ All dependencies installed via pacman")
            return True
        
        logger.warning(f"⚠️ pacman failed for some dependencies, trying yay...")
        
        # STEP 2: Fallback to AUR (yay) WITHOUT sudo
        print("STEP 2: Trying yay (without sudo)...")
        cmd = f"yay -S --needed --noconfirm {deps_str}"
        result = self.run_cmd(cmd, log_cmd=True, check=False, user="builder")
        
        if result.returncode == 0:
            logger.info("✅ Dependencies installed via yay")
            return True
        
        # STEP 3: Failure handling - mark as failed but continue
        logger.error(f"❌ Failed to install dependencies: {deps}")
        print(f"Failed dependencies: {deps}")
        return False
    
    def _extract_dependencies_from_srcinfo(self, pkg_dir):
        """Extract dependencies from .SRCINFO file."""
        srcinfo = pkg_dir / ".SRCINFO"
        if not srcinfo.exists():
            return []
        
        deps = []
        makedeps = []
        checkdeps = []
        
        with open(srcinfo, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('depends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        deps.append(dep)
                elif line.startswith('makedepends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        makedeps.append(dep)
                elif line.startswith('checkdepends ='):
                    dep = line.split('=', 1)[1].strip()
                    if dep and not any(x in dep for x in ['$', '{', '}']):
                        checkdeps.append(dep)
        
        return deps + makedeps + checkdeps
    
    def _extract_dependencies_from_pkgbuild(self, pkg_dir):
        """Extract dependencies from PKGBUILD as fallback."""
        pkgbuild_path = pkg_dir / "PKGBUILD"
        if not pkgbuild_path.exists():
            return []
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            deps = []
            
            # Look for depends=(
            dep_match = re.search(r'depends\s*=\s*\((.*?)\)', content, re.DOTALL)
            if dep_match:
                dep_content = dep_match.group(1)
                for line in dep_content.split('\n'):
                    line = line.strip().strip("'\"")
                    if line and not line.startswith('#') and not any(x in line for x in ['$', '{', '}']):
                        deps.append(line)
            
            # Look for makedepends=(
            makedep_match = re.search(r'makedepends\s*=\s*\((.*?)\)', content, re.DOTALL)
            if makedep_match:
                makedep_content = makedep_match.group(1)
                for line in makedep_content.split('\n'):
                    line = line.strip().strip("'\"")
                    if line and not line.startswith('#') and not any(x in line for x in ['$', '{', '}']):
                        deps.append(line)
            
            return deps
            
        except Exception as e:
            logger.error(f"Failed to parse PKGBUILD for dependencies: {e}")
            return []
    
    def _install_package_dependencies(self, pkg_dir, pkg_name):
        """Install dependencies for a package."""
        print(f"Checking dependencies for {pkg_name}...")
        
        # First try .SRCINFO
        deps = self._extract_dependencies_from_srcinfo(pkg_dir)
        
        # If no .SRCINFO, try PKGBUILD
        if not deps:
            deps = self._extract_dependencies_from_pkgbuild(pkg_dir)
        
        if not deps:
            logger.info(f"No dependencies for {pkg_name}")
            return
        
        # Special dependencies from config
        special_deps = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
        if pkg_name in special_deps:
            logger.info(f"Adding special dependencies for {pkg_name}")
            deps.extend(special_deps[pkg_name])
        
        self._install_dependencies_strict(deps)
    
    def _extract_package_metadata(self, pkg_file_path):
        """Extract metadata from built package file for hokibot observation."""
        try:
            filename = os.path.basename(pkg_file_path)
            base_name = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
            parts = base_name.split('-')
            
            arch = parts[-1]
            pkgrel = parts[-2]
            version_part = parts[-3]
            
            version_index = len(parts) - 3
            pkgname = '-'.join(parts[:version_index])
            
            epoch = None
            pkgver = version_part
            if ':' in version_part:
                epoch_part, pkgver = version_part.split(':', 1)
                epoch = epoch_part
            
            return {
                'filename': filename,
                'pkgname': pkgname,
                'pkgver': pkgver,
                'pkgrel': pkgrel,
                'epoch': epoch,
                'built_version': f"{epoch + ':' if epoch else ''}{pkgver}-{pkgrel}"
            }
        except Exception as e:
            logger.warning(f"Could not extract metadata from {pkg_file_path}: {e}")
            return None
    
    def _build_aur_package(self, pkg_name):
        """Build AUR package."""
        aur_dir = self.repo_root / "build_aur"
        aur_dir.mkdir(exist_ok=True)
        
        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)
        
        print(f"Cloning {pkg_name} from AUR...")
        
        # Try different AUR URLs
        aur_urls = [
            f"https://aur.archlinux.org/{pkg_name}.git",
            f"git://aur.archlinux.org/{pkg_name}.git",
        ]
        
        clone_success = False
        for aur_url in aur_urls:
            logger.info(f"Trying AUR URL: {aur_url}")
            result = self.run_cmd(
                f"git clone --depth 1 {aur_url} {pkg_dir}",
                check=False
            )
            if result and result.returncode == 0:
                clone_success = True
                logger.info(f"Successfully cloned {pkg_name} from {aur_url}")
                break
            else:
                if pkg_dir.exists():
                    shutil.rmtree(pkg_dir, ignore_errors=True)
                logger.warning(f"Failed to clone from {aur_url}")
        
        if not clone_success:
            logger.error(f"Failed to clone {pkg_name} from any AUR URL")
            return False
        
        # Set correct permissions
        self.run_cmd(f"chown -R builder:builder {pkg_dir}", check=False)
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
        
        # Extract version info
        content = pkgbuild.read_text()
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        if pkgver_match and pkgrel_match:
            version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
            
            if self.package_exists(pkg_name):
                logger.info(f"✅ {pkg_name} already exists on server - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            remote_version = self.get_remote_version(pkg_name)
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
        else:
            version = "unknown"
            logger.warning(f"Could not extract version for {pkg_name}")
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
            
            # Install dependencies
            self._install_package_dependencies(pkg_dir, pkg_name)
            
            print("Building package...")
            build_result = self.run_cmd(
                f"makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            if build_result.returncode == 0:
                moved = False
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                
                shutil.rmtree(pkg_dir, ignore_errors=True)
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                logger.error(f"Failed to build {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False
    
    def _build_local_package(self, pkg_name):
        """Build local package."""
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"Package directory not found: {pkg_name}")
            return False
        
        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"No PKGBUILD found for {pkg_name}")
            return False
        
        content = pkgbuild.read_text()
        pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        epoch_match = re.search(r'^epoch\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
        
        if pkgver_match and pkgrel_match:
            version = f"{pkgver_match.group(1)}-{pkgrel_match.group(1)}"
            
            if self.package_exists(pkg_name):
                logger.info(f"✅ {pkg_name} already exists on server - skipping")
                self.skipped_packages.append(f"{pkg_name} ({version})")
                return False
            
            remote_version = self.get_remote_version(pkg_name)
            if remote_version:
                logger.info(f"ℹ️  {pkg_name}: remote has {remote_version}, building {version}")
            else:
                logger.info(f"ℹ️  {pkg_name}: not on server, building {version}")
        else:
            version = "unknown"
            logger.warning(f"Could not extract version for {pkg_name}")
        
        try:
            logger.info(f"Building {pkg_name} ({version})...")
            
            print("Downloading sources...")
            source_result = self.run_cmd(f"makepkg -od --noconfirm", 
                                        cwd=pkg_dir, check=False, capture=True)
            if source_result.returncode != 0:
                logger.error(f"Failed to download sources for {pkg_name}")
                return False
            
            # Install dependencies
            self._install_package_dependencies(pkg_dir, pkg_name)
            
            print("Building package...")
            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                logger.info("GTK2: Skipping check step (long)")
            
            build_result = self.run_cmd(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                capture=True,
                check=False
            )
            
            if build_result.returncode == 0:
                moved = False
                built_files = []
                for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                    dest = self.output_dir / pkg_file.name
                    shutil.move(str(pkg_file), str(dest))
                    self.packages_to_clean.add(pkg_name)
                    logger.info(f"✅ Built: {pkg_file.name}")
                    moved = True
                    built_files.append(str(dest))
                
                if moved:
                    self.built_packages.append(f"{pkg_name} ({version})")
                    self.rebuilt_local_packages.append(pkg_name)
                    
                    # Collect metadata for hokibot
                    if built_files:
                        metadata = self._extract_package_metadata(built_files[0])
                        if metadata:
                            self.hokibot_data.append({
                                'name': pkg_name,
                                'built_version': metadata['built_version'],
                                'pkgver': metadata['pkgver'],
                                'pkgrel': metadata['pkgrel'],
                                'epoch': metadata['epoch']
                            })
                            logger.info(f"📝 HOKIBOT observed: {pkg_name} -> {metadata['built_version']}")
                    
                    return True
                else:
                    logger.error(f"No package files created for {pkg_name}")
                    return False
            else:
                logger.error(f"Failed to build {pkg_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error building {pkg_name}: {e}")
            return False
    
    def _build_single_package(self, pkg_name, is_aur):
        """Build a single package."""
        print(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")
        
        if is_aur:
            return self._build_aur_package(pkg_name)
        else:
            return self._build_local_package(pkg_name)
    
    def build_packages(self):
        """Build packages."""
        print("\n" + "="*60)
        print("Building packages")
        print("="*60)
        
        local_packages, aur_packages = self.get_package_lists()
        
        print(f"📦 Package statistics:")
        print(f"   Local packages: {len(local_packages)}")
        print(f"   AUR packages: {len(aur_packages)}")
        print(f"   Total packages: {len(local_packages) + len(aur_packages)}")
        
        print(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if self._build_single_package(pkg, is_aur=True):
                self.stats["aur_success"] += 1
            else:
                self.stats["aur_failed"] += 1
        
        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if self._build_single_package(pkg, is_aur=False):
                self.stats["local_success"] += 1
            else:
                self.stats["local_failed"] += 1
        
        return self.stats["aur_success"] + self.stats["local_success"]
    
    def _update_pkgbuild_in_clone(self, clone_dir, pkg_data):
        """Update a single PKGBUILD in the git clone based on observed data."""
        pkg_dir = clone_dir / pkg_data['name']
        pkgbuild_path = pkg_dir / "PKGBUILD"
        
        if not pkgbuild_path.exists():
            logger.warning(f"PKGBUILD not found in clone for {pkg_data['name']}")
            return False
        
        try:
            with open(pkgbuild_path, 'r') as f:
                content = f.read()
            
            changed = False
            
            current_pkgver_match = re.search(r'^pkgver\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if current_pkgver_match:
                current_pkgver = current_pkgver_match.group(1)
                if current_pkgver != pkg_data['pkgver']:
                    content = re.sub(
                        r'^pkgver\s*=\s*["\']?[^"\'\n]+',
                        f"pkgver={pkg_data['pkgver']}",
                        content,
                        flags=re.MULTILINE
                    )
                    changed = True
                    logger.info(f"  Updated pkgver: {current_pkgver} -> {pkg_data['pkgver']}")
            
            current_pkgrel_match = re.search(r'^pkgrel\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if current_pkgrel_match:
                current_pkgrel = current_pkgrel_match.group(1)
                if current_pkgrel != pkg_data['pkgrel']:
                    content = re.sub(
                        r'^pkgrel\s*=\s*["\']?[^"\'\n]+',
                        f"pkgrel={pkg_data['pkgrel']}",
                        content,
                        flags=re.MULTILINE
                    )
                    changed = True
                    logger.info(f"  Updated pkgrel: {current_pkgrel} -> {pkg_data['pkgrel']}")
            
            current_epoch_match = re.search(r'^epoch\s*=\s*["\']?([^"\'\n]+)', content, re.MULTILINE)
            if pkg_data['epoch'] is not None:
                if current_epoch_match:
                    current_epoch = current_epoch_match.group(1)
                    if current_epoch != pkg_data['epoch']:
                        content = re.sub(
                            r'^epoch\s*=\s*["\']?[^"\'\n]+',
                            f"epoch={pkg_data['epoch']}",
                            content,
                            flags=re.MULTILINE
                        )
                        changed = True
                        logger.info(f"  Updated epoch: {current_epoch} -> {pkg_data['epoch']}")
                else:
                    lines = content.split('\n')
                    new_lines = []
                    epoch_added = False
                    for line in lines:
                        new_lines.append(line)
                        if not epoch_added and line.strip().startswith('pkgver='):
                            new_lines.append(f'epoch={pkg_data["epoch"]}')
                            epoch_added = True
                            changed = True
                            logger.info(f"  Added epoch: {pkg_data['epoch']}")
                    content = '\n'.join(new_lines)
            else:
                if current_epoch_match:
                    content = re.sub(r'^epoch\s*=\s*["\']?[^"\'\n]+\n?', '', content, flags=re.MULTILINE)
                    changed = True
                    logger.info(f"  Removed epoch: {current_epoch_match.group(1)}")
            
            if changed:
                with open(pkgbuild_path, 'w') as f:
                    f.write(content)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to update PKGBUILD for {pkg_data['name']} in clone: {e}")
            return False
    
    def _synchronize_pkgbuilds(self):
        """PHASE 2: Isolated PKGBUILD synchronization."""
        if not self.hokibot_data:
            logger.info("No local packages were rebuilt - skipping PKGBUILD synchronization")
            return
        
        print("\n" + "="*60)
        print("🔄 PHASE 2: Isolated PKGBUILD Synchronization")
        print("="*60)
        
        clone_dir = Path("/tmp/manjaro-awesome-gitclone")
        
        try:
            if clone_dir.exists():
                shutil.rmtree(clone_dir)
            
            clone_dir.mkdir(parents=True, exist_ok=True)
            
            github_ssh_key = os.getenv('CI_PUSH_SSH_KEY')
            if not github_ssh_key:
                logger.warning("CI_PUSH_SSH_KEY not set in environment - skipping PKGBUILD sync")
                return
            
            # Use GITHUB_TOKEN for authentication instead of SSH key
            repo_url = f"https://x-access-token:{github_ssh_key}@github.com/megvadulthangya/manjaro-awesome.git"
            
            print(f"📥 Cloning repository to {clone_dir}...")
            clone_result = subprocess.run(
                ['git', 'clone', repo_url, str(clone_dir)],
                capture_output=True,
                text=True
            )
            
            if clone_result.returncode != 0:
                logger.error(f"Failed to clone repository: {clone_result.stderr}")
                return
            
            subprocess.run(
                ['git', 'config', 'user.name', 'GitHub Actions Builder'],
                cwd=clone_dir,
                capture_output=True
            )
            subprocess.run(
                ['git', 'config', 'user.email', 'builder@github-actions.local'],
                cwd=clone_dir,
                capture_output=True
            )
            
            modified_packages = []
            for pkg_data in self.hokibot_data:
                print(f"\n📝 Processing {pkg_data['name']}...")
                print(f"   Observed version: {pkg_data['built_version']}")
                
                if self._update_pkgbuild_in_clone(clone_dir, pkg_data):
                    modified_packages.append(pkg_data['name'])
            
            if not modified_packages:
                print("\n✅ No PKGBUILDs needed updates")
                return
            
            print(f"\n📝 Committing changes for {len(modified_packages)} package(s)...")
            
            for pkg_name in modified_packages:
                pkgbuild_path = clone_dir / pkg_name / "PKGBUILD"
                if pkgbuild_path.exists():
                    subprocess.run(
                        ['git', 'add', str(pkgbuild_path.relative_to(clone_dir))],
                        cwd=clone_dir,
                        capture_output=True
                    )
            
            commit_msg = f"chore: synchronize PKGBUILDs with built versions\n\n"
            commit_msg += f"Updated {len(modified_packages)} rebuilt local package(s):\n"
            for pkg_name in modified_packages:
                for pkg_data in self.hokibot_data:
                    if pkg_data['name'] == pkg_name:
                        commit_msg += f"- {pkg_name}: {pkg_data['built_version']}\n"
                        break
            
            commit_result = subprocess.run(
                ['git', 'commit', '-m', commit_msg],
                cwd=clone_dir,
                capture_output=True,
                text=True
            )
            
            if commit_result.returncode == 0:
                print("✅ Changes committed")
                
                print("\n📤 Pushing changes to main branch...")
                push_result = subprocess.run(
                    ['git', 'push', 'origin', 'main'],
                    cwd=clone_dir,
                    capture_output=True,
                    text=True
                )
                
                if push_result.returncode == 0:
                    print("✅ Changes pushed to main branch")
                else:
                    logger.error(f"Failed to push changes: {push_result.stderr}")
            else:
                logger.warning(f"Commit failed or no changes: {commit_result.stderr}")
            
        except Exception as e:
            logger.error(f"Error during PKGBUILD synchronization: {e}")
            import traceback
            traceback.print_exc()
    
    def upload_packages(self):
        """Upload packages to server using RSYNC - WITH RETRY LOGIC."""
        # Get all package files and database files
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))
        
        all_files = pkg_files + db_files
        
        if not all_files:
            logger.warning("No files to upload")
            return False
        
        logger.info(f"Uploading {len(all_files)} files...")
        
        # Collect files using glob patterns
        file_patterns = [
            str(self.output_dir / "*.pkg.tar.*"),
            str(self.output_dir / f"{self.repo_name}.*")
        ]
        
        files_to_upload = []
        for pattern in file_patterns:
            files_to_upload.extend(glob.glob(pattern))
        
        if not files_to_upload:
            logger.error("No files found to upload!")
            return False
        
        # Log files to upload
        logger.info(f"Files to upload ({len(files_to_upload)}):")
        for f in files_to_upload:
            size_mb = os.path.getsize(f) / (1024 * 1024)
            file_type = "DATABASE" if self.repo_name in os.path.basename(f) else "PACKAGE"
            logger.info(f"  - {os.path.basename(f)} ({size_mb:.1f}MB) [{file_type}]")
        
        # Build RSYNC command with SSH config (no -e option, uses SSH config)
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          --chmod=0644 \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        # Log the command
        logger.info(f"RUNNING RSYNC COMMAND:")
        logger.info(rsync_cmd.strip())
        logger.info(f"SOURCE: {self.output_dir}/")
        logger.info(f"DESTINATION: {self.vps_user}@{self.vps_host}:{self.remote_dir}/")
        
        # FIRST ATTEMPT
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE (attempt 1): {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"RSYNC: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip():
                        logger.error(f"RSYNC ERR: {line}")
            
            if result.returncode == 0:
                logger.info(f"✅ RSYNC upload successful! ({duration} seconds)")
                # Verification is now non-blocking - errors don't affect success
                try:
                    self._verify_uploaded_files(files_to_upload)
                except Exception as e:
                    logger.warning(f"⚠️ Verification error (upload still successful): {e}")
                return True
            else:
                logger.warning(f"⚠️ First RSYNC attempt failed (code: {result.returncode})")
                
        except Exception as e:
            logger.error(f"RSYNC execution error: {e}")
        
        # SECOND ATTEMPT (with different SSH options)
        logger.info("⚠️ Retrying with different SSH options...")
        time.sleep(5)
        
        # Use -e option with SSH command this time
        rsync_cmd_retry = f"""
        rsync -avz \
          --progress \
          --stats \
          --chmod=0644 \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=60 -o ServerAliveInterval=30 -o ServerAliveCountMax=3" \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.vps_user}@{self.vps_host}:{self.remote_dir}/'
        """
        
        logger.info(f"RUNNING RSYNC RETRY COMMAND:")
        logger.info(rsync_cmd_retry.strip())
        
        start_time = time.time()
        
        try:
            result = subprocess.run(
                rsync_cmd_retry,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            logger.info(f"EXIT CODE (attempt 2): {result.returncode}")
            if result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"RSYNC RETRY: {line}")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip():
                        logger.error(f"RSYNC RETRY ERR: {line}")
            
            if result.returncode == 0:
                logger.info(f"✅ RSYNC upload successful on retry! ({duration} seconds)")
                # Verification is now non-blocking - errors don't affect success
                try:
                    self._verify_uploaded_files(files_to_upload)
                except Exception as e:
                    logger.warning(f"⚠️ Verification error (upload still successful): {e}")
                return True
            else:
                logger.error(f"❌ RSYNC upload failed on both attempts!")
                return False
                
        except Exception as e:
            logger.error(f"RSYNC retry execution error: {e}")
            return False
    
    def _verify_uploaded_files(self, uploaded_files):
        """Verify uploaded files on remote server."""
        logger.info("Verifying uploaded files on remote server...")
        
        # Get list of files we uploaded
        uploaded_filenames = [os.path.basename(f) for f in uploaded_files]
        
        # Check remote directory - FIXED: Use proper string formatting for shell variable
        remote_cmd = f"""
        echo "=== REMOTE DIRECTORY ==="
        ls -la "{self.remote_dir}/" 2>/dev/null | head -30
        echo ""
        echo "=== UPLOADED FILES ==="
        for file in {" ".join(uploaded_filenames)}; do
            if [ -f "{self.remote_dir}/$file" ]; then
                size=$(stat -c%s "{self.remote_dir}/$file" 2>/dev/null || echo "0")
                size_mb=$(echo "scale=2; $size / 1048576" | bc 2>/dev/null || echo "0")
                echo "✅ $file (${{size_mb}}MB)"
            else
                echo "❌ $file - MISSING"
            fi
        done
        echo ""
        echo "=== DATABASE STATE ==="
        ls -la "{self.remote_dir}/{self.repo_name}.*" 2>/dev/null || echo "No database files found"
        echo ""
        echo "=== DISK USAGE ==="
        df -h "{self.remote_dir}" 2>/dev/null || echo "Disk info not available"
        """
        
        ssh_cmd = [
            "ssh",
            f"{self.vps_user}@{self.vps_host}",
            remote_cmd
        ]
        
        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.splitlines():
                    if line.strip():
                        logger.info(f"VERIFY: {line}")
            else:
                if result.stderr:
                    logger.warning(f"Verification warning: {result.stderr[:200]}")
                    
        except Exception as e:
            logger.warning(f"Verification error: {e}")
    
    def cleanup_old_packages(self):
        """Remove old package versions (keep only last 3 versions)."""
        if not self.packages_to_clean:
            logger.info("No packages to clean up")
            return
        
        logger.info(f"Cleaning up old versions for {len(self.packages_to_clean)} packages...")
        
        cleaned = 0
        for pkg in self.packages_to_clean:
            # Keep only the last 3 versions of each package
            remote_cmd = (
                f'cd {self.remote_dir} && '
                f'ls -t {pkg}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | '
                f'xargs -r rm -f 2>/dev/null || true'
            )
            
            ssh_cmd = [
                "ssh",
                f"{self.vps_user}@{self.vps_host}",
                remote_cmd
            ]
            
            logger.info(f"CLEANUP COMMAND: {' '.join(ssh_cmd)}")
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=False)
            
            logger.info(f"EXIT CODE: {result.returncode}")
            if result.returncode == 0:
                cleaned += 1
            else:
                if result.stderr:
                    logger.warning(f"Cleanup warning for {pkg}: {result.stderr[:200]}")
        
        logger.info(f"✅ Cleanup complete ({cleaned} packages processed)")
    
    def run(self):
        """Main execution with CORRECT Arch Linux repository ordering and LOCAL MIRRORING."""
        print("\n" + "="*60)
        print("🚀 MANJARO PACKAGE BUILDER (CORRECT ARCH ORDERING + LOCAL MIRROR)")
        print("="*60)
        
        try:
            print("\n🔧 Initial setup...")
            print(f"Repository root: {self.repo_root}")
            print(f"Repository name: {self.repo_name}")
            print(f"Output directory: {self.output_dir}")
            
            special_deps = getattr(config, 'SPECIAL_DEPENDENCIES', {}) if HAS_CONFIG_FILES else {}
            print(f"Special dependencies loaded: {len(special_deps)}")
            
            # STEP 1: SSH/rsync - List all *.pkg.tar.zst files
            print("\n" + "="*60)
            print("PHASE 1: REPOSITORY FILESYSTEM STATE (SOURCE OF TRUTH)")
            print("="*60)
            
            # Disable repository initially to prevent pacman errors
            self._apply_repository_decision("DISABLE")
            
            remote_packages = self._list_remote_packages()
            
            # MANDATORY STEP: Mirror ALL remote packages locally before any database operations
            if remote_packages:
                print("\n" + "="*60)
                print("MANDATORY PRECONDITION: Mirroring remote packages locally")
                print("="*60)
                
                if not self._mirror_remote_packages():
                    logger.error("❌ FAILED to mirror remote packages locally")
                    logger.error("Cannot proceed without local package mirror")
                    return 1
            else:
                logger.info("ℹ️ No remote packages to mirror (repository appears empty)")
            
            # STEP 2: Check existing database files
            existing_db_files, missing_db_files = self._check_database_files()
            
            # Fetch existing database if available
            if existing_db_files:
                self._fetch_existing_database(existing_db_files)
            
            # Build packages (repository is disabled during build)
            print("\n" + "="*60)
            print("PHASE 2: PACKAGE BUILDING")
            print("="*60)
            
            total_built = self.build_packages()
            
            # Check if we have any packages locally (mirrored + newly built)
            local_packages = self._get_all_local_packages()
            
            if local_packages or remote_packages:
                print("\n" + "="*60)
                print("PHASE 3: REPOSITORY DATABASE HANDLING (WITH LOCAL MIRROR)")
                print("="*60)
                
                # Generate database with ALL locally available packages
                if self._generate_full_database():
                    # Upload regenerated database and packages
                    if not self.test_ssh_connection():
                        logger.warning("SSH test failed, but trying upload anyway...")
                    
                    # Upload everything (packages + database)
                    upload_success = self.upload_packages()
                    
                    if upload_success:
                        # Cleanup old packages
                        self.cleanup_old_packages()
                        
                        # STEP 4: ONLY NOW enable repository and sync pacman
                        print("\n" + "="*60)
                        print("PHASE 4: PACMAN SYNCHRONIZATION (CONSUMER)")
                        print("="*60)
                        
                        self._apply_repository_decision("ENABLE")
                        self._sync_pacman_databases()
                        
                        # Synchronize PKGBUILDs
                        self._synchronize_pkgbuilds()
                        
                        print("\n✅ Build completed successfully!")
                    else:
                        print("\n❌ Upload failed!")
                else:
                    print("\n❌ Database generation failed!")
            else:
                print("\n📊 Build summary:")
                print(f"   AUR packages built: {self.stats['aur_success']}")
                print(f"   AUR packages failed: {self.stats['aur_failed']}")
                print(f"   Local packages built: {self.stats['local_success']}")
                print(f"   Local packages failed: {self.stats['local_failed']}")
                print(f"   Total skipped: {len(self.skipped_packages)}")
                
                if self.stats['aur_failed'] > 0 or self.stats['local_failed'] > 0:
                    print("⚠️ Some packages failed to build")
                else:
                    print("✅ All packages are up to date or built successfully!")
                
                # Even if no packages built, ensure repository is in correct state
                if remote_packages:
                    self._apply_repository_decision("ENABLE")
                    self._sync_pacman_databases()
            
            elapsed = time.time() - self.stats["start_time"]
            
            print("\n" + "="*60)
            print("📊 BUILD SUMMARY")
            print("="*60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {self.stats['aur_success']} (failed: {self.stats['aur_failed']})")
            print(f"Local packages:  {self.stats['local_success']} (failed: {self.stats['local_failed']})")
            print(f"Total built:     {total_built}")
            print(f"Skipped:         {len(self.skipped_packages)}")
            print("="*60)
            
            if self.built_packages:
                print("\n📦 Built packages:")
                for pkg in self.built_packages:
                    print(f"  - {pkg}")
            
            return 0
            
        except Exception as e:
            print(f"\n❌ Build failed: {e}")
            import traceback
            traceback.print_exc()
            return 1

if __name__ == "__main__":
    sys.exit(PackageBuilder().run())