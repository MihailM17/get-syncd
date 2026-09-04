#!/bin/bash
set -e
# Build Python sidecar binary for Tauri for the CURRENT host OS/arch.
# Produces app/src-tauri/binaries/get-syncd-api-<rust-target-triple>
# Usage: ./scripts/build-sidecar.sh
# NOTE: PyInstaller cannot cross-compile — run this on each OS you ship
# (or use .github/workflows/build.yml, which builds per-OS in CI).

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv"
BIN_NAME="get-syncd-api"

echo "Building Python sidecar for Tauri..."

if [ ! -d "$VENV" ]; then
  echo "No venv at $VENV — run ./install-mac.sh (macOS), ./install-linux.sh (Linux), or install-windows.ps1 (Windows) first"
  exit 1
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q pyinstaller 2>&1 | tail -n 5

# Detect Rust-style target triple for this host
OS="$(uname -s)"
ARCH="$(uname -m)"
case "$OS" in
  Darwin)
    case "$ARCH" in
      arm64) TARGET="aarch64-apple-darwin" ;;
      *)     TARGET="x86_64-apple-darwin" ;;
    esac
    ;;
  Linux)
    case "$ARCH" in
      aarch64|arm64) TARGET="aarch64-unknown-linux-gnu" ;;
      *)             TARGET="x86_64-unknown-linux-gnu" ;;
    esac
    ;;
  MINGW*|MSYS*|CYGWIN*)
    case "$ARCH" in
      aarch64|arm64) TARGET="aarch64-pc-windows-msvc" ;;
      *)             TARGET="x86_64-pc-windows-msvc" ;;
    esac
    ;;
  *)
    echo "Unknown OS: $OS ($ARCH) — defaulting to x86_64-unknown-linux-gnu"
    TARGET="x86_64-unknown-linux-gnu"
    ;;
esac

OUT_DIR="$REPO_DIR/app/src-tauri/binaries"
mkdir -p "$OUT_DIR"

echo "→ Building $BIN_NAME for $TARGET..."
WORKDIR="${TMPDIR:-/tmp}/pyinstaller_build"
# NOTE: build via scripts/sidecar_entry.py (imports get_syncd as a package);
# freezing api_server.py directly breaks its relative imports.
pyinstaller --onefile --name "$BIN_NAME-$TARGET" --distpath "$OUT_DIR" --workpath "$WORKDIR" --specpath "$WORKDIR" --clean \
  --paths "$REPO_DIR/src" \
  --hidden-import=opentimelineio --hidden-import=PIL --hidden-import=rich \
  "$REPO_DIR/scripts/sidecar_entry.py" 2>&1 | tail -n 20

chmod +x "$OUT_DIR/$BIN_NAME-$TARGET" 2>/dev/null || true
echo "Sidecar built: $OUT_DIR/$BIN_NAME-$TARGET ($(du -h "$OUT_DIR/$BIN_NAME-$TARGET" | cut -f1))"

# Also copy as generic for dev (sidecar lookup falls back to plain name)
cp "$OUT_DIR/$BIN_NAME-$TARGET" "$OUT_DIR/$BIN_NAME" 2>/dev/null || true

echo "Done."
