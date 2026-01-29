"""
Configuration file for Manjaro Package Builder
Central source of truth for all configuration values.
"""

import os
from pathlib import Path

# --- DYNAMIC REPOSITORY CONFIGURATION ---
# Get repository URL from environment or default
GITHUB_REPO = os.getenv("GITHUB_REPO", "megvadulthangya/manjaro-awesome.git")

# Extract repository name dynamically from URL
# e.g., "user/repo.git" -> "repo"
_repo_basename = os.path.basename(GITHUB_REPO)
if _repo_basename.endswith('.git'):
    _repo_basename = _repo_basename[:-4]

# Allow explicit override, otherwise use extracted name
REPO_NAME = os.getenv("REPO_NAME", _repo_basename)

# Database name usually matches repo name
REPO_DB_NAME = REPO_NAME

# --- PATHS (DYNAMIC) ---
# All temporary paths include the repo name to avoid collisions
MIRROR_TEMP_DIR = f"/tmp/{REPO_NAME}_mirror"
SYNC_CLONE_DIR = f"/tmp/{REPO_NAME}_gitclone"

# Local directories
OUTPUT_DIR = "built_packages"
BUILD_TRACKING_DIR = ".build_tracking"
AUR_BUILD_DIR = "build_aur"

# --- IDENTITIES & SECRETS ---
# Packager identity
PACKAGER_ID = os.getenv("PACKAGER_ENV", "Maintainer <no-reply@gshoots.hu>")

# VPS Configuration (Loaded from Secrets)
VPS_USER = os.getenv("VPS_USER", "")
VPS_HOST = os.getenv("VPS_HOST", "")
VPS_SSH_KEY = os.getenv("VPS_SSH_KEY", "")
REMOTE_DIR = os.getenv("REMOTE_DIR", "")

# Git SSH Key for synchronization
CI_PUSH_SSH_KEY = os.getenv("CI_PUSH_SSH_KEY", "")
SSH_REPO_URL = f"git@github.com:{GITHUB_REPO}"

# GPG Configuration
GPG_PRIVATE_KEY = os.getenv("GPG_PRIVATE_KEY", "")
GPG_KEY_ID = os.getenv("GPG_KEY_ID", "")

# --- BUILD CONFIGURATION ---
SSH_OPTIONS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=30",
    "-o", "BatchMode=yes"
]

# AUR Configuration
AUR_URLS = [
    "https://aur.archlinux.org/{pkg_name}.git",
    "git://aur.archlinux.org/{pkg_name}.git"
]

# Build timeouts (seconds)
MAKEPKG_TIMEOUT = {
    "default": 3600,
    "large_packages": 7200,
}

# Dependency mappings
SPECIAL_DEPENDENCIES = {
    "gtk2": ["gtk-doc", "docbook-xsl", "libxslt", "gobject-introspection"],
    "awesome-git": ["lua", "lgi", "imagemagick", "asciidoc"],
}

# Required tools
REQUIRED_BUILD_TOOLS = [
    "make", "gcc", "pkg-config", "autoconf", "automake", 
    "libtool", "cmake", "meson", "ninja", "patch"
]

# Debug mode
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"