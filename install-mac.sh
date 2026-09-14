#!/bin/bash
set -e
echo "=== Get Syncd — Mac installer (M2 / Intel) ==="
echo ""
if ! command -v brew &> /dev/null; then
  echo "Installing Homebrew (needs your Mac password)..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
  eval "$(/opt/homebrew/bin/brew shellenv)"
else
  echo "Homebrew found: $(brew --version | head -n1)"
fi
echo "Installing Python + git..."
brew install python git
echo "Creating virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
echo ""
echo "Done! Test it:"
echo "  get-syncd --help"
echo "  pytest -q   (should pass with no failures)"
echo ""
echo "Next: mkdir ~/Movies/MyFilm && cd ~/Movies/MyFilm && get-syncd init"
echo ""
echo "Optional: add Get Syncd to Resolve's Scripts menu (Workspace -> Scripts -> Comp):"
echo "  sudo mkdir -p \"/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp\""
echo "  sudo cp scripts/resolve/GetSyncd_Launch.py \"/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/\""
echo "  (then restart Resolve)"
