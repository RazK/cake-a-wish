#!/bin/bash
# One-time setup for Cake A Wish on Mac/Linux.
# Run this once; after that, use run.sh to start the app.
set -e

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
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "✓ Virtual environment ready"

# 3. Install dependencies
echo "Installing dependencies (this may take a minute)..."
pip install -r requirements.txt -q
echo "✓ Dependencies installed"

# 4. Create desktop shortcut (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
  SHORTCUT="$HOME/Desktop/Cake A Wish.command"
  cat > "$SHORTCUT" <<EOF
#!/bin/bash
cd "$SCRIPT_DIR"
source .venv/bin/activate
python launcher.py
EOF
  chmod +x "$SHORTCUT"
  echo "✓ Desktop shortcut created: ~/Desktop/Cake A Wish.command"
fi

echo ""
echo "=== Setup complete ==="
echo "Double-click 'Cake A Wish.command' on your Desktop to start."
echo "Or run: ./run.sh"
