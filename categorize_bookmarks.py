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


# ── Call Claude API ────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=api_key)
MODEL = "claude-haiku-4-5-20251001"

def classify_batch(tweet_batch):
    """Send a batch of tweets to Claude and return list of {id, category} dicts."""
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


# ── Run classification (batch if > 150 tweets) ────────────────────────────────

BATCH_SIZE = 100
assignments = []  # list of {id, category}

if len(all_tweets) <= 150:
    print("Classifying all tweets in a single API call...")
    assignments = classify_batch(all_tweets)
else:
    batches = [all_tweets[i:i+BATCH_SIZE] for i in range(0, len(all_tweets), BATCH_SIZE)]
    print(f"Classifying {len(all_tweets)} tweets in {len(batches)} batches...")
    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{len(batches)} ({len(batch)} tweets)...")
        assignments.extend(classify_batch(batch))

print(f"Classified {len(assignments)} tweets.")


# ── Build category map ────────────────────────────────────────────────────────

# Map tweet id → category
id_to_cat = {item["id"]: item["category"] for item in assignments if "id" in item and "category" in item}

# Map tweet id → full tweet object
id_to_tweet = {t["id"]: t for t in all_tweets}

# Group tweets by category
categories: dict[str, list] = {}
for tweet_id, cat in id_to_cat.items():
    tweet = id_to_tweet.get(tweet_id)
    if tweet is None:
        continue
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(tweet)

# Sort each category's tweets by like_count descending
for cat in categories:
    categories[cat].sort(key=lambda t: t.get("like_count", 0), reverse=True)

# Sort categories by number of tweets descending
categories = dict(sorted(categories.items(), key=lambda x: len(x[1]), reverse=True))

print("\nCategories:")
for cat, tweets in categories.items():
    print(f"  {cat}: {len(tweets)} tweets")


# ── Write categories.js ───────────────────────────────────────────────────────

OUT_JS = os.path.join(os.path.dirname(__file__), "categories.js")
categories_json = json.dumps(categories, ensure_ascii=False, indent=2)

with open(OUT_JS, "w", encoding="utf-8") as f:
    f.write("// Auto-generated by categorize_bookmarks.py — do not edit manually.\n")
    f.write(f"window.BOOKMARK_CATEGORIES = {categories_json};\n")

print(f"\nWrote {OUT_JS}")
print("Done! Open categories.html to browse by category.")
