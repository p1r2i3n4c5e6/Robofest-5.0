#!/bin/bash
# Activate venv if exists (optional, assuming system python or user environment)
# source .venv/bin/activate 

echo "Starting AI Pilot..."
echo "Ensure your drone is connected to /dev/ttyUSB0 (or edit backend.py)"
echo "Press 'q' in the video window to quit."

python3 ai_pilot.py
