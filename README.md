---

# Manjaro Awesome Nord Repository

Automated package repository for Manjaro Linux, providing AwesomeWM configurations, Nord-themed assets, and related enhancements.

This repository delivers curated AwesomeWM components and Nord-styled packages with continuous automated builds.

---

## Usage

### 1. Add the repository (one-line safe command)

Run the following single command to create the include file and register the repository safely without overwriting any existing configuration:

```bash
sudo tee /etc/pacman.d/manjaro-awesome >/dev/null <<'EOF' && \
sudo grep -qxF 'Include = /etc/pacman.d/manjaro-awesome' /etc/pacman.conf || \
echo 'Include = /etc/pacman.d/manjaro-awesome' | sudo tee -a /etc/pacman.conf >/dev/null
[manjaro-awesome]
SigLevel = Optional TrustAll
Server = https://megvadulthangya.github.io/manjaro-awesome/
EOF
```

### 2. Refresh package databases

```bash
sudo pacman -Syy
```

### 3. Install packages

```bash
sudo pacman -S nordic-backgrounds awesome-rofi-themes awesome-copycats
```

---

## Included Packages

### Custom Packages

* nordic-backgrounds
* awesome-rofi-themes
* awesome-copycats

### AUR Packages (referenced or supported)

* raw-thumbnailer
* grayjay-bin
* gsconnect
* and others as needed

---

## Automated Builds

All repository packages are automatically built:

* daily, and
* on every push to the `main` branch.

This ensures up-to-date and reproducible package availability for Manjaro systems.

---
