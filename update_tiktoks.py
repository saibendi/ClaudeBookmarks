#!/usr/bin/env python3
"""
update_tiktoks.py — Runs TikTokDownloader/fetch_tiktoks.py then
categorize_tiktoks.py back to back, so you don't have to run both commands
separately. Mirrors update_bookmarks.py's role on the Twitter side.

Usage:
    python3 update_tiktoks.py --start-line 555 --end-line 574   # fetch that
                                                                  # urls.md
                                                                  # range, then
                                                                  # categorize
    python3 update_tiktoks.py --count 20                        # fetch next
                                                                  # 20 pending
                                                                  # (top of
                                                                  # urls.md),
                                                                  # then
                                                                  # categorize
    python3 update_tiktoks.py --start-line 555 --end-line 574 --reclassify

Run with the same Python that has requests / python-dotenv / anthropic
installed, e.g.:
    /usr/bin/python3 update_tiktoks.py --start-line 555 --end-line 574
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
FETCH_SCRIPT = "TikTokDownloader/fetch_tiktoks.py"
CATEGORIZE_SCRIPT = "categorize_tiktoks.py"


def run(args, label):
    print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
    result = subprocess.run(
        [sys.executable, "-u", *args],
        cwd=SCRIPT_DIR,
    )
    if result.returncode != 0:
        print(f"\n{label} failed (exit code {result.returncode}) — stopping.")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Fetch TikToks, then categorize them, in one step.")
    parser.add_argument(
        "--count", type=int, default=15, metavar="N",
        help="How many not-yet-downloaded TikToks to process this run (default: 15)"
    )
    parser.add_argument(
        "--start-line", type=int, default=None, metavar="N",
        help="Only consider urls.md lines >= N (1-indexed, inclusive) — e.g. to target one section"
    )
    parser.add_argument(
        "--end-line", type=int, default=None, metavar="N",
        help="Only consider urls.md lines <= N (1-indexed, inclusive)"
    )
    parser.add_argument(
        "--reclassify", action="store_true",
        help="Ignore existing categories.js and reclassify everything"
    )
    args = parser.parse_args()

    fetch_args = [FETCH_SCRIPT, "--count", str(args.count)]
    if args.start_line is not None:
        fetch_args += ["--start-line", str(args.start_line)]
    if args.end_line is not None:
        fetch_args += ["--end-line", str(args.end_line)]

    categorize_args = [CATEGORIZE_SCRIPT]
    if args.reclassify:
        categorize_args.append("--reclassify")

    run(fetch_args, "Step 1/2: fetch_tiktoks.py")
    run(categorize_args, "Step 2/2: categorize_tiktoks.py")

    print(f"\n{'=' * 60}\nDone. Open index.html / day.html / categories.html to see the update.\n{'=' * 60}")


if __name__ == "__main__":
    main()
