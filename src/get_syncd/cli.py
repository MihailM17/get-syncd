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
        # preview for GUI
        try:
            from .preview import generate_preview
            generate_preview(repo, commit_hash, repo / dest)
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
    # interactive pick if no rev or rev == "interactive"
    rev_input = getattr(args, "rev", None)
    if not rev_input and getattr(args, "interactive", False):
        versions = git_store.log_versions(repo, limit=20)
        if not versions:
            ui.print_error("No versions yet.", hint="Save one first: get-syncd save -m \"First cut\"")
            sys.exit(1)
        rev_input = ui.prompt_pick_version(versions)
        if not rev_input:
            sys.exit(0)
    rev = _resolve_rev_alias(repo, rev_input) if rev_input else None
    if not rev:
        ui.print_error("No version selected.", hint="Run: get-syncd log then get-syncd restore <number> --apply")
        sys.exit(1)

    # --apply means overwrite timeline.otio in-place (one-click "change to this version")
    apply_mode = getattr(args, "apply", False)
    out = None
    if apply_mode:
        if getattr(args, "out", None):
            ui.print_error("--apply and --out can't be used together", hint="Use --apply to overwrite timeline.otio, or --out to write elsewhere.")
            sys.exit(1)
        out = repo / "timeline.otio"
        # confirm unless --yes
        if not getattr(args, "yes", False) and sys.stdin.isatty():
            if not ui.confirm_apply(rev_input, out):
                print("Cancelled.")
                sys.exit(0)
        # backup current timeline.otio if it exists
        try:
            if out.exists():
                backup_dir = repo / ".get-syncd" / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                import shutil, datetime
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(str(out), str(backup_dir / f"timeline-{ts}.otio"))
        except Exception:
            pass
    else:
        _out = getattr(args, "out", None)
        out = Path(_out) if _out else Path(rev_input + ".otio")
        if not _out and rev_input.isdigit():
            out = Path(f"version-{rev_input}.otio")

    # If rev_input is a file path that exists, copy directly (unless apply mode)
    if not apply_mode:
        p = Path(rev_input)
        if p.exists() and p.is_file():
            ui.print_hint(f"'{rev_input}' is a file, copying directly")
            import shutil
            shutil.copy2(str(p), str(out))
            ui.print_hint(f"Copied {rev_input} → {out}")
            return
    try:
        result_path = git_store.restore_version(repo, rev, out)
        if apply_mode:
            ui.print_restore_apply_success(rev_input, result_path, repo)
            # show diff vs previous HEAD for context
            try:
                # optional: hint status
                res = git_store.status(repo)
                if res.get("has_changes"):
                    ui.print_hint("Status is now 'Unsaved changes' — that's the restored version waiting in timeline.otio.\nRe-import in Resolve: File → Import Timeline → OpenTimelineIO → timeline.otio\nOr just run get-syncd save to keep this as a new version.")
            except Exception:
                pass
        else:
            if ui.HAS_RICH:
                ui.console.print(ui.Panel(
                    f"[bold]{rev_input} → {result_path.resolve()}[/]\n\n[dim]Next step in DaVinci Resolve:[/]\n[bold]File → Import Timeline → OpenTimelineIO[/] → pick:\n[cyan]{result_path.resolve()}[/]\n\n[dim]Resolve will create a NEW timeline — your current edit isn't overwritten until you import.[/]\n[dim]Tip: use [cyan]get-syncd restore {rev_input} --apply[/] to directly overwrite timeline.otio (one-click 'change to this version').[/]",
                    title="[green]Restored![/]",
                    border_style="green",
                ))
            else:
                print(f"Restored {rev} → {result_path}")
                print("Next step: In DaVinci Resolve, File → Import Timeline → OpenTimelineIO → select:")
                print(f"  {result_path.resolve()}")
                print(f"Tip: get-syncd restore {rev_input} --apply  to overwrite timeline.otio directly.")
    except Exception as e:
        ui.print_error(f"Restore failed: {e}", hint="Try 'get-syncd log' to see valid version numbers or hashes.")
        sys.exit(1)


def cmd_checkout(args):
    # alias for restore --apply
    args.apply = True
    # ensure required attrs exist (checkout parser doesn't have --out)
    if not hasattr(args, "out"):
        args.out = None
    if not hasattr(args, "interactive"):
        args.interactive = False
    if not hasattr(args, "yes"):
        args.yes = False
    return cmd_restore(args)


def cmd_watch(args):
    """Watch repo for Resolve exports and auto-prompt to save."""
    repo = _get_repo(args)
    if not git_store.is_git_repo(repo):
        ui.print_error("Not a Get Syncd project", hint="Run get-syncd init in your film folder first.")
        sys.exit(1)
    interval = getattr(args, "interval", 2.0)
    auto = getattr(args, "auto", False)
    ui.print_watch_start(repo, interval, auto)
    import time
    from pathlib import Path as _P
    watch_file = repo / "timeline.otio"
    # track last hash/mtime
    last_hash = ""
    if watch_file.exists():
        try:
            last_hash = git_store.file_hash(watch_file)
        except Exception:
            last_hash = str(watch_file.stat().st_mtime)
    try:
        while True:
            time.sleep(interval)
            if not watch_file.exists():
                continue
            try:
                cur_hash = git_store.file_hash(watch_file)
            except Exception:
                continue
            if cur_hash != last_hash:
                last_hash = cur_hash
                # file changed — check status
                result = git_store.status(repo)
                if result.get("has_changes"):
                    # show diff vs HEAD
                    try:
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                            tmp_path = tmp.name
                        try:
                            git_store.restore_version(repo, "HEAD", tmp_path)
                            old = parse_otio_file(tmp_path)
                            new = parse_otio_file(watch_file)
                            d = diff_timelines(old, new)
                            ui.print_watch_change(d)
                        finally:
                            try: _P(tmp_path).unlink()
                            except Exception: pass
                    except Exception as e:
                        ui.print_hint(f"Detected change in timeline.otio ({e})")
                    if auto:
                        # auto save without prompt
                        import subprocess, shutil
                        msg = changelog_line(d) if 'd' in locals() else "Auto save"
                        print(f"[watch] Auto-saving: {msg}")
                        # use save_version directly
                        try:
                            h = git_store.save_version(repo, watch_file, msg)
                            ui.print_save_success(h[:8], msg, repo)
                        except Exception as e:
                            ui.print_error(f"Auto-save failed: {e}")
                    else:
                        # interactive prompt
                        ans = ui.prompt_watch_save()
                        if ans == "save":
                            msg = changelog_line(d) if 'd' in locals() else "Save version"
                            # ask for custom message
                            custom = ui.prompt_save_message(msg)
                            try:
                                h = git_store.save_version(repo, watch_file, custom)
                                ui.print_save_success(h[:8], custom, repo)
                            except ValueError:
                                ui.print_save_no_changes()
                            except Exception as e:
                                ui.print_error(f"Save failed: {e}")
                        elif ans == "diff":
                            # already shown, loop again
                            pass
                        else:
                            ui.print_hint("Skipped — will prompt again on next change.")
    except KeyboardInterrupt:
        ui.print_hint("\nWatch stopped.")
        sys.exit(0)


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
    sp = sub.add_parser("restore", help="Bring back an old version", description="Makes a .otio file you re-import in Resolve. Use --apply to directly overwrite timeline.otio (one-click 'change to this version').")
    sp.add_argument("rev", nargs="?", help="Version to bring back: number (1=latest), hash, or HEAD~1 (omit for interactive picker)")
    sp.add_argument("--out", "-o", help="Where to write it (default: version-N.otio, ignored with --apply)")
    sp.add_argument("--apply", action="store_true", help="Overwrite timeline.otio directly so Resolve sees it next import/open (one-click change)")
    sp.add_argument("--yes", action="store_true", help="Skip confirmation when using --apply")
    sp.add_argument("--interactive", action="store_true", help="Pick version from a list")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_restore)

    # checkout / switch alias — one-click change
    for name in ("checkout", "switch", "use"):
        sp = sub.add_parser(name, help="Switch timeline to an old version (one-click, overwrites timeline.otio)")
        sp.add_argument("rev", nargs="?", help="Version to switch to: number, hash, or HEAD~1")
        sp.add_argument("--yes", action="store_true", help="Skip confirmation")
        sp.add_argument("--interactive", action="store_true", help="Pick version from a list")
        add_repo_arg(sp)
        sp.set_defaults(func=cmd_checkout)

    # watch — automatic folder watcher
    sp = sub.add_parser("watch", help="Watch for Resolve exports and auto-prompt to save", description="Watches timeline.otio in this folder. When Resolve re-exports, shows what changed and prompts to save. Use --auto to save without asking.")
    sp.add_argument("--interval", type=float, default=2.0, help="Poll every N seconds (default 2.0)")
    sp.add_argument("--auto", action="store_true", help="Auto-save without prompting")
    add_repo_arg(sp)
    sp.set_defaults(func=cmd_watch)

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

    # gui — sidecar desktop app
    sp = sub.add_parser("gui", help="Open sidecar desktop app (runs beside Resolve)", description="Sidecar window: Export from Resolve with one click, add note, save, see log/diff, change to any version, branches, watch. Keep open beside DaVinci Resolve.")
    add_repo_arg(sp)
    def _cmd_gui(args):
        from pathlib import Path as _P
        repo_val = getattr(args, "repo", None)
        if not repo_val:
            from .gui import DEFAULT_WORKSPACE
            repo = DEFAULT_WORKSPACE
        else:
            repo = _P(repo_val).resolve()
        from .gui import run_gui
        run_gui(repo)
    sp.set_defaults(func=_cmd_gui)

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
