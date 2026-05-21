# Crammys — working notes for Claude Code sessions

This repo hosts multiple flashcard decks ("Crammys: Best Picture" today,
"Crammys: Restaurant Chains" being prototyped, possibly more later). Each
deck is its own HTML file (`index.html`, `chains.html`) that loads the
shared design system from sibling files.

## File responsibilities

- **`crammys-shared.css`** — visual identity and cross-deck UI primitives.
  Owns: design tokens (`:root`), base layout (`body`, `main`, `.controls`),
  the 3D card-flip system, common buttons (`.btn`, `.icon-btn`, `.seg`,
  `.chip`), modals (`.modal-backdrop`, `.panel`, `.modal-close`), deck
  switcher dropdown, side card-arrows, Tier-2 rate buttons (`.rate-btn`,
  `.rate-missed`, `.rate-got`), context-aware hint variants (`.hint-desktop`,
  `.hint-touch`), score-stars indicator, panel-foot, link-danger, etc.
  **Anything that another deck would also want.**

- **`crammys-shared.js`** — cross-deck behavior. Owns: `DECKS` registry,
  theme toggle + persistence, deck-switcher dropdown wiring. Each deck
  page sets `window.CURRENT_DECK` in a tiny inline `<script>` before
  loading this.

- **Per-page inline `<style>` and `<script>`** — deck-specific feature CSS
  and JS. For `index.html` (Best Picture) this includes: image-mode
  (`.image-stage`, `.image-overlay`, `.image-controls`), slate view
  (`.slate-row`), winner/nominee badges, the year-range modal contents,
  movie/year/person tooltips, the trailer modal iframe, etc.

## Default routing for new CSS

When adding a new CSS rule, ask: **would `chains.html` (or a future deck)
benefit from this exact rule?**

- **Yes** → put it in `crammys-shared.css`.
- **No** (it references a deck-specific class like `.image-overlay`, a
  data shape unique to that deck, etc.) → keep it inline in the deck's
  HTML file.

Examples of "yes, shared":

- A new general-purpose button variant
- A new modal layout class
- Anything keyed off `:root` design tokens with no deck-specific selector
- Hover/touch media-query patterns

Examples of "no, inline":

- Styles for the image-stage / slate / nominees-list (Best Picture)
- Styles for the chain-logo card (Restaurant Chains)
- Per-deck font choices for the answer text (if a deck wanted a different
  typeface for some reason)

## Default routing for new JS

- Cross-deck behavior (theme, deck switcher, anything reading `window.CURRENT_DECK`)
  → `crammys-shared.js`.
- Deck-specific behavior (rendering Best Picture cards, picking trailer
  IDs, etc.) → the deck page's inline `<script>`.

## Workflow notes

- The `chains` branch holds in-progress work on `chains.html` by a parallel
  Claude session. **Don't switch the user's local working tree** between
  `main` and `chains` while that session is active. Use a temporary git
  worktree (`git worktree add /tmp/crammys-main main`) for `main`-side
  edits and remove it after pushing.
- `GitHub Pages` serves from `main`. Commits to `main` go live at
  https://brettgus.github.io/crammys/ within ~30 seconds.
- Image and people caches (`images/`, `people/`) are gitignored; the app
  pulls from TMDB's CDN over `http(s)://` and from local files over
  `file://`. Don't commit these folders.
- Secrets (`ANTHROPIC_API_KEY`, `TMDB_API_KEY`) live in `.env` (gitignored).
  `.env.example` shows the shape.

## Annual refresh (after each Oscars ceremony)

See README. The short version:

```sh
python3 fetch_one_year.py <year>   # scaffold a year's DECK_INLINE snippet
# paste into index.html DECK_INLINE, then:
python3 fetch_movies.py && python3 fetch_images.py && \
python3 fetch_people.py && python3 scan_spoilers.py
```
