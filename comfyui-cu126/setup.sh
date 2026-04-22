#!/bin/bash

_appdir="/opt/ComfyUI"
_appuser="diffusion"

echo "Removing old virtual environment..."
rm -rf "${_appdir}/venv"

echo "Creating new virtual environment..."
sudo -u "${_appuser}" python3.13 -m venv "${_appdir}/venv"

sudo -u "${_appuser}" bash -c '
set -e
cd "'"${_appdir}"'"

echo "Upgrading pip, setuptools, and wheel..."
./venv/bin/python -m pip install --upgrade pip setuptools wheel

echo "Installing ComfyUI requirements (cu126)..."
./venv/bin/python -m pip install --extra-index-url https://download.pytorch.org/whl/cu126 -r requirements.txt

echo "Installing ComfyUI-Manager..."
cd custom_nodes
if [ ! -d "comfyui-manager" ]; then
    git clone https://github.com/ltdrdata/ComfyUI-Manager comfyui-manager
else
    echo "ComfyUI-Manager already exists, skipping clone."
fi
cd ..

if [ -f manager_requirements.txt ]; then
    echo "Installing manager_requirements.txt..."
    ./venv/bin/python -m pip install -r manager_requirements.txt
fi

echo "Adjusting specific package versions..."
./venv/bin/python -m pip uninstall -y requests urllib3 chardet charset-normalizer
./venv/bin/python -m pip install --no-cache-dir --no-deps requests==2.32.3 urllib3==2.2.3 charset-normalizer==3.3.2 chardet==5.2.0

echo -e "\n\n--- INSTALLATION COMPLETED SUCCESSFULLY ---"
'
