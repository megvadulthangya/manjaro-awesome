import os
import re

# A bemeneti fájl neve
input_file = 'full_project.txt'

# Minta a fájl elválasztó sor felismerésére
# A bash szkripted így generálta: --- FILE: ./utvonal/fajl.py ---
marker_pattern = re.compile(r'^--- FILE: (.+) ---\s*$')

current_file = None

if not os.path.exists(input_file):
    print(f"Hiba: Nem található a {input_file}!")
    exit(1)

print("Fájlok szétválasztása és mappák létrehozása folyamatban...")

with open(input_file, 'r', encoding='utf-8', errors='replace') as f_in:
    for line in f_in:
        # Megnézzük, hogy a sor egy elválasztó fejléc-e
        match = marker_pattern.match(line.strip())
        
        if match:
            # Ha volt már megnyitva fájl, azt lezárjuk
            if current_file:
                current_file.close()
                current_file = None
            
            # Kinyerjük az útvonalat (pl. .github/scripts/valami.py)
            path = match.group(1).strip()
            
            # Létrehozzuk a szükséges mappákat
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            
            # Megnyitjuk az új fájlt írásra
            try:
                current_file = open(path, 'w', encoding='utf-8')
                print(f"Létrehozva: {path}")
            except Exception as e:
                print(f"Hiba a(z) {path} létrehozásakor: {e}")
        else:
            # Ha nem fejléc, akkor ez a fájl tartalma -> írjuk a nyitott fájlba
            if current_file:
                current_file.write(line)

# Az utolsó fájl lezárása
if current_file:
    current_file.close()

print("Kész! A fájlok visszaállítva.")
