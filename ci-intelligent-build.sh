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

echo "[INTELLIGENT BUILD] Repo gyökér: $REPO_ROOT"
echo "[INTELLIGENT BUILD] Push URL: $SSH_REPO_URL"

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
log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_succ() { echo -e "\e[32m[OK]\e[0m $1"; }
log_skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }
log_err()  { echo -e "\e[31m[HIBA]\e[0m $1"; }
log_debug() { echo -e "\e[35m[DEBUG]\e[0m $1"; }
log_warn() { echo -e "\e[33m[FIGYELEM]\e[0m $1"; }
log_dep()  { echo -e "\e[36m[FÜGGŐSÉG]\e[0m $1"; }

# 2. YAY TELEPÍTÉSE ÉS KONFIGURÁLÁSA
install_yay() {
    if ! command -v yay &> /dev/null; then
        log_info "Yay telepítése..."
        cd /tmp
        if git clone https://aur.archlinux.org/yay.git 2>/dev/null; then
            cd yay
            yes | makepkg -si --noconfirm 2>&1 | grep -v "warning:" || {
                log_warn "Alternatív yay telepítés..."
                pacman -S --noconfirm go 2>/dev/null || true
                if command -v go &> /dev/null; then
                    go install github.com/Jguer/yay@latest 2>/dev/null || true
                fi
            }
            cd /tmp
            rm -rf yay 2>/dev/null || true
        fi
        cd "$REPO_ROOT"
    fi
    
    if command -v yay &> /dev/null; then
        log_info "Yay konfigurálása automatikus módra..."
        yay -Y --gendb --noconfirm 2>/dev/null || true
        yay -Y --devel --save --noconfirm 2>/dev/null || true
        yay -Y --combinedupgrade --save --noconfirm 2>/dev/null || true
        yay -Y --nocleanmenu --save --noconfirm 2>/dev/null || true
        yay -Y --nodiffmenu --save --noconfirm 2>/dev/null || true
        yay -Y --noeditmenu --save --noconfirm 2>/dev/null || true
        yay -Y --removemake --save --noconfirm 2>/dev/null || true
        yay -Y --upgrademenu --save --noconfirm 2>/dev/null || true
    fi
}

install_yay

# 3. SZERVER LISTA LEKÉRÉSE - CSAK FÁJLOK, EGYSZERŰ LISTA
log_info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "ls -1 $REMOTE_DIR 2>/dev/null" > "$REPO_ROOT/remote_files.txt"; then
    log_succ "Szerver lista letöltve ($(wc -l < "$REPO_ROOT/remote_files.txt") fájl)."
else
    log_warn "Nem sikerült lekérni a listát! (De folytatjuk)"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 4. DB LETÖLTÉS
log_info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# --- JÓ MŰKÖDŐ VERZIÓELLENŐRZÉS ---

# Ellenőrzi, hogy a csomag már a szerveren van-e PONTOS VERZIÓVAL
is_on_server_exact_version() {
    local pkgname="$1"
    local exact_version="$2"
    
    # Ha megtaláljuk a pontos verziót, akkor TRUE
    if grep -q "^${pkgname}-${exact_version}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
        return 0
    fi
    
    # Ha epoch van a verzióban, próbáljuk anélkül is
    if [[ "$exact_version" == *:* ]]; then
        local version_without_epoch="${exact_version#*:}"
        if grep -q "^${pkgname}-${version_without_epoch}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
            return 0
        fi
    fi
    
    return 1
}

# Verzió kinyerése PKGBUILD-ból (megbízhatóan)
get_pkg_version() {
    local pkg_dir="$1"
    
    cd "$pkg_dir" || return 1
    
    local version=""
    
    # Először próbáljuk a .SRCINFO fájlt
    if [ -f .SRCINFO ]; then
        # Az igazi, épített verziót kell kinyerni
        version=$(grep "pkgver =" .SRCINFO | head -1 | awk '{print $3}')
        local pkgrel=$(grep "pkgrel =" .SRCINFO | head -1 | awk '{print $3}')
        
        if [ -n "$version" ] && [ -n "$pkgrel" ]; then
            version="${version}-${pkgrel}"
        fi
    fi
    
    # Ha nem sikerült, próbáljuk a PKGBUILD-ot
    if [ -z "$version" ] && [ -f PKGBUILD ]; then
        # Egyszerű grep, nem source-olunk
        local pkgver=$(grep '^pkgver=' PKGBUILD | head -1 | cut -d= -f2 | tr -d " \t'\"")
        local pkgrel=$(grep '^pkgrel=' PKGBUILD | head -1 | cut -d= -f2 | tr -d " \t'\"")
        
        if [ -n "$pkgver" ]; then
            version="${pkgver}-${pkgrel:-1}"
        fi
    fi
    
    # Epoch kezelése
    if [ -f PKGBUILD ]; then
        local epoch=$(grep '^epoch=' PKGBUILD | head -1 | cut -d= -f2 | tr -d " \t'\"")
        if [ -n "$epoch" ] && [ "$epoch" != "0" ]; then
            version="${epoch}:${version}"
        fi
    fi
    
    echo "$version"
    
    cd - > /dev/null || return 1
}

# PKGBUILD frissítése a ténylegesen épített verzióval
update_pkgbuild_with_actual_version() {
    local pkg="$1"
    local built_pkg_file="$2"
    
    if [ ! -f "$built_pkg_file" ]; then
        log_warn "Nincs épített fájl: $pkg"
        return 1
    fi
    
    cd "$REPO_ROOT/$pkg" || return 1
    
    if [ ! -f PKGBUILD ]; then
        log_warn "Nincs PKGBUILD a(z) $pkg mappában"
        cd - > /dev/null || return 1
        return 1
    fi
    
    # Kinyerjük a verziót az épített fájlnévből
    local filename
    filename=$(basename "$built_pkg_file")
    
    # Példa: tilix-git-1.9.4.r35.g1234567-1-x86_64.pkg.tar.zst
    # Kinyerjük: 1.9.4.r35.g1234567-1
    
    local version_part
    version_part=$(echo "$filename" | sed "s/^${pkg}-//" | sed "s/-x86_64.*//" | sed "s/-any.*//" | sed "s/\.pkg\.tar\..*//")
    
    if [ -z "$version_part" ]; then
        log_warn "Nem sikerült kinyerni a verziót: $filename"
        cd - > /dev/null || return 1
        return 1
    fi
    
    # Kinyerjük a részleteket
    local epoch_val="" new_pkgver="" new_pkgrel="1"
    
    # Parse the version string
    if [[ "$version_part" == *:* ]]; then
        # Contains epoch
        epoch_val="${version_part%%:*}"
        local rest="${version_part#*:}"
        new_pkgver="${rest%%-*}"
        new_pkgrel="${rest##*-}"
    else
        # No epoch
        new_pkgver="${version_part%%-*}"
        new_pkgrel="${version_part##*-}"
    fi
    
    log_debug "PKGBUILD frissítés: $pkg -> pkgver:$new_pkgver pkgrel:$new_pkgrel"
    
    # Frissítjük a PKGBUILD-ot
    local changed=0
    
    # Epoch frissítése
    if [ -n "$epoch_val" ]; then
        if grep -q "^epoch=" PKGBUILD; then
            sed -i "s/^epoch=.*/epoch='$epoch_val'/" PKGBUILD
            changed=1
        else
            sed -i "/^pkgver=/i epoch='$epoch_val'" PKGBUILD
            changed=1
        fi
    fi
    
    # pkgver frissítése
    if grep -q "^pkgver=" PKGBUILD; then
        sed -i "s/^pkgver=.*/pkgver='$new_pkgver'/" PKGBUILD
        changed=1
    fi
    
    # pkgrel frissítése
    if grep -q "^pkgrel=" PKGBUILD; then
        sed -i "s/^pkgrel=.*/pkgrel='$new_pkgrel'/" PKGBUILD
        changed=1
    fi
    
    if [ "$changed" -eq 1 ]; then
        # Frissítjük a .SRCINFO fájlt
        makepkg --printsrcinfo > .SRCINFO 2>/dev/null || true
        log_succ "PKGBUILD frissítve: $pkg -> $version_part"
        
        # Git-hez hozzáadjuk
        git add PKGBUILD .SRCINFO 2>/dev/null || true
        
        # Verzióváltozás naplózása
        echo "$pkg: $version_part" >> "$REPO_ROOT/updated_packages.txt"
        
        cd - > /dev/null || return 1
        return 0
    else
        log_skip "Nincs változás a PKGBUILD-ban: $pkg"
        cd - > /dev/null || return 1
        return 1
    fi
}

# Fő build funkció - HELYESEN MŰKÖDŐ VERZIÓELLENŐRZÉSSEL
build_package_smart() {
    local pkg="$1"
    local is_aur="$2"
    
    log_info "========================================"
    log_info "Csomag feldolgozása: $pkg"
    log_info "========================================"
    
    cd "$REPO_ROOT" || return 1
    
    local pkg_dir=""
    local current_version=""
    
    if [ "$is_aur" = "true" ]; then
        # AUR csomag
        mkdir -p build_aur
        cd build_aur || return 1
        
        if [ -d "$pkg" ]; then 
            rm -rf "$pkg"
        fi
        
        log_info "AUR klónozás: $pkg"
        if ! git clone "https://aur.archlinux.org/$pkg.git" 2>/dev/null; then
            log_err "AUR klónozás sikertelen: $pkg"
            cd "$REPO_ROOT" || return 1
            return 1
        fi
        
        pkg_dir="$REPO_ROOT/build_aur/$pkg"
        cd "$pkg" || return 1
    else
        # Helyi csomag
        if [ ! -d "$pkg" ]; then 
            log_err "Helyi mappa nem található: $pkg"
            return 1
        fi
        pkg_dir="$REPO_ROOT/$pkg"
        cd "$pkg" || return 1
    fi
    
    # 1. VERZIÓ MEGHATÁROZÁSA (a jelenlegi PKGBUILD-ból)
    current_version=$(get_pkg_version "$pkg_dir")
    
    if [ -z "$current_version" ] || [ "$current_version" = "-1" ]; then
        log_err "Nem sikerült meghatározni a verziót: $pkg"
        if [ "$is_aur" = "true" ]; then
            cd "$REPO_ROOT"
            rm -rf "build_aur/$pkg" 2>/dev/null || true
        fi
        return 1
    fi
    
    log_debug "Aktuális verzió: $current_version"
    
    # 2. VERZIÓ ELLENŐRZÉS - CSAK AKTOR SKIP, HA UGYANAZ A VERZIÓ
    if is_on_server_exact_version "$pkg" "$current_version"; then
        log_skip "$pkg ($current_version) -> UGYANAZ A VERZIÓ MÁR A SZERVEREN."
        if [ "$is_aur" = "true" ]; then
            cd "$REPO_ROOT"
            rm -rf "build_aur/$pkg" 2>/dev/null || true
        else
            cd "$REPO_ROOT"
        fi
        return 0
    fi
    
    # 3. HA NEM UGYANAZ A VERZIÓ, ÉPÍTJÜK
    log_info "ÚJ VERZIÓ ÉSZLELVE! Építés: $pkg ($current_version)"
    
    # Függőségek ellenőrzése
    log_dep "Függőségek ellenőrzése..."
    if [ "$is_aur" = "true" ]; then
        yay -S --asdeps --needed --noconfirm $(makepkg --printsrcinfo 2>/dev/null | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//' | tr '\n' ' ') 2>/dev/null || true
    fi
    
    # Forrás letöltés ellenőrzése
    if ! makepkg -od --noconfirm 2>&1; then
        log_err "Forrás letöltési hiba: $pkg"
        if [ "$is_aur" = "true" ]; then
            cd "$REPO_ROOT"
            rm -rf "build_aur/$pkg" 2>/dev/null || true
        fi
        return 1
    fi
    
    # Építés
    if makepkg -si --noconfirm --clean --nocheck 2>&1; then
        # Sikeres build
        shopt -s nullglob
        local built_files=()
        for pkgfile in *.pkg.tar.*; do
            if [ -f "$pkgfile" ]; then
                mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
                built_files+=("$REPO_ROOT/$OUTPUT_DIR/$pkgfile")
                log_succ "$pkg építése sikeres: $pkgfile"
                echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
            fi
        done
        shopt -u nullglob
        
        # 4. HA HELYI CSOMAG, FRISSÍTJÜK A PKGBUILD VERZIÓT
        if [ "$is_aur" = "false" ] && [ ${#built_files[@]} -gt 0 ]; then
            # Az első épített fájlt használjuk
            local first_built_file="${built_files[0]}"
            if update_pkgbuild_with_actual_version "$pkg" "$first_built_file"; then
                log_succ "PKGBUILD verzió frissítve"
            fi
        fi
    else
        log_err "Build hiba: $pkg"
    fi
    
    cd "$REPO_ROOT" || return 1
    
    # Takarítás
    if [ "$is_aur" = "true" ]; then 
        rm -rf "build_aur/$pkg" 2>/dev/null || true
    fi
}

# Git push funkció - CSAK EGYSZER A VÉGÉN
git_push_all_changes() {
    log_info "=== GIT VÁLTOZÁSOK PUSH (EGYSZER A VÉGÉN) ==="
    
    cd "$REPO_ROOT" || return 1
    
    # Ellenőrizzük, van-e változás
    if ! git status --porcelain | grep -q "."; then
        log_info "Nincs változás a git repository-ban."
        return 0
    fi
    
    log_info "Változások észlelve:"
    git status --porcelain
    
    # Commit üzenet összeállítása
    local commit_message="Auto-update: PKGBUILD version updates"
    
    if [ -f "$REPO_ROOT/updated_packages.txt" ] && [ -s "$REPO_ROOT/updated_packages.txt" ]; then
        commit_message="$commit_message\n\nFrissített csomagok:\n"
        commit_message="$commit_message$(cat "$REPO_ROOT/updated_packages.txt")"
    fi
    
    # Minden változást hozzáadunk
    git add .
    
    # Commit
    git commit -m "$commit_message"
    
    # Push
    log_info "Push to GitHub..."
    if git push "$SSH_REPO_URL" main 2>/dev/null; then
        log_succ "Git push sikeres!"
        return 0
    else
        log_err "Git push sikertelen!"
        return 1
    fi
}

# ================================
# FŐ FUTTATÁS
# ================================

log_info "=== INTELLIGENS BUILD RENDSZER ==="
log_info "Kezdés: $(date)"
log_info "Összes csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"

# Frissített csomagok listája
rm -f "$REPO_ROOT/updated_packages.txt"
touch "$REPO_ROOT/updated_packages.txt"

# AUR csomagok
log_info "--- AUR CSOMAGOK (${#AUR_PACKAGES[@]}) ---"
rm -rf build_aur 2>/dev/null
mkdir -p build_aur

for pkg in "${AUR_PACKAGES[@]}"; do
    build_package_smart "$pkg" "true"
done

# Helyi csomagok
log_info "--- SAJÁT CSOMAGOK (${#LOCAL_PACKAGES[@]}) ---"
for pkg in "${LOCAL_PACKAGES[@]}"; do
    build_package_smart "$pkg" "false"
done

# ================================
# FELTÖLTÉS ÉS RENDSZERFRISSÍTÉS
# ================================

cd "$REPO_ROOT" || exit 1

# Ellenőrizzük van-e épített csomag
shopt -s nullglob
pkg_files=("$OUTPUT_DIR"/*.pkg.tar.*)
shopt -u nullglob

if [ ${#pkg_files[@]} -eq 0 ]; then
    log_succ "Nincs új csomag - minden naprakész!"
    
    # Még lehetnek PKGBUILD változások (ha manuálisan módosítottál)
    git_push_all_changes
    exit 0
fi

log_info "=== FELTÖLTÉS ÉS ADATBÁZIS FRISSÍTÉS ==="

# Adatbázis frissítése
cd "$OUTPUT_DIR" || exit 1
log_info "Épített csomagok: $(ls *.pkg.tar.* 2>/dev/null | wc -l) db"

if [ -f "${REPO_DB_NAME}.db.tar.gz" ]; then
    log_info "Meglévő adatbázis bővítése..."
    repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || log_err "repo-add hiba"
else
    log_info "Új adatbázis létrehozása..."
    repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || log_err "repo-add hiba"
fi

# Feltöltés a szerverre
log_info "Feltöltés a szerverre..."
cd "$REPO_ROOT" || exit 1

if scp $SSH_OPTS "$OUTPUT_DIR"/* "$VPS_USER@$VPS_HOST:$REMOTE_DIR/" 2>/dev/null; then
    log_succ "Feltöltés sikeres!"
else
    # Második próbálkozás
    sleep 3
    if scp $SSH_OPTS "$OUTPUT_DIR"/* "$VPS_USER@$VPS_HOST:$REMOTE_DIR/" 2>/dev/null; then
        log_succ "Második próbálkozás sikeres!"
    else
        log_err "Feltöltés sikertelen!"
        exit 1
    fi
fi

# Régi csomagok takarítása a szerveren
if [ -f packages_to_clean.txt ] && [ -s packages_to_clean.txt ]; then
    log_info "Régi csomagok takarítása a szerveren..."
    while read -r pkg_to_clean || [ -n "$pkg_to_clean" ]; do
        ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" \
            "cd $REMOTE_DIR && ls -t ${pkg_to_clean}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | xargs -r rm -f" 2>/dev/null || true
    done < packages_to_clean.txt
fi

# ================================
# GIT PUSH - CSAK EGYSZER A VÉGÉN!
# ================================

git_push_all_changes

log_info "========================================"
log_succ "BUILD RENDSZER SIKERESEN BEFEJEZVE!"
log_info "Idő: $(date)"
log_info "Összegzés:"
log_info "  - Összes feldolgozott csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"
shopt -s nullglob
pkg_count=("$OUTPUT_DIR"/*.pkg.tar.*)
shopt -u nullglob
log_info "  - Új csomagok építve: ${#pkg_count[@]}"
if [ -s "$REPO_ROOT/updated_packages.txt" ]; then
    log_info "  - Frissített PKGBUILD-ok:"
    cat "$REPO_ROOT/updated_packages.txt" | while read -r line; do
        log_info "    * $line"
    done
fi
log_info "========================================"