"""Regression tests for the What-changed timeline view.

Covers, per the approved plan:
- timeline timecodes (new-side for added/moved/trimmed, old-side for removed)
- multi-track diffs (all video + audio tracks, sections only for changed tracks)
- trim direction wording (beginning / end / both / extended / slip)
- moved clips with signed position deltas
- volume changes (only when actually differing, 1-decimal)
- title text changes (incl. nested compounds) + extraction incl. AnyDictionary
"""
import sys

sys.path.insert(0, "src")

import pathlib

import pytest

from get_syncd.otio_parse import (
    NormalizedClip,
    NormalizedTimeline,
    NormalizedTrack,
)
from get_syncd import diff as D


@pytest.fixture(autouse=True)
def _allow_tmp_repos(monkeypatch):
    from get_syncd import api as _api

    monkeypatch.setattr(_api, "is_repo_allowed", lambda repo: True)


RATE = 600.0


def _clip(name, dur_s, url="", start_s=0.0, idx=0, volume_db=None,
          title_text=None, is_title=False, kind="clip"):
    return NormalizedClip(
        kind=kind, index=idx, name=name, url=url or f"file://{name}",
        start_frames=start_s * RATE, duration_frames=dur_s * RATE,
        orig_start=start_s * 30.0, orig_duration=dur_s * 30.0, orig_rate=30.0,
        volume_db=volume_db, is_title=is_title, title_text=title_text,
        title_texts=[title_text] if title_text else [],
    )


def _track(name, kind, clips):
    for i, c in enumerate(clips):
        c.index = i
    return NormalizedTrack(name=name, kind=kind, items=clips)


def _tl(*tracks):
    return NormalizedTimeline(name="T", tracks=list(tracks))


def _lines_for(old, new):
    d = D.diff_all_tracks(old, new)
    out = {}
    for c in d.changes:
        out.setdefault(c.type, []).append(c)
    return d, out


# --- timecodes -----------------------------------------------------------

def test_added_clip_timecode_is_new_position():
    old = _tl(_track("Video 1", "Video", [_clip("A", 10.0), _clip("B", 5.0)]))
    new = _tl(_track("Video 1", "Video", [_clip("A", 10.0), _clip("X", 4.0), _clip("B", 5.0)]))
    d, by_type = _lines_for(old, new)
    assert [c.clip_name for c in by_type.get("added", [])] == ["X"]
    secs = D.build_sections(old, new, d)
    assert len(secs) == 1 and secs[0]["track"] == "Video 1"
    entry = secs[0]["entries"][0]
    assert entry["timecode_s"] == 10.0
    assert entry["timecode"] == "00:00:10.000"
    assert entry["label"] == "Clip: X"


def test_removed_clip_timecode_is_old_position():
    old = _tl(_track("Video 1", "Video", [_clip("A", 10.0), _clip("R", 5.0), _clip("B", 5.0)]))
    new = _tl(_track("Video 1", "Video", [_clip("A", 10.0), _clip("B", 5.0)]))
    d, by_type = _lines_for(old, new)
    assert [c.clip_name for c in by_type.get("removed", [])] == ["R"]
    secs = D.build_sections(old, new, d)
    entry = secs[0]["entries"][0]
    assert entry["timecode_s"] == 10.0
    assert entry["timecode"] == "00:00:10.000"


def test_timecode_format_edge_rounds_up():
    assert D.format_timecode(59.99996) == "00:01:00.000"
    assert D.format_timecode(12.43) == "00:00:12.430"
    assert D.format_timecode(3723.5) == "01:02:03.500"
    assert D.format_signed_delta(3.2) == "+00:00:03.200"
    assert D.format_signed_delta(-3.2) == "-00:00:03.200"


# --- multi-track ----------------------------------------------------------

def test_audio_only_change_yields_only_audio_section():
    old = _tl(
        _track("Video 1", "Video", [_clip("A", 10.0)]),
        _track("Audio 1", "Audio", [_clip("M", 10.0)]),
    )
    new = _tl(
        _track("Video 1", "Video", [_clip("A", 10.0)]),
        _track("Audio 1", "Audio", [_clip("M", 10.0), _clip("N", 4.0)]),
    )
    d, _ = _lines_for(old, new)
    secs = D.build_sections(old, new, d)
    assert [(s["track"], s["kind"]) for s in secs] == [("Audio 1", "audio")]
    assert secs[0]["entries"][0]["timecode_s"] == 10.0


def test_sections_follow_timeline_track_order():
    old = _tl(
        _track("Video 1", "Video", [_clip("A", 10.0)]),
        _track("Video 2", "Video", [_clip("B", 10.0)]),
        _track("Audio 1", "Audio", [_clip("M", 10.0)]),
    )
    new = _tl(
        _track("Video 1", "Video", [_clip("A", 10.0), _clip("A2", 2.0)]),
        _track("Video 2", "Video", [_clip("B", 10.0)]),
        _track("Audio 1", "Audio", [_clip("M", 10.0), _clip("N", 1.0)]),
    )
    d, _ = _lines_for(old, new)
    secs = D.build_sections(old, new, d)
    assert [(s["track"], s["kind"]) for s in secs] == [("Video 1", "video"), ("Audio 1", "audio")]
    assert "Video 2" not in [s["track"] for s in secs]


# --- trim wording ----------------------------------------------------------

def _trim_lines(old_dur, old_start, new_dur, new_start):
    a = _clip("C", old_dur, start_s=old_start)
    b = _clip("C", new_dur, start_s=new_start)
    old = _tl(_track("Video 1", "Video", [a]))
    new = _tl(_track("Video 1", "Video", [b]))
    d = D.diff_all_tracks(old, new)
    assert len(d.changes) == 1, [c.to_dict() for c in d.changes]
    return D.change_lines(d.changes[0], a, b)


def test_trim_head_only():
    assert _trim_lines(10.0, 0.0, 7.7, 2.3) == ["Trimmed 2.3s from beginning"]


def test_trim_tail_only():
    assert _trim_lines(10.0, 0.0, 8.5, 0.0) == ["Trimmed 1.5s from end"]


def test_trim_both_ends():
    assert _trim_lines(10.0, 0.0, 6.0, 2.3) == ["Trimmed 2.3s from beginning, 1.7s from end"]


def test_extend_tail():
    assert _trim_lines(10.0, 0.0, 11.5, 0.0) == ["Extended 1.5s from end"]


def test_slip_same_duration():
    assert _trim_lines(10.0, 0.0, 10.0, 1.0) == ["Slipped 1s later"]


# --- moves -----------------------------------------------------------------

def test_moved_clip_shows_signed_delta():
    old = _tl(_track("Video 1", "Video", [_clip("A", 10.0), _clip("M", 5.0), _clip("B", 5.0)]))
    new = _tl(_track("Video 1", "Video", [_clip("M", 5.0), _clip("A", 10.0), _clip("B", 5.0)]))
    d, by_type = _lines_for(old, new)
    assert "reordered" in by_type, [c.to_dict() for c in d.changes]
    mv = [c for c in by_type["reordered"] if c.clip_name == "M"][0]
    assert mv.details["move_delta_s"] == -10.0
    secs = D.build_sections(old, new, d)
    entry = [e for s in secs for e in s["entries"] if e["label"] == "Clip: M"][0]
    assert entry["timecode_s"] == 0.0
    assert entry["lines"][0] == "Moved -00:00:10.000"


# --- volume -----------------------------------------------------------------

def test_volume_only_change_is_modified_with_line():
    old = _tl(_track("Audio 1", "Audio", [_clip("M", 10.0, volume_db=-6.0)]))
    new = _tl(_track("Audio 1", "Audio", [_clip("M", 10.0, volume_db=-12.0)]))
    d, by_type = _lines_for(old, new)
    assert [c.clip_name for c in by_type.get("modified", [])] == ["M"]
    secs = D.build_sections(old, new, d)
    entry = secs[0]["entries"][0]
    assert entry["lines"] == ["Volume: -6.0 dB → -12.0 dB"]


def test_volume_below_display_precision_is_ignored():
    old = _tl(_track("Audio 1", "Audio", [_clip("M", 10.0, volume_db=5.21)]))
    new = _tl(_track("Audio 1", "Audio", [_clip("M", 10.0, volume_db=5.24)]))
    d, _ = _lines_for(old, new)
    assert d.changes == []


def test_volume_missing_on_one_side_is_ignored():
    old = _tl(_track("Audio 1", "Audio", [_clip("M", 10.0, volume_db=None)]))
    new = _tl(_track("Audio 1", "Audio", [_clip("M", 10.0, volume_db=-12.0)]))
    d, _ = _lines_for(old, new)
    assert d.changes == []


def test_volume_change_rides_along_with_trim():
    old = _tl(_track("Audio 1", "Audio", [_clip("M", 10.0, volume_db=-6.0)]))
    new = _tl(_track("Audio 1", "Audio", [_clip("M", 8.0, volume_db=-12.0)]))
    d, by_type = _lines_for(old, new)
    assert [c.clip_name for c in by_type.get("trimmed", [])] == ["M"]
    assert "modified" not in by_type
    secs = D.build_sections(old, new, d)
    assert secs[0]["entries"][0]["lines"] == [
        "Trimmed 2s from end", "Volume: -6.0 dB → -12.0 dB"]


# --- titles ------------------------------------------------------------------

def test_title_only_change_is_modified_with_line():
    old = _tl(_track("Video 1", "Video", [_clip("T", 4.0, title_text="SUMMER FESTIVAL", is_title=True)]))
    new = _tl(_track("Video 1", "Video", [_clip("T", 4.0, title_text="SUMMER FESTIVAL 2026", is_title=True)]))
    d, by_type = _lines_for(old, new)
    assert [c.clip_name for c in by_type.get("modified", [])] == ["T"]
    secs = D.build_sections(old, new, d)
    assert [(s["track"], s["kind"]) for s in secs] == [("Text", "text")]
    entry = secs[0]["entries"][0]
    assert entry["label"] is None
    assert entry["lines"] == ['Text: "SUMMER FESTIVAL" → "SUMMER FESTIVAL 2026"']


def test_nested_stack_title_change_surfaces_in_text_section():
    def stack(name, titles):
        return NormalizedClip(kind="stack", index=0, name=name, url="",
                              duration_frames=10.0 * RATE, title_texts=list(titles))
    old = _tl(_track("Video 3", "Video", [_clip("A", 10.0), stack("Comp", ["Hello"])]))
    new = _tl(_track("Video 3", "Video", [_clip("A", 10.0), stack("Comp", ["Hello world"])])
              )
    # fix indices (helper only sets them inside _track; stacks built inline)
    old.tracks[0].items[1].index = 1
    new.tracks[0].items[1].index = 1
    d, by_type = _lines_for(old, new)
    assert "modified" in by_type
    secs = D.build_sections(old, new, d)
    assert secs[-1]["kind"] == "text"
    assert secs[-1]["entries"][0]["lines"] == ['Text: "Hello" → "Hello world"']


def test_otio_extraction_volume_and_title():
    import opentimelineio as otio

    def vol_effect(value):
        return otio.schema.Effect(
            name="Volume",
            metadata={"Resolve_OTIO": {
                "Name": "Volume",
                "Parameters": [{"Parameter ID": "volume", "Parameter Value": value}],
            }},
        )

    def title_clip(text):
        return otio.schema.Clip(
            name="Title",
            source_range=otio.opentime.TimeRange(
                otio.opentime.RationalTime(0, 30), otio.opentime.RationalTime(120, 30)),
            media_reference=otio.schema.GeneratorReference(
                name="Text", generator_kind="Rich",
                parameters={"Resolve_OTIO": [{
                    "Name": "Rich Text",
                    "Parameters": [{"Parameter ID": "rich text", "Parameter Value": text}],
                }]},
            ),
        )

    vtrack = otio.schema.Track(name="Video 1", kind=otio.schema.TrackKind.Video)
    atrack = otio.schema.Track(name="Audio 1", kind=otio.schema.TrackKind.Audio)

    def mksr(dur=300):
        return otio.opentime.TimeRange(
            otio.opentime.RationalTime(0, 30), otio.opentime.RationalTime(dur, 30))

    sr = mksr()
    vclip = otio.schema.Clip(name="A.mov", source_range=mksr(),
                             media_reference=otio.schema.ExternalReference(target_url="file://A.mov"))
    aclip = otio.schema.Clip(name="M.wav", source_range=mksr(),
                             media_reference=otio.schema.ExternalReference(target_url="file://M.wav"),
                             effects=[vol_effect(-6.5)])
    tclip = title_clip("Hello there")
    vtrack.extend([vclip, tclip])
    atrack.append(aclip)
    # NOTE: Timeline(tracks=<non-empty stack>) raises "child already has a
    # parent" in OTIO 0.18 — extend the default stack instead.
    tl = otio.schema.Timeline(name="T")
    tl.tracks.extend([vtrack, atrack])

    from get_syncd.otio_parse import parse_timeline
    nt = parse_timeline(tl)
    va = next(t for t in nt.tracks if t.name == "Video 1")
    au = next(t for t in nt.tracks if t.name == "Audio 1")
    assert au.items[0].volume_db == -6.5
    got = [c for c in va.items if c.is_title]
    assert len(got) == 1 and got[0].title_text == "Hello there"

    solid = otio.schema.Clip(
        name="Slug", source_range=mksr(),
        media_reference=otio.schema.GeneratorReference(
            name="Solid Color", generator_kind="Solid Color", parameters={}))
    v2 = otio.schema.Track(name="Video 1", kind=otio.schema.TrackKind.Video)
    v2.append(solid)
    stl = otio.schema.Timeline(name="S")
    stl.tracks.append(v2)
    assert parse_timeline(stl).tracks[0].items[0].is_title is False


def test_api_diff_response_carries_sections(tmp_path=None):
    """api_diff response includes grouped sections; old keys untouched."""
    import shutil
    import tempfile
    from get_syncd import api, git_store
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "proj"
        (repo / "timelines").mkdir(parents=True)
        git_store.init_repo(repo)
        shutil.copy("tests/fixtures/base.otio", str(repo / "timelines" / "1.otio"))
        h1 = git_store.save_version(repo, repo / "timelines" / "1.otio", "one",
                                    timeline_dest="timelines/1.otio")
        shutil.copy("tests/fixtures/trimmed_early.otio", str(repo / "timelines" / "1.otio"))
        h2 = git_store.save_version(repo, repo / "timelines" / "1.otio", "two",
                                    timeline_dest="timelines/1.otio")
        d = api.api_diff(repo, a=h1, b=h2, timeline="1")
        assert "sections" in d and isinstance(d["sections"], list)
        assert "changes" in d and "summary" in d  # backwards compatible
        flat = [e for s in d["sections"] for e in s["entries"]]
        assert flat, "expected section entries"
        assert all(set(e) >= {"timecode", "label", "type", "lines"} for e in flat)


def test_api_diff_first_save_sections_are_all_added(tmp_path=None):
    import shutil
    import tempfile
    from get_syncd import api, git_store
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "proj"
        (repo / "timelines").mkdir(parents=True)
        git_store.init_repo(repo)
        shutil.copy("tests/fixtures/base.otio", str(repo / "timelines" / "1.otio"))
        h1 = git_store.save_version(repo, repo / "timelines" / "1.otio", "only",
                                    timeline_dest="timelines/1.otio")
        d = api.api_diff(repo, a="empty", b=h1, timeline="1")
        assert d.get("is_first_save") is True
        flat = [e for s in d["sections"] for e in s["entries"]]
        assert flat
        assert all(e["lines"] == ["+ Added"] or e["lines"][0].startswith("+ Added") for e in flat)


def _gap(dur_s, idx=0, name=""):
    return NormalizedClip(kind="gap", index=idx, name=name or f"Gap_{idx}", url="",
                          duration_frames=dur_s * RATE)


def _track_mixed(name, kind, items):
    for i, c in enumerate(items):
        c.index = i
    return NormalizedTrack(name=name, kind=kind, items=items)


def test_small_gap_resize_hidden_big_gap_shown():
    old = _tl(_track_mixed("Video 1", "Video", [_clip("A", 10.0), _gap(10.0), _clip("B", 5.0)]))
    new = _tl(_track_mixed("Video 1", "Video", [_clip("A", 10.0), _gap(6.0), _clip("B", 5.0)]))
    secs = D.build_sections(old, new, D.diff_all_tracks(old, new))
    assert secs == [], secs  # 4s wiggle is spacing fallout, not an edit
    old2 = _tl(_track_mixed("Video 1", "Video", [_clip("A", 10.0)]))
    new2 = _tl(_track_mixed("Video 1", "Video", [_clip("A", 10.0), _gap(30.0)]))
    secs2 = D.build_sections(old2, new2, D.diff_all_tracks(old2, new2))
    assert len(secs2) == 1 and len(secs2[0]["entries"]) == 1  # 30s hole matters


def test_shifted_gap_collapses_to_nothing():
    old = _tl(_track_mixed("Video 1", "Video", [_clip("A", 10.0), _gap(7.0), _clip("B", 5.0)]))
    new = _tl(_track_mixed("Video 1", "Video", [_clip("Z", 3.0), _clip("A", 10.0), _gap(7.0), _clip("B", 5.0)]))
    d = D.diff_all_tracks(old, new)
    secs = D.build_sections(old, new, d)
    kinds = [(e["type"], e["kind"]) for s in secs for e in s["entries"]]
    assert not any(k == "gap" for _, k in kinds), kinds
    assert any(t == "added" for t, _ in kinds)  # the Z clip still shows


def test_adjacent_same_clip_adds_group_into_one_entry():
    old = _tl(_track_mixed("Video 2", "Video", [_clip("A", 10.0)]))
    new = _tl(_track_mixed("Video 2", "Video", [_clip("A", 10.0), _clip("V", 4.0), _clip("V", 3.0), _clip("V", 2.0)]))
    secs = D.build_sections(old, new, D.diff_all_tracks(old, new))
    assert len(secs) == 1
    assert len(secs[0]["entries"]) == 1
    assert secs[0]["entries"][0]["lines"] == ["+ Added ×3"]


def test_separated_repeats_stay_separate_with_source_lines():
    old = _tl(_track_mixed("Video 2", "Video", [_clip("A", 10.0)]))
    new = _tl(_track_mixed(
        "Video 2", "Video",
        [_clip("A", 10.0),
         _clip("V", 4.0, url="file://V", start_s=100.0),
         _clip("Q", 4.0),
         _clip("V", 3.0, url="file://V", start_s=200.0)]))
    secs = D.build_sections(old, new, D.diff_all_tracks(old, new))
    vents = [e for e in secs[0]["entries"] if (e["label"] or "").endswith("V")]
    assert len(vents) == 2, secs[0]["entries"]
    assert all(any(ln.startswith("Source: ") for ln in e["lines"]) for e in vents)
    assert vents[0]["lines"][-1] != vents[1]["lines"][-1]
    assert "00:01:40.000" in vents[0]["lines"][-1]  # source 100s @30fps orig rate


def test_gap_entries_never_carry_source_lines():
    old = _tl(_track_mixed("Video 1", "Video", [_clip("A", 10.0)]))
    new = _tl(_track_mixed("Video 1", "Video", [_clip("A", 10.0), _gap(30.0)]))
    secs = D.build_sections(old, new, D.diff_all_tracks(old, new))
    gaps = [e for s in secs for e in s["entries"] if e["kind"] == "gap"]
    assert gaps, "expected the significant gap to survive"
    assert all(not any(ln.startswith("Source: ") for ln in e["lines"]) for e in gaps)


def test_grouped_entry_has_no_source_line():
    old = _tl(_track_mixed("Video 2", "Video", [_clip("A", 10.0)]))
    new = _tl(_track_mixed("Video 2", "Video", [_clip("A", 10.0), _clip("V", 4.0), _clip("V", 3.0)]))
    secs = D.build_sections(old, new, D.diff_all_tracks(old, new))
    entry = secs[0]["entries"][0]
    assert entry["lines"] == ["+ Added ×2"]
