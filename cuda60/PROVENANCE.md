# Prebuilt CUDA 6.0 Samples — Provenance

## Fájl

`cuda60-samples-6.0.37-20260923.tar.xz`

Ez a tarball a **CUDA 6.0.37 toolkithez tartozó sample-ök előre lefordított
binárisait** tartalmazza. Célja, hogy a `cuda60` PKGBUILD felhasználói
Manjaro / Arch Linux alatt **ne kényszerüljenek a sample-ök újrafordítására**
— ami modern GCC-vel (>= 6) nem is lehetséges a CUDA 6.0 `host_config.h`
és a 2014-es `<cuda_runtime.h>` miatt.

## Build környezet

| Elem | Érték |
|---|---|
| Build disztribúció | Debian 8.11.0 (Jessie) |
| Build dátum | 2026-09-23 |
| Host GCC | 4.8.5 (`g++-4.8`) |
| Host glibc | 2.19 |
| CUDA toolkit | 6.0.37 (V6.0.37) |
| CUDA install prefix | `$HOME/cuda60-build/pkg` |
| Runtime | CUDA 6.0 elfogadja a 340.108 drivert (CUDART_VERSION=6000) |

## Build parancsok

A binárisok a **Makefile alapértelmezett** `SMS` értékével készültek:

```bash
sh cuda_6.0.37_linux_64.run --extract=$HOME/cuda60-build
cd $HOME/cuda60-build
./cuda-linux64-rel-*.run  --noexec --keep
./cuda-samples-linux-*.run --noexec --keep

cd $HOME/cuda60-build/pkg/cuda-samples/<sample>
make \
    CUDA_PATH=$HOME/cuda60-build/pkg \
    GCC=/usr/bin/g++-4.8 \
    -j1
```

A Makefile alapértelmezett target listája:

```
SMS = 10 20 30 32 35 50
```

Ez **fat binary**-t eredményez minden sample-hez, a fenti 6 architektúra
cubin-jával.



## Linking

- A legtöbb bináris **statikusan linkeli a `cudart`-ot**.
- A `*Drv` binárisok (`deviceQueryDrv`, `matrixMulDrv`,
  `simpleTextureDrv`, `vectorAddDrv`) a **driver API**-t használják.
- Nincs `libcuhook.so.1` (az csak a 6.5 prebuiltben van).

## Ismert probléma és workaround

**NVIDIA 340.108 + glibc >= 2.35:**

A `libcuda.so.340.108` **executable stack-et igényel**
(`READ_IMPLIES_EXEC` personality). A modern glibc biztonsági okból
**megtagadja** az ilyen library `dlopen()`-nel való betöltését:

```
cannot enable executable stack as shared object requires: Invalid argument
```

Emiatt a `cudart` statikus inicializálója **0-t lát** a driver
verziójaként, és minden sample a `cudaErrorInsufficientDriver` (35)
hibát adja.

**Workaround:** a `PKGBUILD` `package()` függvénye `patchelf --add-needed
libcuda.so.1` hívással **kényszeríti** a `libcuda.so.1`-et minden bináris
`NEEDED` listájába. Így a dynamic loader már a process indításakor betölti
(a personality be van állítva), és a `cudart` helyesen látja a driver
verzióját.

Ez a workaround **GPU CC-től független** — minden 340.108-cal használt
GPU-n (Tesla, Fermi, Kepler, Maxwell GM107/GM108) ugyanúgy szükséges.

## Licenc

A tarballban található binárisok **NVIDIA CUDA Sample-ökből** származnak.
Rájuk az **NVIDIA CUDA Toolkit EULA** vonatkozik, amelynek szövege
a repóban `EULA-cuda-samples.txt` néven található, és amely megegyezik
a csomag telepítése után a `/opt/cuda/samples/License.txt` fájllal.

A binárisok **nem** szabad szoftverek. Újraelosztásukra és felhasználásukra
az NVIDIA EULA feltételei érvényesek.
