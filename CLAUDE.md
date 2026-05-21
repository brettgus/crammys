# Crammys — working notes for Claude Code sessions

This repo hosts multiple flashcard decks. Each deck is its own HTML file
(e.g. `index.html`, `chains.html`) that loads a shared design system.

## File responsibilities

- **`crammys-shared.css`** — visual identity and cross-deck UI primitives:
  design tokens, base layout, the card-flip system, generic buttons /
  chips / segments / modals / dropdowns, footer-hint variants, side
  card-arrows, the rate buttons, etc. **Anything another deck would
  also want.** When in doubt, read the file: its section headers list
  what's already there.

- **`crammys-shared.js`** — cross-deck behavior: `DECKS` registry, theme
  toggle + persistence, deck-switcher dropdown wiring. Each deck page
  sets `window.CURRENT_DECK` before loading it.

- **Per-page inline `<style>` and `<script>`** — deck-specific feature
  CSS and JS (anything coupled to that deck's data shape or unique
  modes).

## Routing decisions

When adding CSS or JS, ask:

> Would another deck want this exact rule / function?

- **Yes** → put it in the shared file.
- **No** (it references a class or data shape unique to one deck) →
  inline in that deck's page.

Borderline cases default to **inline + add a TODO** to promote later;
that's reversible and safer than putting something in shared that turns
out to need per-deck overrides.

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

## Annual refresh (after each Oscars ceremony)

```sh
python3 fetch_one_year.py <year>   # scaffold the DECK_INLINE snippet for that year
# paste it into index.html, then:
python3 fetch_movies.py && python3 fetch_images.py && \
python3 fetch_people.py && python3 scan_spoilers.py
```
