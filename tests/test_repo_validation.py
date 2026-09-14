"""Trust boundary: only ~/GetSyncd and children are servable."""

from pathlib import Path

from get_syncd import api


def test_allows_base_and_children():
    assert api.is_repo_allowed(None)
    assert api.is_repo_allowed(api.DEFAULT_REPO)
    assert api.is_repo_allowed(api.DEFAULT_REPO / "Git test")
    assert api.is_repo_allowed(str(api.DEFAULT_REPO / "Marginal Videos"))


def test_rejects_outside_paths():
    assert not api.is_repo_allowed("/etc")
    assert not api.is_repo_allowed("/tmp/evil")
    assert not api.is_repo_allowed(Path.home() / "Other")
    # Traversal that escapes base
    assert not api.is_repo_allowed(api.DEFAULT_REPO / ".." / "evil")


def test_api_log_rejects_outside_repo():
    # Must return [] (or 403 at server layer), never touch other paths
    assert api.api_log("/etc", limit=5) == []
    assert api.api_log("/tmp", limit=5, timeline="1") == []


def test_mutating_apis_reject_outside_repo(tmp_path):
    # init/save/restore/delete/export/branches enforce the boundary at the
    # api.* layer too — not just in api_server.py. Nothing may be created.
    outside = tmp_path / "evil"
    assert api.api_init(outside)["ok"] is False
    assert api.api_save(outside, message="x")["ok"] is False
    assert api.api_restore(outside, rev="HEAD")["ok"] is False
    assert api.api_delete(outside, rev="HEAD")["ok"] is False
    assert api.api_export(outside)["ok"] is False
    assert api.api_create_branch(outside, name="b")["ok"] is False
    assert api.api_delete_branch(outside, name="b")["ok"] is False
    assert not outside.exists(), "rejected call must not create anything"


def test_mutating_apis_allow_inside_repo(tmp_path, monkeypatch):
    # Same calls succeed (at the boundary layer) for a repo under ~/GetSyncd.
    # Redirect DEFAULT_REPO into tmp so no real user folder is touched.
    import get_syncd.api as api_mod
    monkeypatch.setattr(api_mod, "DEFAULT_REPO", tmp_path / "GetSyncd")
    from get_syncd import git_store
    repo = tmp_path / "GetSyncd" / "Proj"
    assert api.api_init(repo)["ok"] is True
    assert repo.is_dir() and git_store.is_git_repo(repo)
