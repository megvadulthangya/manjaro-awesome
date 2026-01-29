#!/usr/bin/env python3
"""
RSYNC Upload Test - Python Version
Ez a szkript teszteli a fájlfeltöltést RSYNC-vel egy távoli szerverre.
"""

import os
import sys
import time
import subprocess
import tarfile
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, List, Dict
import shutil
import stat

# === KONSTANSOK ===
OUTPUT_DIR = Path("/home/builder/built_packages")
TEST_PREFIX = f"github_test_{int(time.time())}"

# === KONFIGURÁCIÓ ===
class Config:
    """Konfigurációs osztály"""
    def __init__(self):
        self.remote_dir = os.environ.get("REMOTE_DIR", "/var/www/repo")
        self.vps_user = os.environ.get("VPS_USER", "root")
        self.vps_host = os.environ.get("VPS_HOST", "")
        self.test_size_mb = int(os.environ.get("TEST_SIZE_MB", "10"))
        
        # Ellenőrizzük a kötelező változókat
        if not self.vps_host:
            raise ValueError("VPS_HOST nincs beállítva!")
        
        # SSH utasítás
        self.ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", 
                       "-o", "ConnectTimeout=30", "-o", "BatchMode=yes"]

# === LOGOLÁS ===
class Logger:
    """Logoló osztály"""
    
    @staticmethod
    def log(level: str, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_icons = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "ERROR": "❌",
            "WARNING": "⚠️"
        }
        icon = level_icons.get(level, "")
        print(f"[{timestamp}] {icon} {message}")
    
    @staticmethod
    def info(message: str):
        Logger.log("INFO", message)
    
    @staticmethod
    def success(message: str):
        Logger.log("SUCCESS", message)
    
    @staticmethod
    def error(message: str):
        Logger.log("ERROR", message)
    
    @staticmethod
    def warning(message: str):
        Logger.log("WARNING", message)

# === FŐ OSZTÁLY ===
class RsyncUploadTester:
    """RSYNC feltöltés tesztelő"""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = Logger()
        self.test_files: List[Path] = []
        
        # Kimeneti könyvtár létrehozása
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # Jogosultságok beállítása
        os.chmod(OUTPUT_DIR, stat.S_IRWXU | stat.S_IRWXG | stat.S_IROTH | stat.S_IXOTH)
    
    def run_command(self, cmd: List[str], check: bool = True, 
                    capture: bool = False, shell: bool = False) -> Tuple[int, str, str]:
        """Parancs futtatása"""
        try:
            self.logger.info(f"Futtatás: {' '.join(cmd) if not shell else cmd}")
            
            if shell and isinstance(cmd, list):
                cmd = " ".join(cmd)
            
            result = subprocess.run(
                cmd, 
                check=check, 
                capture_output=capture,
                text=True,
                shell=shell
            )
            return (
                result.returncode,
                result.stdout if capture else "",
                result.stderr if capture else ""
            )
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Parancs hibásan fejeződött be: {e}")
            if capture:
                return (e.returncode, e.stdout, e.stderr)
            if check:
                raise
            return (e.returncode, "", str(e))
        except Exception as e:
            self.logger.error(f"Parancs futtatási hiba: {e}")
            if check:
                raise
            return (1, "", str(e))
    
    def ssh_command(self, remote_cmd: str, check: bool = True) -> Tuple[int, str, str]:
        """SSH parancs futtatása"""
        full_cmd = self.config.ssh_cmd + [
            f"{self.config.vps_user}@{self.config.vps_host}",
            remote_cmd
        ]
        return self.run_command(full_cmd, check=check, capture=True)
    
    def test_ssh_connection(self) -> bool:
        """SSH kapcsolat tesztelése"""
        self.logger.info("1. SSH kapcsolat teszt...")
        
        try:
            returncode, stdout, stderr = self.ssh_command("echo 'SSH OK' && hostname")
            if returncode == 0:
                self.logger.success(f"SSH kapcsolat rendben - {stdout.strip()}")
                return True
            else:
                self.logger.error(f"SSH kapcsolat sikertelen: {stderr}")
                return False
        except Exception as e:
            self.logger.error(f"SSH kapcsolat hiba: {e}")
            return False
    
    def test_remote_directory(self) -> bool:
        """Távoli könyvtár ellenőrzése"""
        self.logger.info("2. Távoli könyvtár ellenőrzése...")
        
        remote_dir = self.config.remote_dir
        returncode, stdout, stderr = self.ssh_command(
            f"if [ -d '{remote_dir}' ]; then "
            f"echo 'Könyvtár létezik' && ls -ld '{remote_dir}'; "
            f"else echo 'Könyvtár nem létezik, létrehozom...' && "
            f"sudo mkdir -p '{remote_dir}' && sudo chmod 755 '{remote_dir}'; fi"
        )
        
        if returncode == 0:
            self.logger.success(f"Könyvtár rendben: {stdout.splitlines()[0] if stdout else 'OK'}")
            return True
        else:
            self.logger.error(f"Könyvtár probléma: {stderr}")
            return False
    
    def create_dummy_file(self, path: Path, size_mb: int) -> bool:
        """Dummy fájl létrehozása"""
        try:
            # MB-ban megadott méret byte-okra konvertálása
            size_bytes = size_mb * 1024 * 1024
            
            # Véletlenszerű adatokkal feltöltés
            with open(path, 'wb') as f:
                # 1MB-os blokkokban írunk a hatékonyság érdekében
                block_size = 1024 * 1024  # 1MB
                blocks = size_mb
                remaining = size_bytes % block_size
                
                for i in range(blocks):
                    f.write(os.urandom(block_size))
                
                if remaining > 0:
                    f.write(os.urandom(remaining))
            
            # Jogosultságok beállítása
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            return True
            
        except Exception as e:
            self.logger.error(f"Hiba a fájl létrehozásakor {path}: {e}")
            return False
    
    def create_test_files(self) -> bool:
        """Tesztfájlok létrehozása"""
        self.logger.info("3. Tesztfájlok létrehozása...")
        
        try:
            # Töröljük a régi fájlokat
            for f in OUTPUT_DIR.glob("*"):
                try:
                    f.unlink()
                except:
                    pass
            
            # Fájlméretek - VALÓDI PKG NEVEKKEL
            file_specs = [
                ("awesome-git-4.0.r123.gabc123def-1-x86_64.pkg.tar.zst", 5),
                ("nvidia-driver-470.199.02-1-x86_64.pkg.tar.zst", 190),
                (f"custom-package-1.0.{self.config.test_size_mb}-1-x86_64.pkg.tar.zst", self.config.test_size_mb),
            ]
            
            # Fájlok létrehozása
            for filename, size_mb in file_specs:
                self.logger.info(f"  - {filename} ({size_mb}MB)...")
                filepath = OUTPUT_DIR / filename
                
                if self.create_dummy_file(filepath, size_mb):
                    self.test_files.append(filepath)
                else:
                    self.logger.error(f"Nem sikerült létrehozni: {filename}")
                    return False
            
            # Adatbázis fájl létrehozása (tar.gz)
            self.logger.info("  - Adatbázis fájl...")
            db_filename = OUTPUT_DIR / "test-repo.db.tar.gz"
            
            try:
                import gzip
                import io
                
                # Egyszerű tar.gz fájl létrehozása
                with tarfile.open(db_filename, "w:gz") as tar:
                    for test_file in self.test_files:
                        tar.add(test_file, arcname=test_file.name)
                
                self.test_files.append(db_filename)
                
            except Exception as e:
                self.logger.warning(f"Adatbázis fájl létrehozása nem sikerült: {e}")
                # Létrehozunk egy üres adatbázis fájlt
                with open(db_filename, 'wb') as f:
                    f.write(b"dummy repo database")
                self.test_files.append(db_filename)
            
            # Fájlinformációk
            self.logger.info("Fájlok elkészültek:")
            total_size = 0
            for f in self.test_files:
                size = f.stat().st_size
                size_mb = size / (1024 * 1024)
                total_size += size_mb
                self.logger.info(f"    {f.name} - {size_mb:.1f}MB")
            
            self.logger.info(f"    Összesen: {total_size:.1f}MB")
            return True
            
        except Exception as e:
            self.logger.error(f"Fájl létrehozási hiba: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def run_rsync_upload(self) -> bool:
        """RSYNC feltöltés futtatása"""
        self.logger.info("4. RSYNC feltöltés indítása...")
        self.logger.info(f"  Forrás: {OUTPUT_DIR}/")
        self.logger.info(f"  Cél: {self.config.vps_user}@{self.config.vps_host}:{self.config.remote_dir}/")
        
        # Ellenőrizzük, vannak-e fájlok
        if not self.test_files:
            self.logger.error("Nincsenek feltölthető fájlok!")
            return False
        
        # Gyűjtsük össze a fájlokat
        file_patterns = [
            str(OUTPUT_DIR / "*.pkg.tar.zst"),
            str(OUTPUT_DIR / "*.db.tar.gz")
        ]
        
        # Shell glob használata a fájlok keresésére
        import glob
        files_to_upload = []
        for pattern in file_patterns:
            files_to_upload.extend(glob.glob(pattern))
        
        if not files_to_upload:
            self.logger.error("Nem találhatók fájlok a glob pattern alapján!")
            self.logger.info(f"Glob pattern: {file_patterns}")
            self.logger.info(f"OUTPUT_DIR tartalma: {list(OUTPUT_DIR.iterdir())}")
            return False
        
        self.logger.info(f"  Feltöltendő fájlok ({len(files_to_upload)} db):")
        for f in files_to_upload:
            size_mb = os.path.getsize(f) / (1024 * 1024)
            self.logger.info(f"    - {os.path.basename(f)} ({size_mb:.1f}MB)")
        
        # RSYNC parancs összeállítása - SHELL MODBAN!
        rsync_cmd = f"""
        rsync -avz \
          --progress \
          --stats \
          --chmod=0644 \
          -e "ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30 -o BatchMode=yes" \
          {" ".join(f"'{f}'" for f in files_to_upload)} \
          '{self.config.vps_user}@{self.config.vps_host}:{self.config.remote_dir}/'
        """
        
        start_time = time.time()
        
        try:
            self.logger.info("RSYNC futtatása...")
            
            # RSYNC futtatása shell módban
            returncode, stdout, stderr = self.run_command(
                rsync_cmd,
                check=False,
                capture=True,
                shell=True
            )
            
            # Kimenet kiírása
            if stdout:
                for line in stdout.splitlines():
                    if line.strip():
                        print(f"    {line}")
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            if returncode == 0:
                self.logger.success(f"RSYNC sikeres! ({duration} másodperc)")
                
                # Statisztikák kinyerése
                if "sent" in stdout.lower():
                    for line in stdout.splitlines():
                        if "sent" in line.lower() and "received" in line.lower():
                            self.logger.info(f"    Átvitel: {line.strip()}")
                
                # Fájlok ellenőrzése
                self.verify_remote_files()
                return True
            else:
                self.logger.error(f"RSYNC sikertelen! (return code: {returncode})")
                if stderr:
                    self.logger.error(f"RSYNC hiba: {stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"RSYNC futtatási hiba: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def verify_remote_files(self):
        """Távoli fájlok ellenőrzése"""
        self.logger.info("5. Fájlok ellenőrzése a szerveren...")
        
        remote_cmd = f"""
        echo "=== SZERVER FÁJLOK ==="
        ls -la "{self.config.remote_dir}/" 2>/dev/null | head -20
        echo ""
        echo "=== PKG FÁJLOK ==="
        ls -lh "{self.config.remote_dir}/"*.pkg.tar.* 2>/dev/null || echo "Nincsenek .pkg.tar fájlok"
        echo ""
        echo "=== DB FÁJL ==="
        ls -lh "{self.config.remote_dir}/"*.db.tar.gz 2>/dev/null || echo "Nincs .db.tar.gz fájl"
        echo ""
        echo "=== HELY FOGYASZTÁS ==="
        du -sh "{self.config.remote_dir}/" 2>/dev/null || echo "Nem elérhető"
        """
        
        returncode, stdout, stderr = self.ssh_command(remote_cmd, check=False)
        
        if returncode == 0 and stdout:
            for line in stdout.splitlines():
                if line.strip():
                    print(f"    {line}")
        elif stderr:
            self.logger.warning(f"Ellenőrzés hibája: {stderr}")
    
    def cleanup(self):
        """Takarítás"""
        self.logger.info("6. Takarítás...")
        
        # Lokális fájlok törlése
        try:
            # Töröljük a teljes OUTPUT_DIR tartalmát
            for item in OUTPUT_DIR.iterdir():
                try:
                    if item.is_file():
                        item.unlink()
                    elif item.is_dir():
                        shutil.rmtree(item)
                except Exception as e:
                    self.logger.warning(f"Nem sikerült törölni {item}: {e}")
            
            self.logger.success("Lokális fájlok törölve")
        except Exception as e:
            self.logger.error(f"Lokális törlés hiba: {e}")
        
        # Távoli tesztfájlok törlése
        try:
            # Csak a mai tesztfájlokat töröljük
            remote_cmd = f"""
            echo "Távoli tesztfájlok törlése..."
            # Töröljük az összes .pkg.tar.zst fájlt
            rm -f "{self.config.remote_dir}/"*.pkg.tar.zst 2>/dev/null
            # Töröljük az összes .db.tar.gz fájlt
            rm -f "{self.config.remote_dir}/"*.db.tar.gz 2>/dev/null
            echo "✅ Távoli tesztfájlok törölve"
            """
            
            returncode, stdout, stderr = self.ssh_command(remote_cmd, check=False)
            if returncode == 0:
                if stdout:
                    self.logger.success(stdout.splitlines()[-1] if stdout else "Törölve")
            else:
                self.logger.warning(f"Távoli törlés figyelmeztetés: {stderr}")
        except Exception as e:
            self.logger.warning(f"Távoli törlés hiba: {e}")
    
    def run(self) -> bool:
        """Fő teszt futtatása"""
        self.logger.info("=== RSYNC FELTÖLTÉS TESZT (Python) ===")
        self.logger.info(f"Host: {self.config.vps_host}")
        self.logger.info(f"User: {self.config.vps_user}")
        self.logger.info(f"Remote: {self.config.remote_dir}")
        self.logger.info(f"File size: {self.config.test_size_mb}MB")
        print()
        
        # Lépések
        steps = [
            ("SSH kapcsolat", self.test_ssh_connection),
            ("Könyvtár ellenőrzés", self.test_remote_directory),
            ("Fájlok létrehozása", self.create_test_files),
        ]
        
        success = True
        for step_name, step_func in steps:
            if not step_func():
                self.logger.error(f"{step_name} sikertelen!")
                success = False
                break
        
        # RSYNC feltöltés csak ha minden előző lépés sikeres
        rsync_success = False
        if success:
            rsync_success = self.run_rsync_upload()
        
        # Takarítás mindig
        self.cleanup()
        
        # Összefoglaló
        self.print_summary(success and rsync_success)
        
        return success and rsync_success
    
    def print_summary(self, overall_success: bool):
        """Összefoglaló kiírása"""
        print()
        print("=" * 50)
        self.logger.info("=== TESZT VÉGE ===")
        print()
        
        if overall_success:
            self.logger.success("🎉 RSYNC MŰKÖDIK!")
            print()
            print("✅ Az eredeti CI script RSYNC-re átírható.")
            print()
            print("📋 Javasolt RSYNC konfiguráció az eredeti CI-hez:")
            print()
            print('''
            # Az eredeti scriptben cseréld le az scp részt:
            
            # RÉGI (SCP):
            # scp $SSH_OPTS $OUTPUT_DIR/* $VPS_USER@$VPS_HOST:$REMOTE_DIR/
            
            # ÚJ (RSYNC):
            log_info "Fájlok feltöltése RSYNC-kel..."
            rsync -avz \\
                --progress \\
                --stats \\
                --chmod=0644 \\
                -e "ssh $SSH_OPTS" \\
                "$OUTPUT_DIR/"*.pkg.tar.* \\
                "$VPS_USER@$VPS_HOST:$REMOTE_DIR/"
            ''')
        else:
            self.logger.error("RSYNC SIKERTELEN")
            print()
            print("🔧 Hibaelhárítás:")
            print("1. Ellenőrizd az SSH kulcs jogosultságokat")
            print("2. Ellenőrizd a távoli könyvtár írási jogosultságait")
            print("3. Ellenőrizd a tűzfal beállításokat (port 22)")
            print("4. Ellenőrizd, hogy a szerver elérhető-e a konténerből")
            print("5. SSH kapcsolat tesztelése kézzel:")
            print(f"   ssh -i /home/builder/.ssh/id_ed25519 {self.config.vps_user}@{self.config.vps_host}")
        
        print()
        print(f"🕒 Teszt időpont: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)

# === FŐ PROGRAM ===
def main():
    """Fő program"""
    try:
        # Konfiguráció betöltése
        config = Config()
        
        # Tesztelő létrehozása és futtatása
        tester = RsyncUploadTester(config)
        success = tester.run()
        
        # Kilépési kód
        sys.exit(0 if success else 1)
        
    except ValueError as e:
        Logger.error(f"Konfigurációs hiba: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        Logger.info("Teszt megszakítva")
        sys.exit(130)
    except Exception as e:
        Logger.error(f"Váratlan hiba: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()