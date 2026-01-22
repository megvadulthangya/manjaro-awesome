# Manjaro-Builder - Moduláris Architektúra Dokumentáció

## 1. PROJEKT ÁTTEKINTÉS

Az Arch Linux Builder egy automatizált rendszer, amely **AUR (Arch User Repository)** és helyi csomagok fordítását, **GPG aláírását**, és egy távoli **VPS-en** tárolt Arch Linux repozitóriumba való szinkronizálását végzi.

### Fő célok:
- **Automatizált csomagépítés**: AUR és helyi csomagok automatikus fordítása a legfrissebb verziókra
- **GPG aláírás**: Repozitórium fájlok digitális aláírása biztonságos disztribúció érdekében
- **Zero-Residue politika**: A szerveren csak az aktuális verziók maradnak, régebbi verziók automatikus eltávolítása
- **Modularitás**: A korábbi 3200 soros monolitikus kód modulokra bontása jobb karbantarthatóság érdekében

## 2. KÖNYVTÁRSZERKEZET ÉS MODULOK

### 2.1 Fő struktúra
```
.github/scripts/
├── builder.py                 # Fő vezérlő (orchestrator)
├── modules/
│   ├── __init__.py           # Modulok exportálása, csomagszintű elérés
│   ├── repo_manager.py       # Adatbázis kezelés és Zero-Residue tisztítás
│   ├── vps_client.py         # SSH és Rsync műveletek
│   ├── build_engine.py       # AUR és helyi csomagok fordítása
│   └── gpg_handler.py        # GPG aláírás kezelése
├── config.py                 # Konfigurációs fájl (opcionális)
└── packages.py              # Csomaglisták (LOCAL_PACKAGES, AUR_PACKAGES)
```

### 2.2 Modulok részletes leírása

#### **`builder.py` - Fő Vezérlő (Orchestrator)**
- **Felelősség**: A modulok koordinálása, folyamatok sorrendjének irányítása
- **Kulcsfontosságú metódusok**:
  - `run()`: Fő végrehajtási metódus
  - `_init_modules()`: Modulok inicializálása
  - `_apply_repository_state()`: Pacman konfiguráció frissítése

#### **`repo_manager.py` - Repository Kezelő**
- **Felelősség**: Adatbázis műveletek és Zero-Residue tisztítás
- **Kritikus funkciók**:
  ```python
  # ZERO-RESIDUE MAG
  server_cleanup()            # Szerveren lévő árva fájlok törlése
  pre_build_purge_old_versions()  # Régi verziók eltávolítása build előtt
  generate_full_database()    # Teljes repo adatbázis generálása
  ```
- **Zero-Residue logika**: A szerver állapotát a helyi kimeneti könyvtárhoz igazítja

#### **`vps_client.py` - VPS Kliens**
- **Felelősség**: Távoli szerverrel való kommunikáció
- **Fő műveletek**:
  ```python
  setup_ssh_config()          # SSH konfiguráció beállítása
  mirror_remote_packages()    # Távoli csomagok helyi tükrözése
  upload_files()             # Fájlok feltöltése rsync-csel
  test_ssh_connection()      # SSH kapcsolat ellenőrzése
  ```

#### **`build_engine.py` - Build Motor**
- **Felelősség**: Csomagépítési logika és verziókezelés
- **Kulcsfontosságú funkciók**:
  ```python
  extract_version_from_srcinfo()  # Verzió információk kinyerése
  compare_versions()         # Verzió-összehasonlítás (vercmp)
  clean_workspace()         # Munkaterület tisztítása
  install_dependencies_strict()  # Függőségek telepítése
  ```

#### **`gpg_handler.py` - GPG Kezelő**
- **Felelősség**: GPG kulcsok és aláírások kezelése
- **Fontos metódusok**:
  ```python
  import_gpg_key()          # GPG kulcs importálása konténer-kompatibilis módon
  sign_repository_files()   # Repozitórium fájlok aláírása
  cleanup()                # Ideiglenes GPG könyvtár törlése
  ```

## 3. LOGIKAI FOLYAMAT (WORKFLOW)

### 3.1 Teljes folyamat áttekintése
```
1. GPG inicializálás
   ↓
2. Távoli állapot felmérése
   ↓
3. Helyi tükrözés (MANDATORY)
   ↓
4. Csomagok ellenőrzése/építése
   ↓
5. Adatbázis generálás + GPG aláírás
   ↓
6. Feltöltés VPS-re
   ↓
7. Zero-Residue tisztítás (sikeres feltöltés után)
   ↓
8. Pacman adatbázis frissítés
```

### 3.2 Részletes lépések

#### **1. GPG Inicializálás**
```python
# 1.1 GPG_PRIVATE_KEY és GPG_KEY_ID ellenőrzése
# 1.2 Kulcs importálása ideiglenes GNUPGHOME könyvtárba
# 1.3 Kulcs hozzáadása pacman-key keyring-hez
# 1.4 Ultimate trust beállítása (6 = ultimate)
```

#### **2. Távoli Állapot Felmérése**
```python
# 2.1 SSH kapcsolat tesztelése
# 2.2 Repository létezésének ellenőrzése VPS-en
# 2.3 Pacman konfiguráció frissítése (/etc/pacman.conf)
#    - Ha repository létezik: SigLevel = Optional TrustAll
#    - Ha nem létezik: kommentálva marad
```

#### **3. Helyi Tükrözés (KÖTELEZŐ)**
```python
# 3.1 Összes távoli csomag listázása SSH-val
# 3.2 Csomagok letöltése rsync-csel mirror_temp_dir-be
# 3.3 Érvényes csomagok másolása output_dir-be
# 3.4 Mirror könyvtár törlése
```

#### **4. Csomagok Ellenőrzése/Építése**
```python
# 4.1 packages.py betöltése (LOCAL_PACKAGES, AUR_PACKAGES)
# 4.2 Minden csomag esetében:
#   - .SRCINFO-ból verzió kinyerése
#   - Távoli verzió ellenőrzése
#   - Verzió-összehasonlítás (vercmp)
#   - Ha újabb: build indítása
#   - Ha nem újabb: SKIP, de ZERO-RESIDUE tisztítás!
```

#### **5. Adatbázis Generálás**
```python
# 5.1 Összes helyi csomag összegyűjtése
# 5.2 Régi adatbázis fájlok törlése
# 5.3 repo-add futtatása shell=True-val (wildcard támogatás)
# 5.4 Adatbázis aláírása (ha GPG engedélyezett)
```

#### **6. Feltöltés VPS-re**
```python
# 6.1 Feltöltendő fájlok összegyűjtése
# 6.2 Rsync futtatása --delete NÉLKÜL
# 6.3 Sikertelen feltöltés esetén újrapróbálkozás
# 6.4 _upload_successful flag beállítása
```

#### **7. Zero-Residue Tisztítás**
```python
# 7.1 Csak sikeres feltöltés után fut!
# 7.2 Helyi kimeneti könyvtár valid fájljainak összegyűjtése
# 7.3 VPS összes fájljának listázása
# 7.4 Árva fájlok azonosítása (VPS-en van, helyi nincs)
# 7.5 Metaadatok védelme (.db, .sig fájlok)
# 7.6 Árva fájlok törlése ATOMIKUSAN
```

#### **8. Pacman Frissítés**
```python
# 8.1 Pacman adatbázis szinkronizálás (pacman -Sy)
# 8.2 Repository állapotának ellenőrzése (pacman -Sl)
```

## 4. ZERO-RESIDUE ÉS TAKARÍTÁSI POLITIKA

### 4.1 A "Zero-Residue" filozófia
A rendszer garantálja, hogy a VPS szerveren **csak az aktuális csomagverziók maradnak**. Ez a következőket jelenti:

1. **Régi verziók automatikus eltávolítása** új build előtt
2. **Build skip esetén is tisztítás** - ha egy csomag nem épül (mert a verzió nem újabb), a régebbi verziókat mégis eltávolítja
3. **Forrásként a helyi kimeneti könyvtár** - csak ami itt van, az marad a szerveren

### 4.2 Tisztítási szcenáriók

#### **Scenarió 1: Build skip (qownnotes példa)**
```
VPS szerveren: qownnotes-26.1.9
Új verzió: 26.1.10 (NEM épül, mert 26.1.9 már létezik)

MEGTÖRTÉNIK:
1. pre_build_purge_old_versions("qownnotes", "26.1.9")
2. qownnotes-26.1.9 törlődik a helyi könyvtárból
3. server_cleanup() törli a VPS-ről is
```

#### **Scenarió 2: Sikeres build**
```
VPS szerveren: qownnotes-26.1.9
Új verzió: 26.1.10 (épül, mert újabb)

MEGTÖRTÉNIK:
1. pre_build_purge_old_versions("qownnotes", "26.1.9")
2. qownnotes-26.1.10 építése
3. qownnotes-26.1.9 törlése VPS-ről server_cleanup() által
```

### 4.3 Védett fájltípusok
A következő fájlok **NEM TÖRŐDHETNEK** a tisztítás során:
- `.db`, `.db.tar.gz`, `.db.sig`
- `.files`, `.files.tar.gz`, `.files.sig`
- `.abs.tar.gz`

## 5. BIZTONSÁGI SZELEPEK (SAFETY VALVES)

### 5.1 Feltöltés sikertelenségi szelep
```python
# A tisztítás NEM futhat, ha a feltöltés sikertelen
if not self._upload_successful:
    logger.error("❌ SAFETY VALVE: Cleanup cannot run because upload was not successful!")
    return
```

### 5.2 Üres kimeneti könyvtár védelme
```python
# Ha nincs érvényes fájl a helyi könyvtárban, NEM törölhetünk
if len(valid_filenames) == 0:
    logger.error("❌❌❌ CRITICAL SAFETY VALVE ACTIVATED: No valid files in output directory!")
    logger.error("   🚨 CLEANUP ABORTED - Output directory empty, potential data loss!")
    return
```

### 5.3 SSH kapcsolat védelme
```python
# SSH parancsok timeout-tal
try:
    result = subprocess.run(ssh_cmd, timeout=30, ...)
except subprocess.TimeoutExpired:
    logger.error("❌ SSH command timed out - aborting cleanup for safety")
```

### 5.4 Metaadatok védelme
```python
# Védett kiterjesztések listája
protected_extensions = [
    '.db', '.db.tar.gz', '.db.sig',
    '.files', '.files.tar.gz', '.files.sig',
    '.abs.tar.gz'
]
```

## 6. KÖRNYEZETI VÁLTOZÓK (SECRETS)

### 6.1 Kötelező változók

| Változó | Leírás | Példa |
|---------|---------|--------|
| `REPO_NAME` | Repository neve (csak alfanumerikus, kötőjel, aláhúzás) | `my-awesome-repo` |
| `VPS_HOST` | VPS szerver hosztneve vagy IP címe | `repo.example.com` |
| `VPS_USER` | SSH felhasználónév | `deploy-user` |
| `VPS_SSH_KEY` | SSH privát kulcs (OpenSSH formátum) | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `REMOTE_DIR` | Távoli könyvtár elérési útja | `/var/www/html/repo` |

### 6.2 Opcionális (de ajánlott) változók

| Változó | Leírás | Példa |
|---------|---------|--------|
| `REPO_SERVER_URL` | Repository teljes URL-je | `https://repo.example.com/repo` |
| `GPG_KEY_ID` | GPG kulcs ID (16 karakter hex) | `ABCD1234EFGH5678` |
| `GPG_PRIVATE_KEY` | GPG privát kulcs (ASCII-armored) | `-----BEGIN PGP PRIVATE KEY BLOCK-----...` |
| `GITHUB_REPO` | GitHub repository elérési út | `felhasznalo/repository.git` |

### 6.3 GitHub Actions Secrets beállítása
```yaml
# .github/workflows/build.yml
env:
  REPO_NAME: ${{ secrets.REPO_NAME }}
  VPS_HOST: ${{ secrets.VPS_HOST }}
  VPS_USER: ${{ secrets.VPS_USER }}
  VPS_SSH_KEY: ${{ secrets.VPS_SSH_KEY }}
  REMOTE_DIR: ${{ secrets.REMOTE_DIR }}
  GPG_KEY_ID: ${{ secrets.GPG_KEY_ID }}
  GPG_PRIVATE_KEY: ${{ secrets.GPG_PRIVATE_KEY }}
```

## 7. HIBAELHÁRÍTÁS (TROUBLESHOOTING)

### 7.1 Gyors referencia: Melyik modulhoz nyúljunk?

| Probléma | Első modul | Második modul | Ellenőrzendő |
|----------|------------|---------------|--------------|
| **GPG hiba** | `gpg_handler.py` | `builder.py` | Környezeti változók, kulcs formátum |
| **SSH kapcsolat hiba** | `vps_client.py` | - | SSH kulcs, tűzfal, hosztnév |
| **Build hiba** | `build_engine.py` | - | Függőségek, internet kapcsolat |
| **Repository szinkron hiba** | `repo_manager.py` | `vps_client.py` | Jogosultságok, lemezterület |
| **Zero-Residue tisztítás hiba** | `repo_manager.py` | - | `_upload_successful` flag |

### 7.2 Gyakori hibák és megoldások

#### **Hiba: "GPG key import failed"**
```bash
# Ellenőrizd:
1. GPG_PRIVATE_KEY formátuma (ASCII-armored)
2. GPG_KEY_ID formátuma (16 karakter hex)
3. A konténerben elérhető-e a gpg parancs

# Teszt parancs:
echo "$GPG_PRIVATE_KEY" | gpg --import
```

#### **Hiba: "SSH connection failed"**
```bash
# Ellenőrizd:
1. VPS_SSH_KEY formátuma (OpenSSH)
2. VPS_HOST és VPS_USER helyessége
3. Tűzfal beállítások (port 22)

# Teszt parancs:
ssh -o StrictHostKeyChecking=no -i ~/.ssh/id_ed25519 $VPS_USER@$VPS_HOST "echo test"
```

#### **Hiba: "repo-add failed"**
```bash
# Ellenőrizd:
1. Jogosultságok a kimeneti könyvtárban
2. Csomagfájlok létezése
3. repo-add parancs elérhetősége

# Teszt parancs:
cd output_dir && repo-add test.db *.pkg.tar.zst
```

#### **Hiba: "Zero-Residue cleanup deletes wrong files"**
```bash
# Ellenőrizd:
1. A helyi output_dir tartalma
2. A védett fájltípusok listája
3. Log fájl: builder.log

# Debug mód:
export DEBUG_CLEANUP=1
python builder.py
```

### 7.3 Log fájlok és debugging

#### **Log szintek**
```python
# builder.py-ban módosítható
logging.basicConfig(
    level=logging.DEBUG,  # Változtasd DEBUG-ra részletes loghoz
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('builder.log')  # Teljes log fájl
    ]
)
```

#### **Kulcsfontosságú log üzenetek**
```
✅ SIKERES: "✅ GPG key imported successfully"
🚨 HIBA: "❌ SSH command timed out"
🔍 DEBUG: "[DEBUG] Comparing Package: Remote(..."
🗑️  TÖRLÉS: "🗑️ Pre-emptively removed old version"
```

### 7.4 Manuális tesztelés

#### **Teljes folyamat tesztelése**
```bash
# 1. Környezeti változók beállítása
export REPO_NAME="test-repo"
export VPS_HOST="test.example.com"
# ... stb.

# 2. Script futtatása
cd .github/scripts
python builder.py

# 3. Log követése
tail -f builder.log
```

#### **Modulonkénti tesztelés**
```python
# Python interpreterben
from modules.repo_manager import RepoManager
from modules.vps_client import VPSClient

# Konfiguráció
config = {
    'repo_name': 'test-repo',
    'output_dir': '/path/to/output',
    # ... többi konfig
}

# Teszt példány
repo_mgr = RepoManager(config)
vps_client = VPSClient(config)

# Funkciók tesztelése
vps_client.test_ssh_connection()
```

---

## 8. FEJLESZTÉSI ÚTMUTATÓ

### 8.1 Új modul hozzáadása
1. Hozz létre új fájlt a `modules/` könyvtárban
2. Implementáld az osztályt a megfelelő interfészekkel
3. Importáld a `modules/__init__.py`-ban
4. Inicializáld a `builder.py` `_init_modules()` metódusában

### 8.2 Konfiguráció bővítése
```python
# config.py új változó
NEW_CONFIG_VALUE = "érték"

# builder.py betöltés
if HAS_CONFIG_FILES:
    self.new_value = getattr(config, 'NEW_CONFIG_VALUE', 'alapértelmezett')
```

### 8.3 Zero-Residue logika testreszabása
```python
# repo_manager.py módosítás
class RepoManager:
    def custom_cleanup_logic(self):
        """Egyedi tisztítási logika"""
        # Implementáld a saját logikádat
        pass
```

---

## 9. TELJESÍTMÉNYOPTIMALIZÁLÁS

### 9.1 Parallel build támogatás (jövőbeli)
```python
# build_engine.py kiterjesztése
from concurrent.futures import ThreadPoolExecutor

def build_packages_parallel(self, packages_list, max_workers=3):
    """Párhuzamos csomagépítés"""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for pkg in packages_list:
            future = executor.submit(self._build_single_package, pkg)
            futures.append(future)
        
        # Eredmények gyűjtése
        results = [f.result() for f in futures]
    return results
```

### 9.2 Cache réteg hozzáadása
```python
# repo_manager.py cache támogatással
import json
from functools import lru_cache

class RepoManager:
    @lru_cache(maxsize=128)
    def get_remote_package_cache(self, pkg_name):
        """Cache-elt távoli csomag információk"""
        return self.get_remote_version(pkg_name)
```

---

**Dokumentáció frissítve**: 2026. január 22.  
**Verzió**: 2.0.0 (Moduláris refaktor)  
**Készítő**: @megvadulthangya  

*Ez a dokumentáció folyamatosan frissül a projekt változásainak megfelelően... vagy nem...*
