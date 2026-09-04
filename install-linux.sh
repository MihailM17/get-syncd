#!/bin/bash
set -e
echo "=== Get Syncd — Linux installer ==="
echo ""
if ! command -v python3 &> /dev/null; then
  echo "Installing Python + git..."
  if command -v apt-get &> /dev/null; then
    sudo apt-get update && sudo apt-get install -y python3 python3-venv git
  elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 git
  elif command -v pacman &> /dev/null; then
    sudo pacman -S --noconfirm python git
  else
    echo "Install Python 3.10+ and git with your package manager, then re-run."
    exit 1
  fi
else
  echo "Python found: $(python3 --version)"
fi
echo "Creating virtual environment..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
echo ""
echo "Done! Test it:"
echo "  get-syncd --help"
echo "  pytest -q"
echo ""
echo "Projects live in ~/GetSyncd — same as macOS."
echo ""
echo "Optional: add Get Syncd to Resolve's Scripts menu (Workspace -> Scripts -> Comp):"
echo "  sudo mkdir -p /opt/resolve/Fusion/Scripts/Comp"
echo "  sudo cp scripts/resolve/GetSyncd_Launch.py /opt/resolve/Fusion/Scripts/Comp/"
echo "  (then restart Resolve)"
