#!/usr/bin/env python3
import os
import yaml
import sys
import requests
from datetime import datetime

CONFIG_FILE = "projects.yaml"

def get_latest_commit(repo, branch="main"):
    """Get latest commit hash from GitHub"""
    try:
        url = f"https://api.github.com/repos/{repo}/commits/{branch}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()['sha'][:7]
    except:
        pass
    return "unknown"

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 generate-single-pkgbuild.py <package-name>")
        sys.exit(1)
    
    pkgname = sys.argv[1]
    
    # Load config
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        sys.exit(1)
    
    # Find the project
    project = None
    for p in config.get('custom_packages', []):
        if p['name'] == pkgname:
            project = p
            break
    
    if not project:
        print(f"Error: Package {pkgname} not found in config")
        sys.exit(1)
    
    repo = project['repo']
    branch = project.get('branch', 'main')
    repo_name = repo.split('/')[-1]
    
    # Get version
    commit_hash = get_latest_commit(repo, branch)
    date_str = datetime.now().strftime("%Y%m%d")
    pkgver = f"{date_str}.{commit_hash}"
    
    # Generate PKGBUILD
    pkgbuild = f"""# Maintainer: Manjaro Awesome Nord
pkgname={pkgname}
pkgver={pkgver}
pkgrel=1
pkgdesc="{project['description']}"
arch=('any')
url="https://github.com/{repo}"
license=('{project.get('license', 'MIT')}')

source=("https://github.com/{repo}/archive/refs/heads/{branch}.tar.gz")
sha256sums=('SKIP')

package() {{
  cd "${{srcdir}}/{repo_name}-{branch}"
"""
    
    # Add install steps
    for step in project.get('install_steps', []):
        if step['type'] == 'copy':
            src = step['source']
            dest = step['destination']
            
            if dest.startswith('/etc/skel'):
                pkg_dir = dest.replace('/etc/skel', '$pkgdir/etc/skel')
            elif dest.startswith('/usr'):
                pkg_dir = f"$pkgdir{dest}"
            else:
                pkg_dir = f"$pkgdir/usr/share/{pkgname}"
            
            pkgbuild += f'  install -dm755 "{pkg_dir}"\n'
            pkgbuild += f'  cp -r {src} "{pkg_dir}/"\n'
            
        elif step['type'] == 'command':
            pkgbuild += f"  {step['command']}\n"
    
    pkgbuild += "}\n"
    
    # Write PKGBUILD
    pkg_dir = f"packages/{pkgname}"
    os.makedirs(pkg_dir, exist_ok=True)
    
    with open(f"{pkg_dir}/PKGBUILD", 'w') as f:
        f.write(pkgbuild)
    
    print(f"Generated PKGBUILD for {pkgname}")

if __name__ == "__main__":
    main()