#!/bin/bash
cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

echo "[BUILD SYSTEM] Repo gyökér: $REPO_ROOT"

# --- KONFIGURÁCIÓ ---
LOCAL_PACKAGES=(
    "gtk2" "awesome-freedesktop-git" "lain-git" "awesome-rofi"
    "nordic-backgrounds" "awesome-copycats-manjaro" "i3lock-fancy-git"
    "ttf-font-awesome-5" "nvidia-driver-assistant" "grayjay-bin" "awesome-git"
)

AUR_PACKAGES=(
    "libinput-gestures" "qt5-styleplugins" "urxvt-resize-font-git" "i3lock-color"
    "raw-thumbnailer" "gsconnect" "tilix-git" "tamzen-font" "betterlockscreen"
    "nordic-theme" "nordic-darker-theme" "geany-nord-theme" "nordzy-icon-theme"
    "oh-my-posh-bin" "fish-done" "find-the-command" "p7zip-gui" "qownnotes"
    "xorg-fonts-utils" "xnviewmp" "simplescreenrecorder" "gtkhash-thunar"
    "a4tech-bloody-driver-git" "nordic-bluish-accent-theme"
    "nordic-bluish-accent-standard-buttons-theme" "nordic-polar-standard-buttons-theme"
    "nordic-standard-buttons-theme" "nordic-darker-standard-buttons-theme"
)

REMOTE_DIR="/var/www/repo"
REPO_DB_NAME="manjaro-awesome"
OUTPUT_DIR="built_packages"
BUILD_TRACKING_DIR=".buildtracking"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"

mkdir -p "$REPO_ROOT/$OUTPUT_DIR"
mkdir -p "$REPO_ROOT/$BUILD_TRACKING_DIR"

git config --global user.name "GitHub Action Bot"
git config --global user.email "action@github.com"

# --- LOGGING ---
info() { echo -e "\e[34m[INFO]\e[0m $1"; }
ok() { echo -e "\e[32m[OK]\e[0m $1"; }
warn() { echo -e "\e[33m[WARN]\e[0m $1"; }
error() { echo -e "\e[31m[ERROR]\e[0m $1"; }
skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }

# 1. YAY TELEPÍTÉS HA KELL
if ! command -v yay &> /dev/null; then
    info "Yay telepítése..."
    cd /tmp
    git clone https://aur.archlinux.org/yay.git 2>/dev/null && {
        cd yay
        makepkg -si --noconfirm 2>&1 | grep -v "warning:"
        cd /tmp
        rm -rf yay
    } || warn "Yay telepítés skip"
    cd "$REPO_ROOT"
fi

# 2. SZERVER LISTA LEKÉRÉSE
info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "find $REMOTE_DIR -name '*.pkg.tar.*' -printf '%f\n' 2>/dev/null" > "$REPO_ROOT/remote_files.txt"; then
    ok "Szerver lista letöltve ($(wc -l < "$REPO_ROOT/remote_files.txt") fájl)."
else
    warn "Nem sikerült lekérni a listát"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 3. DB LETÖLTÉS
info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# --- EGYSZERŰ HASH TRACKING ---
get_package_hash() {
    local pkg_dir="$1"
    
    cd "$pkg_dir" 2>/dev/null || { echo "no_dir"; return 1; }
    
    # SHA1 hash a PKGBUILD-ból
    if [ -f PKGBUILD ]; then
        sha1sum PKGBUILD 2>/dev/null | cut -d' ' -f1
    elif [ -d .git ]; then
        git rev-parse HEAD 2>/dev/null || echo "git_no_hash"
    else
        echo "no_hash"
    fi
    
    cd - >/dev/null 2>&1
}

load_stored_hash() {
    local pkg="$1"
    local hash_file="$REPO_ROOT/$BUILD_TRACKING_DIR/package_hashes.txt"
    
    if [ -f "$hash_file" ]; then
        grep "^${pkg}:" "$hash_file" 2>/dev/null | cut -d: -f2-
    else
        echo ""
    fi
}

save_package_hash() {
    local pkg="$1"
    local hash="$2"
    local hash_file="$REPO_ROOT/$BUILD_TRACKING_DIR/package_hashes.txt"
    
    # Távolítsuk el a régi bejegyzést
    if [ -f "$hash_file" ]; then
        grep -v "^${pkg}:" "$hash_file" > "${hash_file}.tmp" 2>/dev/null || true
        mv "${hash_file}.tmp" "$hash_file" 2>/dev/null || true
    fi
    
    # Adjuk hozzá az újat
    echo "${pkg}:${hash}" >> "$hash_file"
}

is_any_version_on_server() {
    local pkgname="$1"
    grep -q "^${pkgname}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null
}

# --- JAVÍTOTT BUILD FUNKCIÓ ---
build_package_fixed() {
    local pkg="$1"
    local is_aur="$2"
    
    info "========================================"
    info "Csomag: $pkg"
    info "========================================"
    
    # Kihagyás, ha már a szerveren van
    if is_any_version_on_server "$pkg"; then
        skip "$pkg MÁR A SZERVEREN VAN - SKIP"
        return 0
    fi
    
    local pkg_dir=""
    local current_hash=""
    local stored_hash=""
    
    stored_hash=$(load_stored_hash "$pkg")
    
    # 1. PKGBUILD BESZERZÉSE
    if [ "$is_aur" = "true" ]; then
        mkdir -p "$REPO_ROOT/build_aur"
        cd "$REPO_ROOT/build_aur" 2>/dev/null || return 0
        
        rm -rf "$pkg" 2>/dev/null
        info "AUR klónozás: $pkg"
        if ! git clone "https://aur.archlinux.org/$pkg.git" 2>/dev/null; then
            error "AUR klónozás sikertelen: $pkg"
            cd "$REPO_ROOT"
            return 0
        fi
        
        pkg_dir="$REPO_ROOT/build_aur/$pkg"
        cd "$pkg" 2>/dev/null || { cd "$REPO_ROOT"; return 0; }
    else
        if [ ! -d "$REPO_ROOT/$pkg" ]; then
            warn "Helyi mappa nem található: $pkg"
            return 0
        fi
        pkg_dir="$REPO_ROOT/$pkg"
        cd "$pkg_dir" 2>/dev/null || return 0
    fi
    
    # 2. HASH SZÁMÍTÁS
    current_hash=$(get_package_hash "$pkg_dir")
    
    # 3. HASH ELLENŐRZÉS
    if [ -n "$stored_hash" ] && [ "$current_hash" = "$stored_hash" ] && [ "$current_hash" != "no_hash" ]; then
        skip "$pkg HASH VÁLTOZATLAN - SKIP"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # 4. ÉPÍTÉS
    info "Építés..."
    
    # JAVÍTÁS: Függőségek teleítése YAY-val
    info "Függőségek telepítése yay-val..."
    if [ "$is_aur" = "true" ]; then
        # Kinyerjük a függőségeket a .SRCINFO-ból
        if [ -f .SRCINFO ]; then
            local deps=""
            deps=$(grep -E '^\s*(make)?depends\s*=' .SRCINFO | sed 's/^.*=\s*//' | tr '\n' ' ')
            if [ -n "$deps" ]; then
                # Külön kezeljük a gtk2-t (azt mi építjük)
                deps=$(echo "$deps" | sed 's/gtk2//g')
                if [ -n "$deps" ]; then
                    yay -S --asdeps --needed --noconfirm $deps 2>/dev/null || {
                        warn "Egyes függőségek telepítése sikertelen, de folytatjuk..."
                    }
                fi
            fi
        fi
    fi
    
    # Források letöltése
    if ! makepkg -od --noconfirm 2>&1; then
        error "Forrás letöltés sikertelen: $pkg"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # JAVÍTÁS: Build NOCHECK-kel, hogy ne próbáljon függőségeket telepíteni
    info "Build folyamat..."
    if makepkg -si --noconfirm --clean --nocheck 2>&1; then
        for pkgfile in *.pkg.tar.*; do
            [ -f "$pkgfile" ] || continue
            mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
            ok "Build sikeres: $(basename "$pkgfile")"
            echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
            
            # Hash mentése
            save_package_hash "$pkg" "$current_hash"
            break
        done
    else
        error "Build sikertelen: $pkg"
        warn "Build hiba, de folytatjuk a következő csomaggal..."
    fi
    
    cd "$REPO_ROOT" 2>/dev/null || true
    rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
}

# --- FŐ FUTÁS ---
main() {
    info "=== JAVÍTOTT BUILD RENDSZER ==="
    info "Kezdés: $(date)"
    
    # Hash fájl létrehozása ha nincs
    local hash_file="$REPO_ROOT/$BUILD_TRACKING_DIR/package_hashes.txt"
    if [ ! -f "$hash_file" ]; then
        info "Új hash fájl létrehozása..."
        echo "# Package hashes - $(date)" > "$hash_file"
    fi
    
    # Reset
    rm -f "$REPO_ROOT/packages_to_clean.txt"
    rm -rf "$REPO_ROOT/build_aur" 2>/dev/null
    rm -rf "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null
    touch "$REPO_ROOT/packages_to_clean.txt"
    
    # 1. ELŐSZÖR A HELYI CSOMAGOK (különösen gtk2)
    info "--- HELYI CSOMAGOK ELŐSZÖR (${#LOCAL_PACKAGES[@]}) ---"
    for pkg in "${LOCAL_PACKAGES[@]}"; do
        build_package_fixed "$pkg" "false"
        echo ""
    done
    
    # 2. UTÁNA AZ AUR CSOMAGOK
    info "--- AUR CSOMAGOK UTÁNA (${#AUR_PACKAGES[@]}) ---"
    for pkg in "${AUR_PACKAGES[@]}"; do
        build_package_fixed "$pkg" "true"
        echo ""
    done
    
    # VAN-E ÉPÍTETT CSOMAG?
    local output_count=0
    output_count=$(ls -1 "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null | wc -l)
    
    if [ "$output_count" -eq 0 ]; then
        ok "Nincs új csomag - minden naprakész!"
        exit 0
    fi
    
    info "=== FELTÖLTÉS ($output_count csomag) ==="
    
    # Adatbázis frissítés
    cd "$REPO_ROOT/$OUTPUT_DIR" 2>/dev/null || { error "Nem lehet a $OUTPUT_DIR mappába menni"; return 0; }
    if [ -f "${REPO_DB_NAME}.db.tar.gz" ]; then
        repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || warn "repo-add hiba"
    else
        repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || warn "repo-add hiba"
    fi
    
    # Feltöltés
    cd "$REPO_ROOT" 2>/dev/null || return 0
    info "Feltöltés a szerverre..."
    
    local upload_success=0
    for attempt in 1 2 3; do
        if scp $SSH_OPTS "$OUTPUT_DIR"/* "$VPS_USER@$VPS_HOST:$REMOTE_DIR/" 2>/dev/null; then
            ok "Feltöltés sikeres!"
            upload_success=1
            break
        else
            warn "Feltöltés sikertelen ($attempt/3)"
            sleep 3
        fi
    done
    
    if [ "$upload_success" -eq 0 ]; then
        error "Feltöltés sikertelen 3 próbálkozás után"
    fi
    
    # Régi csomagok törlése
    if [ -f "$REPO_ROOT/packages_to_clean.txt" ]; then
        info "Régi csomagok törlése..."
        while read -r pkg_to_clean || [ -n "$pkg_to_clean" ]; do
            ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" \
                "cd $REMOTE_DIR && ls -t ${pkg_to_clean}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | xargs -r rm -f" 2>/dev/null || true
        done < "$REPO_ROOT/packages_to_clean.txt"
    fi
    
    # Összegzés
    info "========================================"
    ok "KÉSZ! $(date)"
    info "Új csomagok: $output_count"
    info "Hash fájl: $hash_file"
    info "========================================"
}

# --- FUTTATÁS ---
main || error "Hiba történt."
exit 0