# Plan

## Design Choices

### #1 — Store local downloaded files, not TikTok CDN URLs

**Question:** For ~1200 TikTok videos, should downloaded media live as local files (mp4/jpg) referenced by path, or should we keep using remote TikTok CDN URLs — like the existing ClaudeBookmarks product does for tweets (`pbs.twimg.com` / `video.twimg.com`)? Isn't storing the remote URL more consistent with the existing strategy?

**Answer:** No — this isn't actually a stylistic choice, it's a hard technical constraint specific to TikTok. There are two different URLs in play:

1. **The permalink** (`tiktok.com/@user/video/12345...`) — stable indefinitely, like a tweet URL. This is what shows up in the Favorites/Likes export.
2. **The raw media file URL** — the actual `.mp4` location on TikTok's CDN, which is *signed and expires* (an `expire=` timestamp baked into the URL, often just hours later). This is what `yt-dlp`/`gallery-dl` extract from the permalink at download time, and what a `<video src="...">` tag actually needs to play something.

Twitter's `pbs.twimg.com` links are an exception among platforms — no expiry token, so the existing tweet pipeline can safely store just the URL. TikTok doesn't offer that for video files; only the permalink is durable, and the permalink itself isn't embeddable and isn't independent of TikTok (breaks if the video is deleted, geo-blocked, or the account is banned).

**Decision:** Download and store the actual video/image files locally (already happening via the yt-dlp → gallery-dl pipeline), reference them by relative path in `data.js`. Store the permalink alongside as a "source of truth" reference/citation, not as the playback source. Storage cost is negligible — ~1200 short clips ≈ 20-30GB on a 1TB drive.

### #2 — Slotting the TikTok pipeline into the existing app: what's already covered vs. what needs new work

**Question:** so we discussed that we'd be downloading the videos (the download mechanism we can discuss later once we actually receive the custom data from tiktok - the mechanism is worthwhile listing out as a todo or something in the plan) - but the flow i'm imagining is we have a database or a folder with all the downloaded tiktok videos; we then run something like fetch_tiktoks (something similar to fetch_bookmarks) which'll populate data.js with the tiktok metadata; then we run something like categorize_tiktoks (similar to categorize_bookmarks) to update categories.js - and the flexibility of downloading a new categories.js after moving stuff around in the .html will be unchanged / will be the same; and I think everything else is already implemented right - index.html / stats.html / categories.html all pull from the data.js and categories.js right? are there any other parts of the pipeline that need to be addressed

**Answer:** I checked the actual code rather than assume, and your mental model is mostly right — but there's one real gap that would break things, and a few reassuring facts backing you up.

**Good news — you're right that this mostly already works:**

I checked how `categories.html`/`day.html` render video-type items:
```js
if (img.type !== "photo" && img.video_url) {
  video.src = img.video_url;        // ← works fine with a local relative path
  if (img.url) video.poster = img.url;  // ← thumbnail
  video.muted = true; video.loop = true; video.autoplay = true;
}
```
This already expects a video + poster-thumbnail pair, and it doesn't care whether `video_url`/`url` point at Twitter's CDN or a local file — a relative path just works. Same story for `stats.html`: it computes everything off `like_count`, `text`, `author_name`, `author_handle`, `bookmark_count`, all with `|| 0` / `|| ''` fallbacks. So **if TikTok items are shaped into the same field names** (caption → `text`, creator → `author_name`/`author_handle`, video like count → `like_count`, `images: [{url: thumbnail, type: "video", video_url: local_mp4_path}]`), `index.html`, `day.html`, `categories.html`, and `stats.html` genuinely need zero code changes. That part of your plan is correct.

**The real gap — `data.js` is fully overwritten, not merged:**

I read `write_data_js` in `fetch_bookmarks.py` — there's no read-existing-file-and-merge step anywhere in the script. Every run just writes `dates`/`tweets_by_date` from whatever it fetched, full stop. If `fetch_tiktoks.py` writes into that same `data.js`, the two scripts will clobber each other every time either one runs — whichever ran last wins, the other's data vanishes.

**Fix:** keep TikTok data in its own generated file — `data_tiktok.js` with its own globals (`TIKTOK_DATES`, `TIKTOK_VIDEOS`) — and have the HTML pages load both `<script>` tags and merge them at render time. Zero risk to the working Twitter pipeline, and you still get the unified calendar/stats view since the merge just happens one layer up.

`categories.js` is safer to actually share as one file — `categorize_bookmarks.py`'s reconcile mode does read-existing → classify-only-new → merge-back → write, which is collision-safe by design. `categorize_tiktoks.py` following the same pattern (reading both `data.js` and `data_tiktok.js`) can write into the same shared `categories.js` fine.

**Other things worth flagging, roughly in priority order:**

1. **ID namespacing** — resolved, see Decision #6.
2. **No ongoing TikTok API** — resolved, see Decision #7.
3. **Caption availability** — resolved. This item assumed we'd be waiting on a TikTok personal data export before knowing what fields were available. That assumption is now stale: Decision #3's testing already confirmed `gallery-dl`'s metadata JSON includes the full caption (`desc` field) plus rich stats, author info, hashtags, etc., pulled directly from each permalink in `urls.md` — no export needed.
4. **Local media path convention** — resolved, see Decision #5.

### #3 — Download tool: gallery-dl only, not yt-dlp

**Question:** yt-dlp and gallery-dl were both tested against a real video URL (line 582 of `urls.md`, the Tigers TikTok). Both downloaded the video fine and both produced usable metadata JSON (yt-dlp's flat, gallery-dl's richer/nested — `author`, `stats`/`statsV2`, `music`, `challenges`, etc., with matching numbers). yt-dlp also writes a thumbnail out of the box (`--write-thumbnail`); gallery-dl doesn't by default. But yt-dlp doesn't reliably handle TikTok *photo* posts (multi-image slideshow posts), while gallery-dl does — confirmed against line 172 (`theroyalmercury/photo/7527110080576245006`, "mood combos"), which gallery-dl correctly pulled apart into 7 numbered images (`_01`–`_07`) plus the post's background-audio track, each with its own metadata JSON (`post_type`/`type`: `"image"` vs `"video"` distinguishes the two).

**Decision:** Use **gallery-dl exclusively** — one tool for both post types, simpler pipeline. For video posts, the missing thumbnail is recovered as a cheap extra step rather than a yt-dlp fallback: gallery-dl's own metadata JSON already contains the cover URL (`video.originCover`, same field yt-dlp uses internally) — just fetch that URL directly (plain HTTP GET, no extra tool) and save it as `<id>_thumb.jpg`. Verified working end-to-end in testing (960×540 JPEG, matches yt-dlp's thumbnail size).

**Follow-up — HEVC codec, another extra step:** after the first real live-fetch batch (8 items), videos played audio but showed no picture in Chrome. Root cause: gallery-dl just grabs the highest-bitrate URL from TikTok's `bitrateInfo`, no codec preference, and TikTok's CDN is currently serving that as HEVC — confirmed via the raw `hvc1` fourcc in the downloaded bytes, despite gallery-dl's own `codecType` metadata field claiming "h264" (that field turned out to be unreliable, not ground truth). Chrome/Firefox generally have no HEVC decoder at all; Safari on macOS does (native hardware support), so this wasn't universal, but H.264 plays everywhere so fixing at the source beats working around it per-browser. Confirmed yt-dlp isn't an escape hatch either — it hit the identical HEVC stream for this same video back in Decision #3's original test. Same "recover via a cheap extra step" pattern as the thumbnail fix: `fetch_tiktoks.py` now probes the actual codec with `ffprobe` after download and re-encodes to H.264 (`ffmpeg`, `libx264`/`aac`) only when it isn't already, wired into the main fetch loop so this is automatic for every future video, not just a one-off patch.

### #4 — Photo posts: keep background music, no thumbnail step, needs a manual slideshow

**Question:** TikTok photo posts (slideshow-style, multiple images + a looping background audio track) downloaded via gallery-dl produce N numbered images + one mp3, all sharing the same post metadata (`stats`, `author`, `desc`). Do we keep the background music? Do photo posts need the same cover-thumbnail step as videos? And how should multiple images per post actually render?

**Decision:**
- **Keep the background music** — it's part of the post as bookmarked, not a throwaway artifact.
- **No thumbnail step for photo posts** — unlike video, the first image itself already works as a static preview; no separate cover fetch needed.
- **Rendering**: extends, doesn't restructure, the existing schema. `images: [...]` already supports multiple entries — currently only ever populated with one for tweets. For a TikTok photo post it holds all N images (`type: "photo"` per entry), and a new top-level `audio_url` field holds the local path to the mp3. Frontend needs two small additions to `categories.html`/`day.html`: (1) a manual prev/next (or dot) control to page through `images` when there's more than one, mirroring the existing video autoplay/loop pattern but user-driven instead of automatic; (2) an `<audio src={audio_url} autoplay loop>` element per card when `audio_url` is present, same autoplay/loop convention already used for video. Scoped, additive — no architecture change.

**Implemented (Stage 3):** Turned out `categories.html` had a real bug on top of this, not just a design gap — it hard-capped every card to `tweet.images.slice(0, 2)`, silently dropping 4-13 images per TikTok photo post. Fixed both `categories.html` and `day.html` the same way: ≤2 images keep the exact previous layout (zero change for normal tweets), >2 images switch to single-image paging with hover-revealed prev/next buttons, an always-visible "N / total" counter, and the `<audio>` element with the same hover-to-unmute convention already used for video (avoids multiple cards' background music autoplaying over each other, since `categories.html` shows 2 cards on screen at once). Verified live in both pages against real multi-image TikTok posts (15-image and two 6-image posts).

### #5 — Storage layout: flat, ID-keyed folders, not per-URL/per-creator nesting

**Question:** With ~1200 URLs each producing its own set of files (mp4/mp3/jpg/json), what's the actual on-disk layout? gallery-dl's default behavior nests output per-creator (as seen in the existing `gallery-dl/tiktok/cecireadsstein` folder from earlier testing), which doesn't scale to browsing or lookup at this volume. And to restate Decision #1: the ~20-30GB of media has to live *somewhere* local — that decision was about avoiding TikTok's expiring CDN URLs as the source of truth, not about avoiding storage entirely. "Reference by relative path" means `data_tiktok.js` stores paths like `media/tiktok/<id>/<id>.mp4` rather than absolute paths, so the app stays portable if the whole `ClaudeBookmarks` folder moves; "permalink kept as citation" means the original `tiktok.com/@user/video/...` URL is stored in a separate `source_url` field purely for reference/click-through, never for playback.

**Decision:** Flat directory keyed by TikTok post ID, one subfolder per post — no creator or date nesting:

```
media/tiktok/<id>/
  <id>.mp4          (video posts only)
  <id>_thumb.jpg    (video posts only — fetched via Decision #3's extra step)
  <id>_01.jpg ... _NN.jpg   (photo posts only)
  <id>.mp3          (photo posts only — background audio, per Decision #4)
  <id>.json         (raw gallery-dl metadata, kept for reference/reprocessing)
```

ID-keyed matches how `data_tiktok.js` looks items up (same ID space used for dedup/reconcile), avoids collisions that creator- or date-based nesting would risk, and stays flat enough to `ls`/grep at scale.

**Correction caught during `fetch_tiktoks.py` implementation:** `media/tiktok/<id>/...` is relative to the `ClaudeBookmarks` project root, not to `TikTokDownloader/` where the script and `urls.md` actually live. The script's first draft got this wrong — it derived `MEDIA_DIR`/`DATA_TIKTOK_JS` from its own folder (`Path(__file__).parent`), which would have put `data_tiktok.js` and all downloaded media one level too deep. `index.html`/`day.html`/etc. live at the project root and resolve `<script src="...">` and every path stored inside it against *their own* location, same as `data.js` — so `data_tiktok.js` and `media/` both have to sit at the root too. Fixed before any real download ran: `PROJECT_ROOT = Path(__file__).parent.parent` in `fetch_tiktoks.py`, only `urls.md` stays resolved against the script's own folder.

### #6 — ID namespacing: prefix TikTok IDs at write time, leave tweet IDs untouched

**Question:** Tweet IDs and TikTok post IDs are different spaces — both happen to be large numeric strings, so a literal collision is astronomically unlikely, but the reconcile "already classified" set (shared across `categorize_bookmarks.py`/`categorize_tiktoks.py`) and `categories.html`'s drag-and-drop/localStorage keys need a real correctness guarantee, not just low odds. How do we namespace this without breaking the working Twitter side?

**Decision:** Apply a `tt_` prefix to the `id` field **only** when `fetch_tiktoks.py` writes `data_tiktok.js` — e.g. `id: f"tt_{raw_numeric_id}"`. Twitter's existing tweet IDs are left exactly as they are (no `tw_` retrofit): touching them would invalidate every existing `categories.js` entry and every user's localStorage "seen" snapshot for zero added safety, since one-sided prefixing already guarantees uniqueness (Twitter snowflake IDs are plain digits and will never start with `tt_`).

Local media paths and filenames (Decision #5) keep using the **raw**, unprefixed numeric ID — the prefix applies only to the identity field the app reads (`.id`), not to files on disk. Because `categories.html`/`day.html`/etc. already treat `.id` as an opaque string wherever they use it for dedup, drag-and-drop, or localStorage keys, **no frontend code changes are required** — the fix is entirely inside `fetch_tiktoks.py`'s data-shaping step.

### #7 — Processing cadence: small manual batches, not a bulk run; manual `urls.md` additions going forward

**Question:** With no ongoing TikTok API (this is a one-time backfill, not a poller — see item 2 above) and ~590 URLs queued in `urls.md`, how should `fetch_tiktoks.py` actually get run? A single pass over the whole backlog risks getting rate-limited/blocked by hammering `gallery-dl` against TikTok 590 times in a row, and would surface every edge case (dead links, private/deleted posts, unusual post shapes) all at once mid-run instead of incrementally. Separately: once this backfill is done, how do newly-bookmarked TikToks get captured going forward, since there's no API to poll?

**Decision:**
- **Batches, not bulk**: process roughly 10-20 TikToks/day over the next several days rather than one run against the full backlog. Lower rate-limit risk by construction, and lets edge cases get shaken out incrementally while the pipeline is still new, instead of needing heavy retry/backoff infrastructure built up front for a single big run.
- **Ongoing capture = manual**: new TikToks get added to `urls.md` by hand as they're bookmarked, same as today. No better mechanism (periodic export, browser scraping, etc.) is being built right now — this stays the capture method until/unless a real need for something more automated shows up.

### #8 — index.html was single-year-only; added real year navigation before writing more TikTok data

**Question:** `urls.md`'s TikTok backlog spans back to ~2022-2023, well before this project existed. Would those older items actually be reachable through the app once `data_tiktok.js` existed? Checking `index.html` revealed `const YEAR = 2026` hardcoded at module scope, with `changeMonth()` clamping `currentMonth` to `[0,11]` and never touching year — so the calendar was not just defaulting to 2026, it was physically incapable of ever showing another year without editing source and reloading. `categories.html` and `stats.html` weren't affected (category drawers aren't calendar-based; `stats.html` reads a `?weekStart=` param with no year check), but the calendar — the primary way into `day.html` — was the one real chokepoint.

**Decision:** Fix `index.html` before writing any more TikTok integration code, since shipping a backfill mostly invisible in the main view would be a worse outcome than a short pause. Turned out to be a small, contained change (not a rewrite): `buildMonthCard(year, monthIndex)` already took `year` as a parameter and never hardcoded it internally, so the only edits needed were replacing the `YEAR` constant with a mutable `currentYear`, and adding month-rollover math to `changeMonth()`:

```js
function changeMonth(delta) {
  currentMonth += delta;
  if (currentMonth > 11) { currentMonth = 0; currentYear++; }
  else if (currentMonth < 0) { currentMonth = 11; currentYear--; }
  render();
}
```

Also simplified the initial view to always default to today's actual year/month (`today.getFullYear()`/`today.getMonth()`), removing the old `(today.getFullYear() === YEAR) ? ... : 0` conditional that only worked because YEAR happened to match the current year. Verified by serving the folder over a temporary local HTTP server (browser automation can't reach `file://` pages directly) and clicking through August 2026 → January 2026 → December 2025 → back to January 2026 — rolled correctly in both directions.

**Follow-up — year-jump buttons:** month-by-month was still the only way to move between years (e.g. 12+ clicks to go from 2026 back to 2023), so added a second pair of nav buttons (`«`/`»`) that call a new `changeYear(delta)` — increments/decrements `currentYear` only, `currentMonth` untouched, so you land on the same month one year over/under instead of walking through all twelve. Reused the existing `.month-nav button` CSS as-is, no new styles needed. Verified: 3 clicks on `«` from August 2026 landed on August 2023 exactly, month held fixed throughout.

### #9 — TikTok items don't get a real added_at; fall back to created_at like pre-existing tweets

**Question:** After building recency sort (`added_at` if present, else `created_at`), `fetch_tiktoks.py` stamped every TikTok with wall-clock time at fetch. That's fine for `fetch_bookmarks.py`'s use case (a live weekly poll, where "when the script saw it" tracks real bookmark time closely) but breaks down for TikTok's one-time backfill through `urls.md`: batches get processed in whatever order they happen to run, not in `urls.md`'s own rough chronological structure (oldest sections near the top, newest — the "2026" section — at the bottom). Caught in practice: the "2026" section was fetched *first*, as the initial test batch, so those 8 items — the chronologically newest content in the whole backlog — got the *earliest* `added_at` timestamp of the entire eventual backfill. Every subsequent batch (working top-to-bottom through older sections) would get a *later* stamp, inverting the actual chronology exactly where it matters most.

**Decision:** Don't stamp `added_at` for TikToks at all — rely on the existing fallback to `created_at` (the real post date, already captured accurately from metadata), same treatment as tweets that predate the `added_at` field. Simpler than deriving a synthetic recency signal from `urls.md` position (the more "correct" fix, but needed an interpolation scheme and still wouldn't be exact), and per-item accuracy loss (bookmark time vs. post time can differ by days/weeks) is an acceptable tradeoff for not having batch-order artifacts silently invert the sort. Removed the stamp from `fetch_tiktoks.py`'s `build_item()` going forward, and retroactively stripped `added_at` from the 8 already-fetched items in both `data_tiktok.js` and their copies in `categories.js`, then re-sorted — verified they now rank by their real `created_at` (Dec 30-31, 2025) among the rest of their category instead of being artificially pinned to the top.

## Known Limitations

### Some videos download with no audio track — TikTok serves them as separate DASH streams

**What happens:** For a minority of videos (2 of 28 fetched so far, ~7%), the downloaded `.mp4` has a video stream but zero audio streams — confirmed via `ffprobe`. In `categories.html`/`day.html` these play silently even after hovering (there's no audio track to unmute). First noticed on two videos in the "Relationship" category (`@sedoxo`, `@catspanti`).

**Root cause:** for these specific videos, TikTok doesn't offer a single combined (progressive-download) audio+video file — only DASH-split components (separate video-only and audio-only streams, each with their own signed CDN URL). `gallery-dl`'s TikTok extractor (`_extract_video_urls`) sorts all available `bitrateInfo` variants purely by resolution and picks the highest one — for these two, that's the video-only DASH component (`adapt_lowest_1080_1`-style), not the combined stream. gallery-dl has no config option to prefer a combined/non-DASH variant, and its audio-fetch logic (`_extract_audio`) only ever runs for photo posts, never video posts.

**Confirmed this isn't a quick fix:**
- Directly fetching the separate audio DASH stream's URL (present in the metadata JSON's `video.bitrateAudioInfo`) → `403 Access Denied` from TikTok's Akamai CDN. These signed URLs need session/cookie auth that only a downloader's own internal HTTP client provides, not a bare request.
- Directly fetching the alternate combined-stream URL (`normal_540_0` in `bitrateInfo`, identifiable by having ~2.5x the file size of other same-resolution entries — the telltale sign of included audio) → also `403 Access Denied`, same reason.
- Tried `yt-dlp` as a fallback on the theory that its DASH-merging (normally strong, e.g. on YouTube) might handle this better — it picked the **byte-identical** video-only asset gallery-dl did (verified: same file size, same missing audio). Both tools have the identical gap for TikTok specifically, so this isn't a "switch tools" fix.

**Status:** accepted as a known limitation, not fixed. Would need real DASH-manifest-aware downloading + muxing (neither `gallery-dl` nor `yt-dlp` implements this for TikTok) or reverse-engineering TikTok's CDN session auth well enough to fetch the alternate streams directly — meaningfully more work than the rate at which this occurs currently justifies. If it turns out to affect a lot more of the backlog once the full `urls.md` finishes processing, revisit.

## Arch

Here's the architecture, grouped by role:

### Data pipeline (Python — runs offline, produces static JS files)

**`fetch_bookmarks.py`** (487 lines) — pulls your bookmarks from Twitter/X.
- Handles the OAuth dance: `generate_pkce_pair`, `run_oauth_flow`, `CallbackHandler` (spins up a local HTTP server to catch the redirect), `load_tokens`/`save_tokens`/`refresh_tokens` → persisted to `tokens.json`
- `fetch_all_bookmarks` — paginates the Twitter API v2 bookmarks endpoint, `since` cutoff controls the fetch window (default last 7 days)
- `group_by_date` — buckets tweets by local calendar date (handles the UTC→local timezone conversion noted in `CLAUDE.md`)
- `write_data_js` — serializes everything into `data.js` as two globals: `BOOKMARK_DATES` (date → count) and `BOOKMARK_TWEETS` (date → array of tweet objects)

**`categorize_bookmarks.py`** (292 lines) — the categorization layer, runs *after* `fetch_bookmarks.py`.
- Reads `data.js`, sends tweet batches to Claude Haiku to classify into named categories
- `load_existing_categories` — parses current `categories.js` via regex to get already-assigned tweet IDs (reconcile mode)
- `build_prompt` vs `build_prompt_reconcile` — reconcile mode passes existing category names to the prompt so Claude reuses them instead of inventing duplicates
- `classify_batch` — routes to the right prompt, calls the API
- Writes `categories.js` (`BOOKMARK_CATEGORIES`: category name → array of tweet objects), backs up the old one to `categories_old.js` first

### Generated data (not hand-edited)

- **`data.js`** (3590 lines) — the tweet database, written by `fetch_bookmarks.py`
- **`categories.js`** (4103 lines) — the categorized view, written by `categorize_bookmarks.py`

### Frontend (static HTML/CSS/JS, opened directly from Finder as `file://` — no server, no build step)

- **`index.html`** — the main view: a 3D "desk calendar," one month at a time. Loads `data.js` only.
- **`day.html`** — drill-down from a calendar day: stacked pages, one tweet per page. Loads `data.js` only.
- **`categories.html`** — the "file cabinet" UI: drawers per category, drag-and-drop to refile tweets between categories or merge drawers, rename/add categories, a "Save categories.js" button that downloads the edited state as a replacement file. Loads `categories.js` only (degrades gracefully if absent).
- **`stats.html`** — weekly stats: 4 charts + "best tweet of the week." Loads both `data.js` and `categories.js`.
- **`style.css`** (1594 lines) — every page's styling, shared. Defines the "wood desk" visual system (gradients, card paper color, accent red, gold separators) as CSS variables, plus per-page overrides via `body.{page}-view` classes.

### Config / secrets

- **`.env`** — `TWITTER_CLIENT_ID`, `TWITTER_CLIENT_SECRET`, `ANTHROPIC_API_KEY`
- **`tokens.json`** — OAuth access/refresh tokens, managed automatically by `fetch_bookmarks.py`

**The core constraint driving all of this**: everything must run as a local file with no server and no build tooling — `fetch()` is blocked on `file://`, so all data has to be injected as `<script src="data.js">` globals rather than fetched at runtime. That's the thing to keep front-of-mind when we design how TikTok data slots in.

## Architecture Diagrams

```
┌─────────────────────────────────────────────────────────────────────┐
│  ONE-TIME SETUP                                                       │
└─────────────────────────────────────────────────────────────────────┘

   .env (TWITTER_CLIENT_ID/SECRET, ANTHROPIC_API_KEY)
        │
        ▼
   fetch_bookmarks.py  ──first run only──▶  run_oauth_flow()
        │                                    → opens browser, PKCE flow,
        │                                    → CallbackHandler catches
        │                                      redirect on localhost
        │                                          │
        │                                          ▼
        │                                     tokens.json  (access + refresh tokens)
        │                                          │
        └──────────────◀── every subsequent run reads/refreshes ──┘


┌─────────────────────────────────────────────────────────────────────┐
│  DATA REFRESH  (run periodically, e.g. weekly)                        │
└─────────────────────────────────────────────────────────────────────┘

   tokens.json ──▶ fetch_bookmarks.py
                        │
                        │  fetch_all_bookmarks()  → Twitter API v2
                        │  group_by_date()        → bucket by local date
                        │  write_data_js()
                        ▼
                    data.js
                    { BOOKMARK_DATES, BOOKMARK_TWEETS }
                        │
                        ▼
                 categorize_bookmarks.py
                        │
                        │  load_existing_categories()  ← categories.js (old)
                        │  build_prompt_reconcile()    → Claude Haiku API
                        │  classify_batch()               (ANTHROPIC_API_KEY)
                        │
                        ├──▶ categories_old.js   (backup of previous version)
                        ▼
                   categories.js
                   { BOOKMARK_CATEGORIES }


┌─────────────────────────────────────────────────────────────────────┐
│  VIEWING  (opened directly from Finder, file:// — no server)          │
└─────────────────────────────────────────────────────────────────────┘

 SOURCES                    PAGES                                        RESULT

 data.js ────────┬────────▶ [ index.html ] ──(click a day)──▶ [ day.html ]
                  │            month calendar                    one tweet/page
                  │
                  └────────▶ [ stats.html ] ◀────────────────────────────┐
                  ┌────────▶   4 charts +                                │
                  │            best tweet                                │
                  │                                                      │
 categories.js ───┴────────▶ [ categories.html ] ──▶ [Save categories.js] ──▶ new categories.js
                                file-cabinet UI,        button (download          downloaded
                                drag/drop refile,        edited state)                 │
                                rename, merge                                          │
                                     ▲                                                 │
                                     └───────── you manually replace the file ─────────┘
                                                    (mutations become permanent,
                                                     loops back as the new source)
```

Reading it top to bottom: OAuth happens once → `fetch_bookmarks.py` runs on a cadence to pull new tweets into `data.js` → `categorize_bookmarks.py` runs after, reconciling new tweets into `categories.js` (never re-classifying old ones) → the four HTML pages are pure readers of those two generated files, with `categories.html` being the one exception that lets you mutate state in-browser and manually re-save it.

The TikTok pipeline will need to slot a parallel path into the "DATA REFRESH" block (its own fetch → its own categorize, or merged into the same `data.js`/`categories.js` per your "unified" decision) — that's the next thing to design.
