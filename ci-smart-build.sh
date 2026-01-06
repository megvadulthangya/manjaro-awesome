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

# AUR csomagok csoportokra bontva könnyebb kezelésért
AUR_PACKAGES_MAIN=(
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
)

AUR_PACKAGES_THEMES=(
    "nordic-theme"
    "nordic-darker-theme"
    "geany-nord-theme"
    "nordzy-icon-theme"
    "nordic-bluish-accent-theme"
    "nordic-bluish-accent-standard-buttons-theme"
    "nordic-polar-standard-buttons-theme"
    "nordic-standard-buttons-theme"
    "nordic-darker-standard-buttons-theme"
)

AUR_PACKAGES_OTHER=(
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
)

# Összes AUR csomag
AUR_PACKAGES=("${AUR_PACKAGES_MAIN[@]}" "${AUR_PACKAGES_THEMES[@]}" "${AUR_PACKAGES_OTHER[@]}")

REMOTE_DIR="/var/www/repo"
REPO_DB_NAME="manjaro-awesome"
OUTPUT_DIR="built_packages"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=30"

mkdir -p "$REPO_ROOT/$OUTPUT_DIR"

# --- GIT KONFIGURÁCIÓ ---
git config --global user.name "GitHub Action Bot"
git config --global user.email "action@github.com"

log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_succ() { echo -e "\e[32m[OK]\e[0m $1"; }
log_skip() { echo -e "\e[33m[SKIP]\e[0m $1"; }
log_err()  { echo -e "\e[31m[HIBA]\e[0m $1"; }
log_debug() { echo -e "\e[35m[DEBUG]\e[0m $1"; }
log_warn() { echo -e "\e[33m[FIGYELEM]\e[0m $1"; }

# 2. YAY TELEPÍTÉSE (javított, robusztusabb változat)
if ! command -v yay &> /dev/null; then
    log_info "Yay telepítése..."
    cd /tmp
    MAX_RETRIES=3
    RETRY_COUNT=0
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        if git clone https://aur.archlinux.org/yay.git; then
            cd yay
            if makepkg -si --noconfirm; then
                log_succ "Yay telepítése sikeres."
                break
            else
                log_err "Yay build sikertelen."
            fi
            cd /tmp
            rm -rf yay
        else
            log_warn "Yay klónozás sikertelen, újrapróbálás ($((RETRY_COUNT+1))/$MAX_RETRIES)..."
        fi
        
        RETRY_COUNT=$((RETRY_COUNT+1))
        sleep 5
    done
    
    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        log_err "Yay telepítése végleg sikertelen."
        exit 1
    fi
    
    cd "$REPO_ROOT"
fi

# 3. SZERVER LISTA LEKÉRÉSE
log_info "Szerver tartalmának lekérdezése (gyors lista)..."
if ssh $SSH_OPTS $VPS_USER@$VPS_HOST "ls -1 $REMOTE_DIR 2>/dev/null" > "$REPO_ROOT/remote_files.txt"; then
    log_succ "Lista letöltve."
else
    log_warn "Nem sikerült lekérni a listát! (De folytatjuk, hátha üres a szerver)"
    touch "$REPO_ROOT/remote_files.txt"
fi

# 4. DB LETÖLTÉS
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

# Javított AUR klónozás funkció
clone_aur_package() {
    local pkg="$1"
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        log_debug "AUR klónozás próba $((retry_count+1))/$max_retries: $pkg"
        
        # Különböző AUR URL-ek kipróbálása
        local aur_urls=(
            "https://aur.archlinux.org/$pkg.git"
            "https://aur.archlinux.org/$pkg"
            "git://aur.archlinux.org/$pkg.git"
        )
        
        for aur_url in "${aur_urls[@]}"; do
            if git clone "$aur_url" > /dev/null 2>&1; then
                log_debug "Sikeres klónozás: $aur_url"
                return 0
            fi
        done
        
        retry_count=$((retry_count+1))
        if [ $retry_count -lt $max_retries ]; then
            log_warn "Újrapróbálás $pkg esetén $((max_retries-retry_count)) próba maradt..."
            sleep 10
        fi
    done
    
    log_err "A(z) $pkg klónozása sikertelen minden próbálkozás után."
    return 1
}

# Fő build funkció
build_package() {
    local pkg="$1"
    local is_aur="$2"
    
    cd "$REPO_ROOT"

    if [ "$is_aur" == "true" ]; then
        mkdir -p build_aur
        cd build_aur
        
        if [ -d "$pkg" ]; then 
            rm -rf "$pkg"
        fi
        
        # Javított klónozás
        if ! clone_aur_package "$pkg"; then
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

    # 1. FORRÁS ELLENŐRZÉS (részletes debug)
    log_debug "Források ellenőrzése a(z) $pkg számára..."
    echo "=== MAKEPKG -OD KIMENET (FORRÁS ELLENŐRZÉS) ==="
    if ! makepkg -od --noconfirm 2>&1 | tee /tmp/makepkg_output.log; then
         log_err "Forrás letöltési/verzió hiba: $pkg"
         
         # További diagnosztika
         log_debug "Közvetlen URL teszt curl-lel:"
         if [ -f PKGBUILD ]; then
             source PKGBUILD 2>/dev/null || true
             if [ -n "${source[@]}" ]; then
                 for src in "${source[@]}"; do
                     if [[ $src == http* ]]; then
                         echo "  Tesztelés: $src"
                         curl -I --connect-timeout 10 -L "$src" 2>/dev/null || echo "  Sikertelen"
                     fi
                 done
             fi
         fi
         
         # Check if it's actually a build dependency error
         if grep -q "automake failed" /tmp/makepkg_output.log || \
            grep -q "gtk-doc.make" /tmp/makepkg_output.log; then
            log_warn "Ez valószínűleg build függőségi hiba, nem forrás letöltési hiba!"
            log_warn "Próbáljuk telepíteni a hiányzó build függőségeket..."
            
            # Próbáljuk telepíteni a gyakori build függőségeket
            pacman -Syu --noconfirm --needed \
                gtk-doc docbook-xsl libxslt \
                gobject-introspection \
                autoconf automake libtool \
                2>/dev/null || true
                
            # Próbáljuk újra a forrás ellenőrzést
            log_debug "Újrapróbálás telepített függőségekkel..."
            if makepkg -od --noconfirm 2>&1 | tee /tmp/makepkg_output_retry.log; then
                log_succ "Forrás ellenőrzés most már sikeres (függőségek telepítve)"
            else
                log_err "Még mindig sikertelen"
                if [ "$is_aur" == "true" ]; then cd "$REPO_ROOT"; fi
                return
            fi
         else
            if [ "$is_aur" == "true" ]; then cd "$REPO_ROOT"; fi
            return
         fi
    fi

    # Verzió információk kinyerése
    if [ -f .SRCINFO ]; then
        full_ver=$(grep "pkgver =" .SRCINFO | head -1 | awk '{print $3}')
        rel_ver=$(grep "pkgrel =" .SRCINFO | head -1 | awk '{print $3}')
    else
        makepkg --printsrcinfo > .SRCINFO 2>/dev/null || true
        full_ver=$(grep "pkgver =" .SRCINFO | head -1 | awk '{print $3}' 2>/dev/null)
        rel_ver=$(grep "pkgrel =" .SRCINFO | head -1 | awk '{print $3}' 2>/dev/null)
    fi
    
    if [ -z "$full_ver" ] && [ -f PKGBUILD ]; then
        source PKGBUILD 2>/dev/null || true
        if [ -n "$pkgver" ]; then
            full_ver=$pkgver
        fi
        if [ -n "$pkgrel" ]; then
            rel_ver=$pkgrel
        fi
    fi

    local current_version="${full_ver}-${rel_ver}"
    
    if [ -z "$full_ver" ]; then
        current_version="unknown"
    fi

    # --- SKIP LOGIKA ---
    if [ "$current_version" != "unknown" ] && is_on_server "$pkg" "$current_version"; then
        log_skip "$pkg ($current_version) -> MÁR A SZERVEREN VAN."
        if [ "$is_aur" == "true" ]; then cd "$REPO_ROOT"; fi
        return
    fi

    # --- 2. ÉPÍTÉS ---
    log_info "ÚJ VERZIÓ! Építés: $pkg ($current_version)"
    
    # Függőségek előtelepítése yay-vel (AUR csomagok esetén)
    if [ "$is_aur" == "true" ]; then
        log_info "Függőségek ellenőrzése (AUR)..."
        # Csak az AUR-ból származó függőségek
        if [ -f .SRCINFO ]; then
            deps=$(makepkg --printsrcinfo | grep -E '^\s*(make)?depends\s*=' | sed 's/^.*=\s*//' | tr '\n' ' ')
            if [ -n "$deps" ]; then
                log_debug "Függőségek telepítése: $deps"
                yay -S --asdeps --needed --noconfirm $deps 2>/dev/null || true
            fi
        fi
    fi

    # Építés
    log_debug "makepkg futtatása..."
    echo "=== TELJES BUILD FOLYAMAT ==="
    
    # GTK2 speciális kezelése - ne csináljunk check-et (mert hosszú)
    local makepkg_flags="-si --noconfirm --clean"
    if [ "$pkg" == "gtk2" ]; then
        makepkg_flags="$makepkg_flags --nocheck"
        log_warn "GTK2: Kihagyjuk az ellenőrzési lépést (hosszú)"
    fi
    
    if timeout 1800 makepkg $makepkg_flags 2>&1 | tee /tmp/makepkg_build.log; then
        # Sikeres build - csomag fájlok mozgatása
        for pkgfile in *.pkg.tar.*; do
            if [ -f "$pkgfile" ]; then
                mv "$pkgfile" "$REPO_ROOT/$OUTPUT_DIR/"
                log_succ "$pkg építése sikeres: $pkgfile"
                echo "$pkg" >> "$REPO_ROOT/packages_to_clean.txt"
            fi
        done

        # --- GIT PUSH (csak saját csomagok esetén) ---
        if [ "$is_aur" == "false" ] && [ "$pkg" != "gtk2" ]; then
            log_info "PKGBUILD frissítése és Git Push..."
            
            # Csak frissítjük ha van .SRCINFO
            if [ -f .SRCINFO ]; then
                sed -i "s/^pkgver=.*/pkgver=${full_ver}/" PKGBUILD 2>/dev/null || true
                sed -i "s/^pkgrel=.*/pkgrel=${rel_ver}/" PKGBUILD 2>/dev/null || true
                makepkg --printsrcinfo > .SRCINFO 2>/dev/null || true
                
                TEMP_GIT_DIR="/tmp/git_publish_$pkg"
                rm -rf "$TEMP_GIT_DIR"
                
                if git clone "$SSH_REPO_URL" "$TEMP_GIT_DIR" 2>/dev/null; then
                    mkdir -p "$TEMP_GIT_DIR/$pkg"
                    cp PKGBUILD "$TEMP_GIT_DIR/$pkg/" 2>/dev/null || true
                    cp .SRCINFO "$TEMP_GIT_DIR/$pkg/" 2>/dev/null || true
                    cd "$TEMP_GIT_DIR"
                    if git diff-index --quiet HEAD -- 2>/dev/null; then
                        log_info "Nincs mit commitolni."
                    else
                        git add "$pkg/PKGBUILD" "$pkg/.SRCINFO" 2>/dev/null
                        git commit -m "Auto-update: $pkg updated to $current_version [skip ci]" 2>/dev/null
                        if git push 2>/dev/null; then
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
        fi
    else
        log_err "HIBA az építésnél: $pkg"
        # Build log megjelenítése
        if [ -f /tmp/makepkg_build.log ]; then
            log_debug "Utolsó 20 sor a build logból:"
            tail -20 /tmp/makepkg_build.log
        fi
    fi

    cd "$REPO_ROOT"
    if [ "$is_aur" == "true" ]; then 
        rm -rf "build_aur/$pkg" 2>/dev/null || true
    fi
}

# --- FŐ CIKLUSOK (javított hibakezeléssel) ---

log_info "=== AUR CSOMAGOK ÉPÍTÉSE ==="
rm -rf build_aur 2>/dev/null || true
mkdir -p build_aur

# AUR csomagok csoportonként
log_info "--- AUR Fő csomagok ---"
for pkg in "${AUR_PACKAGES_MAIN[@]}"; do
    build_package "$pkg" "true"
done

log_info "--- AUR Témák ---"
for pkg in "${AUR_PACKAGES_THEMES[@]}"; do
    build_package "$pkg" "true"
done

log_info "--- AUR Egyéb csomagok ---"
for pkg in "${AUR_PACKAGES_OTHER[@]}"; do
    build_package "$pkg" "true"
done

log_info "=== SAJÁT CSOMAGOK ÉPÍTÉSE ==="
for pkg in "${LOCAL_PACKAGES[@]}"; do
    build_package "$pkg" "false"
done

# --- DB FRISSÍTÉS ÉS FELTÖLTÉS ---
cd "$REPO_ROOT"

if [ -z "$(ls -A $OUTPUT_DIR/*.pkg.tar.* 2>/dev/null)" ]; then
    log_succ "Minden naprakész. Nincs feltölteni való."
    exit 0
fi

log_info "Épített csomagok:"
ls -la "$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null || log_warn "Nincs épített csomag"

log_info "Adatbázis frissítése..."
cd "$OUTPUT_DIR"

if [ -f "${REPO_DB_NAME}.db.tar.gz" ]; then
    log_info "Meglévő adatbázis bővítése..."
    repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || log_err "repo-add sikertelen"
else
    log_info "Új adatbázis létrehozása..."
    repo-add "${REPO_DB_NAME}.db.tar.gz" *.pkg.tar.* 2>/dev/null || log_err "repo-add sikertelen"
fi

log_info "Feltöltés a szerverre..."
cd ..
if scp $SSH_OPTS $OUTPUT_DIR/* $VPS_USER@$VPS_HOST:$REMOTE_DIR/ 2>/dev/null; then
    log_succ "Csomagok feltöltve."
else
    log_err "Feltöltés sikertelen!"
    # Próbáljuk meg újra egyszer
    sleep 5
    scp $SSH_OPTS $OUTPUT_DIR/* $VPS_USER@$VPS_HOST:$REMOTE_DIR/ 2>/dev/null && \
        log_succ "Második próbálkozás sikeres." || \
        log_err "Második próbálkozás is sikertelen."
fi

# Takarítás a szerveren (opcionális)
if [ -f packages_to_clean.txt ] && [ -s packages_to_clean.txt ]; then
    log_info "Takarítás a szerveren..."
    REMOTE_COMMANDS="cd $REMOTE_DIR && "
    
    while read pkg_to_clean; do
        # Csak az utolsó 3 verziót tartsuk meg
        REMOTE_COMMANDS+="ls -t ${pkg_to_clean}-*.pkg.tar.zst 2>/dev/null | tail -n +4 | xargs -r rm -f -- && "
    done < packages_to_clean.txt
    
    REMOTE_COMMANDS+="echo 'Takarítás kész.'"
    
    if ssh $SSH_OPTS $VPS_USER@$VPS_HOST "$REMOTE_COMMANDS" 2>/dev/null; then
        log_succ "Szerver takarítva."
    else
        log_warn "Szerver takarítás sikertelen (de ez nem kritikus)"
    fi
fi

log_succ "=== KÉSZ! Repó frissítve. ==="
echo "Összegzés:"
echo "- Sikeresen épített csomagok: $(ls -1 $OUTPUT_DIR/*.pkg.tar.* 2>/dev/null | wc -l)"
echo "- Hibás AUR csomagok: $(grep -c "Nem sikerült klónozni:" /proc/self/fd/1 2>/dev/null || echo "0")"