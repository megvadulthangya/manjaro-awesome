# Maintainer: Gyöngyösi Gábor <gabor at gshoots dot hu>
pkgname=awesome-updater
pkgver=0.1.0
pkgrel=1
pkgdesc="Manjaro-focused unattended system updater with kernel reboot handling"
arch=('any')
url="https://github.com/megvadulthangya/awesome-updater"
license=('MIT')
depends=(
    'bash'
    'coreutils'
    'inetutils'
    'kernel-modules-hook'
    'pacman'
    'systemd'
    'findutils'
    'gawk'
    'grep'
    'sed'
    'util-linux'
)
optdepends=(
    'git: AUR support when AUR_ENABLED=true'
    'base-devel: AUR support when AUR_ENABLED=true'
    'libnotify: GUI desktop notifications via notify-send'
)
makedepends=('git')
backup=('etc/system-update/config.conf')
install=awesome-updater.install

# VCS-style source. The application is obtained from a git repository,
# never from a downloaded archive. The URL is overridable through the
# AWOSME_UPDATER_VCS_URL environment variable so that local builds,
# GitHub CI, and the portable integration test can point makepkg at a
# local git repository (`file:///path/to/checkout`) without editing the
# PKGBUILD. The default is the canonical upstream repository.
: "${AWESOME_UPDATER_VCS_URL:=https://github.com/megvadulthangya/awesome-updater.git}"

source=("$pkgname::git+$AWESOME_UPDATER_VCS_URL")
sha256sums=('SKIP')

# Derive the package version from the cloned git revision. The count of
# commits ensures monotonic versioning for `pacman -U` upgrades; the
# short hash disambiguates builds that share a commit count.
pkgver() {
    cd "$srcdir/$pkgname"
    printf 'r%s.%s' \
        "$(git rev-list --count HEAD)" \
        "$(git rev-parse --short=8 HEAD)"
}

prepare() {
    cd "$srcdir/$pkgname"
    # Single-source the runtime version string from pkgver.
    sed -i "s/@VERSION@/$pkgver/g" system-update
}

build() {
    : # nothing to build
}

package() {
    cd "$srcdir/$pkgname"

    install -Dm755 system-update \
        "$pkgdir/usr/bin/system-update"

    install -Dm755 system-update-notify \
        "$pkgdir/usr/bin/system-update-notify"

    install -Dm644 profile.d/99-system-update.sh \
        "$pkgdir/etc/profile.d/99-system-update.sh"

    install -Dm644 config/config.conf \
        "$pkgdir/etc/system-update/config.conf"

    install -Dm644 systemd/awesome-updater@.service \
        "$pkgdir/usr/lib/systemd/system/awesome-updater@.service"

    install -Dm644 systemd/awesome-updater@.timer \
        "$pkgdir/usr/lib/systemd/system/awesome-updater@.timer"

    install -Dm644 man/system-update.1 \
        "$pkgdir/usr/share/man/man1/system-update.1"

    install -Dm644 man/system-update-notify.1 \
        "$pkgdir/usr/share/man/man1/system-update-notify.1"

    install -Dm644 README.md \
        "$pkgdir/usr/share/doc/$pkgname/README.md"

    install -Dm644 LICENSE \
        "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}