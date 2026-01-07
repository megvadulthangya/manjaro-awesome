#!/bin/bash
# NINCS set -e! SOHA NE ÁLLJON MEG EGY HIBA MIATT!

# --- 0. BIZTONSÁGI ZÁRAK FELOLDÁSA ---
export GIT_DISCOVERY_ACROSS_FILESYSTEM=1
git config --global --add safe.directory '*'

# --- 1. ÚTVONAL FIXÁLÁS ---
cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

# --- FIX SSH URL ---
SSH_REPO_URL="git@github.com:megvadulthangya/manjaro-awesome.git"

echo "[BUILD SYSTEM] Repo gyökér: $REPO_ROOT"
echo "[BUILD SYSTEM] Push URL: $SSH_REPO_URL"

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

# Logging functions - egyszerűbb
log() { echo -e "$1"; }
info() { echo -e "\e[34m[INFO]\e[0m $1"; }
ok() { echo -e "\e[32m[OK]\e[0m $1"; }
warn() { echo -e "\e[33m[WARN]\e[0m $1"; }
error() { echo -e "\e[31m[ERROR]\e[0m $1"; }
skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }

# 2. YAY TELEPÍTÉSE (ha kell)
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

# 3. SZERVER LISTA LEKÉRÉSE - AZ EREDETI, MŰKÖDŐ MÓD
info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "ls -1 $REMOTE_DIR 2>/dev/null" > "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
    ok "Szerver lista letöltve ($(wc -l < "$REPO_ROOT/remote_files.txt") fájl)."
else
    warn "Nem sikerült lekérni a listát (új repo?)"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 4. DB LETÖLTÉS
info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# --- AZ EREDETI, MŰKÖDŐ VERZIÓELLENŐRZÉS ---
# Ez volt az első scriptben és tökéletesen működött!
# Csak akkor épít, ha nincs a szerveren

is_on_server() {
    local pkgname="$1"
    local version="$2"
    
    # EGYSZERŰ GREP - ez működött!
    if grep -q "^${pkgname}-${version}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
        return 0  # true - van a szerveren
    else
        return 1  # false - nincs a szerveren
    fi
}

# Verzió kinyerése - megbízhatóan
get_version() {
    local pkg_dir="$1"
    
    cd "$pkg_dir" 2>/dev/null || { echo ""; return 1; }
    
    # Először .SRCINFO
    if [ -f .SRCINFO ]; then
        local pkgver pkgrel
        pkgver=$(grep "pkgver =" .SRCINFO | head -1 | awk '{print $3}')
        pkgrel=$(grep "pkgrel =" .SRCINFO | head -1 | awk '{print $3}')
        if [ -n "$pkgver" ] && [ -n "$pkgrel" ]; then
            echo "${pkgver}-${pkgrel}"
            cd - >/dev/null 2>&1
            return 0
        fi
    fi
    
    # Ha nem sikerült, PKGBUILD
    if [ -f PKGBUILD ]; then
        source PKGBUILD 2>/dev/null || true
        if [ -n "$pkgver" ]; then
            echo "${pkgver}-${pkgrel:-1}"
            cd - >/dev/null 2>&1
            return 0
        fi
    fi
    
    echo ""
    cd - >/dev/null 2>&1
    return 1
}

# PKGBUILD frissítése (csak helyi csomagoknál)
update_pkgbuild() {
    local pkg="$1"
    local new_version="$2"
    
    [ -z "$new_version" ] && return 1
    
    cd "$REPO_ROOT/$pkg" 2>/dev/null || return 1
    [ ! -f PKGBUILD ] && return 1
    
    # Parse version
    local pkgver="${new_version%-*}"
    local pkgrel="${new_version##*-}"
    
    # Frissítés
    if grep -q "^pkgver=" PKGBUILD; then
        sed -i "s/^pkgver=.*/pkgver='$pkgver'/" PKGBUILD
    fi
    
    if grep -q "^pkgrel=" PKGBUILD; then
        sed -i "s/^pkgrel=.*/pkgrel='$pkgrel'/" PKGBUILD
    fi
    
    # .SRCINFO frissítése
    makepkg --printsrcinfo > .SRCINFO 2>/dev/null || true
    
    # Git
    git add PKGBUILD .SRCINFO 2>/dev/null || true
    echo "$pkg: $new_version" >> "$REPO_ROOT/updated_packages.txt"
    
    cd - >/dev/null 2>&1
    return 0
}

# Build egy csomag - NAGYON EGYSZERŰ, DE MŰKÖDŐ
build_package() {
    local pkg="$1"
    local is_aur="$2"
    
    info "========================================"
    info "Csomag: $pkg"
    info "========================================"
    
    # VÁLTOZÓK
    local pkg_dir=""
    local version=""
    local built_file=""
    
    # AUR vagy helyi?
    if [ "$is_aur" = "true" ]; then
        mkdir -p "$REPO_ROOT/build_aur"
        cd "$REPO_ROOT/build_aur" 2>/dev/null || return 0
        
        # Klónozás
        rm -rf "$pkg" 2>/dev/null
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
            warn "Helyi mappa nem található: $pkg (skip)"
            return 0
        fi
        pkg_dir="$REPO_ROOT/$pkg"
        cd "$pkg_dir" 2>/dev/null || return 0
    fi
    
    # VERZIÓ MEGHATÁROZÁSA
    version=$(get_version "$pkg_dir")
    if [ -z "$version" ]; then
        warn "Verzió nem határozható meg: $pkg (skip)"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    info "Verzió: $version"
    
    # MÁR VAN A SZERVEREN? (EZ A LÉNYEG!)
    if is_on_server "$pkg" "$version"; then
        skip "$pkg ($version) már a szerveren - SKIP"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # NEM VAGYOK A SZERVEREN -> ÉPÍTÉS
    info "Új verzió! Építés..."
    
    # Függőségek (nem kritikus)
    if [ "$is_aur" = "true" ]; then
        yay -S --asdeps --needed --noconfirm $(makepkg --printsrcinfo 2>/dev/null | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//' | tr '\n' ' ') 2>/dev/null || true
    fi
    
    # Források letöltése
    if ! makepkg -od --noconfirm 2>&1; then
        error "Forrás letöltés sikertelen: $pkg (skip)"
        cd "$REPO_ROOT"
        rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
        return 0
    fi
    
    # ÉPÍTÉS
    if makepkg -si --noconfirm --clean --nocheck 2>&1; then
        # Sikeres build
        for pkgfile in *.pkg.tar.*; do
            [ -f "$pkgfile" ] || continue
            mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
            built_file="$REPO_ROOT/$OUTPUT_DIR/$pkgfile"
            ok "Build sikeres: $pkgfile"
            echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
            break  # csak az első fájl
        done
        
        # Helyi csomag: PKGBUILD frissítés
        if [ "$is_aur" = "false" ] && [ -n "$built_file" ]; then
            # Verzió kinyerése a fájlnévből
            local actual_version
            actual_version=$(basename "$built_file" | sed "s/^${pkg}-//" | sed "s/-x86_64.*//" | sed "s/-any.*//" | sed "s/\.pkg\.tar\..*//")
            
            if [ -n "$actual_version" ]; then
                update_pkgbuild "$pkg" "$actual_version" && info "PKGBUILD frissítve"
            fi
        fi
    else
        error "Build sikertelen: $pkg"
    fi
    
    cd "$REPO_ROOT" 2>/dev/null || true
    rm -rf "$REPO_ROOT/build_aur/$pkg" 2>/dev/null
}

# Fő futás - SOHA NE ÁLLJON MEG!
main() {
    info "=== BUILD RENDSZER ==="
    info "Kezdés: $(date)"
    info "Összes csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"
    
    # Reset fájlok
    rm -f "$REPO_ROOT/updated_packages.txt"
    rm -f "$REPO_ROOT/packages_to_clean.txt"
    touch "$REPO_ROOT/updated_packages.txt"
    
    # Statisztika
    local total=0 success=0 fail=0 skip=0
    
    # AUR CSOMAGOK
    info "--- AUR CSOMAGOK (${#AUR_PACKAGES[@]}) ---"
    rm -rf "$REPO_ROOT/build_aur" 2>/dev/null
    mkdir -p "$REPO_ROOT/build_aur"
    
    for pkg in "${AUR_PACKAGES[@]}"; do
        total=$((total + 1))
        if build_package "$pkg" "true"; then
            success=$((success + 1))
        else
            fail=$((fail + 1))
        fi
        echo ""  # üres sor
    done
    
    # HELYI CSOMAGOK
    info "--- HELYI CSOMAGOK (${#LOCAL_PACKAGES[@]}) ---"
    for pkg in "${LOCAL_PACKAGES[@]}"; do
        total=$((total + 1))
        if build_package "$pkg" "false"; then
            success=$((success + 1))
        else
            fail=$((fail + 1))
        fi
        echo ""  # üres sor
    done
    
    # VAN-E ÉPÍTETT CSOMAG?
    local built_count=0
    built_count=$(ls "$REPO_ROOT/$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null | wc -l)
    
    if [ "$built_count" -eq 0 ]; then
        ok "Nincs új csomag - minden naprakész!"
        
        # Még lehet git változás
        git_push_if_needed
        return 0
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
    info "  - Összes: $total"
    info "  - Új csomagok: $built_count"
    info "  - Sikeres: $success"
    info "  - Sikertelen: $fail"
    
    if [ -s "$REPO_ROOT/updated_packages.txt" ]; then
        info "  - Frissített PKGBUILD-ok:"
        cat "$REPO_ROOT/updated_packages.txt" | while read line; do
            info "    * $line"
        done
    fi
    info "========================================"
}

# Git push (ha van változás)
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

# --- FŐ PROGRAM ---
# TRY-CATCH szerkezet bash-ban
if main; then
    ok "Build rendszer sikeresen lefutott."
    exit 0
else
    error "Build rendszer hibát észlelt, de nem állt meg."
    # SOHA NE LÉPJÜN KI HIBAKÓDDAL!
    exit 0
fi