"""
DaVinci Resolve export helper for Get Syncd.

Usage inside DaVinci Resolve:
  Workspace → Scripts → Console
  Then run: exec(open('/path/to/get-syncd/scripts/resolve_export.py').read())

Or set as a Workspace → Scripts → Comp script.

What it does:
- Tries to export the current timeline to OTIO via the Resolve API (if available in your Resolve version).
- Falls back to printing manual instructions if scripting export is not available.

The Resolve Python API is version-dependent for OTIO export — treat scripted export
as a nice-to-have with a manual fallback, not a hard dependency.

After export, commit with:
  get-syncd save --file /path/to/timeline.otio -m "Your message"
"""

import sys
import os

# Resolve provides `resolve` or `bmd` globals in the Console
try:
    resolve = bmd  # type: ignore  # noqa: F821
except NameError:
    try:
        import DaVinciResolveScript as bmd  # type: ignore

        resolve = bmd.scriptapp("Resolve")
    except Exception:
        resolve = None

OUT_PATH = os.path.expanduser("~/Videos/GetSyncd/timeline.otio")
# Allow override via env
if "GET_SYNCD_OUT" in os.environ:
    OUT_PATH = os.environ["GET_SYNCD_OUT"]

if resolve is None:
    print("[Get Syncd] Could not connect to DaVinci Resolve API.")
    print("Manual export: File → Export Timeline → OpenTimelineIO → save as:")
    print(f"  {OUT_PATH}")
    print("Then run in terminal: get-syncd save --file \"{}\" -m \"Your message\"".format(OUT_PATH))
    sys.exit(0)

try:
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        print("[Get Syncd] No project open in Resolve.")
        print("Open a project, then retry. Manual fallback: File → Export Timeline → OpenTimelineIO")
        sys.exit(0)

    timeline = project.GetCurrentTimeline()
    if not timeline:
        print("[Get Syncd] No timeline open. Open a timeline in the Edit page, then retry.")
        sys.exit(0)

    name = timeline.GetName()
    print(f"[Get Syncd] Current timeline: {name}")

    # Try API export — method names vary by Resolve version; probe several
    exported = False
    # Method 1: Timeline.Export (documented for some versions)
    for method_name in ["Export", "ExportTimeline", "ExportOTIO"]:
        if hasattr(timeline, method_name):
            try:
                ok = getattr(timeline, method_name)(OUT_PATH, "otio")
                if ok:
                    exported = True
                    print(f"[Get Syncd] Exported via Timeline.{method_name} → {OUT_PATH}")
                    break
            except Exception as e:
                print(f"[Get Syncd] Timeline.{method_name} failed: {e}")

    # Method 2: Project.ExportTimeline
    if not exported and hasattr(project, "ExportTimeline"):
        try:
            ok = project.ExportTimeline(OUT_PATH, "otio")
            if ok:
                exported = True
                print(f"[Get Syncd] Exported via Project.ExportTimeline → {OUT_PATH}")
        except Exception as e:
            print(f"[Get Syncd] Project.ExportTimeline failed: {e}")

    if not exported:
        print("[Get Syncd] Automatic export not available in this Resolve version.")
        print("Please export manually:")
        print("  File → Export Timeline → OpenTimelineIO → save as:")
        print(f"    {OUT_PATH}")
        print("Then in terminal:")
        print(f'  get-syncd save --file "{OUT_PATH}" -m "Describe your changes"')
        print(f'  get-syncd status   # check for unsaved changes')
        print(f'  get-syncd diff HEAD~1 HEAD --text')
    else:
        print(f"[Get Syncd] Done. Now run:")
        print(f'  get-syncd save --file "{OUT_PATH}" -m "Describe your changes"')

except Exception as e:
    print(f"[Get Syncd] Error: {e}")
    import traceback

    traceback.print_exc()
    print("Fallback: File → Export Timeline → OpenTimelineIO")
