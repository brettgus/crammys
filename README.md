# Best Picture · Flashcards

A trivia cram tool covering every Academy Award Best Picture winner from 1947 through 2026 — director, top-billed cast, the other nominees of that ceremony, and trailer playback. Optional "Include nominees" mode expands the deck so every Best Picture *nominee* becomes its own card too (~450 cards total).

Three study modes:

- **Year → Title** — given the ceremony year, recall the winning film. With nominees on, the back face shows the full slate (★ winner + all other nominees).
- **Title → Year** — given a film, recall the year. With nominees on, the back face badges each card as *Winner ★* or *Nominated*.
- **Image → Title** — guess the film from a still.

## Run locally (offline, with cached images)

First-time setup — copy the API key template and fill it in:

```sh
cp .env.example .env
# edit .env: paste your TMDB key (and Anthropic key if you'll run the spoiler scan)
```

Then populate the local caches:

```sh
python3 fetch_images.py     # ~2,000 stills + posters into images/
python3 fetch_people.py     # ~870 profile photos into people/
python3 fetch_movies.py     # synopsis / runtime / rating per film -> movies.js
python3 scan_spoilers.py    # AI-flags images showing the title -> spoilers.js
```

All four are idempotent — re-running skips work already done.

Open `index.html` directly in a browser and you're set.

The deck for 1947–1996 is pulled from Wikidata + TMDB into `deck_extension.js`. To regenerate:

```sh
python3 fetch_deck.py
python3 fetch_nominee_directors.py    # adds director field to nominees
python3 fetch_nominee_trailers.py     # backfills trailers for hand-curated nominees
```

## Annual refresh (after each Oscars ceremony)

Two paths depending on how curated you want the new year to be:

**Quick (auto-fetched, no curated trailer URL):**

```sh
python3 fetch_one_year.py 2027    # prints a DECK_INLINE snippet for that year
# paste the snippet into the top of DECK_INLINE in index.html
python3 fetch_movies.py && \
python3 fetch_images.py && \
python3 fetch_people.py && \
python3 scan_spoilers.py
```

`fetch_one_year.py` scaffolds a year by pulling nominees from Wikidata + Wikipedia and enriching each via TMDB. It picks the highest-rated official YouTube trailer automatically.

**Curated (hand-pick trailer URL):**

Same as quick, then edit the new winner's `trailer:` field in `DECK_INLINE` to your preferred YouTube video ID.

## Publish to GitHub Pages

The static site has no build step — push the repo and turn on Pages.

1. Create a new repo on GitHub (any name, public or private).
2. From this folder:
   ```sh
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin git@github.com:YOUR-USERNAME/YOUR-REPO.git
   git push -u origin main
   ```
3. On the repo page → **Settings → Pages**. Set *Source* to *Deploy from a branch*, branch `main`, folder `/ (root)`. Save.
4. Wait ~30 seconds. Your site is live at `https://YOUR-USERNAME.github.io/YOUR-REPO/`.

When the app loads over `http(s)://`, it pulls images from TMDB's CDN automatically — the local `images/` and `people/` caches are only used over `file://`.

## Spoiler review

`scan_spoilers.py` uses Claude Haiku vision to flag images whose visible title would give the answer away in Image → Title mode. To eyeball + correct:

1. Open `review.html` in a browser.
2. Tick *Show flagged only* to focus on the ones the AI marked.
3. Click any thumbnail to toggle its flag (red ↔ green).
4. **Download spoilers.js** to save your overrides into the project folder.
5. Reload `index.html`.

## Data & credits

- Movie metadata, posters, stills, profile photos, and trailer IDs courtesy of [TMDB](https://www.themoviedb.org/).
- Best Picture nomination history sourced from [Wikidata](https://www.wikidata.org/) and [Wikipedia](https://en.wikipedia.org/).
- Image spoiler classification via Anthropic's [Claude Haiku](https://www.anthropic.com/).

This product uses the TMDB API but is not endorsed or certified by TMDB.

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Space` / `Enter` | flip the current card |
| `←` / `→` | previous / next |
| `S` | shuffle |
| `R` | reset |
| `F` | mark mastered (advances to next) |
| `U` | drill unmastered only |
| `N` | toggle "other nominees" on the back face |
| `I` | different image (image mode) |
| `T` | toggle theme |
| `?` | about / help dialog |
| `Esc` | close any popup |
