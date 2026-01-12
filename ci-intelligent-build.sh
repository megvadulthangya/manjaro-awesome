#!/bin/bash
cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

echo "[BUILD SYSTEM] Repo gyökér: $REPO_ROOT"

# --- KONFIGURÁCIÓ - EREDETI FORMÁTUM ---
LOCAL_PACKAGES=(
    "gghelper"
    "gtk2"
    "awesome-freedesktop-git"
    "lain-git"
    "awesome-rofi"
    "nordic-backgrounds"
    "awesome-copycats-manjaro"
    "i3lock-fancy-git"
    "ttf-font-awesome-5"
    "nvidia-driver-assistant"
    "grayjay-bin"
)

AUR_PACKAGES=(
    "libinput-gestures"
    "qt5-styleplugins"
    "urxvt-resize-font-git"
    "i3lock-color"
    "raw-thumbnailer"
    "gsconnect"
    "gtkd"
    "awesome-git"
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
    # "xorg-font-utils"  # KIHAGYVA: nem elérhető az AUR-ban
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
debug() { echo -e "\e[35m[DEBUG]\e[0m $1"; }

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

# 2. SZERVER LISTA LEKÉRÉSE - DEBUG INFÓVAL
info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "find $REMOTE_DIR -name '*.pkg.tar.*' -type f -printf '%f\n' 2>/dev/null | sort" > "$REPO_ROOT/remote_files.txt"; then
    ok "Szerver lista letöltve ($(wc -l < "$REPO_ROOT/remote_files.txt") fájl)."
    # Debug: mutassunk néhány fájlnevet
    debug "Első 5 fájl a szerveren:"
    head -5 "$REPO_ROOT/remote_files.txt" | while read -r line; do
        debug "  $line"
    done
    debug "Utolsó 5 fájl a szerveren:"
    tail -5 "$REPO_ROOT/remote_files.txt" | while read -r line; do
        debug "  $line"
    done
else
    warn "Nem sikerült lekérni a listát"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 3. DB LETÖLTÉS
info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# --- DEBUG FUNKCIÓ: Ellenőrzi, hogy tényleg ott van-e a csomag ---
debug_check_package_on_server() {
    local pkgname="$1"
    
    # Egyszerű grep
    if grep -q "^${pkgname}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
        debug "  ✅ $pkgname TALÁLHATÓ a szerveren"
        # Mutassuk meg a találatot
        local match
        match=$(grep "^${pkgname}-" "$REPO_ROOT/remote_files.txt" | head -1)
        debug "     Találat: $match"
        return 0
    else
        debug "  ❌ $pkgname NEM található a szerveren"
        return 1
    fi
}

# --- HASH TRACKING ---
get_package_hash() {
    local pkg_dir="$1"
    
    cd "$pkg_dir" 2>/dev/null || { echo "no_dir"; return 1; }
    
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
    
    if [ -f "$hash_file" ]; then
        grep -v "^${pkg}:" "$hash_file" > "${hash_file}.tmp" 2>/dev/null || true
        mv "${hash_file}.tmp" "$hash_file" 2>/dev/null || true
    fi
    
    echo "${pkg}:${hash}" >> "$hash_file"
}

# --- JAVÍTOTT: Ellenőrzi, hogy van-e a csomagnak bármilyen verziója a szerveren ---
is_any_version_on_server() {
    local pkgname="$1"
    
    # Üres fájl ellenőrzés
    if [ ! -s "$REPO_ROOT/remote_files.txt" ]; then
        debug "  Üres a remote_files.txt fájl"
        return 1
    fi
    
    # Debug: számoljuk meg, hány találat van
    local match_count
    match_count=$(grep -c "^${pkgname}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null || echo 0)
    
    if [ "$match_count" -gt 0 ]; then
        debug "  $pkgname: $match_count találat"
        return 0
    else
        debug "  $pkgname: NINCS találat"
        return 1
    fi
}

# --- BUILD FUNKCIÓ - DEBUG INFÓVAL ---
build_package_with_debug() {
    local pkg="$1"
    local is_aur="$2"
    
    info "========================================"
    info "Csomag: $pkg"
    info "========================================"
    
    # DEBUG: Ellenőrizzük, hogy tényleg ott van-e
    debug "Ellenőrzés: $pkg a szerveren?"
    if is_any_version_on_server "$pkg"; then
        skip "$pkg MÁR A SZERVEREN VAN - SKIP"
        return 0
    fi
    
    info "$pkg NINCS A SZERVEREN - ÉPÍTÉS"
    
    local pkg_dir=""
    local current_hash=""
    local stored_hash=""
    
    stored_hash=$(load_stored_hash "$pkg")
    
    # AUR vagy helyi?
    if [ "$is_aur" = "true" ]; then
        mkdir -p "$REPO_ROOT/build_aur"
        cd "$REPO_ROOT/build_aur" 2>/dev/null || { warn "Nem lehet build_aur mappába menni"; return 0; }
        
        rm -rf "$pkg" 2>/dev/null
        info "AUR klónozás: $pkg"
        
        # Próbáljuk klónozni
        if ! git clone "https://aur.archlinux.org/$pkg.git" 2>/dev/null; then
            error "AUR klónozás sikertelen: $pkg (nincs az AUR-ban?)"
            cd "$REPO_ROOT"
            return 0
        fi
        
        pkg_dir="$REPO_ROOT/build_aur/$pkg"
        cd "$pkg" 2>/dev/null || { error "Nem lehet a $pkg mappába menni"; cd "$REPO_ROOT"; return 0; }
        
        # Ellenőrizzük, hogy van-e PKGBUILD
        if [ ! -f PKGBUILD ]; then
            error "Nincs PKGBUILD a csomagban: $pkg (hibás AUR csomag)"
            cd "$REPO_ROOT"
            rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
            return 0
        fi
    else
        # Helyi csomag
        if [ ! -d "$REPO_ROOT/$pkg" ]; then
            warn "Helyi mappa nem található: $pkg"
            return 0
        fi
        pkg_dir="$REPO_ROOT/$pkg"
        cd "$pkg_dir" 2>/dev/null || { warn "Nem lehet a $pkg mappába menni"; return 0; }
    fi
    
    # Hash számítás
    current_hash=$(get_package_hash "$pkg_dir")
    debug "Hash: $current_hash (tárolt: $stored_hash)"
    
    # Hash ellenőrzés - ha van tárolt hash és az megegyezik, akkor skip
    if [ -n "$stored_hash" ] && [ "$current_hash" = "$stored_hash" ] && [ "$current_hash" != "no_hash" ]; then
        skip "$pkg HASH VÁLTOZATLAN - SKIP"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # Építés
    info "Építés kezdése..."
    
    # Függőségek (csak AUR csomagoknál próbáljuk)
    if [ "$is_aur" = "true" ] && [ -f .SRCINFO ]; then
        info "Függőségek ellenőrzése..."
        # Kihagyjuk a gtk2-t, mert azt mi építjük
        local deps
        deps=$(grep -E '^\s*(make)?depends\s*=' .SRCINFO | sed 's/^.*=\s*//' | tr '\n' ' ' | sed 's/gtk2//g')
        if [ -n "$deps" ]; then
            yay -S --asdeps --needed --noconfirm $deps 2>/dev/null || {
                warn "Egyes függőségek telepítése sikertelen, de folytatjuk..."
            }
        fi
    fi
    
    # Források letöltése
    if ! makepkg -od --noconfirm 2>&1; then
        error "Forrás letöltés sikertelen: $pkg"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # Build
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

# --- FŐ FUTÁS - DEBUG MÓD ---
main() {
    info "=== DEBUG BUILD RENDSZER ==="
    info "Kezdés: $(date)"
    info "Helyi csomagok: ${#LOCAL_PACKAGES[@]}"
    info "AUR csomagok: ${#AUR_PACKAGES[@]}"
    
    # Hash fájl ellenőrzés
    local hash_file="$REPO_ROOT/$BUILD_TRACKING_DIR/package_hashes.txt"
    if [ ! -f "$hash_file" ]; then
        info "Új hash fájl létrehozása..."
        echo "# Package hashes - $(date)" > "$hash_file"
    else
        info "Hash fájl betöltve ($(wc -l < "$hash_file") bejegyzés)"
    fi
    
    # Reset
    rm -f "$REPO_ROOT/packages_to_clean.txt"
    rm -rf "$REPO_ROOT/build_aur" 2>/dev/null
    rm -rf "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null
    touch "$REPO_ROOT/packages_to_clean.txt"
    
    # DEBUG: Ellenőrizzük MINDEN csomagot
    info "=== DEBUG: ÖSSZES CSOMAG ELLENŐRZÉSE ==="
    debug "Szerveren lévő fájlok száma: $(wc -l < "$REPO_ROOT/remote_files.txt")"
    
    # Ellenőrizzük a helyi csomagokat
    info "--- HELYI CSOMAGOK DEBUG ---"
    for pkg in "${LOCAL_PACKAGES[@]}"; do
        debug_check_package_on_server "$pkg"
    done
    
    # Ellenőrizzük az AUR csomagokat
    info "--- AUR CSOMAGOK DEBUG ---"
    for pkg in "${AUR_PACKAGES[@]}"; do
        debug_check_package_on_server "$pkg"
    done
    
    # Építés - HELYI CSOMAGOK
    info "--- HELYI CSOMAGOK ÉPÍTÉSE ---"
    for pkg in "${LOCAL_PACKAGES[@]}"; do
        build_package_with_debug "$pkg" "false"
        echo ""
    done
    
    # Építés - AUR CSOMAGOK
    info "--- AUR CSOMAGOK ÉPÍTÉSE ---"
    for pkg in "${AUR_PACKAGES[@]}"; do
        build_package_with_debug "$pkg" "true"
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
    info "Statisztika:"
    info "  - Új csomagok: $output_count"
    info "========================================"
}

# --- FUTTATÁS ---
main || error "Hiba történt."
exit 0
