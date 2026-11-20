## 🎬 Get Syncd v0.4.0 — The Visual Timeline & Git Redesign

We're thrilled to introduce **Get Syncd v0.4.0**, a major release featuring a ground-up redesign of the UI/UX, an all-new proportional multi-track visual diff canvas, an interactive Cut Tree rail, live DaVinci Resolve connection status, and seamless keyboard-driven navigation.

---

### ✨ What's New

#### 1. 🎞️ Proportional Multi-Track Visual Timeline Canvas
- **Multi-Track Rendering:** Renders proportional clip blocks across all video (`V1`–`Vn`) and audio (`A1`–`An`) tracks.
- **Diff Overlay Mode (`1`):** Shows live additions, modifications, and semi-transparent ghost blocks with diagonal stripes for deleted clips.
- **Split Before / After Mode (`2`):** Direct side-by-side comparison of baseline and comparison timelines.
- **Interactive Scrubber:** Scrub through the timeline with SMPTE timecode readout (`HH:MM:SS:FF`) and zoom from `1×` to `4×`.

#### 2. 🟢 Live DaVinci Resolve Status
- Real-time connection badge (`● Resolve · Project`) with 15-second polling.
- Hover popover displaying active project name, active timeline, connection health, and quick troubleshooting tips.

#### 3. 🌿 Interactive Multi-Lane Cut Tree
- Visual Git history graph with smooth SVG Bézier curves across multiple lanes.
- Snapshot nodes with author tags, commit hashes, and a slide-out Technical Details drawer showing exact OTIO metadata.
- Integrated GitHub backup status card with quick push/sync actions.

#### 4. 🔍 Plain-English Changes Inspector
- Single compact delta summary bar (`+3 added`, `-1 removed`, `~2 modified`).
- Track filter chips (`All`, `V1`, `V2`, `A1`, `A2`).
- **J / K Keyboard Navigation:** Jump between changes with automatic canvas playhead centering and clip highlighting.
- Bidirectional clip sync: clicking any clip in the canvas scrolls directly to its inspection card.

#### 5. 🛡️ Safe 2-Step Restore Flow
- Restoring an older cut automatically creates a safety snapshot of uncommitted work.
- Injects the historical cut into Resolve via Python API, with an instant **Copy OTIO / XML to Clipboard** fallback if manual relinking is required.

#### 6. ⌨️ Professional Keyboard Shortcuts
| Shortcut | Action |
| :--- | :--- |
| <kbd>⌘S</kbd> / <kbd>Ctrl+S</kbd> | Open **Save Snapshot** modal |
| <kbd>1</kbd> | Switch timeline canvas to **Diff Overlay** |
| <kbd>2</kbd> | Switch timeline canvas to **Split Before / After** |
| <kbd>J</kbd> | Navigate to **Next Change** |
| <kbd>K</kbd> | Navigate to **Previous Change** |
| <kbd>↑</kbd> / <kbd>↓</kbd> | Step through snapshot history |
| <kbd>Esc</kbd> | Dismiss any open modal or popover |

---

### 📦 Downloads & Verification

| OS / Architecture | Package | Description |
| :--- | :--- | :--- |
| **macOS (Apple Silicon)** | `Get Syncd_0.4.0_aarch64.dmg` | Native DMG installer for M1/M2/M3/M4 Macs |

*Note: Windows and Linux packages are automatically built and attached by GitHub Actions CI for tagged releases.*
