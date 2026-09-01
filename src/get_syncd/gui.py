"""Get Syncd — Sidecar desktop app (v2 friendly).

One place for everything: all timelines live in ~/GetSyncd/timeline.otio
No hunting for files — the app *is* the place.
- Big friendly buttons: Export, Save, Refresh
- Live preview image per version (timeline bar)
- Git tree visualiser + branch switcher
- Auto-detect + manual Refresh (fixes "export didn't appear")

Tkinter (built-in). Pillow optional for nicer previews (fallback to canvas).
"""

from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
import tempfile
import hashlib
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    HAS_TK = True
except Exception:
    HAS_TK = False

from . import git_store
from .otio_parse import parse_otio_file
from .diff import diff_timelines, changelog_line
from .preview import generate_preview, _preview_path, ensure_previews, HAS_PIL

# PIL ImageTk needed for display (separate from preview generation)
try:
    from PIL import Image, ImageTk
    HAS_PIL_TK = HAS_PIL
except Exception:
    HAS_PIL_TK = False
    Image = ImageTk = None

DEFAULT_WORKSPACE = Path.home() / "GetSyncd"
PREVIEW_DIRNAME = ".get-syncd/previews"

# ---------- Resolve export ----------
def _try_resolve_export(out_path: Path) -> tuple[bool, str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resolve = None
    try:
        for p in [
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
            str(Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"),
        ]:
            if p not in sys.path and Path(p).exists():
                sys.path.append(p)
        import DaVinciResolveScript as bmd  # type: ignore
        resolve = bmd.scriptapp("Resolve")
    except Exception as e:
        try:
            resolve = globals().get("bmd")
        except Exception:
            pass
        if resolve is None:
            return False, f"Resolve API not reachable ({e}). Is Resolve running? Set Preferences → System → General → External scripting: Local."

    if resolve is None:
        return False, "Could not connect to Resolve. Open Resolve and a project first."
    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
        if not project:
            return False, "No project open in Resolve."
        timeline = project.GetCurrentTimeline()
        if not timeline:
            return False, "No timeline open in Edit page."
        name = timeline.GetName() if hasattr(timeline, "GetName") else "timeline"
        # Preferred: timeline.Export with OTIO constants (correct API)
        try:
            exp_otio = getattr(resolve, "EXPORT_OTIO", None)
            exp_none = getattr(resolve, "EXPORT_NONE", None)
            if exp_otio is not None and hasattr(timeline, "Export"):
                ok = timeline.Export(str(out_path), exp_otio, exp_none if exp_none is not None else 0)
                if ok:
                    return True, f"Exported '{name}' → {out_path} via timeline.Export"
        except Exception:
            pass
        for meth in ["Export", "ExportTimeline", "ExportOTIO"]:
            if hasattr(timeline, meth):
                try:
                    ok = getattr(timeline, meth)(str(out_path), "otio")
                    if ok:
                        return True, f"Exported '{name}' → {out_path} via timeline.{meth}"
                except Exception:
                    try:
                        ok = getattr(timeline, meth)(str(out_path))
                        if ok:
                            return True, f"Exported '{name}' → {out_path} via timeline.{meth}"
                    except Exception:
                        continue
        if hasattr(project, "ExportTimeline"):
            try:
                ok = project.ExportTimeline(str(out_path), "otio")
                if ok:
                    return True, f"Exported '{name}' → {out_path} via project.ExportTimeline"
            except Exception:
                pass
        return False, "Auto export not available in this Resolve version. Use File → Export Timeline → OpenTimelineIO → timeline.otio (manual fallback works)."
    except Exception as e:
        return False, f"Export error: {e}"

# ---------- git tree ----------
def get_git_graph(repo: Path) -> str:
    try:
        # pretty graph with branches
        r = subprocess.run(
            ["git", "log", "--graph", "--all", "--oneline", "--decorate", "-n", "30", "--color=never"],
            cwd=str(repo), capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        # fallback to simple log
        r2 = subprocess.run(["git", "log", "--oneline", "-n", "20"], cwd=str(repo), capture_output=True, text=True)
        return r2.stdout.strip() or "(no history yet)"
    except Exception as e:
        return f"(git tree unavailable: {e})"

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

# ---------- App ----------
class SidecarApp:
    def __init__(self, repo: Path):
        # Enforce single-place workspace: default to ~/GetSyncd if caller passed app repo
        if repo.resolve() == Path(__file__).resolve().parents[2]:
            repo = DEFAULT_WORKSPACE
        if str(repo).endswith("get-syncd") and repo.name == "get-syncd":
            # user launched from app folder — redirect to workspace
            repo = DEFAULT_WORKSPACE
        self.repo = repo
        self.repo.mkdir(parents=True, exist_ok=True)
        # auto-init if needed
        if not git_store.is_git_repo(self.repo):
            git_store.init_repo(self.repo)

        self.root = tk.Tk()
        self.root.title(f"Get Syncd — Sidecar  •  {self.repo.name}")
        self.root.geometry("1100x740")
        self.root.minsize(980, 640)
        try:
            self.root.tk.call("tk", "scaling", 1.8)
        except Exception:
            pass
        style = ttk.Style()
        # keep native macOS theme (aqua) — clam makes tree white-on-white on some Macs
        # only tweak Treeview row colors explicitly if needed
        try:
            style.configure("Treeview", background="white", foreground="black", fieldbackground="white")
            style.configure("Treeview.Heading", background="#e5e5e5", foreground="black")
        except Exception:
            pass

        self._watching = False
        self._preview_images = {}  # keep refs
        self._build_ui()
        self._refresh_all()
        # ensure previews in background
        threading.Thread(target=lambda: ensure_previews(self.repo), daemon=True).start()
        # start watch by default (friendly)
        self.root.after(800, lambda: self._toggle_watch())

    def _build_ui(self):
        # Header: title + workspace + status + big Refresh
        header = ttk.Frame(self.root, padding=(12,10,12,6))
        header.pack(fill=tk.X)
        # left title
        title = ttk.Frame(header)
        title.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title, text="Get Syncd", font=("SF Pro Display", 18, "bold")).pack(anchor="w")
        ttk.Label(title, text=f"All timelines live in  {self.repo}  — you don't need to hunt for files. Just Export → Save here.", foreground="#666", font=("SF Pro Text", 10)).pack(anchor="w", pady=(2,0))

        # right: status + refresh
        right = ttk.Frame(header)
        right.pack(side=tk.RIGHT)
        self.status_var = tk.StringVar(value="—")
        self.status_lbl = ttk.Label(right, textvariable=self.status_var, font=("SF Pro Text", 11, "bold"), foreground="#666")
        self.status_lbl.pack(anchor="e")
        self.refresh_btn = ttk.Button(right, text="↻  Refresh", command=self._refresh_all)
        self.refresh_btn.pack(anchor="e", pady=(4,0))

        # Big friendly action bar
        bar = ttk.Frame(self.root, padding=(12,6,12,8))
        bar.pack(fill=tk.X)
        # Use tk.Button for colored big buttons (ttk hard to color)
        self.export_btn = tk.Button(bar, text="①  Export from Resolve", command=self._export, bg="#0a84ff", fg="white", activebackground="#0060df", font=("SF Pro Text", 12, "bold"), padx=18, pady=10, bd=0, relief="flat", cursor="hand2")
        self.export_btn.pack(side=tk.LEFT, padx=(0,8))
        self.save_btn = tk.Button(bar, text="②  Save version", command=self._save, bg="#30d158", fg="white", activebackground="#28a745", font=("SF Pro Text", 12, "bold"), padx=18, pady=10, bd=0, relief="flat", cursor="hand2")
        self.save_btn.pack(side=tk.LEFT, padx=8)

        # note field
        note_fr = ttk.Frame(bar)
        note_fr.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12)
        ttk.Label(note_fr, text="Note for this save:").pack(anchor="w")
        self.msg_var = tk.StringVar()
        self.msg_entry = ttk.Entry(note_fr, textvariable=self.msg_var, font=("SF Pro Text", 11))
        self.msg_entry.pack(fill=tk.X, pady=(2,0))
        self.msg_entry.bind("<Return>", lambda e: self._save())

        # watch toggle
        self.watch_btn = tk.Button(bar, text="Watch: ON", command=self._toggle_watch, bg="#5856d6", fg="white", font=("SF Pro Text", 10, "bold"), padx=12, pady=8, bd=0, relief="flat", cursor="hand2")
        self.watch_btn.pack(side=tk.LEFT, padx=8)
        # branch switcher compact
        bf = ttk.Frame(bar)
        bf.pack(side=tk.RIGHT)
        ttk.Label(bf, text="Branch:").pack(side=tk.LEFT)
        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(bf, textvariable=self.branch_var, width=14, state="readonly", font=("SF Pro Text", 10))
        self.branch_combo.pack(side=tk.LEFT, padx=6)
        ttk.Button(bf, text="New", command=self._new_branch, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Button(bf, text="Switch", command=self._switch_branch, width=7).pack(side=tk.LEFT)

        # Main paned: left history + tree, center preview/diff
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        # Left: history list + git tree
        left = ttk.Frame(paned)
        paned.add(left, weight=2)
        # history label
        ttk.Label(left, text="History — click any version to preview", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0,4))

        # Tree with preview thumb column — "#" is version number (1=latest, not file name)
        cols = ("#", "Thumb", "ID", "Note", "Date")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=14)
        widths = {"#": 36, "Thumb": 56, "ID": 96, "Note": 320, "Date": 86}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths[c], anchor="w")
        # scrollbar
        scr = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scr.set)
        tree_fr = ttk.Frame(left)
        tree_fr.pack(fill=tk.BOTH, expand=True)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, in_=tree_fr)
        scr.pack(side=tk.RIGHT, fill=tk.Y, in_=tree_fr)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())

        # action row under tree
        tbtn = ttk.Frame(left)
        tbtn.pack(fill=tk.X, pady=6)
        tk.Button(tbtn, text="↔ Diff vs latest", command=self._diff_selected, bg="#f2f2f7", font=("SF Pro Text", 10), padx=10, pady=6, bd=0, relief="flat", cursor="hand2").pack(side=tk.LEFT, padx=2)
        self.change_btn = tk.Button(tbtn, text="↩ Change to this version", command=self._restore_selected, bg="#ff9f0a", fg="white", font=("SF Pro Text", 10, "bold"), padx=12, pady=6, bd=0, relief="flat", cursor="hand2")
        self.change_btn.pack(side=tk.LEFT, padx=6)
        tk.Button(tbtn, text="View", command=self._view_selected, bg="#f2f2f7", font=("SF Pro Text", 10), padx=10, pady=6, bd=0, relief="flat").pack(side=tk.LEFT, padx=2)
        tk.Button(tbtn, text="Push", command=self._push, bg="#f2f2f7", font=("SF Pro Text", 10), padx=10, pady=6, bd=0, relief="flat").pack(side=tk.RIGHT)

        # git tree visualiser (collapsible)
        tree_box = ttk.LabelFrame(left, text="Git tree — branches & history", padding=6)
        tree_box.pack(fill=tk.BOTH, expand=False, pady=(6,0))
        self.git_text = tk.Text(tree_box, height=7, font=("Menlo", 10), wrap=tk.NONE, bg="#1c1c1e", fg="#00ff7f", bd=0, padx=6, pady=4, insertbackground="white")
        self.git_text.pack(fill=tk.BOTH, expand=True)
        # horizontal scroll for graph
        gs = ttk.Scrollbar(tree_box, orient=tk.HORIZONTAL, command=self.git_text.xview)
        self.git_text.configure(xscrollcommand=gs.set)
        gs.pack(fill=tk.X)

        # Right: preview + diff
        right = ttk.Frame(paned)
        paned.add(right, weight=3)
        ttk.Label(right, text="Preview + What changed", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0,4))

        # Preview image area — dark card, white text
        self.preview_lbl = tk.Label(right, text="Preview will appear here\n(click a version on the left)", bg="#1c1c1e", fg="white", width=60, height=8, anchor="center", relief="flat", font=("SF Pro Text", 11))
        self.preview_lbl.pack(fill=tk.X, pady=(0,6))

        # Diff text — white bg, black text (fix white-on-white)
        self.diff_text = tk.Text(right, height=14, wrap=tk.WORD, font=("Menlo", 11), bg="white", fg="black", bd=1, relief="solid", padx=8, pady=6, insertbackground="black")
        self.diff_text.pack(fill=tk.BOTH, expand=True)
        self.diff_text.configure(state="disabled")

        # hint bar
        self.hint = ttk.Label(self.root, text="Keep this window beside Resolve. Export → type a note → Save. Pick any old version → Change to this version. Use Refresh if you exported manually to ~/GetSyncd/timeline.otio", foreground="#666", wraplength=1060, justify=tk.LEFT, font=("SF Pro Text", 10))
        self.hint.pack(fill=tk.X, padx=12, pady=(4,10))

    # ---------- refresh (fixes "didn't detect") ----------
    def _refresh_all(self):
        # Re-resolve repo (may have been moved) and ensure workspace
        try:
            self.repo.mkdir(parents=True, exist_ok=True)
            if not git_store.is_git_repo(self.repo):
                git_store.init_repo(self.repo)
        except Exception:
            pass

        # status
        try:
            res = git_store.status(self.repo)
            msg = res.get("message", "")
            has = res.get("has_changes")
            if has is True:
                self.status_var.set("● Unsaved changes — click Save")
                self.status_lbl.configure(foreground="#d98300")
                self.save_btn.configure(bg="#ff3b30")
            elif has is False:
                self.status_var.set("✓ Up to date")
                self.status_lbl.configure(foreground="#30d158")
                self.save_btn.configure(bg="#30d158")
            else:
                self.status_var.set(msg[:70])
                self.status_lbl.configure(foreground="#666")

            # update diff preview for unsaved changes
            if has is True:
                try:
                    with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                        tp = tmp.name
                    try:
                        git_store.restore_version(self.repo, "HEAD", tp)
                        old = parse_otio_file(tp)
                        new = parse_otio_file(self.repo / "timeline.otio")
                        d = diff_timelines(old, new)
                        self._set_diff_text(f"Unsaved vs last save:\n{changelog_line(d)}\n\n" + "\n".join(f"  {ch.type:12} {ch.clip_name}" for ch in d.changes[:12]))
                        if not self.msg_var.get():
                            self.msg_var.set(changelog_line(d))
                    finally:
                        try: Path(tp).unlink()
                        except: pass
                except Exception:
                    pass
            else:
                # show hint when up to date
                self._set_diff_text("No unsaved changes. Edit in Resolve, then Export → Save.")
        except Exception as e:
            self.status_var.set(str(e)[:80])
            self.status_lbl.configure(foreground="#c00")

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
        self._preview_images.clear()
        try:
            versions = git_store.log_versions(self.repo, limit=50)
            if not versions:
                self._set_diff_text("No saved versions yet.\n\n1) In Resolve: File → Export Timeline → OpenTimelineIO → save as ~/GetSyncd/timeline.otio (overwrite)\n2) Click Refresh if you just exported\n3) Type a note and click Save version\n→ It will appear here as a clickable row (#1 = newest).")
                # also show in tree as placeholder
                self.tree.insert("", tk.END, values=("", "—", "—", "No saved versions yet — Save one above", ""))
            else:
                for i, v in enumerate(versions):
                    # ensure preview exists
                    p = _preview_path(self.repo, v["hash"])
                    if not p.exists() or p.stat().st_size < 100:
                        try:
                            with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                                tp = Path(tmp.name)
                            git_store.restore_version(self.repo, v["hash"], tp)
                            generate_preview(self.repo, v["hash"], tp)
                            tp.unlink(missing_ok=True)
                        except Exception:
                            pass
                    # thumb: show file existence indicator
                    thumb = "▬▬" if p.exists() and p.stat().st_size > 100 else "…"
                    tag = "latest" if i == 0 else ""
                    self.tree.insert("", tk.END, values=(i+1, thumb, v["short"] + (" ← latest" if tag else ""), v["message"][:60], v["date"]))
                # auto-select latest for preview
                if versions:
                    first = self.tree.get_children()[0]
                    if first:
                        self.tree.selection_set(first)
                        self.tree.focus(first)
                        self.root.after(200, self._on_select)
        except Exception as e:
            self._set_diff_text(f"Log error: {e}")

        # git tree visualiser
        try:
            graph = get_git_graph(self.repo)
            self.git_text.configure(state="normal")
            self.git_text.delete("1.0", tk.END)
            self.git_text.insert(tk.END, graph)
            self.git_text.configure(state="disabled")
        except Exception:
            pass

        # highlight refresh
        orig = self.refresh_btn.cget("text")
        self.refresh_btn.config(text="✓ Refreshed")
        self.root.after(900, lambda: self.refresh_btn.config(text="↻  Refresh"))

    def _set_diff_text(self, s: str):
        self.diff_text.configure(state="normal")
        self.diff_text.delete("1.0", tk.END)
        self.diff_text.insert(tk.END, s)
        self.diff_text.configure(state="disabled")

    def _on_select(self):
        sel = self.tree.selection()
        if not sel:
            return
        vals = self.tree.item(sel[0], "values")
        try:
            num = int(vals[0])
        except:
            return
        # Update preview image for selected version
        try:
            versions = git_store.log_versions(self.repo, limit=50)
            idx = num - 1
            if 0 <= idx < len(versions):
                v = versions[idx]
                p = _preview_path(self.repo, v["hash"])
                if HAS_PIL_TK and p.exists() and p.stat().st_size > 100:
                    try:
                        img = Image.open(p)
                        # scale to fit ~ 520px wide
                        w, h = img.size
                        target_w = 540
                        scale = target_w / w
                        img2 = img.resize((target_w, int(h*scale)), Image.LANCZOS)
                        tkimg = ImageTk.PhotoImage(img2)
                        self._preview_images["sel"] = tkimg
                        self.preview_lbl.config(image=tkimg, text="", bg="#1c1c1e")
                    except Exception:
                        self.preview_lbl.config(text=f"Preview: {v['short']} — {v['message']}", image="", bg="#1c1c1e")
                else:
                    self.preview_lbl.config(text=f"Preview: {v['short']} — {v['message']}", image="", bg="#1c1c1e")

                # diff vs latest
                other = versions[0]["hash"] if idx != 0 else (versions[1]["hash"] if len(versions)>1 else v["hash"])
                a = other if idx==0 else v["hash"]
                b = v["hash"] if idx==0 else versions[0]["hash"]
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as ta:
                    pa = ta.name
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tb:
                    pb = tb.name
                try:
                    git_store.restore_version(self.repo, a, pa)
                    git_store.restore_version(self.repo, b, pb)
                    old = parse_otio_file(pa); new = parse_otio_file(pb)
                    d = diff_timelines(old, new)
                    txt = f"Version {num} vs latest:\n{changelog_line(d)}\n\n" + "\n".join(f"{ch.type:12} {ch.clip_name}  {str(ch.details)[:80]}" for ch in d.changes[:20])
                    self._set_diff_text(txt)
                finally:
                    for pp in (pa,pb):
                        try: Path(pp).unlink()
                        except: pass
        except Exception as e:
            self._set_diff_text(f"Preview error: {e}")

    # ---------- actions ----------
    def _export(self):
        out = self.repo / "timeline.otio"
        env_out = os.environ.get("GET_SYNCD_OUT")
        if env_out:
            out = Path(env_out).expanduser()
        ok, msg = _try_resolve_export(out)
        if ok:
            messagebox.showinfo("Exported", msg + f"\n\nNow add a note and click Save. All files stay in {self.repo}")
            self._refresh_all()
        else:
            manual = (
                f"{msg}\n\nManual (always works):\n"
                f"1) Resolve → File → Export Timeline → OpenTimelineIO\n"
                f"2) Save as: {out}\n"
                f"3) Come back and click Refresh → Save"
            )
            messagebox.showwarning("Export — manual step", manual)
            self._set_diff_text(manual)

    def _save(self):
        msg = self.msg_var.get().strip()
        src = self.repo / "timeline.otio"
        if not src.exists():
            cand = git_store.find_timeline_candidate(self.repo)
            if cand and cand.exists():
                src = cand
                try:
                    rel = cand.relative_to(self.repo)
                    if str(rel) != "timeline.otio":
                        print(f"[gui] Using discovered timeline: {rel}")
                except Exception:
                    pass
            else:
                messagebox.showerror("No timeline", f"No {src} yet. Click Export or File → Export Timeline → OpenTimelineIO → {src}")
                return
        if not msg:
            try:
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
            h = git_store.save_version(self.repo, src, msg)
            # generate preview for new version
            try:
                generate_preview(self.repo, h, src)
            except Exception:
                pass
            messagebox.showinfo("Saved", f"Version {h[:8]}:\n{msg}\n\nStored in {self.repo} — no hunting needed.")
            self.msg_var.set("")
            self._refresh_all()
        except ValueError as e:
            messagebox.showinfo("Nothing to save", str(e))
        except Exception as e:
            messagebox.showerror("Save failed", str(e))

    def _diff_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Pick one", "Select a version first.")
            return
        self._on_select()

    def _restore_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Pick one", "Select a version to restore.")
            return
        vals = self.tree.item(sel[0], "values")
        num = str(vals[0])
        if not messagebox.askyesno("Change to this version?", f"Overwrite {self.repo / 'timeline.otio'} with version {num} ({vals[2]})?\n\nThis becomes your current timeline. Next Resolve import will show it.\nBackup saved to .get-syncd/backups/."):
            return
        try:
            versions = git_store.log_versions(self.repo, limit=50)
            idx = int(num)-1
            rev = versions[idx]["hash"] if 0 <= idx < len(versions) else num
            out = self.repo / "timeline.otio"
            if out.exists():
                bdir = self.repo / ".get-syncd" / "backups"
                bdir.mkdir(parents=True, exist_ok=True)
                import shutil, datetime
                ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                shutil.copy2(str(out), str(bdir / f"timeline-{ts}.otio"))
            git_store.restore_version(self.repo, rev, out)
            messagebox.showinfo("Changed", f"Now using version {num}.\n\nResolve → File → Import Timeline → OpenTimelineIO → {out}")
            self._refresh_all()
        except Exception as e:
            messagebox.showerror("Restore failed", str(e))

    def _view_selected(self):
        versions = git_store.log_versions(self.repo, limit=50)
        if len(versions) < 2:
            messagebox.showinfo("Need 2", "Save at least 2 versions to view.")
            return
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values"); idx = int(vals[0])-1
            a = versions[idx]["hash"]; b = versions[0]["hash"]
        else:
            a = versions[1]["hash"]; b = versions[0]["hash"]
        try:
            from .viewer.app import run_viewer
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
        except Exception as e:
            messagebox.showerror("Switch failed", str(e))

    def _push(self):
        try:
            out = git_store.push(self.repo)
            messagebox.showinfo("Pushed", out or "Pushed to GitHub.")
        except Exception as e:
            messagebox.showerror("Push failed", str(e))

    def _toggle_watch(self):
        if self._watching:
            self._watching = False
            self.watch_btn.config(text="Watch: OFF", bg="#5856d6")
            return
        self._watching = True
        self.watch_btn.config(text="Watch: ON", bg="#30d158")
        def loop():
            last = ""
            wf = self.repo / "timeline.otio"
            if wf.exists():
                try: last = git_store.file_hash(wf)
                except: last = str(wf.stat().st_mtime)
            while self._watching:
                time.sleep(2.0)
                if not wf.exists(): continue
                try:
                    cur = git_store.file_hash(wf)
                except: continue
                if cur != last:
                    last = cur
                    try:
                        self.root.after(0, lambda: self._refresh_all())
                        self.root.after(200, lambda: self._on_watch_prompt())
                    except: pass
        threading.Thread(target=loop, daemon=True).start()

    def _on_watch_prompt(self):
        # subtle: just refresh, don't spam popup — status already shows unsaved
        # optionally prompt
        pass

    def run(self):
        self.root.mainloop()

def run_gui(repo: Path):
    # normalize to workspace if user launched from app folder or no repo
    if not repo or str(repo) == ".":
        repo = DEFAULT_WORKSPACE
    repo = Path(repo).expanduser().resolve()
    # If repo is the app source (contains src/get_syncd), redirect to workspace
    if (repo / "src" / "get_syncd").exists() and (repo / "pyproject.toml").exists():
        repo = DEFAULT_WORKSPACE
    repo.mkdir(parents=True, exist_ok=True)
    if not git_store.is_git_repo(repo):
        git_store.init_repo(repo)
    if not HAS_TK:
        print("Tkinter missing — fallback: get-syncd watch", file=sys.stderr)
        sys.exit(1)
    app = SidecarApp(repo)
    app.run()
