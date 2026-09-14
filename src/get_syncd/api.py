"""Get Syncd — Pure JSON API layer for Tauri/React sidecar.

No Rich, no sys.exit, no input() — just data. CLI and Tauri both call these.
Preserves core: Resolve → OTIO → git → GitHub, media stays local.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from . import git_store
from .otio_parse import parse_otio_file
from .diff import diff_timelines, changelog_line
from .preview import generate_preview, _preview_path
from .resolve_state import (
    DEFAULT_REPO,
    _CURRENT_RESOLVE_CACHE,
    _get_resolve_timelines,
    _load_known_timelines,
    _read_current_resolve_state,
    _save_known_timelines,
    _known_timelines_file,
    ensure_resolve_scripting_path,
)
from .timeline_files import _sanitize_timeline_name, _list_timeline_files
from .otio_parse import warmup_otio
import logging

log = logging.getLogger(__name__)

# Backward-compatible re-exports (api.* callers keep working)
__all__ = ["DEFAULT_REPO"]


def is_repo_allowed(repo: str | Path | None) -> bool:
    """Trust boundary: only ~/GetSyncd and its subfolders are servable."""
    try:
        if not repo:
            return True  # resolves to DEFAULT_REPO itself
        base = DEFAULT_REPO.resolve()
        p = Path(repo).expanduser().resolve()
        return p == base or base in p.parents
    except Exception:
        return False


def _require_allowed_repo(repo: Path) -> dict | None:
    """Enforce the trust boundary at the api.* layer (not just the HTTP layer),
    so direct/CLI/embedded callers can't mkdir/commit/restore outside ~/GetSyncd.
    Returns an error dict when rejected, else None."""
    if not is_repo_allowed(repo):
        return {"ok": False, "error": "Repo outside ~/GetSyncd not allowed", "repo": str(repo)}
    return None


def api_get_current_resolve() -> dict:
    """Read-only current Resolve project info for UI hints. Never switches projects."""
    try:
        project_name, current, all_names = _read_current_resolve_state()
        return {"ok": True, "project": project_name, "current_timeline": current, "timelines": all_names}
    except Exception as e:
        log.warning("api_get_current_resolve failed: %s", e)
        return {"ok": False, "error": str(e), "project": None, "current_timeline": None, "timelines": []}


def api_sync_resolve(repo: str | Path | None = None) -> dict:
    """Explicit user action: snapshot the currently open Resolve project into repo's cache.

    Only writes when the open Resolve project name matches the repo folder name,
    preventing cross-project pollution. Call from a 'Sync from Resolve' button,
    never from background polling.
    """
    try:
        r = _resolve_repo(repo)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not is_repo_allowed(r):
        return {"ok": False, "error": "Repo outside ~/GetSyncd not allowed"}
    # Bypass TTL — user explicitly asked for fresh state
    _CURRENT_RESOLVE_CACHE["t"] = 0.0
    project_name, current, all_names = _read_current_resolve_state()
    if not project_name or not all_names:
        return {"ok": False, "error": "No project open in Resolve — open a project first", "repo": str(r)}
    if project_name != r.name:
        return {
            "ok": False,
            "error": f"Open project is '{project_name}' but folder is '{r.name}' — open '{r.name}' in Resolve first",
            "repo": str(r),
            "resolve_project": project_name,
        }
    _save_known_timelines(r, current, all_names)
    return {"ok": True, "repo": str(r), "current": current, "timelines": all_names}

def _get_timeline_file(repo: Path, timeline_name: str | None) -> Path:
    """Resolve file for a timeline. Uses timelines/<safe>.otio if timelines/ exists or name given, else legacy timeline.otio."""
    timelines_dir = repo / "timelines"
    has_timelines = timelines_dir.exists() and any(timelines_dir.glob("*.otio"))
    legacy_exists = (repo / "timeline.otio").exists()
    if timeline_name:
        safe = _sanitize_timeline_name(timeline_name)
        # If legacy exists and no timelines yet, check if this timeline's file exists
        # For current timeline, legacy file may be the correct one
        if not has_timelines and legacy_exists:
            # Check if timelines/<name>.otio exists - if so, use it
            candidate = timelines_dir / f"{safe}.otio"
            if candidate.exists():
                return candidate
            # Check if timeline_name is the current timeline - then use legacy
            try:
                cur, _ = _get_resolve_timelines(repo)
                if timeline_name == cur or timeline_name == "timeline":
                    # Also check if legacy file is newer than any timelines file (for migration)
                    return repo / "timeline.otio"
            except Exception:
                pass
            # For other timelines, use timelines/<name>.otio (will be empty until exported)
            return timelines_dir / f"{safe}.otio"
        if timelines_dir.exists() or timeline_name != "timeline":
            # If timelines folder exists, use it; also for any named timeline
            # But check if legacy exists and this timeline's file doesn't - for current, use legacy
            candidate = timelines_dir / f"{safe}.otio"
            if not has_timelines and legacy_exists and not candidate.exists():
                try:
                    cur, _ = _get_resolve_timelines(repo)
                    if timeline_name == cur:
                        return repo / "timeline.otio"
                except Exception:
                    pass
            return timelines_dir / f"{safe}.otio"
    # Legacy fallback: check timelines folder for existing file
    if timelines_dir.exists():
        if timeline_name:
            candidate = timelines_dir / f"{_sanitize_timeline_name(timeline_name)}.otio"
            if candidate.exists():
                return candidate
        if legacy_exists and not has_timelines:
            return repo / "timeline.otio"
        if timeline_name:
            return timelines_dir / f"{_sanitize_timeline_name(timeline_name)}.otio"
    return repo / "timeline.otio"

def _resolve_repo(repo: str | Path | None) -> Path:
    if not repo:
        return DEFAULT_REPO
    p = Path(repo).expanduser()
    # if passed repo is file, use parent
    if p.is_file():
        p = p.parent
    return p.resolve()

def _rel(repo: Path, p: Path | str) -> str:
    """Repo-relative path in git's forward-slash form for JSON/git use.

    str(Path.relative_to) yields backslashes on Windows, which git treats as
    escape characters and which never match `git show --name-only` output —
    normalize once here (see git_store._posix_pathspec).
    """
    try:
        q = Path(p)
        if q.is_relative_to(repo):
            return git_store._posix_pathspec(q.relative_to(repo))
    except Exception:
        pass
    try:
        return git_store._posix_pathspec(p)
    except Exception:
        return str(p)


def _alias_versions(repo: Path, tfile: str | None, limit: int) -> list[dict]:
    """History for numeric (1 = latest) alias resolution.

    Strictly scoped to the timeline's file, matching exactly what the History
    list shows: no all-commits fallback, so "1" in an untouched timeline
    resolves to nothing instead of another timeline's version.
    """
    if tfile:
        return git_store.log_versions(repo, limit=limit, timeline_file=tfile, fallback=False)
    return git_store.log_versions(repo, limit=limit, timeline_file=None)

def api_init(repo: str | Path | None = None, remote: str | None = None) -> dict:
    r = _resolve_repo(repo)
    denied = _require_allowed_repo(r)
    if denied:
        return denied
    r.mkdir(parents=True, exist_ok=True)
    git_store.init_repo(r, remote_url=remote)
    return {"ok": True, "repo": str(r), "remote": remote}


def api_github_status() -> dict:
    """Best-effort GitHub CLI check for the first-run wizard. Never raises."""
    import shutil

    gh = shutil.which("gh")
    if not gh:
        return {
            "ok": False,
            "has_gh": False,
            "authed": False,
            "error": "GitHub CLI (gh) not installed — see https://cli.github.com, or skip this step.",
        }
    try:
        r = subprocess.run(
            [gh, "auth", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if r.returncode == 0:
            return {"ok": True, "has_gh": True, "authed": True}
        return {
            "ok": False,
            "has_gh": True,
            "authed": False,
            "error": "gh is installed but not logged in — run `gh auth login`, or skip this step.",
        }
    except Exception as e:
        log.warning("gh auth status failed: %s", e)
        return {"ok": False, "has_gh": True, "authed": False, "error": f"Could not check gh auth: {e}"}


def api_github_create(
    repo: str | Path | None = None,
    name: str = "",
    private: bool = True,
    description: str = "",
) -> dict:
    """Create a GitHub repo for a project and push (best-effort, via `gh`).

    Requires the `gh` CLI installed and authed. Safe to call from the wizard;
    failures return {ok: False} with a human message, never raise.
    """
    import re
    import shutil

    name = (name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
        return {"ok": False, "error": "Repo name may only contain letters, numbers, . _ - (max 100 chars)."}
    try:
        r = _resolve_repo(repo)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not is_repo_allowed(r):
        return {"ok": False, "error": "Repo outside ~/GetSyncd not allowed"}
    if not git_store.is_git_repo(r):
        return {"ok": False, "error": "Not a git repo yet — create the project first."}
    gh = shutil.which("gh")
    if not gh:
        return {"ok": False, "error": "GitHub CLI (gh) not installed — see https://cli.github.com."}
    args = [gh, "repo", "create", name, "--private" if private else "--public",
            "--source", str(r), "--push"]
    if description.strip():
        args += ["--description", description.strip()[:350]]
    try:
        p = subprocess.run(
            args,
            cwd=str(r),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "gh timed out — check your network and retry."}
    except Exception as e:
        log.warning("gh repo create failed: %s", e)
        return {"ok": False, "error": f"Could not run gh: {e}"}
    if p.returncode != 0:
        err = (p.stderr or p.stdout or "unknown error").strip().splitlines()
        return {"ok": False, "error": "; ".join(err[-3:])[:500]}
    url = ""
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("https://github.com/"):
            url = line
            break
    return {"ok": True, "repo": str(r), "name": name, "url": url, "private": private}

def api_status(repo: str | Path | None = None) -> dict:
    r = _resolve_repo(repo)
    # Per-timeline status
    files = _list_timeline_files(r)
    # If no files yet, check for legacy or empty
    if not files:
        # Check if repo has timelines folder with no files yet
        timelines_dir = r / "timelines"
        if timelines_dir.exists():
            files = []
        else:
            # Fallback to legacy check for has_changes
            res = git_store.status(r)
            timelines = []
            cur, all_names = _get_resolve_timelines(r)
            return {
                "repo": str(r),
                "is_repo": res.get("is_repo"),
                "has_changes": res.get("has_changes"),
                "message": res.get("message"),
                "stat": res.get("stat", ""),
                "branches": [],
                "current_branch": "",
                "timelines": timelines,
                "current_timeline": cur,
                "all_timelines": all_names,
            }
    # Get per-file status
    timelines_status = []
    any_has_changes = False
    overall_msg = "All changes saved — you're up to date."
    overall_stat = ""
    cur, all_names = _get_resolve_timelines(r)
    # For legacy single-file repos with many Resolve timelines, keep all names
    # The current one's file is timeline.otio, others are not yet exported
    timelines_dir = r / "timelines"
    fs_names = []
    for f in files:
        try:
            name = f.stem
            if f.name == "timeline.otio":
                # For legacy, use current name if available
                if len(all_names) > 1 and cur:
                    name = cur
                else:
                    name = "timeline"
            fs_names.append(name)
        except Exception:
            pass
    combined_names = list(dict.fromkeys(all_names + fs_names))
    if not combined_names and files:
        combined_names = [f.stem if f.name != "timeline.otio" else "timeline" for f in files]
    for name in combined_names:
        tf = _get_timeline_file(r, name if name != "timeline" else None)
        # For legacy, use git_store.status with specific file
        rel = _rel(r, tf)
        if not tf.exists():
            # No working file: either never exported (not a change) or deleted
            # (real change). Never fall back to another timeline's file here —
            # an untouched timeline must not report other timelines' activity.
            hist = git_store._run_git(["log", "--all", "--", rel], cwd=r, check=False)
            if not hist.stdout.strip():
                timelines_status.append({
                    "name": name,
                    "file": rel,
                    "has_changes": None,
                    "message": "Not yet exported",
                    "stat": "",
                })
                continue
            any_has_changes = True
            overall_msg = f"'{name}' was deleted from the folder"
            timelines_status.append({
                "name": name,
                "file": rel,
                "has_changes": True,
                "message": f"'{rel}' is missing — restore a version to bring it back",
                "stat": "",
            })
            continue
        res = git_store.status(r, timeline_file=rel)
        has = res.get("has_changes")
        if has is True:
            any_has_changes = True
            overall_msg = f"'{name}' has unsaved changes"
            overall_stat = res.get("stat", "")
        timelines_status.append({
            "name": name,
            "file": rel,
            "has_changes": has,
            "message": res.get("message", ""),
            "stat": res.get("stat", ""),
        })
    # Overall has_changes is true if any timeline has changes
    # Also check legacy status for overall message if no timelines
    if not timelines_status:
        res = git_store.status(r)
        timelines_status = []
        overall_msg = res.get("message", "")
        overall_stat = res.get("stat", "")
        any_has_changes = res.get("has_changes") is True
    else:
        # If none have changes, overall is false
        if not any_has_changes:
            # Check if any file is missing but should exist
            pass
    # Stray legacy file: once migrated to timelines/*.otio, the root
    # timeline.otio is legacy storage shadowed by every pill — a misdirected
    # export landing there would otherwise be invisible. Surface it loudly.
    notice = None
    try:
        migrated = timelines_dir.exists() and any(timelines_dir.glob("*.otio"))
        legacy = r / "timeline.otio"
        if migrated and legacy.exists():
            st_leg = git_store.status(r, timeline_file="timeline.otio")
            if st_leg.get("has_changes") is True:
                where = f"timelines/{_sanitize_timeline_name(cur)}.otio" if cur else "timelines/<name>.otio"
                notice = (
                    f"timeline.otio in the project root has unsaved changes — "
                    f"it is legacy storage, so no timeline button shows it. "
                    f"Exports belong in {where}: re-export the current timeline there, then Save."
                )
                any_has_changes = True
                overall_msg = "Root timeline.otio has unsaved changes"
                overall_stat = st_leg.get("stat", "")
    except Exception as e:
        log.warning("stray legacy check failed for %s: %s", r, e)
    branches = []
    cur_branch = ""
    try:
        br = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if br.returncode == 0:
            branches = [l.strip() for l in br.stdout.splitlines() if l.strip()]
        cur_r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
        cur_branch = cur_r.stdout.strip() if cur_r.returncode == 0 else ""
    except Exception:
        pass
    # Overall has_changes logic
    has_changes_overall = any_has_changes
    # If no timelines but legacy has changes, use that
    if not timelines_status:
        has_changes_overall = None
    return {
        "repo": str(r),
        "is_repo": True if (r / ".git").exists() else False,
        "has_changes": has_changes_overall,
        "message": overall_msg,
        "notice": notice,
        "stat": overall_stat,
        "branches": branches,
        "current_branch": cur_branch,
        "timelines": timelines_status,
        "current_timeline": cur,
        "all_timelines": all_names or combined_names,
    }

def api_timelines(repo: str | Path | None = None) -> dict:
    r = _resolve_repo(repo)
    cur, all_names = _get_resolve_timelines(r)
    files = _list_timeline_files(r)
    # For legacy single-file repos with many Resolve timelines, we still list all timelines
    # The current one's file is timeline.otio, others are not yet exported
    timelines_dir = r / "timelines"
    # Don't limit all_names - keep all 7
    # Build timeline list with status
    timelines = []
    for f in files:
        rel = _rel(r, f)
        name = f.stem if f.name != "timeline.otio" else (cur or "timeline")
        # If legacy file and we have a current, use current name
        if f.name == "timeline.otio" and cur and len(all_names) > 1:
            name = cur
            # Once migrated, timelines/<current>.otio is the live file — listing
            # the legacy file too would show the same timeline twice.
            if (timelines_dir / f"{_sanitize_timeline_name(cur)}.otio").exists():
                continue
        st = git_store.status(r, timeline_file=rel)
        timelines.append({"name": name, "file": rel, "has_changes": st.get("has_changes"), "message": st.get("message", "")})
    # Add Resolve timelines not yet exported
    for name in all_names:
        safe = _sanitize_timeline_name(name)
        found = any(t["name"] == name or t["name"] == safe for t in timelines)
        if not found:
            timelines.append({"name": name, "file": f"timelines/{safe}.otio", "has_changes": None, "message": "Not yet exported"})
    return {"ok": True, "repo": str(r), "current": cur, "timelines": timelines, "all_names": all_names}

def api_log(repo: str | Path | None = None, limit: int = 20, timeline: str | None = None) -> list[dict]:
    r = _resolve_repo(repo)
    # Guard: non-existent or non-repo returns empty (strict per-repo isolation, no cross-project fallback)
    try:
        if not r.exists() or not git_store.is_git_repo(r):
            return []
    except Exception:
        return []
    # Determine timeline file for log
    if timeline:
        # Per-timeline view: STRICTLY this timeline's file. Legacy
        # timeline.otio saves live in the All view only — mixing them into
        # every pill made untouched timelines show other timelines' saves.
        # (When the repo hasn't migrated, _get_timeline_file already resolves
        # to timeline.otio, so single-file projects keep working unchanged.)
        try:
            tf = _get_timeline_file(r, timeline)
            rel = _rel(r, tf)
        except Exception:
            return []
        versions = git_store.log_versions(r, limit=limit, timeline_file=rel, fallback=False)
        out = []
        for v in versions:
            files = git_store.commit_otio_files(r, v["hash"])
            p = _preview_path(r, v["hash"])
            out.append({
                **v,
                "preview": str(p) if p.exists() else None,
                "timeline": timeline,
                "file": files[0] if files else rel,
                "legacy": False,
            })
        return out
    else:
        # No timeline filter (All view): every commit in this repo, newest-first.
        # Strictly per-repo, never across projects. Each version carries the
        # timeline it was saved for (when attributable) so nothing is hidden.
        versions = git_store.log_versions(r, limit=limit, timeline_file=None)
    # enrich with preview path
    out = []
    for v in versions:
        files = git_store.commit_otio_files(r, v["hash"])
        tl = None
        for f in files:
            if f.startswith("timelines/") and f.lower().endswith(".otio"):
                tl = Path(f).stem
                break
        is_legacy = bool(files) and all(f == "timeline.otio" for f in files)
        p = _preview_path(r, v["hash"])
        out.append({
            **v,
            "preview": str(p) if p.exists() else None,
            "timeline": tl,
            "file": files[0] if files else None,
            "legacy": is_legacy,
        })
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

def api_diff(repo: str | Path | None = None, a: str = "HEAD~1", b: str = "HEAD", timeline: str | None = None) -> dict:
    r = _resolve_repo(repo)
    # Determine timeline file for diff aliases
    tfile = None
    if timeline:
        tf = _get_timeline_file(r, timeline)
        tfile = _rel(r, tf)
    # resolve numeric aliases via cli helper logic (duplicate to avoid cli import)
    def _alias(rev: str) -> str:
        rev = rev.strip()
        if rev.isdigit():
            n = int(rev)
            vers = _alias_versions(r, tfile, max(20, n))
            if 0 <= n-1 < len(vers):
                return vers[n-1]["hash"]
        return rev
    a2 = _alias(a)
    b2 = _alias(b)
    # First-save mode: `a` empty (or same as `b`) means "compare against an
    # empty timeline" — a first save has no previous version, so the view shows
    # everything in it as added instead of a meaningless self-comparison.
    first_save = (a2 == b2) or (a or "").strip().lower() in ("", "empty", "none", "null")
    # materialize
    def _rev_to_file(rev: str) -> Path:
        p = Path(rev)
        if p.exists() and p.is_file():
            return p
        tmp = tempfile.NamedTemporaryFile(suffix=".otio", delete=False)
        tp = Path(tmp.name); tmp.close()
        try:
            if tfile:
                git_store.restore_version(r, rev, tp, timeline_file=tfile)
            else:
                git_store.restore_version(r, rev, tp)
        except Exception:
            # Fallback to legacy timeline.otio if timeline-specific file not found
            try:
                if tfile and tfile != "timeline.otio":
                    git_store.restore_version(r, rev, tp, timeline_file="timeline.otio")
                else:
                    raise
            except Exception as e2:
                # If both fail, try without timeline file (any)
                try:
                    git_store.restore_version(r, rev, tp)
                except Exception:
                    raise e2
        return tp
    pa = None
    pb = None
    try:
        from .otio_parse import NormalizedTimeline
        from .diff import format_text
        if first_save:
            old = NormalizedTimeline(name="Empty", tracks=[])
            pb = _rev_to_file(b2)
            new = parse_otio_file(pb)
        else:
            pa = _rev_to_file(a2)
            pb = _rev_to_file(b2)
            old = parse_otio_file(pa)
            new = parse_otio_file(pb)
        d = diff_timelines(old, new)
        # build viewer data for React bar (scoped to this timeline's file so
        # per-timeline bars work; guarded so a viewer failure never kills the diff)
        from .viewer.app import build_viewer_data
        try:
            vd = build_viewer_data(r, b2 if first_save else a2, b2, tfile or "timeline.otio")
        except Exception as ve:
            log.warning("viewer data failed for %s (timeline %s): %s", r, timeline, ve)
            vd = {}
        if first_save:
            vd = {**vd, "text_log": format_text(d, old_name="empty timeline", new_name=b2)}
        return {
            "repo": str(r),
            "a": a, "b": b,
            "a_resolved": a2, "b_resolved": b2,
            "is_first_save": first_save,
            "summary": d.summary,
            "changes": [c.to_dict() for c in d.changes],
            "warnings": d.warnings,
            "tracks_compared": d.tracks_compared,
            "changelog": changelog_line(d),
            "new_track": vd.get("new_track"),
            "text_log": vd.get("text_log"),
        }
    except Exception as e:
        # Graceful fallback: return empty diff instead of 500
        import traceback as _tb
        tb = _tb.format_exc()
        log.warning("api_diff failed for %s %s->%s timeline %s: %s\n%s", r, a, b, timeline, e, tb)
        return {
            "repo": str(r),
            "a": a, "b": b,
            "a_resolved": a2, "b_resolved": b2,
            "is_first_save": first_save,
            "summary": {"added":0,"removed":0,"trimmed":0,"reordered":0,"total_changes":0,"old_duration_s":0,"new_duration_s":0,"runtime_delta_s":0},
            "changes": [],
            "warnings": [f"Diff not available for timeline '{timeline}' — {e}"],
            "tracks_compared": [],
            "changelog": "No diff",
            "new_track": None,
            "text_log": "",
        }
    finally:
        for p in (pa, pb):
            try:
                if p is not None and p.exists() and p.suffix == ".otio" and "/tmp" in str(p):
                    p.unlink(missing_ok=True)
            except Exception:
                pass

def api_save(repo: str | Path | None = None, file: str | Path | None = None, message: str | None = None, timeline: str | None = None, all_timelines: bool = False) -> dict:
    r = _resolve_repo(repo)
    denied = _require_allowed_repo(r)
    if denied:
        return denied
    if not r.exists():
        r.mkdir(parents=True, exist_ok=True)
    # If all_timelines, save every dirty timeline
    if all_timelines:
        cur, all_names = _get_resolve_timelines(r)
        targets = []
        for name in all_names:
            tf = _get_timeline_file(r, name)
            # Check if file exists in repo or in Resolve export location
            if (r / "timelines" / f"{_sanitize_timeline_name(name)}.otio").exists() or tf.exists():
                targets.append((name, tf))
        # Also check filesystem for dirty files not in Resolve list
        for f in _list_timeline_files(r):
            name = f.stem if f.name != "timeline.otio" else "timeline"
            if not any(n == name for n, _ in targets):
                targets.append((name, f))
        if not targets:
            return {"ok": False, "error": "No timelines found to save"}
        results = []
        for name, tf in targets:
            # Find source for this timeline - try to export or find candidate
            src = None
            if file and Path(file).exists():
                src = Path(file)
            else:
                # Try candidate for this specific timeline
                cand = tf
                if cand.exists():
                    src = cand
                else:
                    # Try find_timeline_candidate but filter for this name
                    cand2 = git_store.find_timeline_candidate(r)
                    if cand2 and _sanitize_timeline_name(name) in str(cand2):
                        src = cand2
            if src and src.exists():
                try:
                    h = git_store.save_version(r, src, message or f"Save {name}", timeline_dest=_rel(r, tf))
                    results.append({"timeline": name, "ok": True, "hash": h})
                except Exception as e:
                    results.append({"timeline": name, "ok": False, "error": str(e)})
        # Return overall
        ok_any = any(x["ok"] for x in results)
        return {"ok": ok_any, "repo": str(r), "results": results}
    # Single timeline save
    # Determine timeline name
    tname = timeline
    if not tname and not file:
        cur, _ = _get_resolve_timelines(repo)
        if cur:
            tname = cur
    # discovery — safe, excludes .get-syncd via git_store helper
    src = None
    if file:
        src = Path(file).expanduser()
    else:
        # Try timeline-specific candidate
        if tname:
            tf = _get_timeline_file(r, tname)
            if tf.exists():
                src = tf
            else:
                # Try to find any candidate and use its name
                cand = git_store.find_timeline_candidate(r)
                if cand and cand.exists():
                    src = cand
                    try:
                        # Infer timeline name from candidate if not given
                        if not tname and cand.parent.name == "timelines":
                            tname = cand.stem
                    except Exception:
                        pass
                else:
                    return {"ok": False, "error": f"No file for timeline '{tname}' — export from Resolve first: File → Export Timeline → OpenTimelineIO → timelines/{_sanitize_timeline_name(tname)}.otio"}
        else:
            cand = git_store.find_timeline_candidate(r)
            if cand and cand.exists():
                src = cand
                try:
                    rel = cand.relative_to(r)
                    if str(rel) != "timeline.otio":
                        print(f"[get-syncd] Using discovered timeline: {rel} (canonical is timeline.otio)")
                except Exception:
                    pass
            else:
                hint = f"timelines/{_sanitize_timeline_name(tname)}.otio" if tname else "timelines/<name>.otio"
                return {"ok": False, "error": f"No export found — export from Resolve first: File → Export Timeline → OpenTimelineIO → {hint} inside the project folder"}
    if not src or not Path(src).exists():
        return {"ok": False, "error": f"File not found: {src}"}
    # auto message if none
    msg = message
    # Determine dest for this save
    dest = None
    if tname:
        dest = _get_timeline_file(r, tname)
        dest_rel = _rel(r, dest)
    else:
        # Infer dest from src if it's in timelines/
        try:
            if src and Path(src).is_relative_to(r / "timelines"):
                dest = Path(src)
                dest_rel = _rel(r, dest)
                tname = dest.stem
            elif src and Path(src).name == "timeline.otio":
                dest = r / "timeline.otio"
                dest_rel = "timeline.otio"
            else:
                dest = r / "timeline.otio"
                dest_rel = "timeline.otio"
        except Exception:
            dest = r / "timeline.otio"
            dest_rel = "timeline.otio"
    if not msg:
        try:
            if git_store.is_git_repo(r) and dest and dest.exists():
                # diff vs HEAD for this specific file
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                    tp = Path(tmp.name)
                try:
                    git_store.restore_version(r, "HEAD", tp, timeline_file=dest_rel)
                    old = parse_otio_file(tp)
                    new = parse_otio_file(Path(src))
                    d = diff_timelines(old, new)
                    msg = changelog_line(d)
                    if tname and tname != "timeline":
                        msg = f"{tname}: {msg}"
                except Exception:
                    msg = f"Save {tname}" if tname and tname != "timeline" else "Save version"
                finally:
                    try: tp.unlink(missing_ok=True)
                    except: pass
            else:
                msg = f"Initial {tname}" if tname and tname != "timeline" else "Initial version"
        except Exception:
            msg = f"Save {tname}" if tname else "Save version"
        if not msg:
            msg = f"Save {tname}" if tname else "Save version"
    # perform save (handles same-file vs copy)
    try:
        h = git_store.save_version(r, Path(src), msg, timeline_dest=dest_rel)
        return {"ok": True, "hash": h, "short": h[:8], "message": msg, "repo": str(r), "timeline": tname, "file": dest_rel}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Save failed: {e}"}

def api_restore(repo: str | Path | None = None, rev: str = "HEAD", apply: bool = False, out: str | Path | None = None, timeline: str | None = None) -> dict:
    r = _resolve_repo(repo)
    denied = _require_allowed_repo(r)
    if denied:
        return denied
    if not rev:
        return {"ok": False, "error": "No revision given"}
    # Determine timeline file for restore
    tf = None
    tname = timeline
    if not tname:
        cur, _ = _get_resolve_timelines(repo)
        if cur:
            tname = cur
    if tname:
        tf = _get_timeline_file(r, tname)
        tfile = _rel(r, tf)
    else:
        # Try to infer from rev's file
        tfile = "timeline.otio"
        # Check if rev touches timelines/ file
        try:
            show = git_store._run_git(["show", "--name-only", "--pretty=format:", rev_resolved if 'rev_resolved' in locals() else rev], cwd=r, check=False)
            for line in show.stdout.splitlines():
                if line.strip().endswith(".otio"):
                    tfile = line.strip()
                    break
        except Exception:
            pass
    # numeric alias
    def _alias(rv: str) -> str:
        rv = rv.strip()
        if rv.isdigit():
            n = int(rv)
            # Use timeline-specific log if we have it
            try:
                vers = _alias_versions(r, tfile, max(20, n))
            except Exception:
                vers = git_store.log_versions(r, limit=max(20, n), timeline_file=None)
            if 0 <= n-1 < len(vers):
                return vers[n-1]["hash"]
        return rv
    rev_resolved = _alias(str(rev))
    # Legacy single-file versions (timeline.otio) predate per-timeline files and
    # are listed under every timeline filter — fall back to them when the
    # timeline-specific file is not in the requested revision (mirrors api_diff).
    candidate_files = [tfile] if tfile == "timeline.otio" else [tfile, "timeline.otio"]

    def _restore_to(out_path: Path) -> str:
        last_err: Exception | None = None
        for cand in candidate_files:
            try:
                git_store.restore_version(r, rev_resolved, out_path, timeline_file=cand)
                return cand
            except Exception as e:
                last_err = e
                continue
        raise last_err if last_err else ValueError(f"Version not found: {rev}")

    try:
        if apply:
            # safety snapshot if has changes for this timeline
            try:
                st = git_store.status(r, timeline_file=tfile)
                has = st.get("has_changes")
            except Exception:
                has = False
                st = {}
            safety = None
            if has:
                try:
                    cur_path = r / tfile
                    if cur_path.exists():
                        safety = git_store.save_version(r, cur_path, "Auto safety snapshot before restore", timeline_dest=tfile)
                except Exception:
                    safety = None
            # backup to .get-syncd/backups
            out_path = r / tfile
            if out_path.exists():
                import shutil, datetime
                bdir = r / ".get-syncd" / "backups"
                bdir.mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                safe_name = Path(tfile).stem
                shutil.copy2(str(out_path), str(bdir / f"{safe_name}-{ts}.otio"))
            restored_from = _restore_to(out_path)
            auto_import_ok, auto_import_msg = _try_resolve_import(out_path)
            return {"ok": True, "rev": rev, "resolved": rev_resolved, "out": str(out_path), "applied": True, "safety": safety, "repo": str(r), "timeline": tname, "file": tfile, "restored_from": restored_from, "auto_import": auto_import_ok, "auto_import_msg": auto_import_msg}
        else:
            out_path = Path(out).expanduser() if out else Path(f"version-{rev}.otio")
            restored_from = _restore_to(out_path)
            return {"ok": True, "rev": rev, "resolved": rev_resolved, "out": str(out_path.resolve()), "applied": False, "repo": str(r), "timeline": tname, "file": tfile, "restored_from": restored_from}
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
    denied = _require_allowed_repo(r)
    if denied:
        return denied
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


def api_delete_branch(repo: str | Path | None = None, name: str = "", force: bool = False) -> dict:
    r = _resolve_repo(repo)
    denied = _require_allowed_repo(r)
    if denied:
        return denied
    if not name or not name.strip():
        return {"ok": False, "error": "Branch name required"}
    name = name.strip()
    # Safety: prevent deleting main/master without force, and current branch
    try:
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(r), capture_output=True, text=True)
        current = cur.stdout.strip() if cur.returncode == 0 else ""
        if name == current:
            return {"ok": False, "error": f"Cannot delete current branch '{name}' — switch to another branch first."}
        if name in ("main", "master") and not force:
            return {"ok": False, "error": f"Deleting '{name}' is destructive. Tick force to confirm."}
        # Check exists
        ex = subprocess.run(["git", "branch", "--list", name], cwd=str(r), capture_output=True, text=True)
        if not ex.stdout.strip():
            return {"ok": False, "error": f"Branch '{name}' not found."}
        # Try safe delete first
        flag = "-D" if force else "-d"
        res = subprocess.run(["git", "branch", flag, name], cwd=str(r), capture_output=True, text=True)
        if res.returncode != 0:
            # If safe delete failed due to not merged, suggest force
            if not force and "not fully merged" in res.stderr:
                return {"ok": False, "error": f"Branch '{name}' not fully merged — tick force to delete anyway. ({res.stderr.strip()})"}
            return {"ok": False, "error": res.stderr.strip() or f"Failed to delete '{name}'"}
        return {"ok": True, "branch": name, "repo": str(r), "force": force}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def api_push(repo: str | Path | None = None, remote: str = "origin", branch: str | None = None) -> dict:
    """Push this project's versions to GitHub (or any git remote).

    Never hangs waiting for credentials: GIT_TERMINAL_PROMPT=0 plus a 90s
    timeout. Missing remotes/upstream produce actionable errors, not tracebacks.
    """
    r = _resolve_repo(repo)
    denied = _require_allowed_repo(r)
    if denied:
        return denied
    if not git_store.is_git_repo(r):
        return {"ok": False, "error": "Not a Get Syncd project yet — create it first.", "repo": str(r)}
    try:
        if branch is None:
            br = git_store._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=r, check=False)
            branch = br.stdout.strip() or "main"
            if branch == "HEAD":
                branch = "main"
    except Exception:
        branch = branch or "main"
    try:
        rems = git_store._run_git(["remote"], cwd=r, check=False)
    except Exception:
        rems = None
    if not rems or not rems.stdout.strip():
        return {
            "ok": False, "repo": str(r),
            "error": "No GitHub remote connected yet — create one (first-run wizard or `gh repo create`), then Sync.",
            "needs_remote": True,
        }
    if remote not in (rems.stdout.split() if rems else []):
        return {"ok": False, "repo": str(r), "error": f"No remote named '{remote}' — connected: {', '.join(rems.stdout.split()) or 'none'}."}
    try:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        p = subprocess.run(
            ["git", "push", remote, branch], cwd=str(r), capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=90, env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "repo": str(r), "error": "Push timed out after 90s — check your network and retry."}
    except Exception as e:
        log.warning("push failed for %s: %s", r, e)
        return {"ok": False, "repo": str(r), "error": f"Could not run git push: {e}"}
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode != 0:
        low = out.lower()
        if "authentication failed" in low or "could not read username" in low or "permission denied" in low:
            return {"ok": False, "repo": str(r), "error": "GitHub rejected the push (sign in: `gh auth login`, or use an SSH remote).", "detail": out[-500:]}
        if "no upstream" in low or "has no upstream branch" in low:
            return {"ok": False, "repo": str(r), "error": f"Branch '{branch}' has no upstream — push once with tracking, then Sync.", "detail": out[-500:]}
        return {"ok": False, "repo": str(r), "error": out[-500:] or "Push failed."}
    return {"ok": True, "repo": str(r), "remote": remote, "branch": branch, "output": out[:2000]}


def api_graph_viz(repo: str | Path | None = None, timeline: str | None = None) -> dict:
    """Structured graph for the right rail — single shared ROW_HEIGHT, orange accent logic."""
    r = _resolve_repo(repo)
    if not git_store.is_git_repo(r):
        return {"ok": False, "error": "Not a git repo", "commits": [], "branches": []}
    try:
        # Current branch and all branches
        cur_r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
        current = cur_r.stdout.strip() if cur_r.returncode == 0 else "main"
        br_r = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
        branches = [l.strip() for l in br_r.stdout.splitlines() if l.strip()] if br_r.returncode == 0 else [current]
        # All commits — if timeline filter given, strictly that file's history
        # (same scope as api_log, so graph and list agree)
        if timeline:
            tf = _get_timeline_file(r, timeline)
            tfile = _rel(r, tf)
            log_r = subprocess.run(["git", "log", "--all", "--pretty=format:%H%x1f%P%x1f%D%x1f%s%x1f%ar%x1f%ad", "--date=short", "--reverse", "--", tfile], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
            # Do NOT fallback to all — if timeline has no history, return empty (strict per-timeline filtering)
            if log_r.returncode != 0 or not log_r.stdout.strip():
                return {"ok": True, "repo": str(r), "current": current, "branches": branches, "commits": [], "fork": None}
        else:
            log_r = subprocess.run(["git", "log", "--all", "--pretty=format:%H%x1f%P%x1f%D%x1f%s%x1f%ar%x1f%ad", "--date=short", "--reverse"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
        if log_r.returncode != 0 or not log_r.stdout.strip():
            return {"ok": True, "repo": str(r), "current": current, "branches": branches, "commits": [], "fork": None}
        commits = []
        for line in log_r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\x1f")
            if len(parts) < 5:
                continue
            h, parents, deco, subj, rel, date = (parts + [""]*6)[:6]
            # branches that point at this commit
            at_branches = []
            if deco:
                for d in deco.split(","):
                    d = d.strip()
                    # deco like "HEAD -> main, origin/main" or "Cut B"
                    if "HEAD ->" in d:
                        d = d.split("HEAD ->")[-1].strip()
                    # remove origin/ and tag: prefixes
                    if d.startswith("origin/") or d.startswith("tag:"):
                        continue
                    if d:
                        # first token before space
                        at_branches.append(d.split()[0].split(":")[0])
            commits.append({
                "hash": h, "short": h[:8], "parents": parents.split() if parents else [],
                "branches": at_branches, "message": subj, "relative": rel, "date": date,
            })
        # Reverse to newest first for UI (like log)
        commits = list(reversed(commits))
        # Find fork point: common ancestor of all branches (use main if exists)
        fork = None
        alt_branch = None
        # Prefer non-main branch as alt (the experimental cut)
        for b in branches:
            if b not in ("main", "master"):
                alt_branch = b
                break
        if not alt_branch and len(branches) > 1:
            # No non-main alt, pick the one that is not current
            for b in branches:
                if b != current:
                    alt_branch = b
                    break
        # Determine main branch name
        main_branch = "main" if "main" in branches else "master" if "master" in branches else branches[0] if branches else current
        if alt_branch:
            try:
                # Fork is merge-base of main and alt (stable, not dependent on current)
                mb = subprocess.run(["git", "merge-base", main_branch, alt_branch], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
                if mb.returncode == 0 and mb.stdout.strip():
                    fork = mb.stdout.strip()
            except Exception:
                pass
        # Mark each commit's visual role — whole tree always visible
        for c in commits:
            c["lane"] = 0
            c["isBranch"] = False
            c["isFork"] = False
            c["isCurrent"] = False
        if alt_branch and fork:
            for c in commits:
                if c["hash"] == fork or c["hash"].startswith(fork[:8]) or fork.startswith(c["hash"][:8]):
                    c["isFork"] = True
                    c["lane"] = 0
            # Alt branch's exclusive commits: alt_branch --not main (always, not dependent on current)
            try:
                alt_only = subprocess.run(["git", "log", alt_branch, "--not", main_branch, "--pretty=format:%H"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace")
                alt_hashes = set(h.strip() for h in alt_only.stdout.splitlines() if h.strip())
                for c in commits:
                    if c["hash"] in alt_hashes:
                        c["isBranch"] = True
                        c["lane"] = 1
            except Exception:
                pass
            # Current position dot: HEAD of *current* branch (highlighted even if on main)
            try:
                head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
                for c in commits:
                    if c["hash"] == head:
                        c["isCurrent"] = True
                        break
            except Exception:
                pass
            except Exception:
                pass
        else:
            # No alternate branch — just mark current HEAD
            try:
                head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(r), capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
                for c in commits:
                    if c["hash"] == head:
                        c["isCurrent"] = True
                        break
            except Exception:
                pass
            if commits:
                commits[0]["isCurrent"] = True  # fallback
        return {"ok": True, "repo": str(r), "current": current, "branches": branches, "altBranch": alt_branch, "fork": fork, "commits": commits}
    except Exception as e:
        return {"ok": False, "error": str(e), "commits": [], "branches": []}


def api_delete(repo: str | Path | None = None, rev: str = "", timeline: str | None = None) -> dict:
    r = _resolve_repo(repo)
    denied = _require_allowed_repo(r)
    if denied:
        return denied
    if not rev or not str(rev).strip():
        return {"ok": False, "error": "No version given"}
    rev = str(rev).strip()
    tfile = None
    if timeline:
        tf = _get_timeline_file(r, timeline)
        tfile = _rel(r, tf)
    # numeric alias: 1 = latest
    def _alias(rv: str) -> str:
        rv = rv.strip()
        if rv.isdigit():
            n = int(rv)
            vers = _alias_versions(r, tfile, max(30, n))
            if 0 <= n - 1 < len(vers):
                return vers[n - 1]["hash"]
        return rv
    rev_resolved = _alias(rev)
    try:
        res = git_store.delete_version(r, rev_resolved, timeline_file=tfile) if tfile else git_store.delete_version(r, rev_resolved)
        return {"ok": True, "repo": str(r), "deleted": res["deleted"], "new_head": res.get("new_head"), "rev": rev, "resolved": rev_resolved, "timeline": timeline}
    except Exception as e:
        return {"ok": False, "error": str(e), "repo": str(r)}

def api_default_repo() -> dict:
    """OS-correct default projects folder (~/GetSyncd). Lets the frontend avoid hardcoding paths."""
    try:
        DEFAULT_REPO.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("default repo mkdir failed: %s", e)
    return {"ok": True, "path": str(DEFAULT_REPO.resolve() if DEFAULT_REPO.exists() else DEFAULT_REPO)}


def api_list_projects() -> dict:
    """List all Get Syncd projects (subfolders of ~/GetSyncd that are git repos)."""
    base = DEFAULT_REPO
    base.mkdir(parents=True, exist_ok=True)
    if not base.exists():
        return {"ok": True, "projects": []}
    projects = []
    # Do NOT include base itself - it's a container for projects, not a project
    for p in base.iterdir():
        if p.name.startswith("."):
            continue
        if p.is_dir() and (p / ".git").exists():
            projects.append({"name": p.name, "path": str(p), "is_base": False})
    return {"ok": True, "projects": sorted(projects, key=lambda x: x["name"])}

def api_scan_resolve_projects() -> dict:
    """Ask DaVinci Resolve for project list and auto-create folders."""
    base = DEFAULT_REPO
    base.mkdir(parents=True, exist_ok=True)
    resolve = None
    try:
        ensure_resolve_scripting_path()
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

def _try_resolve_export(out_path: Path) -> tuple[bool, str]:
    """Try to auto-export current Resolve timeline to OTIO (best-effort)."""
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resolve = None
    try:
        ensure_resolve_scripting_path()
        import DaVinciResolveScript as bmd  # type: ignore
        resolve = bmd.scriptapp("Resolve")
    except Exception as e:
        return False, f"Resolve API not reachable: {e}"
    if not resolve:
        return False, "Could not connect to Resolve — is it running? Open a project first."
    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
        if not project:
            return False, "No project open in Resolve — open a project first."
        timeline = project.GetCurrentTimeline()
        if not timeline:
            return False, "No timeline open in Resolve — open a timeline in the Edit page first."
        tname = timeline.GetName() if hasattr(timeline, "GetName") else "timeline"
        # Preferred: timeline.Export with OTIO constants
        try:
            # Resolve constants are on the resolve object, e.g. resolve.EXPORT_OTIO
            exp_otio = getattr(resolve, "EXPORT_OTIO", None)
            exp_none = getattr(resolve, "EXPORT_NONE", None)
            if exp_otio is not None and hasattr(timeline, "Export"):
                ok = timeline.Export(str(out_path), exp_otio, exp_none if exp_none is not None else 0)
                if ok:
                    return True, f"Exported '{tname}' → {out_path} via timeline.Export"
        except Exception as e:
            pass
        # Fallbacks for older API variants
        for meth in ["Export", "ExportTimeline", "ExportOTIO"]:
            if hasattr(timeline, meth):
                try:
                    # Try with string "otio" as some wrappers accept it
                    ok = getattr(timeline, meth)(str(out_path), "otio")
                    if ok:
                        return True, f"Exported '{tname}' → {out_path} via timeline.{meth}"
                    # Try with no subtype
                    ok = getattr(timeline, meth)(str(out_path))
                    if ok:
                        return True, f"Exported '{tname}' → {out_path} via timeline.{meth}"
                except Exception:
                    continue
        if hasattr(project, "ExportTimeline"):
            try:
                ok = project.ExportTimeline(str(out_path), "otio")
                if ok:
                    return True, f"Exported '{tname}' → {out_path} via project.ExportTimeline"
            except Exception:
                pass
        return False, f"Auto-export not available in this Resolve version — use File → Export Timeline → OpenTimelineIO → {out_path} (must land exactly there)"
    except Exception as e:
        return False, f"Export error: {e}"


def api_export(repo: str | Path | None = None, out: str | Path | None = None, timeline: str | None = None) -> dict:
    r = _resolve_repo(repo)
    denied = _require_allowed_repo(r)
    if denied:
        return denied
    r.mkdir(parents=True, exist_ok=True)
    if out:
        out_path = Path(out).expanduser().resolve()
    else:
        if timeline:
            out_path = _get_timeline_file(r, timeline)
        else:
            cur, _ = _get_resolve_timelines(repo)
            if cur:
                out_path = _get_timeline_file(r, cur)
            else:
                out_path = r / "timeline.otio"
    ok, msg = _try_resolve_export(out_path)
    if ok:
        return {"ok": True, "repo": str(r), "out": str(out_path), "message": msg, "timeline": timeline or (cur if 'cur' in locals() and cur else None)}
    else:
        return {"ok": False, "repo": str(r), "out": str(out_path), "error": msg}


def _try_resolve_import(otio_path: Path) -> tuple[bool, str]:
    """Try to auto-import OTIO into current Resolve project and auto-save.

    Uses MediaPool.ImportTimelineFromFile (correct OTIO API), then SaveProject,
    then Close + Load to ensure restored timeline is current. Best-effort.
    """
    otio_path = Path(otio_path).resolve()
    if not otio_path.exists():
        return False, f"File not found: {otio_path}"
    resolve = None
    try:
        ensure_resolve_scripting_path()
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
        proj_name = project.GetName() if hasattr(project, "GetName") else "Unknown"
        # 1) Preferred: MediaPool.ImportTimelineFromFile (OTIO correct API)
        imported = None
        try:
            mp = project.GetMediaPool()
            if mp and hasattr(mp, "ImportTimelineFromFile"):
                # Try with timelineName from file stem, without extension
                timeline_name = otio_path.stem
                # Resolve 18.5+ expects dict with timelineName
                # Try to find media folder for source clips (where OTIO's target_urls live)
                # For Marginal Videos, media is in ~/Desktop/Маргинал Видеа/
                try:
                    import json as _js
                    _otio_data = _js.load(open(str(otio_path), encoding="utf-8"))
                    # Quick scan for common media dir from OTIO
                    def _find_media_dir(obj, out):
                        if isinstance(obj, dict):
                            if obj.get("OTIO_SCHEMA") == "ExternalReference.1" and obj.get("target_url"):
                                out.append(str(Path(obj["target_url"]).parent))
                            for v in obj.values():
                                _find_media_dir(v, out)
                        elif isinstance(obj, list):
                            for v in obj:
                                _find_media_dir(v, out)
                    _media_dirs = []
                    _find_media_dir(_otio_data, _media_dirs)
                    from collections import Counter
                    _common = Counter(_media_dirs).most_common(1)
                    _source_path = _common[0][0] if _common else ""
                except Exception:
                    _source_path = ""
                for opts in [
                    {"timelineName": timeline_name, "importSourceClips": True, "sourceClipsPath": _source_path} if _source_path else {"timelineName": timeline_name, "importSourceClips": True},
                    {"timelineName": timeline_name, "importSourceClips": True},
                    {"timelineName": timeline_name},
                    {"timelineName": f"{timeline_name}_restored", "importSourceClips": True},
                ]:
                    try:
                        timeline = mp.ImportTimelineFromFile(str(otio_path), opts)
                        if timeline:
                            imported = timeline
                            # Make it current if possible
                            try:
                                if hasattr(project, "SetCurrentTimeline"):
                                    project.SetCurrentTimeline(timeline)
                            except Exception:
                                pass
                            break
                    except Exception:
                        continue
                if imported:
                    # Save project so restored timeline persists.
                    # NOTE: never CloseProject/LoadProject here — background or
                    # restore flows must not visibly switch the user's open
                    # Resolve project. SetCurrentTimeline above already makes
                    # the restored timeline current; the user reopens manually
                    # if Resolve ever shows a stale state.
                    try:
                        pm.SaveProject()
                    except Exception:
                        try:
                            project.SaveProject()  # some versions
                        except Exception:
                            pass
                    return True, f"Imported '{timeline_name}' via ImportTimelineFromFile and saved '{proj_name}' ✓ (already set as the current timeline)"
        except Exception:
            pass
        # 2) Fallback: MediaPool.ImportMedia (older, may work for some)
        try:
            mp = project.GetMediaPool()
            if mp and hasattr(mp, "ImportMedia"):
                res = mp.ImportMedia([str(otio_path)])
                if res:
                    try:
                        pm.SaveProject()
                    except Exception:
                        pass
                    return True, f"Imported via MediaPool.ImportMedia → {otio_path.name} and saved"
        except Exception:
            pass
        # 3) Fallback: Project-level import
        for meth in ["ImportTimeline", "LoadTimeline", "ImportOTIO"]:
            if hasattr(project, meth):
                try:
                    ok = getattr(project, meth)(str(otio_path))
                    if ok:
                        try:
                            pm.SaveProject()
                        except Exception:
                            pass
                        return True, f"Imported via Project.{meth} and saved"
                except Exception:
                    continue
        return False, "Auto-import not available in this Resolve version — use File → Import Timeline → OpenTimelineIO → timeline.otio (then save project manually)"
    except Exception as e:
        return False, f"Import error: {e}"
