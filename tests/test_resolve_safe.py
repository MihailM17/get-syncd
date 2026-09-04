"""Resolve integration must never switch the user's open project.

_get_resolve_timelines is read-only: cache-first, and live reads only apply
when the open project name matches the repo folder name. No LoadProject calls.
"""

import inspect
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
