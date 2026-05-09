# Maintainer: Gyöngyösi Gábor <gabor at gshoots dot hu>
pkgname=awesome-welcome-ai
_appname=awesome-welcome
_pkgmod=awesome_welcome
pkgver=r2.c2f8b02
pkgrel=1
pkgdesc="Welcome screen & AI Services Manager for Manjaro Awesome Respin AI-ML"
arch=('any')
url="https://github.com/megvadulthangya/awesome-welcome"
license=('MIT')
depends=('python' 'gtk3' 'python-gobject')
optdepends=('python-textual: TUI mode support')
makedepends=('git' 'python')
conflicts=('awesome-welcome')
source=("git+https://github.com/megvadulthangya/awesome-welcome.git#branch=AI-ML")
sha256sums=('SKIP')

pkgver() {
  cd "${srcdir}/${_appname}"
  printf "r%s.%s" "$(git rev-list --count HEAD)" "$(git rev-parse --short HEAD)"
}

prepare() {
  cd "${srcdir}/${_appname}"

  # Fix repository URL in Python package config (was pointing at iso-profiles)
  sed -i "s|https://github.com/megvadulthangya/iso-profiles|https://github.com/megvadulthangya/awesome-welcome|" ${_pkgmod}/config.py
}

package() {
  cd "${srcdir}/${_appname}"

  # Resolve Python site-packages path on the build host
  local _site_packages
  _site_packages=$(python -c "import site; print(site.getsitepackages()[0])")

  # Install thin launcher to /usr/bin
  install -Dm755 ${_appname} "${pkgdir}/usr/bin/${_appname}"

  # Install awesome_welcome/ Python package to site-packages
  install -d "${pkgdir}${_site_packages}/${_pkgmod}"
  cp -r ${_pkgmod}/. "${pkgdir}${_site_packages}/${_pkgmod}/"
  # Normalise permissions (cp may inherit odd modes)
  find "${pkgdir}${_site_packages}/${_pkgmod}" -type d -exec chmod 755 {} \;
  find "${pkgdir}${_site_packages}/${_pkgmod}" -type f -exec chmod 644 {} \;

  # Install desktop file to applications directory
  install -Dm644 ${_appname}.desktop "${pkgdir}/usr/share/applications/${_appname}.desktop"

  # Install desktop file to skel autostart directory
  install -Dm644 ${_appname}.desktop "${pkgdir}/etc/skel/.config/autostart/${_appname}.desktop"

  # Install LICENSE file
  if [ -f LICENSE ]; then
    install -Dm644 LICENSE "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
  elif [ -f COPYING ]; then
    install -Dm644 COPYING "${pkgdir}/usr/share/licenses/${pkgname}/LICENSE"
  else
    echo "WARNING: No license file found in source repository"
  fi

  # Install README.md
  if [ -f README.md ]; then
    install -Dm644 README.md "${pkgdir}/usr/share/doc/${pkgname}/README.md"
  fi
}
