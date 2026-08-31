import tempfile
import pathlib
import subprocess
import shutil
import sys
sys.path.insert(0, "src")
from get_syncd import git_store
from get_syncd.otio_parse import parse_otio_file


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
