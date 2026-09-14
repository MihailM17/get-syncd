"""Minimal diff viewer for Get Syncd — no external deps beyond stdlib.

Serves a single HTML page that renders the diff as changelog + timeline bar.
Uses http.server so it works without FastAPI.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import webbrowser
import threading
import urllib.parse
from pathlib import Path
import tempfile
import subprocess

from ..otio_parse import parse_otio_file
from ..diff import diff_timelines, format_text
from .. import git_store


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Get Syncd — Diff Viewer</title>
<style>
  :root { --bg:#0f0f0f; --fg:#e8e8e8; --muted:#888; --green:#2ecc71; --red:#e74c3c; --yellow:#f1c40f; --blue:#3498db; --gap:#555; }
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg);line-height:1.5}
  header{padding:24px 20px;border-bottom:1px solid #222;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
  h1{margin:0;font-size:20px;letter-spacing:0.02em}
  h1 span{color:var(--muted);font-weight:400}
  .badge{font-size:12px;padding:4px 8px;border-radius:999px;background:#1a1a1a;border:1px solid #333;color:var(--muted)}
  main{max-width:1000px;margin:0 auto;padding:20px}
  .summary{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}
  .card{background:#151515;border:1px solid #222;border-radius:10px;padding:12px 14px;min-width:140px}
  .card b{font-size:18px}
  .card small{color:var(--muted)}
  .timeline{margin:20px 0;padding:14px;background:#111;border:1px solid #222;border-radius:10px;overflow-x:auto}
  .bar{display:flex;gap:3px;align-items:stretch;min-height:56px}
  .clip{flex:0 0 auto;min-width:60px;padding:6px 8px;border-radius:6px;font-size:11px;line-height:1.2;display:flex;flex-direction:column;justify-content:center;color:#fff;position:relative;cursor:default}
  .clip.added{background:var(--green);color:#000}
  .clip.removed{background:var(--red);text-decoration:line-through;opacity:0.9}
  .clip.trimmed{background:#b7950b;color:#000;border:1px dashed #fff3}
  .clip.reordered{background:var(--blue)}
  .clip.gap{background:var(--gap);color:#bbb;border:1px dashed #666}
  .clip.transition{background:#8e44ad}
  .clip small{opacity:0.8;font-size:10px;word-break:break-all}
  .legend{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:8px 0}
  .legend i{width:12px;height:12px;border-radius:2px;display:inline-block;vertical-align:middle;margin-right:4px}
  .changes{margin:16px 0}
  .change{padding:10px 12px;border-radius:8px;margin:6px 0;display:flex;gap:10px;align-items:flex-start;font-size:13px}
  .change.added{background:#2ecc7115;border:1px solid #2ecc7140}
  .change.removed{background:#e74c3c15;border:1px solid #e74c3c40}
  .change.trimmed{background:#f1c40f15;border:1px solid #f1c40f40}
  .change.reordered{background:#3498db15;border:1px solid #3498db40}
  .change.renamed{background:#9b59b615;border:1px solid #9b59b640}
  .mono{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;white-space:pre-wrap;background:#0a0a0a;border:1px solid #222;border-radius:8px;padding:12px;overflow:auto}
  footer{padding:16px;text-align:center;color:var(--muted);font-size:12px}
  a{color:var(--blue)}
</style>
</head>
<body>
<header>
  <h1>Get Syncd <span>— visual diff</span></h1>
  <span class="badge" id="revLabel"></span>
</header>
<main>
  <div id="summary" class="summary"></div>
  <div class="timeline">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      <b style="font-size:13px">Timeline</b>
      <span style="font-size:12px;color:var(--muted)" id="runtimeLabel"></span>
    </div>
    <div class="legend">
      <span><i style="background:var(--green)"></i> added</span>
      <span><i style="background:var(--red)"></i> removed</span>
      <span><i style="background:#b7950b"></i> trimmed</span>
      <span><i style="background:var(--blue)"></i> moved</span>
      <span><i style="background:var(--gap)"></i> gap</span>
      <span><i style="background:#8e44ad"></i> transition</span>
    </div>
    <div class="bar" id="bar"></div>
  </div>
  <div class="changes" id="changes"></div>
  <details style="margin-top:16px"><summary style="cursor:pointer;color:var(--muted)">Text changelog</summary><pre class="mono" id="textlog"></pre></details>
  <div id="warnings" style="margin-top:12px;color:#e67e22;font-size:13px"></div>
</main>
<footer>Get Syncd — open the restored .otio in Resolve via File → Import Timeline → OpenTimelineIO</footer>
<script>
const DATA = __DATA_JSON__;
document.getElementById('revLabel').textContent = DATA.rev_a + ' → ' + DATA.rev_b;
document.getElementById('runtimeLabel').textContent = DATA.summary.old_duration_s + 's → ' + DATA.summary.new_duration_s + 's (Δ ' + (DATA.summary.runtime_delta_s>0?'+':'') + DATA.summary.runtime_delta_s + 's)';
const summary = document.getElementById('summary');
// XSS-safe helpers: never use innerHTML with OTIO-derived strings (clip/track
// names and URLs come from project files and may contain markup).
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!==undefined&&text!==null) e.textContent=String(text); return e; }
const SAFE_TYPES = new Set(['added','removed','trimmed','reordered','renamed','gap_changed','transition_changed','gap','transition','stack','clip','unknown']);
function safeType(t){ return SAFE_TYPES.has(t) ? t : 'unknown'; }
function card(label, value){ const d=document.createElement('div'); d.className='card'; d.appendChild(el('small','',label)); d.appendChild(document.createElement('br')); d.appendChild(el('b','',value)); return d; }
summary.appendChild(card('Added', DATA.summary.added||0));
summary.appendChild(card('Removed', DATA.summary.removed||0));
summary.appendChild(card('Trimmed', DATA.summary.trimmed||0));
summary.appendChild(card('Moved', DATA.summary.reordered||0));
summary.appendChild(card('Changes', DATA.summary.total_changes||0));

// Timeline bar: render new timeline clips, color by change type
const bar = document.getElementById('bar');
const changesByNewIndex = new Map();
const changesByOldIndex = new Map();
DATA.changes.forEach(c=>{ if(c.index_new!==null&&c.index_new!==undefined) changesByNewIndex.set(c.index_new, c); if(c.index_old!==null&&c.index_old!==undefined) changesByOldIndex.set(c.index_old, c); });

if(DATA.new_track && DATA.new_track.items){
  DATA.new_track.items.forEach((item, idx)=>{
    const ch = changesByNewIndex.get(idx);
    const div=document.createElement('div');
    let cls='clip';
    if(ch){
      cls+=' '+safeType(ch.type);
    }
    div.className=cls;
    // Width proportional to duration (clamped)
    const dur = item.duration_frames || 24;
    const w = Math.max(60, Math.min(200, dur/6));
    div.style.width=w+'px';
    div.title = (item.name||'(unnamed)') + ' — ' + (item.url||item.kind) + ' — ' + (item.duration_frames/NORMALIZED_RATE).toFixed(2)+'s' + (ch? ' — '+ch.type:'');
    div.appendChild(el('b','',item.name||item.kind));
    div.appendChild(el('small','',item.url ? item.url.split('/').pop() : item.kind));
    bar.appendChild(div);
  });
} else {
  bar.textContent='(no track data)';
}

// Changes list (all user-derived strings via textContent — never innerHTML)
const list=document.getElementById('changes');
DATA.changes.forEach(ch=>{
  const div=document.createElement('div');
  div.className='change '+safeType(ch.type);
  let icon='+';
  if(ch.type==='removed') icon='−';
  else if(ch.type==='trimmed') icon='~';
  else if(ch.type==='reordered') icon='↔';
  else if(ch.type==='renamed') icon='✎';
  const d = ch.details || {};
  let detail='';
  if(ch.type==='trimmed') detail= 'trimmed '+(d.delta_s||0)+'s ('+d.old_duration_s+'s → '+d.new_duration_s+'s)';
  else if(ch.type==='added') detail='added ('+(d.duration_s||'?')+'s)';
  else if(ch.type==='removed') detail='removed';
  else if(ch.type==='reordered') detail='moved ['+ch.index_old+'→'+ch.index_new+']';
  else if(ch.type==='renamed') detail='renamed '+d.renamed_from+' → '+d.renamed_to;
  else detail=ch.type;
  const iconSpan=document.createElement('span'); iconSpan.style.fontWeight='700'; iconSpan.textContent=icon;
  const body=document.createElement('span');
  body.appendChild(el('b','',ch.clip_name||'(unnamed)'));
  body.appendChild(document.createTextNode(' '));
  const urlSmall=document.createElement('small'); urlSmall.style.color='var(--muted)'; urlSmall.textContent=(ch.url||ch.kind||'');
  body.appendChild(urlSmall);
  body.appendChild(document.createElement('br'));
  body.appendChild(el('small','',detail));
  div.appendChild(iconSpan); div.appendChild(body);
  list.appendChild(div);
});
if(DATA.changes.length===0){ const empty=document.createElement('div'); empty.style.color='var(--muted)'; empty.textContent='No clip-level changes — timelines identical on compared track.'; list.appendChild(empty); }
document.getElementById('textlog').textContent = DATA.text_log || '';
if(DATA.warnings && DATA.warnings.length){
  const warnBox=document.getElementById('warnings');
  DATA.warnings.forEach((w,i)=>{ const line=document.createElement('div'); line.textContent='⚠ '+w; warnBox.appendChild(line); });
}
</script>
</body>
</html>
"""

# Rate used for display width calculation in JS
NORMALIZED_RATE = 600.0


def build_viewer_data(repo: Path, rev_a: str, rev_b: str, timeline_file: str = "timeline.otio") -> dict:
    import tempfile

    def rev_to_parsed(rev: str):
        # If rev is a file path, parse directly
        p = Path(rev)
        if p.exists() and p.is_file():
            return parse_otio_file(p), str(p)
        # Otherwise git rev
        tmp = tempfile.NamedTemporaryFile(suffix=".otio", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            git_store.restore_version(repo, rev, tmp_path, timeline_file=timeline_file)
            parsed = parse_otio_file(tmp_path)
            return parsed, rev
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass

    old, _ = rev_to_parsed(rev_a)
    new, _ = rev_to_parsed(rev_b)

    diff = diff_timelines(old, new)
    text_log = format_text(diff, old_name=rev_a, new_name=rev_b)

    # Prepare track data for rendering
    main_new = new.main_track()
    new_track_data = None
    if main_new:
        new_track_data = {
            "name": main_new.name,
            "kind": main_new.kind,
            "items": [
                {
                    "name": c.name,
                    "url": c.url,
                    "kind": c.kind,
                    "duration_frames": c.duration_frames,
                    "index": c.index,
                }
                for c in main_new.items
            ],
        }

    data = {
        "rev_a": rev_a,
        "rev_b": rev_b,
        "summary": diff.summary,
        "changes": [c.to_dict() for c in diff.changes],
        "tracks_compared": diff.tracks_compared,
        "warnings": diff.warnings,
        "text_log": text_log,
        "new_track": new_track_data,
        "NORMALIZED_RATE": NORMALIZED_RATE,
    }
    return data


class ViewerHandler(http.server.SimpleHTTPRequestHandler):
    viewer_data = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            # Escape script-breakout sequences: clip/track names are attacker-
            # controlled and embedded inside a <script> block.
            data_json = json.dumps(self.viewer_data).replace("</", "<\\/").replace("<!--", "<\\!--")
            html = HTML_TEMPLATE.replace("__DATA_JSON__", data_json)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        elif parsed.path == "/data.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(self.viewer_data, indent=2).encode("utf-8"))
        else:
            self.send_error(404, "Not found")

    def log_message(self, format, *args):
        # Quiet except errors
        sys = __import__("sys")
        sys.stdout.write("[viewer] %s\n" % (format % args))


def run_viewer(repo: Path, rev_a: str, rev_b: str, port: int = 8000, open_browser: bool = True):
    data = build_viewer_data(repo, rev_a, rev_b)
    ViewerHandler.viewer_data = data

    # Try ports if busy
    for p in range(port, port + 10):
        try:
            # Loopback only — the viewer exposes clip names/paths and must
            # never listen on LAN interfaces (matches the API server).
            with socketserver.TCPServer(("127.0.0.1", p), ViewerHandler) as httpd:
                url = f"http://localhost:{p}/"
                print(f"Get Syncd viewer: {rev_a} → {rev_b}")
                print(f"  {data['summary']}")
                print(f"Serving at {url}")
                print("Press Ctrl+C to stop.")
                if open_browser:
                    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
                try:
                    httpd.serve_forever()
                except KeyboardInterrupt:
                    print("\nViewer stopped.")
                return
        except OSError as e:
            if "Address already in use" in str(e):
                continue
            raise
    print(f"Could not bind to port {port}–{port+9}", file=__import__("sys").stderr)
