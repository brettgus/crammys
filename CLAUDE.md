# Crammys — working notes for Claude Code sessions

Single-page flashcard app. One HTML shell (`index.html`) loads deck
modules via hash routing (`#bestpicture`, `#chains`). No build step —
native ES modules, served on GitHub Pages.

## Architecture

```
index.html              ← SPA shell: shared DOM skeleton + router
deck-engine.js          ← DeckEngine class (state, scoring, flip, nav, swipe, tooltips)
decks/
  bestpicture.js        ← BP deck module (exports meta, segments, modals, init)
  bestpicture-data.js   ← BP static data (DECK_INLINE array)
  chains.js             ← Chains deck module
crammys-shared.css      ← visual identity, all generic CSS
crammys-shared.js       ← theme toggle, deck-switcher dropdown wiring
chains.html             ← redirect stub → index.html#chains
```

## File responsibilities

- **`index.html`** — SPA shell. Contains the shared card structure
  (controls bar, card-stage, nav row, tooltip element), an inline
  `<style>` for deck-specific CSS that doesn't generalize, and a
  `<script type="module">` router that reads `location.hash`, imports
  the deck module, injects its HTML (segments, overlays, modals), and
  calls `init({ signal })`.

- **`deck-engine.js`** — ES module exporting `DeckEngine` class,
  `shuffleArray`, `escapeHtml`, `loadScript`. The engine handles:
  localStorage state, scoring/retirement, weighted shuffle, card flip
  animation, next/prev/rate, touch swipe, tooltip system, keyboard
  bindings, modal open/close helpers. All `bind*` methods accept an
  `AbortSignal` for clean teardown on deck switch.

- **`decks/<name>.js`** — each deck module exports:
  - `meta` — `{ id, emoji, name }` for the switcher/title
  - `segments` — HTML string injected into `.seg` container
  - `frontExtras` — HTML for front-face overlays (logo stage, image stage)
  - `modals` — HTML for deck-specific modal backdrops
  - `init({ signal })` — async function that loads data scripts, creates
    a DeckEngine instance, wires events, and renders. The `signal`
    (from AbortController) is passed to all addEventListener calls so
    the shell can tear down the deck on switch.

- **`crammys-shared.css`** — visual identity and **all** generic CSS.
  Holds tokens, base layout, the card-flip system, buttons, chips,
  segments, modals, the deck switcher, footer-hint variants, side
  card-arrows, rate buttons, the tooltip skeleton, image-mode overlay,
  trailer-modal frame, credits / nominee-list / slate / badge patterns,
  about-modal contents.

- **`crammys-shared.js`** — cross-deck behavior: `DECKS` registry, theme
  toggle + persistence, deck-switcher dropdown wiring.

## Adding a new deck

1. Create `decks/<name>.js` (and optionally `decks/<name>-data.js` for
   large static data). Export `meta`, `segments`, `frontExtras`, `modals`,
   and `init({ signal })`.

2. Register it in `index.html`'s `DECKS` array:
   ```js
   { id: "<name>", path: "./decks/<name>.js" }
   ```

3. Register it in `crammys-shared.js`'s `DECKS` array so the
   deck-switcher dropdown lists it.

4. (Optional) Create a `<name>.html` redirect stub for backwards compat.

### Deck module conventions

- Import `DeckEngine`, `escapeHtml`, `loadScript` from `../deck-engine.js`.
- Load data scripts with `await loadScript("data-file.js")` — they
  assign to `window.*` and will be ready when the promise resolves.
- Create the engine with deck-specific config: `storeKey`, `cardId`,
  `activeFilter`, `inScopeFilter`, `isStudyMode`, `render`.
- Pass `signal` to `engine.bindStandardUI()`, `engine.bindKeyboard()`,
  `engine.bindTooltips()`, and all `addEventListener()` calls.
- Use standardized DOM IDs from the shell: `#card`, `#navRow`,
  `#frontFace`, `#frontTag`, `#frontPrompt`, `#frontText`,
  `#frontExtras`, `#backTag`, `#backBody`, `#backFooterHint`,
  `#counter`, `#scopeText`, `#scopeExtras`, `#deckChip`, `#progress`,
  `#scoreStarsFront`, `#scoreStarsBack`, `#tooltip`.

### DeckEngine constructor config

```js
new DeckEngine({
  storeKey,           // localStorage key
  defaultState,       // initial state shape
  migrateState,       // (state) => state — version migrations
  allIds,             // string[] of all card IDs
  byId,              // Map<id, card>
  cardId,            // (card) => string
  activeFilter,      // (id, state) => boolean — which cards are in play
  inScopeFilter,     // (id, state) => boolean — which cards count for learned/total
  isStudyMode,       // (state) => boolean
  render,            // () => void — called after any state change
  onBeforeNavigate,  // () => void — e.g. hide tooltips
  reshuffleOnWrap,   // boolean — reshuffle when advancing past last card
  onShuffle,         // () => void — e.g. clear image choices
  cardEl, navRowEl, scoreStarsFrontEl, scoreStarsBackEl,
})
```

## CSS routing decisions

**Default to shared.** Inline CSS is a smell — an unused rule in shared
is inert and costs nothing; a missing-from-shared rule means future decks
have to either duplicate or rediscover it.

- **Generic** (layout, spacing, typography, hover behavior, button
  shapes, modal contents, grids, lists, tooltips, badges) →
  `crammys-shared.css` with a deck-neutral class name.
- **Coupled to one deck's data** → inline `<style>` in the shell.

## Workflow notes

- GitHub Pages serves from `main`. The site goes live within ~30 seconds
  of a push.
- `images/`, `people/`, and `.env` are gitignored. When deployed over
  `http(s)://` the app reads from TMDB's CDN; over `file://` it reads
  the local cache.
- Secrets live in `.env`. `.env.example` shows the shape. Never commit
  `.env`.
- ES modules require `http(s)://` — `file://` won't work (CORS). Use
  `python3 -m http.server` or GitHub Pages for local testing.
- If the user has another Claude Code session active on a different
  branch in this same working tree, do `main`-side edits in a temporary
  git worktree instead of switching their checkout's branch.

## Annual refresh (after each Oscars ceremony)

```sh
python3 fetch_one_year.py <year>   # scaffold the DECK_INLINE snippet for that year
# paste it into decks/bestpicture-data.js, then:
python3 fetch_movies.py && python3 fetch_images.py && \
python3 fetch_people.py && python3 scan_spoilers.py
```
