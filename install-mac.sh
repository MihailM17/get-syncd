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
echo "  pytest -q   (should say 9 passed)"
echo ""
echo "Next: mkdir ~/Movies/MyFilm && cd ~/Movies/MyFilm && get-syncd init"
