"""Friendly Terminal UI for Get Syncd.

All helpers work with Rich if installed, and degrade gracefully to plain ANSI
or no-color if Rich/term is unavailable. Never crashes because of UI.
"""

from __future__ import annotations

import sys
import shutil
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.columns import Columns
    from rich.markup import escape
    from rich import box
    HAS_RICH = True
    console = Console()
except Exception:
    HAS_RICH = False
    console = None

# Fallback ANSI codes
ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "blue": "\033[34m",
    "gray": "\033[90m",
}

def _w() -> int:
    return shutil.get_terminal_size((80, 20)).columns

def _color(name: str, text: str) -> str:
    if HAS_RICH:
        return f"[{name}]{text}[/{name}]"
    code = ANSI.get(name, "")
    rst = ANSI["reset"] if code else ""
    return f"{code}{text}{rst}" if code else text

def print_banner():
    title = "Get Syncd — version control for DaVinci Resolve"
    subtitle = "Your edit's save-game. Media stays local, only the timeline is versioned."
    if HAS_RICH:
        console.print(Panel(
            Text(subtitle, style="dim"),
            title=f"[bold cyan]{title}[/]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
        ))
    else:
        print(f"\n{ANSI['bold']}{title}{ANSI['reset']}")
        print(f"{ANSI['dim']}{subtitle}{ANSI['reset']}\n")

def print_help_hint():
    if HAS_RICH:
        console.print("[dim]Try [bold]get-syncd status[/] to check for unsaved changes, [bold]get-syncd log[/] to see history, or [bold]get-syncd save[/] to save a version.[/]")
    else:
        print("Try: get-syncd status  |  get-syncd log  |  get-syncd save")

def hr():
    if HAS_RICH:
        console.rule(style="dim")
    else:
        print("-" * min(_w(), 60))

# ---------- status ----------
def print_status(result: dict, repo: Path):
    is_repo = result.get("is_repo")
    has_changes = result.get("has_changes")
    msg = result.get("message", "")
    stat = result.get("stat", "")

    if not is_repo:
        if HAS_RICH:
            console.print(Panel(
                f"{msg}\n\n[bold]Next:[/] run [cyan]get-syncd init[/] in this folder",
                title="[yellow]Not a Get Syncd project yet[/]",
                border_style="yellow",
            ))
        else:
            print(f"\n{ANSI['yellow']}Not a Get Syncd project yet{ANSI['reset']}")
            print(msg)
            print("Next: get-syncd init")
        return

    if has_changes is True:
        # Yellow warning
        if HAS_RICH:
            console.print(Panel(
                f"[yellow bold]● You have changes since your last saved version.[/]\n{escape(msg)}\n\n[bold]Next:[/] [cyan]get-syncd save[/]  or  [cyan]get-syncd save -m \"what you changed\"[/]\n[dim]Then File → Export Timeline → OpenTimelineIO → timeline.otio before saving.[/]",
                title="[yellow]Unsaved changes[/]",
                border_style="yellow",
            ))
            if stat:
                console.print(Panel(stat.strip(), title="what changed", border_style="dim", box=box.ROUNDED))
        else:
            print(f"\n{ANSI['yellow']}● You have changes since your last saved version.{ANSI['reset']}")
            print(msg)
            if stat:
                print(stat.strip())
            print(f"\nNext: get-syncd save")
    elif has_changes is False:
        if HAS_RICH:
            console.print(Panel(
                f"[green bold]✓ All changes saved — you're up to date.[/]\n{escape(msg)}\n\n[dim]Keep editing in Resolve, then File → Export → OpenTimelineIO → timeline.otio → [cyan]get-syncd save[/][/]",
                title="[green]Up to date[/]",
                border_style="green",
            ))
        else:
            print(f"\n{ANSI['green']}✓ All changes saved — you're up to date.{ANSI['reset']}")
            print(msg)
    else:
        # Neutral (no timeline yet etc)
        if HAS_RICH:
            console.print(Panel(escape(msg), title="Status", border_style="dim"))
        else:
            print(msg)

# ---------- log ----------
def print_log(versions: list[dict], limit: int = 20):
    if not versions:
        if HAS_RICH:
            console.print(Panel(
                "No versions yet.\n\n[bold]First save:[/] Export from Resolve (File → Export Timeline → OpenTimelineIO → timeline.otio), then run:\n[cyan]get-syncd save -m \"First cut\"[/]",
                title="[yellow]No history yet[/]",
                border_style="yellow",
            ))
        else:
            print("No versions yet. Export from Resolve then run: get-syncd save -m \"First cut\"")
        return

    if HAS_RICH:
        table = Table(title=f"Version history — {len(versions)} saved", box=box.ROUNDED, show_lines=False)
        table.add_column("#", style="dim", width=3, justify="right")
        table.add_column("Version", style="cyan", no_wrap=True)
        table.add_column("Date", style="dim", no_wrap=True)
        table.add_column("What changed", style="white")
        # Show newest first, number 1 = newest, to make `get-syncd diff 2 1` intuitive
        for i, v in enumerate(versions):
            num = str(i + 1)  # 1 = newest
            is_latest = i == 0
            ver = f"{v['short']}" + (" ← latest" if is_latest else "")
            table.add_row(num, ver, v["date"], escape(v["message"]))
        console.print(table)
        console.print("[dim]Tip: [cyan]get-syncd diff 2 1[/] shows what changed between version 2 and 1. Or use git names like [cyan]HEAD~1 HEAD[/].[/]")
        console.print("[dim]     [cyan]get-syncd view[/] opens a visual timeline in your browser.[/]")
    else:
        print(f"\nVersion history — {len(versions)} saved")
        print(f"{'#':>3}  {'Version':<14} {'Date':<12} What changed")
        print("-" * 70)
        for i, v in enumerate(versions):
            mark = " ← latest" if i == 0 else ""
            print(f"{i+1:>3}  {v['short']:<14} {v['date']:<12} {v['message']}{mark}")
        print("\nTip: get-syncd diff 2 1   or   get-syncd view")

def print_log_verbose(versions: list[dict]):
    # fallback for --verbose, just add hash/author
    if HAS_RICH:
        table = Table(box=box.SIMPLE)
        table.add_column("Version", style="cyan")
        table.add_column("Author", style="dim")
        table.add_column("Date", style="dim")
        table.add_column("Message")
        for v in versions:
            table.add_row(v["short"], v["author"], v["date"], escape(v["message"]))
        console.print(table)
    else:
        for v in versions:
            print(f"{v['short']}  {v['date']}  by {v['author']}  {v['message']}")

# ---------- diff ----------
def _badge(text: str, color: str) -> str:
    if HAS_RICH:
        return f"[black on {color}] {text} [/]"
    # fallback
    return f"[{text}]"

def print_diff_summary(summary: dict, old_name: str, new_name: str, warnings: list[str] = None):
    s = summary
    parts = []
    if s.get("added"): parts.append(f"{s['added']} added")
    if s.get("removed"): parts.append(f"{s['removed']} removed")
    if s.get("trimmed"): parts.append(f"{s['trimmed']} trimmed")
    if s.get("reordered"): parts.append(f"{s['reordered']} moved")
    if not parts: parts = ["no changes"]
    delta = s.get("runtime_delta_s", 0)
    delta_str = f"{delta:+g}s"
    delta_color = "green" if delta > 0 else "red" if delta < 0 else "dim"

    if HAS_RICH:
        # header panels
        cols = Columns([
            Panel(f"[bold]{s.get('old_duration_s',0)}s → {s.get('new_duration_s',0)}s[/]\n[dim]runtime[/]", border_style="dim", padding=(0,1)),
            Panel(f"[{delta_color}]{delta_str}[/]", title="change", border_style=delta_color, padding=(0,1)),
            Panel(", ".join(parts) or "no changes", title="edits", border_style="cyan", padding=(0,1)),
        ], equal=True, expand=True)
        console.print(Panel(cols, title=f"[bold]{escape(old_name)} → {escape(new_name)}[/]", border_style="blue", box=box.ROUNDED))
        if warnings:
            for w in warnings:
                console.print(f"[yellow]⚠ {escape(w)}[/]")
    else:
        print(f"\n{ANSI['bold']}{old_name} → {new_name}{ANSI['reset']}")
        print(f"Summary: {', '.join(parts)}")
        print(f"Runtime: {s.get('old_duration_s',0)}s → {s.get('new_duration_s',0)}s (Δ {delta_str})")
        if warnings:
            for w in warnings:
                print(f"⚠ {w}")

def print_diff_changes(changes: list[dict], summary: dict = None):
    if not changes:
        if HAS_RICH:
            console.print(Panel("[dim]No clip-level changes — timelines match on the compared track.[/]", border_style="green"))
        else:
            print("(no clip-level changes)")
        return
    if HAS_RICH:
        table = Table(box=box.ROUNDED, show_lines=False)
        table.add_column("", width=3, justify="center")
        table.add_column("Clip", style="white")
        table.add_column("What happened", style="dim")
        for ch in changes:
            t = ch["type"]
            icon = {"added": "[green]+[/]", "removed": "[red]−[/]", "trimmed": "[yellow]~[/]", "reordered": "[blue]↔[/]", "renamed": "[magenta]✎[/]", "gap_changed": "[dim]~[/]", "transition_changed": "[dim]~[/]"}.get(t, "?")
            name = escape(ch.get("clip_name") or "(unnamed)")
            url = escape(ch.get("url") or ch.get("kind",""))
            clip = f"[bold]{name}[/]\n[dim]{url}[/]" if url else f"[bold]{name}[/]"
            d = ch.get("details",{})
            if t == "added":
                desc = f"added ({d.get('duration_s','?')}s) at [{ch.get('index_new')}]"
            elif t == "removed":
                desc = f"removed from [{ch.get('index_old')}]"
            elif t == "trimmed":
                delta = d.get("delta_s",0)
                sign = "+" if delta>=0 else ""
                desc = f"trimmed {sign}{delta}s  ({d.get('old_duration_s')}s → {d.get('new_duration_s')}s)  [{ch.get('index_old')}→{ch.get('index_new')}]"
                if d.get("also_reordered"):
                    desc += " + moved"
            elif t == "reordered":
                desc = f"moved [{ch.get('index_old')} → {ch.get('index_new')}]"
            elif t == "renamed":
                desc = f"renamed {escape(str(d.get('renamed_from')))} → {escape(str(d.get('renamed_to')))}"
            else:
                desc = t
            table.add_row(icon, clip, desc)
        console.print(table)
        # footer hint
        console.print("[dim]Changelog: [white]" + escape(_changelog_from_summary(summary)) + "[/]  •  [cyan]get-syncd view[/] for a visual timeline[/]" if summary else "")
    else:
        for ch in changes:
            t = ch["type"]
            icon = {"added": "+", "removed": "-", "trimmed": "~", "reordered": "↔"}.get(t, "?")
            print(f"  {icon} [{ch.get('index_old')}→{ch.get('index_new')}] {ch.get('clip_name')} — {t} {ch.get('details')}")

def _changelog_from_summary(summary: dict) -> str:
    if not summary: return ""
    parts = []
    if summary.get("added"): parts.append(f"{summary['added']} added")
    if summary.get("removed"): parts.append(f"{summary['removed']} removed")
    if summary.get("trimmed"): parts.append(f"{summary['trimmed']} trimmed")
    if summary.get("reordered"): parts.append(f"{summary['reordered']} moved")
    if not parts: return f"No changes (runtime {summary.get('new_duration_s',0)}s)"
    return f"{', '.join(parts)}, runtime {summary.get('runtime_delta_s',0):+g}s"

# ---------- save ----------
def print_save_success(commit: str, message: str, repo: Path, is_first: bool = False):
    if HAS_RICH:
        title = "[green]✓ Saved![/]" if not is_first else "[green]✓ First version saved![/]"
        console.print(Panel(
            f"[bold]{escape(message)}[/]\n[dim]version {commit} • {repo}[/]\n\n[dim]Next: keep editing, then File → Export → OpenTimelineIO → timeline.otio → [cyan]get-syncd save[/][/]",
            title=title,
            border_style="green",
            box=box.ROUNDED,
        ))
    else:
        print(f"\nSaved version {commit}: {message}")

def print_save_no_changes():
    if HAS_RICH:
        console.print(Panel(
            "Timeline is identical to your last saved version.\n[dim]Make an edit in Resolve and re-export timeline.otio before saving.[/]",
            title="[yellow]Nothing to save[/]",
            border_style="yellow",
        ))
    else:
        print("No changes to save — timeline is identical to last version.")

# ---------- init ----------
def print_init_success(repo: Path, remote: Optional[str]):
    if HAS_RICH:
        extra = f"\n[dim]Remote:[/] {escape(remote)}" if remote else "\n[dim]No remote yet — add later with:[/] [cyan]git remote add origin <url>[/]\n[dim]Tip:[/] create an empty repo on GitHub, then [cyan]get-syncd push[/]"
        console.print(Panel(
            f"[green]✓ Ready![/] Get Syncd project at\n[bold]{escape(str(repo))}[/]{extra}\n\n[bold]Next:[/] Export from Resolve (File → Export Timeline → OpenTimelineIO → timeline.otio) then [cyan]get-syncd save -m \"First cut\"[/]",
            title="[green]Initialized[/]",
            border_style="green",
        ))
    else:
        print(f"Initialized Get Syncd repo at {repo}")

# ---------- dashboard ----------
def print_dashboard(repo: Path, status_result: dict, versions: list[dict]):
    print_banner()
    print_status(status_result, repo)
    # recent history preview
    if versions:
        if HAS_RICH:
            console.print(f"\n[bold]Recent versions[/] [dim]({len(versions)} total, newest first)[/]")
        else:
            print(f"\nRecent versions ({len(versions)} total):")
        print_log(versions[:3])
    hr()
    if HAS_RICH:
        console.print("[bold]Quick commands[/]")
        table = Table(box=box.SIMPLE, show_header=False, padding=(0,1))
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Does", style="dim")
        table.add_row("get-syncd save", "save a new version (you can add -m \"note\")")
        table.add_row("get-syncd status", "check if you have unsaved changes")
        table.add_row("get-syncd log", "see all saved versions")
        table.add_row("get-syncd diff 2 1", "see what changed between versions")
        table.add_row("get-syncd restore 2 --apply", "change to that version (overwrites timeline.otio)")
        table.add_row("get-syncd checkout 2", "same as restore --apply (one-click)")
        table.add_row("get-syncd watch", "auto-detect Resolve exports")
        table.add_row("get-syncd view", "open visual timeline in browser")
        console.print(table)
    else:
        print("Quick commands:")
        print("  get-syncd save                         — save a new version")
        print("  get-syncd status                       — check for unsaved changes")
        print("  get-syncd log                          — see all versions")
        print("  get-syncd diff 2 1                     — see what changed")
        print("  get-syncd restore 2 --apply            — change to that version")
        print("  get-syncd watch                        — watch for exports")
        print("  get-syncd view                         — visual timeline")

# ---------- interactive prompt ----------
def prompt_save_message(auto_msg: str, is_first: bool = False) -> str:
    """Ask user for a save note. Shows auto suggestion, allows Enter to accept."""
    hint = auto_msg if auto_msg else ("Initial version" if is_first else "Save version")
    if not sys.stdin.isatty():
        return hint
    try:
        if HAS_RICH:
            console.print(f"[dim]Auto note:[/] [white]{escape(hint)}[/]  [dim](press Enter to keep, or type your own)[/]")
            console.print("[bold]What changed?[/] [dim](e.g. \"Trimmed intro, added b-roll\")[/]")
        else:
            print(f"Auto note: {hint}  (Enter to keep, or type your own)")
            print("What changed? ", end="")
        val = input("> " if not HAS_RICH else "").strip()
        return val if val else hint
    except (EOFError, KeyboardInterrupt):
        print()
        return hint

# ---------- generic error/help ----------
def print_error(msg: str, hint: str = ""):
    if HAS_RICH:
        console.print(Panel(escape(msg), title="[red]Error[/]", border_style="red"))
        if hint:
            console.print(f"[dim]{escape(hint)}[/]")
    else:
        print(f"Error: {msg}", file=sys.stderr)
        if hint:
            print(hint, file=sys.stderr)

def print_hint(msg: str):
    if HAS_RICH:
        console.print(f"[dim]{escape(msg)}[/]")
    else:
        print(msg)

# ---------- restore --apply ----------
def confirm_apply(rev: str, dest: Path) -> bool:
    if not sys.stdin.isatty():
        return True
    prompt = f"Overwrite {dest} with version {rev}? This will become your current timeline. [y/N]: "
    try:
        if HAS_RICH:
            console.print(f"[yellow]⚠ This will overwrite [bold]{escape(str(dest))}[/] with version [cyan]{escape(str(rev))}[/][/]")
            console.print("[dim]Your current timeline.otio will be backed up to .get-syncd/backups/[/]")
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def confirm_delete(rev: str, msg: str) -> bool:
    if not sys.stdin.isatty():
        return True
    prompt = f"Delete version {rev} ({msg})? This rewrites history and cannot be undone without a backup. [y/N]: "
    try:
        if HAS_RICH:
            console.print(f"[red]⚠ Delete version [bold]{escape(str(rev))}[/] — [dim]{escape(msg)}[/]?[/]")
            console.print("[dim]This will permanently remove that version from history (git rebase/reset). Later versions will be rewritten.[/]")
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False

def print_restore_apply_success(rev: str, dest: Path, repo: Path):
    if HAS_RICH:
        console.print(Panel(
            f"[green bold]✓ Now using version {escape(str(rev))}[/]\n[bold]{escape(str(dest.resolve()))}[/] now contains that version.\n\n[bold]Next step:[/] In DaVinci Resolve, [cyan]File → Import Timeline → OpenTimelineIO[/] → pick [bold]timeline.otio[/] (or just re-import). Resolve will show the restored timeline.\n[dim]Tip: this overwrote timeline.otio directly — you can [cyan]get-syncd save -m \"keep restored\"[/] to save it as a new checkpoint, or just keep editing.[/]",
            title="[green]Changed to this version![/]",
            border_style="green",
            box=box.ROUNDED,
        ))
    else:
        print(f"\n✓ Now using version {rev}")
        print(f"{dest} now contains that version.")
        print("Next: In Resolve, File → Import Timeline → OpenTimelineIO → timeline.otio")

def prompt_pick_version(versions: list[dict]) -> str:
    # show short table then ask
    print_log(versions[:10])
    try:
        if HAS_RICH:
            console.print("[bold]Pick a version number to restore[/] [dim](1=latest, Enter to cancel):[/]")
        else:
            print("Pick a version number (1=latest): ")
        val = input("> ").strip()
        if not val:
            return ""
        if val.isdigit() and 1 <= int(val) <= len(versions):
            return val
        # also allow hash prefix
        return val
    except (EOFError, KeyboardInterrupt):
        return ""

# ---------- watch ----------
def print_watch_start(repo: Path, interval: float, auto: bool):
    mode = "auto-save" if auto else "prompt to save"
    if HAS_RICH:
        console.print(Panel(
            f"[bold]Watching[/] [cyan]{escape(str(repo))}/timeline.otio[/]\n[dim]Poll every {interval}s — {mode}. Export from Resolve (File → Export Timeline → OpenTimelineIO → timeline.otio) and it will be detected.[/]\n[dim]Press Ctrl+C to stop.[/]",
            title="[cyan]Watcher started[/]",
            border_style="cyan",
        ))
    else:
        print(f"Watching {repo}/timeline.otio every {interval}s ({mode}) — Ctrl+C to stop")

def print_watch_change(d):
    # reuse diff printing
    print_diff_summary(d.summary, "HEAD", "current file", warnings=d.warnings)
    print_diff_changes([c.to_dict() for c in d.changes], summary=d.summary)

def prompt_watch_save() -> str:
    # returns "save" / "diff" / "skip"
    if not sys.stdin.isatty():
        return "skip"
    try:
        if HAS_RICH:
            console.print("[bold]Save this as a new version?[/] [dim][s]ave / [d]iff again / [Enter] skip:[/]")
        else:
            print("Save? [s]ave / [d]iff / skip (Enter): ", end="")
        val = input("> " if not HAS_RICH else "").strip().lower()
        if val in ("s", "save", "y", "yes"):
            return "save"
        if val in ("d", "diff"):
            return "diff"
        return "skip"
    except (EOFError, KeyboardInterrupt):
        return "skip"
