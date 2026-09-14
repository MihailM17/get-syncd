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
    # Use utf-8 explicitly — Resolve's Python API can switch locale to ascii (C), breaking git log with → arrow
    return subprocess.run(
        ["git"] + args, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=check
    )


def _posix_pathspec(p: str | Path) -> str:
    """Repo-relative path in git's forward-slash form.

    Windows callers build these with backslashes (str(Path.relative_to)),
    which git treats as escape characters — every `git show rev:<path>`,
    `git log -- <path>` etc. then fails. Normalize once, here: pathlib still
    resolves the result for filesystem use, and it matches `git show
    --name-only` output for comparisons.

    NOTE: the backslash replacement must be explicit — on POSIX a backslash
    is an ordinary filename character, so Path(...).as_posix() alone is a
    no-op there and would leave Windows-style input broken.
    """
    s = str(p).replace("\\", "/")
    try:
        return Path(s).as_posix()
    except Exception:
        return s


def is_git_repo(path: Path | str = ".") -> bool:
    p = Path(path)
    # Check for direct .git in this folder (handles nested projects correctly)
    if (p / ".git").exists():
        return True
    # Fallback: check if this exact path is a git repo (not just inside parent)
    try:
        r = _run_git(["rev-parse", "--git-dir"], cwd=p, check=False)
        if r.returncode == 0 and r.stdout.strip():
            git_dir = r.stdout.strip()
            # Resolve relative git dir
            try:
                gd = Path(git_dir)
                if not gd.is_absolute():
                    gd = (p / gd).resolve()
                else:
                    gd = gd.resolve()
                return gd == (p / ".git").resolve()
            except Exception:
                return False
        return False
    except Exception:
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


def find_timeline_candidate(repo_path: Path | str) -> Path | None:
    """Safe discovery of an .otio file when timeline.otio is missing.

    Priority: canonical timeline.otio > any .otio in root > recursive search.
    Excludes internal .get-syncd/ and .git/ and hidden files.
    Returns path or None. Does NOT pick snapshots.
    """
    repo = Path(repo_path)
    # 1. canonical (case variants on macOS case-insensitive fs)
    for name in ("timeline.otio", "Timeline.otio", "timeline.OTIO", "TIMELINE.OTIO"):
        p = repo / name
        if p.exists() and p.is_file():
            return p
    # 2. any .otio directly in repo root (non-recursive)
    cands: list[Path] = []
    for pat in ("*.otio", "*.OTIO"):
        for p in repo.glob(pat):
            if not p.is_file():
                continue
            if p.name.startswith("."):
                continue
            if ".get-syncd" in p.parts or ".git" in p.parts:
                continue
            # skip if inside a nested git repo (separate project)
            try:
                if (p.parent / ".git").exists():
                    # root glob candidates shouldn't be inside nested repo anyway, but skip if so
                    if p.parent.resolve() != repo.resolve():
                        continue
            except Exception:
                pass
            if p not in cands:
                cands.append(p)
    if cands:
        # prefer timeline.otio case-insensitive, then shortest name, then alpha
        cands.sort(key=lambda pp: (0 if pp.name.lower() == "timeline.otio" else 1, len(pp.name), pp.name.lower()))
        return cands[0]
    # 3. recursive search (e.g., Git test/timeline.otio) excluding internals
    # Note: skips files inside nested git repos (they are separate projects)
    all_otio: list[Path] = []
    for pat in ("*.otio", "*.OTIO"):
        for p in repo.rglob(pat):
            if not p.is_file():
                continue
            if ".get-syncd" in p.parts or ".git" in p.parts:
                continue
            if p.name.startswith("."):
                continue
            # skip hidden dirs
            try:
                rel_parts = p.relative_to(repo).parts[:-1]
            except Exception:
                rel_parts = []
            if any(part.startswith(".") for part in rel_parts):
                continue
            # skip if inside a nested git repo
            try:
                cur = p.parent
                nested = False
                while cur != repo and cur.is_relative_to(repo):
                    if (cur / ".git").exists():
                        nested = True
                        break
                    if cur.parent == cur:
                        break
                    cur = cur.parent
                if nested:
                    continue
            except Exception:
                pass
            if p not in all_otio:
                all_otio.append(p)
    if not all_otio:
        return None

    def _sort_key(pp: Path):
        rel = pp.relative_to(repo)
        depth = len(rel.parts)
        is_timeline = 0 if pp.name.lower() == "timeline.otio" else 1
        return (depth, is_timeline, len(str(pp)), str(pp).lower())

    all_otio.sort(key=_sort_key)
    return all_otio[0]


def init_repo(path: Path | str = ".", remote_url: Optional[str] = None) -> None:
    p = Path(path)
    if not is_git_repo(p):
        _run_git(["init"], cwd=p)
        _ensure_git_identity(p)
        # Ensure .gitignore
        gitignore = p / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Get Syncd — ignore media, keep timeline\n*.mp4\n*.mov\n*.mxf\n*.wav\n*.aiff\n*.braw\n!timeline.otio\n.get-syncd/\n.DS_Store\n")
        else:
            # ensure existing gitignore has .get-syncd and .DS_Store
            try:
                txt = gitignore.read_text()
                need = []
                if ".get-syncd" not in txt:
                    need.append(".get-syncd/")
                if ".DS_Store" not in txt:
                    need.append(".DS_Store")
                if need:
                    gitignore.write_text(txt.rstrip() + "\n" + "\n".join(need) + "\n")
            except Exception:
                pass
    else:
        _ensure_git_identity(p)
        # also patch existing gitignore if needed
        try:
            gi = p / ".gitignore"
            if gi.exists():
                txt = gi.read_text()
                need = []
                if ".get-syncd" not in txt:
                    need.append(".get-syncd/")
                if ".DS_Store" not in txt:
                    need.append(".DS_Store")
                if need:
                    gi.write_text(txt.rstrip() + "\n" + "\n".join(need) + "\n")
        except Exception:
            pass
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
    timeline_dest = _posix_pathspec(timeline_dest)
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
    timeline_file = _posix_pathspec(timeline_file)
    repo = Path(repo_path)
    if not is_git_repo(repo):
        return {"is_repo": False, "has_changes": None, "message": "Not a git repo — run get-syncd init"}

    # Check if timeline file exists — with safe fallback discovery
    tl = repo / timeline_file
    if not tl.exists():
        cand = find_timeline_candidate(repo)
        if cand and cand.exists() and cand != tl:
            # Found an .otio elsewhere (e.g., Git test/timeline.otio) but canonical missing
            try:
                rel = cand.relative_to(repo)
            except Exception:
                rel = cand
            return {
                "is_repo": True,
                "has_changes": True,
                "message": f"Found {rel} but {timeline_file} is missing — will sync from there. Tip: move it to {timeline_file}",
                "candidate": str(cand),
                "stat": "",
            }
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
                # Check staged vs HEAD as well — scoped to this file so a
                # staged save for ANOTHER timeline doesn't mark this one dirty
                staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", timeline_file], cwd=str(repo), capture_output=True)
                if staged.returncode != 0:
                    has_changes = True
    except Exception as e:
        return {"is_repo": True, "has_changes": None, "message": f"Error checking status: {e}"}

    if not has_changes:
        # Brand-new (never saved) files are untracked: `git diff` does not see
        # them at all, so check porcelain explicitly — otherwise the first save
        # of a timeline reports "up to date" and Save stays blocked.
        try:
            por = _run_git(["status", "--porcelain", "--", timeline_file], cwd=repo, check=False)
            if por.stdout.strip().startswith("??"):
                return {"is_repo": True, "has_changes": True, "message": "New file — save your first version.", "stat": ""}
        except Exception:
            pass

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
    timeline_file = _posix_pathspec(timeline_file)
    repo = Path(repo_path)
    out = Path(out_path)
    if not is_git_repo(repo):
        raise ValueError("Not a git repo")

    # Use git show rev:timeline.otio
    result = _run_git(["show", f"{rev}:{timeline_file}"], cwd=repo)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.stdout, encoding="utf-8")
    return out


def commit_otio_files(repo_path: Path | str, rev: str) -> list[str]:
    """Return .otio files (repo-relative) touched by a commit. Best-effort, never raises."""
    repo = Path(repo_path)
    try:
        r = _run_git(["show", "--name-only", "--pretty=format:", str(rev)], cwd=repo, check=False)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        out = []
        for line in r.stdout.splitlines():
            line = line.strip()
            if line.lower().endswith(".otio") and line not in out:
                out.append(line)
        return out
    except Exception:
        return []


def log_versions(
    repo_path: Path | str = ".",
    limit: int = 20,
    timeline_file: str | list[str] | None = "timeline.otio",
    fallback: bool = True,
) -> list[dict]:
    """Return list of commits that touched timeline file(s).

    timeline_file may be a single path, a list of paths (union, newest-first),
    or None for all commits in the repo (no pathspec). When a single file has
    no history, the all-commits fallback applies unless fallback=False — pass
    fallback=False for per-timeline views so an untouched timeline shows
    nothing instead of other timelines' versions.
    """
    repo = Path(repo_path)
    if not is_git_repo(repo):
        return []
    try:
        # Pretty format: hash|author|date|message
        if timeline_file is None:
            paths: list[str] = []
        elif isinstance(timeline_file, (list, tuple)):
            paths = [_posix_pathspec(p) for p in timeline_file if str(p).strip()]
        else:
            paths = [_posix_pathspec(timeline_file)]
        if paths:
            r = _run_git(["log", f"-n{limit}", "--pretty=format:%H|%an|%ad|%s", "--date=short", "--"] + paths, cwd=repo, check=False)
        else:
            # All view: every branch, so versions on experiment branches show too
            r = _run_git(["log", "--all", f"-n{limit}", "--pretty=format:%H|%an|%ad|%s", "--date=short"], cwd=repo, check=False)
        if r.returncode != 0 or not r.stdout.strip():
            if fallback and len(paths) == 1:
                # Fallback to all commits (legacy behavior for single-file repos)
                r = _run_git(["log", f"-n{limit}", "--pretty=format:%H|%an|%ad|%s", "--date=short"], cwd=repo, check=False)
            else:
                return []
        lines = [l for l in r.stdout.strip().split("\n") if l.strip()]
        out = []
        for line in lines:
            parts = line.split("|", 3)
            if len(parts) == 4:
                out.append({"hash": parts[0], "short": parts[0][:8], "author": parts[1], "date": parts[2], "message": parts[3]})
        return out
    except Exception:
        return []


def delete_version(repo_path: Path | str, rev: str, timeline_file: str = "timeline.otio") -> dict:
    """Delete a version (commit) from history.

    Handles both HEAD and older commits via reset/rebase. Cleans up preview/snapshot.
    Returns {"ok": True, "deleted": short, "new_head": short_or_None}
    """
    timeline_file = _posix_pathspec(timeline_file)
    repo = Path(repo_path)
    if not is_git_repo(repo):
        raise ValueError("Not a git repo")
    # Resolve rev to full hash
    try:
        r = _run_git(["rev-parse", rev], cwd=repo)
        full = r.stdout.strip()
        short = full[:8]
    except subprocess.CalledProcessError as e:
        raise ValueError(f"Version not found: {rev} ({e.stderr.strip() if e.stderr else e})")

    # Check existence in log
    versions = log_versions(repo, limit=100, timeline_file=timeline_file)
    # Also check via git log all if not found in timeline-specific log (e.g., gitignore commits)
    found = any(v["hash"] == full or v["hash"].startswith(rev) or rev.startswith(v["hash"][:8]) for v in versions)
    if not found:
        # Fallback: check if rev exists at all
        try:
            _run_git(["cat-file", "-e", full], cwd=repo)
        except subprocess.CalledProcessError:
            raise ValueError(f"Version not found: {rev}")

    # Determine if rev is HEAD
    try:
        head = _run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()
    except subprocess.CalledProcessError:
        head = ""

    is_head = head and (head == full or head.startswith(rev) or rev.startswith(head[:8]))

    # Count commits
    try:
        cnt_r = _run_git(["rev-list", "--count", "HEAD"], cwd=repo, check=False)
        cnt = int(cnt_r.stdout.strip()) if cnt_r.returncode == 0 and cnt_r.stdout.strip().isdigit() else 0
    except Exception:
        cnt = 0

    if is_head:
        if cnt <= 1:
            # Only one commit — delete HEAD
            try:
                _run_git(["update-ref", "-d", "HEAD"], cwd=repo)
                # Remove timeline file from index if present
                _run_git(["rm", "--cached", timeline_file], cwd=repo, check=False)
                # Keep working file? Remove it to reflect no versions
                # Don't delete working file automatically — leave it for user
            except Exception as e:
                raise ValueError(f"Failed to delete initial version: {e}")
            # Clean up snapshot/preview
            try:
                (repo / ".get-syncd" / "snapshots" / f"{short}.otio").unlink(missing_ok=True)
                (repo / ".get-syncd" / "previews" / f"{short}.png").unlink(missing_ok=True)
            except Exception:
                pass
            return {"ok": True, "deleted": short, "new_head": None}
        else:
            # Reset HEAD to parent
            try:
                _run_git(["reset", "--hard", "HEAD~1"], cwd=repo)
            except subprocess.CalledProcessError as e:
                raise ValueError(f"Failed to delete {short}: {e.stderr.strip() if e.stderr else e}")
            # Clean up
            try:
                (repo / ".get-syncd" / "snapshots" / f"{short}.otio").unlink(missing_ok=True)
                (repo / ".get-syncd" / "previews" / f"{short}.png").unlink(missing_ok=True)
            except Exception:
                pass
            try:
                new_head = _run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()[:8]
            except Exception:
                new_head = None
            return {"ok": True, "deleted": short, "new_head": new_head}
    else:
        # Not HEAD — use rebase to drop the commit
        # Find parent
        try:
            parent_r = _run_git(["rev-parse", f"{full}^"], cwd=repo)
            parent = parent_r.stdout.strip()
        except subprocess.CalledProcessError:
            # Root commit — replay later commits onto empty orphan branch
            try:
                # Get commits after root in reverse order (root .. HEAD)
                commits_r = _run_git(["rev-list", "--reverse", "HEAD"], cwd=repo)
                all_commits = [c.strip() for c in commits_r.stdout.strip().split("\n") if c.strip()]
                # all_commits[0] should be root (full)
                try:
                    root_idx = all_commits.index(full)
                except ValueError:
                    # Find by short
                    root_idx = next((i for i, c in enumerate(all_commits) if c.startswith(short) or short.startswith(c[:8])), -1)
                    if root_idx == -1:
                        raise ValueError("Root commit not found in history")
                later = all_commits[root_idx+1:]
                if not later:
                    # Only root existed — already handled as single commit case, but fallback
                    _run_git(["update-ref", "-d", "HEAD"], cwd=repo, check=False)
                    _run_git(["rm", "--cached", timeline_file], cwd=repo, check=False)
                else:
                    # Create orphan branch and replay each later commit's timeline content
                    # Save current branch name
                    try:
                        cur_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo).stdout.strip()
                    except Exception:
                        cur_branch = "main"
                    if cur_branch == "HEAD":
                        cur_branch = "main"
                    # Create temp orphan
                    _run_git(["checkout", "--orphan", "temp-replay-root"], cwd=repo, check=False)
                    # Clean untracked leftovers FIRST, while .gitignore is still
                    # in place — and always spare the app cache plus any .otio
                    # (a dropped commit's leftovers are harmless; deleting the
                    # user's unsaved exports, previews or media is not).
                    _run_git(["clean", "-fd", "-e", ".get-syncd", "-e", "*.otio"], cwd=repo, check=False)
                    _run_git(["rm", "-rf", "."], cwd=repo, check=False)
                    for c in later:
                        # Get commit message and author
                        msg_r = _run_git(["log", "-1", "--pretty=%B", c], cwd=repo, check=False)
                        msg = msg_r.stdout.strip() if msg_r.returncode == 0 else f"Replay {c[:8]}"
                        # Get timeline content at that commit
                        show_r = _run_git(["show", f"{c}:{timeline_file}"], cwd=repo, check=False)
                        if show_r.returncode == 0:
                            Path(repo / timeline_file).write_text(show_r.stdout, encoding="utf-8")
                            _run_git(["add", timeline_file], cwd=repo, check=False)
                        else:
                            # If file not in that commit, skip
                            pass
                        # Also add .gitignore if exists in that commit
                        gi_r = _run_git(["show", f"{c}:.gitignore"], cwd=repo, check=False)
                        if gi_r.returncode == 0:
                            Path(repo / ".gitignore").write_text(gi_r.stdout, encoding="utf-8")
                            _run_git(["add", ".gitignore"], cwd=repo, check=False)
                        # Commit with original message
                        _run_git(["commit", "-m", msg], cwd=repo, check=False)
                    # Delete old branch and rename
                    _run_git(["branch", "-D", cur_branch], cwd=repo, check=False)
                    _run_git(["branch", "-m", cur_branch], cwd=repo, check=False)
            except subprocess.CalledProcessError as e:
                try:
                    _run_git(["rebase", "--abort"], cwd=repo, check=False)
                    _run_git(["checkout", cur_branch if 'cur_branch' in locals() else "main"], cwd=repo, check=False)
                except Exception:
                    pass
                raise ValueError(f"Failed to delete root version {short}: {e.stderr.strip() if e.stderr else str(e)}")
            except Exception as e:
                raise ValueError(f"Failed to delete root version {short}: {e}")
            # Clean up
            try:
                (repo / ".get-syncd" / "snapshots" / f"{short}.otio").unlink(missing_ok=True)
                (repo / ".get-syncd" / "previews" / f"{short}.png").unlink(missing_ok=True)
            except Exception:
                pass
            try:
                new_head = _run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()[:8]
            except Exception:
                new_head = None
            return {"ok": True, "deleted": short, "new_head": new_head}

        # Normal non-head, non-root: rebase --onto parent rev HEAD
        try:
            # Use --no-verify to avoid hooks, and set GIT_SEQUENCE_EDITOR to true to avoid interactive
            env = os.environ.copy()
            env["GIT_SEQUENCE_EDITOR"] = "true"
            # Use rebase --onto
            subprocess.run(
                ["git", "rebase", "--onto", parent, full, "HEAD"],
                cwd=str(repo),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            # Try to abort rebase on failure
            try:
                _run_git(["rebase", "--abort"], cwd=repo, check=False)
            except Exception:
                pass
            raise ValueError(f"Failed to delete {short}: {e.stderr.strip() if e.stderr else str(e)}")

        # Clean up snapshot/preview for deleted hash
        try:
            (repo / ".get-syncd" / "snapshots" / f"{short}.otio").unlink(missing_ok=True)
            (repo / ".get-syncd" / "previews" / f"{short}.png").unlink(missing_ok=True)
        except Exception:
            pass
        try:
            new_head = _run_git(["rev-parse", "HEAD"], cwd=repo).stdout.strip()[:8]
        except Exception:
            new_head = None
        return {"ok": True, "deleted": short, "new_head": new_head}


def file_hash(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]
