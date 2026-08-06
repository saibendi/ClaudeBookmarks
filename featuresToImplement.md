# Features To Implement

Not yet implemented — planning/backlog only.

## 1. Reconcile removed/unbookmarked tweets within the fetch window

`fetch_bookmarks.py`'s merge (`merge_tweets_by_date`) is currently purely additive — it never removes a tweet from `data.js`, even if it's been unbookmarked on Twitter and no longer appears in the fresh API response.

**Two cases:**
- **Within the fetch window** (e.g. last 7/30 days): fixable — the fresh API response is authoritative for that date range, so any tweet previously stored in that range but absent from the new fetch can be safely pruned.
- **Outside the fetch window**: not fixable without a full `--all` resync — the script never re-queries that date range, so there's no way to detect a removal there short of re-fetching everything.

**Decision:** running with a wide-enough window (e.g. `--days 30`) on a weekly cadence covers realistic usage — unbookmarking something older than a month is not a real scenario here. So implementing window-reconciliation (case 1) is sufficient; no need to also solve the outside-window case for now.
