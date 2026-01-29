#!/bin/bash

# Activate the virtual environment
source venv/bin/activate

# Export display for GUI to show on the RPi screen
export DISPLAY=:0
export XAUTHORITY=/home/leader/.Xauthority

# Run the Drone Control Software
python3 main.py
