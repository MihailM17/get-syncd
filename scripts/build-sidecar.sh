#!/bin/bash
set -e
# Build Python sidecar binary for Tauri (macOS Apple Silicon + Windows cross)
# Produces app/src-tauri/binaries/get-syncd-api-<target>
# Usage: ./scripts/build-sidecar.sh

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv"
BIN_NAME="get-syncd-api"

echo "Building Python sidecar for Tauri..."

if [ ! -d "$VENV" ]; then
  echo "No venv at $VENV — run ./install-mac.sh first"
  exit 1
fi

source "$VENV/bin/activate"
pip install -q pyinstaller 2>&1 | tail -n 5

OUT_DIR="$REPO_DIR/app/src-tauri/binaries"
mkdir -p "$OUT_DIR"

# macOS Apple Silicon
TARGET="aarch64-apple-darwin"
echo "→ Building $BIN_NAME for $TARGET..."
pyinstaller --onefile --name "$BIN_NAME-$TARGET" --distpath "$OUT_DIR" --workpath /tmp/pyinstaller_build --specpath /tmp --clean \
  --hidden-import=opentimelineio --hidden-import=PIL --hidden-import=rich \
  "$REPO_DIR/src/get_syncd/api_server.py" 2>&1 | tail -n 20

chmod +x "$OUT_DIR/$BIN_NAME-$TARGET" 2>/dev/null || true
echo "Sidecar built: $OUT_DIR/$BIN_NAME-$TARGET ($(du -h "$OUT_DIR/$BIN_NAME-$TARGET" | cut -f1))"

# Also copy as generic for dev (Tauri looks for <name>-<target> but fallback to <name>)
cp "$OUT_DIR/$BIN_NAME-$TARGET" "$OUT_DIR/$BIN_NAME" 2>/dev/null || true

echo "Done. Add to tauri.conf.json bundle.externalBin if not present."
