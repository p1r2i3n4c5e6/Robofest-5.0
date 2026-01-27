#!/bin/bash

echo "=========================================="
echo "    RPi 5 Drone Software Installer"
echo "=========================================="

# 1. Update System
echo "[*] Updating System Package List..."
sudo apt update

# 2. Install System Dependencies
# python3-tk: For GUI
# libopenjp2-7: For Pillow/Satellite Images
# python3-venv: For creating virtual env (Required on RPi 5/Bookworm)
echo "[*] Installing System Libraries..."
sudo apt install -y python3-tk libopenjp2-7 python3-venv libatlas-base-dev

# 3. Create Virtual Environment
# RPi 5 restricts global pip installs (PEP 668), so we MUST use a venv.
echo "[*] Creating Python Virtual Environment (venv)..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "    -> venv created."
else
    echo "    -> venv already exists."
fi

# 4. Activate and Install Pip Packages
echo "[*] Installing Python Dependencies into venv..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=========================================="
echo "    Installation Complete! ✅"
echo "    To run the software, execute:"
echo "    ./run_rpi5.sh"
echo "=========================================="
chmod +x run_rpi5.sh
