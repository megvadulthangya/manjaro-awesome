#!/bin/bash
set -e

# --- CSOMAGOK LISTÁJA ---
LOCAL_PACKAGES=(
    "awesome-rofi"
    "nordic-backgrounds"
    "awesome-copycats-manjaro"
    "ttf-font-awesome-5"
    "i3lock-fancy-git"
)

AUR_PACKAGES=(
    "raw-thumbnailer"
    "grayjay-bin"
    "gsconnect"
    "lain-git"
    "awesome-git"
    "awesome-freedesktop-git"
    "tilix-git"
    "tamzen-font"
    "betterlockscreen"
    "nordic-theme"
    "nordic-darker-theme"
    "geany-nord-theme"
    "nordzy-icon-theme"
    "oh-my-posh-bin"
    "fish-done"
    "find-the-command"
    "p7zip-gui"
    "qownnotes"
    "xorg-font-utils"
    "xnviewmp"
    "simplescreenrecorder"
    "gtkhash-thunar"
    "a4tech-bloody-driver-git"
    "nordic-bluish-accent-theme"
    "nordic-bluish-accent-standard-buttons-theme"
    "nordic-polar-standard-buttons-theme"
    "nordic-standard-buttons-theme"
    "nordic-darker-standard-buttons-theme"
)

REMOTE_DIR="/var/www/repo"
REPO_DB_NAME="manjaro-awesome"
OUTPUT_DIR="./built_packages"

mkdir -p "$OUTPUT_DIR"

# --- GIT KONFIGURÁCIÓ (Hogy tudjon pusholni) ---
git config --global user.name "GitHub Action Bot"
git config --global user.email "action@github.com"
# Biztonsági beállítás, hogy a CI tudja írni a mappát
git config --global --add safe.directory '*'

# Színes log
log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_succ() { echo -e "\e[32m[OK]\e[0m $1"; }
log_skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }

# 1. YAY TELEPÍTÉSE
if ! command -v yay &> /dev/null; then
    log_info "Yay telepítése..."
    cd /tmp
    git clone https://aur.archlinux.org/yay.git
    cd yay
    makepkg -si --noconfirm
    cd - > /dev/null
fi

# 2. SZERVER FÁJLLISTA LEKÉRÉSE
log_info "Szerver tartalmának lekérdezése..."
ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST "ls -1 $REMOTE_DIR" > remote_files.txt

# Segédfüggvény: Ellenőrzi, hogy a PONTOS fájlnév ott van-e
is_on_server() {
    local pkgname="$1"
    local version="$2"
    if grep -q "^${pkgname}-${version}-" remote_files.txt; then
        return 0
    else
        return 1
    fi
}

build_package() {
    local pkg="$1"
    local is_aur="$2"
    
    if [ "$is_aur" == "true" ]; then
        if [ -d "$pkg" ]; then rm -rf "$pkg"; fi
        git clone "https://aur.archlinux.org/$pkg.git"
        cd "$pkg"
    else
        if [ ! -d "$pkg" ]; then log_info "Hiba: $pkg mappa nincs meg!"; return; fi
        cd "$pkg"
    fi

    # --- VERZIÓ KIDERÍTÉSE ---
    log_info "Verzió ellenőrzése: $pkg ..."
    # Letöltjük a forrást, hogy a pkgver() frissüljön (főleg -git csomagoknál fontos)
    makepkg -o --noconfirm > /dev/null 2>&1 || true 

    makepkg --printsrcinfo > .SRCINFO
    full_ver=$(grep "pkgver =" .SRCINFO | head -1 | awk '{print $3}')
    rel_ver=$(grep "pkgrel =" .SRCINFO | head -1 | awk '{print $3}')
    
    # Fallback, ha az SRCINFO üres lenne
    if [ -z "$full_ver" ]; then
        source PKGBUILD
        full_ver=$pkgver
        rel_ver=$pkgrel
    fi

    local current_version="${full_ver}-${rel_ver}"

    # --- ELLENŐRZÉS: Kell-e építeni? ---
    if is_on_server "$pkg" "$current_version"; then
        log_skip "$pkg ($current_version) -> MÁR A SZERVEREN VAN."
        if [ "$is_aur" == "true" ]; then cd .. && rm -rf "$pkg"; else cd ..; fi
        return
    fi

    # --- ÉPÍTÉS ---
    log_info "ÚJ VERZIÓ! Építés: $pkg ($current_version)"
    if makepkg -se --noconfirm --clean --nocheck; then
        mv *.pkg.tar.zst ../$OUTPUT_DIR/ || mv *.pkg.tar.xz ../$OUTPUT_DIR/
        echo "$pkg" >> ../packages_to_clean.txt
        log_succ "$pkg építése sikeres."

        # --- ITT A VISSZAÍRÁS A REPÓBA (Csak saját csomagoknál) ---
        if [ "$is_aur" == "false" ]; then
            log_info "PKGBUILD frissítése és Git Push..."
            
            # PKGBUILD frissítése az új verzióval
            sed -i "s/^pkgver=.*/pkgver=${full_ver}/" PKGBUILD
            sed -i "s/^pkgrel=.*/pkgrel=${rel_ver}/" PKGBUILD
            
            # .SRCINFO generálása, hogy az is friss legyen a repóban
            makepkg --printsrcinfo > .SRCINFO
            
            # Git műveletek
            git add PKGBUILD .SRCINFO
            
            # Csak akkor commitolunk, ha van változás
            if git diff-index --quiet HEAD --; then
                log_info "Nincs mit commitolni."
            else
                git commit -m "Auto-update: $pkg updated to $current_version [skip ci]"
                # A [skip ci] a commit üzenetben fontos, hogy ne indítson végtelen loopot!
                git push
                log_succ "Git repo frissítve!"
            fi
        fi

    else
        log_info "HIBA az építésnél: $pkg"
    fi

    if [ "$is_aur" == "true" ]; then cd .. && rm -rf "$pkg"; else cd ..; fi
}

# --- FŐ CIKLUSOK ---

log_info "--- SAJÁT CSOMAGOK ---"
for pkg in "${LOCAL_PACKAGES[@]}"; do
    build_package "$pkg" "false"
done

log_info "--- AUR CSOMAGOK ---"
mkdir -p build_aur
cd build_aur
for pkg in "${AUR_PACKAGES[@]}"; do
    build_package "$pkg" "true"
done
cd ..

# --- FELTÖLTÉS ---
if [ -z "$(ls -A $OUTPUT_DIR)" ]; then
    log_succ "Minden naprakész. Nincs feltölteni való."
    exit 0
fi

log_info "Feltöltés a szerverre..."
scp -o StrictHostKeyChecking=no $OUTPUT_DIR/* $VPS_USER@$VPS_HOST:$REMOTE_DIR/

log_info "Szerver adatbázis frissítése..."
REMOTE_COMMANDS="cd $REMOTE_DIR && "

if [ -f packages_to_clean.txt ]; then
    while read pkg_to_clean; do
        REMOTE_COMMANDS+="ls -t ${pkg_to_clean}-*.pkg.tar.zst | tail -n +2 | xargs -r rm -- && "
    done < packages_to_clean.txt
fi

REMOTE_COMMANDS+="rm -f ${REPO_DB_NAME}.db* ${REPO_DB_NAME}.files* && "
REMOTE_COMMANDS+="repo-add ${REPO_DB_NAME}.db.tar.gz *.pkg.tar.zst"

ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST "$REMOTE_COMMANDS"

log_succ "KÉSZ! Repó frissítve."
