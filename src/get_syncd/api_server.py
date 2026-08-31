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

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import mimetypes

from . import api as core_api
from .preview import _preview_path

def _cors_headers(handler: BaseHTTPRequestHandler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")

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
            self._json({"ok": True, "service": "get-syncd"})
            return
        if parsed.path == "/api/status":
            self._json(core_api.api_status(repo))
            return
        if parsed.path == "/api/log":
            limit = int(qs.get("limit", ["20"])[0])
            self._json(core_api.api_log(repo, limit=limit))
            return
        if parsed.path == "/api/graph":
            self._json(core_api.api_graph(repo))
            return
        if parsed.path == "/api/branches":
            self._json(core_api.api_branches(repo))
            return
        if parsed.path == "/api/diff":
            a = qs.get("a", ["HEAD~1"])[0]
            b = qs.get("b", ["HEAD"])[0]
            try:
                data = core_api.api_diff(repo, a, b)
                self._json(data)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, status=500)
            return
        if parsed.path == "/api/projects":
            self._json(core_api.api_list_projects())
            return
        if parsed.path == "/api/resolve/projects":
            self._json(core_api.api_scan_resolve_projects())
            return
        if parsed.path == "/api/preview":
            h = qs.get("hash", [""])[0]
            if not h:
                self.send_error(400, "hash required")
                return
            # find preview file
            from pathlib import Path as P
            r = core_api._resolve_repo(repo)
            p = _preview_path(r, h)
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

        if parsed.path == "/api/save":
            res = core_api.api_save(repo, file=data.get("file"), message=data.get("message"))
            self._json(res, status=200 if res.get("ok") else 400)
            return
        if parsed.path == "/api/restore":
            res = core_api.api_restore(repo, rev=data.get("rev", "HEAD"), apply=bool(data.get("apply")), out=data.get("out"))
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
        if parsed.path == "/api/resolve/scan":
            res = core_api.api_scan_resolve_projects()
            self._json(res, status=200 if res.get("ok") else 400)
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

def run_api_server(port: int = 5174, open_browser: bool = False):
    # try ports 5174..5184
    for p in range(port, port+10):
        try:
            httpd = HTTPServer(("127.0.0.1", p), Handler)
            print(f"Get Syncd API listening on http://127.0.0.1:{p}")
            print(f"  GET /api/status?repo=~/GetSyncd")
            print(f"  GET /api/log?repo=~/GetSyncd")
            print(f"  GET /api/diff?repo=~/GetSyncd&a=1&b=2")
            print(f"  POST /api/save {{\"repo\":\"~/GetSyncd\",\"message\":\"note\"}}")
            print(f"  Tauri React dev server can fetch http://127.0.0.1:{p}/api/*")
            if open_browser:
                import webbrowser, threading
                threading.Timer(0.5, lambda: webbrowser.open(f"http://127.0.0.1:{p}/health")).start()
            httpd.serve_forever()
            return
        except OSError as e:
            if "Address already in use" in str(e):
                continue
            raise
    print(f"Could not bind 5174-5184", file=__import__("sys").stderr)

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5174)
    args = ap.parse_args()
    run_api_server(port=args.port)
