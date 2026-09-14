import tempfile
import pathlib
import subprocess
import shutil
import sys
sys.path.insert(0, "src")
from get_syncd import api, git_store
from get_syncd.otio_parse import parse_otio_file


def _allow_tmp(monkeypatch):
    monkeypatch.setattr(api, "is_repo_allowed", lambda repo: True)


def test_save_status_log_restore(tmp_path=None):
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        # copy base fixture
        src = pathlib.Path("tests/fixtures/base.otio")
        dest = repo / "timeline.otio"
        shutil.copy(str(src), str(dest))

        git_store.init_repo(repo)
        assert git_store.is_git_repo(repo)

        # status before first save -> has changes
        s = git_store.status(repo)
        assert s["has_changes"] is True

        # save
        h1 = git_store.save_version(repo, dest, "Initial cut")
        assert h1
        s = git_store.status(repo)
        assert s["has_changes"] is False

        # modify and save again
        shutil.copy("tests/fixtures/trimmed_early.otio", str(dest))
        s = git_store.status(repo)
        assert s["has_changes"] is True
        h2 = git_store.save_version(repo, dest, "Trimmed intro")
        assert h2 != h1

        # log
        logs = git_store.log_versions(repo)
        assert len(logs) == 2
        assert logs[0]["hash"] == h2

        # restore
        out = pathlib.Path(tmp) / "restored.otio"
        git_store.restore_version(repo, h1, out)
        assert out.exists()
        # restored should match base
        import opentimelineio as otio
        a = parse_otio_file(out)
        b = parse_otio_file("tests/fixtures/base.otio")
        assert len(a.main_track().items) == len(b.main_track().items)


def test_current_previews_dont_collide():
    import tempfile
    from get_syncd import preview
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        (repo / ".get-syncd" / "previews").mkdir(parents=True)
        shutil.copy("tests/fixtures/base.otio", str(repo / "a.otio"))
        shutil.copy("tests/fixtures/trimmed_early.otio", str(repo / "b.otio"))
        pa = preview.generate_preview(repo, "current-" + git_store.file_hash(repo / "a.otio"), repo / "a.otio")
        pb = preview.generate_preview(repo, "current-" + git_store.file_hash(repo / "b.otio"), repo / "b.otio")
        assert pa != pb, "live previews must not share one file"
        assert pa.exists() and pa.stat().st_size > 100
        assert pb.exists() and pb.stat().st_size > 100


def test_push_to_local_remote(monkeypatch):
    _allow_tmp(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        shutil.copy("tests/fixtures/base.otio", str(repo / "timeline.otio"))
        git_store.init_repo(repo)
        h1 = git_store.save_version(repo, repo / "timeline.otio", "Initial cut")
        bare = pathlib.Path(tmp) / "remote.git"
        subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
        git_store._run_git(["remote", "add", "origin", str(bare)], cwd=repo)
        res = api.api_push(repo)
        assert res["ok"], res
        # remote really received the commit
        r = git_store._run_git(["log", "--pretty=format:%H"], cwd=bare, check=False)
        assert h1 in r.stdout


def test_push_without_remote_is_actionable(monkeypatch):
    _allow_tmp(monkeypatch)
    with tempfile.TemporaryDirectory() as tmp:
        repo = pathlib.Path(tmp) / "repo"
        repo.mkdir()
        git_store.init_repo(repo)
        res = api.api_push(repo)
        assert res["ok"] is False
        assert res.get("needs_remote") is True
        assert "remote" in res["error"].lower()
