#!/bin/bash
# voice-pad startup script

# Find the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "Starting Voice-Pad..."
# Ensure permissions for input devices (often required on Pi)
sudo chmod 666 /dev/input/event*

# Use system python or venv if you create one
python3 "$DIR/src/controller_handler.py"
