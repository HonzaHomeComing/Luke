"""CLI / GUI entrypoint.

Usage:
  python -m wunderwaffe_scanner
  python -m wunderwaffe_scanner --cli "C:\\...\\Project Wunderwaffe"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan Project Wunderwaffe files for the 120-day timer (Phase 1)."
    )
    parser.add_argument(
        "--cli",
        metavar="GAME_DIR",
        help="Run without GUI: scan GAME_DIR and write logs.",
    )
    parser.add_argument(
        "--out",
        default=str(Path.cwd() / "scan_logs"),
        help="Directory for scan logs (default: ./scan_logs)",
    )
    args = parser.parse_args(argv)

    if args.cli:
        from .scanner import scan_game_root, write_logs

        def progress(msg: str, frac: float) -> None:
            pct = int(frac * 100)
            print(f"[{pct:3d}%] {msg}")

        report = scan_game_root(args.cli, progress=progress)
        json_path, txt_path = write_logs(report, args.out)
        print()
        print(f"Hits: {report.total_hits}")
        print(f"Engine guess: {', '.join(report.engine_guess)}")
        print(f"JSON: {json_path}")
        print(f"TXT:  {txt_path}")
        print("Send both log files back for Phase 2.")
        return 0

    # GUI mode
    try:
        from .gui import run

        run()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"GUI failed ({exc}). Falling back to CLI help.", file=sys.stderr)
        parser.print_help()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
