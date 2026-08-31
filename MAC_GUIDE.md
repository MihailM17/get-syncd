# Get Syncd — Plain-English Guide (for MacBook Pro M2)

> You don't need to be a coder. If you can copy-paste into Terminal, you can use this.

### What is this?

Think of it like **Save Game for your edit**.

- Today you do `Project_v1.drp`, `Project_v2_FINAL.drp` and hope you remember what changed.
- With Get Syncd you press **Save Version**, write "trimmed intro after director notes", and later you can see **exactly what changed** between any two saves in plain English: "1 clip trimmed, 1 clip added, runtime +1.5s".
- You can also **go back** to any old version with one click — it makes a file you re-import into Resolve.
- Your video files stay where they are (on your drive). Only the *timeline structure* (clip order, trims) is saved. That's tiny and works with free GitHub.

You **don't need Resolve Studio** ($295). Resolve **Free** works. You **don't need to understand git** — the app hides it.

---

## Can I test it without DaVinci Resolve?

Yes. On this Linux PC we already tested it with fake timelines (no video needed). On your Mac you can do the same:

```bash
pytest   # runs 9 automatic checks — should say "9 passed"
```

Or run the demo script that simulates an editor:
- Save version 1 (5 clips)
- Trim a clip and save version 2
- Add b-roll and save version 3
- Show the list and diffs

You **can** also test for real on your MacBook Pro M2 — that's actually the best place, because Resolve runs great on Apple Silicon.

---

## What you need on your Mac

1. **macOS** (any recent version is fine, Apple Silicon M2 is perfect)
2. **DaVinci Resolve 18.5 or newer** (Free is fine) — only for real edits. Not needed for fake tests.
3. **Python 3.10 or newer** and **git** — we install these in one step below.

Check if you already have them: Open **Terminal** (Applications → Utilities → Terminal) and paste:

```bash
python3 --version
git --version
```

If both print a version, you're done. If not, install them next.

---

## Step 1: Get the Get Syncd code onto your Mac

**Pick one:**

**A) Easiest — download ZIP**
- On this PC, zip the folder `get-syncd` and send it to your Mac via AirDrop / USB / Google Drive.
- On Mac, double-click to unzip. You'll get a folder `get-syncd`.

**B) Via GitHub (if you have a GitHub account)**
- On Mac Terminal: `git clone https://github.com/YOURNAME/get-syncd.git`

**C) Direct copy**
- Ask me to push it to a GitHub repo and you clone it.

You should end up with a folder like `/Users/you/Downloads/get-syncd` or `/Users/you/get-syncd`.

---

## Step 2: One-time install (copy-paste)

Open **Terminal** on your Mac, then run each line one at a time (press Enter after each):

```bash
# 1. Install Homebrew if you don't have it (it installs Python/git for you)
# Skip this if `brew --version` already works
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. Install Python and git
brew install python git

# 3. Go into the Get Syncd folder (CHANGE the path to where you put it)
cd ~/Downloads/get-syncd
# or: cd ~/get-syncd

# 4. Create a private environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 5. Check it works
get-syncd --help
```

You should see a list of commands (`init, save, status...`). If you do, you're installed.

> From now on, every time you open a new Terminal window, run `source .venv/bin/activate` once in that folder before using `get-syncd`. Or just keep the same window open.

---

## Step 3: Create a project (where your edits will be versioned)

Do this **once per film**:

```bash
# Make a folder for your film next to the get-syncd folder
mkdir ~/Movies/MyFilm
cd ~/Movies/MyFilm

# Turn it into a Get Syncd project
~/Downloads/get-syncd/.venv/bin/get-syncd init
# or if you're already activated: get-syncd init
```

That's it. Inside `~/Movies/MyFilm` you'll now have a hidden history.

---

## Step 4: Day-to-day use (with real DaVinci Resolve)

This is your normal loop:

### 1. Edit in Resolve as usual

### 2. Export timeline to a file
In Resolve:
`File → Export Timeline → OpenTimelineIO...`
Save as: `~/Movies/MyFilm/timeline.otio`
(Just overwrite the same file every time — Get Syncd keeps the history)

*Tip: There's also a script in `get-syncd/scripts/resolve_export.py` you can run from Workspace → Scripts → Console, but the manual File menu always works.*

### 3. Save a version
Back in Terminal:

```bash
cd ~/Movies/MyFilm
get-syncd save -m "Rough cut v1 - 5 clips"
# Or just: get-syncd save
# If you don't write a message, it auto-generates one like "1 trimmed, runtime -1s"
```

### 4. Check if you forgot to save
```bash
get-syncd status
```
- "All changes saved" → you're safe
- "You have changes since your last saved version" → you edited but didn't save yet. **This is how you avoid losing work.**

### 5. See what changed
```bash
# See list of all saves
get-syncd log

# See what changed between last two saves (plain English)
get-syncd diff HEAD~1 HEAD

# See it as a visual bar in your browser (red = removed, green = added, yellow = trimmed)
get-syncd view HEAD~1 HEAD
```

### 6. Go back to an old version
```bash
# List versions and copy the code (like dde28d93)
get-syncd log

# Restore that version to a file
get-syncd restore dde28d93 --out /tmp/old_version.otio
```
Then in Resolve:
`File → Import Timeline → OpenTimelineIO...` and pick `/tmp/old_version.otio`
Resolve makes a **new** timeline — your current one isn't overwritten until you import.

### 7. (Optional) Backup to GitHub
So it survives if your laptop dies:

```bash
# One time: create an empty repo on github.com (don't add README)
# Then link it:
git remote add origin https://github.com/YOURNAME/MyFilm.git

# Whenever you want to backup:
get-syncd push
```

That's it. Offline saves always work; pushing is separate for when you have internet.

---

## Quick test without Resolve (on your Mac, right now)

```bash
cd ~/Downloads/get-syncd
source .venv/bin/activate
pytest -q
# Should say: 9 passed

# Or run the fake-editor demo:
bash /tmp/run_demo.sh
```

This proves the diff engine works even without video files.

---

## Troubleshooting

**"command not found: get-syncd"**
→ You forgot `source .venv/bin/activate` in that Terminal window. Run it again.

**"Not a git repo — run get-syncd init"**
→ You ran the command in the wrong folder. `cd ~/Movies/MyFilm` first.

**"No timeline.otio yet — export from Resolve first"**
→ You haven't done File → Export Timeline yet.

**"No changes to save"**
→ You already saved that exact version. Make an edit first, or the file is identical.

**Resolve import looks empty?**
→ Your media drive path changed. Relink media in Resolve's Media Pool (same as normal Resolve — this tool doesn't move your videos).

**Need help?**
→ Run any command with `--help`: e.g. `get-syncd diff --help`

---

## In one sentence

`File → Export Timeline → get-syncd save` = save point. `get-syncd log / diff / view` = see history. `get-syncd restore` → re-import in Resolve = time travel.

All free, works on your M2, no Studio needed.
