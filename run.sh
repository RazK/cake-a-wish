#!/bin/bash
# Start Cake A Wish. Run this after setup.sh has been run once.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  echo "Error: .venv not found. Run setup.sh first."
  exit 1
fi

source .venv/bin/activate
python launcher.py
