#!/usr/bin/env python3
"""
categorize_bookmarks.py — Reads data.js, classifies tweets via Claude Haiku,
writes categories.js with window.BOOKMARK_CATEGORIES.

Usage:
    python3 categorize_bookmarks.py

Requirements:
    pip install anthropic python-dotenv
    Add ANTHROPIC_API_KEY=sk-ant-... to .env
"""

import json
import os
import re
import sys

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed.")
    print("Run: pip install anthropic")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional; key may already be in environment


# ── Load API key ──────────────────────────────────────────────────────────────

api_key = os.environ.get("ANTHROPIC_API_KEY", "")
if not api_key:
    print("ERROR: ANTHROPIC_API_KEY not set.")
    print("Add the following line to your .env file:")
    print("  ANTHROPIC_API_KEY=sk-ant-...")
    sys.exit(1)


# ── Parse data.js ─────────────────────────────────────────────────────────────

DATA_JS = os.path.join(os.path.dirname(__file__), "data.js")
if not os.path.exists(DATA_JS):
    print("ERROR: data.js not found.")
    print("Run fetch_bookmarks.py first to generate data.js.")
    sys.exit(1)

with open(DATA_JS, "r", encoding="utf-8") as f:
    raw = f.read()

# Extract window.BOOKMARK_TWEETS = { ... };
match = re.search(r"window\.BOOKMARK_TWEETS\s*=\s*(\{[\s\S]*?\});", raw)
if not match:
    print("ERROR: Could not find window.BOOKMARK_TWEETS in data.js.")
    sys.exit(1)

try:
    tweets_by_date = json.loads(match.group(1))
except json.JSONDecodeError as e:
    print(f"ERROR: Failed to parse BOOKMARK_TWEETS JSON: {e}")
    sys.exit(1)

# Flatten all tweets, adding _date field
all_tweets = []
for date_str, tweet_list in tweets_by_date.items():
    for tweet in tweet_list:
        t = dict(tweet)
        t["_date"] = date_str
        all_tweets.append(t)

if not all_tweets:
    print("No tweets found in data.js. Run fetch_bookmarks.py to populate it.")
    sys.exit(0)

print(f"Found {len(all_tweets)} tweets across {len(tweets_by_date)} days.")


# ── Load existing categories (for reconcile mode) ─────────────────────────────

def load_existing_categories():
    """Load categories.js and return (cats_dict, set_of_assigned_ids).
    Returns (None, set()) if the file doesn't exist or can't be parsed."""
    out_js = os.path.join(os.path.dirname(__file__), "categories.js")
    if not os.path.exists(out_js):
        return None, set()
    try:
        with open(out_js, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r"window\.BOOKMARK_CATEGORIES\s*=\s*(\{[\s\S]*\});", content)
        if not m:
            return None, set()
        cats = json.loads(m.group(1))
        assigned_ids = {t["id"] for tweets in cats.values() for t in tweets}
        return cats, assigned_ids
    except Exception:
        return None, set()


# ── Build prompt ──────────────────────────────────────────────────────────────

def build_prompt(tweet_batch):
    """Build the classification prompt for a batch of tweets."""
    tweet_summaries = []
    for i, t in enumerate(tweet_batch):
        text = t.get("text", "")[:300]  # truncate long tweets
        tweet_summaries.append(f'{{"id":"{t["id"]}","text":{json.dumps(text)}}}')

    tweets_json = "[\n" + ",\n".join(tweet_summaries) + "\n]"

    return f"""You are classifying Twitter bookmarks into topic categories.

Here are the tweets to classify:
{tweets_json}

Instructions:
1. Invent 5–8 concise category names that cover these tweets (e.g. "AI & Technology", "Finance & Investing", "Productivity", "Design & Creativity", "Science", "Politics & Society", "Health & Fitness", "Humor & Culture").
2. Assign exactly one category to each tweet.
3. Use consistent category names across all tweets.
4. Return ONLY a JSON array, no explanation, no markdown, no code fences. Format:
[{{"id":"<tweet_id>","category":"<category_name>"}},...]"""


def build_prompt_reconcile(tweet_batch, existing_cat_names):
    """Prompt variant that reuses existing category names for new tweets."""
    tweet_summaries = []
    for t in tweet_batch:
        text = t.get("text", "")[:300]
        tweet_summaries.append(f'{{"id":"{t["id"]}","text":{json.dumps(text)}}}')
    tweets_json = "[\n" + ",\n".join(tweet_summaries) + "\n]"
    cats_list = ", ".join(f'"{c}"' for c in existing_cat_names)

    return f"""You are classifying Twitter bookmarks into topic categories.

Existing categories: [{cats_list}]

Here are the new tweets to classify:
{tweets_json}

Instructions:
1. Assign each tweet to one of the existing categories if it fits well.
2. Create a new category name ONLY if none of the existing ones is a good fit.
3. Use the existing category names EXACTLY as given (same spelling and capitalisation).
4. Assign exactly one category to each tweet.
5. Return ONLY a JSON array, no explanation, no markdown, no code fences. Format:
[{{"id":"<tweet_id>","category":"<category_name>"}},...]\
"""


# ── Call Claude API ────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=api_key)
MODEL = "claude-haiku-4-5-20251001"

def classify_batch(tweet_batch, existing_cat_names=None):
    """Send a batch of tweets to Claude and return list of {id, category} dicts."""
    if existing_cat_names:
        prompt = build_prompt_reconcile(tweet_batch, existing_cat_names)
    else:
        prompt = build_prompt(tweet_batch)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}]
        )
    except anthropic.APIError as e:
        print(f"ERROR: Claude API error: {e}")
        sys.exit(1)

    content = response.content[0].text.strip()

    # Strip markdown code fences if present
    content = re.sub(r"^```(?:json)?\n?", "", content)
    content = re.sub(r"\n?```$", "", content)
    content = content.strip()

    try:
        result = json.loads(content)
        if not isinstance(result, list):
            raise ValueError("Expected a JSON array")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        print(f"ERROR: Claude returned non-JSON response.")
        print(f"Raw response:\n{content}")
        print(f"\nParse error: {e}")
        sys.exit(1)


# ── Load existing categories (reconcile mode) ─────────────────────────────────
import argparse
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--reclassify", action="store_true",
                     help="Ignore existing categories.js and reclassify everything")
_args, _ = _parser.parse_known_args()

existing_cats, assigned_ids = (None, set()) if _args.reclassify else load_existing_categories()

if existing_cats is not None:
    new_tweets = [t for t in all_tweets if t["id"] not in assigned_ids]
    if not new_tweets:
        print("All tweets already categorised — nothing new to classify.")
        print("Fetch more bookmarks first, or use --reclassify to force a full re-run.")
        sys.exit(0)
    print(f"{len(assigned_ids)} tweets already categorised; {len(new_tweets)} new to classify.")
    tweets_to_classify = new_tweets
    existing_cat_names = list(existing_cats.keys())
else:
    print("No existing categories.js — classifying all tweets from scratch.")
    tweets_to_classify = all_tweets
    existing_cat_names = None

# ── Run classification ────────────────────────────────────────────────────────
BATCH_SIZE = 100
assignments = []  # list of {id, category}

if len(tweets_to_classify) <= 150:
    print("Classifying in a single API call...")
    assignments = classify_batch(tweets_to_classify, existing_cat_names)
else:
    batches = [tweets_to_classify[i:i+BATCH_SIZE] for i in range(0, len(tweets_to_classify), BATCH_SIZE)]
    print(f"Classifying {len(tweets_to_classify)} tweets in {len(batches)} batches...")
    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{len(batches)} ({len(batch)} tweets)...")
        assignments.extend(classify_batch(batch, existing_cat_names))

print(f"Classified {len(assignments)} tweets.")


# ── Build / merge category map ────────────────────────────────────────────────

# Map tweet id → category for newly classified tweets
id_to_cat = {item["id"]: item["category"] for item in assignments if "id" in item and "category" in item}

# Map tweet id → full tweet object (all tweets from data.js, for lookup)
id_to_tweet = {t["id"]: t for t in all_tweets}

# Start from existing categories (deep copy) or an empty dict for first run
categories: dict[str, list] = {k: list(v) for k, v in existing_cats.items()} if existing_cats else {}

# Insert newly classified tweets into the correct category buckets
for tweet_id, cat in id_to_cat.items():
    tweet = id_to_tweet.get(tweet_id)
    if tweet is None:
        continue
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(tweet)

# Re-sort every category's tweets by recency descending. added_at (when we
# fetched it) if present, else created_at (when it was originally posted) —
# tweets predating the added_at field fall back to created_at automatically.
for cat in categories:
    categories[cat].sort(key=lambda t: t.get("added_at") or t.get("created_at", ""), reverse=True)

# Sort categories by tweet count descending
categories = dict(sorted(categories.items(), key=lambda x: len(x[1]), reverse=True))

print("\nCategories:")
new_cats = []
for cat, tweets in categories.items():
    is_new = existing_cats is not None and cat not in existing_cats
    if is_new:
        new_cats.append(cat)
    marker = " [NEW]" if is_new else ""
    print(f"  {cat}: {len(tweets)} tweets{marker}")

if new_cats:
    print(f"\n{len(new_cats)} new categor{'y' if len(new_cats) == 1 else 'ies'}: {', '.join(new_cats)}")
else:
    print("\nNo new categories.")


# ── Backup existing categories.js ────────────────────────────────────────────
import shutil
OUT_JS = os.path.join(os.path.dirname(__file__), "categories.js")
OLD_JS = os.path.join(os.path.dirname(__file__), "categories_old.js")
if os.path.exists(OUT_JS):
    shutil.copy2(OUT_JS, OLD_JS)
    print(f"Backed up existing categories.js → categories_old.js")


# ── Write categories.js ───────────────────────────────────────────────────────

categories_json = json.dumps(categories, ensure_ascii=False, indent=2)

with open(OUT_JS, "w", encoding="utf-8") as f:
    f.write("// Auto-generated by categorize_bookmarks.py — do not edit manually.\n")
    f.write(f"window.BOOKMARK_CATEGORIES = {categories_json};\n")

print(f"\nWrote {OUT_JS}")
print("Done! Open categories.html to browse by category.")
