"""
Package definitions for Manjaro Package Builder
=================================================================================
PURPOSE: Defines which packages to build and their categorization.
         This is the main package list that the builder processes.

ORGANIZATION:
1. LOCAL_PACKAGES: Packages maintained in this repository (have PKGBUILD here)
2. AUR_PACKAGES: Packages from Arch User Repository (cloned during build)
3. PACKAGE_CATEGORIES: Optional grouping for organizational purposes

NOTE: Packages are built in the order listed here.
      Dependencies between packages in the same list are not automatically handled.
"""

# ==============================================================================
# 1. LOCAL PACKAGES (from our repository)
# ==============================================================================
# These packages have PKGBUILD files in subdirectories of this repository.
# The builder will look for PKGBUILD in ./package-name/ directory.

LOCAL_PACKAGES = [
    "gghelper",                      # Game mode helper utility
    "gtk2",                          # GTK+ 2 graphical toolkit
    "awesome-freedesktop-git",       # Awesome WM freedesktop integration
    "lain-git",                      # Layout library for Awesome WM
    "awesome-rofi",                  # Rofi integration for Awesome WM
    "awesome-git",                   # Awesome Window Manager (git version)
    "tilix-git",                     # Tiling terminal emulator
    "nordic-backgrounds",            # Nordic theme wallpapers
    "awesome-copycats-manjaro",      # Awesome WM configurations
    "i3lock-fancy-git",              # Fancy i3lock screen locker
    "ttf-font-awesome-5",            # Font Awesome 5 icon font
    "nvidia-driver-assistant",       # NVIDIA driver management tool
    "grayjay-bin"                    # Universal media player
]

# ==============================================================================
# 2. AUR PACKAGES (from Arch User Repository)
# ==============================================================================
# These packages are cloned from AUR during build process.
# The builder uses 'yay' or direct git clone to get these packages.

AUR_PACKAGES = [
    "libinput-gestures",             # Touchpad gesture recognition
    "gtkd",                          # D language bindings for GTK
    "qt5-styleplugins",              # Additional Qt5 style plugins
    "urxvt-resize-font-git",         # URxvt font resizing plugin
    "i3lock-color",                  # Colored i3lock fork
    "raw-thumbnailer",               # RAW image thumbnailer
    "gsconnect",                     # KDE Connect implementation for GNOME
    "tamzen-font",                   # Tamzen bitmap font
    "betterlockscreen",              # Improved lock screen
    "nordic-theme",                  # Nordic theme for GTK
    "nordic-darker-theme",           # Darker variant of Nordic theme
    "geany-nord-theme",              # Nord theme for Geany editor
    "nordzy-icon-theme",             # Nord-inspired icon theme
    "oh-my-posh-bin",                # Prompt theme engine
    "fish-done",                     # Fish shell notifications
    "find-the-command",              # Command suggestion tool
    "p7zip-gui",                     # GUI for 7-zip archive tool
    "qownnotes",                     # Note-taking application
    "xorg-font-utils",               # X.org font utilities
    "xnviewmp",                      # Image viewer and converter
    "simplescreenrecorder",          # Screen recording software
    "gtkhash-thunar",                # Thunar integration for gtkhash
    "a4tech-bloody-driver-git",      # A4tech Bloody mouse driver
    "nordic-bluish-accent-theme",    # Nordic theme with bluish accent
    "nordic-bluish-accent-standard-buttons-theme",  # With standard buttons
    "nordic-polar-standard-buttons-theme",         # Polar variant
    "nordic-standard-buttons-theme",               # Standard buttons variant
    "nordic-darker-standard-buttons-theme"         # Darker with standard buttons
]

# ==============================================================================
# 3. OPTIONAL PACKAGE CATEGORIES
# ==============================================================================
# Organizational grouping of packages by function/purpose.
# Not used by builder.py directly, but useful for documentation and reporting.

PACKAGE_CATEGORIES = {
    "desktop": ["awesome-git", "awesome-freedesktop-git", "lain-git", "awesome-rofi"],
    "themes": ["nordic-theme", "nordic-darker-theme", "nordic-bluish-accent-theme"],
    "fonts": ["tamzen-font", "ttf-font-awesome-5"],
    "tools": ["libinput-gestures", "betterlockscreen", "simplescreenrecorder"],
    "drivers": ["nvidia-driver-assistant", "a4tech-bloody-driver-git"]
}