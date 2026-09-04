"""Track warning messages must be plain English — never raw array dumps."""

from get_syncd.diff import diff_timelines, _describe_track_list_change, _describe_track_counts
from get_syncd.otio_parse import NormalizedTimeline, NormalizedTrack


def _tl(tracks):
    return NormalizedTimeline(
        name="Test", tracks=[NormalizedTrack(name=n, kind=k, items=[]) for n, k in tracks]
    )


def test_added_tracks_humanized():
    old = _tl([("Video 1", "Video"), ("Audio 1", "Audio"), ("Audio 2", "Audio")])
    new = _tl(
        [
            ("Video 1", "Video"),
            ("Video 2", "Video"),
            ("Video 3", "Video"),
            ("Audio 1", "Audio"),
            ("Audio 2", "Audio"),
            ("Audio 3", "Audio"),
        ]
    )
    d = diff_timelines(old, new)
    assert d.warnings, "expected track warnings"
    joined = " • ".join(d.warnings)
    assert "[" not in joined and "]" not in joined, f"raw array leaked: {joined}"
    assert any(w.startswith("Added") for w in d.warnings), d.warnings
    assert any(w.startswith("Now") for w in d.warnings), d.warnings
    assert "2 video tracks (Video 2, Video 3)" in d.warnings[0]
    assert "1 audio track (Audio 3)" in d.warnings[0]


def test_removed_tracks_humanized():
    old = _tl([("Video 1", "Video"), ("Audio 1", "Audio"), ("Audio 2", "Audio")])
    new = _tl([("Video 1", "Video"), ("Audio 1", "Audio")])
    d = diff_timelines(old, new)
    assert any("Removed 1 audio track (Audio 2)" in w for w in d.warnings), d.warnings


def test_no_warning_when_same():
    old = _tl([("Video 1", "Video"), ("Audio 1", "Audio")])
    d = diff_timelines(old, old)
    assert d.warnings == []


def test_counts_note_pluralization():
    old = _tl([("Video 1", "Video"), ("Audio 1", "Audio"), ("Audio 2", "Audio")])
    new = _tl([("Video 1", "Video"), ("Audio 1", "Audio")])
    msg = _describe_track_counts(old, new)
    assert "1 video track +" in msg
    assert "2 audio tracks" in msg or "1 audio track" in msg
    assert "[" not in msg


def test_long_list_truncated():
    old = _tl([("Video 1", "Video")])
    new = _tl([("Video 1", "Video")] + [(f"Video {i}", "Video") for i in range(2, 10)])
    msg = _describe_track_list_change(old, new)
    assert "and" in msg and "more" in msg, msg
    assert "[" not in msg
