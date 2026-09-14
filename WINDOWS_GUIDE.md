# Get Syncd on Windows — short version

You don't need to know git. If you can export a timeline in Resolve and type a line in PowerShell, you're good.

### The idea

Instead of `Film_v1.drp`, `Film_v2_FINAL.drp`, you do:

`Save button in Get Syncd` (auto-exports the timeline) → version saved.

Now you have a history. The app shows it, tells you in plain English what changed, and restores any old cut. Media never leaves your drive.

Works with Resolve Free. No Studio needed.

### Easiest path: download the installer

No Python, no Terminal needed:

1. Go to [**Releases**](https://github.com/MihailM17/get-syncd/releases) and download the `.msi` (or portable `.exe`).
2. Run it. The app starts its own background service and opens a **first-run wizard**.
3. The wizard finds your open Resolve project, creates `%USERPROFILE%\GetSyncd\<Project>`, and optionally creates a private GitHub repo for backup.
4. Done — hit **Save** in the app whenever you want a checkpoint.

### Optional: one click from inside Resolve

Copy `scripts\resolve\GetSyncd_Launch.py` (from the repo) to:

```
%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Comp\
```

(needs an admin PowerShell, then restart Resolve). It appears under **Workspace → Scripts → Comp → GetSyncd_Launch**: starts the service if needed, sets up the project folder, opens the app.

### Manual install (CLI people)

PowerShell (normal user):

```powershell
# prerequisites (once):
winget install Python.Python.3.12 Git.Git

# if scripts are blocked:
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

git clone https://github.com/MihailM17/get-syncd.git $HOME\get-syncd
cd $HOME\get-syncd
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
get-syncd --help
```

You'll run `.\.venv\Scripts\Activate.ps1` once per new PowerShell window. If `get-syncd` says command not found, that's why.

### One folder per film

Do this once for each project (or let the wizard / Resolve script do it):

```powershell
mkdir $HOME\GetSyncd\MyFilm
cd $HOME\GetSyncd\MyFilm
get-syncd init
```

`%USERPROFILE%\GetSyncd` is the default the desktop app watches. If you only use the CLI, any folder works.

### Normal loop

1. Edit in Resolve like you always do.
2. Hit **Save** in Get Syncd (it auto-exports the timeline; manual fallback is `File → Export Timeline → OpenTimelineIO` → overwrite `timelines/<TimelineName>.otio`).
3. Save with a note like "trimmed intro after notes" (or leave it empty and it auto-describes).
4. Look back anytime: history list, plain-English diff, restore any version (auto-imports into Resolve when possible).

Optional backup:

```powershell
# create an empty repo on GitHub (no README), then:
git remote add origin https://github.com/YOU/MyFilm.git
get-syncd push
```

Or install [`gh`](https://cli.github.com) (`winget install GitHub.cli`), run `gh auth login`, and let the first-run wizard create + push the repo for you.

Offline saves always work. Push is just when you have internet.

### If it complains

- `get-syncd` not recognized → run `.\.venv\Scripts\Activate.ps1` in that window
- `Not a git repo — run get-syncd init` → `cd` into your project folder first
- `No timeline.otio yet` → hit Save in the app (auto-export) or export manually
- `No changes to save` → the file is identical to last save
- Import looks empty → relink media in Resolve's Media Pool (media paths are absolute)
- Scripts menu missing the launcher → check the copy path above and restart Resolve
