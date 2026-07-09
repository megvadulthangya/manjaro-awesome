# Maintainer: XLibre Team <your@email>
# Contributor: Gyöngyösi Gábor <gabor at gshoots dot hu>
# Contributor: Philip Müller <philm[at]manjaro[dot]org>
# Contributor: Bernhard Landauer <bernhard[at]manjaro[dot]org>
# This PKGBUILD provides the GPG keys for the XLibre xserver repositories.
#
# The .asc key files are stored alongside this PKGBUILD (renamed to avoid
# makepkg treating them as detached signatures). Their integrity is
# verified via sha256sums. The Makefile prepares the combined keyring from them.
# Trusted and revoked key lists are maintained statically.

pkgname=xlibre-keyring
pkgver=20260709
pkgrel=1
pkgdesc="XLibre PGP keyring"
arch=('any')
url="https://github.com/xlibre/xlibre-keyring"
license=('GPL-3.0-or-later')
depends=('pacman')
install="${pkgname}.install"

source=('Makefile'
        'xlibre-trusted'
        'xlibre-revoked'
        'xlibre-archlinux-key.asc'
        'xlibre-manjarolinux-key.asc')
# IMPORTANT: Replace the SKIP entries with the actual SHA256 hashes of the .asc files.
# Run: sha256sum xlibre-archlinux-key.asc xlibre-manjarolinux-key.asc
sha256sums=('SKIP'
            'SKIP'
            'SKIP'
            'SKIP'   # <- replace with real hash
            'SKIP')  # <- replace with real hash

prepare() {
  # Generate the xlibre.gpg keyring from the local .asc files.
  cd "$srcdir"
  make update
}

package() {
  # Install the keyring files into /usr/share/pacman/keyrings/
  make DESTDIR="${pkgdir}" install
}