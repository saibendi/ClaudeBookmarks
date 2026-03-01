#!/usr/bin/env python3
"""
fetch_bookmarks.py — Fetch Twitter/X bookmarks and write data.js for the calendar UI.

Usage:
    python3 fetch_bookmarks.py            # last 7 days (default)
    python3 fetch_bookmarks.py --days 30  # last 30 days
    python3 fetch_bookmarks.py --all      # every bookmark (may be many pages)

Dependencies:
    pip install requests python-dotenv

First run: opens your browser for Twitter OAuth login.
Subsequent runs: uses stored tokens (auto-refreshed).
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DATA_JS      = SCRIPT_DIR / "data.js"
TOKENS_FILE  = SCRIPT_DIR / "tokens.json"
ENV_FILE     = SCRIPT_DIR / ".env"

# ── Twitter API endpoints ─────────────────────────────────────────────────────
AUTH_URL      = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL     = "https://api.twitter.com/2/oauth2/token"
ME_URL        = "https://api.twitter.com/2/users/me"
BOOKMARKS_URL = "https://api.twitter.com/2/users/{user_id}/bookmarks"

REDIRECT_URI  = "http://localhost:8080/callback"
SCOPES        = "bookmark.read tweet.read users.read offline.access"

# ── PKCE helpers ──────────────────────────────────────────────────────────────

def generate_pkce_pair():
    """Return (code_verifier, code_challenge) for PKCE."""
    verifier  = secrets.token_urlsafe(64)[:128]
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ── OAuth callback server ─────────────────────────────────────────────────────

class CallbackHandler(BaseHTTPRequestHandler):
    """Tiny HTTP handler that captures ?code= from the OAuth redirect."""

    auth_code = None
    auth_error = None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)

        if "error" in params:
            CallbackHandler.auth_error = params["error"][0]
            body = b"<html><body><h2>Auth failed.</h2><p>You can close this tab.</p></body></html>"
        elif "code" in params:
            CallbackHandler.auth_code = params["code"][0]
            body = b"<html><body><h2>Authorized!</h2><p>You can close this tab and return to the terminal.</p></body></html>"
        else:
            body = b"<html><body><h2>Unexpected response.</h2></body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # suppress access log noise


def wait_for_callback(timeout=300):
    """Spin up localhost:8080, wait for OAuth callback, return auth code."""
    server = HTTPServer(("localhost", 8080), CallbackHandler)
    server.timeout = 1  # poll every second

    deadline = time.time() + timeout
    while time.time() < deadline:
        server.handle_request()
        if CallbackHandler.auth_code or CallbackHandler.auth_error:
            break

    server.server_close()

    if CallbackHandler.auth_error:
        raise RuntimeError(f"OAuth error: {CallbackHandler.auth_error}")
    if not CallbackHandler.auth_code:
        raise RuntimeError("Timed out waiting for OAuth callback.")
    return CallbackHandler.auth_code


# ── Full OAuth 2.0 PKCE flow ──────────────────────────────────────────────────

def run_oauth_flow(client_id, client_secret):
    """Interactive PKCE flow → returns token dict."""
    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "response_type":         "code",
        "client_id":             client_id,
        "redirect_uri":          REDIRECT_URI,
        "scope":                 SCOPES,
        "state":                 state,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
    }

    auth_url = f"{AUTH_URL}?{urlencode(params)}"
    print(f"\nOpen this URL in an incognito window to log in:\n\n  {auth_url}\n")

    print("Waiting for OAuth callback on http://localhost:8080/callback …")
    code = wait_for_callback()

    # Exchange code for tokens
    resp = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  REDIRECT_URI,
            "code_verifier": verifier,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["obtained_at"] = int(time.time())
    return tokens


# ── Token management ──────────────────────────────────────────────────────────

def load_tokens():
    if TOKENS_FILE.exists():
        with open(TOKENS_FILE) as f:
            return json.load(f)
    return None


def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"Tokens saved to {TOKENS_FILE}")


def refresh_tokens(client_id, client_secret, refresh_token):
    """Use refresh_token to obtain a new access_token."""
    resp = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    resp.raise_for_status()
    tokens = resp.json()
    tokens["obtained_at"] = int(time.time())
    return tokens


def get_valid_access_token(client_id, client_secret):
    """Return a valid access_token, refreshing or re-authorizing as needed."""
    tokens = load_tokens()

    if tokens is None:
        print("No tokens found — starting OAuth flow.")
        tokens = run_oauth_flow(client_id, client_secret)
        save_tokens(tokens)
        return tokens["access_token"]

    # Check expiry (leave 60 s buffer)
    obtained_at  = tokens.get("obtained_at", 0)
    expires_in   = tokens.get("expires_in", 7200)
    expires_at   = obtained_at + expires_in - 60

    if time.time() < expires_at:
        return tokens["access_token"]

    # Try to refresh
    refresh_token = tokens.get("refresh_token")
    if refresh_token:
        print("Access token expired — refreshing…")
        try:
            tokens = refresh_tokens(client_id, client_secret, refresh_token)
            save_tokens(tokens)
            return tokens["access_token"]
        except requests.HTTPError as exc:
            print(f"Refresh failed ({exc}) — re-running OAuth flow.")

    # Fallback: full re-auth
    tokens = run_oauth_flow(client_id, client_secret)
    save_tokens(tokens)
    return tokens["access_token"]


# ── Twitter API calls ─────────────────────────────────────────────────────────

def check_api_error(resp):
    """Check for known Twitter API errors and print a clear message before raising."""
    if resp.status_code == 403:
        try:
            body = resp.json()
        except Exception:
            body = {}
        err_type  = body.get("type", "")
        err_title = body.get("title", "")
        err_detail = body.get("detail", "")
        if "usage-capped" in err_type or "UsageCapExceeded" in err_title:
            print("\nERROR: You've exceeded your X API usage cap.")
            print("You've run out of API credits in your X developer console.")
            print("Visit https://developer.twitter.com to check your plan and usage.")
            sys.exit(1)


def get_user_id(access_token):
    resp = requests.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"})
    check_api_error(resp)
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def fetch_all_bookmarks(access_token, user_id, since=None):
    """
    Return list of tweet dicts with author info, paginating until exhausted
    or (if since is set) until all tweets on a page predate the cutoff.

    Rate limiting:
    - Reactive: on 429, sleeps until x-rate-limit-reset then retries.
    - Proactive: prints a warning when x-rate-limit-remaining drops below 10.
    """
    url = BOOKMARKS_URL.format(user_id=user_id)
    params = {
        "tweet.fields": "id,text,created_at,author_id,public_metrics,note_tweet,attachments",
        "expansions":   "author_id,attachments.media_keys",
        "user.fields":  "name,username",
        "media.fields": "url,preview_image_url,type,width,height,variants",
        "max_results":  100,
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    all_tweets   = []
    users_by_id  = {}
    media_by_key = {}
    page         = 0

    while True:
        page += 1
        resp = requests.get(url, params=params, headers=headers)

        # ── Proactive: warn when limit is almost exhausted ────────────────────
        remaining = resp.headers.get("x-rate-limit-remaining")
        limit     = resp.headers.get("x-rate-limit-limit")
        if remaining is not None and limit is not None:
            remaining_int = int(remaining)
            if remaining_int < 10:
                reset_ts = int(resp.headers.get("x-rate-limit-reset", time.time() + 900))
                resets_in = max(reset_ts - int(time.time()), 0)
                print(f"  ⚠ Rate limit low: {remaining}/{limit} requests remaining "
                      f"(resets in {resets_in}s)")

        # ── Reactive: back off on 429 ─────────────────────────────────────────
        if resp.status_code == 429:
            reset = int(resp.headers.get("x-rate-limit-reset", time.time() + 60))
            wait  = max(reset - int(time.time()), 1)
            print(f"  Rate limited — waiting {wait}s…")
            time.sleep(wait)
            continue

        check_api_error(resp)
        resp.raise_for_status()
        body = resp.json()

        # Collect users and media from includes
        for u in body.get("includes", {}).get("users", []):
            users_by_id[u["id"]] = u
        for m in body.get("includes", {}).get("media", []):
            media_by_key[m["media_key"]] = m

        data = body.get("data", [])

        # ── Early stop: filter to tweets within the date window ───────────────
        if since is not None:
            in_window = []
            for t in data:
                raw = t.get("created_at", "")
                if not raw:
                    continue
                try:
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if dt >= since:
                    in_window.append(t)

            all_tweets.extend(in_window)
            cutoff_str = since.strftime("%Y-%m-%d")
            print(f"  Page {page}: {len(in_window)}/{len(data)} tweets in window "
                  f"(since {cutoff_str}, total: {len(all_tweets)})")

            # Bookmarks are newest-first; if any tweet on this page is within
            # the window we need to keep paging — stop only when ALL are outside.
            if len(in_window) == 0:
                print(f"  All tweets on page {page} predate {cutoff_str} — stopping.")
                break
        else:
            all_tweets.extend(data)
            print(f"  Page {page}: fetched {len(data)} tweets (total: {len(all_tweets)})")

        next_token = body.get("meta", {}).get("next_token")
        if not next_token:
            break
        params["pagination_token"] = next_token

    return all_tweets, users_by_id, media_by_key


# ── Data grouping ─────────────────────────────────────────────────────────────

def group_by_date(tweets, users_by_id, media_by_key):
    """
    Returns:
        dates  = { "YYYY-MM-DD": count }
        tweets_by_date = { "YYYY-MM-DD": [ {id, text, author_name, author_handle,
                                             created_at, url, like_count,
                                             bookmark_count, images} ] }
    """
    dates          = {}
    tweets_by_date = {}

    for t in tweets:
        # created_at is ISO 8601 UTC, e.g. "2026-01-08T09:14:00.000Z"
        created_raw = t.get("created_at", "")
        if not created_raw:
            continue

        try:
            dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except ValueError:
            continue

        date_str = dt.astimezone().strftime("%Y-%m-%d")

        author_id = t.get("author_id", "")
        user      = users_by_id.get(author_id, {})
        metrics   = t.get("public_metrics", {})

        # Use note_tweet.text for long-form posts, fallback to text
        full_text = (t.get("note_tweet") or {}).get("text") or t.get("text", "")

        # Resolve media attachments
        images = []
        for key in t.get("attachments", {}).get("media_keys", []):
            m = media_by_key.get(key, {})
            mtype = m.get("type", "")
            if mtype == "photo":
                images.append({"url": m.get("url", ""), "type": "photo"})
            elif mtype in ("video", "animated_gif"):
                preview = m.get("preview_image_url", "")
                # Pick highest-bitrate MP4 variant for in-page playback
                mp4s = [v for v in m.get("variants", [])
                        if v.get("content_type") == "video/mp4"]
                video_url = ""
                if mp4s:
                    video_url = max(mp4s, key=lambda v: v.get("bit_rate", 0)).get("url", "")
                if preview or video_url:
                    images.append({"url": preview, "type": mtype, "video_url": video_url})

        tweet_obj = {
            "id":             t.get("id", ""),
            "text":           full_text,
            "author_name":    user.get("name", "Unknown"),
            "author_handle":  f"@{user.get('username', 'unknown')}",
            "created_at":     created_raw,
            "url":            f"https://twitter.com/i/web/status/{t.get('id', '')}",
            "like_count":     metrics.get("like_count", 0),
            "bookmark_count": metrics.get("bookmark_count", 0),
            "images":         images,
        }

        tweets_by_date.setdefault(date_str, []).append(tweet_obj)
        dates[date_str] = dates.get(date_str, 0) + 1

    return dates, tweets_by_date


# ── Write data.js ─────────────────────────────────────────────────────────────

def write_data_js(dates, tweets_by_date):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = sum(dates.values())

    content = f"""// Auto-generated by fetch_bookmarks.py — do not edit manually.
// Last updated: {now}  |  Total bookmarks: {total}
// Run: python3 fetch_bookmarks.py
window.BOOKMARK_DATES  = {json.dumps(dates,          indent=2, ensure_ascii=False)};
window.BOOKMARK_TWEETS = {json.dumps(tweets_by_date, indent=2, ensure_ascii=False)};
"""
    DATA_JS.write_text(content, encoding="utf-8")
    print(f"\nWrote {DATA_JS}  ({total} bookmarks across {len(dates)} days)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch Twitter bookmarks → data.js")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--days", type=int, default=7, metavar="N",
        help="Only fetch bookmarks from the last N days (default: 7)"
    )
    group.add_argument(
        "--all", dest="fetch_all", action="store_true",
        help="Fetch every bookmark (no date limit; may be many pages)"
    )
    args = parser.parse_args()

    # Load credentials
    load_dotenv(ENV_FILE)
    client_id     = os.getenv("TWITTER_CLIENT_ID")
    client_secret = os.getenv("TWITTER_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("ERROR: TWITTER_CLIENT_ID and TWITTER_CLIENT_SECRET must be set in .env")
        print("Copy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    # Resolve the since cutoff
    if args.fetch_all:
        since = None
        print("Twitter Bookmark Fetcher  (fetching ALL bookmarks)")
    else:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)
        print(f"Twitter Bookmark Fetcher  (last {args.days} days, since {since.strftime('%Y-%m-%d')})")
    print("=" * 40)

    # Auth
    access_token = get_valid_access_token(client_id, client_secret)
    print("Authenticated.")

    # Get user ID
    user_id = get_user_id(access_token)
    print(f"User ID: {user_id}")

    # Fetch bookmarks
    print("\nFetching bookmarks…")
    tweets, users_by_id, media_by_key = fetch_all_bookmarks(access_token, user_id, since=since)
    print(f"Total tweets fetched: {len(tweets)}")

    # Group
    dates, tweets_by_date = group_by_date(tweets, users_by_id, media_by_key)

    # Write
    write_data_js(dates, tweets_by_date)
    print("\nDone! Open index.html in your browser to see your bookmarks.")


if __name__ == "__main__":
    main()
