#!/usr/bin/env python3
"""
fetch_tiktoks.py — Download TikToks listed in urls.md and write data_tiktok.js
for the calendar UI (mirrors fetch_bookmarks.py's role on the Twitter side).

Usage:
    python3 fetch_tiktoks.py             # process next 15 not-yet-downloaded TikToks
    python3 fetch_tiktoks.py --count 20  # process next 20 instead

Dependencies:
    pip install requests
    gallery-dl must be installed and on PATH (https://github.com/mikf/gallery-dl)
    ffmpeg/ffprobe must be installed and on PATH (brew install ffmpeg) — used to
    detect and re-encode HEVC video to H.264, since TikTok's CDN serves HEVC on
    the URL gallery-dl grabs and most non-Safari browsers can't decode it.

This is a manual, batch-at-a-time backfill, not a poller — there's no ongoing
TikTok API to incrementally check. New TikToks get added to urls.md by hand;
each run picks up wherever the last one left off (idempotent: a TikTok already
downloaded is skipped, tracked by the presence of its media/tiktok/<id>/<id>.json
marker file).
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Paths ─────────────────────────────────────────────────────────────────────
# urls.md is an input, local to this script's own folder. Everything the
# browser actually loads (data_tiktok.js, media/) has to live at the project
# root next to data.js — index.html etc. resolve <script src="..."> and any
# relative path stored inside it against their own location (the root), not
# against wherever this script happens to sit.
SCRIPT_DIR      = Path(__file__).parent
PROJECT_ROOT    = SCRIPT_DIR.parent
URLS_MD         = SCRIPT_DIR / "urls.md"
MEDIA_DIR       = PROJECT_ROOT / "media" / "tiktok"
DATA_TIKTOK_JS  = PROJECT_ROOT / "data_tiktok.js"

# ── urls.md parsing ───────────────────────────────────────────────────────────

URL_RE = re.compile(r"https://www\.tiktok\.com/@[\w.\-]+/(video|photo)/(\d+)")


def parse_urls_md(path, start_line=None, end_line=None):
    """Extract (tiktok_id, url) pairs from urls.md, in file order, deduped by id.
    Lines that aren't TikTok permalinks (section markers, blank lines, the
    scratch category list at the bottom) simply don't match and are skipped.
    start_line/end_line (1-indexed, inclusive) optionally restrict which lines
    of the file are considered at all, e.g. to target one urls.md section."""
    urls = []
    seen_ids = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if start_line is not None and lineno < start_line:
            continue
        if end_line is not None and lineno > end_line:
            continue
        m = URL_RE.search(line)
        if not m:
            continue
        tiktok_id = m.group(2)
        if tiktok_id in seen_ids:
            continue
        seen_ids.add(tiktok_id)
        urls.append((tiktok_id, m.group(0)))
    return urls


def is_already_downloaded(tiktok_id):
    """Completion marker: <id>.json only gets written after a fully successful
    download + normalize pass, so a partial/failed run is correctly retried."""
    return (MEDIA_DIR / tiktok_id / f"{tiktok_id}.json").exists()


# ── Download (gallery-dl) ─────────────────────────────────────────────────────

def run_gallery_dl(url, dest_dir):
    """Run gallery-dl for one URL, writing media + per-file metadata JSON
    straight into dest_dir. Returns True on success, False on failure (so one
    bad URL in a batch doesn't take down the rest)."""
    try:
        result = subprocess.run(
            ["gallery-dl", "--write-metadata", "-D", str(dest_dir), url],
            capture_output=True, text=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("    ! gallery-dl timed out")
        return False
    except FileNotFoundError:
        print("ERROR: gallery-dl not found on PATH — is it installed?")
        sys.exit(1)

    if result.returncode != 0:
        stderr_lines = result.stderr.strip().splitlines()
        detail = stderr_lines[-1] if stderr_lines else "unknown error"
        print(f"    ! gallery-dl failed: {detail}")
        return False
    return True


# ── Normalize gallery-dl's output into the flat <id>-keyed layout (Decision #5) ─

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov"}
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav"}


def normalize_downloaded_files(dest_dir, tiktok_id):
    """Rename gallery-dl's caption-embedded filenames down to the flat
    <id>/<id>.mp4 or <id>/<id>_NN.jpg + <id>.mp3 convention, and collapse the
    per-file metadata JSON sidecars into a single representative <id>.json.
    Returns {"type": "video"|"photo", "video"/"images"/"audio": Path(s),
    "metadata": dict} or None if nothing usable was downloaded."""
    media_files = sorted(
        p for p in dest_dir.iterdir()
        if p.is_file() and p.suffix.lower() != ".json"
    )
    if not media_files:
        return None

    videos = [p for p in media_files if p.suffix.lower() in VIDEO_EXTS]
    images = [p for p in media_files if p.suffix.lower() in IMAGE_EXTS]
    audios = [p for p in media_files if p.suffix.lower() in AUDIO_EXTS]

    metadata = None
    result = {"type": None, "video": None, "images": [], "audio": None}

    if videos:
        result["type"] = "video"
        src = videos[0]
        json_src = Path(str(src) + ".json")
        if json_src.exists():
            metadata = json.loads(json_src.read_text(encoding="utf-8"))
        dst = dest_dir / f"{tiktok_id}.mp4"
        src.rename(dst)
        result["video"] = dst

    elif images:
        result["type"] = "photo"
        for i, src in enumerate(images, start=1):
            json_src = Path(str(src) + ".json")
            if metadata is None and json_src.exists():
                metadata = json.loads(json_src.read_text(encoding="utf-8"))
            dst = dest_dir / f"{tiktok_id}_{i:02d}.jpg"
            src.rename(dst)
            result["images"].append(dst)
        if audios:
            adst = dest_dir / f"{tiktok_id}.mp3"
            audios[0].rename(adst)
            result["audio"] = adst

    else:
        return None

    # Write the one representative metadata file, then sweep every leftover
    # per-asset JSON sidecar gallery-dl left behind (Decision #5: one <id>.json).
    json_dst = dest_dir / f"{tiktok_id}.json"
    if metadata is not None:
        json_dst.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    for leftover in dest_dir.glob("*.json"):
        if leftover.name != json_dst.name:
            leftover.unlink()

    result["metadata"] = metadata
    return result


def fetch_thumbnail(metadata, dest_dir, tiktok_id):
    """Decision #3: gallery-dl doesn't write a thumbnail by default, but its
    metadata already contains the cover image URL — fetch it directly as a
    cheap extra step instead of falling back to a second tool."""
    video_meta = (metadata or {}).get("video", {}) or {}
    cover_url = video_meta.get("originCover") or video_meta.get("dynamicCover") or video_meta.get("cover")
    if not cover_url:
        return None
    try:
        resp = requests.get(cover_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"    ! thumbnail fetch failed: {exc}")
        return None
    dst = dest_dir / f"{tiktok_id}_thumb.jpg"
    dst.write_bytes(resp.content)
    return dst


# ── HEVC → H.264 transcode ────────────────────────────────────────────────────
# gallery-dl's TikTok extractor just grabs the highest-bitrate URL TikTok
# offers, with no codec preference — TikTok's CDN currently serves that as
# HEVC (confirmed: hvc1 fourcc in the actual downloaded bytes, despite
# gallery-dl's own metadata mislabeling it "h264"). Most Chrome/Firefox
# builds have no HEVC decoder at all, so the <video> tag's audio track plays
# but the picture never renders (videoWidth/videoHeight stuck at 0). Safari
# on macOS has native hardware HEVC support and wouldn't hit this, but H.264
# plays everywhere, so re-encoding removes the browser-dependency entirely.

def video_codec(path):
    """Return the video stream's codec name (e.g. "h264", "hevc"), or None
    if ffprobe can't read it."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    name = result.stdout.strip()
    return name or None


def transcode_to_h264(path):
    """Re-encode path to H.264/AAC in place (temp file + atomic rename).
    Returns True on success, False on failure (original file left untouched)."""
    tmp = path.with_suffix(".h264.mp4")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(path),
             "-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart",
             str(tmp)],
            capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        tmp.unlink(missing_ok=True)
        return False

    if result.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return False

    tmp.replace(path)
    return True


def ensure_h264(path):
    """Check path's video codec and transcode only if it isn't already H.264.
    Returns True if a transcode happened, False if already fine or it failed."""
    codec = video_codec(path)
    if codec == "h264":
        return False
    if codec is None:
        print(f"    ! couldn't probe codec for {path.name} — leaving as-is")
        return False
    print(f"    ! {codec} detected, re-encoding to H.264 for browser compatibility…")
    if not transcode_to_h264(path):
        print(f"    ! transcode failed for {path.name} — leaving original (may not play in Chrome/Firefox)")
        return False
    return True


# ── Build the data_tiktok.js item shape ───────────────────────────────────────

def rel_path(p):
    return p.relative_to(PROJECT_ROOT).as_posix()


def build_item(files, tiktok_id, permalink):
    """Shape a downloaded TikTok into the same field names data.js already
    uses for tweets (text, author_name, author_handle, like_count, images: [...])
    so index.html/day.html/categories.html/stats.html need no code changes."""
    metadata = files.get("metadata")
    if metadata is None:
        return None

    author = metadata.get("author", {}) or {}
    stats = metadata.get("stats") or metadata.get("statsV2") or {}

    create_time = metadata.get("createTime")
    if create_time:
        created_dt = datetime.fromtimestamp(int(create_time), tz=timezone.utc)
        created_at = created_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        created_dt = None
        created_at = ""

    handle = author.get("uniqueId") or metadata.get("user") or "unknown"
    name = author.get("nickname") or handle

    item = {
        # Decision #6: tt_ prefix applied only here, at write time — keeps
        # Twitter's existing tweet IDs untouched, guarantees no collision.
        "id":             f"tt_{tiktok_id}",
        "text":           metadata.get("desc") or metadata.get("title") or "",
        "author_name":    name,
        "author_handle":  f"@{handle}",
        "created_at":     created_at,
        # When *we* fetched it, not when the TikTok was originally posted —
        # this is what recency sort in categorize_*.py actually uses.
        "added_at":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Decision #1: permalink kept as citation only, never as playback source.
        "url":            permalink,
        "like_count":     stats.get("diggCount", 0),
        "bookmark_count": stats.get("collectCount", 0),
        "comment_count":  stats.get("commentCount", 0),
        "share_count":    stats.get("shareCount", 0),
        "view_count":     stats.get("playCount", 0),
        "images":         [],
    }

    if files["type"] == "video":
        video_meta = metadata.get("video", {}) or {}
        thumb = files.get("thumb")
        item["images"] = [{
            "url":       rel_path(thumb) if thumb else "",
            "type":      "video",
            "video_url": rel_path(files["video"]),
        }]
        duration = video_meta.get("duration") or metadata.get("duration")
        if duration:
            item["duration"] = duration
    else:  # photo — Decision #4: multiple images + background audio
        item["images"] = [{"url": rel_path(p), "type": "photo"} for p in files["images"]]
        if files.get("audio"):
            item["audio_url"] = rel_path(files["audio"])

    return item, created_dt


# ── Group by date (mirrors fetch_bookmarks.py's group_by_date / timezone handling) ─

def group_by_date(items_with_dt):
    dates = {}
    videos_by_date = {}
    for item, created_dt in items_with_dt:
        if created_dt is None:
            continue
        # .astimezone() with no arg converts UTC → system local before taking
        # the date, same gotcha documented in CLAUDE.md for fetch_bookmarks.py.
        date_str = created_dt.astimezone().strftime("%Y-%m-%d")
        videos_by_date.setdefault(date_str, []).append(item)
        dates[date_str] = dates.get(date_str, 0) + 1
    return dates, videos_by_date


# ── Merge with existing data_tiktok.js ────────────────────────────────────────

def load_existing_data():
    if not DATA_TIKTOK_JS.exists():
        return {}
    try:
        raw = DATA_TIKTOK_JS.read_text(encoding="utf-8")
        match = re.search(r"window\.TIKTOK_VIDEOS\s*=\s*(\{[\s\S]*?\});", raw)
        if not match:
            return {}
        return json.loads(match.group(1))
    except Exception:
        return {}


def merge_by_date(old_by_date, new_by_date):
    """Same read-existing → dedupe-by-id → merge pattern fetch_bookmarks.py
    uses, so repeated small batch runs accumulate instead of clobbering."""
    merged = {date: {v["id"]: v for v in videos} for date, videos in old_by_date.items()}

    added = 0
    for date, videos in new_by_date.items():
        bucket = merged.setdefault(date, {})
        for v in videos:
            if v["id"] not in bucket:
                added += 1
            bucket[v["id"]] = v

    return {date: list(id_map.values()) for date, id_map in merged.items()}, added


# ── Write data_tiktok.js ──────────────────────────────────────────────────────

def write_data_tiktok_js(dates, videos_by_date):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = sum(dates.values())

    content = f"""// Auto-generated by fetch_tiktoks.py — do not edit manually.
// Last updated: {now}  |  Total TikToks: {total}
// Run: python3 fetch_tiktoks.py --count N
window.TIKTOK_DATES  = {json.dumps(dates, indent=2, ensure_ascii=False)};
window.TIKTOK_VIDEOS = {json.dumps(videos_by_date, indent=2, ensure_ascii=False)};
"""
    DATA_TIKTOK_JS.write_text(content, encoding="utf-8")
    print(f"\nWrote {DATA_TIKTOK_JS}  ({total} TikToks across {len(dates)} days)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download TikToks from urls.md → data_tiktok.js")
    parser.add_argument(
        "--count", type=int, default=15, metavar="N",
        help="How many not-yet-downloaded TikToks to process this run (default: 15)"
    )
    parser.add_argument(
        "--urls-file", type=Path, default=URLS_MD,
        help="Path to the urls.md backlog (default: urls.md next to this script)"
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
        "--reencode-existing", action="store_true",
        help="Maintenance mode: scan already-downloaded media/tiktok/*/*.mp4 for "
             "non-H.264 video and re-encode in place. Doesn't touch urls.md or fetch anything new."
    )
    args = parser.parse_args()

    print("TikTok Fetcher")
    print("=" * 40)

    if args.reencode_existing:
        videos = sorted(MEDIA_DIR.glob("*/*.mp4"))
        print(f"Checking {len(videos)} downloaded video(s) for non-H.264 codecs…\n")
        fixed = 0
        for path in videos:
            if ensure_h264(path):
                fixed += 1
        print(f"\n{fixed} re-encoded, {len(videos) - fixed} already fine (or failed to probe).")
        return

    if not args.urls_file.exists():
        print(f"ERROR: {args.urls_file} not found.")
        sys.exit(1)

    all_urls = parse_urls_md(args.urls_file, start_line=args.start_line, end_line=args.end_line)
    pending = [(tid, url) for tid, url in all_urls if not is_already_downloaded(tid)]
    range_desc = ""
    if args.start_line is not None or args.end_line is not None:
        range_desc = f" (lines {args.start_line or 1}-{args.end_line or 'end'})"
    print(f"{len(all_urls)} TikToks in {args.urls_file.name}{range_desc}, "
          f"{len(all_urls) - len(pending)} already downloaded, {len(pending)} pending.")

    if not pending:
        print("Nothing to do — everything in urls.md has already been downloaded.")
        return

    batch = pending[: args.count]
    print(f"Processing {len(batch)} this run (--count {args.count})…\n")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    items_with_dt = []
    succeeded = 0
    failed = 0

    for i, (tiktok_id, url) in enumerate(batch, start=1):
        print(f"[{i}/{len(batch)}] {url}")
        dest_dir = MEDIA_DIR / tiktok_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        if not run_gallery_dl(url, dest_dir):
            failed += 1
            continue

        files = normalize_downloaded_files(dest_dir, tiktok_id)
        if files is None or files.get("metadata") is None:
            print("    ! no usable media/metadata found, skipping")
            failed += 1
            continue

        if files["type"] == "video":
            files["thumb"] = fetch_thumbnail(files["metadata"], dest_dir, tiktok_id)
            ensure_h264(files["video"])

        built = build_item(files, tiktok_id, url)
        if built is None:
            failed += 1
            continue

        item, created_dt = built
        items_with_dt.append((item, created_dt))
        succeeded += 1
        preview = (item["text"] or "")[:60].replace("\n", " ")
        print(f"    ✓ {files['type']} — {item['author_handle']} — {preview!r}")

    print(f"\n{succeeded} succeeded, {failed} failed.")

    if items_with_dt:
        new_dates, new_by_date = group_by_date(items_with_dt)
        existing_by_date = load_existing_data()
        existing_total = sum(len(v) for v in existing_by_date.values())
        merged_by_date, added = merge_by_date(existing_by_date, new_by_date)
        dates = {date: len(v) for date, v in merged_by_date.items()}
        print(f"Merged with existing data_tiktok.js: {existing_total} previously stored, "
              f"{added} new, {sum(dates.values())} total after merge.")
        write_data_tiktok_js(dates, merged_by_date)

    remaining = len(pending) - len(batch)
    if remaining > 0:
        print(f"\n{remaining} still pending in urls.md — run again to continue.")
    else:
        print("\nAll caught up!")


if __name__ == "__main__":
    main()
