"""Parse OTIO files into a normalized, diff-friendly model.

Handles:
- Timeline -> Stack(tracks) -> Track -> [Clip | Gap | Transition | Stack]
- Clip identity via target_url + name (with fallback)
- Time normalization via RationalTime rescaling
- Gaps, Transitions, nested Stacks (flattened or flagged)
- Multi-track awareness (main video track focused, others reported)
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import opentimelineio as otio


# Fixed rate for normalization; 600 is divisible by 24, 25, 30, 60
NORMALIZED_RATE = 600.0


@dataclass
class NormalizedClip:
    """Single item on a track, diff-friendly."""

    kind: str  # "clip" | "gap" | "transition" | "stack"
    index: int  # position in original track
    name: str
    url: str  # target_url for clips, "" for gaps/transitions
    # Normalized times (in NORMALIZED_RATE frames)
    start_frames: Optional[float] = None  # source start (None for gap/transition)
    duration_frames: float = 0.0
    rate: float = NORMALIZED_RATE
    # Keep original for display
    orig_start: Optional[float] = None
    orig_duration: Optional[float] = None
    orig_rate: Optional[float] = None
    # Transition specifics
    transition_type: Optional[str] = None
    in_offset_frames: Optional[float] = None
    out_offset_frames: Optional[float] = None
    # Clip extras
    enabled: bool = True
    metadata: dict = field(default_factory=dict)
    # For stacks / nested sequences
    children: Optional[list] = None

    def identity_key(self) -> str:
        """Key used for sequence diff matching (stable, hashable)."""
        if self.kind == "clip":
            # Prefer URL; fall back to name; include both for uniqueness
            if self.url:
                return f"clip:{self.url}#{self.name}"
            return f"clip:name:{self.name}"
        if self.kind == "gap":
            return f"gap:{self.index}:{self.duration_frames}"
        if self.kind == "transition":
            return f"transition:{self.transition_type}:{self.in_offset_frames}:{self.out_offset_frames}"
        if self.kind == "stack":
            return f"stack:{self.name}:{self.index}"
        return f"{self.kind}:{self.index}"

    def loose_identity(self) -> str:
        """Looser key for reorder detection: match by media URL only.
        Two clips with same URL but different name/trim still match as 'same clip moved'.
        """
        if self.kind == "clip":
            if self.url:
                return f"clip:{self.url}"
            return f"clip:name:{self.name}"
        return self.identity_key()


@dataclass
class NormalizedTrack:
    name: str
    kind: str  # "Video" | "Audio" | "unknown"
    items: list[NormalizedClip] = field(default_factory=list)

    def duration_frames(self) -> float:
        return sum(i.duration_frames for i in self.items)

    def clip_count(self) -> int:
        return sum(1 for i in self.items if i.kind == "clip")


@dataclass
class NormalizedTimeline:
    name: str
    tracks: list[NormalizedTrack] = field(default_factory=list)
    global_start_frames: Optional[float] = None
    source_path: Optional[str] = None

    def main_track(self) -> Optional[NormalizedTrack]:
        """Primary video track (first Video track)."""
        for t in self.tracks:
            if t.kind == "Video":
                return t
        return self.tracks[0] if self.tracks else None

    def video_tracks(self) -> list[NormalizedTrack]:
        return [t for t in self.tracks if t.kind == "Video"]

    def audio_tracks(self) -> list[NormalizedTrack]:
        return [t for t in self.tracks if t.kind == "Audio"]


def _rescale(value: float, from_rate: float, to_rate: float = NORMALIZED_RATE) -> float:
    if from_rate == to_rate or from_rate == 0:
        return float(value)
    return float(value) * (to_rate / from_rate)


def _parse_item(item, index: int) -> NormalizedClip:
    schema = item.schema_name() if hasattr(item, "schema_name") else type(item).__name__

    if isinstance(item, otio.schema.Clip):
        # Extract URL from media_references
        url = ""
        try:
            mr = item.media_reference
            if mr is not None and hasattr(mr, "target_url"):
                url = mr.target_url or ""
            # Also check media_references dict
            if not url and hasattr(item, "media_references"):
                refs = item.media_references
                if refs:
                    for k, v in refs.items():
                        if hasattr(v, "target_url") and v.target_url:
                            url = v.target_url
                            break
        except Exception:
            pass

        # Extract source_range
        start_frames = None
        duration_frames = 0.0
        orig_start = None
        orig_duration = None
        orig_rate = None
        if item.source_range is not None:
            rt_start = item.source_range.start_time
            rt_dur = item.source_range.duration
            orig_start = float(rt_start.value)
            orig_duration = float(rt_dur.value)
            orig_rate = float(rt_start.rate)
            start_frames = _rescale(float(rt_start.value), float(rt_start.rate))
            duration_frames = _rescale(float(rt_dur.value), float(rt_dur.rate))
        else:
            # No source_range — use available_range or 0
            # Try duration() fallback
            try:
                d = item.duration()
                duration_frames = _rescale(float(d.value), float(d.rate))
                orig_duration = float(d.value)
                orig_rate = float(d.rate)
            except Exception:
                pass

        return NormalizedClip(
            kind="clip",
            index=index,
            name=item.name or "",
            url=url or "",
            start_frames=start_frames,
            duration_frames=duration_frames,
            orig_start=orig_start,
            orig_duration=orig_duration,
            orig_rate=orig_rate,
            enabled=bool(getattr(item, "enabled", True)),
            metadata=dict(getattr(item, "metadata", {}) or {}),
        )

    if isinstance(item, otio.schema.Gap):
        duration_frames = 0.0
        orig_duration = None
        orig_rate = None
        if item.source_range is not None:
            rt_dur = item.source_range.duration
            orig_duration = float(rt_dur.value)
            orig_rate = float(rt_dur.rate)
            duration_frames = _rescale(float(rt_dur.value), float(rt_dur.rate))
        else:
            try:
                d = item.duration()
                duration_frames = _rescale(float(d.value), float(d.rate))
                orig_duration = float(d.value)
                orig_rate = float(d.rate)
            except Exception:
                pass
        return NormalizedClip(
            kind="gap",
            index=index,
            name=item.name or f"Gap_{index}",
            url="",
            duration_frames=duration_frames,
            orig_duration=orig_duration,
            orig_rate=orig_rate,
            enabled=bool(getattr(item, "enabled", True)),
        )

    if isinstance(item, otio.schema.Transition):
        in_off = None
        out_off = None
        if hasattr(item, "in_offset") and item.in_offset is not None:
            in_off = _rescale(float(item.in_offset.value), float(item.in_offset.rate))
        if hasattr(item, "out_offset") and item.out_offset is not None:
            out_off = _rescale(float(item.out_offset.value), float(item.out_offset.rate))
        # Transition duration is in+out
        dur = (in_off or 0) + (out_off or 0)
        return NormalizedClip(
            kind="transition",
            index=index,
            name=item.name or "",
            url="",
            duration_frames=dur,
            transition_type=str(getattr(item, "transition_type", "")),
            in_offset_frames=in_off,
            out_offset_frames=out_off,
        )

    if isinstance(item, otio.schema.Stack):
        # Nested sequence — flatten marker
        children = []
        for ci, child in enumerate(item):
            children.append(_parse_item(child, ci))
        dur = 0.0
        try:
            d = item.duration()
            dur = _rescale(float(d.value), float(d.rate))
        except Exception:
            pass
        return NormalizedClip(
            kind="stack",
            index=index,
            name=item.name or f"Stack_{index}",
            url="",
            duration_frames=dur,
            children=children,
        )

    # Fallback for unknown types (e.g., GeneratorReference as clip-like)
    dur = 0.0
    try:
        d = item.duration()
        dur = _rescale(float(d.value), float(d.rate))
    except Exception:
        pass
    return NormalizedClip(
        kind="unknown",
        index=index,
        name=getattr(item, "name", f"Unknown_{index}"),
        url="",
        duration_frames=dur,
    )


def parse_otio_file(path: str | Path) -> NormalizedTimeline:
    """Parse an .otio file from disk."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"OTIO file not found: {path}")
    try:
        timeline = otio.adapters.read_from_file(str(path))
    except Exception as e:
        raise ValueError(f"Failed to parse OTIO file {path}: {e}") from e
    return parse_timeline(timeline, source_path=str(path))


def parse_otio_string(data: str, source_path: Optional[str] = None) -> NormalizedTimeline:
    """Parse OTIO JSON string."""
    try:
        timeline = otio.adapters.read_from_string(data, adapter_name="otio_json")
    except Exception as e:
        raise ValueError(f"Failed to parse OTIO string: {e}") from e
    return parse_timeline(timeline, source_path=source_path)


def parse_timeline(timeline, source_path: Optional[str] = None) -> NormalizedTimeline:
    """Convert an otio.schema.Timeline into NormalizedTimeline."""
    name = getattr(timeline, "name", "") or "Untitled"

    global_start = None
    if getattr(timeline, "global_start_time", None) is not None:
        gst = timeline.global_start_time
        try:
            global_start = _rescale(float(gst.value), float(gst.rate))
        except Exception:
            pass

    tracks: list[NormalizedTrack] = []

    # timeline.tracks is a Stack
    stack = getattr(timeline, "tracks", None)
    if stack is not None:
        for track in stack:
            # Track may be a Track or Stack
            if isinstance(track, otio.schema.Track):
                kind = str(getattr(track, "kind", "unknown"))
                # Normalize "Video"/"Audio"
                if "Video" in kind:
                    kind = "Video"
                elif "Audio" in kind:
                    kind = "Audio"
                items: list[NormalizedClip] = []
                for idx, child in enumerate(track):
                    items.append(_parse_item(child, idx))
                tracks.append(NormalizedTrack(name=track.name or f"Track_{len(tracks)}", kind=kind, items=items))
            elif isinstance(track, otio.schema.Stack):
                # Nested stack as a track-like container
                for sub in track:
                    if isinstance(sub, otio.schema.Track):
                        kind = str(getattr(sub, "kind", "unknown"))
                        if "Video" in kind:
                            kind = "Video"
                        elif "Audio" in kind:
                            kind = "Audio"
                        items = [_parse_item(c, i) for i, c in enumerate(sub)]
                        tracks.append(NormalizedTrack(name=sub.name or f"Track_{len(tracks)}", kind=kind, items=items))

    return NormalizedTimeline(name=name, tracks=tracks, global_start_frames=global_start, source_path=source_path)


def timeline_to_frames(timeline: NormalizedTimeline, track_name: Optional[str] = None) -> float:
    """Total duration in NORMALIZED_RATE frames for a given track or main track."""
    if track_name:
        for t in timeline.tracks:
            if t.name == track_name:
                return t.duration_frames()
        raise ValueError(f"Track not found: {track_name}")
    main = timeline.main_track()
    return main.duration_frames() if main else 0.0
