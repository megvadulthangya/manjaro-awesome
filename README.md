---

# Manjaro Awesome Nord Repository

Binary package repository for the Manjaro Awesome Nord project.
This repository provides all packages — including selected AUR builds — required for building and maintaining the Manjaro Awesome Nord ISO image.

Repository artifacts are hosted on the `gh-pages` branch and served through GitHub Pages.

---

## Repository URL

```
https://megvadulthangya.github.io/manjaro-awesome/
```

Source repository:

```
https://github.com/megvadulthangya/manjaro-awesome
```

---

## Usage

### 1. Add the repository (safe one-line setup)

Run the following command to create the include file and register the repository without overwriting existing settings:

```bash
sudo tee /etc/pacman.d/manjaro-awesome >/dev/null <<'EOF' && \
sudo grep -qxF 'Include = /etc/pacman.d/manjaro-awesome' /etc/pacman.conf || \
echo 'Include = /etc/pacman.d/manjaro-awesome' | sudo tee -a /etc/pacman.conf >/dev/null

[manjaro-awesome]
SigLevel = Optional TrustAll

# 1. gyors mirror – GitHub Pages (100MB alatti csomagok)
Server = https://megvadulthangya.github.io/manjaro-awesome/

# 2. teljes mirror – Oracle szerver (MINDEN csomag, 100MB felett is)
Server = https://repo.gshoots.hu/manjaro-awesome/

EOF
```

### 2. Refresh package databases

```bash
sudo pacman -Syy
```

### 3. Install packages

Example:

```bash
sudo pacman -S awesome-git awesome-rofi nordic-backgrounds nordzy-icon-theme
```

---

## Included Content

This repository contains:

* **Custom AwesomeWM-related packages**
* **Nord theme packages** (icons, GTK themes, wallpapers)
* **Prebuilt AUR packages** required for the Manjaro Awesome Nord ISO
* **Supplementary utilities** supporting AwesomeWM workflows

A non-exhaustive set of components includes (examples only):

* AwesomeWM builds (stable / git)
* AwesomeWM themes (copycats, freedesktop integration, lain)
* Nordic/Nordzy themes and wallpapers
* GSConnect, Grayjay, Tilix-git, QOwnNotes, Tamzen font, and others

The repo is intended to serve as the complete binary dependency set for ISO building, so package listings may evolve over time.

---

## Build & Deployment Schedule

Binary packages are rebuilt and published to the `gh-pages` branch:

* **weekly**, and
* on manual triggers (e.g. when dependencies or PKGBUILDs change).

This guarantees a stable and predictable build environment for ISO generation without daily rebuild overhead.

---

## Notes

* All `.pkg.tar.zst`, `.db`, and `.files` artifacts are stored on the `gh-pages` branch.
* The main branch contains PKGBUILDs and build scripts.
* The repository is compatible with `pacman` and `manjaro-tools` ISO building workflows.

---
