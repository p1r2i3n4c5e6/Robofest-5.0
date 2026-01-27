#!/bin/bash

echo "🚀 Installing Drone Command Center Dependencies..."

# Check if pip exists
if ! command -v pip3 &> /dev/null
then
    echo "❌ pip3 could not be found. Please install python3-pip."
    exit
fi

# Install Dependencies
echo "📦 Installing from requirements.txt..."
pip3 install -r requirements.txt

echo "✅ Installation Complete!"
echo "👉 Run the app with: python3 main.py"
