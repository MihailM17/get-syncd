# Get Syncd on Mac — short version

You don’t need to know git. If you can export a timeline in Resolve and type a line in Terminal, you’re good. (On Linux run `./install-linux.sh`, on Windows `.\install-windows.ps1` — the loop below is the same everywhere.)

### The idea

Instead of `Film_v1.drp`, `Film_v2_FINAL.drp`, you do:

`File → Export Timeline → OpenTimelineIO → timeline.otio` → `get-syncd save`

Now you have a history. `get-syncd log` shows it, `diff` tells you in plain English what changed, `restore` gives you an `.otio` to re-import. Media never leaves your drive.

Works with Resolve Free on Apple Silicon. No Studio needed.

### Check what you have

Open Terminal (`Applications → Utilities → Terminal`):

```bash
python3 --version
git --version
```

If both print numbers, skip the Homebrew step.

### Install (once)

```bash
# Homebrew — skip if brew --version already works
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python git

# get the code (pick one)
git clone https://github.com/MihailM17/get-syncd.git ~/get-syncd
# or: unzip the ZIP you AirDropped and move it to ~/get-syncd

cd ~/get-syncd
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
get-syncd --help
```

You’ll use `source .venv/bin/activate` once per new Terminal window, or just keep the same window open. If `get-syncd` says command not found, that’s why.

To make it global:

```bash
mkdir -p ~/.local/bin
ln -sf ~/get-syncd/.venv/bin/get-syncd ~/.local/bin/get-syncd
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

### One folder per film

Do this once for each project:

```bash
mkdir ~/GetSyncd/MyFilm  # or ~/Movies/MyFilm, whatever you like
cd ~/GetSyncd/MyFilm
get-syncd init
```

`~/GetSyncd` is the default the desktop app watches. If you use the app, keep it there. If you only use the CLI, any folder works.

### Normal loop

1. Edit in Resolve like you always do.
2. Export: `File → Export Timeline → OpenTimelineIO` → overwrite `timeline.otio` in your project folder.
3. Save: `get-syncd save -m "trimmed intro after notes"` (or just `get-syncd save` and it auto-describes).
4. Check: `get-syncd status` — tells you if you exported but forgot to save.
5. Look back: `get-syncd log`, `get-syncd diff HEAD~1 HEAD`, `get-syncd view`.
6. Go back: `get-syncd restore HEAD~2 --out /tmp/old.otio` → in Resolve `File → Import Timeline → OpenTimelineIO → /tmp/old.otio`. Or `get-syncd restore 2 --apply` to overwrite `timeline.otio` directly.

Optional backup:

```bash
# create an empty repo on GitHub (no README), then:
git remote add origin https://github.com/YOU/MyFilm.git
get-syncd push
```

Offline saves always work. Push is just when you have internet.

### Without Resolve

You can test the diff engine with no video:

```bash
cd ~/get-syncd
source .venv/bin/activate
pytest -q  # should say 27 passed
```

### If it complains

- `command not found: get-syncd` → run `source .venv/bin/activate` in that window
- `Not a git repo — run get-syncd init` → `cd ~/GetSyncd/MyFilm` first
- `No timeline.otio yet` → you haven’t exported yet
- `No changes to save` → the file is identical to last save
- Import looks empty → relink media in Resolve’s Media Pool (media paths are absolute)

That’s it. `export → save` is the habit. Everything else is just looking back.
