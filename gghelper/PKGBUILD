# Maintainer: Gyöngyösi Gábor <gabor AT gshoots DOT hu>
pkgname=gghelper
pkgver=2.0.0
pkgrel=1
pkgdesc="Git workflow assistant with GitHub Actions conflict resolution"
arch=('any')
url="https://github.com/megvadulthangya/manjaro-awesome"
license=('MIT')
depends=('python' 'git')
makedepends=('git')
source=("gghelper.py"
        "gghelper"
        "README.md"
        "LICENSE")
sha256sums=('SKIP' 'SKIP' 'SKIP' 'SKIP')

package() {
  # Create directories
  install -dm755 "$pkgdir/usr/bin"
  install -dm755 "$pkgdir/usr/share/gghelper"
  install -dm755 "$pkgdir/usr/share/licenses/$pkgname"
  install -dm755 "$pkgdir/usr/share/doc/$pkgname"
  
  # Install main script
  install -Dm755 "$srcdir/gghelper.py" "$pkgdir/usr/share/gghelper/gghelper.py"
  
  # Install bash wrapper
  install -Dm755 "$srcdir/gghelper" "$pkgdir/usr/bin/gghelper"
  
  # Install documentation
  install -Dm644 "$srcdir/README.md" "$pkgdir/usr/share/doc/$pkgname/README.md"
  
  # Install license
  install -Dm644 "$srcdir/LICENSE" "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  
  # Create symlink for direct Python execution (optional)
  ln -sf "/usr/share/gghelper/gghelper.py" "$pkgdir/usr/bin/gghelper.py"
}
