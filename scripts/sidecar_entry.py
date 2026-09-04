"""Frozen entry point for the Tauri sidecar binary.

PyInstaller must import `get_syncd` as a package (relative imports inside
api_server.py fail when the file is frozen directly as __main__).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from get_syncd.api_server import run_api_server


def main() -> None:
    ap = argparse.ArgumentParser(prog="get-syncd-api")
    ap.add_argument("--port", type=int, default=5174)
    args = ap.parse_args()
    run_api_server(port=args.port)


if __name__ == "__main__":
    main()
