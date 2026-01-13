#!/bin/bash
set -e

# === LOGOLÁS FUNKCIÓK ===
log_info() { echo -e "\e[34m[INFO]\e[0m $1"; }
log_succ() { echo -e "\e[32m[OK]\e[0m $1"; }
log_warn() { echo -e "\e[33m[WARN]\e[0m $1"; }
log_err()  { echo -e "\e[31m[ERROR]\e[0m $1"; }
log_debug() { echo -e "\e[35m[DEBUG]\e[0m $1"; }

# === KÖRNYEZETI VÁLTOZÓK BETÖLTÉSE ===
log_info "Környezeti változók betöltése..."
if [ -f /home/builder/env_vars.sh ]; then
    source /home/builder/env_vars.sh
fi

# Alapértelmezett értékek, ha nincsenek beállítva
TEST_FILE_SIZE_MB=${TEST_FILE_SIZE_MB:-5}
USE_COMPRESSION=${USE_COMPRESSION:-true}

log_info "Környezeti változók:"
echo "  REMOTE_DIR: $REMOTE_DIR"
echo "  VPS_USER: $VPS_USER"
echo "  VPS_HOST: $VPS_HOST"
echo "  TEST_FILE_SIZE_MB: $TEST_FILE_SIZE_MB"
echo "  USE_COMPRESSION: $USE_COMPRESSION"

# === ÉRVÉNYESSÉG ELLENŐRZÉS ===
if [ -z "$REMOTE_DIR" ] || [ -z "$VPS_USER" ] || [ -z "$VPS_HOST" ]; then
    log_err "Hiányzó környezeti változók!"
    exit 1
fi

# === TESZT FÁJLOK LÉTREHOZÁSA ===
log_info "Tesztfájlok létrehozása..."
OUTPUT_DIR="/home/builder/built_packages"
mkdir -p $OUTPUT_DIR

TEST_PREFIX="github_test_$(date +%s)"

# 5MB fájl
log_debug "5MB fájl létrehozása..."
dd if=/dev/urandom of="$OUTPUT_DIR/${TEST_PREFIX}-small-1.0-1-x86_64.pkg.tar.zst" \
   bs=1M count=5 > /dev/null 2>&1

# 190MB fájl  
log_debug "190MB fájl létrehozása..."
dd if=/dev/urandom of="$OUTPUT_DIR/${TEST_PREFIX}-large-2.0-1-x86_64.pkg.tar.zst" \
   bs=1M count=190 > /dev/null 2>&1

# Custom méretű fájl
log_debug "${TEST_FILE_SIZE_MB}MB fájl létrehozása..."
dd if=/dev/urandom of="$OUTPUT_DIR/${TEST_PREFIX}-custom-1.5-1-x86_64.pkg.tar.zst" \
   bs=1M count=$TEST_FILE_SIZE_MB > /dev/null 2>&1

# Adatbázis fájl
log_debug "Adatbázis fájl létrehozása..."
cd $OUTPUT_DIR
tar czf "${TEST_PREFIX}-manjaro-awesome.db.tar.gz" \
    "${TEST_PREFIX}"-*.pkg.tar.zst > /dev/null 2>&1 || true

log_info "Létrehozott fájlok:"
ls -lh "$OUTPUT_DIR/"*.pkg.tar.*
echo "Összesen: $(ls -1 $OUTPUT_DIR/*.pkg.tar.* 2>/dev/null | wc -l) fájl"

# === SSH KAPCSOLAT TESZT ===
log_info "SSH kapcsolat tesztelése..."
SSH_CMD="echo 'SSH kapcsolat rendben'; hostname; whoami; date"
if ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST "$SSH_CMD"; then
    log_succ "SSH kapcsolat sikeres"
else
    log_err "SSH kapcsolat sikertelen"
    exit 1
fi

# === TÁVOLI KÖNYVTÁR ELLENŐRZÉS ===
log_info "Távoli könyvtár ellenőrzése: $REMOTE_DIR"
REMOTE_CHECK="
if [ -d '$REMOTE_DIR' ]; then
    echo 'Könyvtár létezik'
    ls -ld '$REMOTE_DIR'
    echo 'Szabad hely:'
    df -h '$REMOTE_DIR' 2>/dev/null || df -h | grep -E '/var|/www|/home' | head -1
else
    echo 'Könyvtár nem létezik, létrehozás...'
    mkdir -p '$REMOTE_DIR' 2>/dev/null || sudo mkdir -p '$REMOTE_DIR'
    echo 'Könyvtár létrehozva'
fi"

if ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST "$REMOTE_CHECK"; then
    log_succ "Távoli könyvtár ellenőrzve"
else
    log_err "Távoli könyvtár ellenőrzés sikertelen"
fi

# === SCP FELTÖLTÉS TESZT ===
log_info "=== SCP FELTÖLTÉS TESZT ==="
UPLOAD_COUNT=0
for FILE in "$OUTPUT_DIR"/*.pkg.tar.*; do
    if [ -f "$FILE" ]; then
        FILENAME=$(basename "$FILE")
        log_debug "SCP feltöltés: $FILENAME"
        
        START_TIME=$(date +%s.%N)
        if scp -o StrictHostKeyChecking=no \
               -o ConnectTimeout=30 \
               "$FILE" \
               "$VPS_USER@$VPS_HOST:$REMOTE_DIR/$FILENAME"; then
            END_TIME=$(date +%s.%N)
            DURATION=$(echo "$END_TIME - $START_TIME" | bc)
            log_succ "Feltöltve: $FILENAME (${DURATION}s)"
            UPLOAD_COUNT=$((UPLOAD_COUNT + 1))
        else
            log_err "SCP hiba: $FILENAME"
        fi
    fi
done

log_info "SCP összesítés: $UPLOAD_COUNT fájl feltöltve"

# === RSYNC FELTÖLTÉS TESZT ===
log_info "=== RSYNC FELTÖLTÉS TESZT ==="
RSYNC_TIMESTAMP=$(date +%s)
RSYNC_TEST_DIR="$REMOTE_DIR/rsync_test_$RSYNC_TIMESTAMP"

# Távoli könyvtár létrehozása
ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST "mkdir -p '$RSYNC_TEST_DIR'"

# Rsync opciók
RSYNC_OPTS="-av --progress --stats"
if [ "$USE_COMPRESSION" = "true" ]; then
    RSYNC_OPTS="$RSYNC_OPTS -z"
    log_debug "Tömörítés használata"
fi

log_debug "RSYNC parancs: rsync $RSYNC_OPTS fájlok -> $RSYNC_TEST_DIR"
START_TIME=$(date +%s.%N)

# Rsync futtatása
rsync $RSYNC_OPTS \
    -e 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30' \
    "$OUTPUT_DIR/"*.pkg.tar.* \
    "$VPS_USER@$VPS_HOST:$RSYNC_TEST_DIR/" 2>&1 | tee /tmp/rsync_output.log

RSYNC_EXIT=$?
END_TIME=$(date +%s.%N)
DURATION=$(echo "$END_TIME - $START_TIME" | bc)

if [ $RSYNC_EXIT -eq 0 ]; then
    log_succ "RSYNC sikeres (${DURATION}s)"
    
    # Statisztikák
    echo "=== RSYNC STATISZTIKÁK ==="
    grep -E "(Number of files|Total transferred|sent|received)" /tmp/rsync_output.log || true
    
    # Ellenőrzés
    log_debug "RSYNC ellenőrzés..."
    ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST \
        "ls -lh '$RSYNC_TEST_DIR/' | head -10 && \
         echo 'Összesen: \$(ls -1 \"$RSYNC_TEST_DIR/\"*.pkg.tar.* 2>/dev/null | wc -l) fájl'"
else
    log_err "RSYNC hiba (exit code: $RSYNC_EXIT)"
fi

# === ÖSSZEHASONLÍTÁS ===
log_info "=== FELTÖLTÉSI MÓDSZEREK ÖSSZEHASONLÍTÁSA ==="
echo "SCP: $UPLOAD_COUNT fájl feltöltve a $REMOTE_DIR könyvtárba"
echo "RSYNC: $(ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST "ls -1 '$RSYNC_TEST_DIR/'*.pkg.tar.* 2>/dev/null | wc -l") fájl a $RSYNC_TEST_DIR könyvtárban"
echo ""
echo "További teszteléshez ajánlott:"
echo "1. scp -C (tömörítés)"
echo "2. rsync -z --partial (részleges feltöltés)"
echo "3. rsync --bwlimit=RATE (sávszélesség korlátozás)"

# === TAKARÍTÁS ===
log_info "=== TESZT FÁJLOK TÖRLÉSE ==="

# SCP fájlok törlése
log_debug "SCP tesztfájlok törlése..."
ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST \
    "rm -f '$REMOTE_DIR/'github_test_*.pkg.tar.* 2>/dev/null && \
     echo 'SCP fájlok törölve' || echo 'Nincsenek SCP fájlok'"

# RSYNC könyvtárak törlése
log_debug "RSYNC tesztkönyvtárak törlése..."
ssh -o StrictHostKeyChecking=no $VPS_USER@$VPS_HOST \
    "rm -rf '$REMOTE_DIR/'rsync_test_*/ 2>/dev/null && \
     echo 'RSYNC könyvtárak törölve' || echo 'Nincsenek RSYNC könyvtárak'"

# Lokális fájlok törlése
log_debug "Lokális tesztfájlok törlése..."
rm -rf "$OUTPUT_DIR"/* 2>/dev/null && log_succ "Lokális fájlok törölve" || log_warn "Lokális fájlok törlése sikertelen"

# === VÉGLEGES ÖSSZEFOGLALÓ ===
log_info "=== TESZT VÉGE ==="
echo "📅 Dátum: $(date)"
echo "🖥️  Host: $VPS_HOST"
echo "👤 User: $VPS_USER"
echo "📁 Remote dir: $REMOTE_DIR"
echo "📊 Fájlméretek: 5MB, 190MB, ${TEST_FILE_SIZE_MB}MB"
echo "✅ SCP feltöltések: $UPLOAD_COUNT"
echo "✅ RSYNC státusz: $(if [ $RSYNC_EXIT -eq 0 ]; then echo 'SIKERES'; else echo 'SIKERTELEN'; fi)"
echo ""
echo "Az eredeti CI scripthez ajánlott módosítások:"
echo "1. SSH config hozzáadása: ServerAliveInterval 15"
echo "2. Nagy fájlokhoz használj rsync-et scp helyett"
echo "3. Ellenőrizd a távoli könyvtár írási jogosultságokat"

exit 0