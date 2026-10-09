"""
Dependency Installer Module - CI-safe dependency installation with fallback
Now with per-package session tracking + conflict resolution.
"""

import re
import time
import logging
from typing import List, Tuple, Optional, Dict, Set
from pathlib import Path

import config  # for CONFLICT_REMOVE_ALLOWLIST

logger = logging.getLogger(__name__)


class DependencyInstaller:
    """CI-safe dependency installer with pacman -> yay fallback and session cleanup"""

    # Hardcoded provider map for deterministic resolution
    PROVIDER_MAP = {
        "sdl2": "sdl2-compat"
    }

    def __init__(self, shell_executor, debug_mode: bool = False):
        self.shell_executor = shell_executor
        self.debug_mode = debug_mode

        # Session tracking
        self.session_active = False
        self.session_baseline: Optional[Set[str]] = None
        self.session_pkg_name: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_version(dep: str) -> str:
        """Return the base package name without any version constraint."""
        return re.sub(r'[<=>].*', '', dep).strip()

    def _snapshot_explicit(self) -> Set[str]:
        """
        Take a snapshot of currently explicitly installed packages.
        Uses: pacman -Qqe
        Returns set of package names.
        """
        cmd = "LC_ALL=C pacman -Qqe"
        result = self.shell_executor.run_command(
            cmd, log_cmd=False, check=False, timeout=60
        )
        if result.returncode == 0 and result.stdout:
            pkgs = {line.strip() for line in result.stdout.splitlines() if line.strip()}
            logger.debug(f"Explicit packages snapshot: {len(pkgs)} packages")
            return pkgs
        else:
            logger.warning("Failed to take explicit package snapshot, using empty baseline")
            return set()

    def begin_session(self, pkg_name: str):
        """
        Start a new dependency session for a specific package.
        Captures baseline snapshot for later cleanup.
        """
        if self.session_active:
            logger.warning(f"DEP_SESSION_ALREADY_ACTIVE pkg={self.session_pkg_name} new={pkg_name}")
            self.end_session()  # clean up previous just in case

        self.session_pkg_name = pkg_name
        self.session_baseline = self._snapshot_explicit()
        self.session_active = True

        logger.info(f"DEP_SESSION_START=1 pkg={pkg_name}")
        logger.info(f"DEP_SESSION_BASELINE_COUNT={len(self.session_baseline)}")

    def end_session(self):
        """
        End current dependency session and remove all explicitly installed
        packages that were added during this session (difference from baseline).
        Never removes packages that were present in baseline.
        """
        if not self.session_active:
            logger.debug("DEP_SESSION_END: no active session, skipping")
            return

        pkg_name = self.session_pkg_name or "unknown"
        current_explicit = self._snapshot_explicit()
        added_pkgs = current_explicit - self.session_baseline

        logger.info(f"DEP_SESSION_END pkg={pkg_name}")
        logger.info(f"DEP_SESSION_ADDED_COUNT={len(added_pkgs)}")

        if added_pkgs:
            pkgs_list = list(added_pkgs)
            logger.info(f"DEP_SESSION_REMOVE_START=1 count={len(pkgs_list)}")

            # Remove in batches to avoid command line length limits
            batch_size = 50
            success = True
            for i in range(0, len(pkgs_list), batch_size):
                batch = pkgs_list[i:i + batch_size]
                cmd = f"sudo LC_ALL=C pacman -R --noconfirm " + " ".join(batch)
                result = self.shell_executor.run_command(
                    cmd, log_cmd=True, check=False, timeout=300
                )
                if result.returncode != 0:
                    logger.error(f"DEP_SESSION_REMOVE_FAIL=1 pkg={pkg_name} batch={len(batch)}")
                    success = False
                else:
                    logger.info(f"DEP_SESSION_REMOVE_OK=1 pkg={pkg_name} batch={len(batch)}")

            if success:
                logger.info(f"DEP_SESSION_REMOVE_OK=1 pkg={pkg_name} total={len(pkgs_list)}")
            else:
                logger.error(f"DEP_SESSION_REMOVE_FAIL=1 pkg={pkg_name} total={len(pkgs_list)}")
        else:
            logger.info("DEP_SESSION_NO_ADDED_PACKAGES")

        # Clear session state
        self.session_active = False
        self.session_baseline = None
        self.session_pkg_name = None

    def _detect_failure_reason(self, output: str) -> str:
        """Detect the reason for pacman failure"""
        output_lower = output.lower()

        if "target not found" in output_lower or "could not find" in output_lower:
            return "target_not_found"
        elif "could not resolve" in output_lower:
            return "could_not_resolve"
        elif "failed to prepare transaction" in output_lower:
            return "failed_to_prepare_transaction"
        elif "unresolvable package conflicts detected" in output_lower:
            return "unresolvable_conflict"
        elif "are in conflict" in output_lower:
            return "package_conflict"
        else:
            return "unknown"

    def _stderr_has_fatal_error(self, stderr: str) -> bool:
        """
        Detect fatal pacman errors in stderr even when exit code is 0.

        Some pacman hooks (e.g. DKMS) can fail while pacman itself still
        exits 0. Without this check the installer would report success and
        the subsequent makepkg step would fail in a confusing way.

        Only well-known fatal patterns are matched so that normal warnings
        (``warning: ... is up to date -- skipping``) do not trigger this.
        """
        if not stderr:
            return False

        fatal_patterns = (
            "error: command failed to execute correctly",
            "error: failed to commit transaction",
            "error: failed to init transaction",
            "error: target not found",
            "error: could not open file",
            "error: failed to prepare transaction",
            "error: unresolvable package conflicts detected",
        )
        for line in stderr.splitlines():
            line_lower = line.lower()
            for pattern in fatal_patterns:
                if pattern in line_lower:
                    return True
        return False

    # ------------------------------------------------------------------
    # Cleaning / provider / conflict
    # ------------------------------------------------------------------

    def _clean_package_names(self, packages: List[str]) -> List[str]:
        """
        Clean and validate package names.

        IMPORTANT: Version constraints are now PRESERVED in the returned
        list (e.g. ``nvidia-dkms=390.157``). Version stripping is only done
        internally for comparison / provider / conflict lookups, never for
        the actual pacman/yay command line.
        """
        clean_deps = []

        for dep in packages:
            dep_stripped = dep.strip()

            if not dep_stripped:
                continue

            # Skip package references with unresolved shell variables
            if any(x in dep_stripped for x in ['$', '{', '}', '(', ')', '[', ']']):
                logger.debug(f"Skipping malformed dep: {dep_stripped!r}")
                continue

            # Must contain at least one alphanumeric character
            if not re.search(r'[a-zA-Z0-9]', dep_stripped):
                continue

            # Extract base name for special-case handling
            base_name = self._strip_version(dep_stripped)

            # Handle known phantom package 'lgi' -> 'lua-lgi'
            if base_name == 'lgi':
                logger.warning("⚠️ Found phantom package 'lgi' - will be replaced with 'lua-lgi'")
                if 'lua-lgi' not in clean_deps:
                    clean_deps.append('lua-lgi')
                continue

            # Preserve original entry including any version constraint
            clean_deps.append(dep_stripped)

        # Deduplicate while preserving order (dedupe by full string)
        seen = set()
        unique_deps = []
        for dep in clean_deps:
            if dep not in seen:
                seen.add(dep)
                unique_deps.append(dep)

        return unique_deps

    def _apply_provider_map(self, packages: List[str]) -> List[str]:
        """
        Apply deterministic provider mapping.

        A version constraint cannot be meaningfully transplanted onto a
        provider substitute, so the constraint is intentionally dropped
        when a match is found (this mirrors the pre-fix behaviour for the
        provider path only).
        """
        result = []
        for pkg in packages:
            base_name = self._strip_version(pkg)

            if base_name in self.PROVIDER_MAP:
                replacement = self.PROVIDER_MAP[base_name]
                if base_name != pkg:
                    logger.info(
                        f"PROVIDER_RESOLVE_VERSION_DROP: replacing {pkg} "
                        f"with {replacement} (version constraint dropped)"
                    )
                else:
                    logger.info(f"PROVIDER_RESOLVE: replacing {pkg} with {replacement}")
                result.append(replacement)
            else:
                result.append(pkg)
        return result

    def filter_self_references(self, deps: List[str], pkg_names: List[str]) -> List[str]:
        """
        Filter out runtime dependencies that refer to packages produced by this
        same PKGBUILD (self-references in split packages).

        Comparison uses the version-stripped base name; the returned list keeps
        the original entries (including any version constraint).
        """
        if not deps or not pkg_names:
            return deps

        pkg_name_set = set(pkg_names)
        filtered = []
        skipped = []

        for dep in deps:
            dep_clean = self._strip_version(dep)
            if dep_clean in pkg_name_set:
                skipped.append(dep)
            else:
                filtered.append(dep)

        if skipped:
            logger.info(f"DEP_SELF_REFERENCE_SKIP pkg_names={pkg_names} skipped={skipped}")

        return filtered

    def _handle_conflicts(self, packages: List[str]) -> bool:
        """
        Check for known conflicts and resolve them automatically.
        Uses CONFLICT_REMOVE_ALLOWLIST from config.
        Returns True if installation should continue, False if fatal.
        Logs CONFLICT_BASELINE_BLOCK=1 when removal is blocked.

        Conflict lookups use version-stripped base names because the
        allowlist is keyed on plain package names.
        """
        if not packages or not self.session_active:
            return True

        conflict_map = getattr(config, 'CONFLICT_REMOVE_ALLOWLIST', {})
        if not conflict_map:
            return True

        # Check if any of the packages to install are keys in the conflict map
        for pkg in packages:
            pkg_base = self._strip_version(pkg)
            if pkg_base in conflict_map:
                for conflict in conflict_map[pkg_base]:
                    # Check if conflicting package is installed
                    check_cmd = f"pacman -Q {conflict} 2>/dev/null"
                    result = self.shell_executor.run_command(
                        check_cmd, log_cmd=False, check=False, timeout=30
                    )
                    if result.returncode == 0:
                        # Conflict package is installed
                        logger.info(f"CONFLICT_DETECTED pkg={pkg} conflict={conflict}")

                        # Check if conflict is in baseline snapshot
                        if self.session_baseline and conflict in self.session_baseline:
                            logger.error(
                                f"CONFLICT_BASELINE_BLOCK=1 pkg={pkg} "
                                f"conflict={conflict} reason=in_baseline"
                            )
                            logger.error(
                                f"Cannot automatically remove {conflict} because it was "
                                f"present before this build session."
                            )
                            logger.error(
                                f"To resolve, manually remove {conflict} or adjust "
                                f"the conflict allowlist."
                            )
                            return False

                        # Safe to remove
                        logger.info(f"CONFLICT_REMOVE=1 pkg={pkg} conflict={conflict}")
                        remove_cmd = f"sudo LC_ALL=C pacman -R --noconfirm {conflict}"
                        remove_result = self.shell_executor.run_command(
                            remove_cmd, log_cmd=True, check=False, timeout=120
                        )
                        if remove_result.returncode == 0:
                            logger.info(f"CONFLICT_REMOVE_OK=1 pkg={pkg} conflict={conflict}")
                        else:
                            logger.error(f"CONFLICT_REMOVE_FAIL=1 pkg={pkg} conflict={conflict}")
                            return False

        return True

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def install_packages(self, packages: List[str], allow_aur: bool = True, mode: str = "build") -> bool:
        """
        Install packages with pacman -> yay fallback.
        Handles conflict resolution automatically.

        Version constraints in ``packages`` (e.g. ``nvidia-dkms=390.157``)
        are preserved end-to-end so pacman/yay install the correct pinned
        version instead of silently resolving to the latest one.

        Args:
            packages: List of package names to install (may include version pins)
            allow_aur: Whether to allow fallback to AUR (yay)
            mode: Installation mode ("build" for makedepends/checkdepends, "runtime" for depends)

        Returns:
            True if installation successful, False otherwise
        """
        if not packages:
            return True

        clean_packages = self._clean_package_names(packages)

        if not clean_packages:
            logger.info("No valid packages to install after cleaning")
            return True

        # --- Deterministic provider resolution (version-aware) ---
        clean_packages = self._apply_provider_map(clean_packages)
        # ---------------------------------------------------------

        # --- Conflict resolution (version-aware) ---
        if not self._handle_conflicts(clean_packages):
            logger.error("Conflict resolution failed, aborting installation")
            return False

        logger.info(f"DEP_INSTALL_START=1 count={len(clean_packages)} mode={mode}")

        # Log the resolved install list so version pins are visible in logs
        logger.info(f"DEP_INSTALL_PACKAGES={clean_packages}")

        # Convert to string for command (version pins preserved)
        pkgs_str = ' '.join(clean_packages)

        # --- FIRST ATTEMPT: Try pacman ---
        logger.info(f"DEP_INSTALL_ATTEMPT=1 manager=pacman")
        cmd = f"sudo LC_ALL=C pacman -Sy --needed --noconfirm --ask=4 {pkgs_str}"

        result = self.shell_executor.run_command(
            cmd,
            log_cmd=True,
            check=False,
            timeout=1200
        )

        stderr_text = result.stderr or ""
        pacman_stderr_fatal = self._stderr_has_fatal_error(stderr_text)

        if result.returncode == 0 and not pacman_stderr_fatal:
            logger.info(f"DEP_INSTALL_OK=1 manager=pacman count={len(clean_packages)}")
            return True

        # Determine failure reason for logging / fallback decision
        if result.returncode == 0 and pacman_stderr_fatal:
            failure_reason = "stderr_fatal_pattern_exit0"
            logger.warning(
                f"DEP_INSTALL_PACMAN_EXIT0_WITH_ERROR=1 manager=pacman "
                f"count={len(clean_packages)}"
            )
            logger.error(f"STDOUT:\n{result.stdout}")
            logger.error(f"STDERR:\n{result.stderr}")
        else:
            combined_output = (result.stdout or "") + "\n" + stderr_text
            failure_reason = self._detect_failure_reason(combined_output)
            logger.warning(
                f"DEP_INSTALL_PACMAN_FAIL=1 reason={failure_reason} "
                f"exitcode={result.returncode}"
            )
            logger.error(f"STDOUT:\n{result.stdout}")
            logger.error(f"STDERR:\n{result.stderr}")

        # Don't fallback to yay if AUR not allowed
        if not allow_aur:
            logger.error("DEP_INSTALL_YAY_SKIP=1 reason=aur_not_allowed")
            return False

        # --- SECOND ATTEMPT: Fallback to yay ---
        logger.info(f"DEP_INSTALL_ATTEMPT=2 manager=yay")

        # Use yay with --noconfirm to avoid prompts; version pins preserved
        cmd = f"LC_ALL=C yay -S --needed --noconfirm {pkgs_str}"

        result = self.shell_executor.run_command(
            cmd,
            log_cmd=True,
            check=False,
            user="builder",
            timeout=1800
        )

        yay_stderr_text = result.stderr or ""
        yay_stderr_fatal = self._stderr_has_fatal_error(yay_stderr_text)

        if result.returncode == 0 and not yay_stderr_fatal:
            logger.info(f"DEP_INSTALL_OK=1 manager=yay count={len(clean_packages)}")
            return True

        # Analyze yay failure
        if result.returncode == 0 and yay_stderr_fatal:
            yay_failure_reason = "stderr_fatal_pattern_exit0"
            logger.error(
                f"DEP_INSTALL_YAY_EXIT0_WITH_ERROR=1 manager=yay "
                f"count={len(clean_packages)}"
            )
            logger.error(f"STDOUT:\n{result.stdout}")
            logger.error(f"STDERR:\n{result.stderr}")
        else:
            yay_output = (result.stdout or "") + "\n" + yay_stderr_text
            yay_failure_reason = self._detect_failure_reason(yay_output)
            logger.error(
                f"DEP_INSTALL_YAY_FAIL=1 reason={yay_failure_reason} "
                f"exitcode={result.returncode}"
            )
            logger.error(f"STDOUT:\n{result.stdout}")
            logger.error(f"STDERR:\n{result.stderr}")
        return False

    def extract_dependencies(self, pkg_dir: Path) -> Tuple[List[str], List[str], List[str]]:
        """
        Extract dependencies from .SRCINFO or PKGBUILD

        Version constraints (``=390.157``, ``>=...``, etc.) are preserved
        in the returned lists — callers must pass them through unchanged
        to ``install_packages``.

        Args:
            pkg_dir: Path to package directory

        Returns:
            Tuple of (makedepends, checkdepends, depends)
        """
        srcinfo_path = pkg_dir / ".SRCINFO"
        srcinfo_content = None

        # First try to read existing .SRCINFO
        if srcinfo_path.exists():
            try:
                with open(srcinfo_path, 'r') as f:
                    srcinfo_content = f.read()
            except Exception as e:
                logger.warning(f"Failed to read existing .SRCINFO: {e}")

        # Generate .SRCINFO if not available
        if not srcinfo_content:
            try:
                result = self.shell_executor.run_command(
                    'makepkg --printsrcinfo',
                    cwd=pkg_dir,
                    capture=True,
                    check=False,
                    timeout=60
                )

                if result.returncode == 0 and result.stdout:
                    srcinfo_content = result.stdout
                    # Also write to .SRCINFO for future use
                    with open(srcinfo_path, 'w') as f:
                        f.write(srcinfo_content)
                else:
                    logger.warning(f"makepkg --printsrcinfo failed: {result.stderr}")
                    return [], [], []
            except Exception as e:
                logger.warning(f"Error running makepkg --printsrcinfo: {e}")
                return [], [], []

        # Parse dependencies from SRCINFO content
        lines = srcinfo_content.strip().split('\n')

        makedepends = []
        checkdepends = []
        depends = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Look for dependency fields
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Extract all types of dependencies
                if key == 'makedepends':
                    makedepends.append(value)
                elif key == 'checkdepends':
                    checkdepends.append(value)
                elif key == 'depends':
                    depends.append(value)

        return makedepends, checkdepends, depends