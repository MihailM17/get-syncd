"""Frozen entry point for the Tauri sidecar binary.

PyInstaller must import `get_syncd` as a package (relative imports inside
api_server.py fail when the file is frozen directly as __main__).
"""

import argparse
import sys
from pathlib import Path

# Bump on every sidecar change under test — printed by --test-otio so a stale
# binary can never silently pass verification again.
BUILD_ID = "2026-09-04-07-lock-warmup-cleanbuild"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from get_syncd.api_server import run_api_server


def main() -> None:
    ap = argparse.ArgumentParser(prog="get-syncd-api")
    ap.add_argument("--port", type=int, default=5174)
    ap.add_argument("--test-otio", type=str, help="Test OTIO parsing on given file and exit")
    ap.add_argument("--build-id", action="store_true", help="Print BUILD_ID and exit")
    args = ap.parse_args()
    if args.build_id:
        print(BUILD_ID)
        return
    if args.test_otio:
        from get_syncd.otio_parse import parse_otio_file
        import opentimelineio as otio
        print(f"OTIO version: {otio.__version__}")
        print(f"Testing file: {args.test_otio}")
        try:
            from opentimelineio.adapters import available_adapter_names
            print(f"Adapters: {available_adapter_names()}")
        except Exception as e:
            print(f"Failed to list adapters: {e}")
        try:
            tl = parse_otio_file(args.test_otio)
            print(f"Parse OK: {tl.name}, tracks: {len(tl.tracks)}")
            for t in tl.tracks:
                print(f"  Track {t.name} ({t.kind}): {len(t.items)} items")
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"Parse failed: {e}")
        return
    run_api_server(port=args.port)


if __name__ == "__main__":
    main()
