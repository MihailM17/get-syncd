"""Get Syncd — Local HTTP JSON API for Tauri sidecar.

Runs on 127.0.0.1 and exposes the Python core as JSON so React can call it
without spawning subprocesses. Preserves the same git/OTIO logic as CLI.

Endpoints:
  GET  /api/status?repo=PATH
  GET  /api/log?repo=PATH&limit=20
  GET  /api/graph?repo=PATH
  GET  /api/branches?repo=PATH
  GET  /api/diff?repo=PATH&a=REV&b=REV
  POST /api/save  {repo, file, message}
  POST /api/restore {repo, rev, apply}
  GET  /api/projects -> list of ~/GetSyncd sub-projects
  GET  /api/resolve/projects -> scan Resolve DB
  POST /api/resolve/scan -> scan + auto-create folders
  GET  /api/preview?repo=PATH&hash=SHORT  -> PNG
  GET  /health

CORS enabled for Tauri dev server.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from pathlib import Path
import mimetypes

from . import api as core_api
from .preview import _preview_path

# The sidecar is a single per-user daemon on one fixed port. The 5174–5183
# range survives only in *clients* (App.tsx probe, GetSyncd_Launch.py) as a
# harmless superset so old orphans are still found and reaped during the
# transition — the server itself no longer hops ports.
API_PORT_START = 5174
API_PORT_COUNT = 1

_STARTED = time.time()

# Set by scripts/sidecar_entry.py in frozen builds so /health can tell
# binaries apart even when the package version is unchanged ("dev" for
# `python -m get_syncd.api_server`).
SERVER_BUILD = "dev"


def _server_version() -> str:
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("get-syncd")
    except Exception:
        pass
    try:
        from . import __version__ as _v
        return str(_v)
    except Exception:
        return "0.0.0"


def _same_daemon(version: str | None, build: str | None) -> bool:
    """True if a probed server is ours to reuse (not stale to reap).

    Missing build (pre-build-id servers, incl. old frozen binaries) falls
    back to version-only comparison for backward compat.
    """
    if (version or "") != _server_version():
        return False
    if not build or build == "dev" or SERVER_BUILD == "dev":
        return True
    return build == SERVER_BUILD


# --- Single per-user daemon election -------------------------------------
# A tiny runtime file (~/.get-syncd/api.json) records {port, pid, version,
# started} for the current daemon. A new process reuses a healthy
# same-version daemon (and exits), or reaps a stale/different-version one
# (update case) instead of stacking another orphan on the next port.
def _runtime_dir() -> Path:
    d = Path.home() / ".get-syncd"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _runtime_file() -> Path:
    return _runtime_dir() / "api.json"


def _read_runtime() -> dict | None:
    try:
        p = _runtime_file()
        if not p.exists():
            return None
        data = json.loads(p.read_text())
        if isinstance(data, dict) and data.get("port") and data.get("pid"):
            return data
    except Exception:
        pass
    return None


def _write_runtime(port: int) -> None:
    try:
        _runtime_file().write_text(json.dumps({
            "port": int(port),
            "pid": os.getpid(),
            "version": _server_version(),
            "build": SERVER_BUILD,
            "started": _STARTED,
        }))
    except Exception:
        pass


def _clear_runtime() -> None:
    try:
        p = _runtime_file()
        if not p.exists():
            return
        data = json.loads(p.read_text())
        # Only remove our own file — never delete a successor's.
        if isinstance(data, dict) and int(data.get("pid", -1)) == os.getpid():
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        pid = int(pid)
    except Exception:
        return False
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import subprocess
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=3,
            )
            return str(pid) in (out.stdout or "")
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _fetch_health(port: int, timeout: float = 0.7) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{int(port)}/health", timeout=timeout
        ) as r:
            if r.status != 200:
                return None
            data = json.loads(r.read().decode() or "{}")
            return data if isinstance(data, dict) and data.get("ok") else None
    except Exception:
        return None


def _request_shutdown(port: int, timeout: float = 1.5) -> bool:
    """Ask a local server to exit cleanly (loopback only). Best-effort."""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{int(port)}/api/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _kill_pid(pid: int, timeout: float = 3.0) -> None:
    try:
        pid = int(pid)
    except Exception:
        return
    if pid == os.getpid():
        return
    try:
        if os.name == "nt":
            import subprocess
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=5,
            )
            return
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _pid_alive(pid):
                return
            time.sleep(0.1)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass


def _reap_one_stale_server(port: int, pid: int | None, my_version: str) -> None:
    """Shutdown+kill a stale server at port/pid. Never touches our own pid."""
    try:
        if pid and int(pid) == os.getpid():
            return
    except Exception:
        pass
    _request_shutdown(port)
    deadline = time.time() + 2.0
    while time.time() < deadline:
        h = _fetch_health(port, timeout=0.4)
        if not h:
            break
        time.sleep(0.15)
    if pid and _pid_alive(pid):
        # Re-verify the port STILL serves that same pid before SIGKILL: the
        # pid could have been recycled by an unrelated process while we
        # waited, and killing a stranger is the worst thing this code can do.
        try:
            h = _fetch_health(port, timeout=0.6)
            if h and h.get("ok") and int(h.get("pid", -1) or -1) == int(pid):
                _kill_pid(pid)
            elif not h:
                # Port went quiet but pid lives on — it may have exited and
                # the pid been reused; only kill if the command line matches.
                if _pid_cmdline_matches(pid):
                    _kill_pid(pid)
                else:
                    _diag_log(f"NOT killing pid={pid}: port :{port} quiet and cmdline doesn't match")
        except Exception:
            pass


def _pid_cmdline_matches(pid: int) -> bool:
    """True if pid's command line looks like our sidecar (macOS/Linux)."""
    try:
        if os.name == "nt":
            return True  # can't check cheaply; health re-verify above covers it
        import subprocess
        out = subprocess.run(
            ["ps", "-o", "args=", "-p", str(int(pid))],
            capture_output=True, text=True, timeout=3,
        )
        args = (out.stdout or "").lower()
        return ("get-syncd-api" in args) or ("get_syncd" in args and "api_server" in args)
    except Exception:
        return False

ALLOWED_ORIGINS = {
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "tauri://localhost",
    "http://tauri.localhost",
}

def _cors_headers(handler: BaseHTTPRequestHandler):
    origin = handler.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        handler.send_header("Access-Control-Allow-Origin", origin)
        handler.send_header("Vary", "Origin")
    # No wildcard: browsers without Origin (Tauri sidecar, curl) don't need ACAO
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


def _repo_allowed(repo: str | None) -> bool:
    try:
        return core_api.is_repo_allowed(repo) if repo else True
    except Exception:
        return False

class Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        _cors_headers(self)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        repo = qs.get("repo", [None])[0]

        if parsed.path == "/health":
            # pid/started let clients pick the freshest server when several
            # sidecars are alive (e.g. orphans squatting 5174 after an update).
            # build tells binaries with the same version apart.
            # watched is the ppid the orphan watchdog armed on (null = disarmed).
            self._json({"ok": True, "service": "get-syncd", "version": _server_version(), "build": SERVER_BUILD, "pid": os.getpid(), "started": _STARTED, "watched": WATCHED_PARENT[0] if WATCHED_PARENT else None})
            return
        # Trust boundary: repo must stay under ~/GetSyncd
        if repo and not _repo_allowed(repo):
            self._json({"ok": False, "error": "Repo outside ~/GetSyncd not allowed"}, status=403)
            return
        if parsed.path == "/api/status":
            self._json(core_api.api_status(repo))
            return
        if parsed.path == "/api/log":
            try:
                limit = max(1, min(int(qs.get("limit", ["20"])[0]), 100))
            except ValueError:
                limit = 20
            timeline = qs.get("timeline", [None])[0]
            self._json(core_api.api_log(repo, limit=limit, timeline=timeline))
            return
        if parsed.path == "/api/timelines":
            self._json(core_api.api_timelines(repo))
            return
        if parsed.path == "/api/graph":
            self._json(core_api.api_graph(repo))
            return
        if parsed.path == "/api/branches":
            self._json(core_api.api_branches(repo))
            return
        if parsed.path == "/api/graph/viz":
            timeline = qs.get("timeline", [None])[0]
            self._json(core_api.api_graph_viz(repo, timeline=timeline))
            return
        if parsed.path == "/api/diff":
            a = qs.get("a", ["HEAD~1"])[0][:80]
            b = qs.get("b", ["HEAD"])[0][:80]
            timeline = qs.get("timeline", [None])[0]
            try:
                data = core_api.api_diff(repo, a, b, timeline=timeline)
                self._json(data)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, status=500)
            return
        if parsed.path == "/api/projects":
            self._json(core_api.api_list_projects())
            return
        if parsed.path == "/api/default-repo":
            self._json(core_api.api_default_repo())
            return
        if parsed.path == "/api/resolve/projects":
            self._json(core_api.api_scan_resolve_projects())
            return
        if parsed.path == "/api/resolve/current":
            self._json(core_api.api_get_current_resolve())
            return
        if parsed.path == "/api/github/status":
            self._json(core_api.api_github_status())
            return
        if parsed.path == "/api/preview":
            h = qs.get("hash", [""])[0]
            if not h or not h.replace("-", "").replace("_", "").isalnum():
                self.send_error(400, "invalid hash")
                return
            # find preview file
            from pathlib import Path as P
            r = core_api._resolve_repo(repo)
            if not core_api.is_repo_allowed(r):
                self._json({"ok": False, "error": "Repo outside ~/GetSyncd not allowed"}, status=403)
                return
            p = _preview_path(r, h)
            # Contain preview path inside repo (no traversal)
            try:
                p.resolve().relative_to(r.resolve())
            except ValueError:
                self.send_error(404, "preview not found")
                return
            if not p.exists():
                self.send_error(404, "preview not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            _cors_headers(self)
            self.end_headers()
            self.wfile.write(p.read_bytes())
            return
        self.send_error(404, f"Unknown GET {parsed.path}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body.decode() or "{}")
        except Exception:
            data = {}
        repo = data.get("repo") or urllib.parse.parse_qs(parsed.query).get("repo", [None])[0]
        if repo and not _repo_allowed(repo):
            self._json({"ok": False, "error": "Repo outside ~/GetSyncd not allowed"}, status=403)
            return

        if parsed.path == "/api/resolve/sync":
            res = core_api.api_sync_resolve(repo)
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/github/create":
            res = core_api.api_github_create(
                repo,
                name=str(data.get("name", "")),
                private=bool(data.get("private", True)),
                description=str(data.get("description", "")),
            )
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/save":
            res = core_api.api_save(repo, file=data.get("file"), message=data.get("message"), timeline=data.get("timeline"), all_timelines=bool(data.get("all_timelines")))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/restore":
            res = core_api.api_restore(repo, rev=data.get("rev", "HEAD"), apply=bool(data.get("apply")), out=data.get("out"), timeline=data.get("timeline"))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/init":
            res = core_api.api_init(repo, remote=data.get("remote"))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/branch":
            res = core_api.api_create_branch(repo, name=data.get("name", ""))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/branch/delete":
            res = core_api.api_delete_branch(repo, name=data.get("name", "") or data.get("branch", ""), force=bool(data.get("force")))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/delete":
            res = core_api.api_delete(repo, rev=data.get("rev") or data.get("hash") or "", timeline=data.get("timeline"))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/export":
            res = core_api.api_export(repo, out=data.get("out") or data.get("file"), timeline=data.get("timeline"))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/push":
            res = core_api.api_push(repo)
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/resolve/scan":
            res = core_api.api_scan_resolve_projects()
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/shutdown":
            # Loopback-only clean exit so a newer version (or the app on quit)
            # can reap this daemon without SIGKILL. No repo needed.
            try:
                client = (self.client_address[0] if self.client_address else "")
            except Exception:
                client = ""
            if client not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                self._json({"ok": False, "error": "loopback only"}, status=403)
                return
            self._json({"ok": True, "pid": os.getpid()})
            srv = self.server
            threading.Thread(target=_shutdown_server, args=(srv,), daemon=True).start()
            return
        self.send_error(404, f"Unknown POST {parsed.path}")

    def _json(self, obj, status=200):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        _cors_headers(self)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # quiet unless error
        import sys
        sys.stdout.write(f"[api] {format % args}\n")

def _diag_log(msg: str) -> None:
    """Unbuffered file log for the daemon lifecycle (stdout is lost/buffered
    when spawned by the GUI app, so election/watchdog/shutdown go here)."""
    try:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} pid={os.getpid()} {msg}\n"
        with open(_runtime_dir() / "api.log", "a") as f:
            f.write(line)
    except Exception:
        pass
    try:
        print(f"[api] {msg}", flush=True)
    except Exception:
        pass


def _parent_ident() -> tuple[int, str]:
    """(ppid, parent-start-time) — pid alone can be recycled, the pair can't."""
    try:
        ppid = os.getppid()
    except Exception:
        return (-1, "")
    start = ""
    if os.name != "nt":
        try:
            import subprocess
            out = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(ppid)],
                capture_output=True, text=True, timeout=3,
            )
            start = (out.stdout or "").strip()
        except Exception:
            pass
    return (ppid, start)


def _shutdown_server(srv) -> None:
    """Exit cleanly: remove our runtime file, then stop serve_forever()."""
    try:
        _clear_runtime()
    except Exception:
        pass
    try:
        srv.shutdown()
    except Exception:
        pass


# ppid recorded by the watchdog once we bind (None = disarmed). Exposed in
# /health as "watched" for debugging orphan cases.
WATCHED_PARENT: tuple[int, str] | None = None


def _watch_parent(httpd, stop_event: "threading.Event", poll_s: float = 2.0) -> None:
    """Exit when the parent process goes away (orphan watchdog).

    Why: a PyInstaller onefile binary is a bootloader parent + Python child.
    The Tauri app tracks and kills the bootloader on quit, which orphans the
    Python server (killing the bootloader does NOT kill the child). Watching
    the parent lets the server shut itself down cleanly — runtime file
    included — instead of squatting 5174 until the next launch reaps it.

    Identity is (ppid, parent-start-time): a bare pid can be recycled by an
    unrelated process, the pair effectively can't.

    A server already reparented to init (ppid<=1) at startup is a deliberate
    daemon — nothing to watch (logged loudly, since an app-spawned server
    should never start life that way). Windows has no reparenting, so the
    watchdog simply never fires there (quit-cleanup relies on child kill +
    next-launch reaping on that platform).
    """
    global WATCHED_PARENT
    ppid, start = _parent_ident()
    if ppid <= 1:
        _diag_log(f"watchdog DISARMED: already reparented to init at bind (ppid={ppid})")
        return
    WATCHED_PARENT = (ppid, start)
    _diag_log(f"watchdog armed: parent={ppid} ({start})")
    while not stop_event.wait(poll_s):
        try:
            cur = _parent_ident()
            if cur != (ppid, start):
                _diag_log(f"watchdog: parent changed {ppid}/{start} -> {cur[0]}/{cur[1]} — shutting down")
                break
        except Exception as e:
            _diag_log(f"watchdog check failed ({e}) — shutting down")
            break
    WATCHED_PARENT = None
    _shutdown_server(httpd)


def _warmup_otio_background() -> None:
    """Warm OTIO off the critical path so /health is instant on cold start."""
    try:
        from .otio_parse import warmup_otio

        warmup_otio()
    except Exception:
        pass


def _find_reusable_or_stale(port: int) -> tuple[dict | None, list[tuple[int, int, str]]]:
    """Probe runtime file + port range.

    Returns (reusable_same_version_server, stale_servers).
    reusable: {"port","pid","version","started"} healthy and same daemon.
    stale: list of (port, pid, version) that are healthy but different daemon.
    """
    reusable: dict | None = None
    stale: list[tuple[int, int, str]] = []

    # 1) Runtime file fast path (single per-user daemon).
    rt = _read_runtime()
    if rt:
        try:
            rt_port = int(rt.get("port", 0))
            rt_pid = int(rt.get("pid", 0))
        except Exception:
            rt_port, rt_pid = 0, 0
        if rt_port and rt_pid != os.getpid():
            h = _fetch_health(rt_port, timeout=0.6)
            if h and h.get("ok"):
                v = str(h.get("version", rt.get("version", "")))
                b = h.get("build", rt.get("build"))
                pid = int(h.get("pid", rt_pid) or rt_pid)
                if _same_daemon(v, b) and _pid_alive(pid):
                    reusable = {"port": rt_port, "pid": pid,
                                "version": v, "started": float(h.get("started", 0) or 0)}
                elif _pid_alive(pid):
                    stale.append((rt_port, pid, v))
            else:
                # Runtime file points at a dead server — clean it so we can bind.
                if not _pid_alive(rt_pid):
                    try:
                        if _read_runtime() and int(_read_runtime().get("pid", -1)) == rt_pid:
                            _runtime_file().unlink(missing_ok=True)
                    except Exception:
                        pass

    # 2) Sweep the port for orphans squatting it after an update.
    for p in range(port, port + API_PORT_COUNT):
        if reusable and p == reusable["port"]:
            continue
        h = _fetch_health(p, timeout=0.35)
        if not h:
            continue
        try:
            pid = int(h.get("pid", 0) or 0)
        except Exception:
            pid = 0
        v = str(h.get("version", ""))
        if pid == os.getpid():
            continue
        if _same_daemon(v, h.get("build")) and pid and _pid_alive(pid):
            # Prefer the freshest same-daemon server (matches frontend logic).
            cand = {"port": p, "pid": pid, "version": v,
                    "started": float(h.get("started", 0) or 0)}
            if reusable is None or cand["started"] > reusable.get("started", 0):
                reusable = cand
        elif pid and _pid_alive(pid):
            if (p, pid, v) not in stale:
                stale.append((p, pid, v))
    return reusable, stale


def run_api_server(port: int = 5174, open_browser: bool = False, singleton: bool = True, watch_parent: bool = True):
    # Singleton election BEFORE binding: reuse same daemon, reap stale.
    if singleton:
        reusable, stale = _find_reusable_or_stale(port)
        my_version = _server_version()
        for sp, spid, sv in stale:
            _diag_log(f"reaping stale server v{sv} pid={spid} on :{sp} (we are v{my_version}/{SERVER_BUILD})")
            print(f"[api] reaping stale server v{sv} pid={spid} on :{sp} (we are v{my_version})")
            _reap_one_stale_server(sp, spid, my_version)
        if reusable:
            _diag_log(f"reusing live daemon v{reusable['version']} pid={reusable['pid']} on :{reusable['port']} — exiting")
            print(f"Get Syncd API already running (v{reusable['version']} "
                  f"pid={reusable['pid']}) on http://127.0.0.1:{reusable['port']} — reusing it")
            # Refresh runtime file if it went missing but the server is alive.
            try:
                if not _runtime_file().exists():
                    _runtime_dir().mkdir(parents=True, exist_ok=True)
                    _runtime_file().write_text(json.dumps({
                        "port": reusable["port"], "pid": reusable["pid"],
                        "version": reusable["version"], "build": SERVER_BUILD,
                        "started": reusable["started"],
                    }))
            except Exception:
                pass
            return reusable["port"]
        # Re-check runtime file: a previous dead entry may still block us.
        rt = _read_runtime()
        if rt:
            try:
                if not _pid_alive(int(rt.get("pid", 0))):
                    _runtime_file().unlink(missing_ok=True)
            except Exception:
                pass

    # Kick OTIO warmup in the background immediately — /health must answer
    # instantly even on a ~12s PyInstaller cold start. Parse paths take the
    # OTIO lock, so they safely wait if they race the warmup.
    threading.Thread(target=_warmup_otio_background, daemon=True).start()

    for p in range(port, port+API_PORT_COUNT):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            httpd.daemon_threads = True
            _write_runtime(p)
            _diag_log(f"bound 127.0.0.1:{p} (v{_server_version()}/{SERVER_BUILD}) ppid={os.getppid()}")
            atexit.register(_clear_runtime)
            try:
                signal.signal(signal.SIGTERM, lambda *_: (_clear_runtime(), _shutdown_server(httpd)))
            except Exception:
                pass
            try:
                signal.signal(signal.SIGINT, lambda *_: (_clear_runtime(), _shutdown_server(httpd)))
            except Exception:
                pass
            print(f"Get Syncd API listening on http://127.0.0.1:{p}")
            print(f"  GET /api/status?repo=~/GetSyncd")
            print(f"  GET /api/log?repo=~/GetSyncd")
            print(f"  GET /api/diff?repo=~/GetSyncd&a=1&b=2")
            print(f"  POST /api/save {{\"repo\":\"~/GetSyncd\",\"message\":\"note\"}}")
            print(f"  Tauri React dev server can fetch http://127.0.0.1:{p}/api/*")
            if open_browser:
                import webbrowser
                threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{p}/health")).start()
            _stop_watch = threading.Event()
            if watch_parent:
                threading.Thread(target=_watch_parent, args=(httpd, _stop_watch), daemon=True).start()
            try:
                httpd.serve_forever()
            finally:
                _stop_watch.set()
                _clear_runtime()
            return p
        except OSError as e:
            if "Address already in use" in str(e):
                # Race: someone bound between our probe and bind. If it is a
                # same-version server, reuse it; otherwise reap once and retry.
                h = _fetch_health(p, timeout=0.6)
                if h and h.get("ok"):
                    try:
                        pid = int(h.get("pid", 0) or 0)
                    except Exception:
                        pid = 0
                    v = str(h.get("version", ""))
                    if singleton and _same_daemon(v, h.get("build")) and pid and _pid_alive(pid):
                        print(f"Get Syncd API already running (v{v} pid={pid}) "
                              f"on http://127.0.0.1:{p} — reusing it")
                        return p
                    if singleton and pid and _pid_alive(pid):
                        print(f"[api] port :{p} taken by stale v{str(v or '?')} pid={pid} — reaping")
                        _reap_one_stale_server(p, pid, _server_version())
                        time.sleep(0.4)
                        try:
                            httpd2 = ThreadingHTTPServer(("127.0.0.1", p), Handler)
                            httpd2.daemon_threads = True
                            _write_runtime(p)
                            atexit.register(_clear_runtime)
                            print(f"Get Syncd API listening on http://127.0.0.1:{p} (after reaping stale)")
                            _stop_watch2 = threading.Event()
                            if watch_parent:
                                threading.Thread(target=_watch_parent, args=(httpd2, _stop_watch2), daemon=True).start()
                            try:
                                httpd2.serve_forever()
                            finally:
                                _stop_watch2.set()
                                _clear_runtime()
                            return p
                        except OSError:
                            pass
                continue
            raise
    print(f"Could not bind {port}-{port+API_PORT_COUNT-1}", file=__import__("sys").stderr)
    return None

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5174)
    ap.add_argument("--singleton", dest="singleton", action="store_true", default=True)
    ap.add_argument("--no-singleton", dest="singleton", action="store_false")
    ap.add_argument("--no-watchdog", dest="watch_parent", action="store_false", default=True,
                    help="Don't exit when the parent process dies (for intentional daemonizing)")
    args = ap.parse_args()
    run_api_server(port=args.port, singleton=args.singleton, watch_parent=args.watch_parent)
