#!/bin/bash
# NINCS set -e!

cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

echo "[BUILD SYSTEM] Repo gyökér: $REPO_ROOT"

# --- CSOMAGOK LISTÁJA ---
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
    "xorg-font-utils" "xnviewmp" "simplescreenrecorder" "gtkhash-thunar"
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

info() { echo -e "\e[34m[INFO]\e[0m $1"; }
ok() { echo -e "\e[32m[OK]\e[0m $1"; }
warn() { echo -e "\e[33m[WARN]\e[0m $1"; }
error() { echo -e "\e[31m[ERROR]\e[0m $1"; }
skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }

# 1. HASH TRACKING FUNKCIÓK
get_package_hash() {
    local pkg_dir="$1"
    local pkg="$2"
    
    # Helyi csomag: számoljunk hash-t a forrásfájlokból
    if [ -d "$pkg_dir" ]; then
        cd "$pkg_dir" 2>/dev/null || return 1
        
        # Készítsünk hash-t a PKGBUILD és forrásfájlokból
        if [ -f PKGBUILD ]; then
            # SHA256 hash a PKGBUILD-ból és a forrásfájlok neveiből
            local sources=""
            if [ -f .SRCINFO ]; then
                sources=$(grep -E '^\s*source\s*=' .SRCINFO | sort)
            fi
            
            # Hash a PKGBUILD tartalmából és forrásokból
            local hash_content
            hash_content=$(cat PKGBUILD 2>/dev/null; echo "$sources")
            echo "$hash_content" | sha256sum | cut -d' ' -f1
        else
            # Ha nincs PKGBUILD, akkor git hash
            if [ -d .git ]; then
                git rev-parse HEAD 2>/dev/null || echo "no_hash"
            else
                echo "no_hash"
            fi
        fi
        
        cd - >/dev/null 2>&1
    else
        echo "no_dir"
    fi
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

# 2. SZERVER LISTA LEKÉRÉSE
info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "ls -1 $REMOTE_DIR 2>/dev/null" > "$REPO_ROOT/remote_files.txt"; then
    ok "Szerver lista letöltve ($(wc -l < "$REPO_ROOT/remote_files.txt") fájl)."
else
    warn "Nem sikerült lekérni a listát"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 3. DB LETÖLTÉS
info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# 4. HASH ALAPÚ VÁLTOZÁSÉSZLELÉS
is_any_version_on_server() {
    local pkgname="$1"
    grep -q "^${pkgname}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null
}

# 5. BUILD FUNKCIÓ - HASH TRACKINGGEL
build_package_with_hash_tracking() {
    local pkg="$1"
    local is_aur="$2"
    
    info "========================================"
    info "Csomag: $pkg"
    info "========================================"
    
    local pkg_dir=""
    local current_hash=""
    local stored_hash=""
    
    # 1. TÁROLT HASH BETÖLTÉSE
    stored_hash=$(load_stored_hash "$pkg")
    info "Tárolt hash: ${stored_hash:0:16}..."
    
    # 2. PKGBUILD/CSOMAG BESZERZÉSE
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
        
        # AUR csomag hash számítása
        current_hash=$(get_package_hash "$pkg_dir" "$pkg")
        
        # Ha van .SRCINFO, akkor a forrásokat is nézzük
        if [ -f .SRCINFO ]; then
            local srcinfo_hash
            srcinfo_hash=$(sha256sum .SRCINFO 2>/dev/null | cut -d' ' -f1)
            current_hash="${current_hash}_${srcinfo_hash:0:16}"
        fi
    else
        # Helyi csomag
        if [ ! -d "$REPO_ROOT/$pkg" ]; then
            warn "Helyi mappa nem található: $pkg"
            return 0
        fi
        pkg_dir="$REPO_ROOT/$pkg"
        cd "$pkg_dir" 2>/dev/null || return 0
        
        # Helyi csomag hash számítása
        current_hash=$(get_package_hash "$pkg_dir" "$pkg")
    fi
    
    info "Jelenlegi hash: ${current_hash:0:16}..."
    
    # 3. HASH ÖSSZEHASONLÍTÁS
    # Ha a hash változatlan ÉS a csomag már a szerveren van, akkor SKIP
    if [ "$current_hash" = "$stored_hash" ] && [ -n "$current_hash" ] && [ "$current_hash" != "no_hash" ]; then
        if is_any_version_on_server "$pkg"; then
            skip "$pkg HASH VÁLTOZATLAN és MÁR A SZERVEREN VAN - SKIP"
            cd "$REPO_ROOT"
            rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
            return 0
        else
            warn "$pkg hash változatlan, de nincs a szerveren - építés"
        fi
    fi
    
    # 4. HA A HASH VÁLTOZOTT VAGY NINCS A SZERVEREN, ÉPÍTJÜK
    if [ -n "$stored_hash" ] && [ "$current_hash" != "$stored_hash" ]; then
        info "HASH VÁLTOZOTT! Régi: ${stored_hash:0:16}... Új: ${current_hash:0:16}..."
    fi
    
    info "Építés..."
    
    # Függőségek (nem kritikus)
    if [ "$is_aur" = "true" ]; then
        yay -S --asdeps --needed --noconfirm $(makepkg --printsrcinfo 2>/dev/null | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//' | tr '\n' ' ') 2>/dev/null || true
    fi
    
    # Források letöltése
    if ! makepkg -od --noconfirm 2>&1; then
        error "Forrás letöltés sikertelen: $pkg"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # Építés
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
    fi
    
    cd "$REPO_ROOT" 2>/dev/null || true
    rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
}

# 6. FŐ FUTÁS
main() {
    info "=== HASH-BASED BUILD RENDSZER ==="
    info "Kezdés: $(date)"
    info "Helyi csomagok: ${#LOCAL_PACKAGES[@]}"
    info "AUR csomagok: ${#AUR_PACKAGES[@]}"
    
    # Hash fájl ellenőrzése
    local hash_file="$REPO_ROOT/$BUILD_TRACKING_DIR/package_hashes.txt"
    if [ ! -f "$hash_file" ]; then
        warn "Hash fájl nem található, létrehozás: $hash_file"
        touch "$hash_file"
    else
        info "Hash fájl betöltve ($(wc -l < "$hash_file") bejegyzés)"
    fi
    
    # Reset
    rm -f "$REPO_ROOT/packages_to_clean.txt"
    rm -rf "$REPO_ROOT/build_aur" 2>/dev/null
    rm -rf "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null
    touch "$REPO_ROOT/packages_to_clean.txt"
    
    # AUR CSOMAGOK
    info "--- AUR CSOMAGOK ---"
    for pkg in "${AUR_PACKAGES[@]}"; do
        build_package_with_hash_tracking "$pkg" "true"
        echo ""
    done
    
    # HELYI CSOMAGOK
    info "--- HELYI CSOMAGOK ---"
    for pkg in "${LOCAL_PACKAGES[@]}"; do
        build_package_with_hash_tracking "$pkg" "false"
        echo ""
    done
    
    # VAN-E ÉPÍTETT CSOMAG?
    local built_count=0
    built_count=$(ls -1 "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null | wc -l)
    
    if [ "$built_count" -eq 0 ]; then
        ok "Nincs új csomag - minden naprakész!"
        
        # Még lehet git változás (hash fájl frissítése)
        git_push_if_needed
        exit 0
    fi
    
    info "=== FELTÖLTÉS ($built_count csomag) ==="
    
    # Adatbázis frissítés
    cd "$REPO_ROOT/$OUTPUT_DIR" 2>/dev/null || return 0
    if [ -f "${REPO_DB_NAME}.db.tar.gz" ]; then
        repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || warn "repo-add hiba"
    else
        repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || warn "repo-add hiba"
    fi
    
    # Feltöltés
    cd "$REPO_ROOT" 2>/dev/null || return 0
    info "Feltöltés a szerverre..."
    
    for attempt in 1 2 3; do
        if scp $SSH_OPTS "$OUTPUT_DIR"/* "$VPS_USER@$VPS_HOST:$REMOTE_DIR/" 2>/dev/null; then
            ok "Feltöltés sikeres!"
            break
        elif [ "$attempt" -eq 3 ]; then
            error "Feltöltés sikertelen 3 próbálkozás után"
            return 1
        else
            warn "Feltöltés sikertelen, újrapróbálás $attempt..."
            sleep 3
        fi
    done
    
    # Régi csomagok törlése
    if [ -f "$REPO_ROOT/packages_to_clean.txt" ]; then
        info "Régi csomagok törlése..."
        while read -r pkg_to_clean; do
            ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" \
                "cd $REMOTE_DIR && ls -t ${pkg_to_clean}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | xargs -r rm -f" 2>/dev/null || true
        done < "$REPO_ROOT/packages_to_clean.txt"
    fi
    
    # Git push
    git_push_if_needed
    
    # Összegzés
    info "========================================"
    ok "KÉSZ! $(date)"
    info "Statisztika:"
    info "  - Helyi csomagok: ${#LOCAL_PACKAGES[@]}"
    info "  - AUR csomagok: ${#AUR_PACKAGES[@]}"
    info "  - Új csomagok: $built_count"
    info "========================================"
}

# 7. GIT PUSH (ha változott a hash fájl)
git_push_if_needed() {
    cd "$REPO_ROOT" 2>/dev/null || return 0
    
    # Van-e változás?
    if ! git status --porcelain 2>/dev/null | grep -q "."; then
        info "Nincs git változás."
        return 0
    fi
    
    info "Git változások push..."
    
    git add . 2>/dev/null || true
    
    local commit_msg="Auto-update: $(date +%Y-%m-%d)"
    if [ -f "$REPO_ROOT/$BUILD_TRACKING_DIR/package_hashes.txt" ]; then
        local updated_packages
        updated_packages=$(git diff --name-only HEAD -- "$BUILD_TRACKING_DIR/" 2>/dev/null | xargs -r basename -a | tr '\n' ', ' | sed 's/, $//')
        if [ -n "$updated_packages" ]; then
            commit_msg="$commit_msg - Hash updates: $updated_packages"
        fi
    fi
    
    git commit -m "$commit_msg" 2>/dev/null || true
    
    for attempt in 1 2 3; do
        if git push origin main 2>&1; then
            ok "Git push sikeres!"
            return 0
        elif [ "$attempt" -eq 3 ]; then
            warn "Git push sikertelen"
            return 1
        else
            warn "Git push sikertelen, újrapróbálás $attempt..."
            sleep 3
        fi
    done
}

# 8. FUTTATÁS
main || error "Hiba történt, de a script nem állt meg."
exit 0