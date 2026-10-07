# Maintainer: Bernhard Landauer <bernhard[at]manjaro[dot]org>
# Maintainer: Philip Müller <philm[at]manjaro[dot]org>
# Contributor: Gerd Röthig (DAC24)
# Maintainer : Thomas Baechler <thomas@archlinux.org>
# Contributor: Alonso Rodriguez <alonsorodi20 (at) gmail (dot) com>
# Contributor: Sven-Hendrik Haase <sh@lutzhaase.com>
# Contributor: Felix Yan <felixonmars@archlinux.org>
# Contributor: loqs
# Contributor: Dede Dindin Qudsy <xtrymind+gmail+com>
# Contributor: Ike Devolder <ike.devolder+gmail+com>

_linuxprefix=linux612-rt

pkgname="${_linuxprefix}-nvidia-390xx"
pkgver=390.157
pkgrel=22
pkgdesc="NVIDIA kernel modules for ${_linuxprefix}"
arch=('x86_64')
url="https://www.nvidia.com/"
license=('custom')
groups=("${_linuxprefix}-extramodules")
depends=("${_linuxprefix}" "nvidia-utils=${pkgver}" 'libglvnd')
makedepends=("${_linuxprefix}-headers" "nvidia-dkms=$pkgver")
provides=("nvidia=${pkgver}" 'NVIDIA-MODULE')
options=(!strip)

build() {
    _kernver="$(cat /usr/src/${_linuxprefix}/version)"

    export IGNORE_PREEMPT_RT_PRESENCE=1
    fakeroot dkms build --dkmstree "${srcdir}" -m nvidia/${pkgver} -k ${_kernver}
}

package() {
    _kernver="$(cat /usr/src/${_linuxprefix}/version)"

    install -Dt "${pkgdir}/usr/lib/modules/${_kernver}/extramodules" -m644 nvidia/${pkgver}/${_kernver}/${CARCH}/module/*.ko.zst

    # compress each module individually
    find "$pkgdir" -name '*.ko' -exec zstd --rm -19 {} +

    install -Dm644 /usr/share/licenses/nvidia-390xx-dkms/LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
}
