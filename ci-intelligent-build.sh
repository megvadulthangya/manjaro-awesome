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

# 2. YAY TELEPÍTÉSE (ha nincs)
if ! command -v yay &> /dev/null; then
    log_info "Yay telepítése (intelligens AUR helper)..."
    cd /tmp
    if git clone https://aur.archlinux.org/yay.git 2>/dev/null; then
        cd yay
        if makepkg -si --noconfirm 2>/dev/null; then
            log_succ "Yay telepítve."
        else
            log_warn "Alternatív yay telepítés..."
            pacman -S --noconfirm go 2>/dev/null || true
            if command -v go &> /dev/null; then
                go install github.com/Jguer/yay@latest 2>/dev/null || true
            fi
        fi
        cd /tmp
        rm -rf yay 2>/dev/null || true
    fi
    cd "$REPO_ROOT"
fi

# 3. SZERVER LISTA LEKÉRÉSE
log_info "Szerver tartalmának lekérdezése..."
if ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" "ls -1 $REMOTE_DIR 2>/dev/null" > "$REPO_ROOT/remote_files.txt"; then
    log_succ "Szerver lista letöltve."
else
    touch "$REPO_ROOT/remote_files.txt"
fi

# 4. DB LETÖLTÉS
log_info "Adatbázis letöltése..."
scp $SSH_OPTS "$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz" "$REPO_ROOT/$OUTPUT_DIR/" 2>/dev/null || true

# Segédfüggvények

# Ellenőrzi, hogy a csomag már a szerveren van-e
is_on_server() {
    local pkgname="$1"
    local version="$2"
    if grep -q "^${pkgname}-${version}-" "$REPO_ROOT/remote_files.txt" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Intelligens függőség felismerő és telepítő
install_build_deps_intelligent() {
    local pkg_dir="$1"
    local is_aur="$2"
    
    log_dep "Függőségek analízise: $(basename "$pkg_dir")"
    
    cd "$pkg_dir" || return 1
    
    # 1. Kinyerjük a függőségeket a PKGBUILD-ből
    local depends_list=()
    local makedepends_list=()
    local checkdepends_list=()
    
    if [ -f PKGBUILD ]; then
        # Source the PKGBUILD in a controlled way
        {
            # shellcheck disable=SC1091
            source PKGBUILD > /dev/null 2>&1 || true
            
            # Függőségek összegyűjtése
            if [ -n "${depends[*]}" ]; then
                depends_list+=("${depends[@]}")
            fi
            
            if [ -n "${makedepends[*]}" ]; then
                makedepends_list+=("${makedepends[@]}")
            fi
            
            if [ -n "${checkdepends[*]}" ]; then
                checkdepends_list+=("${checkdepends[@]}")
            fi
        } 
        
        # Alternatív módszer: makepkg --printsrcinfo használata
        if command -v makepkg > /dev/null 2>&1; then
            if makepkg --printsrcinfo 2>/dev/null > /tmp/.srcinfo; then
                # depends kinyerése
                local srcinfo_depends
                srcinfo_depends=$(grep -E '^\s*depends\s*=' /tmp/.srcinfo 2>/dev/null | sed 's/^.*=\s*//' | tr '\n' ' ')
                local srcinfo_makedepends
                srcinfo_makedepends=$(grep -E '^\s*makedepends\s*=' /tmp/.srcinfo 2>/dev/null | sed 's/^.*=\s*//' | tr '\n' ' ')
                
                if [ -n "$srcinfo_depends" ]; then
                    # shellcheck disable=SC2206
                    depends_list+=($srcinfo_depends)
                fi
                if [ -n "$srcinfo_makedepends" ]; then
                    # shellcheck disable=SC2206
                    makedepends_list+=($srcinfo_makedepends)
                fi
            fi
        fi
    fi
    
    # 2. Egyedi függőség-kezelés ismert problémás csomagokhoz
    local pkg_name
    pkg_name=$(basename "$pkg_dir")
    case "$pkg_name" in
        gtk2)
            makedepends_list+=("gtk-doc" "docbook-xsl" "libxslt" "gobject-introspection")
            ;;
        awesome-git|awesome-freedesktop-git|lain-git)
            makedepends_list+=("lua" "lgi" "imagemagick" "asciidoc")
            ;;
        rust*|cargo*)
            makedepends_list+=("rust" "cargo")
            ;;
    esac
    
    # 3. Duplikációk eltávolítása
    if [ ${#depends_list[@]} -gt 0 ]; then
        depends_list=($(printf "%s\n" "${depends_list[@]}" | sort -u))
    fi
    if [ ${#makedepends_list[@]} -gt 0 ]; then
        makedepends_list=($(printf "%s\n" "${makedepends_list[@]}" | sort -u))
    fi
    
    # 4. Logoljuk a talált függőségeket
    if [ ${#depends_list[@]} -gt 0 ]; then
        log_dep "Depends: ${depends_list[*]}"
    fi
    if [ ${#makedepends_list[@]} -gt 0 ]; then
        log_dep "Makedepends: ${makedepends_list[*]}"
    fi
    
    # 5. Telepítjük a függőségeket
    local all_deps=("${depends_list[@]}" "${makedepends_list[@]}")
    
    if [ ${#all_deps[@]} -gt 0 ]; then
        log_dep "Függőségek telepítése..."
        
        # Csak azok a csomagok, amik még nincsenek telepítve
        local deps_to_install=()
        for dep in "${all_deps[@]}"; do
            # Tisztítjuk a függőség nevet (eltávolítjuk a >, <, = jeleket)
            local clean_dep
            clean_dep=$(echo "$dep" | sed 's/[<=>].*//')
            
            if ! pacman -Qi "$clean_dep" > /dev/null 2>&1; then
                deps_to_install+=("$clean_dep")
            else
                log_debug "Már telepítve: $clean_dep"
            fi
        done
        
        if [ ${#deps_to_install[@]} -gt 0 ]; then
            log_dep "Telepítendő: ${deps_to_install[*]}"
            
            # AUR csomagok esetén yay-t használunk
            if [ "$is_aur" = "true" ]; then
                # AUR helper használata
                if command -v yay > /dev/null 2>&1; then
                    for dep in "${deps_to_install[@]}"; do
                        log_dep "AUR függőség: $dep"
                        yay -S --asdeps --needed --noconfirm "$dep" 2>/dev/null || \
                            log_warn "Nem sikerült telepíteni: $dep (esetleg nem AUR csomag?)"
                    done
                fi
            fi
            
            # Arch hivatalos csomagok telepítése
            if pacman -Sp "${deps_to_install[@]}" > /dev/null 2>&1; then
                sudo pacman -S --needed --noconfirm "${deps_to_install[@]}" 2>/dev/null || \
                    log_warn "Egyes függőségek telepítése sikertelen"
            else
                # Ha nem hivatalos csomagok, próbáljuk AUR-ból
                for dep in "${deps_to_install[@]}"; do
                    if ! pacman -Si "$dep" > /dev/null 2>&1; then
                        if command -v yay > /dev/null 2>&1; then
                            log_dep "AUR-ból telepítés: $dep"
                            yay -S --asdeps --needed --noconfirm "$dep" 2>/dev/null || true
                        fi
                    fi
                done
            fi
        else
            log_dep "Minden függőség már telepítve van."
        fi
    else
        log_dep "Nincsenek explicit függőségek."
    fi
    
    # 6. Automatikus build-eszközök telepítése
    log_dep "Build eszközök ellenőrzése..."
    local build_tools=("make" "gcc" "pkg-config" "autoconf" "automake" "libtool" "cmake" "meson" "ninja")
    local missing_tools=()
    
    for tool in "${build_tools[@]}"; do
        if ! command -v "$tool" > /dev/null 2>&1; then
            missing_tools+=("$tool")
        fi
    done
    
    if [ ${#missing_tools[@]} -gt 0 ]; then
        log_dep "Hiányzó build eszközök: ${missing_tools[*]}"
        sudo pacman -S --needed --noconfirm "${missing_tools[@]}" 2>/dev/null || true
    fi
    
    cd - > /dev/null || return 1
}

# Intelligens AUR klónozó (javított)
clone_aur_intelligent() {
    local pkg="$1"
    local max_retries=2
    
    for attempt in $(seq 1 "$max_retries"); do
        log_debug "AUR klónozás ($attempt/$max_retries): $pkg"
        
        # 1. Próbáljuk a fő AUR URL-t
        if git clone "https://aur.archlinux.org/$pkg.git" > /dev/null 2>&1; then
            return 0
        fi
        
        # 2. Próbáljuk yay-t (ha van)
        if command -v yay > /dev/null 2>&1; then
            log_debug "Yay használata AUR csomaghoz: $pkg"
            if yay -G "$pkg" > /dev/null 2>&1; then
                return 0
            fi
        fi
        
        if [ "$attempt" -lt "$max_retries" ]; then
            sleep 5
        fi
    done
    
    return 1
}

# Fő build funkció - TELJESEN AUTOMATA
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
        
        if ! clone_aur_intelligent "$pkg"; then
            log_err "AUR klónozás sikertelen: $pkg"
            cd "$REPO_ROOT" || return 1
            return 1
        fi
        
        pkg_dir="$REPO_ROOT/build_aur/$pkg"
    else
        # Helyi csomag
        if [ ! -d "$pkg" ]; then 
            log_err "Helyi mappa nem található: $pkg"
            return 1
        fi
        pkg_dir="$REPO_ROOT/$pkg"
        cd "$pkg" || return 1
    fi
    
    # 1. INTELLIGENS FÜGGŐSÉG TELEPÍTÉS
    install_build_deps_intelligent "$pkg_dir" "$is_aur"
    
    cd "$pkg_dir" || return 1
    
    # 2. FORRÁS ELLENŐRZÉS
    log_debug "Források ellenőrzése..."
    if ! makepkg -od --noconfirm 2>&1 | tee /tmp/makepkg_src.log; then
        log_err "Forrás letöltési/verzió hiba: $pkg"
        
        # Speciális hibakezelés
        if grep -q "gtk-doc.make" /tmp/makepkg_src.log; then
            log_warn "GTK-DOC hiba - telepítjük a hiányzó csomagokat..."
            sudo pacman -S --noconfirm gtk-doc docbook-xsl libxslt 2>/dev/null || true
            # Újrapróbáljuk
            if makepkg -od --noconfirm 2>&1; then
                log_succ "Most már működik!"
            else
                cd "$REPO_ROOT" || return 1
                return 1
            fi
        else
            cd "$REPO_ROOT" || return 1
            return 1
        fi
    fi
    
    # 3. VERZIÓ INFORMÁCIÓK
    local full_ver=""
    local rel_ver=""
    
    if [ -f PKGBUILD ]; then
        # Kinyerjük a verziót a PKGBUILD-ből
        full_ver=$(grep '^pkgver=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "")
        rel_ver=$(grep '^pkgrel=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "1")
    fi
    
    if [ -z "$full_ver" ]; then
        full_ver="unknown"
    fi
    if [ -z "$rel_ver" ]; then
        rel_ver="1"
    fi
    
    local current_version="${full_ver}-${rel_ver}"
    
    # 4. SKIP LOGIKA
    if [ "$current_version" != "unknown-1" ] && is_on_server "$pkg" "$current_version"; then
        log_skip "$pkg ($current_version) -> MÁR A SZERVEREN VAN."
        cd "$REPO_ROOT" || return 1
        return 0
    fi
    
    # 5. ÉPÍTÉS
    log_info "Építés: $pkg ($current_version)"
    
    # Build flags intelligens beállítása
    local makepkg_flags="-si --noconfirm --clean"
    
    # Nagy csomagoknál kihagyjuk a tesztet
    if [[ "$pkg" == *gtk* ]] || [[ "$pkg" == *qt* ]] || [[ "$pkg" == *chromium* ]]; then
        makepkg_flags="$makepkg_flags --nocheck"
        log_warn "Nagy csomag - kihagyjuk az ellenőrzést"
    fi
    
    # Build folyamat
    log_debug "makepkg futtatása: $makepkg_flags"
    
    if timeout 3600 makepkg $makepkg_flags 2>&1 | tee /tmp/makepkg_build.log; then
        # Sikeres build
        for pkgfile in *.pkg.tar.* 2>/dev/null; do
            if [ -f "$pkgfile" ]; then
                mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
                log_succ "$pkg építése sikeres: $pkgfile"
                echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
            fi
        done
        
        # Git push (csak saját csomagoknál)
        if [ "$is_aur" = "false" ] && [ "$pkg" != "gtk2" ]; then
            log_info "Git repo frissítése..."
            
            if [ -f PKGBUILD ] && [ -f .SRCINFO ]; then
                TEMP_GIT_DIR="/tmp/git_publish_$pkg"
                rm -rf "$TEMP_GIT_DIR" 2>/dev/null || true
                
                if git clone "$SSH_REPO_URL" "$TEMP_GIT_DIR" 2>/dev/null; then
                    mkdir -p "$TEMP_GIT_DIR/$pkg"
                    cp PKGBUILD "$TEMP_GIT_DIR/$pkg/" 2>/dev/null
                    cp .SRCINFO "$TEMP_GIT_DIR/$pkg/" 2>/dev/null
                    cd "$TEMP_GIT_DIR" || continue
                    
                    if ! git diff-index --quiet HEAD -- 2>/dev/null; then
                        git add "$pkg/PKGBUILD" "$pkg/.SRCINFO" 2>/dev/null
                        git commit -m "Auto-update: $pkg to $current_version [skip ci]" 2>/dev/null
                        git push 2>/dev/null && log_succ "Git push sikeres"
                    fi
                    
                    cd "$pkg_dir" || return 1
                    rm -rf "$TEMP_GIT_DIR" 2>/dev/null || true
                fi
            fi
        fi
    else
        log_err "Build hiba: $pkg"
        
        # Hibaanalízis
        if grep -q "error:" /tmp/makepkg_build.log 2>/dev/null; then
            log_warn "Utolsó hibák:"
            grep -i "error:" /tmp/makepkg_build.log 2>/dev/null | tail -5
        fi
    fi
    
    cd "$REPO_ROOT" || return 1
    
    # Takarítás
    if [ "$is_aur" = "true" ]; then 
        rm -rf "build_aur/$pkg" 2>/dev/null || true
    fi
}

# ================================
# FŐ FUTTATÁS
# ================================

log_info "=== INTELLIGENS BUILD RENDSZER ==="
log_info "Kezdés: $(date)"
log_info "Összes csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"

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
if [ -z "$(ls -A $OUTPUT_DIR/*.pkg.tar.* 2>/dev/null)" ]; then
    log_succ "Nincs új csomag - minden naprakész!"
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

# Feltöltés
log_info "Feltöltés a szerverre..."
cd "$REPO_ROOT" || exit 1

if scp $SSH_OPTS "$OUTPUT_DIR"/* "$VPS_USER@$VPS_HOST:$REMOTE_DIR/" 2>/dev/null; then
    log_succ "Feltöltés sikeres!"
else
    # Újrapróbálás
    sleep 3
    if scp $SSH_OPTS "$OUTPUT_DIR"/* "$VPS_USER@$VPS_HOST:$REMOTE_DIR/" 2>/dev/null; then
        log_succ "Második próbálkozás sikeres!"
    else
        log_err "Feltöltés sikertelen!"
        exit 1
    fi
fi

# Opcionális takarítás
if [ -f packages_to_clean.txt ] && [ -s packages_to_clean.txt ]; then
    log_info "Régi csomagok takarítása..."
    while read -r pkg_to_clean || [ -n "$pkg_to_clean" ]; do
        ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" \
            "cd $REMOTE_DIR && ls -t ${pkg_to_clean}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | xargs -r rm -f" 2>/dev/null || true
    done < packages_to_clean.txt
fi

log_info "========================================"
log_succ "INTELLIGENS BUILD RENDSZER SIKERESEN BEFEJEZVE!"
log_info "Idő: $(date)"
log_info "Összegzés:"
log_info "  - Összes feldolgozott csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"
log_info "  - Sikeresen épített csomagok: $(ls -1 $OUTPUT_DIR/*.pkg.tar.* 2>/dev/null | wc -l)"
log_info "========================================"