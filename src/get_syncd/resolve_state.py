"""Resolve project state — read-only access, per-repo timeline cache.

Split out of api.py (#5). Never calls LoadProject: background polling must not
visibly switch the user's open Resolve project. Explicit syncs go through
api_sync_resolve() only.
"""

from __future__ import annotations

import logging
import time as _time
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_REPO = Path.home() / "GetSyncd"


def resolve_scripting_paths() -> list[str]:
    """Candidate DaVinci Resolve scripting module dirs for the current OS.

    macOS: /Library/... and ~/Library/...; Windows: %PROGRAMDATA% + %APPDATA%
    variants; Linux: /opt/resolve/... plus XDG-ish fallbacks. Only existing
    dirs are returned, in priority order.
    """
    import sys

    candidates: list[str] = []
    plat = sys.platform
    if plat == "win32":
        import os

        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        app_data = os.environ.get("APPDATA", "")
        candidates.append(
            str(Path(program_data) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Developer" / "Scripting" / "Modules")
        )
        if app_data:
            candidates.append(
                str(Path(app_data) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Developer" / "Scripting" / "Modules")
            )
    elif plat.startswith("linux"):
        candidates.append("/opt/resolve/Developer/Scripting/Modules")
        candidates.append("/opt/BlackmagicDesign/DaVinci_Resolve/Developer/Scripting/Modules")
        candidates.append(
            str(Path.home() / ".local" / "share" / "DaVinciResolve" / "Developer" / "Scripting" / "Modules")
        )
    else:  # macOS and anything else: keep historical behavior
        candidates.append("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules")
        candidates.append(
            str(Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules")
        )
    return [p for p in candidates if Path(p).exists()]


def ensure_resolve_scripting_path() -> bool:
    """Append existing Resolve scripting dirs to sys.path. Returns True if any added."""
    import sys

    added = False
    for pp in resolve_scripting_paths():
        if pp not in sys.path:
            sys.path.append(pp)
            added = True
    return added

_CURRENT_RESOLVE_CACHE: dict = {"t": 0.0, "project": None, "current": None, "names": []}
_CURRENT_RESOLVE_TTL_S = 5.0


def _known_timelines_file(repo: Path) -> Path:
    return repo / ".get-syncd" / "timelines.json"


def _save_known_timelines(repo: Path, current: str | None, all_names: list[str]):
    try:
        repo = Path(repo)
        f = _known_timelines_file(repo)
        f.parent.mkdir(parents=True, exist_ok=True)
        # Replace — do not merge across projects.
        deduped = list(dict.fromkeys(all_names or []))
        if current and current not in deduped:
            deduped.append(current)
        deduped = [n for n in deduped if n and str(n).strip()]
        import json as _js
        import datetime as _dt
        _js.dump(
            {"current": current, "all_names": deduped, "updated": _dt.datetime.now().isoformat()},
            open(f, "w", encoding="utf-8"),
            indent=2,
        )
    except Exception as e:
        log.warning("save known timelines failed for %s: %s", repo, e)


def _load_known_timelines(repo: Path) -> tuple[str | None, list[str]]:
    try:
        f = _known_timelines_file(repo)
        if f.exists():
            import json as _js
            d = _js.load(open(f, encoding="utf-8"))
            return d.get("current"), d.get("all_names") or []
    except Exception as e:
        log.warning("load known timelines failed for %s: %s", repo, e)
    return None, []


def _read_current_resolve_state() -> tuple[str | None, str | None, list[str]]:
    """Read-only: current project + timelines. NEVER calls LoadProject."""
    now = _time.monotonic()
    if now - _CURRENT_RESOLVE_CACHE.get("t", 0) < _CURRENT_RESOLVE_TTL_S:
        c = _CURRENT_RESOLVE_CACHE
        return c.get("project"), c.get("current"), list(c.get("names") or [])

    def _store(project, current, names):
        _CURRENT_RESOLVE_CACHE.update(
            {"t": _time.monotonic(), "project": project, "current": current, "names": list(names or [])}
        )

    try:
        ensure_resolve_scripting_path()
        import DaVinciResolveScript as bmd  # type: ignore
        resolve = bmd.scriptapp("Resolve")
        if not resolve:
            return None, None, []
        pm = resolve.GetProjectManager()
        if not pm:
            return None, None, []
        project = pm.GetCurrentProject() if pm else None
        if not project:
            _store(None, None, [])
            return None, None, []
        try:
            project_name = project.GetName() if hasattr(project, "GetName") else None
        except Exception as e:
            log.warning("resolve GetName failed: %s", e)
            project_name = None
        current = None
        try:
            tl = project.GetCurrentTimeline()
            if tl and hasattr(tl, "GetName"):
                current = tl.GetName()
        except Exception as e:
            log.warning("resolve GetCurrentTimeline failed: %s", e)
        all_names: list[str] = []
        try:
            n = project.GetTimelineCount()
            for i in range(1, int(n) + 1):
                tl = project.GetTimelineByIndex(i)
                if tl and hasattr(tl, "GetName"):
                    all_names.append(tl.GetName())
        except Exception as e:
            log.warning("resolve GetTimelineCount failed: %s", e)
        if not all_names and current:
            all_names = [current]
        _store(project_name, current, all_names)
        return project_name, current, all_names
    except Exception as e:
        log.warning("resolve read failed: %s", e)
        return None, None, []


def _get_resolve_timelines(repo: Path | None = None) -> tuple[str | None, list[str]]:
    """Per-repo timelines without switching projects. Cache-first, read-only live fallback."""
    if repo:
        cur, names = _load_known_timelines(Path(repo))
        if names:
            return cur, names
        try:
            project_name, current, all_names = _read_current_resolve_state()
            if project_name and project_name == Path(repo).name and all_names:
                _save_known_timelines(Path(repo), current, all_names)
                return current, all_names
        except Exception as e:
            log.warning("resolve match check failed for %s: %s", repo, e)
        return None, []
    try:
        _, current, all_names = _read_current_resolve_state()
        if all_names:
            return current, all_names
    except Exception as e:
        log.warning("resolve current read failed: %s", e)
    try:
        cur, names = _load_known_timelines(DEFAULT_REPO)
        if names:
            return cur, names
    except Exception as e:
        log.warning("default cache read failed: %s", e)
    return None, []
