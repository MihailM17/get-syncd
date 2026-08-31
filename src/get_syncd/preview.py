"""Preview generation for Get Syncd — timeline bar PNG.

Shared by git_store (auto on save) and gui (display).
No circular deps: this module only depends on otio_parse.
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:
    HAS_PIL = False
    Image = ImageDraw = ImageFont = None

from .otio_parse import parse_otio_file

PREVIEW_DIRNAME = ".get-syncd/previews"

def _preview_path(repo: Path, rev_hash: str) -> Path:
    return repo / PREVIEW_DIRNAME / f"{rev_hash[:8]}.png"

def generate_preview(repo: Path, rev_hash: str, otio_path: Path) -> Path | None:
    out = _preview_path(repo, rev_hash)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size > 100:
        return out
    if not HAS_PIL:
        try:
            out.touch()
        except Exception:
            pass
        return out
    try:
        tl = parse_otio_file(otio_path)
        track = tl.main_track()
        items = track.items if track else []
    except Exception:
        items = []
    W, H = 800, 96
    pad = 12
    img = Image.new("RGB", (W, H), (18, 18, 18))
    draw = ImageDraw.Draw(img)
    palette = [(46, 204, 113), (52, 152, 219), (241, 196, 15), (231, 76, 60), (155, 89, 182), (22, 160, 133)]
    if not items:
        draw.text((W//2 - 60, H//2 - 8), "No clips", fill=(140, 140, 140))
        img.save(out)
        return out
    total_dur = sum(c.duration_frames for c in items) or 1
    x = pad
    bar_y = 28
    bar_h = 36
    draw.text((pad, 8), f"{len(items)} clips \u2022 {total_dur/60:.1f}s", fill=(180, 180, 180))
    usable = W - pad*2
    for i, c in enumerate(items):
        w = max(6, int(usable * (c.duration_frames / total_dur)))
        if x + w > W - pad:
            w = W - pad - x
        col = palette[i % len(palette)]
        draw.rounded_rectangle([x, bar_y, x+w, bar_y+bar_h], radius=6, fill=col, outline=(255,255,255,40))
        label = (c.name[:10] + "…") if len(c.name) > 10 else c.name
        draw.text((x+4, bar_y+bar_h+6), label, fill=(200,200,200))
        x += w + 3
        if x >= W - pad:
            break
    draw.text((pad, H-16), rev_hash[:8], fill=(100,100,100))
    img.save(out)
    return out

def ensure_previews(repo: Path):
    from . import git_store
    import tempfile
    try:
        versions = git_store.log_versions(repo, limit=20)
        for v in versions:
            p = _preview_path(repo, v["hash"])
            if not p.exists() or p.stat().st_size < 100:
                with tempfile.NamedTemporaryFile(suffix=".otio", delete=False) as tmp:
                    tp = Path(tmp.name)
                try:
                    git_store.restore_version(repo, v["hash"], tp)
                    generate_preview(repo, v["hash"], tp)
                except Exception:
                    pass
                finally:
                    try: tp.unlink(missing_ok=True)
                    except: pass
        cur = repo / "timeline.otio"
        if cur.exists():
            from .git_store import file_hash
            generate_preview(repo, "current-" + file_hash(cur), cur)
    except Exception:
        pass
