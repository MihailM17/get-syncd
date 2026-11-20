from get_syncd.diff import diff_all_tracks, build_sections, build_visual_tracks
from get_syncd.otio_parse import NormalizedTimeline, NormalizedTrack, NormalizedClip


def test_visual_tracks_and_change_id_sync():
    old = NormalizedTimeline(
        name="Main",
        tracks=[
            NormalizedTrack(
                name="Video 1",
                kind="Video",
                items=[
                    NormalizedClip(index=0, kind="clip", name="IMG_5165.MOV", url="/a.mov", start_frames=0, duration_frames=120),
                    NormalizedClip(index=1, kind="clip", name="IMG_5173.MOV", url="/b.mov", start_frames=0, duration_frames=120),
                ],
            ),
            NormalizedTrack(
                name="Audio 1",
                kind="Audio",
                items=[
                    NormalizedClip(index=0, kind="clip", name="BOOM_01.WAV", url="/a.wav", start_frames=0, duration_frames=240),
                ],
            ),
        ],
    )
    new = NormalizedTimeline(
        name="Main",
        tracks=[
            NormalizedTrack(
                name="Video 1",
                kind="Video",
                items=[
                    NormalizedClip(index=0, kind="clip", name="IMG_5173.MOV", url="/b.mov", start_frames=0, duration_frames=150),
                    NormalizedClip(index=1, kind="clip", name="IMG_5180.MOV", url="/c.mov", start_frames=0, duration_frames=90),
                ],
            ),
            NormalizedTrack(
                name="Audio 1",
                kind="Audio",
                items=[
                    NormalizedClip(index=0, kind="clip", name="BOOM_01.WAV", url="/a.wav", start_frames=0, duration_frames=240),
                ],
            ),
        ],
    )

    d = diff_all_tracks(old, new)
    sections = build_sections(old, new, d)
    vt = build_visual_tracks(old, new, d)

    assert vt["duration_s"] > 0
    assert [t["short"] for t in vt["tracks"]] == ["V1", "A1"]

    v1 = vt["tracks"][0]
    assert any(c["status"] == "trimmed" and c["change_id"] is not None for c in v1["after"])
    assert any(c["status"] == "added" and c["change_id"] is not None for c in v1["after"])
    assert any(c["status"] == "removed" and c["change_id"] is not None for c in v1["removed"])

    section_ids = {cid for s in sections for e in s["entries"] for cid in e["change_ids"]}
    clip_ids = {
        c["change_id"]
        for t in vt["tracks"]
        for c in (*t["after"], *t["removed"])
        if c["change_id"] is not None
    }
    assert clip_ids.issubset(section_ids)
