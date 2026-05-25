import { DeckEngine, loadScript, shuffleArray, escapeHtml } from '../deck-engine.js';
import DECK_INLINE from './bestpicture-data.js';

export const meta = { id: "bestpicture", emoji: "🎬", name: "Best Picture" };

export const segments = `
  <button id="dirYearToMovie" class="on">Year → Title</button>
  <button id="dirMovieToYear">Title → Year</button>
  <button id="dirImageToMovie">Image → Title</button>
  <button id="dirStudy">Study</button>`;

export const frontExtras = `
  <div class="image-stage" id="imageStage" hidden>
    <img id="imageEl" alt="" />
    <div class="image-overlay">
      <div class="corner"><span>Image</span></div>
      <div class="bottom">
        <div class="image-controls">
          <span class="image-dots" id="imageDots" aria-hidden="true"></span>
          <button class="image-stack-btn" id="rerollBtn" title="More images" aria-label="More images">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="14" height="14" rx="2"/><path d="M7 3h12a2 2 0 0 1 2 2v12"/></svg>
          </button>
        </div>
        <div class="prompt">What movie is this?</div>
        <div class="footer-hint">
          <span class="hint-desktop"><kbd>Space</kbd> or tap to reveal</span>
          <span class="hint-touch">Tap to reveal · swipe to navigate</span>
        </div>
      </div>
    </div>
  </div>`;

export const modals = `
  <div class="modal-backdrop" id="aboutModal" hidden>
    <div class="panel panel-wide" role="dialog" aria-label="About">
      <button class="modal-close" id="aboutClose" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <h3 class="panel-title">Best Picture · Flashcards</h3>
      <p class="panel-sub">A trivia cram tool covering every Academy Award Best Picture winner from <span id="aboutSpan">1947</span>–<span id="aboutSpanTo">2025</span>.</p>
      <div class="about-section"><h4>Keyboard shortcuts</h4>
        <div class="kbd-grid"><div><kbd>Space</kbd> reveal answer</div><div><kbd>←</kbd> <kbd>→</kbd> previous / next</div><div><kbd>Y</kbd> got it</div><div><kbd>N</kbd> missed</div><div><kbd>S</kbd> shuffle</div><div><kbd>R</kbd> reset progress</div><div><kbd>L</kbd> toggle Study mode</div><div><kbd>↑</kbd> <kbd>↓</kbd> cycle images (image mode)</div><div><kbd>T</kbd> toggle theme</div><div><kbd>?</kbd> this dialog</div><div><kbd>Esc</kbd> close any popup</div></div>
      </div>
      <div class="about-section"><h4>Data &amp; credits</h4>
        <p>Movie metadata, posters, stills, and trailer IDs courtesy of <a href="https://www.themoviedb.org/" target="_blank" rel="noopener">TMDB</a>. Nomination history sourced from <a href="https://www.wikidata.org/" target="_blank" rel="noopener">Wikidata</a>. Person photos and bios via TMDB.</p>
        <p class="panel-fineprint">This product uses the TMDB API but is not endorsed or certified by TMDB.</p>
      </div>
    </div>
  </div>
  <div class="modal-backdrop" id="rangeModal" hidden>
    <div class="panel" role="dialog" aria-label="Year range">
      <button class="modal-close" id="rangeClose" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <h3 class="panel-title">Deck</h3>
      <p class="panel-sub">Limit by year range, and choose whether nominees are part of the deck too.</p>
      <label class="toggle-row"><input type="checkbox" id="includeNomineesChk"><span><strong>Include nominees</strong><em>expands the deck so every Best Picture nominee is its own card</em></span></label>
      <label class="toggle-row"><input type="checkbox" id="yearBasisChk"><span><strong>Show ceremony year instead of release year</strong><em>Default is the film's release year — e.g. <i>Forrest Gump</i> shows 1994. Tick this to show the year of the ceremony where it won (1995).</em></span></label>
      <h4 class="panel-section">Year range</h4>
      <div class="range-presets" id="rangePresets"></div>
      <div class="range-inputs"><label>From <select id="rangeFrom"></select></label><span class="range-dash">–</span><label>To <select id="rangeTo"></select></label></div>
      <div class="panel-foot"><span id="rangeCount" class="panel-count"></span><button class="link-danger" id="resetProgressBtn">Start over</button></div>
    </div>
  </div>
  <div class="modal-backdrop" id="trailerModal" hidden>
    <div class="modal-frame" role="dialog" aria-label="Trailer">
      <button class="modal-close" id="trailerClose" aria-label="Close trailer">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <iframe id="trailerFrame" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe>
    </div>
  </div>`;

export async function init({ signal }) {
  await Promise.all([
    loadScript("images.js"),
    loadScript("people.js"),
    loadScript("movies.js"),
    loadScript("spoilers.js", { onerror: () => { window.SPOILERS = {}; } }),
    loadScript("deck_extension.js"),
  ]);

  const DECK = DECK_INLINE.concat(window.DECK_EXTENSION || []);
  const _maxYear = Math.max(...DECK.map(e => e.year));
  const _minYear = Math.min(...DECK.map(e => e.year));
  const DEFAULT_RANGE = { from: _maxYear - 29, to: _maxYear };
  const SCORE_RETIRED = 3;
  const cardId = (c) => `${c.year}::${c.movie}`;
  const imageChoice = new Map();

  function buildPool(includeNominees) {
    const pool = [];
    for (const w of DECK) {
      const slate = (w.nominees || []).map(n => ({ movie: n.movie, trailer: n.trailer }));
      pool.push({ year: w.year, movie: w.movie, director: w.director, stars: w.stars, trailer: w.trailer, status: "winner", slate, winnerMovie: w.movie });
      if (includeNominees) for (const n of w.nominees || []) pool.push({ year: w.year, movie: n.movie, director: n.director, stars: n.stars, trailer: n.trailer, status: "nominee", slate, winnerMovie: w.movie });
    }
    return pool;
  }

  let POOL = buildPool(false);
  let POOL_BY_ID = new Map(POOL.map(c => [cardId(c), c]));

  const engine = new DeckEngine({
    storeKey: "bp-flashcards-v4",
    defaultState: { direction: "y2m", order: null, idx: 0, scores: {}, range: DEFAULT_RANGE, includeNominees: false, lastDir: "y2m", yearBasis: "film" },
    migrateState(s) {
      if (!s.scores || typeof s.scores !== "object") s.scores = {};
      if (Array.isArray(s.mastered)) { for (const id of s.mastered) if (typeof id === "string") s.scores[id] = SCORE_RETIRED; delete s.mastered; }
      if (s.learn === true) { s.lastDir = s.direction && s.direction !== "study" ? s.direction : "y2m"; s.direction = "study"; }
      delete s.learn; if (!s.lastDir || s.lastDir === "study") s.lastDir = "y2m";
      delete s.onlyUnknown; delete s.showNominees; delete s.theme;
      if (!s.range || typeof s.range.from !== "number") s.range = { ...DEFAULT_RANGE };
      s.range.from = Math.max(_minYear, Math.min(_maxYear, s.range.from));
      s.range.to = Math.max(_minYear, Math.min(_maxYear, s.range.to));
      if (s.range.from > s.range.to) s.range.from = s.range.to;
      if (typeof s.includeNominees !== "boolean") s.includeNominees = false;
      if (s.yearBasis !== "ceremony") s.yearBasis = "film";
      if (s.includeNominees) { POOL = buildPool(true); POOL_BY_ID = new Map(POOL.map(c => [cardId(c), c])); }
      return s;
    },
    allIds: POOL.map(cardId), byId: POOL_BY_ID, cardId,
    reshuffleOnWrap: true, onShuffle: () => imageChoice.clear(),
    activeFilter(id, state) {
      const c = POOL_BY_ID.get(id); if (!c) return false;
      if (!inRange(c.year)) return false;
      if (engine.scoreOf(id) >= SCORE_RETIRED) return false;
      if (state.direction === "y2m" && c.status === "nominee") return false;
      if (state.direction === "i2m" && !cardHasImages(c)) return false;
      return true;
    },
    inScopeFilter(id, state) {
      const c = POOL_BY_ID.get(id); if (!c) return false;
      if (!inRange(c.year)) return false;
      if (state.direction === "y2m" && c.status === "nominee") return false;
      return true;
    },
    isStudyMode: (state) => state.direction === "study",
    render: () => render(),
    onBeforeNavigate: () => hideTip(true),
    cardEl: document.getElementById("card"),
    navRowEl: document.getElementById("navRow"),
    scoreStarsFrontEl: document.getElementById("scoreStarsFront"),
    scoreStarsBackEl: document.getElementById("scoreStarsBack"),
  });

  const state = engine.state;
  const inRange = (y) => !state.range || (y >= state.range.from && y <= state.range.to);
  function rebuildPool() { POOL = buildPool(state.includeNominees); POOL_BY_ID = new Map(POOL.map(c => [cardId(c), c])); engine.byId = POOL_BY_ID; engine.updatePool(POOL.map(cardId), POOL_BY_ID); }

  // DOM
  const frontFace = document.getElementById("frontFace");
  const front = { text: document.getElementById("frontText"), prompt: document.getElementById("frontPrompt"), tag: document.getElementById("frontTag") };
  const back = { tag: document.getElementById("backTag"), body: document.getElementById("backBody") };
  const counter = document.getElementById("counter");
  const scopeTextEl = document.getElementById("scopeText");
  const scopeExtrasEl = document.getElementById("scopeExtras");
  const progress = document.getElementById("progress");
  const imageStage = document.getElementById("imageStage");
  const imageEl = document.getElementById("imageEl");

  // Images
  const IMAGES_BY_CARD = {};
  (window.MOVIE_IMAGES || []).forEach(m => { IMAGES_BY_CARD[`${m.year}::${m.movie}`] = m; });
  const HAS_IMAGES = Object.keys(IMAGES_BY_CARD).length > 0;
  if (!HAS_IMAGES) { const btn = document.getElementById("dirImageToMovie"); btn.disabled = true; btn.style.opacity = .4; btn.title = "Image data not loaded"; }
  const cardHasImages = (c) => !!IMAGES_BY_CARD[cardId(c)];
  const USE_LOCAL_IMAGES = location.protocol === "file:";
  const TMDB_W185 = "https://image.tmdb.org/t/p/w185";
  function movieImageURL(img, size) { if (USE_LOCAL_IMAGES) return `images/${img.f}`; if (img.p) return `https://image.tmdb.org/t/p/${size || "w780"}${img.p}`; return `images/${img.f}`; }
  function thumbForMovie(title) { for (const entry of (window.MOVIE_IMAGES || [])) { if (entry.movie !== title) continue; return (entry.images || []).find(i => i.k === "ps") || entry.images[0] || null; } return null; }
  function personImageURL(p) { if (USE_LOCAL_IMAGES) return p.img || ""; if (p.tmdb_img) return `${TMDB_W185}${p.tmdb_img}`; return p.img || ""; }
  const SPOILERS = window.SPOILERS || {};
  function safeImagesFor(c) { const entry = IMAGES_BY_CARD[cardId(c)]; if (!entry || !entry.images) return []; const safe = entry.images.filter(img => !SPOILERS[img.f]); return safe.length ? safe : entry.images; }
  function pickImage(c, opts = {}) { const safe = safeImagesFor(c); if (!safe.length) return null; const n = safe.length; const key = cardId(c); let idx; if (typeof opts.step === "number" && imageChoice.has(key)) idx = ((imageChoice.get(key) + opts.step) % n + n) % n; else if (opts.reroll && imageChoice.has(key)) { const prev = imageChoice.get(key); idx = (prev + 1 + Math.floor(Math.random() * (n - 1))) % n; } else if (imageChoice.has(key)) idx = Math.min(imageChoice.get(key), n - 1); else idx = Math.floor(Math.random() * n); imageChoice.set(key, idx); return safe[idx]; }
  const imageDotsEl = document.getElementById("imageDots");
  function renderImageDots(c) { const safe = safeImagesFor(c); if (!safe.length) { imageDotsEl.innerHTML = ""; return; } const sel = imageChoice.get(cardId(c)) ?? 0; imageDotsEl.innerHTML = safe.map((_, i) => `<span${i === sel ? ' class="on"' : ""}></span>`).join(""); }
  function setImage(c, opts) { const img = pickImage(c, opts); if (!img) { imageEl.removeAttribute("src"); imageEl.alt = ""; imageDotsEl.innerHTML = ""; return; } imageStage.classList.add("loading"); imageEl.onload = () => imageStage.classList.remove("loading"); imageEl.onerror = () => imageStage.classList.remove("loading"); imageEl.src = movieImageURL(img); imageEl.alt = ""; renderImageDots(c); }
  function rerollImage() { const c = engine.currentCard(); if (c) setImage(c, { reroll: true }); }
  function stepImage(delta) { if (state.direction !== "i2m") return; const c = engine.currentCard(); if (c) setImage(c, { step: delta }); }

  // Helpers
  const extIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7M9 7h8v8"/></svg>';
  const playIcon = '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="7 4 19 12 7 20 7 4"/></svg>';
  const imageIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.5"/><path d="M21 16l-5-5-7 7"/></svg>';
  const stop = `onclick="event.stopPropagation()"`;
  function googleImagesURL(movie) { const m = (window.MOVIES || {})[movie]; const y = m && m.release_date ? m.release_date.slice(0, 4) : null; return `https://www.google.com/search?tbm=isch&q=${encodeURIComponent(y ? `"${movie}" (${y})` : `"${movie}" movie`)}`; }
  const imageSearchLink = (movie) => `<a class="ext" href="${googleImagesURL(movie)}" target="_blank" rel="noopener" title="Image search · ${escapeHtml(movie)}" ${stop}>${imageIcon}</a>`;
  function trailerLink(movie, vid) { if (vid) return `<a class="ext play" href="https://www.youtube.com/watch?v=${vid}" target="_blank" rel="noopener" data-video-id="${vid}" data-title="${escapeHtml(movie)}" title="Watch trailer" ${stop}>${playIcon}</a>`; return `<a class="ext" href="https://www.youtube.com/results?search_query=${encodeURIComponent(movie + " trailer")}" target="_blank" rel="noopener" title="YouTube trailer search" ${stop}>${extIcon}</a>`; }
  const movieLinks = (movie, vid) => trailerLink(movie, vid) + imageSearchLink(movie);
  const imdb = (name) => { const id = (window.PEOPLE || {})[name]?.imdb_id; return id ? `https://www.imdb.com/name/${id}/` : `https://www.imdb.com/find/?q=${encodeURIComponent(name)}&s=nm`; };
  const personLink = (name) => `<a class="ext" href="${imdb(name)}" target="_blank" rel="noopener" title="IMDb · ${escapeHtml(name)}" ${stop}>${extIcon}</a>`;
  const filmInline = (movie, trailer) => `<span class="film" data-movie="${escapeHtml(movie)}"><em>${escapeHtml(movie)}</em>${movieLinks(movie, trailer)}</span>`;
  const personInline = (name) => `<span class="person" data-person="${escapeHtml(name)}" tabindex="0"><em>${escapeHtml(name)}</em>${personLink(name)}</span>`;
  function showYear(cy) { return state.yearBasis === "film" ? cy - 1 : cy; }
  function isFilmYear() { return state.yearBasis === "film"; }
  function moviePosterHTML(title) { const img = thumbForMovie(title); return img ? `<div class="tip-photo tip-poster"><img src="${movieImageURL(img, "w342")}" alt="" loading="lazy"></div>` : ""; }
  function studyAnchorHTML(c) { if (!engine.isStudy()) return ""; const img = thumbForMovie(c.movie); const m = (window.MOVIES || {})[c.movie]; if (!img && !m?.overview) return ""; return `<div class="study-anchor">${img ? `<div class="study-photo"><img src="${movieImageURL(img, "w342")}" alt="" loading="lazy"></div>` : ""}${m?.overview ? `<div class="study-blurb">${escapeHtml(m.overview)}</div>` : ""}</div>`; }

  // Render
  function render() {
    const ord = engine.activeOrder();
    const { learned, total } = engine.learnedAndTotal();
    const c = engine.currentCard();
    scopeTextEl.textContent = `${showYear(state.range.from)}–${showYear(state.range.to)}`;
    scopeExtrasEl.textContent = state.includeNominees ? "· w/ nominees" : "";
    if (!c) { counter.textContent = `${learned} / ${total}`; progress.style.width = total ? `${(learned / total) * 100}%` : "0%"; front.tag.textContent = "All caught up"; front.prompt.textContent = ""; front.text.innerHTML = `<span style="font-size:.5em;color:var(--ink-soft);font-family:inherit">Every card in this range is learned. Open the deck chip and click <em>Start over</em>, or expand the year range.</span>`; back.body.innerHTML = ""; engine.renderScoreStars(null); return; }
    counter.textContent = `${state.idx + 1} / ${ord.length}`; progress.style.width = `${((state.idx + 1) / ord.length) * 100}%`;
    const isWinner = c.status === "winner"; const isImageMode = state.direction === "i2m" && HAS_IMAGES; const isSlateView = state.direction === "y2m" && state.includeNominees;
    frontFace.classList.toggle("image-mode", isImageMode); imageStage.hidden = !isImageMode;
    if (isImageMode) setImage(c);
    else if (state.direction === "y2m" || state.direction === "study") { front.tag.textContent = state.direction === "study" ? "Study" : (isFilmYear() ? "Film year" : "Ceremony"); front.prompt.textContent = isSlateView ? "Best Picture slate of" : (isFilmYear() ? "Movie that won Best Picture" : "Won Best Picture in"); front.text.innerHTML = `<span>${showYear(c.year)}</span>`; }
    else { front.tag.textContent = isWinner ? "Best Picture" : "Best Picture · Nominee"; front.prompt.textContent = isFilmYear() ? "Year of release?" : (isWinner ? "What year did this win?" : "What year was this nominated?"); front.text.innerHTML = `<span>${escapeHtml(c.movie)}</span>${movieLinks(c.movie, c.trailer)}`; }
    let backHTML = "";
    if (isSlateView) { back.tag.textContent = "Best Picture"; backHTML = `<div class="prompt">${isFilmYear() ? `Released in ${showYear(c.year)}` : `${showYear(c.year)} ceremony`} · Best Picture slate</div><div class="slate"><div class="slate-row winner"><span class="slate-marker">★</span><span class="film" data-movie="${escapeHtml(c.movie)}"><em>${escapeHtml(c.movie)}</em></span>${movieLinks(c.movie, c.trailer)}</div>${(c.slate || []).map(n => `<div class="slate-row"><span class="slate-marker">·</span><span class="film" data-movie="${escapeHtml(n.movie)}"><em>${escapeHtml(n.movie)}</em></span>${movieLinks(n.movie, n.trailer)}</div>`).join("")}</div>`; }
    else {
      back.tag.textContent = state.direction === "m2y" ? "Ceremony" : "Best Picture";
      const statusBadge = isWinner ? `<span class="badge winner">Winner ★</span>` : `<span class="badge nominee">Nominated</span>`;
      let answerBlock; if (state.direction === "m2y") { const yp = isFilmYear() ? "Released in" : (isWinner ? "Won Best Picture in" : "Nominated for Best Picture in"); answerBlock = `<div class="prompt">${yp}</div><div class="answer"><span class="year" data-year="${c.year}">${showYear(c.year)}</span></div><div class="prompt" style="margin-top:6px"><span class="film" data-movie="${escapeHtml(c.movie)}">${escapeHtml(c.movie)}</span> ${movieLinks(c.movie, c.trailer)} ${statusBadge}</div>`; }
      else { const yl = isFilmYear() ? `Released in ${showYear(c.year)} · Best Picture` : `${showYear(c.year)} ceremony · Best Picture`; answerBlock = `<div class="prompt">${yl} ${statusBadge}</div><div class="answer"><span class="film" data-movie="${escapeHtml(c.movie)}">${escapeHtml(c.movie)}</span>${movieLinks(c.movie, c.trailer)}</div>`; }
      const dirBlock = c.director ? `<div class="credits"><span class="label">dir.</span>${personInline(c.director)}</div>` : "";
      const starsBlock = c.stars && c.stars.length ? `<div class="credits"><span class="label">starring</span>${c.stars.map(personInline).join('<span class="sep">·</span>')}</div>` : "";
      const wonBlock = !isWinner ? `<div class="credits subtle"><span class="label">won that year:</span><span class="film" data-movie="${escapeHtml(c.winnerMovie)}"><em>${escapeHtml(c.winnerMovie)}</em></span></div>` : "";
      const nomBlock = (isWinner && c.slate && c.slate.length) ? `<div class="nominees"><h4>Other nominees · ${showYear(c.year)}</h4><div class="nominee-list">${c.slate.map(n => filmInline(n.movie, n.trailer)).join('<span class="nominee-sep">·</span>')}</div></div>` : "";
      backHTML = studyAnchorHTML(c) + answerBlock + dirBlock + starsBlock + wonBlock + nomBlock;
    }
    back.body.innerHTML = backHTML;
    const backHint = document.getElementById("backFooterHint");
    if (engine.isStudy()) backHint.innerHTML = `<span class="hint-desktop">Study mode · <kbd>←</kbd> <kbd>→</kbd> navigate · pick a quiz mode to start rating</span><span class="hint-touch">Study mode · swipe to navigate</span>`;
    else backHint.innerHTML = `<span class="hint-desktop">Tap to flip back · <kbd>Y</kbd> got it · <kbd>N</kbd> missed</span><span class="hint-touch">Tap to flip back</span>`;
    engine.renderScoreStars(c);
  }

  // Direction
  function setDirection(dir) {
    if (dir === state.direction) return;
    const wasStudy = state.direction === "study"; const goingStudy = dir === "study";
    if (!goingStudy) state.lastDir = dir; state.direction = dir; updateDirSeg(); engine.persist();
    if (goingStudy) { engine.cardEl.classList.add("flipped"); engine.syncNav(); render(); }
    else if (wasStudy) { engine.cardEl.classList.remove("flipped"); engine.syncNav(); render(); }
    else engine.unflipAndThen(() => render());
  }
  function updateDirSeg() { document.getElementById("dirYearToMovie").classList.toggle("on", state.direction === "y2m"); document.getElementById("dirMovieToYear").classList.toggle("on", state.direction === "m2y"); document.getElementById("dirImageToMovie").classList.toggle("on", state.direction === "i2m"); document.getElementById("dirStudy").classList.toggle("on", state.direction === "study"); }
  updateDirSeg();

  // Wire UI
  engine.bindStandardUI({ nextBtn: document.getElementById("nextBtn"), prevBtn: document.getElementById("prevBtn"), gotBtn: document.getElementById("gotBtn"), missedBtn: document.getElementById("missedBtn"), shuffleBtn: document.getElementById("shuffleIconBtn"), cardClickIgnore: "a, .person, .reroll", signal });
  document.getElementById("rerollBtn").addEventListener("click", (e) => { e.stopPropagation(); rerollImage(); }, { signal });
  document.getElementById("dirYearToMovie").addEventListener("click", () => setDirection("y2m"), { signal });
  document.getElementById("dirMovieToYear").addEventListener("click", () => setDirection("m2y"), { signal });
  document.getElementById("dirImageToMovie").addEventListener("click", () => { if (HAS_IMAGES) setDirection("i2m"); }, { signal });
  document.getElementById("dirStudy").addEventListener("click", () => setDirection("study"), { signal });

  // About modal
  const aboutModal = document.getElementById("aboutModal");
  document.getElementById("aboutSpan").textContent = String(_minYear);
  document.getElementById("aboutSpanTo").textContent = String(_maxYear);
  const { open: openAbout, close: closeAbout } = DeckEngine.bindModal(aboutModal, document.getElementById("aboutClose"), document.getElementById("aboutBtn"));

  // Range modal
  const rangeModal = document.getElementById("rangeModal");
  const rangeFromSel = document.getElementById("rangeFrom"); const rangeToSel = document.getElementById("rangeTo");
  const rangeCountEl = document.getElementById("rangeCount"); const rangePresetsEl = document.getElementById("rangePresets");
  const allYears = Array.from(new Set(DECK.map(e => e.year))).sort((a, b) => b - a);
  const PRESETS = [{ label: "Last 10 yrs", from: _maxYear - 9, to: _maxYear }, { label: "Last 30 yrs", from: _maxYear - 29, to: _maxYear }, { label: "Last 50 yrs", from: _maxYear - 49, to: _maxYear }, { label: "All", from: _minYear, to: _maxYear, isAll: true }];
  function populateYearPickers() { for (const sel of [rangeFromSel, rangeToSel]) { const cur = sel.value; sel.innerHTML = allYears.map(y => `<option value="${y}">${showYear(y)}</option>`).join(""); if (cur) sel.value = cur; } rangePresetsEl.innerHTML = PRESETS.map(p => { const label = p.isAll ? `All (${showYear(p.from)}–${showYear(p.to)})` : p.label; return `<button data-from="${p.from}" data-to="${p.to}">${label}</button>`; }).join(""); }
  populateYearPickers();
  function syncRangeUI() { rangeFromSel.value = state.range.from; rangeToSel.value = state.range.to; document.getElementById("includeNomineesChk").checked = !!state.includeNominees; document.getElementById("yearBasisChk").checked = state.yearBasis === "ceremony"; const yrs = DECK.filter(e => inRange(e.year)).length; const cards = POOL.filter(c => inRange(c.year)).length; rangeCountEl.innerHTML = `<em>${yrs}</em> ${yrs === 1 ? "year" : "years"} · <em>${cards}</em> cards in deck`; rangePresetsEl.querySelectorAll("button").forEach(b => b.classList.toggle("on", +b.dataset.from === state.range.from && +b.dataset.to === state.range.to)); }
  function applyRange(from, to) { if (from > to) [from, to] = [to, from]; state.range = { from, to }; state.idx = 0; engine.persist(); syncRangeUI(); engine.unflipAndThen(() => render()); }
  function openRangeModal() { syncRangeUI(); DeckEngine.openModal(rangeModal); }
  function closeRangeModal() { DeckEngine.closeModal(rangeModal); }
  document.getElementById("deckChip").addEventListener("click", openRangeModal, { signal });
  DeckEngine.bindModal(rangeModal, document.getElementById("rangeClose"));
  rangeFromSel.addEventListener("change", () => applyRange(+rangeFromSel.value, +rangeToSel.value), { signal });
  rangeToSel.addEventListener("change", () => applyRange(+rangeFromSel.value, +rangeToSel.value), { signal });
  rangePresetsEl.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) applyRange(+b.dataset.from, +b.dataset.to); }, { signal });
  document.getElementById("includeNomineesChk").addEventListener("change", () => { state.includeNominees = !state.includeNominees; rebuildPool(); engine.persist(); syncRangeUI(); engine.unflipAndThen(() => render()); }, { signal });
  document.getElementById("yearBasisChk").addEventListener("change", () => { state.yearBasis = state.yearBasis === "film" ? "ceremony" : "film"; engine.persist(); populateYearPickers(); syncRangeUI(); engine.unflipAndThen(() => render()); }, { signal });
  document.getElementById("resetProgressBtn").addEventListener("click", () => { closeRangeModal(); engine.reset(); }, { signal });

  // Trailer modal
  const trailerModal = document.getElementById("trailerModal");
  const trailerFrame = document.getElementById("trailerFrame");
  const CAN_EMBED = location.protocol !== "file:";
  function openTrailer(videoId) { if (!videoId) return; if (!CAN_EMBED) { window.open(`https://www.youtube.com/watch?v=${videoId}`, "_blank", "noopener"); return; } trailerFrame.src = `https://www.youtube.com/embed/${videoId}?autoplay=1&rel=0&modestbranding=1`; DeckEngine.openModal(trailerModal); }
  function closeTrailer() { if (trailerModal.hidden) return; trailerFrame.src = ""; DeckEngine.closeModal(trailerModal); }
  document.getElementById("trailerClose").addEventListener("click", closeTrailer, { signal });
  trailerModal.addEventListener("click", (e) => { if (e.target === trailerModal) closeTrailer(); }, { signal });
  document.addEventListener("click", (e) => { const a = e.target.closest("a.ext.play[data-video-id]"); if (!a) return; e.preventDefault(); e.stopPropagation(); openTrailer(a.dataset.videoId); }, { capture: true, signal });

  // Keyboard
  engine.bindKeyboard({ signal, extraKeys(e) {
    switch (e.key) {
      case "n": case "N": if (!engine.isStudy()) engine.missed(); return true;
      case "y": case "Y": if (!engine.isStudy()) engine.gotIt(); return true;
      case "l": case "L": setDirection(engine.isStudy() ? (state.lastDir || "y2m") : "study"); return true;
      case "ArrowDown": stepImage(+1); return true;
      case "ArrowUp": stepImage(-1); return true;
      case "?": if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return true; e.preventDefault(); if (aboutModal.hidden) openAbout(); else closeAbout(); return true;
      case "Escape": if (!trailerModal.hidden) closeTrailer(); else if (!rangeModal.hidden) closeRangeModal(); else if (!aboutModal.hidden) closeAbout(); else hideTip(true); return true;
    }
    return false;
  }});

  // Tooltips
  function fmtLifespan(p) { const b = (p.born || "").slice(0, 4), d = (p.died || "").slice(0, 4); if (b && d) return `${b}–${d}`; if (b) return `b. ${b}`; return null; }
  function truncate(str, n) { if (!str || str.length <= n) return str || ""; const cut = str.slice(0, n); const ls = cut.lastIndexOf(" "); return (ls > n - 30 ? cut.slice(0, ls) : cut) + "…"; }
  function fmtRuntime(min) { if (!min) return null; const h = Math.floor(min / 60), m = min % 60; return h ? `${h}h ${m}m` : `${m}m`; }
  function ordinal(n) { const s = ["th","st","nd","rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  function personRowHTML(p) { if (!p) return ""; const photoUrl = personImageURL(p); const photo = photoUrl ? `<div class="tip-photo"><img src="${photoUrl}" alt=""></div>` : `<div class="tip-photo">${escapeHtml((p.name||"?").trim().charAt(0))}</div>`; const meta = [p.role, p.country, fmtLifespan(p)].filter(Boolean).join('<span class="dot">·</span>'); const known = (p.knownFor || []).map(k => `<em>${escapeHtml(k.title)}</em>${k.year ? ` <span style="color:var(--ink-faint)">(${k.year})</span>` : ""}`).join(' <span style="color:var(--ink-faint)">·</span> '); return `${photo}<div class="tip-info"><div class="tip-name"><span>${escapeHtml(p.name || "")}</span><a class="ext" href="${imdb(p.name||"")}" target="_blank" rel="noopener" title="IMDb">${extIcon}</a></div>${meta ? `<div class="tip-meta">${meta}</div>` : ""}${known ? `<div class="tip-known"><span class="label">Known for</span>${known}</div>` : ""}</div>`; }
  function duoMemberHTML(p) { if (!p) return ""; const photoUrl = personImageURL(p); const photo = photoUrl ? `<div class="tip-photo"><img src="${photoUrl}" alt=""></div>` : `<div class="tip-photo">${escapeHtml((p.name||"?").trim().charAt(0))}</div>`; const meta = [p.role, p.country, fmtLifespan(p)].filter(Boolean).join('<span class="dot">·</span>'); return `<div class="duo-member">${photo}<div class="tip-info"><div class="tip-name"><span>${escapeHtml(p.name || "")}</span><a class="ext" href="${imdb(p.name||"")}" target="_blank" rel="noopener" title="IMDb">${extIcon}</a></div>${meta ? `<div class="tip-meta">${meta}</div>` : ""}</div></div>`; }
  function tipHTML(el) {
    if (el.dataset.person) { const p = (window.PEOPLE || {})[el.dataset.person]; if (!p) return `<div class="tip-empty">No info for ${escapeHtml(el.dataset.person)}</div>`; if (p.duo && p.duo.length) return `<div class="tip-duo">${p.duo.map(duoMemberHTML).join("")}</div>`; return personRowHTML(p); }
    if (el.dataset.movie) { const m = (window.MOVIES || {})[el.dataset.movie]; if (!m) return `<div class="tip-empty">No info for ${escapeHtml(el.dataset.movie)}</div>`; const meta = [m.release_date ? m.release_date.slice(0, 4) : null, fmtRuntime(m.runtime), m.rating ? `★ ${m.rating}` : null].filter(Boolean).join('<span class="dot">·</span>'); const href = m.imdb_id ? `https://www.imdb.com/title/${m.imdb_id}/` : `https://www.imdb.com/find/?q=${encodeURIComponent(el.dataset.movie)}&s=tt`; return `${moviePosterHTML(el.dataset.movie)}<div class="tip-info" style="flex:1"><div class="tip-name"><span>${escapeHtml(el.dataset.movie)}</span><a class="ext" href="${href}" target="_blank" rel="noopener" title="IMDb">${extIcon}</a></div>${m.tagline ? `<div class="tip-tagline">"${escapeHtml(m.tagline)}"</div>` : ""}${meta ? `<div class="tip-meta">${meta}</div>` : ""}${m.overview ? `<div class="tip-blurb">${escapeHtml(truncate(m.overview, 260))}</div>` : ""}</div>`; }
    if (el.dataset.year) { const year = +el.dataset.year; const entry = DECK.find(e => e.year === year); if (!entry) return `<div class="tip-empty">${year}</div>`; const noms = entry.nominees ? entry.nominees.length : 0; return `${moviePosterHTML(entry.movie)}<div class="tip-info" style="flex:1"><div class="tip-name"><span>${ordinal(year - 1928)} Academy Awards</span></div><div class="tip-meta">Ceremony · ${year}</div><div class="tip-blurb"><strong style="color:var(--ink)">Best Picture:</strong> ${escapeHtml(entry.movie)}<br>${noms} other ${noms === 1 ? "nominee" : "nominees"} that year.</div></div>`; }
    return "";
  }
  const hideTip = engine.bindTooltips({ tipEl: document.getElementById("tooltip"), selector: ".person[data-person], .film[data-movie], .year[data-year]", signal, tipHTML });

  render();
}
