"""Get Syncd — Pure JSON API layer for Tauri/React sidecar.

No Rich, no sys.exit, no input() — just data. CLI and Tauri both call these.
Preserves core: Resolve → OTIO → git → GitHub, media stays local.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from . import git_store
from .otio_parse import parse_otio_file
from .diff import diff_timelines, changelog_line
from .preview import generate_preview, _preview_path

DEFAULT_REPO = Path.home() / "GetSyncd"

def _resolve_repo(repo: str | Path | None) -> Path:
    if not repo:
        return DEFAULT_REPO
    p = Path(repo).expanduser()
    # if passed repo is file, use parent
    if p.is_file():
        p = p.parent
    return p.resolve()

def api_init(repo: str | Path | None = None, remote: str | None = None) -> dict:
    r = _resolve_repo(repo)
    r.mkdir(parents=True, exist_ok=True)
    git_store.init_repo(r, remote_url=remote)
    return {"ok": True, "repo": str(r), "remote": remote}

def api_status(repo: str | Path | None = None) -> dict:
    r = _resolve_repo(repo)
    res = git_store.status(r)
    # also include repo and branches for UI
    branches = []
    try:
        br = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(r), capture_output=True, text=True)
        if br.returncode == 0:
            branches = [l.strip() for l in br.stdout.splitlines() if l.strip()]
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(r), capture_output=True, text=True)
        cur_branch = cur.stdout.strip() if cur.returncode == 0 else ""
    except Exception:
        cur_branch = ""
        branches = []
    return {
        "repo": str(r),
        "is_repo": res.get("is_repo"),
        "has_changes": res.get("has_changes"),
        "message": res.get("message"),
        "stat": res.get("stat", ""),
        "branches": branches,
        "current_branch": cur_branch,
    }

def api_log(repo: str | Path | None = None, limit: int = 20) -> list[dict]:
    r = _resolve_repo(repo)
    versions = git_store.log_versions(r, limit=limit)
    # enrich with preview path
    out = []
    for v in versions:
        p = _preview_path(r, v["hash"])
        out.append({**v, "preview": str(p) if p.exists() else None})
    return out

def api_graph(repo: str | Path | None = None) -> dict:
    r = _resolve_repo(repo)
    try:
        gr = subprocess.run(["git", "log", "--graph", "--all", "--oneline", "--decorate", "-n", "30", "--color=never"], cwd=str(r), capture_output=True, text=True)
        graph = gr.stdout.strip() if gr.returncode == 0 else ""
        if not graph:
            gr2 = subprocess.run(["git", "log", "--oneline", "-n", "20"], cwd=str(r), capture_output=True, text=True)
            graph = gr2.stdout.strip()
    except Exception as e:
        graph = f"error: {e}"
    return {"repo": str(r), "graph": graph}

def api_diff(repo: str | Path | None = None, a: str = "HEAD~1", b: str = "HEAD") -> dict:
    r = _resolve_repo(repo)
    # resolve numeric aliases via cli helper logic (duplicate to avoid cli import)
    def _alias(rev: str) -> str:
        rev = rev.strip()
        if rev.isdigit():
            n = int(rev)
            vers = git_store.log_versions(r, limit=max(20, n))
            if 0 <= n-1 < len(vers):
                return vers[n-1]["hash"]
        return rev
    a2 = _alias(a)
    b2 = _alias(b)
    # materialize
    def _rev_to_file(rev: str) -> Path:
        p = Path(rev)
        if p.exists() and p.is_file():
            return p
        tmp = tempfile.NamedTemporaryFile(suffix=".otio", delete=False)
        tp = Path(tmp.name); tmp.close()
        git_store.restore_version(r, rev, tp)
        return tp
    pa = _rev_to_file(a2)
    pb = _rev_to_file(b2)
    try:
        old = parse_otio_file(pa)
        new = parse_otio_file(pb)
        d = diff_timelines(old, new)
        # build viewer data for React bar
        from .viewer.app import build_viewer_data
        vd = build_viewer_data(r, a, b)
        return {
            "repo": str(r),
            "a": a, "b": b,
            "a_resolved": a2, "b_resolved": b2,
            "summary": d.summary,
            "changes": [c.to_dict() for c in d.changes],
            "warnings": d.warnings,
            "tracks_compared": d.tracks_compared,
            "changelog": changelog_line(d),
            "new_track": vd.get("new_track"),
            "text_log": vd.get("text_log"),
        }
    finally:
        for p in (pa, pb):
            try:
                # only unlink temps (not original files)
                if p.exists() and p.suffix == ".otio" and "/tmp" in str(p):
                    p.unlink(missing_ok=True)
            except Exception:
                pass

def api_save(repo: str | Path | None = None, file: str | Path | None = None, message: str | None = None) -> dict:
    r = _resolve_repo(repo)
    if not r.exists():
        r.mkdir(parents=True, exist_ok=True)
    # discovery like cli.save
    src = None
    if file:
        src = Path(file).expanduser()
    else:
        default = r / "timeline.otio"
        if default.exists():
            src = default
        else:
            cands = list(r.glob("*.otio"))
            if len(cands) == 1:
                src = cands[0]
            elif len(cands) > 1:
                return {"ok": False, "error": f"Multiple .otio files: {', '.join(p.name for p in cands)}. Specify file."}
            else:
                return {"ok": False, "error": "No timeline.otio yet — export from Resolve first: File → Export Timeline → OpenTimelineIO → ~/GetSyncd/timeline.otio"}
    if not src or not Path(src).exists():
        return {"ok": False, "error": f"File not found: {src}"}
    # auto message if none
    msg = message
    if not msg:
        try:
            if git_store.is_git_repo(r) and (r / "timeline.otio").exists():
                # diff vs HEAD
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                    tp = Path(tmp.name)
                try:
                    git_store.restore_version(r, "HEAD", tp)
                    old = parse_otio_file(tp)
                    new = parse_otio_file(Path(src))
                    d = diff_timelines(old, new)
                    msg = changelog_line(d)
                except Exception:
                    msg = "Save version"
                finally:
                    try: tp.unlink(missing_ok=True)
                    except: pass
            else:
                msg = "Initial version"
        except Exception:
            msg = "Save version"
        if not msg:
            msg = "Save version"
    # perform save (handles same-file vs copy)
    try:
        # use git_store.save_version for both cases — it handles copy
        # but for same-file we want to avoid double copy; git_store handles it
        h = git_store.save_version(r, Path(src), msg)
        # preview already generated in git_store
        return {"ok": True, "hash": h, "short": h[:8], "message": msg, "repo": str(r)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Save failed: {e}"}

def api_restore(repo: str | Path | None = None, rev: str = "HEAD", apply: bool = False, out: str | Path | None = None) -> dict:
    r = _resolve_repo(repo)
    if not rev:
        return {"ok": False, "error": "No revision given"}
    # numeric alias
    def _alias(rev: str) -> str:
        rev = rev.strip()
        if rev.isdigit():
            n = int(rev)
            vers = git_store.log_versions(r, limit=max(20, n))
            if 0 <= n-1 < len(vers):
                return vers[n-1]["hash"]
        return rev
    rev_resolved = _alias(str(rev))
    try:
        if apply:
            # safety snapshot if has changes
            status = git_store.status(r)
            safety = None
            if status.get("has_changes"):
                try:
                    cur = r / "timeline.otio"
                    if cur.exists():
                        safety = git_store.save_version(r, cur, "Auto safety snapshot before restore")
                except Exception:
                    safety = None
            # backup to .get-syncd/backups
            out_path = r / "timeline.otio"
            if out_path.exists():
                import shutil, datetime
                bdir = r / ".get-syncd" / "backups"
                bdir.mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(str(out_path), str(bdir / f"timeline-{ts}.otio"))
            git_store.restore_version(r, rev_resolved, out_path)
            # try auto-import into Resolve so reopen shows restored version without manual File→Import
            auto_import_ok, auto_import_msg = _try_resolve_import(out_path)
            return {"ok": True, "rev": rev, "resolved": rev_resolved, "out": str(out_path), "applied": True, "safety": safety, "repo": str(r), "auto_import": auto_import_ok, "auto_import_msg": auto_import_msg}
        else:
            out_path = Path(out).expanduser() if out else Path(f"version-{rev}.otio")
            git_store.restore_version(r, rev_resolved, out_path)
            return {"ok": True, "rev": rev, "resolved": rev_resolved, "out": str(out_path.resolve()), "applied": False, "repo": str(r)}
    except Exception as e:
        return {"ok": False, "error": str(e), "repo": str(r)}

def api_branches(repo: str | Path | None = None) -> dict:
    r = _resolve_repo(repo)
    try:
        br = subprocess.run(["git", "branch", "--format=%(refname:short) %(objectname:short) %(upstream:short)", ], cwd=str(r), capture_output=True, text=True)
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(r), capture_output=True, text=True)
        return {"ok": True, "repo": str(r), "branches_raw": br.stdout.strip(), "current": cur.stdout.strip() if cur.returncode==0 else ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def api_create_branch(repo: str | Path | None = None, name: str = "") -> dict:
    r = _resolve_repo(repo)
    if not name or not name.strip():
        return {"ok": False, "error": "Branch name required"}
    name = name.strip()
    # if branch exists, just switch; otherwise create
    try:
        existing = subprocess.run(["git", "branch", "--list", name], cwd=str(r), capture_output=True, text=True)
        if existing.stdout.strip():
            subprocess.run(["git", "checkout", name], cwd=str(r), check=True, capture_output=True, text=True)
            return {"ok": True, "branch": name, "repo": str(r), "switched": True}
        subprocess.run(["git", "checkout", "-b", name], cwd=str(r), check=True, capture_output=True, text=True)
        return {"ok": True, "branch": name, "repo": str(r), "created": True}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": e.stderr.strip() if e.stderr else str(e)}

def api_list_projects() -> dict:
    """List all Get Syncd projects (subfolders of ~/GetSyncd that are git repos)."""
    base = DEFAULT_REPO
    base.mkdir(parents=True, exist_ok=True)
    if not base.exists():
        return {"ok": True, "projects": []}
    projects = []
    # include base itself if it's a repo (the default single-project case) and not hidden
    if (base / ".git").exists():
        projects.append({"name": base.name, "path": str(base), "is_base": True})
    for p in base.iterdir():
        if p.name.startswith("."):
            continue
        if p.is_dir() and (p / ".git").exists():
            projects.append({"name": p.name, "path": str(p), "is_base": False})
    return {"ok": True, "projects": sorted(projects, key=lambda x: (not x["is_base"], x["name"]))}

def api_scan_resolve_projects() -> dict:
    """Ask DaVinci Resolve for project list and auto-create folders."""
    base = DEFAULT_REPO
    base.mkdir(parents=True, exist_ok=True)
    resolve = None
    try:
        for pp in [
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
            str(Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
        ]:
            if pp not in __import__("sys").path and Path(pp).exists():
                __import__("sys").path.append(pp)
        import DaVinciResolveScript as bmd  # type: ignore
        resolve = bmd.scriptapp("Resolve")
    except Exception as e:
        existing = api_list_projects()
        return {"ok": False, "error": f"Resolve not running or External scripting not enabled. Open Resolve with a project, enable Preferences → System → General → External scripting: Local, then try again. ({e})", "projects": [], "folders": existing.get("projects", [])}
    if not resolve:
        existing = api_list_projects()
        return {"ok": False, "error": "Could not connect to Resolve — is it running?", "projects": [], "folders": existing.get("projects", [])}
    try:
        pm = resolve.GetProjectManager()
        if not pm:
            existing = api_list_projects()
            return {"ok": False, "error": "Resolve: No ProjectManager — is Resolve running with a project open?", "projects": [], "folders": existing.get("projects", [])}
        # try Root folder, fallback to empty folder — handle API variations
        names = None
        for folder_arg in ["Root", "", None]:
            try:
                meth = getattr(pm, "GetProjectListInFolder", None)
                if meth and callable(meth):
                    if folder_arg is None:
                        names = meth()
                    else:
                        names = meth(folder_arg)
                else:
                    names = None
            except Exception:
                names = None
            if names:
                break
        if not names:
            # try current project name as fallback
            try:
                cur = pm.GetCurrentProject()
                if cur and hasattr(cur, "GetName"):
                    n = cur.GetName()
                    if n:
                        names = [n]
            except Exception:
                pass
        if not names:
            names = []
        created = []
        for raw in names:
            name = str(raw).strip()
            if not name:
                continue
            # sanitize folder name
            safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name).strip()
            if not safe:
                safe = name
            folder = base / safe
            folder.mkdir(parents=True, exist_ok=True)
            if not git_store.is_git_repo(folder):
                git_store.init_repo(folder)
                created.append(safe)
        # also return existing GetSyncd projects
        existing = api_list_projects()
        return {"ok": True, "projects": names, "created": created, "folders": existing.get("projects", [])}
    except Exception as e:
        existing = api_list_projects()
        return {"ok": False, "error": f"Scan failed: {e} — showing existing GetSyncd projects.", "projects": [], "folders": existing.get("projects", [])}

def _try_resolve_import(otio_path: Path) -> tuple[bool, str]:
    """Try to auto-import OTIO into current Resolve project (best-effort)."""
    otio_path = Path(otio_path).resolve()
    if not otio_path.exists():
        return False, f"File not found: {otio_path}"
    resolve = None
    try:
        for pp in [
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
            str(Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
        ]:
            if pp not in __import__("sys").path and Path(pp).exists():
                __import__("sys").path.append(pp)
        import DaVinciResolveScript as bmd  # type: ignore
        resolve = bmd.scriptapp("Resolve")
    except Exception as e:
        return False, f"Resolve API not reachable: {e}"
    if not resolve:
        return False, "Could not connect to Resolve"
    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
        if not project:
            return False, "No project open in Resolve — open a project first"
        # Try several import methods (vary by version)
        # 1) MediaPool.ImportMedia
        try:
            mp = project.GetMediaPool()
            if mp and hasattr(mp, "ImportMedia"):
                # ImportMedia expects list
                res = mp.ImportMedia([str(otio_path)])
                if res:
                    return True, f"Imported via MediaPool.ImportMedia → {otio_path.name}"
        except Exception:
            pass
        # 2) Timeline import via Project
        for meth in ["ImportTimeline", "LoadTimeline", "ImportOTIO"]:
            if hasattr(project, meth):
                try:
                    ok = getattr(project, meth)(str(otio_path))
                    if ok:
                        return True, f"Imported via Project.{meth}"
                except Exception:
                    continue
        # 3) Try Fusion? fallback
        return False, "Auto-import not available in this Resolve version — use File → Import Timeline → OpenTimelineIO → timeline.otio"
    except Exception as e:
        return False, f"Import error: {e}"
