"""CLI for Get Syncd.

Commands mirror the user-facing language (no git jargon in primary verbs):
  get-syncd save     — save a new version
  get-syncd status   — show if you have unsaved changes
  get-syncd log      — list past versions
  get-syncd diff     — diff two versions
  get-syncd view     — open visual diff in browser
  get-syncd restore  — restore a past version to .otio file
  get-syncd push     — push to GitHub
  get-syncd init     — init repo
"""

from __future__ import annotations

import argparse
import sys
import json
from pathlib import Path
import subprocess
import os

from .otio_parse import parse_otio_file, parse_otio_string
from .diff import diff_timelines, format_text, changelog_line
from .changelog import generate_commit_message
from . import git_store


def _resolve_rev_to_file(repo: Path, rev: str, timeline_file: str = "timeline.otio") -> Path:
    """Materialize a git rev to a temp file and return path."""
    import tempfile

    # If rev is a file path that exists, use it directly
    p = Path(rev)
    if p.exists() and p.is_file():
        return p
    # If rev contains ".otio", treat as file
    if rev.endswith(".otio") and p.exists():
        return p

    # Otherwise treat as git rev
    # Check if rev is valid git ref (HEAD, HEAD~1, hash, etc.)
    # Try git show
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".otio", delete=False, mode="w")
        # Use git_store to extract
        git_store.restore_version(repo, rev, tmp.name, timeline_file=timeline_file)
        return Path(tmp.name)
    except subprocess.CalledProcessError as e:
        # Fallback: try as file path relative to repo
        candidate = repo / rev
        if candidate.exists():
            return candidate
        print(f"Could not resolve revision '{rev}': {e.stderr.strip() if e.stderr else e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Could not resolve revision '{rev}': {e}", file=sys.stderr)
        sys.exit(1)


def cmd_init(args):
    repo = Path(args.path or ".").resolve()
    repo.mkdir(parents=True, exist_ok=True)
    try:
        git_store.init_repo(repo, remote_url=args.remote)
        print(f"Initialized Get Syncd repo at {repo}")
        if args.remote:
            print(f"Remote: {args.remote}")
        else:
            print("No remote set — add one later with: git remote add origin <url>")
            print("Tip: create a GitHub repo and push with: get-syncd push")
        # Create timeline placeholder gitignore already handled
    except Exception as e:
        print(f"init failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_save(args):
    repo = Path(args.repo or ".").resolve()
    # Determine source OTIO
    source = args.file
    if source is None:
        # Default: look for timeline.otio in repo or prompt
        default = repo / "timeline.otio"
        # If default exists and has been modified, use it? Actually save should copy from given file.
        # For MVP, if --file not given, assume user exported to timeline.otio already and wants to commit it in place.
        # So we just commit the existing timeline.otio if it exists.
        if default.exists():
            source = str(default)
            # Need a temp copy to avoid shutil copy to same file issue — handle in save_version
            # save_version copies source -> dest; if same file, it will still commit
            # We handle same-file case specially
            if Path(source).resolve() == (repo / "timeline.otio").resolve():
                # Commit directly without copy
                # Stage and commit existing file
                # Build message first
                pass
            else:
                pass
        else:
            print("No file specified. Export your timeline from Resolve to an .otio file, then run:", file=sys.stderr)
            print("  get-syncd save --file /path/to/export.otio -m \"Your message\"", file=sys.stderr)
            print("Or: get-syncd save --file timeline.otio", file=sys.stderr)
            sys.exit(1)

    source_path = Path(source)
    if not source_path.exists():
        print(f"File not found: {source}", file=sys.stderr)
        sys.exit(1)

    # Auto-generate message if not provided: diff vs HEAD and use changelog
    message = args.message
    if not message:
        # Try to diff current source vs HEAD's timeline.otio
        try:
            if git_store.is_git_repo(repo) and (repo / "timeline.otio").exists():
                # Parse both
                try:
                    old = parse_otio_file(repo / "timeline.otio")  # but this is same as source until committed
                    # Better: get HEAD version via git show
                    import tempfile

                    with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                        tmp_path = tmp.name
                    try:
                        git_store.restore_version(repo, "HEAD", tmp_path)
                        old = parse_otio_file(tmp_path)
                        new = parse_otio_file(source_path)
                        d = diff_timelines(old, new)
                        message = changelog_line(d)
                        print(f"Auto message: {message}")
                    except Exception:
                        message = "Save version"
                    finally:
                        try:
                            Path(tmp_path).unlink()
                        except Exception:
                            pass
                except Exception:
                    message = "Save version"
            else:
                message = "Initial version"
        except Exception:
            message = "Save version"

        if not message or message.strip() == "":
            message = "Save version"

    # Handle case where source is already the dest timeline.otio (common workflow: user exports directly to repo/timeline.otio)
    dest = "timeline.otio"
    if Path(source).resolve() == (repo / dest).resolve():
        # Just commit the existing file without copying
        if not git_store.is_git_repo(repo):
            git_store.init_repo(repo)
        # Stage
        subprocess.run(["git", "add", dest, ".gitignore"], cwd=str(repo), capture_output=True)
        # Check changes
        st = subprocess.run(["git", "status", "--porcelain", "--", dest], cwd=str(repo), capture_output=True, text=True)
        diff_cached = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(repo))
        if not st.stdout.strip() and diff_cached.returncode == 0:
            # Also check vs HEAD
            head_check = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=str(repo), capture_output=True)
            if head_check.returncode == 0:
                diff_head = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", dest], cwd=str(repo))
                if diff_head.returncode == 0:
                    print("No changes to save — timeline is identical to last version.", file=sys.stderr)
                    sys.exit(0)
        # Commit
        subprocess.run(["git", "commit", "-m", message], cwd=str(repo), check=True)
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True)
        commit_hash = r.stdout.strip()
        # Snapshot
        history_dir = repo / ".get-syncd" / "snapshots"
        history_dir.mkdir(parents=True, exist_ok=True)
        import shutil

        try:
            shutil.copy2(str(repo / dest), str(history_dir / f"{commit_hash[:8]}.otio"))
        except Exception:
            pass
        print(f"Saved version {commit_hash[:8]}: {message}")
        print(f"Runtime: {message}")
        return

    try:
        commit_hash = git_store.save_version(repo, source_path, message, timeline_dest=dest)
        print(f"Saved version {commit_hash[:8]}: {message}")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"save failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_status(args):
    repo = Path(args.repo or ".").resolve()
    result = git_store.status(repo)
    print(result["message"])
    if result.get("stat"):
        print(result["stat"])
    # Exit code 1 if has_changes?
    if result.get("has_changes") is True:
        # has unsaved changes — not an error, but indicate
        pass


def cmd_log(args):
    repo = Path(args.repo or ".").resolve()
    versions = git_store.log_versions(repo, limit=args.limit)
    if not versions:
        print("No versions yet — save one with: get-syncd save --file timeline.otio -m \"First cut\"")
        return
    for v in versions:
        print(f"{v['short']}  {v['date']}  {v['message']}")
        if args.verbose:
            print(f"  {v['hash']}  by {v['author']}")


def cmd_diff(args):
    repo = Path(args.repo or ".").resolve()

    # Resolve inputs: can be git revs or file paths
    # For convenience, support HEAD, HEAD~1, etc., plus file paths
    a_path = _resolve_rev_to_file(repo, args.a)
    b_path = _resolve_rev_to_file(repo, args.b)

    try:
        old = parse_otio_file(a_path)
        new = parse_otio_file(b_path)
    except Exception as e:
        print(f"Failed to parse OTIO: {e}", file=sys.stderr)
        sys.exit(1)

    d = diff_timelines(old, new, track_name=args.track, compare_all_video_tracks=args.all_tracks)

    if args.json:
        print(d.to_json())
    else:
        print(format_text(d, old_name=str(args.a), new_name=str(args.b)))
        # Also print one-line changelog suggestion
        print(f"\nChangelog: {changelog_line(d)}")


def cmd_restore(args):
    repo = Path(args.repo or ".").resolve()
    out = Path(args.out) if args.out else Path(args.rev + ".otio")
    # If rev looks like a file path, just copy
    rev = args.rev
    # If rev is a hash that is also a file path, prioritize git rev
    # Try git restore
    try:
        # If rev is a file that exists, error — user likely meant a git rev
        # But support both
        p = Path(rev)
        if p.exists() and p.is_file():
            print(f"Note: '{rev}' is a file, copying directly", file=sys.stderr)
            import shutil

            shutil.copy2(str(p), str(out))
            print(f"Copied {rev} → {out}")
            return

        result_path = git_store.restore_version(repo, rev, out)
        print(f"Restored {rev} → {result_path}")
        print("Next step: In DaVinci Resolve, File → Import Timeline → OpenTimelineIO → select:")
        print(f"  {result_path.resolve()}")
        print("(Resolve will create a new timeline — your current project is not overwritten until you import.)")
    except Exception as e:
        print(f"restore failed: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_push(args):
    repo = Path(args.repo or ".").resolve()
    try:
        out = git_store.push(repo, remote=args.remote, branch=args.branch)
        print(out)
        print("Pushed to GitHub — your version history is now backed up.")
    except subprocess.CalledProcessError as e:
        print(f"push failed: {e.stderr.strip() if e.stderr else e}", file=sys.stderr)
        print("Check: git remote -v and that you're authenticated (gh auth login or SSH key).", file=sys.stderr)
        sys.exit(1)


def cmd_view(args):
    """Launch visual diff viewer."""
    repo = Path(args.repo or ".").resolve()
    # Lazy import viewer
    try:
        from .viewer.app import run_viewer
    except ImportError as e:
        print(f"viewer not available: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve revs to diff
    a_rev = args.a
    b_rev = args.b
    # If not provided, default to HEAD~1 and HEAD
    if not a_rev or not b_rev:
        # Check if we have at least one commit
        versions = git_store.log_versions(repo, limit=2)
        if len(versions) >= 2:
            a_rev = versions[1]["hash"]
            b_rev = versions[0]["hash"]
        elif len(versions) == 1:
            print("Only one version saved — need two to diff. Make another save first.", file=sys.stderr)
            sys.exit(1)
        else:
            print("No versions yet.", file=sys.stderr)
            sys.exit(1)

    run_viewer(repo, a_rev, b_rev, port=args.port, open_browser=not args.no_browser)


def build_parser():
    p = argparse.ArgumentParser(prog="get-syncd", description="Get Syncd — version control for DaVinci Resolve")
    p.add_argument("--repo", dest="repo", help="Path to repo (default: current directory)")
    sub = p.add_subparsers(dest="command", required=True)

    def add_repo_arg(parser):
        parser.add_argument("--repo", dest="repo", help="Path to repo (default: current directory)", default=argparse.SUPPRESS)

    # init
    sp = sub.add_parser("init", help="Initialize a new Get Syncd repo")
    sp.add_argument("path", nargs="?", help="Path to init (default: current dir)")
    sp.add_argument("--remote", help="Git remote URL (e.g. https://github.com/you/film.git)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_init)

    # save
    sp = sub.add_parser("save", help="Save a new version (commit)")
    sp.add_argument("--file", "-f", help="Path to .otio file to save (exported from Resolve)")
    sp.add_argument("-m", "--message", help="Version message (auto-generated if omitted)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_save)

    # status
    sp = sub.add_parser("status", help="Show if you have unsaved changes")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_status)

    # log
    sp = sub.add_parser("log", help="List past versions")
    sp.add_argument("-n", "--limit", type=int, default=20, help="Number of versions to show")
    sp.add_argument("-v", "--verbose", action="store_true")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_log)

    # diff
    sp = sub.add_parser("diff", help="Diff two versions (git revs or .otio files)")
    sp.add_argument("a", help="Old version (git rev like HEAD~1 or path to .otio)")
    sp.add_argument("b", help="New version (git rev like HEAD or path to .otio)")
    sp.add_argument("--json", action="store_true", help="Output JSON")
    sp.add_argument("--text", action="store_true", help="Output text (default)")
    sp.add_argument("--track", help="Only diff this track name")
    sp.add_argument("--all-tracks", action="store_true", help="Diff all video tracks")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_diff)

    # restore
    sp = sub.add_parser("restore", help="Restore a past version to .otio file for Resolve import")
    sp.add_argument("rev", help="Revision to restore (git hash, HEAD~1, etc.)")
    sp.add_argument("--out", "-o", help="Output path (default: <rev>.otio)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_restore)

    # push
    sp = sub.add_parser("push", help="Push version history to GitHub")
    sp.add_argument("--remote", default="origin")
    sp.add_argument("--branch", help="Branch to push (default: current)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_push)

    # view
    sp = sub.add_parser("view", help="Open visual diff in browser")
    sp.add_argument("a", nargs="?", help="Old version (default: previous version)")
    sp.add_argument("b", nargs="?", help="New version (default: latest)")
    sp.add_argument("--port", type=int, default=8000)
    sp.add_argument("--no-browser", action="store_true")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_view)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    # Repo default handling: subcommands expect --repo, but init uses path
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        sys.exit(1)
    func(args)


if __name__ == "__main__":
    main()
