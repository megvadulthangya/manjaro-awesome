#!/bin/bash

_appdir="/opt/ComfyUI"
_appuser="diffusion"
_session_name="comfyui_install"

rm -rf "${_appdir}/venv"
sudo -u "${_appuser}" python3.13 -m venv "${_appdir}/venv"

sudo -u "${_appuser}" byobu kill-session -t "${_session_name}" 2>/dev/null
sudo -u "${_appuser}" byobu new-session -d -s "${_session_name}"

sudo -u "${_appuser}" byobu send-keys -t "${_session_name}" "cd ${_appdir} && \
./venv/bin/python -m pip install --upgrade pip setuptools wheel && \
./venv/bin/python -m pip install -r requirements.txt && \
if [ -f manager_requirements.txt ]; then ./venv/bin/python -m pip install -r manager_requirements.txt; fi && \
./venv/bin/python -m pip uninstall -y requests urllib3 chardet charset-normalizer && \
./venv/bin/python -m pip install --no-cache-dir --no-deps requests==2.32.3 urllib3==2.2.3 charset-normalizer==3.3.2 chardet==5.2.0 && \
echo -e '\n\n--- TELEPITES SIKERESEN BEFEJEZODOTT ---'" C-m
