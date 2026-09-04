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
