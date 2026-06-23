#!/bin/bash
# One-time setup for Cake A Wish on Mac/Linux.
# Run this once; after that, use run.sh to start the app.
# Use --force to redo all steps even if already complete.
set -e

FORCE=0
if [[ "$1" == "--force" ]]; then
  FORCE=1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Cake A Wish Setup ==="

# 1. Check Python 3.11+
if ! command -v python3 &>/dev/null; then
  echo "Error: Python 3 not found."
  echo "Install it from https://www.python.org/downloads/ then run this script again."
  exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
  echo "Error: Python 3.11+ required (found $PY_VERSION)."
  echo "Install it from https://www.python.org/downloads/ then run this script again."
  exit 1
fi
echo "✓ Python $PY_VERSION"

# 2. Create virtual environment
if [ ! -d ".venv" ] || [ "$FORCE" -eq 1 ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "✓ Virtual environment ready"

# 3. Install dependencies (skip if already installed)
if [ "$FORCE" -eq 1 ] || ! python3 -c "import uvicorn, fastapi, PIL, brother_ql, serial" &>/dev/null; then
  echo "Installing dependencies (this may take a minute)..."
  pip install -r requirements.txt -q
  echo "✓ Dependencies installed"
else
  echo "✓ Dependencies already installed"
fi

# 4. Download face_landmarker.task if missing
TASK_FILE="blow_detection/face_landmarker.task"
TASK_URL="https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
if [ ! -f "$TASK_FILE" ] || [ "$FORCE" -eq 1 ]; then
  echo "Downloading face_landmarker.task (~3.6 MB)..."
  curl -L -o "$TASK_FILE" "$TASK_URL" && echo "✓ face_landmarker.task downloaded" || { rm -f "$TASK_FILE"; echo "Warning: download failed — camera blow detection will be unavailable"; }
else
  echo "✓ face_landmarker.task already present"
fi

# 5. Create desktop shortcut (macOS, skip if already exists)
if [[ "$OSTYPE" == "darwin"* ]]; then
  SHORTCUT="$HOME/Desktop/Cake A Wish.command"
  if [ ! -f "$SHORTCUT" ] || [ "$FORCE" -eq 1 ]; then
    cat > "$SHORTCUT" <<EOF
#!/bin/bash
cd "$SCRIPT_DIR"
source .venv/bin/activate
python launcher.py
EOF
    chmod +x "$SHORTCUT"
    echo "✓ Desktop shortcut created: ~/Desktop/Cake A Wish.command"
  else
    echo "✓ Desktop shortcut already exists"
  fi
fi

echo ""
echo "=== Setup complete ==="
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "Double-click 'Cake A Wish.command' on your Desktop to start."
  echo "Or run: ./run.sh"
else
  echo "Run: ./run.sh"
fi
