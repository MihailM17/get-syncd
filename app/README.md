# Get Syncd — Desktop

Tauri + React frontend for Get Syncd. Talks to the Python core over `http://127.0.0.1:5174`.

The heavy lifting (OTIO parse, diff, git) lives in `src/get_syncd`. This app just calls it.

### Dev

```bash
# from repo root, one-time Python sidecar
python3 -m venv .venv && source .venv/bin/activate && pip install -e .

# in another terminal, API
get-syncd serve  # -> http://127.0.0.1:5174/health

# in app/
npm install
npm run dev      # -> http://localhost:5173 (Tauri uses this as devUrl)
npm run tauri:dev  # opens desktop window
```

### Build

```bash
npm run build          # vite -> dist/
npm run tauri:build    # release bundle for your OS:
                       # macOS -> target/release/bundle/macos/Get Syncd.app
                       # Windows -> target/release/bundle/msi/*.msi + nsis/*.exe
                       # Linux -> target/release/bundle/appimage/*.AppImage
```

```bash
# macOS install example:
ditto target/release/bundle/macos/Get\ Syncd.app /Applications/Get\ Syncd.app
xattr -cr /Applications/Get\ Syncd.app
```

Notes:

- The Python sidecar is per-OS: run `../scripts/build-sidecar.sh` on each OS first (PyInstaller can't cross-compile). CI (`.github/workflows/build.yml`) does this automatically per runner.
- Custom app icon: `cargo tauri icon public/getsyncd-icon.png`, then rebuild. If the old icon sticks around in the Dock, remove the app from the Dock and run `killall Dock` (macOS icon cache).

No extra config. Media stays local, only `timeline.otio` is versioned.
