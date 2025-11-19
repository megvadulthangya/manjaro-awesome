---

# Manjaro Awesome Nord Repository

Package repository for Manjaro Linux providing AwesomeWM configurations, Nord-themed assets, and small productivity enhancements.

All repository artifacts are published via the `gh-pages` branch and served through GitHub Pages.

---

## Repository Location

The built packages and repository metadata are hosted at:

```
https://megvadulthangya.github.io/manjaro-awesome/
```

Source code and build definitions are located in the main project repository:

```
https://github.com/megvadulthangya/manjaro-awesome
```

---

## Usage

### 1. Add the repository (safe one-line setup)

This command creates the include file and appends the pacman include reference only if missing:

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

### AUR Packages (referenced or supported only)

Examples:

* raw-thumbnailer
* grayjay-bin
* gsconnect

(Az AUR-os csomagok nincsenek feltöltve a repo-ba, csak ajánlások.)

---

## Build & Deployment Schedule

Repository packages are rebuilt and published to the `gh-pages` branch:

* **weekly**, and
* optionally on manual triggers (e.g., pushing changes to the packaging branch).

This ensures stable and predictable package availability without daily churn.

---

## Notes

* The repository uses GitHub Pages as a static pacman-compatible package host.
* All package metadata (`db`, `files`, `pkg.tar.zst`) resides in the `gh-pages` branch.
* The main branch contains packaging scripts, PKGBUILD files, and automation logic.

---
