"""
Configuration file for Manjaro Package Builder
=================================================================================
PURPOSE: Centralized configuration for the package builder system.
         This file contains settings that control build behavior, timeouts,
         and special dependency mappings.

USAGE: Imported by builder.py to get configuration values.
       Environment variables can override these defaults.

ORGANIZATION:
1. Repository configuration
2. SSH and Git configuration  
3. Build timeouts
4. Special dependency mappings
5. Required build tools
"""

# ==============================================================================
# 1. REPOSITORY CONFIGURATION
# ==============================================================================

# REPO_DB_NAME: Name of the repository database file
# This appears in /etc/pacman.conf as [repo-name] and in filenames as repo-name.db.tar.gz
# Can be overridden by REPO_NAME environment variable
REPO_DB_NAME = "manjaro-awesome"  # Default, can be overridden by env

# OUTPUT_DIR: Directory where built packages are stored locally before upload
# Relative to repository root
OUTPUT_DIR = "built_packages"

# BUILD_TRACKING_DIR: Directory for tracking build state across runs
# Used to determine which packages need rebuilding
BUILD_TRACKING_DIR = ".buildtracking"

# ==============================================================================
# 2. SSH AND GIT CONFIGURATION
# ==============================================================================

# SSH_REPO_URL: Git repository URL for SSH-based operations
# Used for PKGBUILD synchronization feature (hokibot)
# Format: git@github.com:username/repository.git
SSH_REPO_URL = "git@github.com:megvadulthangya/manjaro-awesome.git"

# ==============================================================================
# 3. BUILD TIMEOUTS (seconds)
# ==============================================================================
# Different packages require different build times. These timeouts prevent
# the builder from hanging indefinitely on slow builds.

MAKEPKG_TIMEOUT = {
    "default": 3600,        # 1 hour for normal packages
    "large_packages": 7200, # 2 hours for large packages (gtk, qt, chromium)
    "simplescreenrecorder": 5400,  # 1.5 hours for this specific package
}

# ==============================================================================
# 4. SPECIAL DEPENDENCY MAPPINGS
# ==============================================================================
# Some packages don't list all their dependencies correctly in PKGBUILD,
# or need extra dependencies that aren't obvious. This dictionary maps
# package names to additional dependencies that should be installed.

SPECIAL_DEPENDENCIES = {
    "gtk2": ["gtk-doc", "docbook-xsl", "libxslt", "gobject-introspection"],
    "awesome-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "awesome-freedesktop-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "lain-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "simplescreenrecorder": ["jack2"],  # Convert jack to jack2 (Arch naming)
}

# ==============================================================================
# 5. REQUIRED BUILD TOOLS
# ==============================================================================
# List of build tools that should be present in the system.
# The builder will check for these and install them if missing.

REQUIRED_BUILD_TOOLS = [
    "make",      # GNU make - build automation
    "gcc",       # GNU Compiler Collection - C/C++ compiler
    "pkg-config", # Library configuration tool
    "autoconf",  # Generate configure scripts
    "automake",  # Makefile generator
    "libtool",   # Library building helper
    "cmake",     # Cross-platform build system
    "meson",     # Modern build system
    "ninja",     # Fast build system (used by meson)
    "patch",     # Apply patch files
]