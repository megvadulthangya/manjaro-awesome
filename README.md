# Manjaro Awesome Nord Distribution

Automated package repository for Manjaro Linux with AwesomeWM and Nord theme.

## Usage

Add this repository to your `/etc/pacman.conf`:


[manjaro-awesome]
SigLevel = Optional TrustAll
Server = https://<your-username>.github.io/manjaro-awesome/
Then update and install packages:


sudo pacman -Syu
sudo pacman -S nordic-backgrounds awesome-rofi-themes awesome-copycats
Included Packages
Custom Packages
nordic-backgrounds

awesome-rofi-themes

awesome-copycats

AUR Packages
raw-thumbnailer, grayjay-bin, gsconnect, etc.

Automated Builds
Packages are automatically built daily and on every push to main branch.

