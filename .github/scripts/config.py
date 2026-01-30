"""
Configuration file for Manjaro Package Builder
All variables and secrets are defined here - ZERO HARDCODING elsewhere
"""

import os

# ============================================================================
# GITHUB SECRETS - Load from environment variables (set in GitHub Secrets)
# ============================================================================

# SSH and VPS configuration
VPS_USER = os.getenv("VPS_USER", "")
VPS_HOST = os.getenv("VPS_HOST", "")
VPS_SSH_KEY = os.getenv("VPS_SSH_KEY", "")  # Private SSH key for VPS access
REMOTE_DIR = os.getenv("REMOTE_DIR", "")    # Remote directory on VPS

# Repository configuration
REPO_NAME = os.getenv("REPO_NAME", "")      # Repository name (e.g., "manjaro-awesome")
REPO_SERVER_URL = os.getenv("REPO_SERVER_URL", "")  # Full URL to repository

# GPG configuration (optional)
GPG_KEY_ID = os.getenv("GPG_KEY_ID", "")    # GPG key ID for signing
GPG_PRIVATE_KEY = os.getenv("GPG_PRIVATE_KEY", "")  # GPG private key

# Packager identity
PACKAGER_ID = os.getenv("PACKAGER_ENV", "Maintainer <no-reply@gshoots.hu>")

# ============================================================================
# BUILD CONFIGURATION
# ============================================================================

# Local directories
OUTPUT_DIR = "built_packages"               # Local output directory
BUILD_TRACKING_DIR = ".buildtracking"       # Build tracking directory

# AUR configuration
AUR_URLS = [
    "https://aur.archlinux.org/{pkg_name}.git",
    "git://aur.archlinux.org/{pkg_name}.git"
]

# Build directory names
AUR_BUILD_DIR = "build_aur"

# Temporary directories (POSIX invariant)
MIRROR_TEMP_DIR = "/tmp/repo_mirror"
SYNC_CLONE_DIR = "/tmp/manjaro-awesome-gitclone"

# SSH options
SSH_OPTIONS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=30",
    "-o", "BatchMode=yes"
]

# Build timeouts (seconds)
MAKEPKG_TIMEOUT = {
    "default": 3600,        # 1 hour for normal packages
    "large_packages": 7200, # 2 hours for large packages
    "simplescreenrecorder": 5400,  # 1.5 hours
}

# Special dependency mappings
SPECIAL_DEPENDENCIES = {
    "gtk2": ["gtk-doc", "docbook-xsl", "libxslt", "gobject-introspection"],
    "awesome-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "awesome-freedesktop-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "lain-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "simplescreenrecorder": ["jack2"],
}

# Required build tools
REQUIRED_BUILD_TOOLS = [
    "make", "gcc", "pkg-config", "autoconf", "automake", 
    "libtool", "cmake", "meson", "ninja", "patch"
]

# Debug mode - when True, bypass logger for critical build output
DEBUG_MODE = True