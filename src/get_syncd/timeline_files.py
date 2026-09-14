"""Timeline file resolution — maps timeline names to .otio paths.

Split out of api.py (#5). Pure filesystem logic, no Resolve calls.
"""

from __future__ import annotations

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
                return name, str(candidate.relative_to(repo))
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
    """List all versioned timeline files in repo (timelines/*.otio + legacy)."""
    files: list[Path] = []
    timelines_dir = repo / "timelines"
    if timelines_dir.exists():
        files.extend(sorted(timelines_dir.glob("*.otio")))
        files.extend(sorted(timelines_dir.glob("*.OTIO")))
    legacy = repo / "timeline.otio"
    if legacy.exists():
        if not files:
            files.append(legacy)
        elif legacy not in files:
            files.append(legacy)
    for p in repo.glob("*.otio"):
        if p not in files and p.name.lower() != "timeline.otio":
            files.append(p)
    return files
