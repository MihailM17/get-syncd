# Get Syncd — scripts for DaVinci Resolve's Scripts menu

`GetSyncd_Launch.py` appears under **Workspace → Scripts → Comp → GetSyncd_Launch** and, in one click: starts the sidecar if needed, creates `~/GetSyncd/<CurrentProject>` on first run, and opens the desktop app. No Console needed.

### Install (copy one file, restart Resolve)

- **macOS:** `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/`
- **Windows:** `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Comp\`
- **Linux:** `/opt/resolve/Fusion/Scripts/Comp/`

```bash
# macOS example:
cp scripts/resolve/GetSyncd_Launch.py "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/"
```

The repo installers print the exact copy command (with `sudo` where needed) but don't run it — copy the file yourself, then restart Resolve.

`resolve_export.py` (one folder up) is the older Console-paste helper; the launcher supersedes it for normal use.
