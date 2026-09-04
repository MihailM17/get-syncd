# Get Syncd on Linux — short version

You don't need to know git. If you can export a timeline in Resolve and type a line in a terminal, you're good.

### The idea

Instead of `Film_v1.drp`, `Film_v2_FINAL.drp`, you do:

`Save button in Get Syncd` (auto-exports the timeline) → version saved.

Now you have a history. The app shows it, tells you in plain English what changed, and restores any old cut. Media never leaves your drive.

Works with Resolve Free (including the Linux release). No Studio needed.

### Easiest path: download the AppImage

No Python, no terminal needed:

1. Go to [**Releases**](https://github.com/MihailM17/get-syncd/releases) and download the `.AppImage`.
2. Make it executable and run it:
   ```bash
   chmod +x Get-Syncd-*.AppImage
   ./Get-Syncd-*.AppImage
   ```
3. The app starts its own background service and opens a **first-run wizard**: it finds your open Resolve project, creates `~/GetSyncd/<Project>`, and optionally creates a private GitHub repo for backup.
4. Done — hit **Save** in the app whenever you want a checkpoint.

### Optional: one click from inside Resolve

Copy `scripts/resolve/GetSyncd_Launch.py` (from the repo) to:

```
/opt/resolve/Fusion/Scripts/Comp/
```

```bash
sudo mkdir -p /opt/resolve/Fusion/Scripts/Comp
sudo cp scripts/resolve/GetSyncd_Launch.py /opt/resolve/Fusion/Scripts/Comp/
```

Then restart Resolve. It appears under **Workspace → Scripts → Comp → GetSyncd_Launch**: starts the service if needed, sets up the project folder, opens the app.

### Manual install (CLI people)

```bash
# prerequisites (Debian/Ubuntu; Fedora: dnf install python3 git / Arch: pacman -S python git)
sudo apt-get update && sudo apt-get install -y python3 python3-venv git

git clone https://github.com/MihailM17/get-syncd.git ~/get-syncd
cd ~/get-syncd
./install-linux.sh
source .venv/bin/activate
get-syncd --help
```

You'll run `source .venv/bin/activate` once per new terminal window. If `get-syncd` says command not found, that's why.

### One folder per film

Do this once for each project (or let the wizard / Resolve script do it):

```bash
mkdir ~/GetSyncd/MyFilm
cd ~/GetSyncd/MyFilm
get-syncd init
```

`~/GetSyncd` is the default the desktop app watches. If you only use the CLI, any folder works.

### Normal loop

1. Edit in Resolve like you always do.
2. Hit **Save** in Get Syncd (it auto-exports the timeline; manual fallback is `File → Export Timeline → OpenTimelineIO` → overwrite `timeline.otio`).
3. Save with a note like "trimmed intro after notes" (or leave it empty and it auto-describes).
4. Look back anytime: history list, plain-English diff, restore any version (auto-imports into Resolve when possible).

Optional backup:

```bash
# create an empty repo on GitHub (no README), then:
git remote add origin https://github.com/YOU/MyFilm.git
get-syncd push
```

Or install [`gh`](https://cli.github.com), run `gh auth login`, and let the first-run wizard create + push the repo for you.

Offline saves always work. Push is just when you have internet.

### If it complains

- `command not found: get-syncd` → run `source .venv/bin/activate` in that window
- `Not a git repo — run get-syncd init` → `cd ~/GetSyncd/MyFilm` first
- `No timeline.otio yet` → hit Save in the app (auto-export) or export manually
- `No changes to save` → the file is identical to last save
- Import looks empty → relink media in Resolve's Media Pool (media paths are absolute)
- AppImage won't start → `chmod +x` it first; on some distros install `libwebkit2gtk-4.1` / `libappindicator3`
- Scripts menu missing the launcher → check the copy path above and restart Resolve
