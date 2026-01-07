# A build_package_intelligent függvényben, a verzió kinyerés után:

# 3. VERZIÓ INFORMÁCIÓK
local full_ver=""
local rel_ver=""
local epoch_val=""

if [ -f PKGBUILD ]; then
    # Kinyerjük az epoch-ot
    epoch_val=$(grep '^epoch=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "")
    
    # Kinyerjük a verziót
    full_ver=$(grep '^pkgver=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "")
    rel_ver=$(grep '^pkgrel=' PKGBUILD | head -1 | cut -d= -f2 | tr -d "'\"" || echo "1")
fi

if [ -z "$full_ver" ]; then
    full_ver="unknown"
fi
if [ -z "$rel_ver" ]; then
    rel_ver="1"
fi

# Ha van epoch, hozzáadjuk
local current_version
if [ -n "$epoch_val" ] && [ "$epoch_val" != "" ]; then
    current_version="${epoch_val}:${full_ver}-${rel_ver}"
else
    current_version="${full_ver}-${rel_ver}"
fi