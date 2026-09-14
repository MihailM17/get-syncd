"""Diff engine for Get Syncd.

Compares two NormalizedTimeline objects by sequence identity, not absolute timecode.
Trimming an early clip shifts all later clips in time but does not mark them changed.

Algorithm:
- Use difflib.SequenceMatcher on loose identity keys (media URL) to find LCS.
- Classify each opcode region into added/removed/reordered/trimmed.
- Output structured list of changes + summary.

This mirrors git's Myers/LCS but applied to clips instead of lines.
"""

from __future__ import annotations

import dataclasses
import difflib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

from .otio_parse import NORMALIZED_RATE, NormalizedTimeline, NormalizedTrack, NormalizedClip


@dataclass
class ClipChange:
    type: str  # trimmed | added | removed | reordered | gap_changed | transition_changed | renamed | moved
    index_old: Optional[int] = None
    index_new: Optional[int] = None
    clip_name: str = ""
    url: str = ""
    kind: str = "clip"
    details: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class TimelineDiff:
    changes: list[ClipChange] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    tracks_compared: list[str] = field(default_factory=list)  # track names diffed
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "changes": [c.to_dict() for c in self.changes],
            "summary": self.summary,
            "tracks_compared": self.tracks_compared,
            "warnings": self.warnings,
        }

    def to_json(self, indent=2):
        return json.dumps(self.to_dict(), indent=indent)


def _frames_to_seconds(frames: float) -> float:
    return frames / NORMALIZED_RATE if NORMALIZED_RATE else 0.0


def _frames_to_timecode(frames: float) -> str:
    secs = _frames_to_seconds(frames)
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def format_timecode(seconds: float) -> str:
    """Timeline position as HH:MM:SS.mmm (quantized to the millisecond first
    so 59.9999s never renders as an invalid 60.000s)."""
    total_ms = max(0, int(round(float(seconds) * 1000)))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def format_signed_delta(seconds: float) -> str:
    """Signed position delta for moves: +00:03.200 / -00:03.200."""
    s = float(seconds)
    sign = "-" if s < 0 else "+"
    return f"{sign}{format_timecode(abs(s))}"


def _fmt_secs(seconds: float) -> str:
    """Compact seconds for prose: 2.3, 12, 0.5 (never 2.300)."""
    s = round(float(seconds), 1)
    if s == int(s):
        return str(int(s))
    return f"{s:.1f}"


def _track_offsets(track: NormalizedTrack) -> list[float]:
    """Timeline start (seconds) of every item = prefix sums of durations."""
    offsets: list[float] = []
    acc = 0.0
    for item in track.items:
        offsets.append(round(acc, 3))
        try:
            acc += _frames_to_seconds(item.duration_frames)
        except Exception:
            pass
    return offsets


def _volume_delta(a: NormalizedClip, b: NormalizedClip) -> dict | None:
    """Volume sub-change between matched clips, or None.

    Compared at 1-decimal precision so a reported change always renders
    visibly different values (never "-6.0 dB → -6.0 dB").
    """
    if a.volume_db is None or b.volume_db is None:
        return None
    old = round(float(a.volume_db), 1)
    new = round(float(b.volume_db), 1)
    if old == new:
        return None
    return {"old": old, "new": new}


def _title_delta(a: NormalizedClip, b: NormalizedClip) -> dict | None:
    """Title-text sub-change between matched clips/stacks, or None."""
    olds = list(getattr(a, "title_texts", None) or ([a.title_text] if a.title_text else []))
    news = list(getattr(b, "title_texts", None) or ([b.title_text] if b.title_text else []))
    olds = [str(t).strip() for t in olds if str(t or "").strip()]
    news = [str(t).strip() for t in news if str(t or "").strip()]
    if olds == news:
        return None
    return {"old": olds[0] if olds else None, "new": news[0] if news else None}


def _attr_deltas(a: NormalizedClip, b: NormalizedClip) -> dict:
    """Volume/title sub-changes between a matched pair (possibly empty)."""
    out: dict = {}
    try:
        v = _volume_delta(a, b)
        if v:
            out["volume"] = v
    except Exception:
        pass
    try:
        t = _title_delta(a, b)
        if t:
            out["title"] = t
    except Exception:
        pass
    return out


def _clips_equal_by_trim(a: NormalizedClip, b: NormalizedClip, tolerance_frames: float = 1.0) -> bool:
    """Check if two clips with same identity have same trim (start+duration)."""
    if a.kind != b.kind:
        return False
    if a.kind == "clip":
        # Compare start and duration within tolerance
        a_start = a.start_frames if a.start_frames is not None else 0
        b_start = b.start_frames if b.start_frames is not None else 0
        if abs(a_start - b_start) > tolerance_frames:
            return False
        if abs(a.duration_frames - b.duration_frames) > tolerance_frames:
            return False
        # Also check name change (treated as rename, not trim)
        # but we handle rename separately
        return True
    if a.kind == "gap":
        return abs(a.duration_frames - b.duration_frames) <= tolerance_frames
    if a.kind == "transition":
        if a.transition_type != b.transition_type:
            return False
        ao = a.in_offset_frames or 0
        bo = b.in_offset_frames or 0
        if abs(ao - bo) > tolerance_frames:
            return False
        ao2 = a.out_offset_frames or 0
        bo2 = b.out_offset_frames or 0
        if abs(ao2 - bo2) > tolerance_frames:
            return False
        return True
    if a.kind == "stack":
        # Same compound only if the duration matches AND no nested title
        # changed (title texts are flattened at parse, incl. Stacks that
        # nest whole Tracks).
        if a.duration_frames != b.duration_frames:
            return False
        return list(getattr(a, "title_texts", []) or []) == list(getattr(b, "title_texts", []) or [])
    return a.duration_frames == b.duration_frames


def _describe_trim(a: NormalizedClip, b: NormalizedClip) -> dict:
    details = {}
    if a.kind == "clip":
        old_dur = _frames_to_seconds(a.duration_frames)
        new_dur = _frames_to_seconds(b.duration_frames)
        details["old_duration_s"] = round(old_dur, 3)
        details["new_duration_s"] = round(new_dur, 3)
        details["delta_s"] = round(new_dur - old_dur, 3)
        details["delta_frames_normalized"] = round(b.duration_frames - a.duration_frames, 1)
        if a.start_frames is not None and b.start_frames is not None:
            details["old_start_frames"] = a.orig_start
            details["new_start_frames"] = b.orig_start
            details["old_start_rate"] = a.orig_rate
            details["start_delta_frames"] = round(b.start_frames - a.start_frames, 1)
        if a.name != b.name:
            details["renamed_from"] = a.name
            details["renamed_to"] = b.name
    elif a.kind == "gap":
        details["old_gap_s"] = round(_frames_to_seconds(a.duration_frames), 3)
        details["new_gap_s"] = round(_frames_to_seconds(b.duration_frames), 3)
        details["delta_s"] = round(_frames_to_seconds(b.duration_frames - a.duration_frames), 3)
    elif a.kind == "transition":
        details["old_type"] = a.transition_type
        details["new_type"] = b.transition_type
        details["old_in_offset"] = a.in_offset_frames
        details["new_in_offset"] = b.in_offset_frames
        details["old_out_offset"] = a.out_offset_frames
        details["new_out_offset"] = b.out_offset_frames
    else:
        # Stacks / unknown kinds: bare duration change (no source offsets).
        details["old_duration_s"] = round(_frames_to_seconds(a.duration_frames), 3)
        details["new_duration_s"] = round(_frames_to_seconds(b.duration_frames), 3)
        details["delta_s"] = round(_frames_to_seconds(b.duration_frames - a.duration_frames), 3)
    return details


def _trim_line(a: NormalizedClip, b: NormalizedClip, details: dict) -> str:
    """Human trim wording with direction. Never exposes raw source offsets."""
    eps = 0.002
    try:
        delta_s = float(details.get("delta_s", 0.0))
    except (TypeError, ValueError):
        delta_s = 0.0
    try:
        head_s = float(details.get("start_delta_frames", 0.0)) / NORMALIZED_RATE
    except (TypeError, ValueError):
        head_s = 0.0
    # Tail change = total change minus what the head shift accounts for:
    # new_dur = old_dur - head_cut + tail_change.
    tail_s = delta_s + head_s
    if abs(delta_s) < eps and abs(head_s) >= eps:
        # Same duration, later/earlier source: a slip, not a trim.
        return f"Slipped {_fmt_secs(abs(head_s))}s {'earlier' if head_s < 0 else 'later'}"
    verb = "Extended" if delta_s > 0 else "Trimmed"
    parts: list[str] = []
    if abs(head_s) >= eps:
        parts.append(f"{_fmt_secs(abs(head_s))}s from beginning")
    if abs(tail_s) >= eps:
        parts.append(f"{_fmt_secs(abs(tail_s))}s from end")
    if not parts:
        parts.append(f"{_fmt_secs(abs(delta_s))}s")
    return f"{verb} " + ", ".join(parts)


def diff_tracks(old: NormalizedTrack, new: NormalizedTrack, tolerance_frames: float = 1.0) -> TimelineDiff:
    """Diff two NormalizedTracks (same track name ideally)."""
    result = TimelineDiff(tracks_compared=[old.name, new.name])

    # Build identity sequences for LCS
    # Use loose identity so that trimmed clips still match as "same clip"
    old_keys = [c.loose_identity() for c in old.items]
    new_keys = [c.loose_identity() for c in new.items]

    # Also build strict keys for exact matching (to detect reorder vs trim)
    # We use SequenceMatcher with autojunk=False to avoid misclassifying duplicates
    sm = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    opcodes = sm.get_opcodes()

    added = 0
    removed = 0
    trimmed = 0
    reordered = 0
    modified = 0
    gap_changed = 0
    transition_changed = 0

    # For reorder detection: collect removed and added clips that share loose identity
    # We'll first handle opcodes, then do a second pass for reorders
    # Simple approach: equal blocks may still contain trimmed clips

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            # Same sequence of identities — check each pair for trim changes
            for oi, nj in zip(range(i1, i2), range(j1, j2)):
                oc = old.items[oi]
                nc = new.items[nj]
                if not _clips_equal_by_trim(oc, nc, tolerance_frames):
                    # A title change deep inside a compound surfaces as a
                    # modification of the stack (with the stack's position),
                    # not a trim — durations alone can't describe it.
                    if oc.kind == "stack":
                        tdelta = _title_delta(oc, nc)
                        if tdelta:
                            result.changes.append(
                                ClipChange(
                                    type="modified",
                                    index_old=oi,
                                    index_new=nj,
                                    clip_name=nc.name or oc.name,
                                    url=nc.url or oc.url,
                                    kind=oc.kind,
                                    details={"title": tdelta, "is_title": True},
                                )
                            )
                            modified += 1
                            continue
                    if oc.kind == "gap":
                        result.changes.append(
                            ClipChange(
                                type="gap_changed",
                                index_old=oi,
                                index_new=nj,
                                clip_name=oc.name,
                                url=oc.url,
                                kind=oc.kind,
                                details=_describe_trim(oc, nc),
                            )
                        )
                        gap_changed += 1
                    elif oc.kind == "transition":
                        result.changes.append(
                            ClipChange(
                                type="transition_changed",
                                index_old=oi,
                                index_new=nj,
                                clip_name=oc.name,
                                url=oc.url,
                                kind=oc.kind,
                                details=_describe_trim(oc, nc),
                            )
                        )
                        transition_changed += 1
                    else:
                        # Check if it's just a rename
                        if oc.url == nc.url and oc.name != nc.name and abs(oc.duration_frames - nc.duration_frames) <= tolerance_frames and (oc.start_frames or 0) == (nc.start_frames or 0):
                            result.changes.append(
                                ClipChange(
                                    type="renamed",
                                    index_old=oi,
                                    index_new=nj,
                                    clip_name=nc.name,
                                    url=nc.url,
                                    kind=oc.kind,
                                    details={**_describe_trim(oc, nc), **_attr_deltas(oc, nc)},
                                )
                            )
                        else:
                            result.changes.append(
                                ClipChange(
                                    type="trimmed",
                                    index_old=oi,
                                    index_new=nj,
                                    clip_name=nc.name or oc.name,
                                    url=nc.url or oc.url,
                                    kind=oc.kind,
                                    details={**_describe_trim(oc, nc), **_attr_deltas(oc, nc)},
                                )
                            )
                        trimmed += 1
                else:
                    # Structurally identical, but volume and/or title text
                    # differ — a modification, not a trim.
                    attrs = _attr_deltas(oc, nc)
                    if attrs and oc.kind == "clip":
                        result.changes.append(
                            ClipChange(
                                type="modified",
                                index_old=oi,
                                index_new=nj,
                                clip_name=nc.name or oc.name,
                                url=nc.url or oc.url,
                                kind=oc.kind,
                                details=attrs,
                            )
                        )
                        modified += 1

        elif tag == "replace":
            # Could be reordered, trimmed+replaced, or added/removed mix
            old_slice = old.items[i1:i2]
            new_slice = new.items[j1:j2]

            # Build maps by loose identity for this slice
            old_map = {c.loose_identity(): c for c in old_slice}
            new_map = {c.loose_identity(): c for c in new_slice}

            # Check for reordered: same loose identity appears in both slices at different positions
            old_identities = set(old_map.keys())
            new_identities = set(new_map.keys())
            common = old_identities & new_identities

            handled_old = set()
            handled_new = set()

            for ident in common:
                oc = old_map[ident]
                nc = new_map[ident]
                oi = old_keys.index(ident, i1, i2) if ident in old_keys[i1:i2] else i1
                nj = new_keys.index(ident, j1, j2) if ident in new_keys[j1:j2] else j1
                # Find actual indices (first occurrence in slice)
                for k, c in enumerate(old_slice):
                    if c.loose_identity() == ident:
                        oi = i1 + k
                        break
                for k, c in enumerate(new_slice):
                    if c.loose_identity() == ident:
                        nj = j1 + k
                        break

                if not _clips_equal_by_trim(oc, nc, tolerance_frames):
                    # Moved and trimmed
                    result.changes.append(
                        ClipChange(
                            type="trimmed",
                            index_old=oi,
                            index_new=nj,
                            clip_name=nc.name or oc.name,
                            url=nc.url,
                            kind=nc.kind,
                            details={**_describe_trim(oc, nc), "also_reordered": True, **_attr_deltas(oc, nc)},
                        )
                    )
                    trimmed += 1
                else:
                    result.changes.append(
                        ClipChange(
                            type="reordered",
                            index_old=oi,
                            index_new=nj,
                            clip_name=nc.name or oc.name,
                            url=nc.url,
                            kind=nc.kind,
                            details={"from_index": oi, "to_index": nj, "loose_identity": ident, **_attr_deltas(oc, nc)},
                        )
                    )
                    reordered += 1
                handled_old.add(ident)
                handled_new.add(ident)

            # Remaining in old slice = removed
            for k, oc in enumerate(old_slice):
                ident = oc.loose_identity()
                if ident in handled_old:
                    continue
                # Check if this identity exists elsewhere in new (outside slice) — might be moved farther
                # For MVP, treat remaining replace as removed
                result.changes.append(
                    ClipChange(
                        type="removed",
                        index_old=i1 + k,
                        index_new=None,
                        clip_name=oc.name,
                        url=oc.url,
                        kind=oc.kind,
                        details={"duration_s": round(_frames_to_seconds(oc.duration_frames), 3)},
                    )
                )
                removed += 1

            # Remaining in new slice = added
            for k, nc in enumerate(new_slice):
                ident = nc.loose_identity()
                if ident in handled_new:
                    continue
                result.changes.append(
                    ClipChange(
                        type="added",
                        index_old=None,
                        index_new=j1 + k,
                        clip_name=nc.name,
                        url=nc.url,
                        kind=nc.kind,
                        details={"duration_s": round(_frames_to_seconds(nc.duration_frames), 3)},
                    )
                )
                added += 1

        elif tag == "delete":
            for k in range(i1, i2):
                oc = old.items[k]
                result.changes.append(
                    ClipChange(
                        type="removed",
                        index_old=k,
                        index_new=None,
                        clip_name=oc.name,
                        url=oc.url,
                        kind=oc.kind,
                        details={"duration_s": round(_frames_to_seconds(oc.duration_frames), 3)},
                    )
                )
                removed += 1

        elif tag == "insert":
            for k in range(j1, j2):
                nc = new.items[k]
                result.changes.append(
                    ClipChange(
                        type="added",
                        index_old=None,
                        index_new=k,
                        clip_name=nc.name,
                        url=nc.url,
                        kind=nc.kind,
                        details={"duration_s": round(_frames_to_seconds(nc.duration_frames), 3)},
                    )
                )
                added += 1

    # Second pass for reorder detection across non-adjacent blocks:
    # If a removed clip's URL appears as an added clip elsewhere, reclassify as reordered
    # (handles moves that SequenceMatcher split into delete+insert)
    removed_changes = [c for c in result.changes if c.type == "removed"]
    added_changes = [c for c in result.changes if c.type == "added"]
    to_remove_from_changes = set()
    reorder_to_add = []

    for rc in removed_changes:
        rc_ident = f"clip:{rc.url}" if rc.url else f"clip:name:{rc.clip_name}"
        # Find matching added
        match = None
        for ac in added_changes:
            ac_ident = f"clip:{ac.url}" if ac.url else f"clip:name:{ac.clip_name}"
            if ac_ident == rc_ident and id(ac) not in to_remove_from_changes:
                # Check if not already handled
                already_reordered = any(
                    x.type == "reordered" and x.url == rc.url and x.clip_name == rc.clip_name
                    for x in result.changes
                )
                if not already_reordered:
                    match = ac
                    break
        if match:
            # Reclassify pair as reordered
            to_remove_from_changes.add(id(rc))
            to_remove_from_changes.add(id(match))
            # Find original items to check trim
            # Locate NormalizedClips
            oc = None
            nc = None
            for item in old.items:
                if (item.url == rc.url and rc.url) or (item.name == rc.clip_name and not rc.url):
                    if item.index == rc.index_old:
                        oc = item
                        break
            for item in new.items:
                if (item.url == match.url and match.url) or (item.name == match.clip_name and not match.url):
                    if item.index == match.index_new:
                        nc = item
                        break
            if oc and nc and not _clips_equal_by_trim(oc, nc, tolerance_frames):
                reorder_to_add.append(
                    ClipChange(
                        type="trimmed",
                        index_old=rc.index_old,
                        index_new=match.index_new,
                        clip_name=match.clip_name or rc.clip_name,
                        url=match.url or rc.url,
                        kind=match.kind,
                        details={**_describe_trim(oc, nc), "also_reordered": True, **_attr_deltas(oc, nc)},
                    )
                )
                trimmed += 1
                added -= 1
                removed -= 1
            else:
                reorder_to_add.append(
                    ClipChange(
                        type="reordered",
                        index_old=rc.index_old,
                        index_new=match.index_new,
                        clip_name=match.clip_name or rc.clip_name,
                        url=match.url or rc.url,
                        kind=match.kind,
                        details={"from_index": rc.index_old, "to_index": match.index_new, **(_attr_deltas(oc, nc) if oc and nc else {})},
                    )
                )
                reordered += 1
                added -= 1
                removed -= 1

    if to_remove_from_changes:
        result.changes = [c for c in result.changes if id(c) not in to_remove_from_changes]
        result.changes.extend(reorder_to_add)
        # Sort by new index then old
        result.changes.sort(key=lambda c: (c.index_new if c.index_new is not None else 9999, c.index_old if c.index_old is not None else 9999))

    _annotate_positions(result.changes, old, new)

    # Compute runtime delta
    old_dur = old.duration_frames()
    new_dur = new.duration_frames()
    delta_frames = new_dur - old_dur
    delta_s = _frames_to_seconds(delta_frames)

    result.summary = {
        "added": added,
        "removed": removed,
        "trimmed": trimmed,
        "reordered": reordered,
        "modified": modified,
        "gap_changed": gap_changed,
        "transition_changed": transition_changed,
        "total_changes": len(result.changes),
        "old_duration_s": round(_frames_to_seconds(old_dur), 3),
        "new_duration_s": round(_frames_to_seconds(new_dur), 3),
        "runtime_delta_s": round(delta_s, 3),
        "runtime_delta_frames": round(delta_frames, 1),
    }

    return result


def _annotate_positions(changes: list, old: NormalizedTrack, new: NormalizedTrack) -> None:
    """Attach timeline positions to every change, in place.

    New-side position for added/moved-to/trimmed-in-place; old-side position
    for removed. Reordered changes get both plus the signed delta. Sections
    and timecodes downstream read only these fields.
    """
    try:
        old_off = _track_offsets(old)
    except Exception:
        old_off = []
    try:
        new_off = _track_offsets(new)
    except Exception:
        new_off = []
    for c in changes:
        try:
            d = c.details
            if not isinstance(d, dict):
                continue
            if c.index_new is not None and 0 <= c.index_new < len(new_off):
                d["timeline_start_s"] = new_off[c.index_new]
            if c.index_old is not None and 0 <= c.index_old < len(old_off):
                d["timeline_old_s"] = old_off[c.index_old]
            if c.type == "reordered" and "timeline_start_s" in d and "timeline_old_s" in d:
                d["move_delta_s"] = round(d["timeline_start_s"] - d["timeline_old_s"], 3)
        except Exception:
            continue


def _volume_lines(details: dict) -> list[str]:
    v = details.get("volume") if isinstance(details, dict) else None
    if not isinstance(v, dict):
        return []
    try:
        return [f"Volume: {float(v['old']):.1f} dB → {float(v['new']):.1f} dB"]
    except (KeyError, TypeError, ValueError):
        return []


def _title_lines(details: dict) -> list[str]:
    t = details.get("title") if isinstance(details, dict) else None
    if not isinstance(t, dict):
        return []
    old = t.get("old")
    new = t.get("new")
    if old and new:
        return [f'Text: "{old}" → "{new}"']
    if new:
        return [f'Text: "{new}"']
    if old:
        return [f'Text: "{old}"']
    return []


def change_lines(ch, old_item=None, new_item=None) -> list[str]:
    """Preformatted detail lines for one change (the sections contract).

    The frontend renders these verbatim, so CLI and UI can never drift apart.
    Volume/title sub-lines appear only when the value actually differs —
    never as attribute dumps.
    """
    d = ch.details if isinstance(getattr(ch, "details", None), dict) else {}
    lines: list[str] = []
    t = ch.type
    title_text = ""
    try:
        for cand in (new_item, old_item):
            if cand is not None and getattr(cand, "title_text", None):
                title_text = str(cand.title_text).strip()
                break
    except Exception:
        title_text = ""
    if t == "added":
        if title_text:
            lines.append(f'+ Added "{title_text}"')
        else:
            lines.append("+ Added")
    elif t == "removed":
        if title_text:
            lines.append(f'- Removed "{title_text}"')
        else:
            lines.append("- Removed")
    elif t == "trimmed":
        if old_item is not None and new_item is not None:
            lines.append(_trim_line(old_item, new_item, d))
        elif "delta_s" in d:
            try:
                delta = float(d.get("delta_s", 0.0))
                verb = "Extended" if delta > 0 else "Trimmed"
                lines.append(f"{verb} {_fmt_secs(abs(delta))}s")
            except (TypeError, ValueError):
                lines.append("Trimmed")
        elif "old_duration_s" in d and "new_duration_s" in d:
            try:
                lines.append(f"Duration {d['old_duration_s']}s → {d['new_duration_s']}s")
            except Exception:
                lines.append("Changed")
        else:
            lines.append("Changed")
    elif t == "reordered":
        if "move_delta_s" in d:
            try:
                lines.append(f"Moved {format_signed_delta(float(d['move_delta_s']))}")
            except (TypeError, ValueError):
                lines.append("Moved")
        else:
            lines.append("Moved")
    elif t == "renamed":
        old_n = d.get("renamed_from", "")
        new_n = d.get("renamed_to", ch.clip_name)
        lines.append(f'Renamed "{old_n}" → "{new_n}"')
    elif t == "modified":
        pass  # lines come entirely from the volume/title sublines below
    elif t == "gap_changed":
        try:
            lines.append(f"Gap length {d.get('old_gap_s')}s → {d.get('new_gap_s')}s")
        except Exception:
            lines.append("Gap changed")
    elif t == "transition_changed":
        ot, nt = d.get("old_type"), d.get("new_type")
        if ot or nt:
            lines.append(f"Transition {ot or '?'} → {nt or '?'}")
        else:
            lines.append("Transition changed")
    else:
        lines.append("Changed")
    lines.extend(_volume_lines(d))
    lines.extend(_title_lines(d))
    if t == "modified" and not lines:
        lines.append("Changed")
    return lines


def _track_bucket(kind: str) -> str:
    k = str(kind or "").lower()
    if "audio" in k:
        return "audio"
    return "video"


def diff_all_tracks(old: NormalizedTimeline, new: NormalizedTimeline, tolerance_frames: float = 1.0) -> TimelineDiff:
    """Diff every video and audio track, matched by name within kind.

    Each change is tagged details["track"]/details["track_kind"] so the
    sections view can group entries. Added tracks contribute per-item added
    changes (not just a warning); removed tracks contribute per-item removed.
    """
    combined = TimelineDiff()
    totals = {"added": 0, "removed": 0, "trimmed": 0, "reordered": 0, "modified": 0,
              "gap_changed": 0, "transition_changed": 0}
    old_dur_total = 0.0
    new_dur_total = 0.0

    def _kind_tracks(tl: NormalizedTimeline, bucket: str) -> list:
        return [t for t in tl.tracks if _track_bucket(t.kind) == bucket]

    for bucket in ("video", "audio"):
        old_tracks = _kind_tracks(old, bucket)
        new_tracks = _kind_tracks(new, bucket)
        new_by_name = {t.name: t for t in new_tracks}
        for ot in old_tracks:
            nt = new_by_name.get(ot.name)
            if nt is None:
                combined.warnings.append(f"Track removed in new: {ot.name}")
                offs = _track_offsets(ot)
                for item in ot.items:
                    pos = offs[item.index] if 0 <= item.index < len(offs) else None
                    details: dict = {"duration_s": round(_frames_to_seconds(item.duration_frames), 3),
                                     "track": ot.name, "track_kind": bucket}
                    if pos is not None:
                        details["timeline_old_s"] = pos
                    combined.changes.append(
                        ClipChange(type="removed", index_old=item.index, index_new=None,
                                   clip_name=item.name, url=item.url, kind=item.kind,
                                   details=details)
                    )
                    totals["removed"] += 1
                continue
            d = diff_tracks(ot, nt, tolerance_frames)
            for c in d.changes:
                if isinstance(c.details, dict):
                    c.details.setdefault("track", ot.name)
                    c.details.setdefault("track_kind", bucket)
            combined.changes.extend(d.changes)
            combined.warnings.extend(w for w in d.warnings if w not in combined.warnings)
            for k in totals:
                totals[k] += int(d.summary.get(k, 0) or 0)
            old_dur_total += ot.duration_frames()
            new_dur_total += nt.duration_frames()
            combined.tracks_compared.append(ot.name)
        for nt in new_tracks:
            if not any(t.name == nt.name for t in old_tracks):
                combined.warnings.append(f"Track added in new: {nt.name}")
                offs = _track_offsets(nt)
                for item in nt.items:
                    pos = offs[item.index] if 0 <= item.index < len(offs) else None
                    details = {"duration_s": round(_frames_to_seconds(item.duration_frames), 3),
                               "track": nt.name, "track_kind": bucket}
                    if pos is not None:
                        details["timeline_start_s"] = pos
                    combined.changes.append(
                        ClipChange(type="added", index_old=None, index_new=item.index,
                                   clip_name=item.name, url=item.url, kind=item.kind,
                                   details=details)
                    )
                    totals["added"] += 1
                old_d = 0.0
                new_d = nt.duration_frames()
                old_dur_total += old_d
                new_dur_total += new_d
                combined.tracks_compared.append(nt.name)

    # Positions need per-track offsets — matched-track changes were already
    # annotated inside diff_tracks; added/removed-track items were annotated
    # at construction above.
    delta = new_dur_total - old_dur_total
    combined.summary = {
        **totals,
        "total_changes": len(combined.changes),
        "old_duration_s": round(_frames_to_seconds(old_dur_total), 3),
        "new_duration_s": round(_frames_to_seconds(new_dur_total), 3),
        "runtime_delta_s": round(_frames_to_seconds(delta), 3),
    }
    return combined


def _lookup_change_items(old, new, track_name, bucket, change):
    """(old_item, new_item) for a change, resolved by index (best effort)."""
    old_item = new_item = None
    for tl, want_new in ((new, True), (old, False)):
        try:
            tracks = [t for t in tl.tracks if _track_bucket(t.kind) == bucket and t.name == track_name]
            if not tracks:
                # Fall back to any track with that name (bucket mismatch).
                tracks = [t for t in tl.tracks if t.name == track_name]
            if not tracks:
                continue
            track = tracks[0]
            idx = change.index_new if want_new else change.index_old
            if idx is None:
                continue
            if 0 <= idx < len(track.items):
                if want_new:
                    new_item = track.items[idx]
                else:
                    old_item = track.items[idx]
        except Exception:
            continue
    return old_item, new_item


# Empty space appearing, vanishing, or changing by this much is editorially
# meaningful on its own; smaller gap wiggles are usually byproducts of
# neighboring clip edits and stay out of the sections view.
GAP_SIGNIFICANT_S = 5.0


def _gap_magnitude(change, old_item=None, new_item=None) -> float | None:
    """Size (seconds) behind a gap entry: duration for added/removed,
    absolute change for trims."""
    d = change.details if isinstance(getattr(change, "details", None), dict) else {}
    for key in ("duration_s",):
        try:
            if d.get(key) is not None:
                return abs(float(d[key]))
        except (TypeError, ValueError):
            pass
    try:
        if d.get("old_gap_s") is not None and d.get("new_gap_s") is not None:
            return abs(float(d["new_gap_s"]) - float(d["old_gap_s"]))
    except (TypeError, ValueError):
        pass
    try:
        if d.get("delta_s") is not None:
            return abs(float(d["delta_s"]))
    except (TypeError, ValueError):
        pass
    try:
        item = new_item if new_item is not None else old_item
        if item is not None:
            return abs(_frames_to_seconds(item.duration_frames))
    except Exception:
        pass
    return None


def _gap_significant(change, old_item=None, new_item=None) -> bool:
    mag = _gap_magnitude(change, old_item, new_item)
    return mag is not None and mag >= GAP_SIGNIFICANT_S


def _entry_identity(change) -> str:
    """Stable identity for grouping/disambiguation (mirrors loose identity)."""
    url = getattr(change, "url", "") or ""
    name = getattr(change, "clip_name", "") or ""
    kind = getattr(change, "kind", "") or ""
    if url:
        return f"{kind}:clip:{url}"
    return f"{kind}:name:{name}"


def _source_range_s(item) -> tuple[float, float] | None:
    """Source in/out (seconds) identifying WHICH segment of the media a clip
    instance uses — from original timebase when available."""
    if item is None:
        return None
    try:
        rate = float(getattr(item, "orig_rate", 0) or 0)
        if rate > 0 and getattr(item, "orig_start", None) is not None \
                and getattr(item, "orig_duration", None) is not None:
            s = float(item.orig_start) / rate
            return (round(s, 3), round(s + float(item.orig_duration) / rate, 3))
    except (TypeError, ValueError):
        pass
    try:
        start = float(getattr(item, "start_frames", 0) or 0) / NORMALIZED_RATE
        dur = float(getattr(item, "duration_frames", 0) or 0) / NORMALIZED_RATE
        return (round(start, 3), round(start + dur, 3))
    except (TypeError, ValueError):
        return None


def _source_line(item) -> str | None:
    rng = _source_range_s(item)
    if not rng:
        return None
    return f"Source: {format_timecode(rng[0])} – {format_timecode(rng[1])}"


def build_sections(old, new, diff) -> list[dict]:
    """Group a diff's changes into track sections for the What changed view.

    Returns [{track, kind, entries}] with kind in video/audio/text. Video and
    audio sections follow timeline track order and carry timeline timecodes;
    title-clip changes across all tracks collect into a single TEXT section.
    Tracks without changes are omitted. Gaps are infrastructure, not content:
    only significant ones (empty space appearing/vanishing/changing by
    GAP_SIGNIFICANT_S or more) survive — the rest still count in the gap note
    via the flat changes list. Adjacent added/removed runs of the same clip
    merge into one entry ("+ Added ×3"); repeated identities that stay
    separate get a Source range line so instances are distinguishable.
    Pure function of the diff.
    """
    buckets: dict[tuple[str, str], list] = {}
    text_entries: list[dict] = []
    changes = list(getattr(diff, "changes", []) or [])
    default_track = (getattr(diff, "tracks_compared", None) or [None])[0]

    # Working records: [entry, old_item, new_item, identity, mergeable]
    records: list[list] = []
    for c in changes:
        d = c.details if isinstance(getattr(c, "details", None), dict) else {}
        track = d.get("track") or default_track or "Video 1"
        bucket = d.get("track_kind") or "video"
        if bucket not in ("video", "audio"):
            bucket = "video"
        old_item, new_item = _lookup_change_items(old, new, track, bucket, c)
        is_title = bool(d.get("is_title"))
        if not is_title:
            try:
                is_title = bool((old_item is not None and old_item.is_title)
                                or (new_item is not None and new_item.is_title))
            except Exception:
                is_title = False
        pos = d.get("timeline_start_s", d.get("timeline_old_s"))
        try:
            pos_f = float(pos) if pos is not None else None
        except (TypeError, ValueError):
            pos_f = None
        if c.kind == "gap":
            if c.clip_name and not c.clip_name.startswith("Gap"):
                label = f"Gap: {c.clip_name}"
            else:
                label = "Gap"
        elif c.kind == "transition":
            label = "Transition"
        elif is_title:
            label = None
        else:
            label = f"Clip: {c.clip_name or '(unnamed)'}"
        entry = {
            "timecode_s": pos_f,
            "timecode": format_timecode(pos_f) if pos_f is not None else None,
            "label": label,
            "type": c.type,
            "kind": c.kind,
            "lines": change_lines(c, old_item, new_item),
        }
        if c.kind == "gap" and not _gap_significant(c, old_item, new_item):
            continue
        ident = _entry_identity(c)
        mergeable = c.type in ("added", "removed") and not is_title
        records.append([entry, old_item, new_item, ident, mergeable, is_title, bucket, track])

    def _is_gap_rec(rec) -> bool:
        return rec[0].get("kind") == "gap"

    def _gap_dur(rec) -> float | None:
        item = rec[2] if rec[2] is not None else rec[1]
        try:
            if item is not None:
                return float(item.duration_frames)
        except (TypeError, ValueError):
            pass
        return None

    # A gap that merely moved is spacing, not an edit: drop reordered gaps,
    # and collapse removed+added gap pairs with equal duration (neighboring
    # inserts rename all following gaps, so match by duration, not name).
    kept: list[list] = []
    removed_gaps: dict[tuple[str, str], list] = {}
    for rec in records:
        if _is_gap_rec(rec) and rec[0].get("type") == "reordered":
            continue
        if _is_gap_rec(rec) and rec[0].get("type") == "removed":
            removed_gaps.setdefault((rec[6], rec[7]), []).append(rec)
            continue
        kept.append(rec)
    records = []
    for rec in kept:
        if _is_gap_rec(rec) and rec[0].get("type") == "added":
            d = _gap_dur(rec)
            mates = removed_gaps.get((rec[6], rec[7]), [])
            paired = None
            if d is not None:
                for m in mates:
                    md = _gap_dur(m)
                    if md is not None and abs(md - d) <= 1.0:
                        paired = m
                        break
            if paired is not None:
                mates.remove(paired)
                continue
        records.append(rec)
    for mates in removed_gaps.values():
        records.extend(mates)

    # Merge adjacent added/removed runs of the same clip instance family
    # ("Vid 5.mp4 ×3") instead of unexplained duplicate rows.
    merged: list[list] = []
    for rec in records:
        entry = rec[0]
        if (rec[4] and merged and merged[-1][4]
                and merged[-1][0]["type"] == entry["type"]
                and merged[-1][3] == rec[3]
                and merged[-1][7] == rec[7] and merged[-1][6] == rec[6]):
            prev = merged[-1][0]
            prev["_count"] = prev.get("_count", 1) + 1
            n = prev["_count"]
            verb = "+ Added" if prev["type"] == "added" else "- Removed"
            prev["lines"] = [f"{verb} ×{n}"]
            continue
        merged.append(rec)

    # Disambiguate repeated instances that stay separate: a Source range line
    # (timeline position alone can't tell two "Vid 5.mp4" rows apart). Clips
    # only — gaps/transitions have no meaningful source range, and title text
    # already identifies title entries.
    counts: dict[str, int] = {}
    for rec in merged:
        counts[rec[3]] = counts.get(rec[3], 0) + 1
    final: list[list] = []
    for rec in merged:
        entry = rec[0]
        if (counts.get(rec[3], 0) > 1 and not rec[5] and "_count" not in entry
                and entry.get("kind") == "clip"):
            src = _source_line(rec[2] if rec[2] is not None else rec[1])
            if src:
                entry = dict(entry)
                entry["lines"] = list(entry["lines"]) + [src]
                rec = list(rec)
                rec[0] = entry
        final.append(rec)

    for rec in final:
        entry, _, _, _, _, is_title, bucket, track = rec
        entry.pop("_count", None)
        if is_title:
            text_entries.append(entry)
        else:
            buckets.setdefault((bucket, track), []).append(entry)

    sections: list[dict] = []

    def _track_order(bucket: str) -> list[str]:
        names: list[str] = []
        for tl in (old, new):
            try:
                for t in tl.tracks:
                    if _track_bucket(t.kind) == bucket and t.name not in names:
                        names.append(t.name)
            except Exception:
                continue
        for _, name in buckets:
            if _ == bucket and name not in names:
                names.append(name)
        return names

    for bucket in ("video", "audio"):
        for name in _track_order(bucket):
            entries = buckets.get((bucket, name), [])
            if not entries:
                continue
            entries.sort(key=lambda e: (e["timecode_s"] is None, e["timecode_s"] or 0.0))
            sections.append({"track": name, "kind": bucket, "entries": entries})
    if text_entries:
        text_entries.sort(key=lambda e: (e["timecode_s"] is None, e["timecode_s"] or 0.0))
        sections.append({"track": "Text", "kind": "text", "entries": text_entries})
    return sections


def _plural_tracks(n: int, kind: str) -> str:
    """'1 video track' vs '2 video tracks'. Kind is 'video track', 'audio track' or 'track'."""
    return f"{n} {kind}{'' if n == 1 else 's'}"


def _format_track_names(names: list[str], max_show: int = 4) -> str:
    """'Video 2, Video 3' or 'A, B, C and 2 more' when long."""
    if len(names) <= max_show:
        return ", ".join(names)
    shown = ", ".join(names[:max_show])
    return f"{shown} and {len(names) - max_show} more"


def _describe_track_list_change(old: NormalizedTimeline, new: NormalizedTimeline) -> str:
    """Plain-English description of added/removed tracks, e.g.
    'Added 2 video tracks (Video 2, Video 3) and 1 audio track (Audio 3)'.
    Never dumps raw Python arrays.
    """
    old_names = [t.name for t in old.tracks]
    new_names = [t.name for t in new.tracks]
    old_set, new_set = set(old_names), set(new_names)
    added = [n for n in new_names if n not in old_set]
    removed = [n for n in old_names if n not in new_set]

    new_kind = {t.name: t.kind for t in new.tracks}
    old_kind = {t.name: t.kind for t in old.tracks}

    def _group(names: list[str], lookup: dict) -> tuple[list[str], list[str], list[str]]:
        video, audio, other = [], [], []
        for n in names:
            k = lookup.get(n, "")
            if k == "Video":
                video.append(n)
            elif k == "Audio":
                audio.append(n)
            else:
                other.append(n)
        return video, audio, other

    added_video, added_audio, added_other = _group(added, new_kind)
    removed_video, removed_audio, removed_other = _group(removed, old_kind)

    def _join_groups(groups: list[tuple[list[str], str]], verb: str) -> str:
        # groups: [(names, kind_label)] non-empty only, e.g. [(['Video 2','Video 3'], 'video track')]
        parts = []
        for names, kind_label in groups:
            parts.append(f"{_plural_tracks(len(names), kind_label)} ({_format_track_names(names)})")
        if not parts:
            return ""
        if len(parts) == 1:
            return f"{verb} {parts[0]}"
        # "Added X and Y" — verb only on first part
        return f"{verb} {parts[0]} and " + " and ".join(parts[1:])

    added_groups = [
        (added_video, "video track"),
        (added_audio, "audio track"),
        (added_other, "track"),
    ]
    added_groups = [(names, kind) for names, kind in added_groups if names]
    removed_groups = [
        (removed_video, "video track"),
        (removed_audio, "audio track"),
        (removed_other, "track"),
    ]
    removed_groups = [(names, kind) for names, kind in removed_groups if names]

    added_sentence = _join_groups(added_groups, "Added") if added_groups else ""
    removed_sentence = _join_groups(removed_groups, "Removed") if removed_groups else ""

    if added_sentence and removed_sentence:
        # Lowercase second verb after semicolon for natural reading
        removed_sentence = removed_sentence[0].lower() + removed_sentence[1:]
        return f"{added_sentence}; {removed_sentence}"
    if added_sentence:
        return added_sentence
    if removed_sentence:
        return removed_sentence
    # Fallback (sets differ but no clean added/removed, e.g. duplicates)
    return f"Tracks changed — now {len(new_names)} tracks (was {len(old_names)} tracks)"


def _describe_track_counts(old: NormalizedTimeline, new: NormalizedTimeline) -> str:
    """Scope note when video/audio track counts differ, e.g.
    'Now 3 video tracks + 3 audio tracks (was 1 video track + 2 audio tracks) — ...'."""
    old_v, old_a = len(old.video_tracks()), len(old.audio_tracks())
    new_v, new_a = len(new.video_tracks()), len(new.audio_tracks())
    return (
        f"Now {_plural_tracks(new_v, 'video track')} + {_plural_tracks(new_a, 'audio track')} "
        f"(was {_plural_tracks(old_v, 'video track')} + {_plural_tracks(old_a, 'audio track')}) "
        f"— only the main track is compared, check the others manually"
    )


def diff_timelines(
    old: NormalizedTimeline,
    new: NormalizedTimeline,
    track_name: Optional[str] = None,
    compare_all_video_tracks: bool = False,
) -> TimelineDiff:
    """Diff two timelines.

    By default diffs the main video track. If compare_all_video_tracks is True,
    diffs each video track separately and concatenates results.
    """
    # Check track mismatch warnings (plain English, no raw array dumps)
    warnings = []
    old_names = [t.name for t in old.tracks]
    new_names = [t.name for t in new.tracks]
    if set(old_names) != set(new_names):
        warnings.append(_describe_track_list_change(old, new))

    if track_name:
        old_track = next((t for t in old.tracks if t.name == track_name), None)
        new_track = next((t for t in new.tracks if t.name == track_name), None)
        if not old_track or not new_track:
            raise ValueError(f"Track not found: {track_name} (old: {old_names}, new: {new_names})")
        d = diff_tracks(old_track, new_track)
        d.warnings.extend(warnings)
        return d

    if compare_all_video_tracks:
        combined = TimelineDiff(warnings=warnings)
        total_added = total_removed = total_trimmed = total_reordered = 0
        old_dur_total = new_dur_total = 0
        for ot in old.video_tracks():
            nt = next((t for t in new.video_tracks() if t.name == ot.name), None)
            if nt is None:
                # Track removed
                combined.warnings.append(f"Track removed in new: {ot.name}")
                for item in ot.items:
                    combined.changes.append(
                        ClipChange(type="removed", index_old=item.index, clip_name=item.name, url=item.url, kind=item.kind, details={"track": ot.name})
                    )
                continue
            d = diff_tracks(ot, nt)
            combined.changes.extend(d.changes)
            total_added += d.summary.get("added", 0)
            total_removed += d.summary.get("removed", 0)
            total_trimmed += d.summary.get("trimmed", 0)
            total_reordered += d.summary.get("reordered", 0)
            old_dur_total += ot.duration_frames()
            new_dur_total += nt.duration_frames()
            combined.tracks_compared.append(ot.name)
        # Check for new tracks added
        for nt in new.video_tracks():
            if not any(t.name == nt.name for t in old.video_tracks()):
                combined.warnings.append(f"Track added in new: {nt.name}")

        delta = new_dur_total - old_dur_total
        combined.summary = {
            "added": total_added,
            "removed": total_removed,
            "trimmed": total_trimmed,
            "reordered": total_reordered,
            "total_changes": len(combined.changes),
            "old_duration_s": round(_frames_to_seconds(old_dur_total), 3),
            "new_duration_s": round(_frames_to_seconds(new_dur_total), 3),
            "runtime_delta_s": round(_frames_to_seconds(delta), 3),
        }
        return combined

    # Default: main track
    old_main = old.main_track()
    new_main = new.main_track()
    if not old_main and not new_main:
        return TimelineDiff(summary={"added": 0, "removed": 0, "trimmed": 0, "reordered": 0, "total_changes": 0}, warnings=["No video tracks found"])
    if not old_main:
        # All added (e.g. a timeline's first save vs an empty timeline)
        d = TimelineDiff(tracks_compared=[new_main.name] if new_main else [], warnings=warnings)
        for item in new_main.items:
            d.changes.append(ClipChange(type="added", index_new=item.index, clip_name=item.name, url=item.url, kind=item.kind))
        new_dur = new_main.duration_frames()
        d.summary = {"added": len(new_main.items), "removed": 0, "trimmed": 0, "reordered": 0, "total_changes": len(d.changes),
                     "old_duration_s": 0.0, "new_duration_s": round(_frames_to_seconds(new_dur), 3), "runtime_delta_s": round(_frames_to_seconds(new_dur), 3)}
        return d
    if not new_main:
        d = TimelineDiff(tracks_compared=[old_main.name], warnings=warnings)
        for item in old_main.items:
            d.changes.append(ClipChange(type="removed", index_old=item.index, clip_name=item.name, url=item.url, kind=item.kind))
        old_dur = old_main.duration_frames()
        d.summary = {"added": 0, "removed": len(old_main.items), "trimmed": 0, "reordered": 0, "total_changes": len(d.changes),
                     "old_duration_s": round(_frames_to_seconds(old_dur), 3), "new_duration_s": 0.0, "runtime_delta_s": round(_frames_to_seconds(-old_dur), 3)}
        return d

    d = diff_tracks(old_main, new_main)
    d.warnings.extend(warnings)
    # Also warn if audio/video track counts differ (flag, don't guess)
    if len(old.video_tracks()) != len(new.video_tracks()) or len(old.audio_tracks()) != len(new.audio_tracks()):
        d.warnings.append(_describe_track_counts(old, new))
    return d


def format_text(diff: TimelineDiff, old_name: str = "old", new_name: str = "new") -> str:
    """Plain-English summary for terminal."""
    s = diff.summary
    lines = []
    name = f"{old_name} → {new_name}"
    lines.append(f"Diff: {name}")
    if diff.tracks_compared:
        lines.append(f"Tracks: {', '.join(diff.tracks_compared)}")
    # Summary line like "3 clips trimmed, 1 removed, runtime −12s"
    parts = []
    if s.get("added"):
        parts.append(f"{s['added']} added")
    if s.get("removed"):
        parts.append(f"{s['removed']} removed")
    if s.get("trimmed"):
        parts.append(f"{s['trimmed']} trimmed")
    if s.get("reordered"):
        parts.append(f"{s['reordered']} reordered")
    if s.get("modified"):
        parts.append(f"{s['modified']} modified")
    if s.get("gap_changed"):
        parts.append(f"{s['gap_changed']} gaps changed")
    if s.get("transition_changed"):
        parts.append(f"{s['transition_changed']} transitions changed")
    if not parts:
        parts.append("no changes")
    lines.append(f"Summary: {', '.join(parts)}")
    lines.append(f"Runtime: {s.get('old_duration_s', 0)}s → {s.get('new_duration_s', 0)}s (Δ {s.get('runtime_delta_s', 0):+g}s)")

    if diff.warnings:
        lines.append("Warnings:")
        for w in diff.warnings:
            lines.append(f"  ! {w}")

    if not diff.changes:
        lines.append("(no clip-level changes)")
    else:
        lines.append("")
        lines.append("Changes:")
        for ch in diff.changes:
            if ch.type == "added":
                lines.append(f"  + [{ch.index_new}] {ch.clip_name or '(unnamed)'} ({ch.url or ch.kind}) — added ({ch.details.get('duration_s', '?')}s)")
            elif ch.type == "removed":
                lines.append(f"  - [{ch.index_old}] {ch.clip_name or '(unnamed)'} ({ch.url or ch.kind}) — removed")
            elif ch.type == "trimmed":
                d = ch.details
                delta = d.get("delta_s", 0)
                sign = "+" if delta >= 0 else ""
                lines.append(f"  ~ [{ch.index_old}->{ch.index_new}] {ch.clip_name} ({ch.url}) — trimmed {sign}{delta}s ({d.get('old_duration_s')}s → {d.get('new_duration_s')}s)")
            elif ch.type == "reordered":
                lines.append(f"  ↔ [{ch.index_old}->{ch.index_new}] {ch.clip_name} ({ch.url}) — moved")
            elif ch.type == "renamed":
                lines.append(f"  ✎ [{ch.index_old}->{ch.index_new}] {ch.details.get('renamed_from')} → {ch.details.get('renamed_to')} ({ch.url}) — renamed")
            elif ch.type == "gap_changed":
                lines.append(f"  ~ gap [{ch.index_old}->{ch.index_new}] — {ch.details.get('old_gap_s')}s → {ch.details.get('new_gap_s')}s")
            elif ch.type == "transition_changed":
                lines.append(f"  ~ transition [{ch.index_old}->{ch.index_new}] {ch.details.get('old_type')} → {ch.details.get('new_type')}")
            else:
                lines.append(f"  ? [{ch.index_old}->{ch.index_new}] {ch.clip_name} — {ch.type} {ch.details}")

    return "\n".join(lines)


def changelog_line(diff: TimelineDiff) -> str:
    """One-line human summary for commit messages."""
    s = diff.summary
    parts = []
    if s.get("added"):
        parts.append(f"{s['added']} added")
    if s.get("removed"):
        parts.append(f"{s['removed']} removed")
    if s.get("trimmed"):
        parts.append(f"{s['trimmed']} trimmed")
    if s.get("reordered"):
        parts.append(f"{s['reordered']} reordered")
    if not parts:
        return f"No changes (runtime {s.get('new_duration_s', 0)}s)"
    delta = s.get("runtime_delta_s", 0)
    return f"{', '.join(parts)}, runtime {delta:+g}s ({s.get('old_duration_s', 0)}s → {s.get('new_duration_s', 0)}s)"
