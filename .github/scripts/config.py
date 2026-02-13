import os

# Repository configuration
REPO_DB_NAME = "manjaro-awesome"  # Default repository name
OUTPUT_DIR = "built_packages"     # Local output directory
BUILD_TRACKING_DIR = ".buildtracking"  # Build tracking directory

# PACKAGER identity from environment variable (secure via GitHub Secrets)
# Default to a safe generic identity if environment variable is not set
PACKAGER_ID = os.getenv("PACKAGER_ENV", "CI Builder <no-reply@users.noreply.github.com>")

# Hokibot Git identity for commits
HOKIBOT_GIT_USER_NAME = "hokibot"
HOKIBOT_GIT_USER_EMAIL = "hokibot@users.noreply.github.com"

# SSH and Git configuration
SSH_REPO_URL = "git@github.com:megvadulthangya/manjaro-awesome.git"
SSH_OPTIONS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=30",
    "-o", "BatchMode=yes"
]

# Build timeouts (seconds)
MAKEPKG_TIMEOUT = {
    "default": 3600,        # 1 hour for normal packages
    "large_packages": 7200, # 2 hours for large packages (gtk, qt, chromium)
    "simplescreenrecorder": 5400,  # 1.5 hours
}

# Special dependency mappings
SPECIAL_DEPENDENCIES = {
    "gtk2": ["gtk-doc", "docbook-xsl", "libxslt", "gobject-introspection"],
    "awesome-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "awesome-freedesktop-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "lain-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "simplescreenrecorder": ["jack2"],  # Convert jack to jack2
}

# Build tool checks (will be installed if missing)
REQUIRED_BUILD_TOOLS = [
    "make", "gcc", "pkg-config", "autoconf", "automake", 
    "libtool", "cmake", "meson", "ninja", "patch"
]

# Temporary directories (runtime-required, /tmp is POSIX invariant)
MIRROR_TEMP_DIR = "/tmp/repo_mirror"
SYNC_CLONE_DIR = "/tmp/repo-builder-gitclone"  # FIX: generic, no repo name

# AUR configuration
AUR_URLS = [
    "https://aur.archlinux.org/{pkg_name}.git",
    "git://aur.archlinux.org/{pkg_name}.git"
]

# Build directory names
AUR_BUILD_DIR = "build_aur"

# GitHub repository for synchronization (fork‑safe, fallback to env)
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY", "")  # FIX: no hardcoded owner/repo

# Debug mode configuration - when True, bypass logger for critical build output
DEBUG_MODE = True

# VPS configuration (from environment variables)
VPS_USER = os.getenv("VPS_USER")
VPS_HOST = os.getenv("VPS_HOST")
VPS_SSH_KEY = os.getenv("VPS_SSH_KEY")
REMOTE_DIR = os.getenv("REMOTE_DIR")
REPO_NAME = os.getenv("REPO_NAME")
REPO_SERVER_URL = os.getenv("REPO_SERVER_URL")

# GPG configuration
GPG_KEY_ID = os.getenv("GPG_KEY_ID")
GPG_PRIVATE_KEY = os.getenv("GPG_PRIVATE_KEY")

# Package signing configuration
SIGN_PACKAGES = True  # Default toggle for individual package signing

# Default behavior: install runtime depends during build in CI
INSTALL_RUNTIME_DEPS_IN_CI = True

# Conflict resolution allowlist
# Format: {"package-being-installed": ["conflicting-package-to-remove"]}
# When installing the key package, if conflict suggests removing the value package,
# it will be auto-removed if allowed by this list.
CONFLICT_REMOVE_ALLOWLIST = {
    "i3lock-color": ["i3lock"]
}

# ----------------------------------------------------------------------
# VPS HYGIENE CONFIGURATION (P0)
# ----------------------------------------------------------------------
# Enable/disable automatic cleanup of extra files on the VPS after publish.
ENABLE_VPS_HYGIENE = True

# When True, only log what would be deleted; no actual deletions.
VPS_HYGIENE_DRY_RUN = False

# Number of latest versions to keep per package on the VPS.
# Only applies to packages present in the desired inventory.
KEEP_LATEST_VERSIONS = 1

# If True, never delete public key / metadata files (*.pub, *.key, etc.) on VPS.
# If False, they will be considered for deletion (subject to other rules).
KEEP_VPS_EXTRA_METADATA = True

# ----------------------------------------------------------------------
# VPS HYGIENE 2‑PHASE SAFETY SWITCH
# ----------------------------------------------------------------------
# When False, even if VPS_HYGIENE_DRY_RUN=False, orphan signature deletions
# are still blocked (only logged). When True, orphan signature deletions
# are allowed when dry_run=False. Old‑version pruning remains dry‑run only
# regardless of this flag.
ENABLE_VPS_ORPHAN_SIG_DELETE = True
