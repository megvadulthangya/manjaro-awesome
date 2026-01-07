#!/bin/bash
set -e

# --- 0. BIZTONSÁGI ZÁRAK FELOLDÁSA ---
export GIT_DISCOVERY_ACROSS_FILESYSTEM=1
git config --global --add safe.directory '*'

# --- 1. ÚTVONAL FIXÁLÁS ---
cd "$(dirname "$0")"
REPO_ROOT=$(pwd)

# --- SECRETS ÉS KONFIGURÁCIÓ ---
# Ezeket a GitHub Secrets-ből kell betölteni
# VPS_USER, VPS_HOST, GITHUB_TOKEN, SSH_PRIVATE_KEY
SSH_REPO_URL="git@github.com:megvadulthangya/manjaro-awesome.git"
GIT_HTTPS_URL="https://github.com/megvadulthangya/manjaro-awesome.git"

# SSH kulcs beállítása GitHub-hoz
mkdir -p ~/.ssh
if [ -n "$SSH_PRIVATE_KEY" ]; then
    echo "$SSH_PRIVATE_KEY" > ~/.ssh/id_rsa
    chmod 600 ~/.ssh/id_rsa
fi

# GitHub host hozzáadása ismert hosts-hoz
ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null

echo "[INTELLIGENT BUILD] Repo gyökér: $REPO_ROOT"
echo "[INTELLIGENT BUILD] VPS: $VPS_USER@$VPS_HOST"

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
VERSION_TRACKING_DIR="version_tracking"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"

mkdir -p "$REPO_ROOT/$OUTPUT_DIR"
mkdir -p "$REPO_ROOT/$VERSION_TRACKING_DIR"

# --- GIT KONFIGURÁCIÓ ---
git config --global user.name "GitHub Action Bot"
git config --global user.email "action@github.com"
git config --global pull.rebase false

# Logging functions
log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_succ() { echo -e "\e[32m[OK]\e[0m $1"; }
log_skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }
log_err()  { echo -e "\e[31m[HIBA]\e[0m $1"; }
log_debug() { echo -e "\e[35m[DEBUG]\e[0m $1"; }
log_warn() { echo -e "\e[33m[FIGYELEM]\e[0m $1"; }
log_dep()  { echo -e "\e[36m[FÜGGŐSÉG]\e[0m $1"; }
log_git()  { echo -e "\e[36m[GIT]\e[0m $1"; }

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
    
    # Yay konfigurálása TELJESEN AUTOMATA módra
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

# 3. SZERVER LISTA LEKÉRÉSE
log_info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "ls -1 $REMOTE_DIR 2>/dev/null" > "$REPO_ROOT/remote_files.txt"; then
    log_succ "Szerver lista letöltve."
else
    log_warn "Nem sikerült lekérni a listát! (De folytatjuk)"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 4. DB LETÖLTÉS
log_info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# --- SEGÉDFÜGGVÉNYEK ---

# Ellenőrzi, hogy a csomag már a szerveren van-e
is_on_server() {
    local pkgname="$1"
    local version="$2"
    
    # Többféle formátumot is elfogadunk
    # 1. Teljes verzióval (epoch:pkgver-pkgrel)
    if grep -q "^${pkgname}-${version}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
        return 0
    fi
    
    # 2. Ha a version tartalmaz epoch-ot, próbáljuk anélkül is
    if [[ "$version" == *:* ]]; then
        local version_without_epoch="${version#*:}"
        if grep -q "^${pkgname}-${version_without_epoch}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
            return 0
        fi
    fi
    
    # 3. Próbáljuk meg fordítva: ha nincs epoch, de a szerveren van
    if [[ "$version" != *:* ]] && grep -q "^${pkgname}-[0-9]*:${version}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
        return 0
    fi
    
    return 1
}

# Verzió kinyerése PKGBUILD-ból
extract_version_from_pkgbuild() {
    local pkg_dir="$1"
    cd "$pkg_dir" || return 1
    
    local epoch_val="" pkgver_val="" pkgrel_val="1"
    
    if [ -f PKGBUILD ]; then
        # Kinyerjük az epoch-ot
        epoch_val=$(grep '^epoch=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "")
        
        # Kinyerjük a verziót
        pkgver_val=$(grep '^pkgver=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "")
        pkgrel_val=$(grep '^pkgrel=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "1")
        
        # Ha üres valamelyik, próbáljuk source-olni
        if [ -z "$pkgver_val" ]; then
            # shellcheck disable=SC1091
            source PKGBUILD 2>/dev/null || true
            epoch_val="${epoch:-}"
            pkgver_val="${pkgver:-}"
            pkgrel_val="${pkgrel:-1}"
        fi
    fi
    
    # Epoch kezelése
    if [ -n "$epoch_val" ] && [ "$epoch_val" != "" ]; then
        echo "${epoch_val}:${pkgver_val}-${pkgrel_val}"
    else
        echo "${pkgver_val}-${pkgrel_val}"
    fi
    
    cd - > /dev/null || return 1
}

# Verzió mentése előtte-utána
save_version() {
    local pkg="$1"
    local pkg_dir="$2"
    local suffix="$3"
    
    local version_file="$REPO_ROOT/$VERSION_TRACKING_DIR/${pkg}_${suffix}.version"
    extract_version_from_pkgbuild "$pkg_dir" > "$version_file"
    
    local version_content
    version_content=$(cat "$version_file" 2>/dev/null || echo "N/A")
    log_debug "Verzió mentve ($suffix): $pkg -> $version_content"
}

# Visszaírja a verziót a PKGBUILD-be, ha változott
update_pkgbuild_if_changed() {
    local pkg="$1"
    local pkg_dir="$2"
    
    local before_file="$REPO_ROOT/$VERSION_TRACKING_DIR/${pkg}_before.version"
    local after_file="$REPO_ROOT/$VERSION_TRACKING_DIR/${pkg}_after.version"
    
    if [ ! -f "$before_file" ] || [ ! -f "$after_file" ]; then
        log_warn "Verziófájlok hiányoznak: $pkg"
        return 1
    fi
    
    local before_version after_version
    before_version=$(cat "$before_file")
    after_version=$(cat "$after_file")
    
    if [ "$before_version" != "$after_version" ]; then
        log_info "VERZIÓVÁLTOZÁS: $pkg"
        log_info "  Régi: $before_version"
        log_info "  Új:   $after_version"
        
        cd "$pkg_dir" || return 1
        
        # Frissítjük a .SRCINFO fájlt
        if [ -f PKGBUILD ]; then
            makepkg --printsrcinfo > .SRCINFO 2>/dev/null || true
            log_succ ".SRCINFO frissítve: $pkg"
            
            # Git-hez hozzáadjuk
            git add PKGBUILD .SRCINFO 2>/dev/null || true
            
            # Verzióváltozás naplózása
            echo "$pkg: $before_version -> $after_version" >> "$REPO_ROOT/version_changes.txt"
        fi
        
        cd - > /dev/null || return 1
        return 0
    else
        log_skip "Verzió változatlan: $pkg"
        return 1
    fi
}

# Intelligens build függvény - verzió követéssel
build_package_intelligent() {
    local pkg="$1"
    local is_aur="$2"
    
    log_info "========================================"
    log_info "Csomag feldolgozása: $pkg"
    log_info "========================================"
    
    cd "$REPO_ROOT" || return 1

    local pkg_dir=""
    
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
        
        # ELŐTTE: Mentjük az eredeti verziót
        save_version "$pkg" "$pkg_dir" "before"
    fi
    
    # Verzió ellenőrzés (korai skip)
    local current_version
    current_version=$(extract_version_from_pkgbuild "$pkg_dir")
    
    if [ "$current_version" != "N/A" ] && [ "$current_version" != "-1" ] && is_on_server "$pkg" "$current_version"; then
        log_skip "$pkg ($current_version) -> MÁR A SZERVEREN VAN."
        if [ "$is_aur" = "true" ]; then
            cd "$REPO_ROOT"
            rm -rf "build_aur/$pkg" 2>/dev/null || true
        else
            cd "$REPO_ROOT"
        fi
        return 0
    fi
    
    # Függőségek telepítése
    log_dep "Függőségek ellenőrzése..."
    if [ "$is_aur" = "true" ]; then
        # AUR csomag függőségei yay-vel
        yay -S --asdeps --needed --noconfirm $(makepkg --printsrcinfo 2>/dev/null | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//' | tr '\n' ' ') 2>/dev/null || true
    else
        # Helyi csomag függőségei
        if [ -f PKGBUILD ]; then
            # shellcheck disable=SC1091
            source PKGBUILD 2>/dev/null || true
            local all_deps=("${depends[@]}" "${makedepends[@]}")
            if [ ${#all_deps[@]} -gt 0 ]; then
                log_dep "Telepítendő függőségek: ${all_deps[*]}"
                for dep in "${all_deps[@]}"; do
                    # Tisztítjuk a függőség nevet
                    local clean_dep
                    clean_dep=$(echo "$dep" | sed 's/[<=>].*//')
                    if [ -n "$clean_dep" ] && ! pacman -Qi "$clean_dep" > /dev/null 2>&1; then
                        sudo pacman -S --noconfirm "$clean_dep" 2>/dev/null || true
                    fi
                done
            fi
        fi
    fi
    
    # Forrás letöltés ellenőrzése
    log_debug "Források letöltése..."
    if ! makepkg -od --noconfirm 2>&1; then
        log_err "Forrás letöltési hiba: $pkg"
        if [ "$is_aur" = "true" ]; then
            cd "$REPO_ROOT"
            rm -rf "build_aur/$pkg" 2>/dev/null || true
        else
            cd "$REPO_ROOT"
        fi
        return 1
    fi
    
    # Építés
    log_info "Építés: $pkg ($current_version)"
    
    if makepkg -si --noconfirm --clean --nocheck 2>&1; then
        # Sikeres build
        shopt -s nullglob
        for pkgfile in *.pkg.tar.*; do
            if [ -f "$pkgfile" ]; then
                mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
                log_succ "$pkg építése sikeres: $pkgfile"
                echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
            fi
        done
        shopt -u nullglob
        
        # UTÁNA: Helyi csomagoknál mentjük az új verziót és frissítjük
        if [ "$is_aur" = "false" ]; then
            save_version "$pkg" "$pkg_dir" "after"
            update_pkgbuild_if_changed "$pkg" "$pkg_dir"
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

# --- GIT PUSH FUNKCIÓ (javított) ---
git_push_changes() {
    log_git "Git változások ellenőrzése..."
    
    cd "$REPO_ROOT" || return 1
    
    # Ellenőrizzük, van-e változás
    if ! git status --porcelain | grep -q "."; then
        log_git "Nincs változás a git repository-ban."
        return 0
    fi
    
    log_git "Változások észlelve:"
    git status --porcelain
    
    # Összegyűjtjük a commit üzenetet
    local commit_message="Auto-update: PKGBUILD version updates"
    
    if [ -s "$REPO_ROOT/version_changes.txt" ]; then
        commit_message="$commit_message\n\n$(cat "$REPO_ROOT/version_changes.txt")"
    fi
    
    # Hozzáadjuk az összes változást
    git add .
    
    # Commit
    log_git "Commit készítése..."
    git commit -m "$commit_message"
    
    # Próbáljuk először HTTPS-el (ha van GITHUB_TOKEN)
    if [ -n "$GITHUB_TOKEN" ]; then
        log_git "Push HTTPS-el (GITHUB_TOKEN)..."
        git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/megvadulthangya/manjaro-awesome.git"
        if git push origin main 2>/dev/null; then
            log_succ "Git push sikeres (HTTPS)!"
            return 0
        fi
    fi
    
    # Ha HTTPS nem működik, próbáljuk SSH-val
    log_git "Push SSH-val..."
    git remote set-url origin "$SSH_REPO_URL"
    if git push origin main 2>/dev/null; then
        log_succ "Git push sikeres (SSH)!"
        return 0
    fi
    
    # Ha mindkettő sikertelen
    log_err "Git push sikertelen mindkét módszerrel!"
    return 1
}

# ================================
# FŐ FUTTATÁS
# ================================

log_info "=== INTELLIGENS BUILD RENDSZER ==="
log_info "Kezdés: $(date)"
log_info "Összes csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"

# Verzióváltozások fájl inicializálása
rm -f "$REPO_ROOT/version_changes.txt"
touch "$REPO_ROOT/version_changes.txt"

# AUR csomagok
log_info "--- AUR CSOMAGOK (${#AUR_PACKAGES[@]}) ---"
rm -rf build_aur 2>/dev/null
mkdir -p build_aur

for pkg in "${AUR_PACKAGES[@]}"; do
    build_package_intelligent "$pkg" "true"
done

# Helyi csomagok
log_info "--- SAJÁT CSOMAGOK (${#LOCAL_PACKAGES[@]}) ---"
for pkg in "${LOCAL_PACKAGES[@]}"; do
    build_package_intelligent "$pkg" "false"
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
    
    # Mégis lehetnek PKGBUILD változások (verzió update nélkül is)
    git_push_changes
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
# GIT PUSH A VÁLTOZÁSOKHOZ
# ================================

log_info "=== GIT VÁLTOZÁSOK PUSH ==="
git_push_changes

log_info "========================================"
log_succ "INTELLIGENS BUILD RENDSZER SIKERESEN BEFEJEZVE!"
log_info "Idő: $(date)"
log_info "Összegzés:"
log_info "  - Összes feldolgozott csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"
shopt -s nullglob
pkg_count=("$OUTPUT_DIR"/*.pkg.tar.*)
shopt -u nullglob
log_info "  - Sikeresen épített csomagok: ${#pkg_count[@]}"
if [ -s "$REPO_ROOT/version_changes.txt" ]; then
    log_info "  - Frissített PKGBUILD-ok:"
    cat "$REPO_ROOT/version_changes.txt" | while read -r line; do
        log_info "    * $line"
    done
fi
log_info "========================================"