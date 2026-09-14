"""Get Syncd launcher — runs from DaVinci Resolve's Scripts menu.

Install: copy this file into Resolve's Comp scripts folder, then restart Resolve.
It appears under Workspace -> Scripts -> Comp -> GetSyncd_Launch.

  macOS:   /Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Comp/
  Windows: %PROGRAMDATA%\\Blackmagic Design\\DaVinci Resolve\\Fusion\\Scripts\\Comp\\
  Linux:   /opt/resolve/Fusion/Scripts/Comp/

What it does (stdlib only, works inside Resolve's embedded Python):
  1. Pings the Get Syncd sidecar (http://127.0.0.1:5174/health).
  2. Starts it if down (bundled binary, else `python -m get_syncd.api_server`).
  3. First-time setup: creates ~/GetSyncd/<CurrentResolveProject> as a git repo.
  4. Opens the Get Syncd desktop app (falls back to printed instructions).

Can also be run standalone:  python3 GetSyncd_Launch.py
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:5174"
APP_NAME = "Get Syncd"
# Must match api_server.API_PORT_START/COUNT: the sidecar takes the first free
# port, so locate the freshest healthy one instead of assuming 5174.
API_PORTS = range(5174, 5184)


def _get(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:
        return None


def _post(path, payload, timeout=15):
    try:
        req = urllib.request.Request(
            API + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _sidecar_candidates():
    """Bundled sidecar binary locations per OS (Tauri externalBin layout)."""
    cands = []
    if sys.platform == "darwin":
        base = Path("/Applications") / (APP_NAME + ".app") / "Contents" / "MacOS"
        cands += [base / "get-syncd-api", base / "get-syncd-api-aarch64-apple-darwin", base / "get-syncd-api-x86_64-apple-darwin"]
    elif sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        if str(local):
            cands += list((local / APP_NAME).glob("get-syncd-api-*.exe"))
        cands += list((pf / APP_NAME).glob("get-syncd-api-*.exe"))
    else:
        for d in [Path.home() / ".local" / "bin", Path("/opt") / APP_NAME, Path("/usr/local/bin")]:
            cands += sorted(d.glob("get-syncd-api-*"))
    return [p for p in cands if p.is_file()]


def _probe(port, timeout=0.8):
    """Health of one candidate port, or None. Picks freshest on ties via started."""
    d = None
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=timeout) as r:
            d = json.loads(r.read().decode() or "{}")
    except Exception:
        return None
    if not d or not d.get("ok"):
        return None
    try:
        started = float(d.get("started") or 0)
    except Exception:
        started = 0
    return (started, port)


def _find_api():
    """URL of the freshest healthy sidecar across the port range, else None."""
    best = None
    for port in API_PORTS:
        hit = _probe(port)
        if hit and (best is None or hit[0] > best[0]):
            best = hit
    if best:
        return "http://127.0.0.1:%d" % best[1]
    return None


def _ensure_sidecar():
    global API
    found = _find_api()
    if found:
        API = found
        print("[Get Syncd] sidecar already running at %s." % API)
        return True
    cmd = None
    for p in _sidecar_candidates():
        cmd = [str(p), "--port", "5174"]
        break
    if cmd is None:
        for py in ["python3", "python"]:
            if shutil.which(py):
                cmd = [py, "-m", "get_syncd.api_server", "--port", "5174"]
                break
    if cmd is None:
        print("[Get Syncd] no sidecar binary and no python found.")
        print("Install the desktop app from https://github.com/MihailM17/get-syncd/releases")
        return False
    print("[Get Syncd] starting sidecar: " + " ".join(cmd))
    try:
        if sys.platform == "win32":
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        print("[Get Syncd] could not start sidecar: %s" % e)
        print("Start it manually: python -m get_syncd.api_server --port 5174")
        return False
    for _ in range(30):
        time.sleep(1)
        found = _find_api()
        if found:
            API = found
            print("[Get Syncd] sidecar is up at %s." % API)
            return True
    print("[Get Syncd] sidecar did not answer within 30s.")
    return False


def _current_project_name():
    # 1) Inside Resolve: use the live project (most reliable)
    try:
        g = globals().get("bmd") or globals().get("resolve")
        if g is None:
            try:
                from get_syncd.resolve_state import ensure_resolve_scripting_path  # noqa

                ensure_resolve_scripting_path()
            except Exception:
                pass
            try:
                import DaVinciResolveScript as _bmd  # type: ignore

                g = _bmd.scriptapp("Resolve")
            except Exception:
                g = None
        if g is not None:
            pm = g.GetProjectManager()
            proj = pm.GetCurrentProject() if pm else None
            if proj and hasattr(proj, "GetName"):
                name = proj.GetName()
                if name:
                    return name
    except Exception:
        pass
    # 2) Ask the sidecar what Resolve has open
    try:
        cur = _get(API + "/api/resolve/current", timeout=5) or {}
        if cur.get("project"):
            return cur["project"]
    except Exception:
        pass
    return None


def _first_time_setup(project_name):
    base = Path.home() / "GetSyncd"
    if project_name:
        safe = "".join(c if (c.isalnum() or c in " -_.") else "_" for c in project_name).strip() or "MyProject"
    else:
        safe = "MyProject"
    repo = base / safe
    if (repo / ".git").exists():
        print("[Get Syncd] project folder already set up: %s" % repo)
        return repo
    print("[Get Syncd] first-time setup: creating %s" % repo)
    res = _post("/api/init", {"repo": str(repo)})
    if res.get("ok"):
        print("[Get Syncd] ready: %s" % repo)
    else:
        print("[Get Syncd] setup failed: %s" % res.get("error"))
        print("Create it manually: get-syncd init \"%s\"" % repo)
    return repo


def _open_app():
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", APP_NAME])
            return True
        if sys.platform == "win32":
            for p in _sidecar_candidates():
                app_dir = p.parent
                for exe in [app_dir / (APP_NAME + ".exe"), app_dir.parent / (APP_NAME + ".exe")]:
                    if exe.is_file():
                        os.startfile(str(exe))  # noqa: PGHloor -- Windows only branch
                        return True
            return False
        # Linux: best effort
        for name in ["get-syncd", "Get Syncd"]:
            try:
                subprocess.Popen([name])
                return True
            except Exception:
                continue
        return False
    except Exception:
        return False


def main():
    print("[Get Syncd] launch ...")
    if not _ensure_sidecar():
        return
    name = _current_project_name()
    if name:
        print("[Get Syncd] Resolve project: %s" % name)
    else:
        print("[Get Syncd] no Resolve project detected (open one and re-run for auto-setup).")
    _first_time_setup(name)
    if _open_app():
        print("[Get Syncd] opening the desktop app ...")
    else:
        print("[Get Syncd] could not open the app automatically — open \"%s\" yourself." % APP_NAME)
    print("[Get Syncd] done. Your timelines version into ~/GetSyncd; media stays where it is.")


# globals().get: Resolve's Scripts menu exec's this file (sometimes without a
# module __name__), so default to running — a menu click runs the whole flow.
if globals().get("__name__", "__main__") == "__main__":
    try:
        main()
    except Exception as e:
        print("[Get Syncd] error: %s" % e)
