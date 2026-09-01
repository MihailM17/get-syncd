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
# from app/src-tauri
cargo tauri build --bundles app  # -> target/release/bundle/macos/Get Syncd.app
ditto target/release/bundle/macos/Get\ Syncd.app /Applications/Get\ Syncd.app
xattr -cr /Applications/Get\ Syncd.app
```

No extra config. Media stays local, only `timeline.otio` is versioned.
