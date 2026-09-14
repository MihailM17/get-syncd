"""CLI is timeline-aware: --timeline routes saves/logs/restores/deletes to
timelines/<name>.otio instead of the legacy single file."""

import json
import shutil
import sys
import types
from pathlib import Path

sys.path.insert(0, "src")
from get_syncd import cli, git_store

FIX = Path(__file__).parent / "fixtures" / "base.otio"
TRIM = Path(__file__).parent / "fixtures" / "trimmed_early.otio"


def _ns(**kw):
    base = dict(repo=None, timeline=None, file=None, message=None, json=True,
                no_prompt=True, yes=True, interactive=False, out=None, apply=False,
                limit=20, verbose=False, a=None, b=None, track=None, all_tracks=False,
                rev=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _repo(tmp, name="Proj", cur="5"):
    repo = Path(tmp) / name
    (repo / "timelines").mkdir(parents=True)
    git_store.init_repo(repo)
    cache = repo / ".get-syncd" / "timelines.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"current": cur, "all_names": [cur]}))
    return repo


def _export(repo, name, fixture=FIX):
    p = repo / "timelines" / f"{name}.otio"
    shutil.copy(str(fixture), str(p))
    return p


def test_save_timeline_flag(tmp_path, capsys):
    repo = _repo(tmp_path)
    _export(repo, "5")
    cli.cmd_save(_ns(repo=str(repo), timeline="5", message="First 5"))
    capsys.readouterr()
    assert (repo / "timelines" / "5.otio").exists()
    assert not (repo / "timeline.otio").exists(), "must not touch legacy storage"
    vers = git_store.log_versions(repo, limit=5, timeline_file="timelines/5.otio", fallback=False)
    assert len(vers) == 1 and vers[0]["message"] == "First 5"


def test_save_infers_timeline_from_file(tmp_path, capsys):
    repo = _repo(tmp_path)
    p = _export(repo, "5")
    cli.cmd_save(_ns(repo=str(repo), file=str(p), message="Via file"))
    capsys.readouterr()
    vers = git_store.log_versions(repo, limit=5, timeline_file="timelines/5.otio", fallback=False)
    assert len(vers) == 1


def test_save_bare_uses_current_timeline(tmp_path, capsys):
    repo = _repo(tmp_path)
    _export(repo, "5")
    cli.cmd_save(_ns(repo=str(repo), timeline="5", message="First 5"))
    capsys.readouterr()
    # second export with changes, bare save (no flags) follows cur=5 from cache
    shutil.copy(str(TRIM), str(repo / "timelines" / "5.otio"))
    cli.cmd_save(_ns(repo=str(repo), message="Second 5"))
    capsys.readouterr()
    vers = git_store.log_versions(repo, limit=5, timeline_file="timelines/5.otio", fallback=False)
    assert len(vers) == 2


def test_log_and_delete_are_scoped(tmp_path, capsys):
    repo = _repo(tmp_path)
    _export(repo, "5")
    cli.cmd_save(_ns(repo=str(repo), timeline="5", message="Save 5"))
    capsys.readouterr()
    _export(repo, "1")
    cli.cmd_save(_ns(repo=str(repo), timeline="1", message="Save 1"))
    capsys.readouterr()
    cli.cmd_log(_ns(repo=str(repo), timeline="5"))
    out = json.loads(capsys.readouterr().out)
    assert [v["message"] for v in out] == ["Save 5"]
    cli.cmd_delete(_ns(repo=str(repo), timeline="1", rev="1"))
    capsys.readouterr()
    assert git_store.log_versions(repo, limit=5, timeline_file="timelines/1.otio", fallback=False) == []
    assert len(git_store.log_versions(repo, limit=5, timeline_file="timelines/5.otio", fallback=False)) == 1


def test_restore_apply_writes_timeline_file(tmp_path, capsys):
    repo = _repo(tmp_path)
    _export(repo, "5")
    cli.cmd_save(_ns(repo=str(repo), timeline="5", message="Save 5"))
    capsys.readouterr()
    shutil.copy(str(TRIM), str(repo / "timelines" / "5.otio"))
    cli.cmd_restore(_ns(repo=str(repo), timeline="5", rev="1", apply=True))
    capsys.readouterr()
    assert (repo / "timelines" / "5.otio").exists()
    assert not (repo / "timeline.otio").exists()


def test_diff_timeline_and_status(tmp_path, capsys):
    repo = _repo(tmp_path)
    _export(repo, "5")
    cli.cmd_save(_ns(repo=str(repo), timeline="5", message="Save 5"))
    capsys.readouterr()
    shutil.copy(str(TRIM), str(repo / "timelines" / "5.otio"))
    cli.cmd_save(_ns(repo=str(repo), timeline="5", message="Save 5b"))
    capsys.readouterr()
    cli.cmd_diff(_ns(repo=str(repo), timeline="5", a="2", b="1"))
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["total_changes"] >= 0 and "changes" in out
    cli.cmd_status(_ns(repo=str(repo), timeline="5"))
    st = json.loads(capsys.readouterr().out)
    assert st["has_changes"] is False
