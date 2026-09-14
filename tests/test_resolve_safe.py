"""Resolve integration must never switch the user's open project.

_get_resolve_timelines is read-only: cache-first, and live reads only apply
when the open project name matches the repo folder name. No LoadProject calls.
Restore auto-import must also never CloseProject/LoadProject: SetCurrentTimeline
plus SaveProject is enough, the user reopens manually if ever needed.
"""

import inspect
import shutil
import sys
import types
from pathlib import Path

from get_syncd import resolve_state, api


def test_no_load_project_anywhere_in_resolve_path():
    src = inspect.getsource(resolve_state) + inspect.getsource(api._get_resolve_timelines)
    assert ".LoadProject(" not in src, "read path must never call LoadProject"


def test_cache_isolated_per_repo(tmp_path):
    a = tmp_path / "ProjA"
    b = tmp_path / "ProjB"
    resolve_state._save_known_timelines(a, "T1", ["T1", "T2"])
    resolve_state._save_known_timelines(b, "X1", ["X1"])
    cur_a, names_a = resolve_state._load_known_timelines(a)
    cur_b, names_b = resolve_state._load_known_timelines(b)
    assert names_a == ["T1", "T2"] and cur_a == "T1"
    assert names_b == ["X1"] and cur_b == "X1"


def test_save_replaces_never_merges(tmp_path):
    r = tmp_path / "Proj"
    resolve_state._save_known_timelines(r, "A", ["A", "B"])
    resolve_state._save_known_timelines(r, "C", ["C"])
    _, names = resolve_state._load_known_timelines(r)
    assert names == ["C"], f"merge bug regressed: {names}"


def test_no_cache_no_resolve_returns_empty(tmp_path, monkeypatch):
    r = tmp_path / "NoSuchProj_xyz"
    monkeypatch.setattr(resolve_state, "_read_current_resolve_state", lambda: (None, None, []))
    cur, names = api._get_resolve_timelines(r)
    assert (cur, names) == (None, [])


def test_live_state_ignored_when_project_mismatch(tmp_path, monkeypatch):
    r = tmp_path / "Git test"
    # Open project is something else — must NOT leak its timelines
    monkeypatch.setattr(
        resolve_state, "_read_current_resolve_state", lambda: ("Marginal Videos", "2", ["1", "2"])
    )
    cur, names = api._get_resolve_timelines(r)
    assert (cur, names) == (None, [])


class _FakeTimeline:
    def GetName(self):
        return "5"


class _FakeMediaPool:
    def __init__(self, calls):
        self.calls = calls

    def ImportTimelineFromFile(self, path, opts):
        self.calls.append(("import", str(path)))
        return _FakeTimeline()


class _FakeProject:
    def __init__(self, calls):
        self.calls = calls

    def GetName(self):
        return "Proj"

    def GetMediaPool(self):
        return _FakeMediaPool(self.calls)

    def SetCurrentTimeline(self, tl):
        self.calls.append(("set_current", True))


class _FakePM:
    def __init__(self):
        self.calls = []

    def GetCurrentProject(self):
        return _FakeProject(self.calls)

    def SaveProject(self):
        self.calls.append(("save_project",))

    def CloseProject(self, project):
        self.calls.append(("close_project",))
        raise AssertionError("restore must never close the user's project")

    def LoadProject(self, name):
        self.calls.append(("load_project",))
        raise AssertionError("restore must never load/switch projects")


def test_restore_never_closes_or_reopens_project(tmp_path, monkeypatch):
    from get_syncd import git_store

    monkeypatch.setattr(api, "is_repo_allowed", lambda repo: True)
    fake_mod = types.ModuleType("DaVinciResolveScript")
    fake_pm = _FakePM()

    class _FakeResolve:
        def GetProjectManager(self):
            return fake_pm

    fake_mod.scriptapp = lambda name: _FakeResolve()
    monkeypatch.setitem(sys.modules, "DaVinciResolveScript", fake_mod)

    repo = tmp_path / "Proj"
    (repo / "timelines").mkdir(parents=True)
    git_store.init_repo(repo)
    fixture = Path(__file__).parent / "fixtures" / "base.otio"
    t5 = repo / "timelines" / "5.otio"
    shutil.copy(str(fixture), str(t5))
    h = git_store.save_version(repo, t5, "Save 5", timeline_dest="timelines/5.otio")

    res = api.api_restore(repo, rev=h, apply=True, timeline="5")
    assert res["ok"], res
    assert ("save_project",) in fake_pm.calls
    assert ("set_current", True) in fake_pm.calls
    kinds = [k for k, *_ in fake_pm.calls]
    assert "close_project" not in kinds and "load_project" not in kinds

    src = inspect.getsource(api._try_resolve_import)
    assert ".CloseProject(" not in src and ".LoadProject(" not in src
