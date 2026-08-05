# Plan

## IMG_4874.HEIC transcription

1. **How do I automate the TikTok link process?**
   - URL option 1 (Manual): restricted — copy each TikTok link to an `.md` file
   - Conversion automated: `S → try(ydp) → if(Unsupported URL) then try(gallery-dl)`
     - i.e. try `yt-dlp` first, fall back to `gallery-dl` if the URL isn't supported

2. Diagram at the top sketching a pipeline: DB (hard drive) → local storage → buckets for "video/audio" and "images," with a "calendar view" and "coverage/creator(?)" grid, plus some rough icons (a triangle/prism, a map, and a downloader symbol).

## IMG_4875.HEIC transcription

2. **How should we name the TikTok files?**
   - Could this tie in to helping categorization?
     - Should we use metadata of the file to name it?
   - What are the existing categories?
     - and should we add new categories?
   - **DECISION**: Let's stick with the same categories for now

3. We don't need calendar notifications for posts → mostly/all activity is from the past, so that's just noise

## IMG_4876.HEIC transcription

**What is the end goal of this? How will you use it? D2D workflow?**

1. Open it up 1x a week
2. Hm → populates both views
   - then what?
3. → you check categories & see trends

4. Removing context (catch-up work) which helps us with knowing what you like → discernment

## IMG_4877.HEIC transcription

4. Is this scalable to other social media platforms → Pinterest?

5. New Features
   → can expand drawer view
   → e.g. category UI can have a new icon → that brings in other links → good reads
     - Spotify, Monarch [?]
   → additional layer on top of that

Front-end category (CSV-scraped)
CSV import
Scav frontend import? [?]
Landscape? [?]

## IMG_4878.HEIC transcription

**TASTE**
- Surface level → **Level 1**: TikTok, Twitter, YouTube, Pinterest
- contextualized → **Level 2**: cross-pollination of preferences
- predictive → once I have this preference archive
  → understand you can get predictive
  → discernment

~~#SYNCHRONICITY~~ (crossed out)

**PROJECT / LESS IS MORE**
→ knowing what you like & wants
  - Emo tags [?]
  ⟸ Say NO easier

## IMG_4879.HEIC transcription

*(This page was hard to read — several items flagged `[?]`, please double-check against the original.)*

**SYNCHRONICITY:**
An abstraction layer above all this that captures all this data to understand & explain to you what YOU like and who YOU are.

Sources:
- Goodreads
- Pinterest
- TikTok
- Twitter
- YouTube
- Monarch
- Mint / Mstg.com [?]
- Freshbook [?]
- WhatsApp
- Monarch (again?) [?]
- Beli / Yelp
- Letterboxd

→ All of these describe you — tastes & life, to some individual slice

**BUT** this is only one aspect of your life — Strava [?], AllTrails, Runna [?]

↓ abstraction layer above that

- can be used for Spotify / Apple [Music?] [?]
- Consumption (personal/professional)
- This is bigger than any [single] topic — your own interests

## Claude Review

Honest take: the plan has one solid idea buried under one shaky one.

**What's actually worth building:** the TikTok downloader/archiver (pages 1-2). Scoped, tractable, useful — you save things, they get pulled down and categorized before they vanish or you lose the link. That's a weekend project with real payoff.

**What's scope creep dressed as vision:** the "taste abstraction layer" spanning Goodreads, Letterboxd, Beli, Strava, WhatsApp, Spotify, AllTrails, etc. (pages 5-6). A few problems:

1. **Each platform is its own project.** Different auth, different rate limits, different data shapes, several with no public API at all (Letterboxd, Beli). You're not scoping one tool, you're scoping ten, and the plan treats that as an afterthought ("new features") rather than the actual bulk of the work.
2. **You're rebuilding what these apps already do.** Spotify Wrapped, Letterboxd stats, Goodreads reading history — they already tell you what you like. The pitch to "explain what YOU like and who YOU are" doesn't say what output this produces that those don't already give you.
3. **No defined deliverable.** "An abstraction layer that captures all this data to explain who you are" is a mission statement, not a spec. There's no artifact — no report, no dashboard, no query — described anywhere in six pages. That's how side projects become permanent works-in-progress.
4. **TikTok scraping is built on sand.** yt-dlp/gallery-dl fight an arms race against anti-scraping changes and ToS. Fine for personal archiving at small scale; not a foundation to build a bigger system on top of.
5. **WhatsApp is a red flag**, not a taste signal — it's private messages, likely including other people's data, and scraping it is a different category of problem (privacy/consent) than "what videos do I like."
6. **Ironic tension**: the notes explicitly say "less is more" / "discernment" / "say no easier," but the plan for getting there is *more data sources, more categorization, more weekly review overhead*. The system you're describing is itself more consumption to manage.

**Bottom line:** build the TikTok tool, actually use it for a month, and only then decide if you still want the grand cross-platform version — you'll have real usage data telling you what's worth automating instead of guessing from a notebook sketch.

## From Passive to Active: Interaction Features

Right now the categorization view (`categories.html`) is passive — you can see what's been sorted, but you can't add your own thoughts to it or make connections across categories. The push is toward active/contextual: interacting with the archive, annotating it, and surfacing cross-pollinating connections between items that live in different categories/sources.

**"Think in Moods" (game)** — curate a cross-category moodboard by pulling one item from several different categories/sources that all evoke the same feeling or vibe, then name/tag the resulting mood. Examples:
- EDM (Kettama) + night club + Barcelona
- Tuscany + Chianti/Merlot + The Godfather + Piero Piccioni

The point isn't sorting into existing categories — it's building new, personal, cross-cutting associations (sound × place × film × drink) that no single-platform "Wrapped" feature would ever surface, since it requires pulling from multiple sources at once.

Other feature directions in the same spirit:
- **Freeform annotations** — a lightweight notes/comment field on any item (tweet, TikTok, etc.) so reactions and context aren't lost the moment you scroll past.
- **Manual cross-links** — let you explicitly connect two items from different categories/sources ("this reminds me of that"), building a graph on top of the flat category lists.
- **Mood decks as a saved object** — once you build a "Think in Moods" board, save/name it so it persists like a category does, and it can be revisited or extended later.
- **Weekly prompt/challenge** — surface a random pair of unrelated items and ask "what connects these?" as a lightweight discernment exercise, rather than only reviewing what got auto-categorized.
- **Connection surfacing** — lightweight suggestions (not auto-classification) hinting "you've tagged Barcelona + night-life items before — anything else fit this mood?" to make cross-pollination easier to notice rather than something you have to remember to do manually.
