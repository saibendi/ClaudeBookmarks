#!/usr/bin/env python3
"""
categorize_tiktoks.py — Reads data.js + data_tiktok.js, classifies any
not-yet-categorized tweets/TikToks via Claude Haiku, writes categories.js with
window.BOOKMARK_CATEGORIES — the same shared file categorize_bookmarks.py
writes. Mirrors categorize_bookmarks.py's reconcile pattern exactly, just
reading both sources instead of one.

Usage:
    python3 categorize_tiktoks.py
    python3 categorize_tiktoks.py --reclassify   # ignore existing categories.js, redo everything

Requirements:
    pip install anthropic python-dotenv
    Add ANTHROPIC_API_KEY=sk-ant-... to .env
"""

import argparse
import json
import os
import re
import shutil
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


# ── Parse data.js + data_tiktok.js ────────────────────────────────────────────

HERE           = os.path.dirname(__file__)
DATA_JS        = os.path.join(HERE, "data.js")
DATA_TIKTOK_JS = os.path.join(HERE, "data_tiktok.js")


def load_items_by_date(path, global_name):
    """Parse a data.js-shaped file for one window.<global_name> = {...}; block.
    Returns {} if the file doesn't exist or the block isn't found."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()
    match = re.search(rf"window\.{global_name}\s*=\s*(\{{[\s\S]*?\}});", raw)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse {global_name} in {path}: {e}")
        sys.exit(1)


if not os.path.exists(DATA_JS) and not os.path.exists(DATA_TIKTOK_JS):
    print("ERROR: neither data.js nor data_tiktok.js found.")
    print("Run fetch_bookmarks.py and/or TikTokDownloader/fetch_tiktoks.py first.")
    sys.exit(1)

tweets_by_date  = load_items_by_date(DATA_JS, "BOOKMARK_TWEETS")
tiktoks_by_date = load_items_by_date(DATA_TIKTOK_JS, "TIKTOK_VIDEOS")

# Flatten both sources, adding _date field
all_items = []
for date_str, item_list in tweets_by_date.items():
    for item in item_list:
        it = dict(item)
        it["_date"] = date_str
        all_items.append(it)
for date_str, item_list in tiktoks_by_date.items():
    for item in item_list:
        it = dict(item)
        it["_date"] = date_str
        all_items.append(it)

if not all_items:
    print("No tweets or TikToks found. Run fetch_bookmarks.py / fetch_tiktoks.py to populate them.")
    sys.exit(0)

n_tweets  = sum(len(v) for v in tweets_by_date.values())
n_tiktoks = sum(len(v) for v in tiktoks_by_date.values())
n_days    = len(set(tweets_by_date) | set(tiktoks_by_date))
print(f"Found {n_tweets} tweets + {n_tiktoks} TikToks = {len(all_items)} total across {n_days} days.")


# ── Load existing categories (for reconcile mode) ─────────────────────────────

def load_existing_categories():
    """Load categories.js and return (cats_dict, set_of_assigned_ids).
    Returns (None, set()) if the file doesn't exist or can't be parsed."""
    out_js = os.path.join(HERE, "categories.js")
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

def build_prompt(item_batch):
    """Build the classification prompt for a batch of tweets/TikToks."""
    summaries = []
    for it in item_batch:
        text = it.get("text", "")[:300]  # truncate long captions/tweets
        summaries.append(f'{{"id":"{it["id"]}","text":{json.dumps(text)}}}')

    items_json = "[\n" + ",\n".join(summaries) + "\n]"

    return f"""You are classifying social media bookmarks (tweets and TikTok captions) into topic categories.

Here are the items to classify:
{items_json}

Instructions:
1. Invent 5–8 concise category names that cover these items (e.g. "AI & Technology", "Finance & Investing", "Productivity", "Design & Creativity", "Science", "Politics & Society", "Health & Fitness", "Humor & Culture").
2. Assign exactly one category to each item.
3. Use consistent category names across all items.
4. Return ONLY a JSON array, no explanation, no markdown, no code fences. Format:
[{{"id":"<item_id>","category":"<category_name>"}},...]"""


def build_prompt_reconcile(item_batch, existing_cat_names):
    """Prompt variant that reuses existing category names for new items."""
    summaries = []
    for it in item_batch:
        text = it.get("text", "")[:300]
        summaries.append(f'{{"id":"{it["id"]}","text":{json.dumps(text)}}}')
    items_json = "[\n" + ",\n".join(summaries) + "\n]"
    cats_list = ", ".join(f'"{c}"' for c in existing_cat_names)

    return f"""You are classifying social media bookmarks (tweets and TikTok captions) into topic categories.

Existing categories: [{cats_list}]

Here are the new items to classify:
{items_json}

Instructions:
1. Assign each item to one of the existing categories if it fits well.
2. Create a new category name ONLY if none of the existing ones is a good fit.
3. Use the existing category names EXACTLY as given (same spelling and capitalisation).
4. Assign exactly one category to each item.
5. Return ONLY a JSON array, no explanation, no markdown, no code fences. Format:
[{{"id":"<item_id>","category":"<category_name>"}},...]\
"""


# ── Call Claude API ────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=api_key)
MODEL = "claude-haiku-4-5-20251001"

def classify_batch(item_batch, existing_cat_names=None):
    """Send a batch of tweets/TikToks to Claude and return list of {id, category} dicts."""
    if existing_cat_names:
        prompt = build_prompt_reconcile(item_batch, existing_cat_names)
    else:
        prompt = build_prompt(item_batch)
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


# ── Reconcile mode setup ──────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Classify tweets + TikToks into categories.js")
parser.add_argument("--reclassify", action="store_true",
                     help="Ignore existing categories.js and reclassify everything")
args = parser.parse_args()

existing_cats, assigned_ids = (None, set()) if args.reclassify else load_existing_categories()

if existing_cats is not None:
    new_items = [it for it in all_items if it["id"] not in assigned_ids]
    if not new_items:
        print("All tweets/TikToks already categorised — nothing new to classify.")
        print("Fetch more first, or use --reclassify to force a full re-run.")
        sys.exit(0)
    print(f"{len(assigned_ids)} items already categorised; {len(new_items)} new to classify.")
    items_to_classify = new_items
    existing_cat_names = list(existing_cats.keys())
else:
    print("No existing categories.js — classifying everything from scratch.")
    items_to_classify = all_items
    existing_cat_names = None

# ── Run classification ────────────────────────────────────────────────────────
BATCH_SIZE = 100
assignments = []  # list of {id, category}

if len(items_to_classify) <= 150:
    print("Classifying in a single API call...")
    assignments = classify_batch(items_to_classify, existing_cat_names)
else:
    batches = [items_to_classify[i:i+BATCH_SIZE] for i in range(0, len(items_to_classify), BATCH_SIZE)]
    print(f"Classifying {len(items_to_classify)} items in {len(batches)} batches...")
    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{len(batches)} ({len(batch)} items)...")
        assignments.extend(classify_batch(batch, existing_cat_names))

print(f"Classified {len(assignments)} items.")


# ── Build / merge category map ────────────────────────────────────────────────

# Map item id → category for newly classified items
id_to_cat = {item["id"]: item["category"] for item in assignments if "id" in item and "category" in item}

# Map item id → full item object (all tweets + TikToks, for lookup)
id_to_item = {it["id"]: it for it in all_items}

# Start from existing categories (deep copy) or an empty dict for first run
categories: dict[str, list] = {k: list(v) for k, v in existing_cats.items()} if existing_cats else {}

# Insert newly classified items into the correct category buckets
for item_id, cat in id_to_cat.items():
    item = id_to_item.get(item_id)
    if item is None:
        continue
    if cat not in categories:
        categories[cat] = []
    categories[cat].append(item)

# Re-sort every category's items by recency descending. added_at (when we
# fetched it) if present, else created_at (when it was originally posted) —
# items predating the added_at field fall back to created_at automatically.
for cat in categories:
    categories[cat].sort(key=lambda t: t.get("added_at") or t.get("created_at", ""), reverse=True)

# Sort categories by item count descending
categories = dict(sorted(categories.items(), key=lambda x: len(x[1]), reverse=True))

print("\nCategories:")
new_cats = []
for cat, items in categories.items():
    is_new = existing_cats is not None and cat not in existing_cats
    if is_new:
        new_cats.append(cat)
    marker = " [NEW]" if is_new else ""
    print(f"  {cat}: {len(items)} items{marker}")

if new_cats:
    print(f"\n{len(new_cats)} new categor{'y' if len(new_cats) == 1 else 'ies'}: {', '.join(new_cats)}")
else:
    print("\nNo new categories.")


# ── Backup existing categories.js ────────────────────────────────────────────
OUT_JS = os.path.join(HERE, "categories.js")
OLD_JS = os.path.join(HERE, "categories_old.js")
if os.path.exists(OUT_JS):
    shutil.copy2(OUT_JS, OLD_JS)
    print(f"Backed up existing categories.js → categories_old.js")


# ── Write categories.js ───────────────────────────────────────────────────────

categories_json = json.dumps(categories, ensure_ascii=False, indent=2)

with open(OUT_JS, "w", encoding="utf-8") as f:
    f.write("// Auto-generated by categorize_bookmarks.py / categorize_tiktoks.py — do not edit manually.\n")
    f.write(f"window.BOOKMARK_CATEGORIES = {categories_json};\n")

print(f"\nWrote {OUT_JS}")
print("Done! Open categories.html to browse by category.")
