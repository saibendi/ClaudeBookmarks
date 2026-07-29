#!/usr/bin/env python3
"""
update_bookmarks.py — Runs fetch_bookmarks.py then categorize_bookmarks.py
back to back, so you don't have to run both commands separately.

Usage:
    python3 update_bookmarks.py                # fetch last 30 days, then categorize
    python3 update_bookmarks.py --days 7        # fetch last 7 days, then categorize
    python3 update_bookmarks.py --all            # fetch every bookmark, then categorize
    python3 update_bookmarks.py --reclassify     # fetch last 30 days, then force full re-categorization

Run with the same Python that has requests / python-dotenv / anthropic installed, e.g.:
    /usr/bin/python3 update_bookmarks.py
"""

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


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
    parser = argparse.ArgumentParser(description="Fetch bookmarks, then categorize them, in one step.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--days", type=int, default=30, metavar="N",
        help="Only fetch bookmarks from the last N days (default: 30)"
    )
    group.add_argument(
        "--all", dest="fetch_all", action="store_true",
        help="Fetch every bookmark (no date limit; may be many pages)"
    )
    parser.add_argument(
        "--reclassify", action="store_true",
        help="Ignore existing categories.js and reclassify everything"
    )
    args = parser.parse_args()

    fetch_args = ["fetch_bookmarks.py"]
    if args.fetch_all:
        fetch_args.append("--all")
    else:
        fetch_args += ["--days", str(args.days)]

    categorize_args = ["categorize_bookmarks.py"]
    if args.reclassify:
        categorize_args.append("--reclassify")

    run(fetch_args, "Step 1/2: fetch_bookmarks.py")
    run(categorize_args, "Step 2/2: categorize_bookmarks.py")

    print(f"\n{'=' * 60}\nDone. Open index.html / categories.html / stats.html to see the update.\n{'=' * 60}")


if __name__ == "__main__":
    main()
