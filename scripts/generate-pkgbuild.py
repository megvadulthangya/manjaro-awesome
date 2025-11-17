#!/usr/bin/env python3
import os
import yaml
import requests
from datetime import datetime
import sys

CONFIG_FILE = "projects.yaml"

def debug_log(message):
    print(f"DEBUG: {message}", file=sys.stderr)

def main():
    print("Starting PKGBUILD generation...")
    
    # Ellenőrizzük, hogy a fájl létezik-e
    if not os.path.exists(CONFIG_FILE):
        print(f"ERROR: {CONFIG_FILE} not found!")
        print("Current directory:", os.getcwd())
        print("Files in current directory:", os.listdir('.'))
        sys.exit(1)
    
    # Konfiguráció betöltése
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f)
        debug_log("Config loaded successfully")
    except Exception as e:
        print(f"ERROR loading config: {e}")
        sys.exit(1)
    
    custom_packages = config.get('custom_packages', [])
    debug_log(f"Found {len(custom_packages)} custom packages")
    
    # Töröljük és újra létrehozzuk a packages mappát
    if os.path.exists("packages"):
        import shutil
        shutil.rmtree("packages")
    os.makedirs("packages", exist_ok=True)
    
    for project in custom_packages:
        try:
            pkgname = project['name']
            repo = project['repo']
            branch = project.get('branch', 'main')
            
            debug_log(f"Processing {pkgname} from {repo}")
            
            # Repository név kinyerése
            repo_name = repo.split('/')[-1]
            
            # Egyszerű PKGBUILD generálás
            pkgbuild = f"""# Maintainer: Manjaro Awesome Nord
pkgname={pkgname}
pkgver=1.0.0
pkgrel=1
pkgdesc="{project['description']}"
arch=('any')
url="https://github.com/{repo}"
license=('{project.get('license', 'MIT')}')

source=("$pkgname-$pkgver.tar.gz::https://github.com/{repo}/archive/refs/heads/{branch}.tar.gz")
sha256sums=('SKIP')

package() {{
  cd "$srcdir/{repo_name}-{branch}"
"""
            
            # Install lépések hozzáadása
            for step in project.get('install_steps', []):
                if step['type'] == 'copy':
                    src = step['source']
                    dest = step['destination']
                    
                    if dest.startswith('/etc/skel'):
                        dest = dest.replace('/etc/skel', '$pkgdir/etc/skel', 1)
                    elif dest.startswith('/usr'):
                        dest = f"$pkgdir{dest}"
                    else:
                        dest = f"$pkgdir/usr/share/{pkgname}"
                        
                    pkgbuild += f'  install -dm755 "{dest}"\n'
                    pkgbuild += f'  cp -r {src} "{dest}/"\n'
                    
                elif step['type'] == 'command':
                    pkgbuild += f"  {step['command']}\n"
            
            pkgbuild += "}\n"
            
            pkg_dir = f"packages/{pkgname}"
            os.makedirs(pkg_dir, exist_ok=True)
            
            with open(f"{pkg_dir}/PKGBUILD", 'w') as f:
                f.write(pkgbuild)
            
            debug_log(f"Created PKGBUILD for {pkgname}")
            
        except Exception as e:
            print(f"ERROR with {project.get('name', 'unknown')}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print("PKGBUILD generation completed!")
    print("Generated packages:")
    for root, dirs, files in os.walk("packages"):
        for dir in dirs:
            print(f"  - {dir}")

if __name__ == "__main__":
    main()