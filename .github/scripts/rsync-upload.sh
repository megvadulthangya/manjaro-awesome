#!/bin/bash
set -e

# === KONSTANSOK ===
OUTPUT_DIR="/home/builder/built_packages"
TEST_PREFIX="github_test_$(date +%s)"

# === LOG FUNKCIÓK ===
log() { echo "[$(date '+%H:%M:%S')] $1"; }
info() { log "ℹ️  $1"; }
success() { log "✅ $1"; }
error() { log "❌ $1"; }

# === VÁLTOZÓK ===
REMOTE_DIR="${REMOTE_DIR:-/var/www/repo}"
VPS_USER="${VPS_USER:-root}"
VPS_HOST="${VPS_HOST}"
TEST_SIZE_MB="${TEST_SIZE_MB:-10}"

# === ÉRVÉNYESSÉG ELLENŐRZÉS ===
if [ -z "$VPS_HOST" ]; then
    error "VPS_HOST nincs beállítva!"
    exit 1
fi

info "=== RSYNC FELTÖLTÉS TESZT ==="
info "Host: $VPS_HOST"
info "User: $VPS_USER"
info "Remote: $REMOTE_DIR"
info "File size: ${TEST_SIZE_MB}MB"
echo ""

# === 1. SSH KAPCSOLAT TESZT ===
info "1. SSH kapcsolat teszt..."
if ssh -o ConnectTimeout=10 "$VPS_USER@$VPS_HOST" "echo 'SSH OK' && hostname"; then
    success "SSH kapcsolat rendben"
else
    error "SSH kapcsolat sikertelen"
    exit 1
fi

# === 2. KÖNYVTÁR ELLENŐRZÉS ===
info "2. Távoli könyvtár ellenőrzése..."
if ssh "$VPS_USER@$VPS_HOST" "[ -d '$REMOTE_DIR' ] && echo 'Könyvtár létezik' || echo 'Könyvtár nem létezik, létrehozom...' && mkdir -p '$REMOTE_DIR'"; then
    success "Könyvtár rendben"
else
    error "Könyvtár probléma"
    exit 1
fi

# === 3. TESZT FÁJLOK LÉTREHOZÁSA ===
info "3. Tesztfájlok létrehozása..."
mkdir -p "$OUTPUT_DIR"

# 5MB fájl
info "  - 5MB fájl..."
dd if=/dev/urandom of="$OUTPUT_DIR/${TEST_PREFIX}-small-1.0-1.pkg.tar.zst" bs=1M count=5 > /dev/null 2>&1

# 190MB fájl
info "  - 190MB fájl..."
dd if=/dev/urandom of="$OUTPUT_DIR/${TEST_PREFIX}-large-2.0-1.pkg.tar.zst" bs=1M count=190 > /dev/null 2>&1

# Custom fájl
info "  - ${TEST_SIZE_MB}MB fájl..."
dd if=/dev/urandom of="$OUTPUT_DIR/${TEST_PREFIX}-custom-1.5-1.pkg.tar.zst" bs=1M count=$TEST_SIZE_MB > /dev/null 2>&1

# Adatbázis fájl
cd "$OUTPUT_DIR"
tar czf "${TEST_PREFIX}-repo.db.tar.gz" "${TEST_PREFIX}"-*.pkg.tar.zst > /dev/null 2>&1 || true

info "Fájlok elkészültek:"
ls -lh "$OUTPUT_DIR"/*.pkg.tar.* 2>/dev/null || true
echo ""

# === 4. RSYNC FELTÖLTÉS ===
info "4. RSYNC feltöltés indítása..."
info "  Forrás: $OUTPUT_DIR/"
info "  Cél: $VPS_USER@$VPS_HOST:$REMOTE_DIR/"
echo ""

# RSYNC opciók
RSYNC_CMD="rsync -avz --progress --stats --chmod=0644"
RSYNC_CMD="$RSYNC_CMD -e 'ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30'"
RSYNC_CMD="$RSYNC_CMD '$OUTPUT_DIR/'*.pkg.tar.*"
RSYNC_CMD="$RSYNC_CMD '$VPS_USER@$VPS_HOST:$REMOTE_DIR/'"

log "RSYNC parancs: $RSYNC_CMD"
echo ""

START_TIME=$(date +%s)

# RSYNC futtatása
if eval $RSYNC_CMD 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    success "RSYNC sikeres! ($DURATION másodperc)"
    
    # Fájlok ellenőrzése
    info "5. Fájlok ellenőrzése a szerveren..."
    ssh "$VPS_USER@$VPS_HOST" "
        echo 'Fájlok a szerveren:'
        ls -lh '$REMOTE_DIR'/*.pkg.tar.* 2>/dev/null | head -10
        echo ''
        echo 'Összesen: \$(ls -1 \"$REMOTE_DIR\"/*.pkg.tar.* 2>/dev/null | wc -l) fájl'
        echo 'Méret: \$(du -sh \"$REMOTE_DIR\" 2>/dev/null || echo \"0\")'
    "
else
    error "RSYNC sikertelen!"
    RSYNC_ERROR=1
fi

# === 6. TAKARÍTÁS ===
info "6. Takarítás..."
rm -rf "$OUTPUT_DIR"/* 2>/dev/null && success "Lokális fájlok törölve" || error "Lokális törlés sikertelen"

ssh "$VPS_USER@$VPS_HOST" "
    rm -f '$REMOTE_DIR'/${TEST_PREFIX}-*.pkg.tar.* 2>/dev/null
    rm -f '$REMOTE_DIR'/${TEST_PREFIX}-*.db.tar.gz 2>/dev/null
    echo 'Távoli tesztfájlok törölve'
" || true

# === 7. ÖSSZEFOGLALÓ ===
echo ""
echo "========================================"
info "=== TESZT VÉGE ==="
echo ""
if [ -z "$RSYNC_ERROR" ]; then
    success "🎉 RSYNC MŰKÖDIK!"
    echo ""
    echo "Az eredeti CI script RSYNC-re átírható."
    echo ""
    echo "Javasolt RSYNC opciók a CI-hez:"
    echo "  rsync -avz --progress --stats \\"
    echo "    -e 'ssh -o StrictHostKeyChecking=no' \\"
    echo "    built_packages/* \\"
    echo "    user@host:/remote/dir/"
else
    error "RSYNC SIKERTELEN"
    echo ""
    echo "Hibaelhárítás:"
    echo "1. Ellenőrizd az SSH kulcsot"
    echo "2. Ellenőrizd a távoli könyvtár jogosultságait"
    echo "3. Ellenőrizd a tűzfal beállításokat"
fi
echo ""
echo "🕒 Teszt időpont: $(date)"
echo "========================================"