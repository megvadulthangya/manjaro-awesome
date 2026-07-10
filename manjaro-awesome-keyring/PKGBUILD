# Maintainer: Gyöngyösi Gábor <gabor at gshoots dot hu>
# Contributor: Philip Müller <philm[at]manjaro[dot]org>
# Contributor: Bernhard Landauer <bernhard[at]manjaro[dot]org>
# Contributor: Pierre Schmitz <pierre@archlinux.de>

# Before building, generate manjaro-awesome.gpg with:
#   gpg --export --armor A9A569C8F797B6878E44C4F8FBF4AB57E9BB9D3C > manjaro-awesome.gpg

pkgname=manjaro-awesome-keyring
pkgver=20260117
pkgrel=1
pkgdesc="Manjaro Awesome PGP keyring"
arch=('any')
url="https://github.com/megvadulthangya/keyring/tree/manjaro-awesome"
license=('GPL-3.0-or-later')
depends=('pacman')
install="${pkgname}.install"
source=('Makefile'
        'manjaro-awesome.gpg'
        'manjaro-awesome-revoked'
        'manjaro-awsome-trusted')
sha256sums=('SKIP'
            'SKIP'
            'SKIP'
            'SKIP')

pkgver() {
  date +%Y%m%d
}

package() {
  make DESTDIR="${pkgdir}" install
}