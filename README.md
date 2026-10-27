# Manjaro Awesome Respin — Nordic Themed

![Maintenance](https://img.shields.io/badge/Maintenance-Active-brightgreen)
[![Build](https://img.shields.io/github/actions/workflow/status/megvadulthangya/manjaro-awesome/manjaro-testing.yaml?label=build)](https://github.com/megvadulthangya/manjaro-awesome/actions/workflows/manjaro-testing.yaml)
[![Kernel watcher](https://img.shields.io/github/actions/workflow/status/megvadulthangya/manjaro-awesome/kernel-watcher.yaml?label=kernel%20watcher)](https://github.com/megvadulthangya/manjaro-awesome/actions/workflows/kernel-watcher.yaml)
![Platform](https://img.shields.io/badge/platform-Manjaro%20Linux-blue)
![License](https://img.shields.io/github/license/megvadulthangya/manjaro-awesome)

**Build infrastructure for the Manjaro Awesome Respin project.**

This repository holds the PKGBUILDs, patches, configuration, and CI/CD workflows that produce every binary package served to users of the Manjaro Awesome ISOs. Its output is published to the project's package repository at `repo.gshoots.hu`.

It is not the ISO download page and it is not an official Manjaro component.

---

## About the project

**Manjaro Awesome Respin** is an independent project providing Nordic-themed desktop respins based on Manjaro Linux, shipped in three editions (AwesomeWM, XFCE + Compiz, GNOME).

The project publishes updates, ISO announcements, and download links on Facebook:

**https://www.facebook.com/manjaroawesome**

It is not affiliated with, sponsored by, or endorsed by the official Manjaro project.

---

## What this repository is

This is the *upstream* — where packages get built. End users pull from `repo.gshoots.hu`, which this repository's CI populates.

The project's scope has grown beyond its name: the repository now builds the complete dependency set for all three desktop variants — not just AwesomeWM packages.

### Contents

| Path | Purpose |
|------|---------|
| `*/PKGBUILD` | Every package built for the ISOs (local packages and AUR clones) |
| `*/` supporting files | Per-package patches, configs, install hooks, sources |
| `.github/workflows/manjaro-testing.yaml` | Main build workflow |
| `.github/workflows/kernel-watcher.yaml` | Kernel module rebuilder |
| `.github/scripts/` | Modular Python build pipeline |
| `.build_tracking/` | Which kernel version each NVIDIA module was last built against |
| `.pending/` | In-flight `pkgrel` bumps, cleared after the corresponding build succeeds |

---

## The pipeline

Two workflows cooperate. Both share a GitHub Actions concurrency group so they never run at the same time.

### Main build — `manjaro-testing.yaml`

Triggers: daily at 03:00 UTC, on manual dispatch, and on push to `packages.py`, `config.py`, any `PKGBUILD`, or the workflows themselves.

Steps:

1. **Sync** — read the current VPS package state and mirror it locally
2. **Audit** — for each PKGBUILD, compare its version against the VPS
3. **Build** — makepkg only the outdated or missing packages
4. **Sign** — detached GPG signature per built package
5. **Database** — `repo-add` to regenerate the repository databases
6. **Stage** — upload new/modified files to `…/.staging/<run_id>/` on the VPS
7. **Verify** — confirm every expected file landed in staging
8. **Promote** — `mv` under a remote lock into the live directory
9. **Post-verify** — confirm every expected file is present in the live directory
10. **Prune** — remove outdated versions and orphan signatures (only when all prior steps succeeded)

Failed builds do not break the rest of the pipeline: each package is audited independently.

### Kernel watcher — `kernel-watcher.yaml`

Triggers: every 3 hours, on manual dispatch.

Steps:

1. **Discover** — find every PKGBUILD containing `_linuxprefix=` (NVIDIA kernel modules)
2. **Compare** — read `.build_tracking/<module>`, then query the current version of that kernel
3. **Bump** — if the kernel moved, increment `pkgrel`
4. **Push** — with a personal access token, so the resulting build trigger fires (bot-actor pushes are filtered out by the main workflow)
5. **Record** — after the follow-up build succeeds, the new kernel version is written to `.build_tracking/<module>` and the `.pending/<module>` marker is cleared

This loop is what keeps legacy NVIDIA kernel modules current when upstream kernels move — without users having to run DKMS locally on every machine.

---

## Building locally

The CI environment is a Manjaro `base-devel` container on the testing branch. To reproduce it:

- Manjaro Linux (testing branch for parity with CI)
- `python`, `python-yaml`, `git`, `curl`, `gnupg`
- `base-devel`, `pacman-contrib`
- SSH access to a destination VPS
- A GPG key for signing

The complete list of environment variables lives in `.github/workflows/manjaro-testing.yaml` and maps 1:1 to GitHub Actions secrets. At minimum:

- `VPS_USER`, `VPS_HOST`, `VPS_SSH_KEY` — VPS access
- `REMOTE_DIR`, `REPO_NAME`, `REPO_SERVER_URL` — where packages land
- `PACKAGER_ENV` — packager identity embedded in built packages
- `GPG_KEY_ID`, `GPG_PRIVATE_KEY` — package and repository signing (optional but recommended)

The kernel watcher additionally requires `LINK_PUSH_TOKEN` — a personal access token with `Contents: Read and write` and `Workflows: Read and write`, so its push triggers the main build workflow instead of being filtered as a bot push.

---

## License

See `LICENSE` at the repository root.

Individual PKGBUILDs, patches, and vendored sources are under their own respective licenses. Check each package directory before redistribution.
