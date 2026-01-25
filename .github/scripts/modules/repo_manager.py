"""
Repository Management Module - Holy Grail Decision Engine
"""

import os
import subprocess
import json
import re
import logging
from pathlib import Path
from typing import List, Set, Tuple, Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class RepoManager:
    """Manages repository database operations with Holy Grail Decision Engine"""
    
    def __init__(self, config: dict):
        """
        Initialize RepoManager with configuration
        
        Args:
            config: Dictionary containing:
                - repo_name: Repository name
                - output_dir: Local output directory
                - remote_dir: Remote directory on VPS
                - vps_user: VPS username
                - vps_host: VPS hostname
        """
        self.repo_name = config['repo_name']
        self.output_dir = Path(config['output_dir'])
        self.remote_dir = config['remote_dir']
        self.vps_user = config['vps_user']
        self.vps_host = config['vps_host']
        
        # State tracking directories
        self.build_tracking_dir = self.output_dir.parent / ".build_tracking"
        self.build_tracking_dir.mkdir(exist_ok=True, parents=True)
        self.state_file = self.build_tracking_dir / "vps_state.json"
        
        # State tracking
        self.state_data: Dict[str, Dict[str, str]] = {}
        
        # Load existing state (but state-first means we load in builder.py)
    
    def load_state(self) -> bool:
        """Load JSON state from file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    self.state_data = json.load(f)
                logger.info(f"📊 Loaded state for {len(self.state_data)} packages")
                return True
            except json.JSONDecodeError:
                logger.warning("State file corrupted")
                return False
            except Exception as e:
                logger.warning(f"Could not load state file: {e}")
                return False
        else:
            logger.info("ℹ️ No state file found locally")
            return False
    
    def save_state(self) -> bool:
        """Save JSON state to file with human-readable indentation"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state_data, f, indent=4, sort_keys=True)
            logger.debug("✅ Saved state file with indent=4")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to save state file: {e}")
            return False
    
    def initialize_state_from_vps(self, vps_client) -> bool:
        """
        Initialize state from VPS package list (when no state exists)
        
        Returns:
            True if successful
        """
        logger.info("🔄 Initializing state from VPS package list...")
        
        # Get packages from VPS
        packages = vps_client.get_remote_package_list_for_state()
        if not packages:
            logger.info("ℹ️ No packages on VPS, creating empty state")
            self.state_data = {}
        else:
            self.state_data = packages
        
        return self.save_state()
    
    def decision_engine(self, pkg_name: str, pkg_type: str, local_version: str, 
                       aur_version: Optional[str] = None, vps_client = None) -> Dict[str, Any]:
        """
        Holy Grail Decision Engine
        
        Args:
            pkg_name: Package name
            pkg_type: "local" or "aur"
            local_version: Version from local PKGBUILD (for local) or AUR RPC (for AUR)
            aur_version: AUR version (only for AUR packages)
            vps_client: VPSClient for integrity checks
        
        Returns:
            Dictionary with decision and metadata
        """
        decision = {
            "build": False,
            "skip": False,
            "warning": None,
            "reason": "",
            "remote_version": None,
            "file_exists": False
        }
        
        # Check if package is in state
        if pkg_name in self.state_data:
            state_info = self.state_data[pkg_name]
            state_version = state_info.get("version", "")
            
            # Integrity check: Does file exist on VPS?
            if vps_client:
                filename = state_info.get("filename", "")
                if filename:
                    remote_path = f"{self.remote_dir}/{filename}"
                    decision["file_exists"] = vps_client.check_remote_file_exists(remote_path)
                    if not decision["file_exists"]:
                        decision["build"] = True
                        decision["reason"] = "File missing from VPS (integrity check failed)"
                        return decision
            
            # For AUR packages, compare with AUR version
            if pkg_type == "aur" and aur_version:
                if state_version == aur_version:
                    # Same version - SKIP (No-Clone Zone)
                    decision["skip"] = True
                    decision["reason"] = f"AUR version {aur_version} matches state"
                    logger.debug(f"✅ {pkg_name}: AUR {aur_version} == State {state_version} - SKIP")
                else:
                    # Need to compare which version is newer
                    try:
                        # Use vercmp if available
                        result = subprocess.run(
                            ['vercmp', aur_version, state_version],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if result.returncode == 0:
                            cmp_result = int(result.stdout.strip())
                            if cmp_result > 0:
                                # AUR version > State version - BUILD
                                decision["build"] = True
                                decision["reason"] = f"AUR {aur_version} > State {state_version}"
                                logger.info(f"ℹ️ {pkg_name}: AUR {aur_version} > State {state_version} - BUILD")
                            elif cmp_result < 0:
                                # AUR version < State version - WARNING (downgrade)
                                decision["skip"] = True
                                decision["warning"] = f"Would downgrade from {state_version} to {aur_version}"
                                decision["reason"] = "Downgrade protection"
                                logger.warning(f"⚠️ {pkg_name}: AUR {aur_version} < State {state_version} - SKIP (downgrade)")
                            else:
                                # Equal - SKIP
                                decision["skip"] = True
                                decision["reason"] = "Versions equal"
                        else:
                            # Fallback: Build if different
                            decision["build"] = True
                            decision["reason"] = f"Version comparison failed, building to be safe"
                    except Exception:
                        # Build if different (conservative)
                        decision["build"] = True
                        decision["reason"] = f"AUR {aur_version} != State {state_version}"
            
            # For local packages, compare with local version
            elif pkg_type == "local":
                if state_version == local_version:
                    # Same version - SKIP
                    decision["skip"] = True
                    decision["reason"] = f"Local version {local_version} matches state"
                    logger.debug(f"✅ {pkg_name}: Local {local_version} == State {state_version} - SKIP")
                else:
                    # Compare versions
                    try:
                        result = subprocess.run(
                            ['vercmp', local_version, state_version],
                            capture_output=True,
                            text=True,
                            check=False
                        )
                        
                        if result.returncode == 0:
                            cmp_result = int(result.stdout.strip())
                            if cmp_result > 0:
                                # Local version > State version - BUILD
                                decision["build"] = True
                                decision["reason"] = f"Local {local_version} > State {state_version}"
                                logger.info(f"ℹ️ {pkg_name}: Local {local_version} > State {state_version} - BUILD")
                            elif cmp_result < 0:
                                # Local version < State version - WARNING (downgrade)
                                decision["skip"] = True
                                decision["warning"] = f"Would downgrade from {state_version} to {local_version}"
                                decision["reason"] = "Downgrade protection"
                                logger.warning(f"⚠️ {pkg_name}: Local {local_version} < State {state_version} - SKIP (downgrade)")
                            else:
                                decision["skip"] = True
                                decision["reason"] = "Versions equal"
                        else:
                            decision["build"] = True
                            decision["reason"] = f"Local {local_version} != State {state_version}"
                    except Exception:
                        decision["build"] = True
                        decision["reason"] = f"Local {local_version} != State {state_version}"
            
            decision["remote_version"] = state_version
            
        else:
            # Not in state - BUILD
            decision["build"] = True
            decision["reason"] = "Not in state file"
            logger.info(f"ℹ️ {pkg_name}: Not in state - BUILD")
        
        return decision
    
    def update_package_state(self, pkg_name: str, version: str, filename: str, vps_client) -> bool:
        """
        Update state for a newly built package
        
        Args:
            pkg_name: Package name
            version: Package version
            filename: Package filename
            vps_client: VPSClient instance for hash calculation
            
        Returns:
            True if successful
        """
        remote_hash = vps_client.get_remote_file_hash(f"{self.remote_dir}/{filename}")
        if remote_hash:
            self.state_data[pkg_name] = {
                "version": version,
                "hash": remote_hash,
                "filename": filename,
                "last_verified": datetime.now().isoformat(),
                "built_at": datetime.now().isoformat()
            }
            logger.info(f"📝 Updated state for {pkg_name} ({version})")
            return self.save_state()
        else:
            logger.warning(f"⚠️ Could not get hash for {pkg_name}, state not updated")
            return False
    
    def atomic_dependency_injection(self, build_engine) -> bool:
        """
        Atomic Dependency Injection: Update local repo database and sync pacman
        
        Returns:
            True if successful
        """
        logger.info("⚛️ Atomic Dependency Injection: Updating local repo...")
        
        # Check if we have any packages
        local_packages = list(self.output_dir.glob("*.pkg.tar.*"))
        if not local_packages:
            logger.info("ℹ️ No packages to inject")
            return True
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            # Generate or update local database
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            # Create database
            cmd = f"repo-add {db_file} *.pkg.tar.* 2>/dev/null || true"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                logger.info("✅ Local repository database updated")
                
                # Sync pacman databases
                logger.info("🔄 Running pacman -Sy for dependency injection...")
                sync_result = subprocess.run(
                    ["sudo", "pacman", "-Sy", "--noconfirm"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False
                )
                
                if sync_result.returncode == 0:
                    logger.info("✅ Pacman databases synchronized")
                    return True
                else:
                    logger.warning(f"⚠️ Pacman sync warning: {sync_result.stderr[:200]}")
                    return False
            else:
                logger.error(f"❌ Failed to update local database: {result.stderr[:200]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def generate_full_database(self) -> bool:
        """Generate final repository database"""
        logger.info("\n" + "=" * 60)
        logger.info("📦 FINAL Repository Database Generation")
        logger.info("=" * 60)
        
        all_packages = list(self.output_dir.glob("*.pkg.tar.*"))
        if not all_packages:
            logger.info("ℹ️ No packages available for database generation")
            return False
        
        old_cwd = os.getcwd()
        os.chdir(self.output_dir)
        
        try:
            db_file = f"{self.repo_name}.db.tar.gz"
            
            # Clean old database files
            for f in [f"{self.repo_name}.db", f"{self.repo_name}.db.tar.gz", 
                      f"{self.repo_name}.files", f"{self.repo_name}.files.tar.gz"]:
                if os.path.exists(f):
                    os.remove(f)
            
            cmd = rf"repo-add {db_file} *.pkg.tar.zst *.pkg.tar.xz"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                logger.info(f"✅ Database created with {len(all_packages)} packages")
                return True
            else:
                logger.error(f"❌ repo-add failed: {result.stderr[:500]}")
                return False
                
        finally:
            os.chdir(old_cwd)
    
    def check_integrity(self, vps_client) -> List[str]:
        """
        Check integrity of packages in state vs actual files on VPS
        
        Returns:
            List of packages with missing files
        """
        missing = []
        
        for pkg_name, info in self.state_data.items():
            filename = info.get("filename")
            if filename:
                remote_path = f"{self.remote_dir}/{filename}"
                if not vps_client.check_remote_file_exists(remote_path):
                    missing.append(pkg_name)
        
        if missing:
            logger.warning(f"⚠️ Integrity check: {len(missing)} packages missing from VPS")
        
        return missing