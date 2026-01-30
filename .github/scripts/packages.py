"""
Package definitions for Manjaro Package Builder
"""

# LOCAL packages (from our repository)
LOCAL_PACKAGES = [
    "gghelper",
    "gtk2",
    "awesome-freedesktop-git",
    "lain-git",
    "awesome-rofi",
    "awesome-git",
    "awesome-welcome",
    "tilix-git",
    "nordic-backgrounds",
    "awesome-copycats-manjaro",
    "i3lock-fancy-git",
    "ttf-font-awesome-5",
    "nvidia-driver-assistant",
    "grayjay-bin"
]

# AUR packages (from Arch User Repository)
AUR_PACKAGES = [
    "libinput-gestures",
    "gtkd",
    "qt5-styleplugins",
    "urxvt-resize-font-git",
    "i3lock-color",
    "raw-thumbnailer",
    "gsconnect",
    "tamzen-font",
    "betterlockscreen",
    "nordic-theme",
    "nordic-darker-theme",
    "geany-nord-theme",
    "nordzy-icon-theme",
    "oh-my-posh-bin",
    "fish-done",
    "find-the-command",
    "p7zip-gui",
    "qownnotes",
    "xorg-font-utils",
    "xnviewmp",
    "simplescreenrecorder",
    "gtkhash-thunar",
    "a4tech-bloody-driver-git",
    "nordic-bluish-accent-theme",
    "nordic-bluish-accent-standard-buttons-theme",
    "nordic-polar-standard-buttons-theme",
    "nordic-standard-buttons-theme",
    "nordic-darker-standard-buttons-theme"
]

# Optionally, you can also define package groups or categories
PACKAGE_CATEGORIES = {
    "desktop": ["awesome-freedesktop-git", "lain-git", "awesome-rofi"],
    "themes": ["nordic-theme", "nordic-darker-theme", "nordic-bluish-accent-theme"],
    "fonts": ["tamzen-font", "ttf-font-awesome-5"],
    "tools": ["libinput-gestures", "betterlockscreen", "simplescreenrecorder"],
    "drivers": ["nvidia-driver-assistant", "a4tech-bloody-driver-git"]
}