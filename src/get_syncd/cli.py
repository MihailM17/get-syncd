"""CLI for Get Syncd — friendly, plain-English, color when you want it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import subprocess
import tempfile

from .otio_parse import parse_otio_file
from .diff import diff_timelines, format_text, changelog_line
from . import git_store
from . import ui


# ---------- helpers ----------

def _get_repo(args) -> Path:
    # --repo can be global or per-command (we use SUPPRESS trick)
    path = getattr(args, "repo", None)
    if path is None:
        # also check top-level?
        path = "."
    return Path(path).resolve()


def _resolve_rev_alias(repo: Path, rev: str) -> str:
    """Allow numeric shortcuts: 1 = latest, 2 = previous, etc. Also pass through HEAD/file revs."""
    if rev is None:
        return rev
    # numeric ?
    if rev.strip().isdigit():
        n = int(rev.strip())
        versions = git_store.log_versions(repo, limit=max(20, n))
        if not versions:
            return rev
        # 1 = newest (index 0)
        idx = n - 1
        if 0 <= idx < len(versions):
            return versions[idx]["hash"]
        # out of range, return as-is to surface error
        return rev
    return rev


def _resolve_rev_to_file(repo: Path, rev: str, timeline_file: str = "timeline.otio") -> Path:
    # numeric alias first
    rev = _resolve_rev_alias(repo, rev)
    p = Path(rev)
    if p.exists() and p.is_file():
        return p
    if rev.endswith(".otio") and p.exists():
        return p
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".otio", delete=False, mode="w")
        git_store.restore_version(repo, rev, tmp.name, timeline_file=timeline_file)
        return Path(tmp.name)
    except subprocess.CalledProcessError as e:
        candidate = repo / rev
        if candidate.exists():
            return candidate
        ui.print_error(f"Can't find version '{rev}'", hint=f"Try 'get-syncd log' to see available versions. Details: {e.stderr.strip() if e.stderr else e}")
        sys.exit(1)
    except Exception as e:
        ui.print_error(f"Can't read version '{rev}': {e}", hint="Try 'get-syncd log' to see what exists.")
        sys.exit(1)


# ---------- commands ----------

def cmd_init(args):
    repo = Path(args.path or ".").resolve()
    repo.mkdir(parents=True, exist_ok=True)
    try:
        git_store.init_repo(repo, remote_url=args.remote)
        ui.print_init_success(repo, args.remote)
    except Exception as e:
        ui.print_error(f"Init failed: {e}")
        sys.exit(1)


def cmd_save(args):
    repo = _get_repo(args)
    source = args.file
    # nice discovery if no --file
    if source is None:
        default = repo / "timeline.otio"
        # also look for any .otio in repo
        if default.exists():
            source = str(default)
        else:
            # look for any otio file in repo
            cands = list(repo.glob("*.otio"))
            if cands:
                if len(cands) == 1:
                    source = str(cands[0])
                    ui.print_hint(f"Using {cands[0].name} (no --file given).")
                else:
                    ui.print_error(
                        "Multiple .otio files found — which one to save?",
                        hint=f"Found: {', '.join(p.name for p in cands)}\nRun: get-syncd save --file <name>.otio -m \"your note\"",
                    )
                    sys.exit(1)
            else:
                ui.print_error(
                    "No timeline file found.",
                    hint="In Resolve: File → Export Timeline → OpenTimelineIO → save as timeline.otio in this folder, then run get-syncd save",
                )
                sys.exit(1)

    source_path = Path(source)
    if not source_path.exists():
        ui.print_error(f"File not found: {source}", hint="Check the path and try again. Example: get-syncd save --file timeline.otio")
        sys.exit(1)

    # Auto message via diff if not provided — then interactive prompt
    message = args.message
    is_first = False
    auto_msg = None

    # Detect first save
    try:
        is_first = not git_store.is_git_repo(repo) or not (repo / "timeline.otio").exists() or git_store.log_versions(repo, limit=1) == []
        # check HEAD exists
        head_check = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=str(repo), capture_output=True)
        is_first = head_check.returncode != 0
    except Exception:
        is_first = False

    if not message:
        try:
            if not is_first and git_store.is_git_repo(repo):
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    git_store.restore_version(repo, "HEAD", tmp_path)
                    old = parse_otio_file(tmp_path)
                    new = parse_otio_file(source_path)
                    d = diff_timelines(old, new)
                    auto_msg = changelog_line(d)
                except Exception:
                    auto_msg = "Save version"
                finally:
                    try: Path(tmp_path).unlink()
                    except Exception: pass
            else:
                auto_msg = "Initial version"
        except Exception:
            auto_msg = "Save version"
        # interactive prompt (shows auto suggestion, Enter to accept)
        if getattr(args, "no_prompt", False):
            message = auto_msg
        else:
            message = ui.prompt_save_message(auto_msg, is_first=is_first)
        if not message or not message.strip():
            message = auto_msg or "Save version"

    # Commit path: same-file handling
    dest = "timeline.otio"
    if Path(source).resolve() == (repo / dest).resolve():
        if not git_store.is_git_repo(repo):
            git_store.init_repo(repo)
        subprocess.run(["git", "add", dest, ".gitignore"], cwd=str(repo), capture_output=True)
        st = subprocess.run(["git", "status", "--porcelain", "--", dest], cwd=str(repo), capture_output=True, text=True)
        diff_cached = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(repo), capture_output=True)
        if not st.stdout.strip() and diff_cached.returncode == 0:
            head_check = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=str(repo), capture_output=True)
            if head_check.returncode == 0:
                diff_head = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", dest], cwd=str(repo), capture_output=True)
                if diff_head.returncode == 0:
                    ui.print_save_no_changes()
                    sys.exit(0)
        try:
            subprocess.run(["git", "commit", "-m", message], cwd=str(repo), check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            ui.print_error("Save failed", hint=e.stderr.decode() if e.stderr else str(e))
            sys.exit(1)
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), capture_output=True, text=True, check=True)
        commit_hash = r.stdout.strip()
        # snapshot
        history_dir = repo / ".get-syncd" / "snapshots"
        history_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        try:
            shutil.copy2(str(repo / dest), str(history_dir / f"{commit_hash[:8]}.otio"))
        except Exception:
            pass
        ui.print_save_success(commit_hash[:8], message, repo, is_first=is_first)
        return

    try:
        commit_hash = git_store.save_version(repo, source_path, message, timeline_dest=dest)
        ui.print_save_success(commit_hash[:8], message, repo, is_first=is_first)
    except ValueError as e:
        # no changes
        ui.print_save_no_changes()
        sys.exit(0)
    except Exception as e:
        ui.print_error(f"Save failed: {e}")
        sys.exit(1)


def cmd_status(args):
    repo = _get_repo(args)
    result = git_store.status(repo)
    ui.print_status(result, repo)


def cmd_log(args):
    repo = _get_repo(args)
    versions = git_store.log_versions(repo, limit=args.limit)
    if args.verbose:
        ui.print_log_verbose(versions)
    else:
        ui.print_log(versions, limit=args.limit)


def cmd_diff(args):
    repo = _get_repo(args)
    # Support numeric aliases and file paths
    a_raw = args.a
    b_raw = args.b
    # Resolve numeric -> hash before mapping to file
    a_path = _resolve_rev_to_file(repo, a_raw)
    b_path = _resolve_rev_to_file(repo, b_raw)

    try:
        old = parse_otio_file(a_path)
        new = parse_otio_file(b_path)
    except Exception as e:
        ui.print_error(f"Can't read timelines: {e}")
        sys.exit(1)

    d = diff_timelines(old, new, track_name=args.track, compare_all_video_tracks=args.all_tracks)

    if args.json:
        print(d.to_json())
        return

    # Friendly TUI
    old_label = a_raw if a_raw else "old"
    new_label = b_raw if b_raw else "new"
    # If they used numbers, show short hash labels too
    versions = git_store.log_versions(repo, limit=20)
    def label_for(r):
        if r and r.isdigit() and versions and 1 <= int(r) <= len(versions):
            return f"#{r} ({versions[int(r)-1]['short']})"
        return r
    ui.print_diff_summary(d.summary, label_for(old_label), label_for(new_label), warnings=d.warnings)
    ui.print_diff_changes([c.to_dict() for c in d.changes], summary=d.summary)
    if ui.HAS_RICH:
        # also show text fallback collapsible
        pass
    else:
        print(format_text(d, old_name=old_label, new_name=new_label))
        print(f"\nChangelog: {changelog_line(d)}")


def cmd_restore(args):
    repo = _get_repo(args)
    rev = _resolve_rev_alias(repo, args.rev)
    out = Path(args.out) if args.out else Path(args.rev + ".otio")
    # If args.out not given and rev was numeric, name by version file
    if not args.out and args.rev.isdigit():
        out = Path(f"version-{args.rev}.otio")
    # If rev still looks like file path
    p = Path(args.rev)
    if p.exists() and p.is_file():
        ui.print_hint(f"'{args.rev}' is a file, copying directly")
        import shutil
        shutil.copy2(str(p), str(out))
        ui.print_hint(f"Copied {args.rev} → {out}")
        return
    try:
        result_path = git_store.restore_version(repo, rev, out)
        if ui.HAS_RICH:
            ui.console.print(ui.Panel(
                f"[bold]{args.rev} → {result_path.resolve()}[/]\n\n[dim]Next step in DaVinci Resolve:[/]\n[bold]File → Import Timeline → OpenTimelineIO[/] → pick:\n[cyan]{result_path.resolve()}[/]\n\n[dim]Resolve will create a NEW timeline — your current edit isn't overwritten until you import.[/]",
                title="[green]Restored![/]",
                border_style="green",
            ))
        else:
            print(f"Restored {rev} → {result_path}")
            print("Next step: In DaVinci Resolve, File → Import Timeline → OpenTimelineIO → select:")
            print(f"  {result_path.resolve()}")
    except Exception as e:
        ui.print_error(f"Restore failed: {e}", hint="Try 'get-syncd log' to see valid version numbers or hashes.")
        sys.exit(1)


def cmd_push(args):
    repo = _get_repo(args)
    try:
        out = git_store.push(repo, remote=args.remote, branch=args.branch)
        if ui.HAS_RICH:
            ui.console.print(ui.Panel(out.strip() or "Pushed.", title="[green]Backed up to GitHub[/]", border_style="green"))
            ui.print_hint("Your version history now survives a dead laptop.")
        else:
            print(out)
            print("Pushed to GitHub — your version history is now backed up.")
    except subprocess.CalledProcessError as e:
        ui.print_error(f"Push failed: {e.stderr.strip() if e.stderr else e}", hint="Check: git remote -v and that you're logged in (gh auth login or SSH key).")
        sys.exit(1)


def cmd_view(args):
    repo = _get_repo(args)
    try:
        from .viewer.app import run_viewer
    except ImportError as e:
        ui.print_error(f"Viewer not available: {e}")
        sys.exit(1)
    a_rev = _resolve_rev_alias(repo, args.a) if args.a else None
    b_rev = _resolve_rev_alias(repo, args.b) if args.b else None
    if not a_rev or not b_rev:
        versions = git_store.log_versions(repo, limit=2)
        if len(versions) >= 2:
            a_rev = versions[1]["hash"]
            b_rev = versions[0]["hash"]
        elif len(versions) == 1:
            ui.print_error("Only one version saved — need two to view a diff.", hint="Make another edit and run get-syncd save")
            sys.exit(1)
        else:
            ui.print_error("No versions yet.", hint="Save one first: get-syncd save -m \"First cut\"")
            sys.exit(1)
    # Show a quick summary before launching browser
    if ui.HAS_RICH:
        ui.console.print(f"[dim]Opening visual diff for[/] [cyan]{args.a or 'previous'} → {args.b or 'latest'}[/] [dim]at http://localhost:{args.port}/[/]")
    run_viewer(repo, a_rev, b_rev, port=args.port, open_browser=not args.no_browser)


def cmd_dashboard(args):
    repo = _get_repo(args)
    result = git_store.status(repo)
    versions = git_store.log_versions(repo, limit=5)
    ui.print_dashboard(repo, result, versions)


def build_parser():
    p = argparse.ArgumentParser(
        prog="get-syncd",
        description="Get Syncd — save-game for your DaVinci Resolve edit. Friendly, no git jargon.",
        epilog="Examples:  get-syncd save  |  get-syncd status  |  get-syncd log  |  get-syncd diff 2 1  |  get-syncd view",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--repo", dest="repo", help="Folder to use (default: current folder)")

    sub = p.add_subparsers(dest="command")

    def add_repo_arg(parser):
        parser.add_argument("--repo", dest="repo", help="Folder to use (default: current folder)", default=argparse.SUPPRESS)

    # init
    sp = sub.add_parser("init", help="Set up a new project (one time per film)", description="Create a new Get Syncd project in this folder.")
    sp.add_argument("path", nargs="?", help="Folder to set up (default: this folder)")
    sp.add_argument("--remote", help="GitHub address (e.g. https://github.com/you/film.git)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_init)

    # save — friendlier help
    sp = sub.add_parser("save", help="Save a new version", description="Save what you just exported from Resolve. Auto-describes what changed if you don't write a note.")
    sp.add_argument("--file", "-f", help="Which .otio file to save (default: timeline.otio in this folder)")
    sp.add_argument("-m", "--message", help="Short note like \"Trimmed intro\" (auto-made if you skip it)")
    sp.add_argument("--no-prompt", action="store_true", help="Don't ask to edit the auto note (for scripts)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_save)

    # status
    sp = sub.add_parser("status", help="Check if you have unsaved edits")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_status)

    # log
    sp = sub.add_parser("log", help="See all saved versions")
    sp.add_argument("-n", "--limit", type=int, default=20, help="How many to show")
    sp.add_argument("-v", "--verbose", action="store_true", help="Show full hashes")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_log)

    # diff
    sp = sub.add_parser("diff", help="See what changed between two versions", description="Compare any two versions: numbers from log (e.g. 2 1), git names (HEAD~1 HEAD), or .otio files.")
    sp.add_argument("a", help="Older version: number (1=latest), hash, HEAD~1, or path to .otio")
    sp.add_argument("b", help="Newer version")
    sp.add_argument("--json", action="store_true", help="Machine-readable output")
    sp.add_argument("--track", help="Only compare this track name")
    sp.add_argument("--all-tracks", action="store_true", help="Compare all video tracks")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_diff)

    # restore
    sp = sub.add_parser("restore", help="Bring back an old version", description="Makes a .otio file you re-import in Resolve (File → Import Timeline → OpenTimelineIO). Your current edit isn't touched until you import.")
    sp.add_argument("rev", help="Version to bring back: number (1=latest), hash, or HEAD~1")
    sp.add_argument("--out", "-o", help="Where to write it (default: version-N.otio)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_restore)

    # push
    sp = sub.add_parser("push", help="Back up to GitHub")
    sp.add_argument("--remote", default="origin", help="Git remote name")
    sp.add_argument("--branch", help="Branch to push (default: current)")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_push)

    # view
    sp = sub.add_parser("view", help="Open a pretty visual diff in your browser")
    sp.add_argument("a", nargs="?", help="Older version (default: previous)")
    sp.add_argument("b", nargs="?", help="Newer version (default: latest)")
    sp.add_argument("--port", type=int, default=8000, help="Browser port")
    sp.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_view)

    # dashboard alias (no subcommand)
    return p


def main():
    parser = build_parser()
    # If no subcommand, show friendly dashboard instead of error
    if len(sys.argv) == 1:
        try:
            class Args: repo = "."
            cmd_dashboard(Args())
        except Exception:
            parser.print_help()
        sys.exit(0)
    # Also handle `get-syncd --repo X` with no subcommand -> dashboard for that repo
    try:
        args = parser.parse_args()
    except SystemExit as e:
        if e.code == 2 and len(sys.argv) <= 3:
            repo_val = "."
            if "--repo" in sys.argv:
                idx = sys.argv.index("--repo")
                if idx + 1 < len(sys.argv):
                    repo_val = sys.argv[idx + 1]
            try:
                class Args: repo = repo_val
                cmd_dashboard(Args())
            except Exception:
                parser.print_help()
            sys.exit(0)
        raise
    func = getattr(args, "func", None)
    if func is None:
        try:
            class Args: repo = getattr(args, "repo", ".")
            cmd_dashboard(Args())
        except Exception:
            parser.print_help()
        sys.exit(0)
    func(args)


if __name__ == "__main__":
    main()
