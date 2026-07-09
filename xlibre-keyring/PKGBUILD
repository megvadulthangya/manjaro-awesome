# Maintainer: XLibre Team <your@email>
# Contributor: Gyöngyösi Gábor <gabor at gshoots dot hu>
# Contributor: Philip Müller <philm[at]manjaro[dot]org>
# Contributor: Bernhard Landauer <bernhard[at]manjaro[dot]org>
# This PKGBUILD provides the GPG keys for the XLibre xserver repositories.
#
# The two .asc files are included as sources and verified via checksums.
# The keyring xlibre.gpg is built in prepare() using the Makefile update target,
# which first tries to import the local .asc files and falls back to downloading
# from primary URLs -> keyserver.ubuntu.com -> keys.openpgp.org.
#
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

# Source files: Makefile, trusted list, revoked list, and the actual key material
source=('Makefile'
        'xlibre-trusted'
        'xlibre-revoked'
        'xlibre-archlinux.asc'
        'xlibre-manjarolinux.asc')
# The checksums below must be updated after the .asc files have been downloaded.
# To generate: sha256sum xlibre-archlinux.asc xlibre-manjarolinux.asc
sha256sums=('SKIP'
            'SKIP'
            'SKIP'
            'SKIP'
            'SKIP')

prepare() {
  # Generate the xlibre.gpg keyring using the Makefile update target.
  # This will import the provided .asc files (if present) or download
  # the keys using the defined fallback methods.
  cd "$srcdir"
  make update
}

package() {
  # Install the keyring files into /usr/share/pacman/keyrings/
  make DESTDIR="${pkgdir}" install
}