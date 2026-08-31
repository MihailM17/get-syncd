# Get Syncd

Free, open-source version control for DaVinci Resolve.

Save checkpoints of a timeline, see a human-readable diff of what changed between any two versions, and restore safely — using git + GitHub as the backend. Media stays local; only the OTIO timeline structure is versioned.

## Quick start

```bash
uv pip install -e .   # or pip install -e .
get-syncd init        # init git repo + link remote (optional)
get-syncd save -m "Rough cut v3 — trimmed intro"
get-syncd status      # shows if you have changes since last save
get-syncd log         # list versions with changelogs
get-syncd diff HEAD~1 HEAD --text
get-syncd view HEAD~1 HEAD   # opens visual diff in browser
get-syncd restore HEAD~2 --out /tmp/restore.otio
# then in Resolve: File → Import Timeline → OpenTimelineIO → /tmp/restore.otio
```

## How it works

Resolve → Export Timeline (OTIO) → local git commit → push to GitHub → diff viewer.

Import is manual (Resolve scripting API cannot lay clips programmatically) — `restore` produces a `.otio` file you import via Resolve's dialog.

## Install

Requires Python 3.10+ and `opentimelineio`.

```bash
uv pip install -e .
# or
pip install -e .
```

## Resolve export

- In Resolve: File → Export Timeline → OpenTimelineIO → save as `timeline.otio` in your repo.
- Or via script: Workspace → Scripts → `scripts/resolve_export.py`.

## License

MIT
