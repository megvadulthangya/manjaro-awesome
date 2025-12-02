#!/bin/bash
set -e

# --- 0. BIZTONSÁGI ZÁRAK FELOLDÁSA ---
export GIT_DISCOVERY_ACROSS_FILESYSTEM=1
git config --global --add safe.directory '*'

# --- 1. ÚTVONAL FIXÁLÁS ---
cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

# --- FIX SSH URL ---
SSH_REPO_URL="git@github.com:megvadulthangya/manjaro-awesome.git"

echo "[DEBUG] Repo gyökér: $REPO_ROOT"
echo "[DEBUG] Push URL: $SSH_REPO_URL"

# --- CSOMAGOK LISTÁJA ---
LOCAL_PACKAGES=(
    "awesome-rofi"
    "nordic-backgrounds"
    "awesome-copycats-manjaro"
    "i3lock-fancy-git"
)

AUR_PACKAGES=(
    "urxvt-resize-font-git"
    "ttf-font-awesome-5"
    "grayjay-bin"
    "awesome-git"
    "i3lock-color"
    "raw-thumbnailer"
    "gsconnect"
    "lain-git"
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
    # "nordic-polar-standard-buttons-theme" <-- Üres repo miatt kivéve
    "nordic-standard-buttons-theme"
    "nordic-darker-standard-buttons-theme"
)

REMOTE_DIR="/var/www/repo"
REPO_DB_NAME="manjaro-awesome"
OUTPUT_DIR="built_packages"

SSH_OPTS="-o StrictHostKeyChecking=no"

mkdir -p "$REPO_ROOT/$OUTPUT_DIR"

# --- GIT KONFIGURÁCIÓ ---
git config --global user.name "GitHub Action Bot"
git config --global user.email "action@github.com"

log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_succ() { echo -e "\e[32m[OK]\e[0m $1"; }
log_skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }
log_err()  { echo -e "\e[31m[HIBA]\e[0m $1"; }

# 2. YAY TELEPÍTÉSE
if ! command -v yay &> /dev/null; then
    log_info "Yay telepítése..."
    cd /tmp
    git clone https://aur.archlinux.org/yay.git
    cd yay
    makepkg -si --noconfirm
    cd - > /dev/null
fi

# 3. SZERVER LISTA LEKÉRÉSE (CSAK LISTA, NEM FÁJLOK!)
log_info "Szerver tartalmának lekérdezése (gyors lista)..."
if ssh $SSH_OPTS $VPS_USER@$VPS_HOST "ls -1 $REMOTE_DIR" > "$REPO_ROOT/remote_files.txt"; then
    log_succ "Lista letöltve."
else
    log_err "Nem sikerült lekérni a listát! (De folytatjuk, hátha üres a szerver)"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 4. DB LETÖLTÉS (Csak a kicsi adatbázis fájl kell a frissítéshez)
log_info "Adatbázis letöltése..."
scp $SSH_OPTS $VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# Segédfüggvény: A letöltött szöveges listában keres
is_on_server() {
    local pkgname="$1"
    local version="$2"
    if grep -q "^${pkgname}-${version}-" "$REPO_ROOT/remote_files.txt"; then
        return 0
    else
        return 1
    fi
}

build_package() {
    local pkg="$1"
    local is_aur="$2"
    
    cd "$REPO_ROOT"

    if [ "$is_aur" == "true" ]; then
        mkdir -p build_aur
        cd build_aur
        if [ -d "$pkg" ]; then rm -rf "$pkg"; fi
        if ! git clone "https://aur.archlinux.org/$pkg.git" > /dev/null 2>&1; then
             log_err "Nem sikerült klónozni: $pkg"
             return
        fi
        cd "$pkg"
    else
        if [ ! -d "$pkg" ]; then 
            log_err "Helyi mappa nem található: $pkg"
            return
        fi
        cd "$pkg"
    fi

    # 1. GYORS ELLENŐRZÉS
    if ! makepkg -od --noconfirm > /dev/null 2>&1; then
         log_err "Forrás letöltési/verzió hiba: $pkg"
         if [ "$is_aur" == "true" ]; then cd "$REPO_ROOT"; fi
         return
    fi

    makepkg --printsrcinfo > .SRCINFO
    full_ver=$(grep "pkgver =" .SRCINFO | head -1 | awk '{print $3}')
    rel_ver=$(grep "pkgrel =" .SRCINFO | head -1 | awk '{print $3}')
    
    if [ -z "$full_ver" ]; then
        source PKGBUILD
        full_ver=$pkgver
        rel_ver=$pkgrel
    fi

    local current_version="${full_ver}-${rel_ver}"

    # --- SKIP LOGIKA (KÖNNYŰSÚLYÚ) ---
    # Ha a listában benne van a név, akkor kész. Nem töltünk le semmit!
    if is_on_server "$pkg" "$current_version"; then
        log_skip "$pkg ($current_version) -> MÁR A SZERVEREN VAN."
        if [ "$is_aur" == "true" ]; then cd "$REPO_ROOT"; fi
        return
    fi

    # --- 2. ÉPÍTÉS ---
    log_info "ÚJ VERZIÓ! Építés: $pkg ($current_version)"
    
    # Függőségek előtelepítése yay-vel (ha kell)
    if [ "$is_aur" == "true" ]; then
        log_info "Függőségek ellenőrzése (AUR)..."
        yay -S --asdeps --needed --noconfirm $(makepkg --printsrcinfo | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//') 2>/dev/null || true
    fi

    if makepkg -sei --noconfirm --clean --nocheck; then
        mv *.pkg.tar.zst "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || mv *.pkg.tar.xz "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null
        echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
        log_succ "$pkg építése sikeres."

        # --- GIT PUSH (CLONE MÓDSZER) ---
        if [ "$is_aur" == "false" ]; then
            log_info "PKGBUILD frissítése és Git Push..."
            
            sed -i "s/^pkgver=.*/pkgver=${full_ver}/" PKGBUILD
            sed -i "s/^pkgrel=.*/pkgrel=${rel_ver}/" PKGBUILD
            makepkg --printsrcinfo > .SRCINFO
            
            TEMP_GIT_DIR="/tmp/git_publish_$pkg"
            rm -rf "$TEMP_GIT_DIR"
            
            if git clone "$SSH_REPO_URL" "$TEMP_GIT_DIR"; then
                cp "$REPO_ROOT/$pkg/PKGBUILD" "$TEMP_GIT_DIR/$pkg/"
                cp "$REPO_ROOT/$pkg/.SRCINFO" "$TEMP_GIT_DIR/$pkg/"
                cd "$TEMP_GIT_DIR"
                if git diff-index --quiet HEAD --; then
                    log_info "Nincs mit commitolni."
                else
                    git add "$pkg/PKGBUILD" "$pkg/.SRCINFO"
                    git commit -m "Auto-update: $pkg updated to $current_version [skip ci]"
                    if git push; then
                        log_succ "Git repo frissítve!"
                    else
                        log_err "Git Push sikertelen!"
                    fi
                fi
                cd "$REPO_ROOT"
                rm -rf "$TEMP_GIT_DIR"
            else
                log_err "Nem sikerült klónozni a publish repót."
            fi
        fi
    else
        log_err "HIBA az építésnél: $pkg"
    fi

    cd "$REPO_ROOT"
    if [ "$is_aur" == "true" ]; then rm -rf "build_aur/$pkg"; fi
}

# --- FŐ CIKLUSOK (AUR ELŐBB!) ---

log_info "--- AUR CSOMAGOK ---"
rm -rf build_aur
for pkg in "${AUR_PACKAGES[@]}"; do
    build_package "$pkg" "true"
done

log_info "--- SAJÁT CSOMAGOK ---"
for pkg in "${LOCAL_PACKAGES[@]}"; do
    build_package "$pkg" "false"
done

# --- DB FRISSÍTÉS ÉS FELTÖLTÉS ---
cd "$REPO_ROOT"

if [ -z "$(ls -A $OUTPUT_DIR/*.pkg.tar.* 2>/dev/null)" ]; then
    log_succ "Minden naprakész. Nincs feltölteni való."
    exit 0
fi

log_info "Adatbázis generálása..."
cd "$OUTPUT_DIR"
rm -f ${REPO_DB_NAME}.db* ${REPO_DB_NAME}.files*
repo-add ${REPO_DB_NAME}.db.tar.gz *.pkg.tar.zst

log_info "Feltöltés a szerverre..."
cd ..
scp $SSH_OPTS $OUTPUT_DIR/* $VPS_USER@$VPS_HOST:$REMOTE_DIR/

log_info "Takarítás a szerveren..."
REMOTE_COMMANDS="cd $REMOTE_DIR && "

if [ -f packages_to_clean.txt ]; then
    while read pkg_to_clean; do
        REMOTE_COMMANDS+="ls -t ${pkg_to_clean}-*.pkg.tar.zst 2>/dev/null | tail -n +2 | xargs -r rm -- && "
    done < packages_to_clean.txt
fi

REMOTE_COMMANDS+="echo 'Takarítás kész.'"
ssh $SSH_OPTS $VPS_USER@$VPS_HOST "$REMOTE_COMMANDS"

log_succ "KÉSZ! Repó frissítve."
