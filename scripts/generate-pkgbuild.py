#!/usr/bin/env python3
import os
import yaml
import requests
from datetime import datetime
import sys

CONFIG_FILE = "projects.yaml"

def get_latest_commit(repo, branch="main"):
    """Automatikusan lekéri a legújabb commit hash-t"""
    try:
        url = f"https://api.github.com/repos/{repo}/commits/{branch}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()['sha'][:7]
        else:
            print(f"Warning: Could not fetch commit for {repo} ({response.status_code})")
    except Exception as e:
        print(f"Error fetching commit for {repo}: {e}")
    
    return "unknown"

def generate_pkgbuild(project_config):
    """Generál PKGBUILD fájlt a konfiguráció alapján"""
    
    pkgname = project_config['name']
    repo = project_config['repo']
    branch = project_config.get('branch', 'main')
    commit_hash = get_latest_commit(repo, branch)
    
    # Verzió formátum: dátum.commit_hash
    date_str = datetime.now().strftime("%Y%m%d")
    pkgver = f"{date_str}.{commit_hash}"
    
    # Alap PKGBUILD struktúra
    pkgbuild = f"""# Maintainer: {project_config.get('maintainer', 'Manjaro Awesome Nord')}
pkgname={pkgname}
pkgver={pkgver}
pkgrel=1
pkgdesc="{project_config['description']}"
arch=('any')
url="https://github.com/{repo}"
license=('{project_config.get('license', 'MIT')}')
"""

    # Függőségek
    if 'depends' in project_config and project_config['depends']:
        depends_str = ' '.join([f"'{d}'" for d in project_config['depends']])
        pkgbuild += f"depends=({depends_str})\n"
    
    # Manjaro specifikus beállítások
    pkgbuild += """# Manjaro specific
options=('!strip' '!emptydirs')
"""

    # Source - branch specifikus letöltés
    pkgbuild += f"""source=("$pkgname-$pkgver.tar.gz::https://github.com/{repo}/archive/refs/heads/{branch}.tar.gz")
sha256sums=('SKIP')

package() {{
  cd "$srcdir/{pkgname}-{branch}"
"""
    
    # Install lépések
    for step in project_config.get('install_steps', []):
        if step['type'] == 'copy':
            src = step['source']
            dest = step['destination']
            
            # Ha a cél /etc/skel, akkor a $pkgdir/etc/skel-be másolunk
            if dest.startswith('/etc/skel'):
                dest = dest.replace('/etc/skel', '$pkgdir/etc/skel', 1)
            elif dest.startswith('/usr'):
                dest = f"$pkgdir{dest}"
            else:
                # Ha nem abszolút útvonal, akkor warning
                print(f"Warning: Destination '{dest}' is not absolute path in {pkgname}")
                dest = f"$pkgdir/usr/share/{pkgname}"
                
            # Könyvtár létrehozása és másolás
            pkgbuild += f'  install -dm755 "{dest}"\n'
            
            # Wildcard kezelése
            if '*' in src:
                pkgbuild += f'  cp -r {src} "{dest}/"\n'
            else:
                pkgbuild += f'  cp -r {src} "{dest}/"\n'
            
        elif step['type'] == 'command':
            # System parancsok (pl. fc-cache) a package() függvényben
            pkgbuild += f"  {step['command']}\n"
    
    pkgbuild += "}\n"
    
    return pkgbuild

def generate_srcinfo(project_config, pkgver):
    """Generál .SRCINFO fájlt"""
    pkgname = project_config['name']
    
    srcinfo = f"""pkgbase = {pkgname}
\tpkgdesc = {project_config['description']}
\tpkgver = {pkgver}
\tpkgrel = 1
\turl = https://github.com/{project_config['repo']}
\tarch = any
\tlicense = {project_config.get('license', 'MIT')}
"""
    
    if 'depends' in project_config and project_config['depends']:
        for dep in project_config['depends']:
            srcinfo += f"\tdepends = {dep}\n"
    
    return srcinfo

def load_config():
    """Betölti a konfigurációs YAML fájlt"""
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: {CONFIG_FILE} not found!")
        sys.exit(1)
    
    with open(CONFIG_FILE, 'r') as f:
        try:
            return yaml.safe_load(f)
        except yaml.YAMLError as e:
            print(f"Error parsing {CONFIG_FILE}: {e}")
            sys.exit(1)

def main():
    print("Starting PKGBUILD generation...")
    
    config = load_config()
    
    # Csak egyéni csomagok generálása
    custom_packages = config.get('custom_packages', [])
    
    if not custom_packages:
        print("No custom packages found in config!")
        return
    
    print(f"Found {len(custom_packages)} custom packages to generate")
    
    for project in custom_packages:
        pkgname = project['name']
        print(f"Generating PKGBUILD for {pkgname}...")
        
        try:
            pkgbuild_content = generate_pkgbuild(project)
            pkg_dir = f"packages/{pkgname}"
            
            # Mappa létrehozása
            os.makedirs(pkg_dir, exist_ok=True)
            
            # PKGBUILD írása
            with open(f"{pkg_dir}/PKGBUILD", 'w') as f:
                f.write(pkgbuild_content)
            
            # .SRCINFO generálása
            pkgver = pkgbuild_content.split('pkgver=')[1].split()[0]
            srcinfo_content = generate_srcinfo(project, pkgver)
            
            with open(f"{pkg_dir}/.SRCINFO", 'w') as f:
                f.write(srcinfo_content)
            
            print(f"✓ Successfully generated PKGBUILD for {pkgname}")
            
        except Exception as e:
            print(f"✗ Error generating PKGBUILD for {pkgname}: {e}")
            continue
    
    # AUR csomagok listázása
    aur_packages = config.get('aur_packages', [])
    if aur_packages:
        print(f"\nFound {len(aur_packages)} AUR packages (will be built directly from AUR)")
        for aur_pkg in aur_packages:
            print(f"  - {aur_pkg}")
    
    print("\nPKGBUILD generation completed!")

if __name__ == "__main__":
    main()