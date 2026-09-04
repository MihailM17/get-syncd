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
