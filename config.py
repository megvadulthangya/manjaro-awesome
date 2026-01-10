"""
Configuration file for Manjaro Package Builder
"""

# Repository configuration
REPO_DB_NAME = "manjaro-awesome"
OUTPUT_DIR = "built_packages"
BUILD_TRACKING_DIR = ".buildtracking"

# SSH and Git configuration
SSH_REPO_URL = "git@github.com:megvadulthangya/manjaro-awesome.git"

# Build options
MAKEPKG_TIMEOUT = {
    "default": 3600,  # 1 óra
    "large_packages": 7200,  # 2 óra (gtk, qt, chromium stb.)
    "simplescreenrecorder": 5400,  # 1.5 óra
}

# Special dependency mappings
SPECIAL_DEPENDENCIES = {
    "gtk2": ["gtk-doc", "docbook-xsl", "libxslt", "gobject-introspection"],
    "awesome-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "awesome-freedesktop-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "lain-git": ["lua", "lgi", "imagemagick", "asciidoc"],
    "simplescreenrecorder": ["jack2"],  # jack -> jack2 konverzió
}

# Provider preferences (for interactive prompts)
PROVIDER_PREFERENCES = {
    "jack": "jack2",  # Mindig jack2-t válasszuk
}

# Build tool checks
REQUIRED_BUILD_TOOLS = [
    "make", "gcc", "pkg-config", "autoconf", "automake", 
    "libtool", "cmake", "meson", "ninja"
]