# Crammys — working notes for Claude Code sessions

This repo hosts multiple flashcard decks. Each deck is its own HTML file
(e.g. `index.html`, `chains.html`) that loads a shared design system.

## File responsibilities

- **`crammys-shared.css`** — visual identity and **all** generic CSS.
  Holds tokens, base layout, the card-flip system, buttons, chips,
  segments, modals, the deck switcher, footer-hint variants, side
  card-arrows, rate buttons, the tooltip skeleton, image-mode overlay,
  trailer-modal frame, credits / nominee-list / slate / badge patterns,
  about-modal contents — anything that's purely visual logic. Section
  headers (`/* ── Section ───── */`) list what's already there.

- **`crammys-shared.js`** — cross-deck behavior: `DECKS` registry, theme
  toggle + persistence, deck-switcher dropdown wiring. Each deck page
  sets `window.CURRENT_DECK` before loading it.

- **Per-page inline `<style>` and `<script>`** — deck-specific *behavior*.
  Inline `<style>` should be near-empty; inline `<script>` holds the
  deck's render logic, data fetching, and event wiring (anything that
  references that deck's data shape).

## Routing decisions

**Default to shared, especially for CSS.** Inline CSS is a smell — an
unused rule in shared is inert and costs nothing; a missing-from-shared
rule means future decks have to either duplicate or rediscover it.

When adding a CSS rule, the question is:

> Is this rule about a generic visual / interaction pattern, or is it
> tightly coupled to one deck's data shape?

- **Generic** (layout, spacing, typography, hover behavior, button
  shapes, modal contents, grids, lists, tooltips, badges) →
  `crammys-shared.css` with a **deck-neutral class name**
  (`.detail-grid`, not `.restaurant-detail-grid`).
- **Coupled to one deck's data** (selector hardcodes a deck-specific
  class, or only makes sense alongside that deck's content) → inline.

The only legitimate reason to inline CSS is "naming this generically
would force a deck-specific concept into the shared file." If you can
rename the class to be deck-neutral, the rule belongs in shared.

For **JS**: cross-deck behaviors (theme, deck switcher) → shared.
Deck-specific render logic / event wiring → inline. JS that references
DOM IDs unique to one deck stays inline.

## Workflow notes

- GitHub Pages serves from `main`. The site goes live within ~30 seconds
  of a push.
- `images/`, `people/`, and `.env` are gitignored. When deployed over
  `http(s)://` the app reads from TMDB's CDN; over `file://` it reads
  the local cache.
- Secrets live in `.env`. `.env.example` shows the shape. Never commit
  `.env`.
- If the user has another Claude Code session active on a different
  branch in this same working tree, do `main`-side edits in a temporary
  git worktree (`git worktree add /tmp/crammys-main main`) instead of
  switching their checkout's branch.

## Building a new deck page

A new deck (e.g. `chains.html`) inherits the entire visual identity from
the shared files. Conventions:

**Must follow:**
- Use the existing design tokens (`--bg`, `--ink`, `--accent`, etc.). Don't
  introduce new colors or fonts.
- Reuse `.card-stage` / `.card` / `.face` / `.face.back` for the flip system.
- Reuse `.rate-btn` / `.rate-missed` / `.rate-got` for the got-it/missed flow.
- Reuse the modal system (`.modal-backdrop` + `.panel`) for popups.
- Reuse `.btn`, `.icon-btn`, `.seg`, `.chip`, `.chip-btn` for buttons /
  segmented controls / chips. Don't invent parallel styles for the same
  affordances.
- Set `window.CURRENT_DECK = "<id>"` in a tiny `<script>` in the head, before
  loading `crammys-shared.js`.
- Register the deck in `crammys-shared.js`'s `DECKS` array so the deck-switcher
  dropdown lists it.

**May diverge on (where the divergence is *behavior*, not visual style):**
- The direction-segment options. ("Year → Title" doesn't apply to chains;
  chains might be "Logo → Name", "Name → Founded", etc.) Markup goes in
  the page; the segment styling is already shared.
- Card content layout — markup in the page, styling in shared.
- The contents of the deck-info chip and deck-specific modal panels —
  markup in the page, styling in shared.
- Image / media affordances unique to that deck — chains' logo-grid
  markup goes in the page, but the visual styling (grid layout, hover
  lift, etc.) should be a generic shared rule the page references.

**Add to shared whenever you invent a generic visual primitive.** Chains
needs a "two-column stat panel"? Add `.stat-panel` to shared — BP and any
future deck can adopt it later. Don't inline it just because today only
one deck uses it.

## Annual refresh (after each Oscars ceremony)

```sh
python3 fetch_one_year.py <year>   # scaffold the DECK_INLINE snippet for that year
# paste it into index.html, then:
python3 fetch_movies.py && python3 fetch_images.py && \
python3 fetch_people.py && python3 scan_spoilers.py
```
