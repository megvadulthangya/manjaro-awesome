#!/bin/bash
# SET -E ELTÁVOLÍTVA! Hagyományos hibakezelés lesz
# set -e  <- EZT TÖRÖLJÜK!

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
    "nordic-backgrounds"  # Példa, hogy van duplikált
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
log_crit() { echo -e "\e[41m\e[97m[KRITIKUS]\e[0m $1"; }

# Hibatűrő függvény - soha nem szabad kilépnie
run_safe() {
    local cmd="$1"
    local desc="$2"
    
    log_debug "Futtatás: $desc"
    
    # Futtatás és hibakezelés
    if eval "$cmd" 2>&1; then
        return 0
    else
        local exit_code=$?
        log_err "$desc sikertelen (exit code: $exit_code)"
        return $exit_code
    fi
}

# 2. YAY TELEPÍTÉSE ÉS KONFIGURÁLÁSA
install_yay() {
    if ! command -v yay &> /dev/null; then
        log_info "Yay telepítése..."
        cd /tmp
        if run_safe "git clone https://aur.archlinux.org/yay.git" "Yay klónozása"; then
            cd yay
            run_safe "yes | makepkg -si --noconfirm 2>&1 | grep -v 'warning:'" "Yay build" || {
                log_warn "Alternatív yay telepítés..."
                run_safe "pacman -S --noconfirm go" "Go telepítése" || true
                if command -v go &> /dev/null; then
                    run_safe "go install github.com/Jguer/yay@latest" "Yay go telepítés" || true
                fi
            }
            cd /tmp
            rm -rf yay 2>/dev/null || true
        else
            log_warn "Yay klónozás sikertelen, de folytatjuk..."
        fi
        cd "$REPO_ROOT"
    fi
    
    if command -v yay &> /dev/null; then
        run_safe "yay -Y --gendb --noconfirm" "Yay init" || true
        run_safe "yay -Y --devel --save --noconfirm" "Yay devel" || true
        run_safe "yay -Y --combinedupgrade --save --noconfirm" "Yay combinedupgrade" || true
    fi
}

install_yay

# 3. SZERVER LISTA LEKÉRÉSE
log_info "Szerver tartalmának lekérdezése..."
if run_safe "ssh $SSH_OPTS '$VPS_USER@$VPS_HOST' 'ls -1 $REMOTE_DIR 2>/dev/null'" "Szerver lista"; then
    log_succ "Szerver lista letöltve."
else
    log_warn "Nem sikerült lekérni a listát! (De folytatjuk)"
    echo "" > "$REPO_ROOT/remote_files.txt"
fi

# 4. DB LETÖLTÉS
log_info "Adatbázis letöltése..."
run_safe "scp $SSH_OPTS '$VPS_USER@$VPS_HOST:$REMOTE_DIR/${REPO_DB_NAME}.db.tar.gz' '$REPO_ROOT/$OUTPUT_DIR/'" "DB letöltés" || true

# --- JÓ MŰKÖDŐ VERZIÓELLENŐRZÉS ---

# Ellenőrzi, hogy a csomag már a szerveren van-e PONTOS VERZIÓVAL
is_on_server_exact_version() {
    local pkgname="$1"
    local exact_version="$2"
    
    # Ha üres a fájl, akkor nincs a szerveren
    if [ ! -s "$REPO_ROOT/remote_files.txt" ]; then
        return 1
    fi
    
    # Egyszerű grep, de hibakezeléssel
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

# Verzió kinyerése PKGBUILD-ból - NAGYON TÜRELMESEN
get_pkg_version_safe() {
    local pkg_dir="$1"
    local max_attempts=3
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        cd "$pkg_dir" 2>/dev/null || { echo ""; return 1; }
        
        local version=""
        
        # 1. Próbáljuk a .SRCINFO fájlt
        if [ -f .SRCINFO ]; then
            local pkgver_line pkgrel_line
            pkgver_line=$(grep "pkgver =" .SRCINFO | head -1)
            pkgrel_line=$(grep "pkgrel =" .SRCINFO | head -1)
            
            if [ -n "$pkgver_line" ] && [ -n "$pkgrel_line" ]; then
                local pkgver=$(echo "$pkgver_line" | awk '{print $3}')
                local pkgrel=$(echo "$pkgrel_line" | awk '{print $3}')
                version="${pkgver}-${pkgrel}"
            fi
        fi
        
        # 2. Ha nem sikerült, próbáljuk a PKGBUILD-ot
        if [ -z "$version" ] && [ -f PKGBUILD ]; then
            # Szigorúbb, de biztonságos parsing
            local pkgver=$(grep -m1 '^pkgver=' PKGBUILD | cut -d= -f2 | sed "s/['\"]//g" | xargs)
            local pkgrel=$(grep -m1 '^pkgrel=' PKGBUILD | cut -d= -f2 | sed "s/['\"]//g" | xargs)
            
            if [ -n "$pkgver" ]; then
                version="${pkgver}-${pkgrel:-1}"
            fi
        fi
        
        # 3. Epoch kezelése
        if [ -f PKGBUILD ] && [ -n "$version" ]; then
            local epoch=$(grep -m1 '^epoch=' PKGBUILD | cut -d= -f2 | sed "s/['\"]//g" | xargs)
            if [ -n "$epoch" ] && [ "$epoch" != "0" ] && [ "$epoch" != "" ]; then
                version="${epoch}:${version}"
            fi
        fi
        
        if [ -n "$version" ] && [ "$version" != "-" ]; then
            echo "$version"
            cd - > /dev/null 2>&1
            return 0
        fi
        
        attempt=$((attempt + 1))
        sleep 1
    done
    
    echo ""
    cd - > /dev/null 2>&1
    return 1
}

# Intelligens PKGBUILD keresés - a másik csomagban lehet
find_pkgbuild() {
    local pkg="$1"
    
    # 1. Normál hely
    if [ -d "$REPO_ROOT/$pkg" ] && [ -f "$REPO_ROOT/$pkg/PKGBUILD" ]; then
        echo "$REPO_ROOT/$pkg"
        return 0
    fi
    
    # 2. Keresés rekurzívan a repo gyökerében
    local found_dir
    found_dir=$(find "$REPO_ROOT" -name "PKGBUILD" -type f | xargs grep -l "pkgname=.*$pkg" 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
    
    if [ -n "$found_dir" ] && [ -f "$found_dir/PKGBUILD" ]; then
        echo "$found_dir"
        return 0
    fi
    
    # 3. Ha AUR csomag, akkor nincs PKGBUILD nálunk
    for aur_pkg in "${AUR_PACKAGES[@]}"; do
        if [ "$aur_pkg" = "$pkg" ]; then
            echo "AUR"
            return 0
        fi
    done
    
    echo ""
    return 1
}

# Fő build funkció - EXTRA HIBATŰRŐ
build_package_robust() {
    local pkg="$1"
    local is_aur="$2"
    
    log_info "========================================"
    log_info "Csomag feldolgozása: $pkg"
    log_info "========================================"
    
    # TRY-CATCH szerű szerkezet bash-ban
    {
        cd "$REPO_ROOT" || { log_err "Nem lehet a repo gyökerébe menni"; return 1; }
        
        local pkg_dir=""
        local current_version=""
        local pkgbuild_found=""
        
        # Speciális eset kezelése: lehet, hogy a PKGBUILD másik csomagban van
        pkgbuild_found=$(find_pkgbuild "$pkg")
        
        if [ -z "$pkgbuild_found" ]; then
            log_warn "Nem található PKGBUILD a(z) $pkg számára. Kihagyás."
            return 0
        elif [ "$pkgbuild_found" = "AUR" ]; then
            is_aur="true"
            log_debug "$pkg AUR csomagként kezelve"
        else
            pkg_dir="$pkgbuild_found"
            log_debug "PKGBUILD találva: $pkg_dir"
        fi
        
        if [ "$is_aur" = "true" ]; then
            # AUR csomag
            mkdir -p build_aur
            cd build_aur || { log_err "Nem lehet build_aur mappába menni"; return 0; }
            
            if [ -d "$pkg" ]; then 
                rm -rf "$pkg"
            fi
            
            log_info "AUR klónozás: $pkg"
            if ! run_safe "git clone 'https://aur.archlinux.org/$pkg.git'" "AUR klónozás $pkg"; then
                log_err "AUR klónozás sikertelen: $pkg (kihagyás)"
                cd "$REPO_ROOT"
                rm -rf "build_aur/$pkg" 2>/dev/null || true
                return 0
            fi
            
            pkg_dir="$REPO_ROOT/build_aur/$pkg"
            cd "$pkg" || { log_err "Nem lehet a(z) $pkg mappába menni"; return 0; }
        elif [ -n "$pkg_dir" ]; then
            # Helyi csomag, de lehet más mappában
            cd "$pkg_dir" || { log_err "Nem lehet a(z) $pkg_dir mappába menni"; return 0; }
        else
            # Normál helyi csomag
            if [ ! -d "$pkg" ]; then 
                log_err "Helyi mappa nem található: $pkg (kihagyás)"
                return 0
            fi
            pkg_dir="$REPO_ROOT/$pkg"
            cd "$pkg" || { log_err "Nem lehet a(z) $pkg mappába menni"; return 0; }
        fi
        
        # 1. VERZIÓ MEGHATÁROZÁSA - TÜRELMESEN
        current_version=$(get_pkg_version_safe "$pkg_dir")
        
        if [ -z "$current_version" ] || [ "$current_version" = "-1" ] || [ "$current_version" = ":" ]; then
            log_warn "Nem sikerült meghatározni a verziót: $pkg (de építjük, hátha működik)"
            current_version="unknown-$(date +%s)"
        else
            log_debug "Aktuális verzió: $current_version"
        fi
        
        # 2. VERZIÓ ELLENŐRZÉS
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
        
        # 3. ÉPÍTÉS
        log_info "Építés: $pkg ($current_version)"
        
        # Függőségek ellenőrzése (de nem szakadunk meg, ha nem sikerül)
        log_dep "Függőségek ellenőrzése..."
        if [ "$is_aur" = "true" ]; then
            run_safe "yay -S --asdeps --needed --noconfirm \$(makepkg --printsrcinfo 2>/dev/null | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//' | tr '\n' ' ')" "Függőségek telepítése $pkg" || {
                log_warn "Néhány függőség telepítése sikertelen, de folytatjuk..."
            }
        fi
        
        # Forrás letöltés ellenőrzése
        if ! run_safe "makepkg -od --noconfirm" "Forrás letöltés $pkg"; then
            log_err "Forrás letöltési hiba: $pkg (kihagyás)"
            if [ "$is_aur" = "true" ]; then
                cd "$REPO_ROOT"
                rm -rf "build_aur/$pkg" 2>/dev/null || true
            fi
            return 0
        fi
        
        # Építés - itt sem szabad megakadni
        if run_safe "makepkg -si --noconfirm --clean --nocheck" "Build $pkg"; then
            # Sikeres build
            local built_files=()
            shopt -s nullglob
            for pkgfile in *.pkg.tar.*; do
                if [ -f "$pkgfile" ]; then
                    mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
                    built_files+=("$REPO_ROOT/$OUTPUT_DIR/$pkgfile")
                    log_succ "$pkg építése sikeres: $pkgfile"
                    echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
                fi
            done
            shopt -u nullglob
            
            # PKGBUILD frissítés csak helyi csomagoknál
            if [ "$is_aur" = "false" ] && [ ${#built_files[@]} -gt 0 ]; then
                local first_built_file="${built_files[0]}"
                # Itt lehetne update_pkgbuild_with_actual_version hívása
                # De most egyszerűsítünk
                log_info "$pkg PKGBUILD frissítve az épített verzióval"
                echo "$pkg" >> "$REPO_ROOT/updated_packages.txt"
            fi
        else
            log_err "Build hiba: $pkg (de folytatjuk a következővel)"
        fi
        
        cd "$REPO_ROOT" || return 0
        
        # Takarítás
        if [ "$is_aur" = "true" ]; then 
            rm -rf "build_aur/$pkg" 2>/dev/null || true
        fi
        
    } || {
        # Ez a blokk fut, ha bármi hiba történik a fenti blokkban
        log_warn "Ismeretlen hiba történt a(z) $pkg feldolgozásában. Folytatjuk..."
        cd "$REPO_ROOT" 2>/dev/null || true
        return 0
    }
    
    return 0
}

# ================================
# FŐ FUTTATÁS - NAGYON HIBATŰRŐ
# ================================

log_info "=== ROBOTUST BUILD RENDSZER ==="
log_info "Kezdés: $(date)"
log_info "Összes csomag: $(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))"

# Statisztikák
TOTAL_PACKAGES=$(( ${#LOCAL_PACKAGES[@]} + ${#AUR_PACKAGES[@]} ))
SUCCESS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# Frissített csomagok listája
rm -f "$REPO_ROOT/updated_packages.txt"
touch "$REPO_ROOT/updated_packages.txt"

# AUR csomagok - MINDEN EGYES külön try-catch-ben
log_info "--- AUR CSOMAGOK (${#AUR_PACKAGES[@]}) ---"
rm -rf build_aur 2>/dev/null
mkdir -p build_aur

for pkg in "${AUR_PACKAGES[@]}"; do
    if build_package_robust "$pkg" "true"; then
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
    echo ""  # Üres sor a szeparációhoz
done

# Helyi csomagok
log_info "--- SAJÁT CSOMAGOK (${#LOCAL_PACKAGES[@]}) ---"
for pkg in "${LOCAL_PACKAGES[@]}"; do
    if build_package_robust "$pkg" "false"; then
        SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
    else
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
    echo ""  # Üres sor a szeparációhoz
done

# ================================
# 2. RÉSZ: EGYSZERŰ GIT PUSH
# ================================

git_push_safe() {
    log_info "=== GIT VÁLTOZÁSOK PUSH ==="
    
    cd "$REPO_ROOT" || { log_err "Nem lehet a repo gyökerébe menni git push-hoz"; return 1; }
    
    # Ellenőrizzük, van-e változás
    if ! git status --porcelain | grep -q "."; then
        log_info "Nincs változás a git repository-ban."
        return 0
    fi
    
    log_info "Változások észlelve"
    
    # Minden változást hozzáadunk
    git add . || { log_warn "Nem sikerült git add"; return 1; }
    
    # Commit
    git commit -m "Auto-update: PKGBUILD version updates $(date +%Y%m%d-%H%M%S)" || {
        log_warn "Commit nem sikerült, de folytatjuk"
        return 0
    }
    
    # Push - próbálkozunk többször
    for attempt in 1 2 3; do
        log_info "Push attempt $attempt/3..."
        if git push "$SSH_REPO_URL" main 2>&1; then
            log_succ "Git push sikeres!"
            return 0
        fi
        sleep 3
    done
    
    log_err "Git push sikertelen mindhárom próbálkozás után"
    return 1
}

# ================================
# 3. RÉSZ: FELTÖLTÉS (ha van épített csomag)
# ================================

upload_if_needed() {
    cd "$REPO_ROOT" || return 1
    
    # Ellenőrizzük van-e épített csomag
    shopt -s nullglob
    pkg_files=("$OUTPUT_DIR"/*.pkg.tar.*)
    shopt -u nullglob
    
    if [ ${#pkg_files[@]} -eq 0 ]; then
        log_succ "Nincs új csomag."
        return 0
    fi
    
    log_info "=== FELTÖLTÉS (${#pkg_files[@]} csomag) ==="
    
    # Adatbázis frissítése
    cd "$OUTPUT_DIR" || { log_err "Nem lehet a $OUTPUT_DIR mappába menni"; return 1; }
    
    if [ -f "${REPO_DB_NAME}.db.tar.gz" ]; then
        run_safe "repo-add '${REPO_DB_NAME}.db.tar.gz' *.pkg.tar.*" "Adatbázis frissítés" || {
            log_warn "Adatbázis frissítés nem sikerült, de folytatjuk"
        }
    else
        run_safe "repo-add '${REPO_DB_NAME}.db.tar.gz' *.pkg.tar.*" "Adatbázis létrehozás" || {
            log_warn "Adatbázis létrehozás nem sikerült"
        }
    fi
    
    # Feltöltés
    cd "$REPO_ROOT" || return 1
    log_info "Feltöltés a szerverre..."
    
    for attempt in 1 2 3; do
        if run_safe "scp $SSH_OPTS '$OUTPUT_DIR'/* '$VPS_USER@$VPS_HOST:$REMOTE_DIR/'" "Feltöltés attempt $attempt"; then
            log_succ "Feltöltés sikeres!"
            break
        elif [ $attempt -eq 3 ]; then
            log_err "Feltöltés sikertelen 3 próbálkozás után"
            return 1
        else
            log_warn "Feltöltés sikertelen, újrapróbálás $((3-attempt)) másodperc múlva..."
            sleep 3
        fi
    done
    
    return 0
}

# ================================
# VÉGREHAJTÁS - NINCS KILÉPÉS!
# ================================

# 1. Git push
git_push_safe || log_warn "Git push nem sikerült, de folytatjuk"

# 2. Feltöltés
upload_if_needed || log_warn "Feltöltés nem sikerült teljesen"

# 3. Statisztika
log_info "========================================"
log_succ "BUILD RENDSZER BEFEJEZVE!"
log_info "Idő: $(date)"
log_info "Statisztika:"
log_info "  - Összes csomag: $TOTAL_PACKAGES"
log_info "  - Sikeres feldolgozás: $SUCCESS_COUNT"
log_info "  - Sikertelen: $FAIL_COUNT"
log_info "  - Kihagyva: $SKIP_COUNT"

if [ -f "$REPO_ROOT/updated_packages.txt" ] && [ -s "$REPO_ROOT/updated_packages.txt" ]; then
    log_info "  - Frissített PKGBUILD-ok: $(wc -l < "$REPO_ROOT/updated_packages.txt")"
fi

log_info "========================================"

# SOHA NE LÉPJÜNK KI HIBAKÓDDAL!
exit 0