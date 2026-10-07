# nvidia-340xx-utils

Manjaro/Arch packaging for the NVIDIA 340.108 legacy driver, built on top
of the Debian `340xx/main` patch workflow.

It is an independent Manjaro-oriented PKGBUILD that reuses the Debian
patchset and applies a small set of follow-up patches to extend kernel
module build support to recent Linux kernels (up to 7.3 at the time of
writing).

The packaging structure (PKGBUILD, `.install`, `.rules`, `mhwd-nvidia`,
etc.) is derived from the Manjaro `nvidia-390xx-utils` package.

## Status

The kernel module builds cleanly on the kernels listed below.

| Kernel   | Result |
|----------|--------|
| 6.1      | OK     |
| 6.1-rt   | OK     |
| 6.6      | OK     |
| 6.6-rt   | OK     |
| 6.12     | OK     |
| 6.12-rt  | OK     |
| 6.18     | OK     |
| 7.1      | OK     |
| 7.2      | OK     |
| 7.3      | OK     |

## Patch workflow

Patches are listed in `series.resolved` and applied in that order from
the `kernel/` directory using `patch -Np1`. The PKGBUILD `prepare()`
function iterates over the list and applies each patch in sequence.

The Debian-named patches keep their original names. The four follow-up
patches use descriptive names without numeric prefixes:

- `kernel-6.18-workqueue-flush.patch` – use
  `flush_workqueue(system_wq)` instead of the deprecated
  `flush_scheduled_work()`.
- `kernel-7.0-screen_info.patch` – use
  `sysfb_primary_display.screen` when `screen_info` was removed.
- `vma-lock-7.0-plus.patch` – handle the `__is_vma_write_locked()`
  signature change and the `VMA_LOCK_OFFSET` →
  `VM_REFCNT_EXCLUDE_READERS_FLAG` rename.
- `kernel-7.3-acpi.patch` – stub `nv_acpi_init()` / `nv_acpi_uninit()`
  on 7.3+ since `struct acpi_driver` was removed and its
  `platform_driver` replacement is GPL-only.

## Credits

This package contains traces of, summarises, and draws inspiration
from the work of many people.

**Andreas Beckmann** ([@anbe42](https://salsa.debian.org/anbe42)) –
Debian 340xx maintainer. The Debian patchset and the entire patch
workflow this repository is built on are his work.

**Joan Bruguera Micó** ([@joanbm](https://github.com/joanbm)) – his
470xx patchset is the origin of several patches in this repository,
which were ported down to 390 and then to 340.

**Oleh Nykyforchyn** ([@ONykyf](https://github.com/ONykyf)) –
Slackware build scripts, source of several VMA-lock ideas.

**Mark Wagie** ([@yochananmarqos](https://github.com/yochananmarqos)) –
guidance and patience throughout the project.

**Philip Müller** ([@hphilm](https://github.com/hphilm)) and the
**Manjaro team** – thanks for their work and for maintaining the
`nvidia-390xx-utils` package, whose PKGBUILD structure this repository
is based on. The `kernel-7.3-acpi.patch` was carried over to the
390xx branch from this work.

Thank you all.

## Notes

CVE fixes: only the open-source parts are being worked on. Attempting
to hunt them down. Work in progress.

## Disclaimer

This is an unofficial, community-maintained package. It is **not
endorsed by NVIDIA, Debian, or Manjaro**. It is provided as-is, without
warranty of any kind, express or implied. **The author is not
responsible for any damage, data loss, hardware failure, or any other
consequence arising from the use of this package.**

The 340xx driver series is in **legacy/EOL status**. It contains known
**security vulnerabilities** that will not be fixed upstream. Use it
only on systems that are not exposed to untrusted input, and only if
you understand the risks.

The package is intended for use with **Xorg** based servers only:
`xorg-xserver` (untested) or `xlibre-xserver-legacyabi`. Wayland and
other display servers are not supported.

Use at your own risk.
