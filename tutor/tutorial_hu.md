# 🚀 TERMINAL ALAPOK ÉS HATÉKONYSÁGNÖVELŐ ÚTMUTATÓ

Üdvözlünk! Ez az útmutató azoknak szól, akik most látják először a terminált. A terminál egy szöveges parancsablak. Itt nem kattintgatunk; parancsokat gépelünk, és nyomunk egy **Entert**.

A rendszered úgy van beállítva, hogy a lehető legkényelmesebb legyen. Ne félj kísérletezni!

---

## ⌨️ 0. A LEGFONTOSABB BILLENTYŰK

Ezeket jegyezd meg először, ezek a túlélő eszközeid:

* **Enter** = A beírt parancs futtatása
* **Tab** = Automatikus kiegészítés (Elkezdesz írni egy nevet? Nyomj Tabot, és befejezi!)
* **↑ / ↓** = Lépegetés a korábban beírt parancsaid között
* **Ctrl + C** = 🛑 ÁLLJ! (Azonnal megszakítja azt, ami épp fut)
* **Ctrl + L** = 🧹 Képernyő letisztítása
* **q** = Kilépés (a legtöbb szöveges nézegetőből így tudsz kilépni)
* **exit** = A terminál bezárása

---

## 🧭 1. NAVIGÁCIÓ (HOL VAGYOK?)

Tudnod kell, hol vagy a rendszerben, és hogyan léphetsz be mappákba.

* `pwd` = Megmutatja a pontos útvonalat, ahol épp állsz
* `ls` = Kilistázza a mappában lévő fájlokat
* `cd mappa_neve` = Belépés az adott mappába

**Visszalépés (A Pont-Rövidítések):**
Alapesetben egy szinttel feljebb a `cd ..` paranccsal jutsz. Ezt sokkal gyorsabbá tettük! Csak gépelj pontokat:

| Parancs | Mit csinál? | Példa |
| :--- | :--- | :--- |
| `..` | **1** szinttel feljebb lép | `cd ..` |
| `...` | **2** szinttel feljebb lép | `cd ...` |
| `....` | **3** szinttel feljebb lép | `cd ....` |
| `.....` | **4** szinttel feljebb lép | `cd .....` |

> 💡 **Tipp:** Ha teljesen eltévedtél, csak írd be: `cd ~`, és azonnal visszakerülsz a saját Home mappádba!

---

## 📄 2. FÁJLOK KEZELÉSE ÉS SZERKESZTÉSE

* `mkdir nev` = Új mappa létrehozása
* `touch fajl.txt` = Új, üres fájl létrehozása
* `rm fajl.txt` = Fájl törlése (⚠️ **Vigyázz! Nincs Lomtár!**)
* `cat fajl.txt` = A fájl teljes tartalmának kiírása a képernyőre
* `less fajl.txt` = Fájl megnyitása görgethető nézetben (Kilépés a `q` betűvel)

**Szövegszerkesztés (Nano):**
A `nano fajl.txt` megnyitja a rendszer kezdőbarát szövegszerkesztőjét.
* Csak kezdj el gépelni, mintha a Jegyzettömbben lennél.
* Mentés és kilépés: Nyomj **Ctrl+X**-et, majd **Y**-t (Igen), végül **Entert**.

---

## 🔧 3. MODERN ESZKÖZÖK (ÁLNEVEK)

A régi, fapados parancsokat gyönyörű, modern alternatívákra cseréltük.

* 📊 **Rendszerfigyelő (`btop`)**
  * *Ehelyett:* `top` vagy `htop`
  * *Csak írd be:* `top` 
  * *Mit csinál:* Megnyit egy gyönyörű, interaktív panelt, ahol látod a CPU, RAM és hálózat terhelését. Kilépés: `q`.
* 📖 **Gyors Segítség (`tldr`)**
  * *Ehelyett:* 50 oldalas `man` kézikönyvek olvasása.
  * *Csak írd be:* `help <parancs>` (pl. `help tar`)
  * *Mit csinál:* Rövid, azonnal használható gyakorlati példákat mutat a parancshoz.
* 🎨 **JSON Formázó (`jq`)**
  * *Csak írd be:* `cat adatok.json | json`
  * *Mit csinál:* Az olvashatatlan, egybefolyó JSON kimenetet gyönyörűen színezve és tagolva jeleníti meg.
* 🔎 **Keresés PDF-ekben és Dokksikban (`rga`)**
  * *Csak írd be:* `rpdf "kulcsszó" ~/Dokumentumok/`
  * *Mit csinál:* Szöveget keres a PDF-ek, Word dokumentumok és archívumok *belsejében*, nem csak a sima szövegfájlokban!

---

## ⚡ 4. A NAGYÁGYÚK (KÉNYELMI FUNKCIÓK)

### 🔍 FZF (Villámgyors Fájlkereső)
A mappák kézi böngészése lassú. 
* **Nyomj `Ctrl + T`**-t bárhol a terminálban!
* Kezdd el gépelni a keresett fájl nevét. Azonnal, betűről betűre szűr!
* A jobb oldalon azonnal látod a kiválasztott fájl élő előnézetét.
* Nyomj **Entert**, és a fájl elérési útja egyből bekerül a parancssorodba.
* *(Bónusz: Nyomj **Ctrl + R**-t a régi, korábban kiadott parancsaid közötti villámgyors kereséshez!)*

### 📁 Midnight Commander (`mc`)
Szereted a klasszikus, kétpaneles Total Commander stílusú fájlkezelőket?
* **Írd be:** `mc`
* A nyilakkal mozoghatsz, a **Tabbal** válthatsz a panelek között, és **F10**-zel léphetsz ki.
* *Varázslat:* Amikor kilépsz, a terminálod pontosan abban a mappában fog maradni, ahol az MC-ben tartottál!

---

## 🆘 5. "COMMAND NOT FOUND" (NINCS ILYEN PARANCS)?

Ha beírsz egy parancsot, ami nincs telepítve (pl. `cmatrix`), a terminál nem csak egy buta hibaüzenetet dob. Automatikusan átkutatja az adatbázist, és pontosan megmondja, mit kell letöltened!

```text
$ cmatrix
cmatrix may be found in the following packages:
  extra/cmatrix 2.0-3

```

Csak add ki a `sudo pacman -S cmatrix` parancsot, és már kész is vagy. Nincs több találgatás!

```
