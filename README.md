# Get Syncd

Version control for DaVinci Resolve timelines. No more `MyFilm_v3_FINAL_FINAL.drp`.

You export your timeline as OTIO, hit save, and you can see what actually changed between any two versions — "trimmed 2 clips, added 1, runtime +1.2s" — then jump back to any old cut without digging through old project files.

Media stays on your drive. Only the timeline structure (clip order, trims, gaps) goes into git, so it’s tiny and works fine on the free GitHub plan. Works with Resolve Free — you don’t need Studio.

There’s a CLI if you like the terminal, and a desktop app if you don’t.

### How it works

`Resolve` → `File → Export Timeline → OpenTimelineIO` → `timeline.otio` → `get-syncd save` → git commit → (optional) push to GitHub.

Restoring just writes an `.otio` you re-import in Resolve. That part is manual — the Resolve API can’t reliably lay out clips for you, so `Import Timeline` is still the safest way.

### Quick start

```bash
pip install -e .  # or uv pip install -e .

# in your film folder (next to where you export timeline.otio)
get-syncd init
get-syncd save -m "rough cut v1 - 5 clips"
get-syncd status        # any unsaved changes?
get-syncd log           # history
get-syncd diff HEAD~1 HEAD
get-syncd view          # visual diff in browser
get-syncd restore HEAD~1 --out /tmp/old.otio
# then in Resolve: File → Import Timeline → OpenTimelineIO → /tmp/old.otio
```

### Install

Python 3.10+ and `opentimelineio`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
get-syncd --help
```

### Desktop app

If you prefer clicking:

```bash
get-syncd gui          # Tk sidecar — simple, stays next to Resolve
# or the Tauri build:
cd app && npm install && npm run tauri:dev   # dev
# or just open /Applications/Get\ Syncd.app after a release build
```

The app watches `~/GetSyncd` by default. Export from Resolve to `timeline.otio` in there, type a note, hit Save. History shows up on the left, preview + diff on the right. Branches, restore, delete, and Scan Resolve to auto-create project folders.

### Why OTIO + git?

- `.drp` files are binary blobs — git can’t diff them in a useful way.
- OTIO is JSON describing your timeline. Git diffs that fine, and `get-syncd` turns it into plain English.
- You don’t need to learn git. `save` / `log` / `diff` / `restore` is the whole surface.

### Notes

- Tested on macOS Apple Silicon, Resolve 18.5+ Free. Linux works for the CLI/diff engine without Resolve.
- Media paths are absolute — if you move drives, relink in Resolve’s Media Pool like you normally would.
- `get-syncd push` is just `git push` to whatever GitHub repo you linked with `get-syncd init --remote` or `git remote add origin ...`.

MIT — do what you want with it. Issues and small PRs welcome.
