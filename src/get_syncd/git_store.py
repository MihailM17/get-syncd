"""Git wrappers for Get Syncd — save, status, push, restore, log.

Uses subprocess git CLI (no extra deps). Offline-first: save is local.
"""

from __future__ import annotations

import subprocess
import hashlib
from pathlib import Path
from typing import Optional
import shutil
import os


def _run_git(args: list[str], cwd: Path | str = ".", check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, check=check)


def is_git_repo(path: Path | str = ".") -> bool:
    try:
        _run_git(["rev-parse", "--git-dir"], cwd=path)
        return True
    except subprocess.CalledProcessError:
        return False


def _ensure_git_identity(path: Path | str = ".") -> None:
    """Ensure git user.name/email is set for commits (needed in fresh repos/CI)."""
    p = Path(path)
    try:
        name = _run_git(["config", "user.name"], cwd=p, check=False)
        email = _run_git(["config", "user.email"], cwd=p, check=False)
        if not name.stdout.strip():
            _run_git(["config", "user.name", "Get Syncd"], cwd=p, check=False)
        if not email.stdout.strip():
            _run_git(["config", "user.email", "get-syncd@example.com"], cwd=p, check=False)
    except Exception:
        pass


def init_repo(path: Path | str = ".", remote_url: Optional[str] = None) -> None:
    p = Path(path)
    if not is_git_repo(p):
        _run_git(["init"], cwd=p)
        _ensure_git_identity(p)
        # Ensure .gitignore
        gitignore = p / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Get Syncd — ignore media, keep timeline\n*.mp4\n*.mov\n*.mxf\n*.wav\n*.aiff\n*.braw\n!timeline.otio\n")
    else:
        _ensure_git_identity(p)
    if remote_url:
        try:
            _run_git(["remote", "add", "origin", remote_url], cwd=p)
        except subprocess.CalledProcessError:
            _run_git(["remote", "set-url", "origin", remote_url], cwd=p)


def get_repo_root(start: Path | str = ".") -> Optional[Path]:
    try:
        r = _run_git(["rev-parse", "--show-toplevel"], cwd=start, check=True)
        return Path(r.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def save_version(
    repo_path: Path | str,
    otio_source: Path | str,
    message: str,
    timeline_dest: str = "timeline.otio",
) -> str:
    """Copy OTIO into repo, commit. Returns commit hash."""
    repo = Path(repo_path)
    src = Path(otio_source)
    if not src.exists():
        raise FileNotFoundError(f"Source OTIO not found: {src}")
    if not is_git_repo(repo):
        init_repo(repo)

    dest = repo / timeline_dest
    # Ensure parent exists
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if Path(src).resolve() != dest.resolve():
            shutil.copy2(str(src), str(dest))
    except FileNotFoundError:
        shutil.copy2(str(src), str(dest))

    # Also keep timestamped snapshot for viewer history (optional)
    history_dir = repo / ".get-syncd" / "snapshots"
    history_dir.mkdir(parents=True, exist_ok=True)

    _ensure_git_identity(repo)
    _run_git(["add", timeline_dest, ".gitignore"], cwd=repo, check=False)
    # Also add gitignore if newly created
    try:
        _run_git(["add", ".gitignore"], cwd=repo, check=False)
    except Exception:
        pass

    # Check if there's anything to commit
    # For first commit, HEAD doesn't exist — any staged file counts as changes
    head_exists = _run_git(["rev-parse", "--verify", "HEAD"], cwd=repo, check=False).returncode == 0
    if not head_exists:
        # If we have staged changes, proceed
        diff_cached = _run_git(["diff", "--cached", "--quiet"], cwd=repo, check=False)
        has_changes = diff_cached.returncode != 0
        if not has_changes:
            # Check porcelain as fallback
            status = _run_git(["status", "--porcelain", "--", timeline_dest], cwd=repo, check=False)
            has_changes = status.stdout.strip() != ""
        if not has_changes:
            raise ValueError("No changes to save — timeline is identical to last version.")
    else:
        status = _run_git(["status", "--porcelain", "--", timeline_dest], cwd=repo, check=False)
        diff_cached = _run_git(["diff", "--cached", "--quiet"], cwd=repo, check=False)
        # diff --cached --quiet returns 0 if no diff, 1 if diff exists
        has_changes = status.stdout.strip() != "" or diff_cached.returncode == 1

        # Also check untracked
        if not has_changes:
            # No changes staged — check if file changed vs HEAD
            try:
                _run_git(["diff", "--quiet", "HEAD", "--", timeline_dest], cwd=repo, check=False)
                if _run_git(["diff", "--quiet", "HEAD", "--", timeline_dest], cwd=repo, check=False).returncode == 0:
                    # Try to get HEAD file
                    pass
            except Exception:
                pass
            # Fallback: check git status
            full_status = _run_git(["status", "--porcelain"], cwd=repo, check=False)
            if not full_status.stdout.strip():
                raise ValueError("No changes to save — timeline is identical to last version.")

    _run_git(["commit", "-m", message], cwd=repo)

    # Get commit hash
    r = _run_git(["rev-parse", "HEAD"], cwd=repo)
    commit_hash = r.stdout.strip()

    # Save snapshot copy named by commit
    try:
        shutil.copy2(str(dest), str(history_dir / f"{commit_hash[:8]}.otio"))
    except Exception:
        pass

    # Generate preview image for GUI (best-effort, Pillow optional)
    try:
        from .preview import generate_preview  # type: ignore
        try:
            generate_preview(repo, commit_hash, dest)
        except Exception:
            pass
    except Exception:
        pass

    return commit_hash


def status(repo_path: Path | str = ".", timeline_file: str = "timeline.otio") -> dict:
    """Return status dict: has_changes, is_repo, etc."""
    repo = Path(repo_path)
    if not is_git_repo(repo):
        return {"is_repo": False, "has_changes": None, "message": "Not a git repo — run get-syncd init"}

    # Check if timeline file exists
    tl = repo / timeline_file
    if not tl.exists():
        return {"is_repo": True, "has_changes": None, "message": f"No {timeline_file} yet — export from Resolve first"}

    # Compare working tree vs HEAD
    try:
        # Use git diff --quiet HEAD -- timeline.otio (capture to avoid leaking fatal: bad revision)
        result = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", timeline_file], cwd=str(repo), capture_output=True)
        has_changes = result.returncode != 0
        # Also check untracked
        if not has_changes:
            # Check if file is untracked (no HEAD)
            head_check = _run_git(["rev-parse", "--verify", "HEAD"], cwd=repo, check=False)
            if head_check.returncode != 0:
                has_changes = True  # No commits yet, so changes exist
            else:
                # Check staged vs HEAD as well
                staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(repo), capture_output=True)
                if staged.returncode != 0:
                    has_changes = True
    except Exception as e:
        return {"is_repo": True, "has_changes": None, "message": f"Error checking status: {e}"}

    if has_changes:
        # Also report diff stat
        try:
            r = _run_git(["diff", "--stat", "HEAD", "--", timeline_file], cwd=repo, check=False)
            stat = r.stdout.strip()
        except Exception:
            stat = ""
        return {"is_repo": True, "has_changes": True, "message": "You have changes since your last saved version.", "stat": stat}
    else:
        return {"is_repo": True, "has_changes": False, "message": "All changes saved — you're up to date."}


def push(repo_path: Path | str = ".", remote: str = "origin", branch: str = None) -> str:
    repo = Path(repo_path)
    if not is_git_repo(repo):
        raise ValueError("Not a git repo")
    # Determine branch if not given
    if branch is None:
        try:
            r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo)
            branch = r.stdout.strip()
        except Exception:
            branch = "main"
    result = _run_git(["push", remote, branch], cwd=repo)
    return result.stdout + result.stderr


def restore_version(
    repo_path: Path | str,
    rev: str,
    out_path: Path | str,
    timeline_file: str = "timeline.otio",
) -> Path:
    """Restore a past version to out_path (does not overwrite working file unless out_path == timeline_file)."""
    repo = Path(repo_path)
    out = Path(out_path)
    if not is_git_repo(repo):
        raise ValueError("Not a git repo")

    # Use git show rev:timeline.otio
    result = _run_git(["show", f"{rev}:{timeline_file}"], cwd=repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.stdout, encoding="utf-8")
    return out


def log_versions(repo_path: Path | str = ".", limit: int = 20, timeline_file: str = "timeline.otio") -> list[dict]:
    """Return list of commits that touched timeline file."""
    repo = Path(repo_path)
    if not is_git_repo(repo):
        return []
    try:
        # Pretty format: hash|author|date|message
        r = _run_git(["log", f"-n{limit}", "--pretty=format:%H|%an|%ad|%s", "--date=short", "--", timeline_file], cwd=repo, check=False)
        if r.returncode != 0 or not r.stdout.strip():
            # Fallback to all commits
            r = _run_git(["log", f"-n{limit}", "--pretty=format:%H|%an|%ad|%s", "--date=short"], cwd=repo, check=False)
        lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
        out = []
        for line in lines:
            parts = line.split("|", 3)
            if len(parts) == 4:
                out.append({"hash": parts[0], "short": parts[0][:8], "author": parts[1], "date": parts[2], "message": parts[3]})
        return out
    except Exception:
        return []


def file_hash(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]
