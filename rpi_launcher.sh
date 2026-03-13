#!/bin/bash
# --- Raspberry Pi AI Launcher ---
echo "Starting AI Pipeline (rpi_hover_ai.py)..."
echo "Make sure the Pixhawk is connected via USB!"
echo "------------------------------------------------"

cd ~/nanodet/nanodet_frisbee_rpi4/build
python3 ../rpi_hover_ai.py

echo "------------------------------------------------"
echo "Process Exited or Crashed."
read -p "Press [Enter] to close this window..."
