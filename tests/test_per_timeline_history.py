"""Regression tests for per-timeline version history.

Covers the reported bugs around switching timelines:
1. The All view must show every save in the project, including legacy
   timeline.otio saves made before per-timeline files existed.
2. Each timeline pill must show STRICTLY that timeline's own saves — an
   untouched timeline shows nothing, never other timelines' versions.
"""
import json
import shutil
import sys
import pathlib

import pytest

sys.path.insert(0, "src")
from get_syncd import api, git_store


@pytest.fixture(autouse=True)
def _allow_tmp_repos(monkeypatch):
    # These history tests run in /tmp, outside ~/GetSyncd — bypass the trust
    # boundary (covered separately in test_repo_validation.py).
    monkeypatch.setattr(api, "is_repo_allowed", lambda repo: True)


def _make_mixed_repo(tmp):
    """Repo with 2 legacy saves + 2 per-timeline saves (timeline 1 x1, 2 x1)."""
    repo = pathlib.Path(tmp) / "proj"
    (repo / "timelines").mkdir(parents=True)
    git_store.init_repo(repo)

    legacy = repo / "timeline.otio"
    shutil.copy("tests/fixtures/base.otio", str(legacy))
    h_legacy1 = git_store.save_version(repo, legacy, "Legacy save 1", timeline_dest="timeline.otio")
    shutil.copy("tests/fixtures/trimmed_early.otio", str(legacy))
    h_legacy2 = git_store.save_version(repo, legacy, "Legacy save 2", timeline_dest="timeline.otio")

    t1 = repo / "timelines" / "1.otio"
    shutil.copy("tests/fixtures/base.otio", str(t1))
    h_t1 = git_store.save_version(repo, t1, "Save 1", timeline_dest="timelines/1.otio")

    t2 = repo / "timelines" / "2.otio"
    shutil.copy("tests/fixtures/trimmed_early.otio", str(t2))
    h_t2 = git_store.save_version(repo, t2, "Save 2", timeline_dest="timelines/2.otio")

    # Simulate Resolve cache: current timeline 2, names 1..3
    cache = repo / ".get-syncd" / "timelines.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"current": "2", "all_names": ["1", "2", "3"]}))
    return repo, h_legacy1, h_legacy2, h_t1, h_t2


def test_all_view_shows_every_version(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, h_l1, h_l2, h_t1, h_t2 = _make_mixed_repo(tmp)
        versions = api.api_log(repo, limit=30)
        hashes = [v["hash"] for v in versions]
        assert hashes == [h_t2, h_t1, h_l2, h_l1], f"All view hid versions: {hashes}"
        # per-timeline attribution for new saves
        by_hash = {v["hash"]: v for v in versions}
        assert by_hash[h_t1]["timeline"] == "1"
        assert by_hash[h_t2]["timeline"] == "2"
        assert by_hash[h_t2]["file"] == "timelines/2.otio"


def test_timeline_filter_is_strict(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, h_l1, h_l2, h_t1, h_t2 = _make_mixed_repo(tmp)
        # Each timeline shows only its own saves — nothing leaks across.
        v2 = api.api_log(repo, limit=30, timeline="2")
        assert [v["hash"] for v in v2] == [h_t2]
        assert all(v["legacy"] is False for v in v2)
        v1 = api.api_log(repo, limit=30, timeline="1")
        assert [v["hash"] for v in v1] == [h_t1]
        # Untouched timeline shows nothing (never other timelines' versions,
        # not even shared legacy history — that lives in the All view).
        v3 = api.api_log(repo, limit=30, timeline="3")
        assert v3 == []


def test_unmigrated_repo_filter_shows_legacy_file(tmp_path=None):
    """Single-file projects (no timelines/ dir): the current timeline's pill
    resolves to timeline.otio and shows those saves as its own."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "proj"
        repo.mkdir()
        git_store.init_repo(repo)
        legacy = repo / "timeline.otio"
        shutil.copy("tests/fixtures/base.otio", str(legacy))
        h1 = git_store.save_version(repo, legacy, "Only save", timeline_dest="timeline.otio")
        cache = repo / ".get-syncd" / "timelines.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"current": "Timeline 1", "all_names": ["Timeline 1"]}))
        v = api.api_log(repo, limit=30, timeline="Timeline 1")
        assert [x["hash"] for x in v] == [h1]
        assert v[0]["legacy"] is False


def test_timelines_list_has_no_duplicates(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, *_ = _make_mixed_repo(tmp)
        t = api.api_timelines(repo)
        names = [x["name"] for x in t["timelines"]]
        assert len(names) == len(set(names)), f"duplicate timeline entries: {names}"
        assert "1" in names and "2" in names and "3" in names


def test_status_untouched_timeline_is_not_dirty(tmp_path=None):
    import tempfile
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        repo, *_ = _make_mixed_repo(tmp)
        # Stage a change for timeline 1 only — timeline 2 must stay clean
        # (the staged check is per-file, not global).
        t1 = repo / "timelines" / "1.otio"
        t1.write_bytes(t1.read_bytes() + b"\n")
        subprocess.run(["git", "add", "timelines/1.otio"], cwd=str(repo), check=True)
        s = api.api_status(repo)
        by_name = {t["name"]: t for t in s["timelines"]}
        assert by_name["1"]["has_changes"] is True
        assert by_name["2"]["has_changes"] is False, by_name["2"]
        # Timeline 3 was never exported: not dirty, never another timeline's
        # activity — no "Found timelines/..." candidate confusion.
        assert by_name["3"]["has_changes"] is None
        assert by_name["3"]["message"] == "Not yet exported"


def test_status_sees_brand_new_untracked_file(tmp_path=None):
    """A timeline exported for the first time (untracked file) must report
    changes — otherwise the app says 'up to date' and the first Save is
    blocked with 'No changes to save'."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, *_ = _make_mixed_repo(tmp)
        fresh = repo / "timelines" / "9.otio"
        shutil.copy("tests/fixtures/base.otio", str(fresh))
        st = git_store.status(repo, timeline_file="timelines/9.otio")
        assert st["has_changes"] is True, st
        assert st["message"] == "New file — save your first version."
        s = api.api_status(repo)
        by_name = {t["name"]: t for t in s["timelines"]}
        assert by_name["9"]["has_changes"] is True, by_name["9"]
        assert s["has_changes"] is True


def test_stray_root_export_surfaces_notice(tmp_path=None):
    """In a migrated repo the root timeline.otio is legacy storage shadowed by
    every pill — a misdirected export landing there must still raise the
    overall dirty flag plus an explicit notice (never silent 'up to date')."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, *_ = _make_mixed_repo(tmp)
        legacy = repo / "timeline.otio"
        legacy.write_bytes(legacy.read_bytes() + b"\n")
        s = api.api_status(repo)
        assert s["has_changes"] is True, s
        assert s["notice"] and "project root" in s["notice"], s
        assert "timelines/2.otio" in s["notice"], s  # cur=2 in test cache
        # No pill claims it (none can save it) — but nothing is hidden either.
        by_name = {t["name"]: t for t in s["timelines"]}
        assert by_name["1"]["has_changes"] is False
        assert by_name["2"]["has_changes"] is False


def test_untracked_root_export_surfaces_notice(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "proj"
        (repo / "timelines").mkdir(parents=True)
        git_store.init_repo(repo)
        t1 = repo / "timelines" / "1.otio"
        shutil.copy("tests/fixtures/base.otio", str(t1))
        git_store.save_version(repo, t1, "Save 1", timeline_dest="timelines/1.otio")
        cache = repo / ".get-syncd" / "timelines.json"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"current": "1", "all_names": ["1"]}))
        (repo / "timeline.otio").write_bytes(b"stray export")
        s = api.api_status(repo)
        assert s["has_changes"] is True, s
        assert s["notice"] and "project root" in s["notice"], s


def test_root_delete_preserves_cache_and_unsaved_otio(tmp_path=None):
    """Deleting the root version must not wipe .get-syncd/ or unsaved .otio
    exports (the replay flow once ran `clean -fd` with .gitignore removed)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "proj"
        repo.mkdir()
        git_store.init_repo(repo)
        legacy = repo / "timeline.otio"
        shutil.copy("tests/fixtures/base.otio", str(legacy))
        h_root = git_store.save_version(repo, legacy, "Root", timeline_dest="timeline.otio")
        shutil.copy("tests/fixtures/trimmed_early.otio", str(legacy))
        git_store.save_version(repo, legacy, "Child", timeline_dest="timeline.otio")
        # Untracked precious files
        cache_note = repo / ".get-syncd" / "notes.txt"
        cache_note.parent.mkdir(parents=True, exist_ok=True)
        cache_note.write_text("do not delete")
        unsaved = repo / "timelines" / "9.otio"
        unsaved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy("tests/fixtures/base.otio", str(unsaved))
        res = git_store.delete_version(repo, h_root)
        assert res["ok"]
        assert cache_note.exists(), ".get-syncd was wiped by root delete"
        assert unsaved.exists(), "unsaved .otio export was wiped by root delete"
        remaining = git_store.log_versions(repo, limit=10)
        assert all(v["hash"] != h_root for v in remaining)


def test_diff_first_save_needs_no_previous(tmp_path=None):
    """Selecting a timeline's only save must not self-compare: the API shows
    everything in it as added (a='empty' or a==b both work)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, *_ = _make_mixed_repo(tmp)
        only = api.api_log(repo, limit=30, timeline="2")[0]["hash"]
        for a in ("empty", only):
            d = api.api_diff(repo, a=a, b=only, timeline="2")
            assert d.get("is_first_save") is True, d
            assert d["summary"]["added"] > 0, d["summary"]
            assert all(c["type"] == "added" for c in d["changes"]), d["changes"]
            assert "Diff not available" not in " ".join(d.get("warnings", []))


def test_restore_legacy_version_from_timeline_filter(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo, h_l1, h_l2, h_t1, h_t2 = _make_mixed_repo(tmp)
        out = pathlib.Path(tmp) / "dl.otio"
        res = api.api_restore(repo, rev=h_l2, apply=False, out=str(out), timeline="2")
        assert res["ok"], res
        assert out.exists()
