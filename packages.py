"""
Package definitions for Manjaro Package Builder
"""

# LOCAL packages (from our repository)
LOCAL_PACKAGES = [
    "gghelper",
    "awesome-git"
]

# AUR packages (from Arch User Repository)
AUR_PACKAGES = [
]

# Optionally, you can also define package groups or categories
PACKAGE_CATEGORIES = {
    "desktop": ["awesome-git", "awesome-freedesktop-git", "lain-git", "awesome-rofi"],
    "themes": ["nordic-theme", "nordic-darker-theme", "nordic-bluish-accent-theme"],
    "fonts": ["tamzen-font", "ttf-font-awesome-5"],
    "tools": ["libinput-gestures", "betterlockscreen", "simplescreenrecorder"],
    "drivers": ["nvidia-driver-assistant", "a4tech-bloody-driver-git"]
}
