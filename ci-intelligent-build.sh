#!/bin/bash
# NINCS set -e! SOHA NE ÁLLJON MEG!

# --- 0. BIZTONSÁGI ZÁRAK FELOLDÁSA ---
export GIT_DISCOVERY_ACROSS_FILESYSTEM=1
git config --global --add safe.directory '*'

# --- 1. ÚTVONAL FIXÁLÁS ---
cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

# --- FIX SSH URL ---
SSH_REPO_URL="git@github.com:megvadulthangya/manjaro-awesome.git"

echo "[BUILD SYSTEM] Repo gyökér: $REPO_ROOT"

# --- CSOMAGOK LISTÁJA ---
LOCAL_PACKAGES=(
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
    "awesome-git"
)

AUR_PACKAGES=(
    "libinput-gestures"
    "qt5-styleplugins"
    "urxvt-resize-font-git"
    "i3lock-color"
    "raw-thumbnailer"
    "gsconnect"
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
OUTPUT_DIR="built_packages"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"

mkdir -p "$REPO_ROOT/$OUTPUT_DIR"

# --- GIT KONFIGURÁCIÓ ---
git config --global user.name "GitHub Action Bot"
git config --global user.email "action@github.com"

# Logging functions
info() { echo -e "\e[34m[INFO]\e[0m $1"; }
ok() { echo -e "\e[32m[OK]\e[0m $1"; }
warn() { echo -e "\e[33m[WARN]\e[0m $1"; }
error() { echo -e "\e[31m[ERROR]\e[0m $1"; }
skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }
debug() { echo -e "\e[35m[DEBUG]\e[0m $1"; }

# 2. YAY TELEPÍTÉSE
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

# 3. SZERVER LISTA LEKÉRÉSE - FÁJLOK ÉS VERSZIÓK
info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "find $REMOTE_DIR -name '*.pkg.tar.*' -type f -printf '%f\n' 2>/dev/null" > "$REPO_ROOT/remote_packages.txt"; then
    ok "Szerver lista letöltve ($(wc -l < "$REPO_ROOT/remote_packages.txt") fájl)."
    # Debug: mutassunk néhány csomagot
    debug "Példák a szerveren:"
    head -5 "$REPO_ROOT/remote_packages.txt" | while read line; do debug "  $line"; done
else
    warn "Nem sikerült lekérni a listát (új repo?)"
    touch "$REPO_ROOT/remote_packages.txt"
fi

# 4. DB LETÖLTÉS
info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# --- MŰKÖDŐ VERZIÓELLENŐRZÉS ---
# Ez a funkció ELLENŐRZI, hogy a csomag MÁR A SZERVEREN VAN-E

is_package_on_server() {
    local pkgname="$1"
    local version_to_check="$2"
    
    # Ha nincs megadva verzió, akkor csak a név alapján keresünk
    if [ -z "$version_to_check" ]; then
        if grep -q "^${pkgname}-" "$REPO_ROOT/remote_packages.txt" 2>/dev/null; then
            return 0  # true - van ilyen nevű csomag
        else
            return 1  # false - nincs ilyen nevű csomag
        fi
    fi
    
    # Verzióval együtt keresünk
    # Escape special characters for grep
    local escaped_version=$(echo "$version_to_check" | sed 's/[.[\*^$]/\\&/g')
    
    if grep -q "^${pkgname}-${escaped_version}-" "$REPO_ROOT/remote_packages.txt" 2>/dev/null; then
        return 0  # true - pontosan ez a verzió van a szerveren
    else
        return 1  # false - nincs ez a verzió a szerveren
    fi
}

# Verzió kinyerése a PKGBUILD-ból - EGYSZERŰEN
get_pkgbuild_version() {
    local pkg_dir="$1"
    
    cd "$pkg_dir" 2>/dev/null || { echo ""; return 1; }
    
    local pkgver="" pkgrel="1" epoch=""
    
    # PKGBUILD-ból olvassuk
    if [ -f PKGBUILD ]; then
        # Használjunk source-ot, de tiszta környezetben
        pkgver=$(grep '^pkgver=' PKGBUILD | head -1 | cut -d= -f2 | tr -d " '\"")
        pkgrel=$(grep '^pkgrel=' PKGBUILD | head -1 | cut -d= -f2 | tr -d " '\"")
        epoch=$(grep '^epoch=' PKGBUILD | head -1 | cut -d= -f2 | tr -d " '\"")
        
        [ -z "$pkgrel" ] && pkgrel="1"
    fi
    
    # Ha üres, próbáljuk .SRCINFO-t
    if [ -z "$pkgver" ] && [ -f .SRCINFO ]; then
        pkgver=$(grep "pkgver =" .SRCINFO | head -1 | awk '{print $3}')
        pkgrel=$(grep "pkgrel =" .SRCINFO | head -1 | awk '{print $3}')
    fi
    
    # Verzió string összeállítása
    local version_string=""
    if [ -n "$epoch" ] && [ "$epoch" != "0" ]; then
        version_string="${epoch}:${pkgver}-${pkgrel}"
    else
        version_string="${pkgver}-${pkgrel}"
    fi
    
    echo "$version_string"
    cd - >/dev/null 2>&1
}

# Fő build funkció - MŰKÖDŐ VERZIÓELLENŐRZÉSSEL
build_package_smart() {
    local pkg="$1"
    local is_aur="$2"
    
    info "========================================"
    info "Csomag: $pkg"
    info "========================================"
    
    local pkg_dir=""
    local pkg_version=""
    
    # 1. HELY AUR?
    if [ "$is_aur" = "true" ]; then
        mkdir -p "$REPO_ROOT/build_aur"
        cd "$REPO_ROOT/build_aur" 2>/dev/null || return 0
        
        # Klónozás
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
        # Helyi csomag
        if [ ! -d "$REPO_ROOT/$pkg" ]; then
            warn "Helyi mappa nem található: $pkg"
            return 0
        fi
        pkg_dir="$REPO_ROOT/$pkg"
        cd "$pkg_dir" 2>/dev/null || return 0
    fi
    
    # 2. VERZIÓ MEGHATÁROZÁSA A PKGBUILD-BÓL
    pkg_version=$(get_pkgbuild_version "$pkg_dir")
    
    if [ -z "$pkg_version" ] || [ "$pkg_version" = "-1" ]; then
        warn "Verzió nem határozható meg: $pkg (de megpróbáljuk építeni)"
        pkg_version="unknown"
    else
        info "PKGBUILD verzió: $pkg_version"
    fi
    
    # 3. ELLENŐRZÉS: VAN-E MÁR A SZERVEREN?
    # Itt a lényeg: NEM CSAK A VERZIÓT, HANEM A CSOMAG NEVET IS NÉZZÜK
    if is_package_on_server "$pkg" "$pkg_version"; then
        skip "$pkg ($pkg_version) MÁR A SZERVEREN VAN - NEM ÉPÍTJÜK ÚJRA"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # 4. NEM VAGYOK A SZERVEREN -> ÉPÍTÉS
    info "ÚJ VERZIÓ ($pkg_version) - Építés..."
    
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
    
    # ÉPÍTÉS
    if makepkg -si --noconfirm --clean --nocheck 2>&1; then
        # Sikeres build
        local built_file=""
        for pkgfile in *.pkg.tar.*; do
            [ -f "$pkgfile" ] || continue
            mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
            built_file="$REPO_ROOT/$OUTPUT_DIR/$pkgfile"
            ok "Build sikeres: $(basename "$pkgfile")"
            echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
            break
        done
        
        # Verzió kinyerése a fájlnévből
        if [ -n "$built_file" ]; then
            local actual_version=""
            actual_version=$(basename "$built_file" | sed "s/^${pkg}-//" | sed "s/-x86_64.*//" | sed "s/-any.*//" | sed "s/\.pkg\.tar\..*//")
            
            info "Ténylegesen épített verzió: $actual_version"
            
            # Helyi csomag: PKGBUILD frissítés
            if [ "$is_aur" = "false" ] && [ -n "$actual_version" ]; then
                update_pkgbuild_version "$pkg" "$actual_version"
            fi
        fi
    else
        error "Build sikertelen: $pkg"
    fi
    
    cd "$REPO_ROOT" 2>/dev/null || true
    rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
}

# PKGBUILD frissítése
update_pkgbuild_version() {
    local pkg="$1"
    local new_version="$2"
    
    [ -z "$new_version" ] && return 1
    
    cd "$REPO_ROOT/$pkg" 2>/dev/null || return 1
    [ ! -f PKGBUILD ] && return 1
    
    # Parse version
    local epoch="" pkgver="" pkgrel="1"
    
    if [[ "$new_version" == *:* ]]; then
        epoch="${new_version%%:*}"
        local rest="${new_version#*:}"
        pkgver="${rest%%-*}"
        pkgrel="${rest##*-}"
    else
        pkgver="${new_version%%-*}"
        pkgrel="${new_version##*-}"
    fi
    
    # Debug info
    debug "Frissítés: epoch=$epoch, pkgver=$pkgver, pkgrel=$pkgrel"
    
    # Epoch frissítése
    if [ -n "$epoch" ]; then
        if grep -q "^epoch=" PKGBUILD; then
            sed -i "s/^epoch=.*/epoch='$epoch'/" PKGBUILD
        else
            sed -i "/^pkgver=/i epoch='$epoch'" PKGBUILD
        fi
    fi
    
    # pkgver frissítése
    if grep -q "^pkgver=" PKGBUILD; then
        sed -i "s/^pkgver=.*/pkgver='$pkgver'/" PKGBUILD
    fi
    
    # pkgrel frissítése
    if grep -q "^pkgrel=" PKGBUILD; then
        sed -i "s/^pkgrel=.*/pkgrel='$pkgrel'/" PKGBUILD
    fi
    
    # .SRCINFO frissítése
    makepkg --printsrcinfo > .SRCINFO 2>/dev/null || true
    
    # Git
    git add PKGBUILD .SRCINFO 2>/dev/null || true
    echo "$pkg: $new_version" >> "$REPO_ROOT/updated_packages.txt"
    
    ok "PKGBUILD frissítve: $new_version"
    cd - >/dev/null 2>&1
}

# Fő futás
main() {
    info "=== BUILD RENDSZER ==="
    info "Kezdés: $(date)"
    info "Összes csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"
    
    # Reset
    rm -f "$REPO_ROOT/updated_packages.txt"
    rm -f "$REPO_ROOT/packages_to_clean.txt"
    rm -rf "$REPO_ROOT/build_aur" 2>/dev/null
    rm -rf "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null
    touch "$REPO_ROOT/updated_packages.txt"
    
    # Statisztika
    local total=0 built=0
    
    # AUR CSOMAGOK
    info "--- AUR CSOMAGOK (${#AUR_PACKAGES[@]}) ---"
    for pkg in "${AUR_PACKAGES[@]}"; do
        total=$((total + 1))
        build_package_smart "$pkg" "true"
        echo ""
    done
    
    # HELYI CSOMAGOK
    info "--- HELYI CSOMAGOK (${#LOCAL_PACKAGES[@]}) ---"
    for pkg in "${LOCAL_PACKAGES[@]}"; do
        total=$((total + 1))
        build_package_smart "$pkg" "false"
        echo ""
    done
    
    # VAN-E ÉPÍTETT CSOMAG?
    local built_count=0
    built_count=$(ls -1 "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null | wc -l)
    
    if [ "$built_count" -eq 0 ]; then
        ok "Nincs új csomag - minden naprakész!"
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
    info "  - Összes csomag: $total"
    info "  - Új csomagok: $built_count"
    if [ -s "$REPO_ROOT/updated_packages.txt" ]; then
        info "  - Frissített PKGBUILD-ok:"
        cat "$REPO_ROOT/updated_packages.txt" | while read line; do
            info "    * $line"
        done
    fi
    info "========================================"
}

# Git push
git_push_if_needed() {
    cd "$REPO_ROOT" 2>/dev/null || return 0
    
    if ! git status --porcelain 2>/dev/null | grep -q "."; then
        info "Nincs git változás."
        return 0
    fi
    
    info "Git változások push..."
    
    git add . 2>/dev/null || true
    
    local commit_msg="Auto-update: $(date +%Y-%m-%d)"
    if [ -s "$REPO_ROOT/updated_packages.txt" ]; then
        commit_msg="$commit_msg - $(cat "$REPO_ROOT/updated_packages.txt" | tr '\n' ', ' | sed 's/, $//')"
    fi
    
    git commit -m "$commit_msg" 2>/dev/null || true
    
    for attempt in 1 2 3; do
        if git push "$SSH_REPO_URL" main 2>&1; then
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

# Futtatás
main || error "Hiba történt, de a script nem állt meg."
exit 0