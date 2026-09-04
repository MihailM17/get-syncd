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

The repo installers (`install-mac.sh`, `install-linux.sh`, `install-windows.ps1`) attempt this copy automatically — best effort, they skip it if the Resolve folders don't exist or need admin rights.

`resolve_export.py` (one folder up) is the older Console-paste helper; the launcher supersedes it for normal use.
