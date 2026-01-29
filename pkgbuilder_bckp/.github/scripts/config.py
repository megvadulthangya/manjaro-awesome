"""
Configuration file for Manjaro Package Builder
"""

import os

# Repository configuration
REPO_DB_NAME = "manjaro-awesome"  # Default repository name
OUTPUT_DIR = "built_packages"     # Local output directory
BUILD_TRACKING_DIR = ".buildtracking"  # Build tracking directory

# PACKAGER identity from environment variable (secure via GitHub Secrets)
PACKAGER_ID = os.getenv("PACKAGER_ENV", "Maintainer <no-reply@gshoots.hu>")

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
SYNC_CLONE_DIR = "/tmp/manjaro-awesome-gitclone"

# AUR configuration
AUR_URLS = [
    "https://aur.archlinux.org/{pkg_name}.git",
    "git://aur.archlinux.org/{pkg_name}.git"
]

# Build directory names
AUR_BUILD_DIR = "build_aur"

# GitHub repository for synchronization
GITHUB_REPO = "megvadulthangya/manjaro-awesome.git"

# Debug mode configuration - when True, bypass logger for critical build output
DEBUG_MODE = True