# Best Picture · Flashcards

A trivia cram tool covering every Academy Award Best Picture winner from 1947 through 2025, with director, top-billed cast, the other nominees of that ceremony, and trailer playback. Three study modes:

- **Year → Title** — given the ceremony year, recall the winning film.
- **Title → Year** — given the film, recall the year.
- **Image → Title** — guess the film from a still.

## Run locally (offline, with cached images)

First-time setup — copy the API key template and fill it in:

```sh
cp .env.example .env
# edit .env: paste your TMDB key (and Anthropic key if you'll run the spoiler scan)
```

Open `index.html` directly in a browser. To populate the local image cache:

```sh
python3 fetch_images.py    # downloads ~470 stills + posters into images/
python3 fetch_people.py    # downloads ~870 profile photos into people/
```

Both are idempotent — re-running skips files already present.

The deck for 1947–1996 is pulled from Wikidata + TMDB into `deck_extension.js`. To regenerate:

```sh
python3 fetch_deck.py
python3 fetch_nominee_trailers.py    # backfills trailers for hand-curated nominees
```

## Annual refresh (after each Oscars ceremony)

Run this single chain to pull the latest data — Wikidata picks up the new ceremony's nominees, TMDB refreshes the cast/trailer/posters, and the spoiler scan flags any new images that show their title:

```sh
cd path/to/Trivia
python3 fetch_deck.py && \
python3 fetch_movies.py && \
python3 fetch_images.py && \
python3 fetch_people.py && \
python3 scan_spoilers.py
```

Then **manually add the new winner** to `DECK_INLINE` in `index.html` (if you want a curated trailer URL — otherwise the script-fetched data covers the older years just fine).

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
3. On the repo page → **Settings → Pages**. Set "Source" to *Deploy from a branch*, branch `main`, folder `/ (root)`. Save.
4. Wait ~30 seconds. Your site is live at `https://YOUR-USERNAME.github.io/YOUR-REPO/`.

When the app is loaded over `http(s)://`, it pulls images from TMDB's CDN automatically — the local `images/` and `people/` caches are only used over `file://`.

## Data & credits

- Movie metadata, posters, stills, profile photos, and trailer IDs courtesy of [TMDB](https://www.themoviedb.org/).
- Best Picture nomination history sourced from [Wikidata](https://www.wikidata.org/).

This product uses the TMDB API but is not endorsed or certified by TMDB.

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| `Space` / `Enter` | flip the current card |
| `←` / `→` | previous / next |
| `S` | shuffle |
| `R` | reset |
| `F` | mark mastered |
| `U` | drill unmastered only |
| `N` | toggle other nominees |
| `I` | different image (image mode) |
| `T` | toggle theme |
| `?` | this dialog |
| `Esc` | close any popup |
