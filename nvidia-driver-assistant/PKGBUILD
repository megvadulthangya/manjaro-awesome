# Maintainer: Philip Müller <philm[at]manjaro[dot]org>
# Modified by: Gyöngyösi Gábor
# Enforce proprietary driver for Maxwell/Pascal/Volta GPUs
# per NVIDIA Open Kernel Module support policy

pkgname=nvidia-driver-assistant
# 1. VÁLTOZTATÁS: Megemeljük a verziót, hogy a tied frissebb legyen
pkgver=0.23.48.02
# 2. ÚJ VÁLTOZÓ: Ez tárolja az eredeti fájl verzióját a letöltéshez
_realver=0.23.48.01 

pkgrel=1
_pkgrel=1
pkgdesc="Detect and install the best NVIDIA driver packages for the system (Patched for Maxwell/Pascal)"
arch=('any')
url="http://www.nvidia.com/"
license=('MIT AND LicenseRef-custom')
depends=('python')

# 3. VÁLTOZTATÁS: A linkben kicseréljük ${pkgver}-t ${_realver}-re
source=("https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/${pkgname}_${_realver}-${_pkgrel}_all.deb"
        'show-driver'
        'manjaro.patch') # Ez a te v2-es patch fájlod legyen a mappában!

# 4. VÁLTOZTATÁS: A patch hash-ét frissíteni kell!
# Az első kettő marad a régi (az eredeti fájloké), a harmadikat cseréld ki a sajátodra!
sha256sums=('63b7eb75805530914f723213af8ec6070089d60782bece179dd6fc22caf914a9'
            'ba2de9ef5a7295b3127bef360a5da89cacaec7c7362e351b33177045bcf9e3f7'
            'efd0b696193e006d8eeebcea6812248258f7211eedc8b143927a38abbad04c9c') 
 

prepare() {
  # Itt használhatjuk az új pkgver-t mappavnévnek, nem gond
  mkdir -p "${pkgname}-${pkgver}"
  
  # Kicsomagoljuk az eredeti (régi verziós) deb fájlt
  bsdtar -xvf data.tar.xz -C "${pkgname}-${pkgver}"

  cd "${pkgname}-${pkgver}"
  # Ráhúzzuk a te javításodat
  patch -Np1 -i "${srcdir}/manjaro.patch"
}

package() {
  cd "${pkgname}-${pkgver}"
  install -Dm755 "usr/bin/${pkgname}" -t "${pkgdir}/usr/bin/"
  install -Dm644 "usr/share/${pkgname}/supported-gpus"/*.json -t \
    "${pkgdir}/usr/share/${pkgname}/supported-gpus/"
  install -Dm644 "usr/share/doc/${pkgname}"/{CONTRIBUTING.md,README.md} -t \
    "$pkgdir/usr/share/doc/${pkgname}/"
  install -Dm644 "usr/share/doc/${pkgname}/copyright" -t \
    "$pkgdir/usr/share/licenses/${pkgname}/"
  install -Dm644 "usr/share/${pkgname}/driver_eula/LICENSE" -t \
    "${pkgdir}/usr/share/${pkgname}/driver_eula/"
  ln -s "/usr/share/${pkgname}/driver_eula/LICENSE" \
    "$pkgdir/usr/share/licenses/${pkgname}"
  install -m755 "${srcdir}/show-driver" "${pkgdir}/usr/bin/nvidia-recommended-driver"
}
