"""Cross-platform support: Resolve paths per OS, default repo endpoint."""

import sys
from pathlib import Path

from get_syncd import api, resolve_state


def test_default_repo_endpoint_matches_home():
    d = api.api_default_repo()
    assert d["ok"] and d["path"]
    assert Path(d["path"]).name == "GetSyncd"
    assert api.is_repo_allowed(d["path"])


def _paths_for(platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    return resolve_state.resolve_scripting_paths()


def test_macos_paths(monkeypatch):
    paths = _paths_for("darwin", monkeypatch)
    assert any("Application Support" in p for p in paths), paths


def test_windows_paths(monkeypatch):
    monkeypatch.setenv("PROGRAMDATA", r"C:\ProgramData")
    monkeypatch.setenv("APPDATA", r"C:\Users\test\AppData\Roaming")
    paths = _paths_for("win32", monkeypatch)
    assert any("Blackmagic Design" in p for p in paths), paths
    assert len(paths) >= 1


def test_linux_paths(monkeypatch):
    paths = _paths_for("linux", monkeypatch)
    assert any("resolve" in p.lower() for p in paths), paths


def test_ensure_path_no_crash_without_resolve():
    # On machines without Resolve installed this must simply return False
    assert resolve_state.ensure_resolve_scripting_path() in (True, False)


def test_github_status_shape():
    d = api.api_github_status()
    assert set(d) >= {"ok", "has_gh", "authed"}
    assert isinstance(d["ok"], bool)


def test_github_create_validates(tmp_path):
    r = api.api_github_create(tmp_path, name="bad name!", private=True)
    assert not r["ok"]
    r2 = api.api_github_create(tmp_path, name="good-name_1.2", private=True)
    # Either "not a git repo" (no gh side effects) or gh-missing — never a crash
    assert not r2["ok"] and "error" in r2
    r3 = api.api_github_create("/etc", name="x", private=True)
    assert not r3["ok"]
