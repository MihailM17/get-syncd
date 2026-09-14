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
    return details


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
                    # Determine change type
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
                                    details=_describe_trim(oc, nc),
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
                                    details=_describe_trim(oc, nc),
                                )
                            )
                        trimmed += 1

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
                            details={**_describe_trim(oc, nc), "also_reordered": True},
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
                            details={"from_index": oi, "to_index": nj, "loose_identity": ident},
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
                        details={**_describe_trim(oc, nc), "also_reordered": True},
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
                        details={"from_index": rc.index_old, "to_index": match.index_new},
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
        "gap_changed": gap_changed,
        "transition_changed": transition_changed,
        "total_changes": len(result.changes),
        "old_duration_s": round(_frames_to_seconds(old_dur), 3),
        "new_duration_s": round(_frames_to_seconds(new_dur), 3),
        "runtime_delta_s": round(delta_s, 3),
        "runtime_delta_frames": round(delta_frames, 1),
    }

    return result


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
