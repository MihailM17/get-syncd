import pathlib
import opentimelineio as otio
from opentimelineio.opentime import RationalTime, TimeRange
import sys
sys.path.insert(0, "src")
from get_syncd.otio_parse import parse_otio_file, parse_otio_string, parse_timeline
from get_syncd.diff import diff_timelines


def make_timeline(name, clips):
    tl = otio.schema.Timeline(name=name)
    track = otio.schema.Track(name="V1", kind=otio.schema.TrackKind.Video)
    for c in clips:
        clip = otio.schema.Clip(
            name=c["name"],
            media_reference=otio.schema.ExternalReference(target_url=c["url"]),
            source_range=TimeRange(RationalTime(c["start"], 24), RationalTime(c["dur"], 24)),
        )
        track.append(clip)
    tl.tracks.append(track)
    return tl


def parse(clips):
    return parse_timeline(make_timeline("Test", clips))


base = [
    {"name": "Intro", "url": "/media/intro.mp4", "start": 0, "dur": 48},
    {"name": "Scene1", "url": "/media/scene1.mp4", "start": 10, "dur": 72},
    {"name": "Scene2", "url": "/media/scene2.mp4", "start": 5, "dur": 60},
    {"name": "Scene3", "url": "/media/scene3.mp4", "start": 0, "dur": 96},
    {"name": "Outro", "url": "/media/outro.mp4", "start": 0, "dur": 48},
]


def test_trim_early_no_false_positives():
    old = parse(base)
    trimmed = [dict(c) for c in base]
    trimmed[0] = {"name": "Intro", "url": "/media/intro.mp4", "start": 0, "dur": 24}
    new = parse(trimmed)
    d = diff_timelines(old, new)
    assert d.summary["trimmed"] == 1, d.summary
    assert d.summary["added"] == 0
    assert d.summary["removed"] == 0
    assert d.summary["reordered"] == 0
    assert d.summary["total_changes"] == 1
    # Runtime delta -1s
    assert d.summary["runtime_delta_s"] == -1.0


def test_added():
    old = parse(base)
    added = [dict(c) for c in base]
    added.insert(2, {"name": "Broll", "url": "/media/broll.mp4", "start": 0, "dur": 36})
    new = parse(added)
    d = diff_timelines(old, new)
    assert d.summary["added"] == 1
    assert d.summary["removed"] == 0


def test_removed():
    old = parse(base)
    removed = [c for c in base if c["name"] != "Scene2"]
    new = parse(removed)
    d = diff_timelines(old, new)
    assert d.summary["removed"] == 1
    assert d.summary["added"] == 0


def test_reordered():
    old = parse(base)
    reordered = [base[0], base[2], base[1], base[3], base[4]]
    new = parse(reordered)
    d = diff_timelines(old, new)
    # Should be 1 reordered, not added+removed
    assert d.summary["reordered"] == 1, d.summary
    assert d.summary["added"] == 0
    assert d.summary["removed"] == 0


def test_no_changes():
    old = parse(base)
    new = parse(base)
    d = diff_timelines(old, new)
    assert d.summary["total_changes"] == 0
    assert d.summary["added"] == 0
    assert d.summary["removed"] == 0


def test_trim_and_add():
    old = parse(base)
    mixed = [dict(c) for c in base]
    mixed[0] = {"name": "Intro", "url": "/media/intro.mp4", "start": 0, "dur": 24}
    mixed.insert(1, {"name": "Title", "url": "/media/title.mp4", "start": 0, "dur": 48})
    new = parse(mixed)
    d = diff_timelines(old, new)
    assert d.summary["trimmed"] == 1
    assert d.summary["added"] == 1


def test_fixtures_files():
    # Test the actual fixture files written to tests/fixtures
    old = parse_otio_file("tests/fixtures/base.otio")
    new = parse_otio_file("tests/fixtures/trimmed_early.otio")
    d = diff_timelines(old, new)
    assert d.summary["trimmed"] == 1


def test_gap():
    old = parse(base)
    tl = make_timeline("Gap", base)
    gap = otio.schema.Gap(source_range=TimeRange(RationalTime(0, 24), RationalTime(12, 24)))
    tl.tracks[0].insert(1, gap)
    new = parse_timeline(tl)
    d = diff_timelines(old, new)
    assert d.summary["added"] == 1  # gap counted as added
