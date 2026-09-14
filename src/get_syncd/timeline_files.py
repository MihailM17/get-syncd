"""Timeline file resolution — maps timeline names to .otio paths.

Split out of api.py (#5). Pure filesystem logic, no Resolve calls.
"""

from __future__ import annotations

import os
from pathlib import Path


def _sanitize_timeline_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "Untitled"
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in name).strip()
    if not safe:
        safe = "timeline"
    return safe


def resolve_timeline_selection(repo: Path, timeline: str | None = None) -> tuple[str | None, str]:
    """Pick the working file for a CLI/GUI operation: (name or None, repo-relative path).

    Mirrors api._get_timeline_file semantics without importing api:
    - single-file repos → legacy ``timeline.otio`` (explicit names resolve there too,
      unless they name a different timeline that already has its own file);
    - migrated repos (timelines/*.otio exists) → ``timelines/<name>.otio`` for the
      explicit ``--timeline`` or Resolve's current timeline;
    - migrated with no name determinable → (None, "timeline.otio"); callers must
      ask for --timeline instead of guessing.
    """
    from .resolve_state import _get_resolve_timelines

    repo = Path(repo)
    td = repo / "timelines"
    pats: list[Path] = []
    if td.exists():
        pats = list(td.glob("*.otio")) + list(td.glob("*.OTIO"))
    migrated = bool(pats)
    name = (timeline or "").strip() or None
    if not migrated:
        if not name:
            return None, "timeline.otio"
        try:
            cur, _ = _get_resolve_timelines(repo)
        except Exception:
            cur = None
        if cur and name != cur and name != "timeline":
            candidate = td / f"{_sanitize_timeline_name(name)}.otio"
            if candidate.exists():
                return name, candidate.relative_to(repo).as_posix()
            return name, f"timelines/{_sanitize_timeline_name(name)}.otio"
        return name, "timeline.otio"
    if not name:
        try:
            cur, _ = _get_resolve_timelines(repo)
        except Exception:
            cur = None
        name = cur
    if not name:
        return None, "timeline.otio"
    return name, f"timelines/{_sanitize_timeline_name(name)}.otio"


def _list_timeline_files(repo: Path) -> list[Path]:
    """List all versioned timeline files in repo (timelines/*.otio + legacy).

    Dedup is by identity, not spelling: on case-insensitive filesystems
    (Windows, macOS default) the "*.otio" glob already matches "*.OTIO", so
    extending with both patterns lists every file twice. os.path.samefile
    collapses those (and any other aliasing) while keeping genuinely
    distinct files apart on case-sensitive volumes.
    """
    files: list[Path] = []

    def _add(p: Path) -> None:
        for q in files:
            if p == q:
                return
            try:
                if os.path.samefile(p, q):
                    return
            except OSError:
                continue
        files.append(p)

    timelines_dir = repo / "timelines"
    if timelines_dir.exists():
        for p in sorted(timelines_dir.glob("*.otio")):
            _add(p)
        for p in sorted(timelines_dir.glob("*.OTIO")):
            _add(p)
    legacy = repo / "timeline.otio"
    if legacy.exists():
        _add(legacy)
    for p in repo.glob("*.otio"):
        if p.name.lower() != "timeline.otio":
            _add(p)
    return files
