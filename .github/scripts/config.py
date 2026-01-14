"""
Configuration file for Manjaro Package Builder
"""

# Repository configuration
REPO_DB_NAME = "manjaro-awesome"  # Default, can be overridden by env
OUTPUT_DIR = "built_packages"
BUILD_TRACKING_DIR = ".buildtracking"

# SSH and Git configuration
SSH_REPO_URL = "git@github.com:megvadulthangya/manjaro-awesome.git"

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