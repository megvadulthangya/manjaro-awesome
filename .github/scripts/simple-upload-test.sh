#!/bin/bash
set -e

# === EGYSZERŰ LOGOLÁS ===
log() { echo -e "$1"; }
info() { log "📦 $1"; }
success() { log "✅ $1"; }
error() { log "❌ $1"; }
warning() { log "⚠️  $1"; }

# === KÖRNYEZETI VÁLTOZÓK ===
REMOTE_DIR="${REMOTE_DIR:-/var/www/repo}"
VPS_USER="${VPS_USER:-root}"
VPS_HOST="${VPS_HOST:-}"
TEST_FILE_SIZE_MB="${TEST_FILE_SIZE_MB:-5}"

if [ -z "$VPS_HOST" ]; then
    error "VPS_HOST nincs beállítva!"
    exit 1
fi

info "=== FÁJLFELTÖLTÉS TESZT ==="
info "Host: $VPS_HOST"
info "User: $VPS_USER"
info "Remote dir: $REMOTE_DIR"
echo ""

# === SSH KAPCSOLAT EGYSZERŰ TESZT ===
info "1. SSH kapcsolat teszt..."
if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
   "$VPS_USER@$VPS_HOST" "echo '✓ Kapcsolat OK' && hostname"; then
    success "SSH kapcsolat rendben"
else
    error "SSH kapcsolat sikertelen"
    exit 1
fi

# === KÖNYVTÁR ELLENŐRZÉS ===
info "2. Távoli könyvtár ellenőrzés..."
if ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" \
   "[ -d '$REMOTE_DIR' ] && echo '✓ Könyvtár létezik' || echo '✗ Könyvtár nem létezik'"; then
    success "Könyvtár elérhető"
else
    error "Könyvtár nem elérhető"
fi

# === 1 FÁJL LÉTREHOZÁSA ===
info "3. Tesztfájl létrehozása (${TEST_FILE_SIZE_MB}MB)..."
TEST_FILE="/tmp/test_upload_$(date +%s).bin"
dd if=/dev/urandom of="$TEST_FILE" bs=1M count=$TEST_FILE_SIZE_MB status=none
FILE_SIZE=$(stat -c%s "$TEST_FILE")
success "Fájl létrehozva: $(numfmt --to=iec-i --suffix=B $FILE_SIZE)"

# === SCP FELTÖLTÉS ===
info "4. SCP feltöltés teszt..."
REMOTE_FILE="$REMOTE_DIR/test_scp_$(date +%s).bin"

START=$(date +%s.%N)
if scp -o StrictHostKeyChecking=no \
       -o ConnectTimeout=30 \
       -q \
       "$TEST_FILE" \
       "$VPS_USER@$VPS_HOST:$REMOTE_FILE"; then
    END=$(date +%s.%N)
    DURATION=$(echo "$END - $START" | bc | awk '{printf "%.2f", $0}')
    SPEED=$(echo "scale=2; $FILE_SIZE / 1024 / 1024 / $DURATION" | bc)
    success "SCP sikeres: ${DURATION}s (${SPEED} MB/s)"
else
    error "SCP sikertelen"
    SCP_ERROR=1
fi

# === RSYNC FELTÖLTÉS ===
info "5. RSYNC feltöltés teszt..."
REMOTE_FILE_RSYNC="$REMOTE_DIR/test_rsync_$(date +%s).bin"

START=$(date +%s.%N)
if rsync -az \
         --progress \
         --timeout=30 \
         -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30" \
         "$TEST_FILE" \
         "$VPS_USER@$VPS_HOST:$REMOTE_FILE_RSYNC" 2>/dev/null; then
    END=$(date +%s.%N)
    DURATION=$(echo "$END - $START" | bc | awk '{printf "%.2f", $0}')
    success "RSYNC sikeres: ${DURATION}s"
else
    error "RSYNC sikertelen"
    RSYNC_ERROR=1
fi

# === FÁJLOK ELLENŐRZÉSE ===
info "6. Fájlok ellenőrzése a szerveren..."
ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "
    echo 'Szerveren lévő tesztfájlok:'
    find '$REMOTE_DIR' -name 'test_*.bin' -exec ls -lh {} \; 2>/dev/null || echo 'Nincsenek tesztfájlok'
    
    echo -n 'Fájlok száma: '
    find '$REMOTE_DIR' -name 'test_*.bin' 2>/dev/null | wc -l
"

# === TAKARÍTÁS ===
info "7. Takarítás..."
# Lokális fájl törlése
rm -f "$TEST_FILE"

# Távoli fájlok törlése
ssh -o StrictHostKeyChecking=no "$VPS_USER@$VPS_HOST" "
    rm -f '$REMOTE_DIR'/test_*.bin 2>/dev/null && echo '✓ Tesztfájlok törölve' || echo '⚠️  Nincs törlendő fájl'
"

# === ÖSSZEFOGLALÓ ===
echo ""
info "=== TESZT EREDMÉNYEK ==="
echo "📊 Összegzés:"
echo "   • SSH kapcsolat: ✅ MŰKÖDIK"
echo "   • SCP feltöltés: $(if [ -z "$SCP_ERROR" ]; then echo "✅ SIKERES"; else echo "❌ SIKERTELEN"; fi)"
echo "   • RSYNC feltöltés: $(if [ -z "$RSYNC_ERROR" ]; then echo "✅ SIKERES"; else echo "❌ SIKERTELEN"; fi)"
echo ""
echo "💡 Javaslatok:"
echo "   1. Ha időtúllépések vannak, növeld a ConnectTimeout értékét"
echo "   2. RSYNC gyakran stabilabb instabil kapcsolaton (--partial flag)"
echo "   3. Ellenőrizd a tűzfalszabályokat és a hálózati késést"
echo ""
echo "🏁 Teszt vége: $(date)"