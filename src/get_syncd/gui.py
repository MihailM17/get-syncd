"""Get Syncd — Sidecar desktop app (runs alongside DaVinci Resolve).

One window, no terminal needed. Button "Export from Resolve" triggers the
Resolve API (if available) to write timeline.otio into your project folder,
then shows diff, lets you add a note, save, view history, diff any two saves,
and one-click "Change to this version" (restore --apply) so next Resolve import
shows that version.

Fallback: if Resolve API export isn't available in your version, shows manual
File → Export Timeline → OpenTimelineIO instructions and watches the folder
(`get-syncd watch` style).

Works with Resolve Free or Studio on macOS/Win/Linux. Tested on M2 Mac.
Tkinter is built-in Python — no extra pip deps. If Tk not available, prints help
and falls back to TUI.
"""

from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
import tempfile
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    HAS_TK = True
except Exception:
    HAS_TK = False

from . import git_store
from .otio_parse import parse_otio_file
from .diff import diff_timelines, changelog_line


def _try_resolve_export(out_path: Path) -> tuple[bool, str]:
    """Try to export current Resolve timeline to out_path via API. Returns (ok, msg)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Strategy 1: try DaVinciResolveScript module (external scripting)
    resolve = None
    try:
        # Resolve's module path on macOS
        for p in [
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
            os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
        ]:
            if p not in sys.path and Path(p).exists():
                sys.path.append(p)
        import DaVinciResolveScript as bmd  # type: ignore
        resolve = bmd.scriptapp("Resolve")
    except Exception as e:
        # try bmd global (inside Resolve console)
        try:
            resolve = globals().get("bmd") or __import__("builtins").__dict__.get("bmd")  # type: ignore
        except Exception:
            pass
        if resolve is None:
            return False, f"Resolve API not reachable ({e}). Is Resolve running? Enable Preferences → System → General → External scripting: Local."

    if resolve is None:
        return False, "Could not connect to DaVinci Resolve. Open Resolve and a project first."

    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
        if not project:
            return False, "No project open in Resolve. Open a project and timeline first."
        timeline = project.GetCurrentTimeline()
        if not timeline:
            return False, "No timeline open. Open a timeline in the Edit page."
        name = timeline.GetName() if hasattr(timeline, "GetName") else "timeline"
        # Try several export method names (vary by Resolve version)
        for meth in ["Export", "ExportTimeline", "ExportOTIO"]:
            if hasattr(timeline, meth):
                try:
                    ok = getattr(timeline, meth)(str(out_path), "otio")
                    if ok:
                        return True, f"Exported '{name}' via Timeline.{meth} → {out_path}"
                except Exception as ee:
                    continue
        if hasattr(project, "ExportTimeline"):
            try:
                ok = project.ExportTimeline(str(out_path), "otio")
                if ok:
                    return True, f"Exported '{name}' via Project.ExportTimeline → {out_path}"
            except Exception as ee:
                pass
        return False, "Automatic export not available in this Resolve version. Use File → Export Timeline → OpenTimelineIO → timeline.otio (manual fallback works fine)."
    except Exception as e:
        return False, f"Export error: {e}"


def _get_branches(repo: Path) -> list[str]:
    try:
        r = subprocess.run(["git", "branch", "--format=%(refname:short)"], cwd=str(repo), capture_output=True, text=True)
        if r.returncode == 0:
            return [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        pass
    return []

def _create_branch(repo: Path, name: str):
    subprocess.run(["git", "checkout", "-b", name], cwd=str(repo), check=True)

def _switch_branch(repo: Path, name: str):
    subprocess.run(["git", "checkout", name], cwd=str(repo), check=True)


class SidecarApp:
    def __init__(self, repo: Path):
        self.repo = repo
        self.root = tk.Tk()
        self.root.title(f"Get Syncd — {repo.name} — Sidecar")
        self.root.geometry("980x680")
        try:
            self.root.tk.call("tk", "scaling", 2.0)
        except Exception:
            pass
        self._build_ui()
        self._refresh_all()
        # watch thread
        self._watch_thread = None
        self._watching = False

    def _build_ui(self):
        # top bar: repo path + browse + status
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Project folder:").pack(side=tk.LEFT)
        self.repo_var = tk.StringVar(value=str(self.repo))
        ttk.Entry(top, textvariable=self.repo_var, width=46).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="Browse…", command=self._browse).pack(side=tk.LEFT, padx=4)
        ttk.Button(top, text="Init", command=self._init).pack(side=tk.LEFT, padx=4)
        self.status_lbl = ttk.Label(top, text="—", foreground="#666")
        self.status_lbl.pack(side=tk.RIGHT)

        # middle: left log + branches, right diff/preview
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        left = ttk.Frame(paned)
        paned.add(left, weight=1)
        # branches row
        br = ttk.Frame(left)
        br.pack(fill=tk.X, pady=(0,4))
        ttk.Label(br, text="Branch:").pack(side=tk.LEFT)
        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(br, textvariable=self.branch_var, width=16, state="readonly")
        self.branch_combo.pack(side=tk.LEFT, padx=6)
        ttk.Button(br, text="New branch", command=self._new_branch).pack(side=tk.LEFT, padx=4)
        ttk.Button(br, text="Switch", command=self._switch_branch).pack(side=tk.LEFT)
        # log tree
        cols = ("#", "Version", "Date", "Message")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=14)
        for c, w in zip(cols, (40, 90, 90, 420)):
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        # buttons under log
        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=6)
        ttk.Button(btns, text="Diff selected → latest", command=lambda: self._diff_selected()).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Change to this version", command=lambda: self._restore_selected()).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="View in browser", command=lambda: self._view_selected()).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Refresh", command=self._refresh_all).pack(side=tk.RIGHT, padx=2)

        right = ttk.Frame(paned)
        paned.add(right, weight=1)
        ttk.Label(right, text="What changed / Preview:").pack(anchor="w")
        self.diff_text = tk.Text(right, height=18, wrap=tk.WORD, font=("Menlo", 11))
        self.diff_text.pack(fill=tk.BOTH, expand=True, pady=4)
        # message entry
        msgf = ttk.Frame(right)
        msgf.pack(fill=tk.X, pady=6)
        ttk.Label(msgf, text="Note for next save:").pack(anchor="w")
        self.msg_var = tk.StringVar()
        ttk.Entry(msgf, textvariable=self.msg_var).pack(fill=tk.X, pady=2)
        # action row
        act = ttk.Frame(right)
        act.pack(fill=tk.X, pady=6)
        ttk.Button(act, text="① Export from Resolve", command=self._export).pack(side=tk.LEFT, padx=4)
        ttk.Button(act, text="② Save version", command=self._save).pack(side=tk.LEFT, padx=4)
        self.watch_btn = ttk.Button(act, text="Watch: OFF", command=self._toggle_watch)
        self.watch_btn.pack(side=tk.LEFT, padx=12)
        ttk.Button(act, text="Push to GitHub", command=self._push).pack(side=tk.RIGHT, padx=4)

        # bottom hint
        self.hint = ttk.Label(self.root, text="Tip: leave this window open beside Resolve. Click Export → Save. Pick any old version → Change to this version.", foreground="#888", wraplength=920, justify=tk.LEFT)
        self.hint.pack(fill=tk.X, padx=8, pady=(0,8))

    def _browse(self):
        d = filedialog.askdirectory(initialdir=str(self.repo))
        if d:
            self.repo = Path(d)
            self.repo_var.set(d)
            self._refresh_all()

    def _init(self):
        try:
            git_store.init_repo(self.repo)
            messagebox.showinfo("Initialized", f"Get Syncd project ready at\n{self.repo}")
            self._refresh_all()
        except Exception as e:
            messagebox.showerror("Init failed", str(e))

    def _refresh_all(self):
        self.repo = Path(self.repo_var.get()).expanduser().resolve()
        self.repo.mkdir(parents=True, exist_ok=True)
        # status
        try:
            res = git_store.status(self.repo)
            msg = res.get("message", "")
            has = res.get("has_changes")
            if has is True:
                self.status_lbl.config(text="● Unsaved changes", foreground="#d98300")
            elif has is False:
                self.status_lbl.config(text="✓ Up to date", foreground="#1a8a4a")
            else:
                self.status_lbl.config(text=msg[:60], foreground="#666")
            # also update diff preview for unsaved changes vs HEAD
            if has is True:
                try:
                    # quick changelog diff vs HEAD
                    with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                        tp = tmp.name
                    try:
                        git_store.restore_version(self.repo, "HEAD", tp)
                        old = parse_otio_file(tp)
                        new = parse_otio_file(self.repo / "timeline.otio")
                        d = diff_timelines(old, new)
                        self.diff_text.delete("1.0", tk.END)
                        self.diff_text.insert(tk.END, f"Unsaved changes vs last save:\n{changelog_line(d)}\n\n")
                        for ch in d.changes:
                            self.diff_text.insert(tk.END, f"  {ch.type} {ch.clip_name} {ch.details}\n")
                        if not self.msg_var.get():
                            self.msg_var.set(changelog_line(d))
                    finally:
                        try: Path(tp).unlink()
                        except: pass
                except Exception:
                    pass
        except Exception as e:
            self.status_lbl.config(text=str(e)[:80], foreground="#c00")
        # branches
        try:
            branches = _get_branches(self.repo)
            cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(self.repo), capture_output=True, text=True)
            cur_name = cur.stdout.strip() if cur.returncode == 0 else ""
            self.branch_combo["values"] = branches if branches else [cur_name or "main"]
            self.branch_var.set(cur_name or (branches[0] if branches else ""))
        except Exception:
            pass
        # log
        for i in self.tree.get_children():
            self.tree.delete(i)
        try:
            versions = git_store.log_versions(self.repo, limit=50)
            for i, v in enumerate(versions):
                tag = "latest" if i == 0 else ""
                self.tree.insert("", tk.END, values=(i+1, v["short"] + (" ← latest" if tag else ""), v["date"], v["message"]))
        except Exception as e:
            self.diff_text.delete("1.0", tk.END)
            self.diff_text.insert(tk.END, f"Error loading log: {e}\n")

    def _on_select(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        num = str(vals[0])
        try:
            versions = git_store.log_versions(self.repo, limit=50)
            idx = int(num)-1
            if 0 <= idx < len(versions):
                rev = versions[idx]["hash"]
                # show diff vs latest (or vs previous if latest selected)
                other = versions[0]["hash"] if idx != 0 else (versions[1]["hash"] if len(versions)>1 else rev)
                a = other if idx==0 else rev
                b = rev if idx==0 else versions[0]["hash"]
                # use git revs via temp
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as ta:
                    pa = ta.name
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tb:
                    pb = tb.name
                try:
                    git_store.restore_version(self.repo, a, pa)
                    git_store.restore_version(self.repo, b, pb)
                    old = parse_otio_file(pa); new = parse_otio_file(pb)
                    d = diff_timelines(old, new)
                    self.diff_text.delete("1.0", tk.END)
                    self.diff_text.insert(tk.END, f"Diff {num} vs latest:\n{changelog_line(d)}\n\n")
                    for ch in d.changes:
                        self.diff_text.insert(tk.END, f"{ch.type:12} {ch.clip_name}  {ch.details}\n")
                finally:
                    for p in (pa,pb):
                        try: Path(p).unlink()
                        except: pass
        except Exception as e:
            self.diff_text.delete("1.0", tk.END)
            self.diff_text.insert(tk.END, f"Diff error: {e}\n")

    def _export(self):
        out = self.repo / "timeline.otio"
        # prefer env override
        env_out = os.environ.get("GET_SYNCD_OUT")
        if env_out:
            out = Path(env_out).expanduser()
        ok, msg = _try_resolve_export(out)
        if ok:
            messagebox.showinfo("Exported", msg)
            self._refresh_all()
        else:
            # show fallback dialog
            manual = (
                f"{msg}\n\nManual fallback (always works):\n"
                f"1) In Resolve: File → Export Timeline → OpenTimelineIO\n"
                f"2) Save as: {out}\n"
                f"3) Come back here and click 'Save version'."
            )
            messagebox.showwarning("Export — manual step needed", manual)
            # also show in diff pane
            self.diff_text.delete("1.0", tk.END)
            self.diff_text.insert(tk.END, manual + "\n")

    def _save(self):
        msg = self.msg_var.get().strip()
        if not msg:
            # auto
            try:
                # try auto changelog diff vs HEAD
                import tempfile
                src = self.repo / "timeline.otio"
                if not src.exists():
                    messagebox.showerror("No timeline", f"No {src} yet. Click Export first.")
                    return
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                    tp = tmp.name
                try:
                    git_store.restore_version(self.repo, "HEAD", tp)
                    old = parse_otio_file(tp); new = parse_otio_file(src)
                    d = diff_timelines(old, new)
                    msg = changelog_line(d)
                except Exception:
                    msg = "Save version"
                finally:
                    try: Path(tp).unlink()
                    except: pass
            except Exception:
                msg = "Save version"
        try:
            src = self.repo / "timeline.otio"
            if not src.exists():
                # try any otio in repo
                cands = list(self.repo.glob("*.otio"))
                if cands:
                    src = cands[0]
                else:
                    messagebox.showerror("No file", "Export from Resolve first (timeline.otio not found).")
                    return
            h = git_store.save_version(self.repo, src, msg)
            messagebox.showinfo("Saved", f"Version {h[:8]}:\n{msg}")
            self.msg_var.set("")
            self._refresh_all()
        except ValueError as e:
            messagebox.showinfo("Nothing to save", str(e))
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def _diff_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Pick one", "Select a version in the list first.")
            return
        vals = self.tree.item(sel[0], "values")
        num = str(vals[0])
        # diff num vs latest (1)
        try:
            # reuse _on_select diff already shown; also pop viewer?
            self._on_select()
        except Exception as e:
            messagebox.showerror("Diff failed", str(e))

    def _restore_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Pick one", "Select a version to restore first.")
            return
        vals = self.tree.item(sel[0], "values")
        num = str(vals[0])
        if not messagebox.askyesno("Change to this version?", f"Overwrite timeline.otio with version {num} ({vals[1]})?\n\nThis becomes your current timeline. Next Resolve import will show it.\nCurrent timeline.otio will be backed up to .get-syncd/backups/."):
            return
        try:
            versions = git_store.log_versions(self.repo, limit=50)
            idx = int(num)-1
            rev = versions[idx]["hash"] if 0 <= idx < len(versions) else num
            # backup
            out = self.repo / "timeline.otio"
            if out.exists():
                bdir = self.repo / ".get-syncd" / "backups"
                bdir.mkdir(parents=True, exist_ok=True)
                import shutil, datetime
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(str(out), str(bdir / f"timeline-{ts}.otio"))
            git_store.restore_version(self.repo, rev, out)
            messagebox.showinfo("Changed", f"Now using version {num} ({vals[1]}).\n\nIn Resolve: File → Import Timeline → OpenTimelineIO → timeline.otio\n(or re-import).")
            self._refresh_all()
        except Exception as e:
            messagebox.showerror("Restore failed", str(e))

    def _view_selected(self):
        sel = self.tree.selection()
        versions = git_store.log_versions(self.repo, limit=50)
        if len(versions) < 2:
            messagebox.showinfo("Need 2 versions", "Save at least 2 versions to view a diff.")
            return
        if sel:
            vals = self.tree.item(sel[0], "values")
            num = str(vals[0])
            idx = int(num)-1
            a = versions[idx]["hash"]
            b = versions[0]["hash"]
        else:
            a = versions[1]["hash"]; b = versions[0]["hash"]
        try:
            from .viewer.app import run_viewer
            import threading
            threading.Thread(target=lambda: run_viewer(self.repo, a, b, open_browser=True), daemon=True).start()
        except Exception as e:
            messagebox.showerror("Viewer failed", str(e))

    def _new_branch(self):
        name = simpledialog.askstring("New branch", "Branch name (e.g. experiment):")
        if not name: return
        try:
            _create_branch(self.repo, name.strip())
            self._refresh_all()
            messagebox.showinfo("Branch", f"Created and switched to '{name}'")
        except Exception as e:
            messagebox.showerror("Branch failed", str(e))

    def _switch_branch(self):
        name = self.branch_var.get().strip()
        if not name: return
        try:
            _switch_branch(self.repo, name)
            self._refresh_all()
            messagebox.showinfo("Switched", f"Now on '{name}'")
        except Exception as e:
            messagebox.showerror("Switch failed", str(e))

    def _push(self):
        try:
            out = git_store.push(self.repo)
            messagebox.showinfo("Pushed", out or "Pushed to GitHub.")
        except Exception as e:
            messagebox.showerror("Push failed", str(e) + "\n\nTip: git remote -v ; gh auth login")

    def _toggle_watch(self):
        if self._watching:
            self._watching = False
            self.watch_btn.config(text="Watch: OFF")
            return
        self._watching = True
        self.watch_btn.config(text="Watch: ON")
        def loop():
            last = ""
            watch_file = self.repo / "timeline.otio"
            if watch_file.exists():
                try: last = git_store.file_hash(watch_file)
                except: last = str(watch_file.stat().st_mtime)
            while self._watching:
                time.sleep(2.0)
                if not watch_file.exists(): continue
                try:
                    cur = git_store.file_hash(watch_file)
                except: continue
                if cur != last:
                    last = cur
                    # schedule UI update
                    try:
                        self.root.after(0, lambda: self._on_watch_change())
                    except: pass
        threading.Thread(target=loop, daemon=True).start()

    def _on_watch_change(self):
        self._refresh_all()
        # prompt
        if messagebox.askyesno("Change detected", "timeline.otio changed (Resolve export?). Save as new version?"):
            self._save()

    def run(self):
        self.root.mainloop()


def run_gui(repo: Path):
    if not HAS_TK:
        print("Tkinter not available (python-tk missing). Fallback:", file=sys.stderr)
        print("  get-syncd watch  # in one terminal", file=sys.stderr)
        print("  get-syncd log / diff / restore --apply  # in another", file=sys.stderr)
        print("\nInstall Tk on macOS: brew install python-tk  (or use python.org Python which includes Tk)", file=sys.stderr)
        sys.exit(1)
    app = SidecarApp(repo)
    app.run()
