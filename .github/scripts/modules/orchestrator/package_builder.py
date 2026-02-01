"""
Package Builder Module - Main orchestrator for package building coordination
WITH CACHE-AWARE BUILDING
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import time
import glob
import json
import urllib.request
from pathlib import Path
from typing import List, Optional, Tuple

# Add parent directory to path for imports
script_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

try:
    from modules.common.logging_utils import setup_logger
    logger = setup_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)

from modules.common.config_loader import ConfigLoader
from modules.common.environment import EnvironmentValidator
from modules.common.shell_executor import ShellExecutor
from modules.build.artifact_manager import ArtifactManager
from modules.build.aur_builder import AURBuilder
from modules.build.local_builder import LocalBuilder
from modules.build.version_manager import VersionManager
from modules.build.build_tracker import BuildTracker
from modules.gpg.gpg_handler import GPGHandler
from modules.vps.ssh_client import SSHClient
from modules.vps.rsync_client import RsyncClient
from modules.repo.cleanup_manager import CleanupManager
from modules.repo.database_manager import DatabaseManager
from modules.repo.version_tracker import VersionTracker
from modules.repo.manifest_factory import ManifestFactory


class PackageBuilder:
    """Main orchestrator that coordinates between modules for package building WITH CACHE SUPPORT"""

    def __init__(self):
        EnvironmentValidator.validate_env()

        self.config_loader = ConfigLoader()
        self.repo_root = self.config_loader.get_repo_root()
        env_config = self.config_loader.load_environment_config()
        python_config = self.config_loader.load_from_python_config()

        self.vps_user = env_config['vps_user']
        self.vps_host = env_config['vps_host']
        self.ssh_key = env_config['ssh_key']
        self.repo_server_url = env_config['repo_server_url']
        self.remote_dir = env_config['remote_dir']
        self.repo_name = env_config['repo_name']

        self.output_dir = self.repo_root / python_config['output_dir']
        self.build_tracking_dir = self.repo_root / python_config['build_tracking_dir']
        self.mirror_temp_dir = Path(python_config['mirror_temp_dir'])
        self.sync_clone_dir = Path(python_config['sync_clone_dir'])
        self.aur_urls = python_config['aur_urls']
        self.aur_build_dir = self.repo_root / python_config['aur_build_dir']
        self.ssh_options = python_config['ssh_options']
        self.github_repo = python_config['github_repo']
        self.packager_id = python_config['packager_id']
        self.debug_mode = python_config['debug_mode']
        self.sign_packages = python_config['sign_packages']

        self.use_cache = os.getenv('USE_CACHE', 'false').lower() == 'true'

        self.output_dir.mkdir(exist_ok=True)
        self.build_tracking_dir.mkdir(exist_ok=True)

        self._init_modules()

        self.remote_files = []
        self.built_packages = []
        self.skipped_packages = []
        self.rebuilt_local_packages = []

        self.stats = {
            "start_time": time.time(),
            "aur_success": 0,
            "local_success": 0,
            "aur_failed": 0,
            "local_failed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
        }

    def _init_modules(self):
        try:
            vps_config = {
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
                'remote_dir': self.remote_dir,
                'ssh_options': self.ssh_options,
                'repo_name': self.repo_name,
            }
            self.ssh_client = SSHClient(vps_config)
            self.ssh_client.setup_ssh_config(self.ssh_key)

            self.rsync_client = RsyncClient(vps_config)

            repo_config = {
                'repo_name': self.repo_name,
                'output_dir': self.output_dir,
                'remote_dir': self.remote_dir,
                'mirror_temp_dir': self.mirror_temp_dir,
                'vps_user': self.vps_user,
                'vps_host': self.vps_host,
            }
            self.cleanup_manager = CleanupManager(repo_config)
            self.database_manager = DatabaseManager(repo_config)
            self.version_tracker = VersionTracker(repo_config)

            self.artifact_manager = ArtifactManager()
            self.aur_builder = AURBuilder(self.debug_mode)
            self.local_builder = LocalBuilder(self.debug_mode)
            self.version_manager = VersionManager()
            self.build_tracker = BuildTracker()

            self.gpg_handler = GPGHandler(self.sign_packages)

            # Provide GPG handler to cleanup manager (optional verification only)
            self.cleanup_manager.set_gpg_handler(self.gpg_handler)

            self.shell_executor = ShellExecutor(self.debug_mode)

            logger.info("✅ All modules initialized successfully")
            logger.info(f"📝 Package signing: {'ENABLED' if self.sign_packages else 'DISABLED'}")

            if self.use_cache:
                logger.info("🔧 CACHE: Cache-aware building ENABLED")
                built_count = len(list(self.output_dir.glob("*.pkg.tar.*")))
                logger.info(f"🔧 CACHE: Cached package files: {built_count}")
            else:
                logger.info("🔧 CACHE: Cache-aware building DISABLED")

        except NameError as e:
            logger.error(f"❌ NameError during module initialization: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"❌ Error initializing modules: {e}")
            sys.exit(1)

    def get_package_lists(self):
        try:
            import packages
            print("📦 Using package lists from packages.py")
            local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
            print(f">>> DEBUG: Found {len(local_packages_list + aur_packages_list)} packages to check")
            return local_packages_list, aur_packages_list
        except ImportError:
            try:
                import sys
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                import scripts.packages as packages
                print("📦 Using package lists from packages.py")
                local_packages_list, aur_packages_list = packages.LOCAL_PACKAGES, packages.AUR_PACKAGES
                print(f">>> DEBUG: Found {len(local_packages_list + aur_packages_list)} packages to check")
                return local_packages_list, aur_packages_list
            except ImportError:
                logger.error("Cannot load package lists from packages.py. Exiting.")
                sys.exit(1)

    def _check_cache_for_package(self, pkg_name: str, is_aur: bool) -> Tuple[bool, Optional[str]]:
        if not self.use_cache:
            return False, None

        cache_patterns = [
            f"{self.output_dir}/{pkg_name}-*.pkg.tar.*",
            f"{self.output_dir}/*{pkg_name}*.pkg.tar.*"
        ]

        cached_files = []
        for pattern in cache_patterns:
            cached_files.extend(glob.glob(pattern))

        if cached_files:
            for cached_file in cached_files:
                try:
                    filename = os.path.basename(cached_file)
                    base = filename.replace('.pkg.tar.zst', '').replace('.pkg.tar.xz', '')
                    parts = base.split('-')

                    for i in range(len(parts) - 2, 0, -1):
                        possible_name = '-'.join(parts[:i])
                        if possible_name == pkg_name or possible_name.startswith(pkg_name + '-'):
                            if len(parts) >= i + 3:
                                version_part = parts[i]
                                release_part = parts[i + 1]
                                if i + 1 < len(parts) and parts[i].isdigit() and i + 2 < len(parts):
                                    epoch_part = parts[i]
                                    version_part = parts[i + 1]
                                    release_part = parts[i + 2]
                                    cached_version = f"{epoch_part}:{version_part}-{release_part}"

                                    epoch = epoch_part
                                    pkgver = version_part
                                    pkgrel = release_part
                                else:
                                    cached_version = f"{version_part}-{release_part}"

                                    epoch = None
                                    pkgver = version_part
                                    pkgrel = release_part

                                remote_version = self.get_remote_version(pkg_name)
                                if remote_version:
                                    should_build = self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch)
                                    if not should_build:
                                        logger.info(f"📦 CACHE HIT: {pkg_name} (SKIP BUILD)")
                                        self.stats["cache_hits"] += 1
                                        return True, cached_version
                                    else:
                                        logger.info(f"📦 CACHE STALE: {pkg_name} (NEEDS REBUILD)")
                                        self.stats["cache_misses"] += 1
                                        return False, None
                                else:
                                    logger.info(f"📦 CACHE HIT: {pkg_name} (no remote) - SKIP BUILD")
                                    self.stats["cache_hits"] += 1
                                    return True, cached_version
                except Exception as e:
                    logger.debug(f"Could not parse cached version for {pkg_name}: {e}")

        self.stats["cache_misses"] += 1
        return False, None

    def _apply_repository_state(self, exists: bool, has_packages: bool):
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

            in_section = False
            for line in lines:
                if line.strip() == repo_section or line.strip() == f"#{repo_section}":
                    in_section = True
                    continue
                elif in_section and (line.strip().startswith('[') or line.strip() == ''):
                    in_section = False

                if not in_section:
                    new_lines.append(line)

            if exists:
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                new_lines.append(f"# Automatically enabled - found on VPS")
                new_lines.append(repo_section)
                if has_packages:
                    new_lines.append("SigLevel = Optional TrustAll")
                    logger.info("✅ Enabling repository with SigLevel = Optional TrustAll (build mode)")
                else:
                    new_lines.append("# SigLevel = Optional TrustAll")
                    new_lines.append("# Repository exists but has no packages yet")
                    logger.info("⚠️ Repository section added but commented (no packages yet)")

                if self.repo_server_url:
                    new_lines.append(f"Server = {self.repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
            else:
                new_lines.append('')
                new_lines.append(f"# Custom repository: {self.repo_name}")
                new_lines.append(f"# Disabled - not found on VPS (first run?)")
                new_lines.append(f"#{repo_section}")
                new_lines.append("#SigLevel = Optional TrustAll")
                if self.repo_server_url:
                    new_lines.append(f"#Server = {self.repo_server_url}")
                else:
                    new_lines.append("# Server = [URL not configured in secrets]")
                new_lines.append('')
                logger.info("ℹ️ Repository not found on VPS - keeping disabled")

            with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp_file:
                temp_file.write('\n'.join(new_lines))
                temp_path = temp_file.name

            subprocess.run(['sudo', 'cp', temp_path, str(pacman_conf)], check=False)
            subprocess.run(['sudo', 'chmod', '644', str(pacman_conf)], check=False)
            os.unlink(temp_path)

            logger.info(f"✅ Updated pacman.conf for repository '{self.repo_name}'")

            if exists and has_packages:
                logger.info("🔄 Synchronizing pacman databases after enabling repository...")

                cmd = "sudo pacman-key --updatedb"
                result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
                if result.returncode != 0:
                    logger.warning("⚠️ pacman-key --updatedb warning")

                cmd = "sudo LC_ALL=C pacman -Syy --noconfirm"
                result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
                if result.returncode == 0:
                    logger.info("✅ Pacman databases synchronized successfully")
                else:
                    logger.warning("⚠️ Pacman sync warning")

        except Exception as e:
            logger.error(f"Failed to apply repository state: {e}")

    def _sync_pacman_databases(self):
        print("\n" + "=" * 60)
        print("FINAL STEP: Syncing pacman databases")
        print("=" * 60)

        exists, has_packages = self.ssh_client.check_repository_exists_on_vps()
        self._apply_repository_state(exists, has_packages)

        if not exists:
            logger.info("ℹ️ Repository doesn't exist on VPS, skipping pacman sync")
            return False

        cmd = "sudo pacman-key --updatedb"
        result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)
        if result.returncode != 0:
            logger.warning("⚠️ pacman-key --updatedb warning")

        cmd = "sudo LC_ALL=C pacman -Syy --noconfirm"
        result = self.shell_executor.run_command(cmd, log_cmd=True, timeout=300, check=False)

        if result.returncode == 0:
            logger.info("✅ Pacman databases synced successfully")
            debug_cmd = f"sudo pacman -Sl {self.repo_name}"
            debug_result = self.shell_executor.run_command(debug_cmd, log_cmd=True, timeout=30, check=False)
            if debug_result.returncode == 0:
                if debug_result.stdout.strip():
                    logger.info(f"Packages in {self.repo_name} according to pacman:")
                    for line in debug_result.stdout.splitlines():
                        logger.info(f"  {line}")
                else:
                    logger.warning("⚠️ pacman -Sl returned no output (repo might be empty)")
            else:
                logger.warning("⚠️ pacman -Sl failed")
            return True

        logger.error("❌ Pacman sync failed")
        return False

    def _fetch_aur_version(self, pkg_name: str) -> Optional[Tuple[str, str, Optional[str]]]:
        try:
            url = f"https://aur.archlinux.org/rpc/?v=5&type=info&arg[]={pkg_name}"
            logger.info(f"📡 Fetching AUR version for {pkg_name}")

            with urllib.request.urlopen(url, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))

                if data.get('resultcount', 0) > 0:
                    result = data['results'][0]
                    version = result.get('Version', '')

                    if version:
                        logger.info(f"📦 AUR version for {pkg_name}: {version}")

                        if ':' in version:
                            epoch_part, rest = version.split(':', 1)
                            epoch = epoch_part.strip()
                        else:
                            epoch = None
                            rest = version

                        if '-' in rest:
                            pkgver, pkgrel = rest.rsplit('-', 1)
                            pkgver = pkgver.strip()
                            pkgrel = pkgrel.strip()
                        else:
                            pkgver = rest.strip()
                            pkgrel = '1'

                        return pkgver, pkgrel, epoch
                    else:
                        logger.warning(f"⚠️ No version found for {pkg_name} in AUR response")
                else:
                    logger.warning(f"⚠️ Package {pkg_name} not found in AUR")

        except urllib.error.URLError as e:
            logger.error(f"❌ Network error fetching AUR version for {pkg_name}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON decode error for {pkg_name}: {e}")
        except Exception as e:
            logger.error(f"❌ Error fetching AUR version for {pkg_name}: {e}")

        return None

    def _get_local_version(self, pkg_dir: Path) -> Optional[Tuple[str, str, Optional[str]]]:
        try:
            return self.version_manager.extract_version_from_srcinfo(pkg_dir)
        except Exception as e:
            logger.error(f"❌ Failed to extract version for {pkg_dir.name}")

            pkgbuild_path = pkg_dir / "PKGBUILD"
            if pkgbuild_path.exists():
                try:
                    with open(pkgbuild_path, 'r') as f:
                        content = f.read()

                    pkgver_match = re.search(r'pkgver=([^\s\']+)', content)
                    pkgrel_match = re.search(r'pkgrel=([^\s\']+)', content)
                    epoch_match = re.search(r'epoch=([^\s\']+)', content)

                    if pkgver_match and pkgrel_match:
                        pkgver = pkgver_match.group(1).strip('"\'')
                        pkgrel = pkgrel_match.group(1).strip('"\'')
                        epoch = epoch_match.group(1).strip('"\'') if epoch_match else None
                        return pkgver, pkgrel, epoch

                except Exception:
                    logger.error("❌ Failed to parse PKGBUILD")
            return None

    def package_exists(self, pkg_name: str, version=None) -> bool:
        return self.version_tracker.package_exists(pkg_name, self.remote_files)

    def get_remote_version(self, pkg_name: str) -> Optional[str]:
        return self.version_tracker.get_remote_version(pkg_name, self.remote_files)

    def _build_aur_package(self, pkg_name: str) -> bool:
        aur_version_info = self._fetch_aur_version(pkg_name)
        if not aur_version_info:
            logger.error(f"❌ Failed to fetch AUR version for {pkg_name}")
            return False

        pkgver, pkgrel, epoch = aur_version_info
        aur_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)

        remote_version = self.get_remote_version(pkg_name)

        if remote_version:
            should_build = self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch)
            if not should_build:
                logger.info(f"✅ {pkg_name}: Up-to-date - SKIPPING")
                self.skipped_packages.append(f"{pkg_name} ({aur_version})")
                self.version_tracker.register_skipped_package(pkg_name, remote_version)
                return False
            else:
                logger.info(f"🔄 {pkg_name}: NEWER - BUILDING")
        else:
            logger.info(f"🔄 {pkg_name}: No remote version, building")

        aur_dir = self.aur_build_dir
        aur_dir.mkdir(exist_ok=True)

        pkg_dir = aur_dir / pkg_name
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir, ignore_errors=True)

        logger.info(f"📥 Cloning {pkg_name} from AUR...")

        clone_success = False
        for aur_url_template in self.aur_urls:
            aur_url = aur_url_template.format(pkg_name=pkg_name)
            result = self.shell_executor.run_command(
                f"git clone --depth 1 {aur_url} {pkg_dir}",
                check=False
            )
            if result and result.returncode == 0:
                clone_success = True
                break
            else:
                if pkg_dir.exists():
                    shutil.rmtree(pkg_dir, ignore_errors=True)

        if not clone_success:
            logger.error(f"❌ Failed to clone {pkg_name}")
            return False

        self.shell_executor.run_command(f"chown -R builder:builder {pkg_dir}", check=False)

        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"❌ No PKGBUILD found for {pkg_name}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False

        try:
            logger.info(f"🔨 Building {pkg_name}...")

            self.artifact_manager.clean_workspace(pkg_dir)

            source_result = self.shell_executor.run_command(
                f"makepkg -od --noconfirm",
                cwd=pkg_dir,
                check=False,
                capture=True,
                timeout=600,
                extra_env={"PACKAGER": self.packager_id}
            )

            if source_result.returncode != 0:
                logger.error(f"❌ Failed to download sources for {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False

            build_result = self.shell_executor.run_command(
                f"makepkg -si --noconfirm --clean --nocheck",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600,
                extra_env={"PACKAGER": self.packager_id}
            )

            if build_result.returncode != 0:
                logger.error(f"❌ Failed to build {pkg_name}")
                shutil.rmtree(pkg_dir, ignore_errors=True)
                return False

            moved = False
            for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                dest = self.output_dir / pkg_file.name
                shutil.move(str(pkg_file), str(dest))
                logger.info(f"✅ Built: {pkg_file.name}")
                moved = True

                # SECURITY: do not print paths
                if not self.gpg_handler.sign_package(str(dest)):
                    logger.error("❌ Failed to sign package (continuing)")

            shutil.rmtree(pkg_dir, ignore_errors=True)

            if moved:
                self.built_packages.append(f"{pkg_name} ({aur_version})")
                self.version_tracker.register_package_target_version(pkg_name, aur_version)
                return True

            logger.error(f"❌ No package files created for {pkg_name}")
            return False

        except Exception as e:
            logger.error(f"❌ Error building {pkg_name}: {e}")
            shutil.rmtree(pkg_dir, ignore_errors=True)
            return False

    def _build_local_package(self, pkg_name: str) -> bool:
        pkg_dir = self.repo_root / pkg_name
        if not pkg_dir.exists():
            logger.error(f"❌ Package directory not found: {pkg_name}")
            return False

        pkgbuild = pkg_dir / "PKGBUILD"
        if not pkgbuild.exists():
            logger.error(f"❌ No PKGBUILD found for {pkg_name}")
            return False

        local_version_info = self._get_local_version(pkg_dir)
        if not local_version_info:
            logger.error(f"❌ Failed to extract version for {pkg_name}")
            return False

        pkgver, pkgrel, epoch = local_version_info
        local_version = self.version_manager.get_full_version_string(pkgver, pkgrel, epoch)

        remote_version = self.get_remote_version(pkg_name)

        if remote_version:
            should_build = self.version_manager.compare_versions(remote_version, pkgver, pkgrel, epoch)
            if not should_build:
                logger.info(f"✅ {pkg_name}: Up-to-date - SKIPPING")
                self.skipped_packages.append(f"{pkg_name} ({local_version})")
                self.version_tracker.register_skipped_package(pkg_name, remote_version)
                return False
            else:
                logger.info(f"🔄 {pkg_name}: NEWER - BUILDING")
        else:
            logger.info(f"🔄 {pkg_name}: No remote version, building")

        try:
            logger.info(f"🔨 Building {pkg_name}...")

            self.artifact_manager.clean_workspace(pkg_dir)

            source_result = self.shell_executor.run_command(
                f"makepkg -od --noconfirm",
                cwd=pkg_dir,
                check=False,
                capture=True,
                timeout=600,
                extra_env={"PACKAGER": self.packager_id}
            )

            if source_result.returncode != 0:
                logger.error(f"❌ Failed to download sources for {pkg_name}")
                return False

            makepkg_flags = "-si --noconfirm --clean"
            if pkg_name == "gtk2":
                makepkg_flags += " --nocheck"
                logger.info("   GTK2: Skipping check step (long)")

            build_result = self.shell_executor.run_command(
                f"makepkg {makepkg_flags}",
                cwd=pkg_dir,
                capture=True,
                check=False,
                timeout=3600,
                extra_env={"PACKAGER": self.packager_id}
            )

            if build_result.returncode != 0:
                logger.error(f"❌ Failed to build {pkg_name}")
                return False

            moved = False
            for pkg_file in pkg_dir.glob("*.pkg.tar.*"):
                dest = self.output_dir / pkg_file.name
                shutil.move(str(pkg_file), str(dest))
                logger.info(f"✅ Built: {pkg_file.name}")
                moved = True

                if not self.gpg_handler.sign_package(str(dest)):
                    logger.error("❌ Failed to sign package (continuing)")

            if moved:
                self.built_packages.append(f"{pkg_name} ({local_version})")
                self.rebuilt_local_packages.append(pkg_name)
                self.version_tracker.register_package_target_version(pkg_name, local_version)

                self.build_tracker.add_hokibot_data(pkg_name, pkgver, pkgrel, epoch)
                logger.info(f"📝 HOKIBOT observed: {pkg_name} -> {local_version}")
                return True

            logger.error(f"❌ No package files created for {pkg_name}")
            return False

        except Exception as e:
            logger.error(f"❌ Error building {pkg_name}: {e}")
            return False

    def _build_single_package(self, pkg_name: str, is_aur: bool) -> bool:
        print(f"\n--- Processing: {pkg_name} ({'AUR' if is_aur else 'Local'}) ---")

        cached, cached_version = self._check_cache_for_package(pkg_name, is_aur)
        if cached:
            logger.info(f"✅ Using cached package: {pkg_name}")
            self.built_packages.append(f"{pkg_name} ({cached_version}) [CACHED]")

            self.version_tracker.register_package_target_version(pkg_name, cached_version)

            if is_aur:
                self.stats["aur_success"] += 1
                self.build_tracker.record_built_package(pkg_name, cached_version, is_aur=True)
            else:
                self.stats["local_success"] += 1
                self.build_tracker.record_built_package(pkg_name, cached_version, is_aur=False)

            return True

        if is_aur:
            return self._build_aur_package(pkg_name)
        return self._build_local_package(pkg_name)

    def build_packages(self) -> int:
        print("\n" + "=" * 60)
        print("Building packages (Cache-aware)")
        print("=" * 60)

        local_packages, aur_packages = self.get_package_lists()

        print(f"📦 Package statistics:")
        print(f"   Local packages: {len(local_packages)}")
        print(f"   AUR packages: {len(aur_packages)}")
        print(f"   Total packages: {len(local_packages) + len(aur_packages)}")
        print(f"   Cache enabled: {self.use_cache}")
        print(f"   Package signing: {'ENABLED' if self.gpg_handler.sign_packages_enabled else 'DISABLED'}")

        print(f"\n🔨 Building {len(aur_packages)} AUR packages")
        for pkg in aur_packages:
            if not self._build_single_package(pkg, is_aur=True):
                self.stats["aur_failed"] += 1
                self.build_tracker.record_failed_package(is_aur=True)

        print(f"\n🔨 Building {len(local_packages)} local packages")
        for pkg in local_packages:
            if not self._build_single_package(pkg, is_aur=False):
                self.stats["local_failed"] += 1
                self.build_tracker.record_failed_package(is_aur=False)

        return self.stats["aur_success"] + self.stats["local_success"]

    def upload_packages(self) -> bool:
        pkg_files = list(self.output_dir.glob("*.pkg.tar.*"))
        db_files = list(self.output_dir.glob(f"{self.repo_name}.*"))

        all_files = pkg_files + db_files

        if not all_files:
            logger.warning("No files to upload")
            self.version_tracker.set_upload_successful(False)
            return False

        self.ssh_client.ensure_remote_directory()

        file_patterns = [
            str(self.output_dir / "*.pkg.tar.*"),
            str(self.output_dir / f"{self.repo_name}.*")
        ]

        files_to_upload = []
        for pattern in file_patterns:
            files_to_upload.extend(glob.glob(pattern))

        if not files_to_upload:
            logger.error("No files found to upload!")
            self.version_tracker.set_upload_successful(False)
            return False

        upload_success = self.rsync_client.upload_files(files_to_upload, self.output_dir)

        self.version_tracker.set_upload_successful(upload_success)
        return upload_success

    def create_artifact_archive_for_github(self) -> Optional[Path]:
        log_path = Path("builder.log")
        return self.artifact_manager.create_artifact_archive(self.output_dir, log_path)

    def run(self):
        print("\n" + "=" * 60)
        print("🚀 MANJARO PACKAGE BUILDER (MODULAR ARCHITECTURE WITH CACHE)")
        print("=" * 60)

        try:
            print("\n🔧 Initial setup...")
            # SECURITY: do not print paths or directory names
            print("Repository root: [REDACTED]")
            print(f"Repository name: {self.repo_name}")
            print("Output directory: [REDACTED]")
            print("PACKAGER identity: [LOADED]")
            print(f"Cache optimization: {'ENABLED' if self.use_cache else 'DISABLED'}")
            print(f"Package signing: {'ENABLED' if self.sign_packages else 'DISABLED'}")

            if self.use_cache:
                built_count = len(list(self.output_dir.glob("*.pkg.tar.*")))
                print(f"📦 Initial cache contains {built_count} package files")

            # Build manifest allowlist from PKGBUILD parsing (local + AUR)
            local_list, aur_list = self.get_package_lists()
            sources: List[str] = []
            for p in local_list:
                sources.append(str(self.repo_root / p))
            for a in aur_list:
                sources.append(a)

            allowlist = ManifestFactory.build_allowlist(sources)
            self.cleanup_manager.set_allowlist(allowlist)

            print("\n" + "=" * 60)
            print("STEP 0: GPG INITIALIZATION")
            print("=" * 60)
            if self.gpg_handler.gpg_enabled:
                if not self.gpg_handler.import_gpg_key():
                    logger.error("❌ Failed to import GPG key, disabling signing")
                else:
                    logger.info("✅ GPG initialized successfully")
            else:
                logger.info("ℹ️ GPG signing disabled (no key provided)")

            print("\n" + "=" * 60)
            print("STEP 1: SIMPLIFIED REPOSITORY STATE DISCOVERY")
            print("=" * 60)

            repo_exists, has_packages = self.ssh_client.check_repository_exists_on_vps()
            self._apply_repository_state(repo_exists, has_packages)

            self.ssh_client.ensure_remote_directory()

            remote_packages = self.ssh_client.list_remote_packages()
            self.remote_files = [os.path.basename(f) for f in remote_packages] if remote_packages else []

            logger.info(f"📊 Remote packages discovered: {len(self.remote_files)}")

            if remote_packages:
                print("\n" + "=" * 60)
                print("MANDATORY PRECONDITION: Mirroring remote packages locally")
                print("=" * 60)

                cached_mirror_files = list(self.mirror_temp_dir.glob("*.pkg.tar.*"))
                if cached_mirror_files and self.use_cache:
                    print(f"📦 Using cached VPS mirror with {len(cached_mirror_files)} files")
                    for cached_file in cached_mirror_files:
                        dest = self.output_dir / cached_file.name
                        if not dest.exists():
                            shutil.copy2(cached_file, dest)
                else:
                    if not self.rsync_client.mirror_remote_packages(self.mirror_temp_dir, self.output_dir):
                        logger.error("❌ FAILED to mirror remote packages locally")
                        return 1
            else:
                logger.info("ℹ️ No remote packages to mirror (repository appears empty)")

            existing_db_files, missing_db_files = self.database_manager.check_database_files()
            if existing_db_files:
                self.database_manager.fetch_existing_database(existing_db_files)

            print("\n" + "=" * 60)
            print("STEP 5: PACKAGE BUILDING (CACHE-AWARE SRCINFO VERSIONING)")
            print("=" * 60)

            total_built = self.build_packages()

            local_packages = self.database_manager._get_all_local_packages()

            if local_packages or remote_packages:
                print("\n" + "=" * 60)
                print("STEP 6: REPOSITORY DATABASE HANDLING (WITH LOCAL MIRROR)")
                print("=" * 60)

                # Pre-db VPS cleanup is safe and will never delete db artifacts;
                # it will enforce mirror deletions only once local inventory exists.
                print("\n" + "=" * 60)
                print("🚨 PRE-DATABASE CLEANUP: Removing obsolete remote packages")
                print("=" * 60)
                self.cleanup_manager.server_cleanup(self.version_tracker)

                if self.database_manager.generate_full_database(self.repo_name, self.output_dir, self.cleanup_manager):
                    if self.gpg_handler.gpg_enabled:
                        if not self.gpg_handler.sign_repository_files(self.repo_name, str(self.output_dir)):
                            logger.warning("⚠️ Failed to sign repository files, continuing anyway")

                    if not self.ssh_client.test_ssh_connection():
                        logger.warning("SSH test failed, but trying upload anyway...")

                    upload_success = self.upload_packages()

                    # Post-upload VPS cleanup: enforce exact local output_dir inventory (delete stale)
                    if upload_success:
                        print("\n" + "=" * 60)
                        print("🚨 POST-UPLOAD CLEANUP: Enforcing VPS mirror of local output_dir")
                        print("=" * 60)
                        self.cleanup_manager.server_cleanup(self.version_tracker)

                    self.gpg_handler.cleanup()

                    if upload_success:
                        print("\n" + "=" * 60)
                        print("STEP 7: FINAL REPOSITORY STATE UPDATE")
                        print("=" * 60)

                        repo_exists, has_packages = self.ssh_client.check_repository_exists_on_vps()
                        self._apply_repository_state(repo_exists, has_packages)
                        self._sync_pacman_databases()

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
                print(f"   Cache hits: {self.stats['cache_hits']}")
                print(f"   Cache misses: {self.stats['cache_misses']}")

                if self.stats['aur_failed'] > 0 or self.stats['local_failed'] > 0:
                    print("⚠️ Some packages failed to build")
                else:
                    print("✅ All packages are up to date or built successfully!")

                self.gpg_handler.cleanup()

            print("\n" + "=" * 60)
            print("STEP 8: CREATING ARTIFACT ARCHIVE FOR GITHUB")
            print("=" * 60)

            artifact_archive = self.create_artifact_archive_for_github()
            if artifact_archive:
                logger.info("✅ Artifact archive created")
            else:
                logger.warning("⚠️ Failed to create artifact archive")

            elapsed = time.time() - self.stats["start_time"]
            summary = self.build_tracker.get_summary()

            print("\n" + "=" * 60)
            print("📊 BUILD SUMMARY WITH CACHE STATISTICS")
            print("=" * 60)
            print(f"Duration: {elapsed:.1f}s")
            print(f"AUR packages:    {summary['aur_success']} (failed: {summary['aur_failed']})")
            print(f"Local packages:  {summary['local_success']} (failed: {summary['local_failed']})")
            print(f"Total built:     {summary['total_built']}")
            print(f"Skipped:         {summary['skipped']}")
            print(f"Cache hits:      {self.stats['cache_hits']}")
            print(f"Cache misses:    {self.stats['cache_misses']}")
            denom = (self.stats['cache_hits'] + self.stats['cache_misses']) or 1
            print(f"Cache efficiency: {self.stats['cache_hits'] / denom * 100:.1f}%")
            print(f"GPG signing:     {'Enabled' if self.gpg_handler.gpg_enabled else 'Disabled'}")
            print(f"Package signing: {'Enabled' if self.gpg_handler.sign_packages_enabled else 'Disabled'}")
            print("PACKAGER:        [LOADED]")
            print(f"Mirror policy:   ✅ VPS is target only")
            print("=" * 60)

            if self.built_packages:
                print("\n📦 Built packages:")
                for pkg in self.built_packages:
                    print(f"  - {pkg}")

            return 0

        except Exception as e:
            print("\n❌ Build failed")
            import traceback
            traceback.print_exc()
            if hasattr(self, 'gpg_handler'):
                self.gpg_handler.cleanup()
            return 1
