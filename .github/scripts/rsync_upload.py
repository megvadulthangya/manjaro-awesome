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
import tempfile
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, List

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
        self.ssh_cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=30"]

# === LOGOLÁS ===
class Logger:
    """Logoló osztály"""
    
    @staticmethod
    def log(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {message}")
    
    @staticmethod
    def info(message: str):
        Logger.log(f"ℹ️  {message}")
    
    @staticmethod
    def success(message: str):
        Logger.log(f"✅ {message}")
    
    @staticmethod
    def error(message: str):
        Logger.log(f"❌ {message}")
    
    @staticmethod
    def warning(message: str):
        Logger.log(f"⚠️  {message}")

# === FŐ OSZTÁLY ===
class RsyncUploadTester:
    """RSYNC feltöltés tesztelő"""
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = Logger()
        self.test_files: List[Path] = []
        
        # Kimeneti könyvtár létrehozása
        OUTPUT_DIR.mkdir(exist_ok=True)
    
    def run_command(self, cmd: List[str], check: bool = True, 
                    capture: bool = False) -> Tuple[int, str, str]:
        """Parancs futtatása"""
        try:
            self.logger.info(f"Futtatás: {' '.join(cmd)}")
            result = subprocess.run(
                cmd, 
                check=check, 
                capture_output=capture,
                text=True
            )
            return (
                result.returncode,
                result.stdout if capture else "",
                result.stderr if capture else ""
            )
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Parancs hibásan fejeződött be: {e}")
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
        cmd = self.config.ssh_cmd + [
            f"{self.config.vps_user}@{self.config.vps_host}",
            remote_cmd
        ]
        return self.run_command(cmd, check=check, capture=True)
    
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
            f"if [ -d '{remote_dir}' ]; then echo 'Könyvtár létezik'; "
            f"else echo 'Könyvtár nem létezik, létrehozom...'; "
            f"mkdir -p '{remote_dir}'; fi"
        )
        
        if returncode == 0:
            self.logger.success(f"Könyvtár rendben: {stdout.strip()}")
            return True
        else:
            self.logger.error(f"Könyvtár probléma: {stderr}")
            return False
    
    def create_test_files(self) -> bool:
        """Tesztfájlok létrehozása"""
        self.logger.info("3. Tesztfájlok létrehozása...")
        
        try:
            # Töröljük a régi fájlokat
            for f in OUTPUT_DIR.glob("*"):
                f.unlink()
            
            # Fájlméretek
            file_sizes = [
                ("small", 5),
                ("large", 190),
                ("custom", self.config.test_size_mb)
            ]
            
            # Fájlok létrehozása
            for name, size_mb in file_sizes:
                self.logger.info(f"  - {name} ({size_mb}MB)...")
                filename = OUTPUT_DIR / f"{TEST_PREFIX}-{name}-1.0-1.pkg.tar.zst"
                
                # dd parancs használata fájl létrehozására
                cmd = ["dd", "if=/dev/urandom", f"of={filename}", 
                       f"bs=1M", f"count={size_mb}", "status=none"]
                self.run_command(cmd)
                
                self.test_files.append(filename)
            
            # Adatbázis fájl létrehozása
            self.logger.info("  - Adatbázis fájl...")
            db_filename = OUTPUT_DIR / f"{TEST_PREFIX}-repo.db.tar.gz"
            
            with tarfile.open(db_filename, "w:gz") as tar:
                for test_file in self.test_files:
                    tar.add(test_file, arcname=test_file.name)
            
            self.test_files.append(db_filename)
            
            # Fájlinformációk
            self.logger.info("Fájlok elkészültek:")
            for f in self.test_files:
                size = f.stat().st_size
                size_mb = size / (1024 * 1024)
                self.logger.info(f"    {f.name} - {size_mb:.1f}MB")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Fájl létrehozási hiba: {e}")
            return False
    
    def run_rsync_upload(self) -> bool:
        """RSYNC feltöltés futtatása"""
        self.logger.info("4. RSYNC feltöltés indítása...")
        self.logger.info(f"  Forrás: {OUTPUT_DIR}/")
        self.logger.info(f"  Cél: {self.config.vps_user}@{self.config.vps_host}:{self.config.remote_dir}/")
        
        # RSYNC opciók
        rsync_cmd = [
            "rsync", "-avz", "--progress", "--stats", "--chmod=0644",
            "-e", f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=30"
        ]
        
        # Fájlok hozzáadása
        rsync_cmd.extend([str(OUTPUT_DIR / "*.pkg.tar.*"), 
                         f"{self.config.vps_user}@{self.config.vps_host}:{self.config.remote_dir}/"])
        
        start_time = time.time()
        
        try:
            # RSYNC futtatása
            self.logger.info(f"RSYNC parancs: {' '.join(rsync_cmd)}")
            
            # Subprocess futtatása a kimenettel
            process = subprocess.Popen(
                rsync_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Kimenet feldolgozása
            for line in process.stdout:
                if line.strip():  # Csak nem üres sorok
                    print(f"    {line.strip()}")
            
            process.wait()
            returncode = process.returncode
            
            end_time = time.time()
            duration = int(end_time - start_time)
            
            if returncode == 0:
                self.logger.success(f"RSYNC sikeres! ({duration} másodperc)")
                
                # Fájlok ellenőrzése
                self.verify_remote_files()
                return True
            else:
                self.logger.error(f"RSYNC sikertelen! (return code: {returncode})")
                return False
                
        except Exception as e:
            self.logger.error(f"RSYNC futtatási hiba: {e}")
            return False
    
    def verify_remote_files(self):
        """Távoli fájlok ellenőrzése"""
        self.logger.info("5. Fájlok ellenőrzése a szerveren...")
        
        remote_cmd = f"""
        echo 'Fájlok a szerveren:'
        ls -lh '{self.config.remote_dir}'/*.pkg.tar.* 2>/dev/null | head -10
        echo ''
        echo 'Összesen:'
        ls -1 '{self.config.remote_dir}'/*.pkg.tar.* 2>/dev/null | wc -l
        echo 'Méret:'
        du -sh '{self.config.remote_dir}' 2>/dev/null || echo '0'
        """
        
        returncode, stdout, stderr = self.ssh_command(remote_cmd, check=False)
        
        if returncode == 0:
            print(stdout)
        else:
            self.logger.warning(f"Ellenőrzés sikertelen: {stderr}")
    
    def cleanup(self):
        """Takarítás"""
        self.logger.info("6. Takarítás...")
        
        # Lokális fájlok törlése
        try:
            for f in self.test_files:
                if f.exists():
                    f.unlink()
            self.logger.success("Lokális fájlok törölve")
        except Exception as e:
            self.logger.error(f"Lokális törlés hiba: {e}")
        
        # Távoli fájlok törlése
        try:
            remote_cmd = f"""
            rm -f '{self.config.remote_dir}'/{TEST_PREFIX}-*.pkg.tar.* 2>/dev/null
            rm -f '{self.config.remote_dir}'/{TEST_PREFIX}-*.db.tar.gz 2>/dev/null
            echo 'Távoli tesztfájlok törölve'
            """
            
            returncode, stdout, stderr = self.ssh_command(remote_cmd, check=False)
            if returncode == 0:
                self.logger.success(stdout.strip())
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
        print("=" * 40)
        self.logger.info("=== TESZT VÉGE ===")
        print()
        
        if overall_success:
            self.logger.success("🎉 RSYNC MŰKÖDIK!")
            print()
            print("Az eredeti CI script RSYNC-re átírható.")
            print()
            print("Javasolt RSYNC opciók a CI-hez:")
            print("  rsync -avz --progress --stats \\")
            print("    -e 'ssh -o StrictHostKeyChecking=no' \\")
            print("    built_packages/* \\")
            print("    user@host:/remote/dir/")
        else:
            self.logger.error("RSYNC SIKERTELEN")
            print()
            print("Hibaelhárítás:")
            print("1. Ellenőrizd az SSH kulcsot")
            print("2. Ellenőrizd a távoli könyvtár jogosultságait")
            print("3. Ellenőrizd a tűzfal beállításokat")
        
        print()
        print(f"🕒 Teszt időpont: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 40)

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
        sys.exit(1)

if __name__ == "__main__":
    main()