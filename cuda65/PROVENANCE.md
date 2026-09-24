# Prebuilt CUDA 6.5 Samples — Provenance

## Fájl

`cuda65-samples-6.5.19-sm11-13-20260923.tar.xz`

Ez a tarball a **CUDA 6.5.19 toolkithez tartozó sample-ök előre lefordított
binárisait** tartalmazza. Célja, hogy a `cuda65` PKGBUILD felhasználói
Manjaro / Arch Linux alatt **ne kényszerüljenek a sample-ök újrafordítására**
— ami modern GCC-vel (>= 6) nem is lehetséges a CUDA 6.5 `host_config.h`
és a 2015-ös `<cuda_runtime.h>` miatt.

## Build környezet

| Elem | Érték |
|---|---|
| Build disztribúció | Debian 8.11.0 (Jessie) |
| Build dátum | 2026-09-23 |
| Host GCC | 4.8.5 (`g++-4.8`) |
| Host glibc | 2.19 |
| CUDA toolkit | 6.5.19 (V6.5.16) |
| CUDA install prefix | `$HOME/cuda65-build/pkg` |

A Debian 8 környezet azért szükséges, mert a CUDA 6.5 hivatalosan csak
GCC 4.4–4.9-et támogat (`host_config.h` blacklisteli a >= 5-öt), és a
2015-ös `cudart` a modern glibc-vel (>= 2.35) nem linkelhető újra.

## Build parancsok

```bash
sh cuda_6.5.19_linux_64.run --extract=$HOME/cuda65-build
cd $HOME/cuda65-build
./cuda-linux64-rel-*.run  --noexec --keep
./cuda-samples-linux-*.run --noexec --keep

cd $HOME/cuda65-build/pkg/cuda-samples/<sample>
make \
    CUDA_PATH=$HOME/cuda65-build/pkg \
    GCC=/usr/bin/g++-4.8 \
    SMS="11 12 13" \
    -j1
```

A `SMS="11 12 13"` **fat binary**-t eredményez: `sm_11`, `sm_12`, `sm_13`
cubin-ok mind a három architektúrára. Ez szükséges, mert a célhardver
(NVIDIA Quadro NVS 295, **Compute Capability 1.1**) csak `sm_11`-et futtat,
de a `deviceQuery` és más sample-ök a JIT-hez a többi architektúrát is
tartalmazzák.

## Tartalom

```
cuda65-prebuilt-staging/
├── BUILD_INFO     # rövid, géppel olvasható metaadat
├── MANIFEST       # fájlonkénti lista
├── README         # angol nyelvű leírás
└── bin/
    ├── alignedTypes
    ├── asyncAPI
    ├── bandwidthTest
    ├── ...
    ├── libcuhook.so.1     # megosztott library (a cuHook sample-hez)
    └── vectorAddDrv
```

A `bin/` könyvtár **lapos** struktúrájú: minden bináris egy helyen van,
a sample nevével megegyező fájlnévvel. A `PKGBUILD` `package()` függvénye
helyezi el őket a végső `/opt/cuda/samples/<kategória>/<sample>/`
könyvtárakba.

## Linking

- A legtöbb bináris **statikusan linkeli a `cudart`-ot** (nincs `libcudart`
  a NEEDED listában).
- A `*Drv` végű binárisok (`deviceQueryDrv`, `matrixMulDrv`, `simpleTextureDrv`,
  `vectorAddDrv`) a **driver API**-t használják, és közvetlenül linkelnek
  a `libcuda.so.1`-hez.
- A `libcuhook.so.1` megosztott library, a `cuHook` sample-hez.

## Ismert probléma és workaround

**NVIDIA 340.108 + glibc >= 2.35:**

A `libcuda.so.340.108` **executable stack-et igényel**
(`READ_IMPLIES_EXEC` personality). A modern glibc biztonsági okból
**megtagadja** az ilyen library `dlopen()`-nel való betöltését:

```
cannot enable executable stack as shared object requires: Invalid argument
```

Emiatt a `cudart` statikus inicializálója **0-t lát** a driver verziójaként,
és minden sample a `cudaErrorInsufficientDriver` (35) hibát adja — **kivéve**
a `*Drv` binárisokat, amelyek a kernel-indításkori `NEEDED` betöltést
használják.

**Workaround:** a `PKGBUILD` `package()` függvénye `patchelf --add-needed
libcuda.so.1` hívással **kényszeríti** a `libcuda.so.1`-et minden bináris
`NEEDED` listájába. Így a dynamic loader már a process indításakor betölti
(a personality be van állítva), és a `cudart` helyesen látja a driver
verzióját (6.5).

Részletek: lásd a `PKGBUILD` `package()` függvényének megjegyzéseit.

## Licenc

A tarballban található binárisok **NVIDIA CUDA Sample-ökből** származnak.
Rájuk az **NVIDIA CUDA Samples EULA** vonatkozik, amelynek teljes szövege
a repóban `EULA-cuda-samples.txt` néven található, és amely megegyezik
a csomag telepítése után a `/opt/cuda/samples/EULA.txt` fájllal.

A binárisok **nem** szabad szoftverek. Újraelosztásukra és felhasználásukra
az NVIDIA EULA feltételei érvényesek.
```

___

EULA-cuda-samples.txt

___

