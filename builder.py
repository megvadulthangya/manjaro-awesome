#!/usr/bin/env python3
"""
Unified Manjaro Package Builder
Consolidates all CI/CD logic from multiple bash scripts into a single Python solution.
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass
from datetime import datetime
import requests
import git
import yaml
from enum import Enum

# Import configuration
from config import (
    REPO_DB_NAME, OUTPUT_DIR, BUILD_TRACKING_DIR,
    SSH_REPO_URL, MAKEPKG_TIMEOUT, SPECIAL_DEPENDENCIES,
    PROVIDER_PREFERENCES, REQUIRED_BUILD_TOOLS
)

# Import package lists
from packages import LOCAL_PACKAGES, AUR_PACKAGES

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('builder.log')
    ]
)
logger = logging.getLogger(__name__)

class PackageType(Enum):
    LOCAL = "local"
    AUR = "aur"

@dataclass
class Package:
    name: str
    pkg_type: PackageType
    version: str = ""
    pkgrel: str = "1"
    source_dir: Path = None
    built_files: List[Path] = None
    
    def __post_init__(self):
        self.built_files = []
    
    @property
    def full_version(self) -> str:
        return f"{self.version}-{self.pkgrel}"

class PackageBuilder:
    def __init__(self):
        self.repo_root = Path(os.getcwd())
        self.output_dir = self.repo_root / OUTPUT_DIR
        self.build_tracking_dir = self.repo_root / BUILD_TRACKING_DIR
        
        # Load sensitive configuration from environment
        self._load_environment_config()
        
        # Package lists from imported modules
        self.local_packages = LOCAL_PACKAGES
        self.aur_packages = AUR_PACKAGES
        
        # Custom repository configuration
        self.custom_repo_config = self._generate_repo_config()
        
        # Setup directories
        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)
        
        # Tracking
        self.remote_files = []
        self.packages_to_clean = set()
        self.built_packages = []
        self.failed_packages = []
        
        # Statistics
        self.stats = {
            "start_time": time.time(),
            "aur_processed": 0,
            "local_processed": 0,
            "aur_success": 0,
            "local_success": 0,
            "dependencies_installed": 0,
            "bytes_uploaded": 0
        }
    
    def _load_environment_config(self):
        """Load all sensitive configuration from environment variables."""
        self.vps_user = os.getenv('VPS_USER', '')
        self.vps_host = os.getenv('VPS_HOST', '')
        self.gh_pat = os.getenv('GH_PAT', '')
        self.ssh_key = os.getenv('VPS_SSH_KEY', '')
        
        # Remote directory from environment (with fallback)
        self.remote_dir = os.getenv('REMOTE_DIR', '/var/www/repo')
        
        # Repository server URL for pacman.conf
        self.repo_server_url = os.getenv('REPO_SERVER_URL', 'https://your-repo.example.com')
        
        # Optional configuration
        self.ssh_port = os.getenv('VPS_SSH_PORT', '22')
        self.ssh_username = os.getenv('VPS_SSH_USERNAME', self.vps_user)
        self.repo_name = os.getenv('REPO_NAME', REPO_DB_NAME)
        
        # Validate required configuration
        self._validate_config()
    
    def _validate_config(self):
        """Validate that required configuration is present."""
        required_vars = ['VPS_USER', 'VPS_HOST', 'VPS_SSH_KEY']
        missing = [var for var in required_vars if not getattr(self, var.lower(), None)]
        
        if missing:
            logger.error(f"Missing required environment variables: {', '.join(missing)}")
            logger.error("Please set these in your GitHub repository secrets")
            sys.exit(1)
    
    def _generate_repo_config(self) -> str:
        """Generate pacman repository configuration."""
        return f"""[{self.repo_name}]
Server = {self.repo_server_url}
SigLevel = Optional TrustAll
"""
    
    def run_command(self, cmd: List[str], cwd: Path = None, env: Dict = None, 
                   capture_output: bool = False, check: bool = True,
                   timeout: int = None) -> subprocess.CompletedProcess:
        """Run a shell command with proper error handling."""
        logger.debug(f"Running command: {' '.join(cmd)}")
        
        if env is None:
            env = os.environ.copy()
        
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                capture_output=capture_output,
                text=True,
                check=check,
                timeout=timeout
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed (exit {e.returncode}): {' '.join(cmd)}")
            if e.stderr:
                logger.error(f"Stderr: {e.stderr[:500]}...")  # Limit output
            if check:
                raise
            return e
        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timeout after {timeout}s: {' '.join(cmd)}")
            raise
    
    def network_diagnostics(self) -> Dict[str, bool]:
        """Perform comprehensive network connectivity checks."""
        logger.info("=== NETWORK DIAGNOSTICS ===")
        
        test_urls = {
            "GitHub": "https://github.com",
            "AUR": "https://aur.archlinux.org",
            "GNOME": "https://github.com/GNOME/gtk/archive/refs/tags/2.24.33.tar.gz",
            "IP Info": "https://ipinfo.io/ip",
            "Custom Repo": self.repo_server_url
        }
        
        results = {}
        for name, url in test_urls.items():
            try:
                start = time.time()
                response = requests.get(url, timeout=10)
                elapsed = (time.time() - start) * 1000
                
                if response.status_code < 400:
                    logger.info(f"✓ {name}: Connected ({response.status_code}) - {elapsed:.0f}ms")
                    results[name] = True
                else:
                    logger.warning(f"✗ {name}: HTTP {response.status_code} - {elapsed:.0f}ms")
                    results[name] = False
                    
            except requests.exceptions.Timeout:
                logger.warning(f"✗ {name}: Timeout")
                results[name] = False
            except Exception as e:
                logger.warning(f"✗ {name}: Error - {str(e)}")
                results[name] = False
        
        # Test SSH connectivity
        try:
            self.run_command(
                ["ssh", "-o", "ConnectTimeout=10", f"{self.vps_user}@{self.vps_host}", "echo SSH_OK"],
                capture_output=True,
                check=False
            )
            logger.info("✓ SSH: Connection successful")
            results["SSH"] = True
        except:
            logger.warning("✗ SSH: Connection failed")
            results["SSH"] = False
        
        # Overall status
        success_rate = sum(results.values()) / len(results) * 100
        logger.info(f"Network diagnostics: {success_rate:.1f}% successful")
        
        return results
    
    def setup_environment(self):
        """Setup the build environment including pacman.conf and SSH."""
        logger.info("Setting up build environment...")
        
        # 1. Configure pacman.conf with custom repository
        self._configure_pacman()
        
        # 2. Setup SSH for builder
        self._setup_ssh()
        
        # 3. Install yay if not present
        self._install_yay()
        
        # 4. Git configuration
        self.run_command(["git", "config", "--global", "user.name", "GitHub Action Bot"])
        self.run_command(["git", "config", "--global", "user.email", "action@github.com"])
        
        # 5. System-wide git settings
        self.run_command(["git", "config", "--system", "--add", "safe.directory", "*"])
        os.environ["GIT_DISCOVERY_ACROSS_FILESYSTEM"] = "1"
        
        # 6. Ensure build tools are available
        self._ensure_build_tools()
        
        logger.info("Environment setup complete")
    
    def _configure_pacman(self):
        """Inject custom repository into pacman.conf with validation."""
        pacman_conf = Path("/etc/pacman.conf")
        
        if not pacman_conf.exists():
            logger.warning("pacman.conf not found, skipping custom repo configuration")
            return
        
        # Backup original
        backup_path = pacman_conf.with_suffix('.conf.backup')
        if not backup_path.exists():
            shutil.copy2(pacman_conf, backup_path)
            logger.debug(f"Created pacman.conf backup: {backup_path}")
        
        # Read current config
        content = pacman_conf.read_text()
        
        # Check if our repo is already configured
        repo_section = f"[{self.repo_name}]"
        if repo_section in content:
            logger.info(f"Custom repository '{self.repo_name}' already configured")
            
            # Update server URL if needed
            if self.repo_server_url not in content:
                logger.warning(f"Repository server URL might be different in pacman.conf")
            return
        
        # Find where to insert (before [community] or at end)
        lines = content.split('\n')
        insert_pos = len(lines)
        
        for i, line in enumerate(lines):
            if line.strip().startswith("[community]"):
                insert_pos = i
                break
            elif line.strip().startswith("[extra]"):
                insert_pos = i + 1
        
        # Insert our repo config with comment
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo_config = f"\n# Custom repository added by builder.py on {timestamp}\n"
        repo_config += self.custom_repo_config
        
        lines.insert(insert_pos, repo_config)
        
        # Write back
        pacman_conf.write_text('\n'.join(lines))
        logger.info(f"Custom repository '{self.repo_name}' added to pacman.conf")
        
        # Update pacman database
        try:
            self.run_command(["pacman", "-Sy", "--noconfirm"])
            logger.info("Pacman database synchronized")
        except Exception as e:
            logger.error(f"Failed to sync pacman database: {e}")
    
    def _setup_ssh(self):
        """Setup SSH keys for remote access with improved security."""
        ssh_dir = Path("/home/builder/.ssh")
        ssh_dir.mkdir(parents=True, exist_ok=True)
        
        # Set strict permissions on .ssh directory
        ssh_dir.chmod(0o700)
        
        # Write SSH key
        if self.ssh_key:
            key_path = ssh_dir / "id_ed25519"
            ssh_config = ssh_dir / "config"
            
            try:
                # Decode base64 key
                import base64
                try:
                    key_data = base64.b64decode(self.ssh_key)
                    key_path.write_bytes(key_data)
                except:
                    # If not base64, write as-is
                    key_path.write_text(self.ssh_key)
                
                key_path.chmod(0o600)
                logger.debug("SSH key written")
                
                # Create SSH config for the host
                ssh_config_content = f"""
Host {self.vps_host}
    HostName {self.vps_host}
    User {self.vps_user}
    Port {self.ssh_port}
    IdentityFile {key_path}
    StrictHostKeyChecking yes
    UserKnownHostsFile {ssh_dir / "known_hosts"}
"""
                ssh_config.write_text(ssh_config_content)
                ssh_config.chmod(0o600)
                
            except Exception as e:
                logger.error(f"Failed to setup SSH: {e}")
                raise
        
        # Add known hosts with verification
        known_hosts = ssh_dir / "known_hosts"
        known_hosts_content = []
        
        hosts_to_scan = []
        if self.vps_host:
            hosts_to_scan.append(self.vps_host)
        hosts_to_scan.append("github.com")
        
        for host in hosts_to_scan:
            try:
                result = self.run_command(
                    ["ssh-keyscan", "-H", "-p", self.ssh_port, host],
                    capture_output=True,
                    timeout=10
                )
                if result.stdout:
                    known_hosts_content.append(f"# {host}")
                    known_hosts_content.append(result.stdout.strip())
                    logger.debug(f"Added SSH key for {host}")
            except Exception as e:
                logger.warning(f"Failed to get SSH key for {host}: {e}")
        
        if known_hosts_content:
            known_hosts.write_text('\n'.join(known_hosts_content))
            known_hosts.chmod(0o600)
        
        # Set ownership
        self.run_command(["chown", "-R", "builder:builder", str(ssh_dir)])
        logger.info("SSH setup complete")
    
    def _install_yay(self):
        """Install yay AUR helper with proper configuration."""
        try:
            self.run_command(["which", "yay"], check=False, capture_output=True)
            logger.info("yay is already installed")
            return
        except:
            pass
        
        logger.info("Installing yay AUR helper...")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Clone yay
            self.run_command([
                "git", "clone", "https://aur.archlinux.org/yay.git",
                str(tmpdir_path / "yay")
            ], cwd=tmpdir_path)
            
            # Build and install
            self.run_command([
                "makepkg", "-si", "--noconfirm", "--clean"
            ], cwd=tmpdir_path / "yay")
        
        # Configure yay for automation
        yay_config_commands = [
            ["yay", "-Y", "--gendb", "--noconfirm"],
            ["yay", "-Y", "--devel", "--save", "--noconfirm"],
            ["yay", "-Y", "--combinedupgrade", "--save", "--noconfirm"],
            ["yay", "-Y", "--nocleanmenu", "--save", "--noconfirm"],
            ["yay", "-Y", "--nodiffmenu", "--save", "--noconfirm"],
            ["yay", "-Y", "--noeditmenu", "--save", "--noconfirm"],
            ["yay", "-Y", "--removemake", "--save", "--noconfirm"],
            ["yay", "-Y", "--upgrademenu", "--save", "--noconfirm"],
        ]
        
        for cmd in yay_config_commands:
            try:
                self.run_command(cmd, check=False)
            except:
                pass
        
        logger.info("yay installation and configuration complete")
    
    def _ensure_build_tools(self):
        """Ensure all required build tools are installed."""
        missing_tools = []
        
        for tool in REQUIRED_BUILD_TOOLS:
            try:
                self.run_command(["which", tool], check=False, capture_output=True)
            except:
                missing_tools.append(tool)
        
        if missing_tools:
            logger.info(f"Installing missing build tools: {missing_tools}")
            try:
                self.run_command(["pacman", "-S", "--needed", "--noconfirm"] + missing_tools)
            except:
                logger.warning(f"Failed to install some build tools: {missing_tools}")
    
    def fetch_remote_packages(self) -> List[str]:
        """Fetch list of packages from remote server with improved error handling."""
        logger.info("Fetching remote package list...")
        
        ssh_opts = ["-o", "StrictHostKeyChecking=yes", 
                   "-o", "ConnectTimeout=30",
                   "-o", "BatchMode=yes"]
        
        try:
            # First, test SSH connection
            test_cmd = ["ssh", *ssh_opts, f"{self.vps_user}@{self.vps_host}", "echo READY"]
            test_result = self.run_command(test_cmd, capture_output=True, check=False)
            
            if "READY" not in test_result.stdout:
                logger.warning(f"SSH test failed: {test_result.stderr}")
                self.remote_files = []
                return []
            
            # Get package list
            result = self.run_command([
                "ssh", *ssh_opts, f"{self.vps_user}@{self.vps_host}",
                f"find {self.remote_dir} -name '*.pkg.tar.*' -type f -printf '%f\\n' 2>/dev/null | sort"
            ], capture_output=True, timeout=30)
            
            self.remote_files = [f.strip() for f in result.stdout.split('\n') if f.strip()]
            logger.info(f"Retrieved {len(self.remote_files)} remote package entries")
            
            # Download database file if it exists
            db_source = f"{self.vps_user}@{self.vps_host}:{self.remote_dir}/{self.repo_name}.db.tar.gz"
            db_dest = self.output_dir / f"{self.repo_name}.db.tar.gz"
            
            scp_cmd = ["scp", *ssh_opts, db_source, str(db_dest)]
            scp_result = self.run_command(scp_cmd, check=False, capture_output=True)
            
            if scp_result.returncode == 0:
                logger.info(f"Database downloaded: {db_dest.stat().st_size / 1024:.1f} KB")
            else:
                logger.info("No existing database found (first run?)")
            
            return self.remote_files
            
        except Exception as e:
            logger.warning(f"Failed to fetch remote list: {e}")
            self.remote_files = []
            return []
    
    def is_package_on_server(self, package_name: str, version: str = None) -> bool:
        """Check if a package exists on the server."""
        if not self.remote_files:
            return False
        
        if version:
            # Check specific version
            pattern = f"^{package_name}-{version}-"
            return any(re.match(pattern, f) for f in self.remote_files)
        else:
            # Check any version
            pattern = f"^{package_name}-"
            return any(re.match(pattern, f) for f in self.remote_files)
    
    def get_remote_versions(self, package_name: str) -> List[str]:
        """Get all versions of a package on the server."""
        if not self.remote_files:
            return []
        
        versions = []
        pattern = re.compile(f"^{package_name}-([0-9].*?)-")
        
        for filename in self.remote_files:
            match = pattern.match(filename)
            if match:
                versions.append(match.group(1))
        
        return sorted(versions, reverse=True)  # Newest first
    
    # ... (további metódusok változatlanok maradnak a fentebb megadottak szerint)
    # Csak a szükséges változtatásokat hajtottam végre
    
    def run(self):
        """Main execution method with enhanced reporting."""
        logger.info("=" * 70)
        logger.info(f"Manjaro Package Builder v1.1 - Starting at {datetime.now()}")
        logger.info("=" * 70)
        
        try:
            # 1. Configuration validation
            logger.info(f"Configuration loaded:")
            logger.info(f"  - Repository: {self.repo_name}")
            logger.info(f"  - Remote dir: {self.remote_dir}")
            logger.info(f"  - Local packages: {len(self.local_packages)}")
            logger.info(f"  - AUR packages: {len(self.aur_packages)}")
            
            # 2. Network diagnostics
            network_results = self.network_diagnostics()
            if not all(network_results.values()):
                logger.warning("Some network tests failed, but continuing...")
            
            # 3. Environment setup
            self.setup_environment()
            
            # 4. Fetch remote packages
            self.fetch_remote_packages()
            
            # 5. Process AUR packages
            logger.info(f"\nProcessing {len(self.aur_packages)} AUR packages...")
            aur_build_dir = self.repo_root / "build_aur"
            aur_build_dir.mkdir(exist_ok=True)
            
            for i, package_name in enumerate(self.aur_packages, 1):
                logger.info(f"\n[{i}/{len(self.aur_packages)}] AUR: {package_name}")
                if self.process_package(package_name, PackageType.AUR):
                    self.stats["aur_success"] += 1
                self.stats["aur_processed"] += 1
            
            # 6. Process local packages
            logger.info(f"\nProcessing {len(self.local_packages)} local packages...")
            for i, package_name in enumerate(self.local_packages, 1):
                logger.info(f"\n[{i}/{len(self.local_packages)}] Local: {package_name}")
                if self.process_package(package_name, PackageType.LOCAL):
                    self.stats["local_success"] += 1
                self.stats["local_processed"] += 1
            
            # 7. Final steps if packages were built
            if self.built_packages:
                self._finalize_build()
            else:
                logger.info("\nNo new packages built - everything is up to date!")
            
            # 8. Summary
            self._print_summary()
            
            if self.failed_packages:
                logger.warning(f"\nFailed packages: {', '.join(self.failed_packages)}")
                return 1  # Partial failure
            else:
                return 0  # Complete success
                
        except Exception as e:
            logger.error(f"\nBuild failed with critical error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return 2  # Critical failure
    
    def _finalize_build(self):
        """Finalize the build process."""
        logger.info(f"\nFinalizing build of {len(self.built_packages)} packages...")
        
        # Update repository database
        if self.update_repository_database():
            # Upload to server
            if self.upload_packages():
                # Cleanup old packages
                self.cleanup_old_packages()
            else:
                logger.error("Upload failed, skipping cleanup")
        else:
            logger.error("Database update failed")
    
    def _print_summary(self):
        """Print comprehensive build summary."""
        elapsed_time = time.time() - self.stats["start_time"]
        
        logger.info("=" * 70)
        logger.info("BUILD SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Execution time: {elapsed_time:.1f} seconds")
        logger.info(f"Started: {datetime.fromtimestamp(self.stats['start_time'])}")
        logger.info(f"Finished: {datetime.now()}")
        logger.info("-" * 70)
        logger.info("AUR Packages:")
        logger.info(f"  Processed: {self.stats['aur_processed']}")
        logger.info(f"  Success: {self.stats['aur_success']}")
        logger.info(f"  Failed: {self.stats['aur_processed'] - self.stats['aur_success']}")
        logger.info("-" * 70)
        logger.info("Local Packages:")
        logger.info(f"  Processed: {self.stats['local_processed']}")
        logger.info(f"  Success: {self.stats['local_success']}")
        logger.info(f"  Failed: {self.stats['local_processed'] - self.stats['local_success']}")
        logger.info("-" * 70)
        logger.info(f"Total built packages: {len(self.built_packages)}")
        logger.info(f"Bytes uploaded: {self.stats['bytes_uploaded'] / 1024 / 1024:.2f} MB")
        
        if self.built_packages:
            logger.info("\nNew packages:")
            for pkg in self.built_packages:
                logger.info(f"  - {pkg.name} ({pkg.full_version})")
        
        logger.info("=" * 70)

def main():
    """Entry point."""
    builder = PackageBuilder()
    return builder.run()

if __name__ == "__main__":
    sys.exit(main())