import { DeckEngine, loadScript, escapeHtml } from '../deck-engine.js';

export const meta = { id: "grammys", emoji: "🏆", name: "Grammy Big Four" };

export const segments = `
  <button data-mode="a2w" class="on">Artist → Award</button>
  <button data-mode="w2a">Work → Artist</button>
  <button data-mode="y2w">Year → Winner</button>
  <button data-mode="study">Study</button>`;

export const frontExtras = ``;

export const modals = `
  <div class="modal-backdrop" id="aboutModal" hidden>
    <div class="panel panel-wide" role="dialog" aria-label="About">
      <button class="modal-close" id="aboutClose" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <h3 class="panel-title">Grammy Big Four · Crammys</h3>
      <p class="panel-sub">Flashcards for <span id="grammysCount">0</span> Grammy "Big Four" winners (<span id="grammysYears">1959–2025</span>).</p>
      <div class="about-section"><h4>Keyboard shortcuts</h4>
        <div class="kbd-grid">
          <div><kbd>Space</kbd> reveal answer</div>
          <div><kbd>←</kbd> <kbd>→</kbd> previous / next</div>
          <div><kbd>Y</kbd> got it</div>
          <div><kbd>N</kbd> missed</div>
          <div><kbd>S</kbd> shuffle</div>
          <div><kbd>R</kbd> reset progress</div>
          <div><kbd>L</kbd> toggle Study mode</div>
          <div><kbd>T</kbd> toggle theme</div>
          <div><kbd>?</kbd> this dialog</div>
          <div><kbd>Esc</kbd> close any popup</div>
        </div>
      </div>
      <div class="about-section"><h4>Data &amp; credits</h4>
        <p>Winner data from <a href="https://www.wikidata.org/" target="_blank" rel="noopener">Wikidata</a> and
          <a href="https://en.wikipedia.org/wiki/Grammy_Award" target="_blank" rel="noopener">Wikipedia</a>.
          Spotify links via the <a href="https://developer.spotify.com/" target="_blank" rel="noopener">Spotify Web API</a>.
        </p>
      </div>
    </div>
  </div>
  <div class="modal-backdrop" id="deckModal" hidden>
    <div class="panel" role="dialog" aria-label="Deck">
      <button class="modal-close" id="deckClose" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <h3 class="panel-title">Deck</h3>
      <p class="panel-sub">Filter by ceremony year range and category.</p>
      <h4 class="panel-section">Ceremony year range</h4>
      <div class="range-presets" id="yearPresets"></div>
      <div class="range-inputs">
        <label>From <select id="yearFrom"></select></label>
        <span class="range-dash">–</span>
        <label>To <select id="yearTo"></select></label>
      </div>
      <h4 class="panel-section">Category</h4>
      <div class="option-grid" id="catGrid"></div>
      <div class="panel-foot">
        <span id="deckCount" class="panel-count"></span>
        <button class="link-danger" id="resetProgressBtn" title="Clear every card's score and start fresh">Start over</button>
      </div>
    </div>
  </div>`;

export async function init({ signal }) {
  await loadScript("grammys-data.js?v=2");

  const DATA = window.GRAMMYS_DATA || [];
  if (!DATA.length) {
    document.querySelector(".card-stage").innerHTML =
      `<div style="text-align:center;padding:60px 20px;color:var(--ink-soft)">No data yet — run <code>python3 fetch_grammys.py</code> to populate <code>grammys-data.js</code>.</div>`;
    return;
  }

  const cardId = (c) => `${c.categoryShort}|${c.artist}|${c.year}`;
  const BY_ID = new Map(DATA.map(c => [cardId(c), c]));
  const allIds = DATA.map(cardId);
  const TOTAL = DATA.length;
  const SCORE_RETIRED = 3;

  const ALL_CATS = ["AOTY", "ROTY", "SOTY", "BNA"];
  const CAT_LABELS = { AOTY: "Album of the Year", ROTY: "Record of the Year", SOTY: "Song of the Year", BNA: "Best New Artist" };

  const minYear = Math.min(...DATA.filter(d => d.year).map(d => d.year));
  const maxYear = Math.max(...DATA.filter(d => d.year).map(d => d.year));

  const engine = new DeckEngine({
    storeKey: "crammys-grammys-v1",
    defaultState: { mode: "a2w", idx: 0, order: null, scores: {}, cats: ALL_CATS.slice(), yearFrom: 1990, yearTo: maxYear, lastMode: "a2w" },
    migrateState(s) {
      if (!s.scores || typeof s.scores !== "object") s.scores = {};
      if (!Array.isArray(s.cats) || !s.cats.length) s.cats = ALL_CATS.slice();
      if (typeof s.yearFrom !== "number") s.yearFrom = 1990;
      if (typeof s.yearTo !== "number") s.yearTo = maxYear;
      s.yearFrom = Math.max(minYear, Math.min(maxYear, s.yearFrom));
      s.yearTo = Math.max(minYear, Math.min(maxYear, s.yearTo));
      if (s.yearFrom > s.yearTo) s.yearFrom = s.yearTo;
      if (!s.lastMode || s.lastMode === "study") s.lastMode = "a2w";
      return s;
    },
    allIds, byId: BY_ID, cardId,
    activeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      if (!c.year) return false;
      if (c.year < state.yearFrom || c.year > state.yearTo) return false;
      if (!state.cats.includes(c.categoryShort)) return false;
      if (engine.scoreOf(id) >= SCORE_RETIRED) return false;
      // In w2a mode, skip BNA entries (no work to show)
      if (state.mode === "w2a" && c.categoryShort === "BNA") return false;
      return true;
    },
    inScopeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      if (!c.year) return false;
      if (c.year < state.yearFrom || c.year > state.yearTo) return false;
      if (!state.cats.includes(c.categoryShort)) return false;
      if (state.mode === "w2a" && c.categoryShort === "BNA") return false;
      return true;
    },
    isStudyMode: (state) => state.mode === "study",
    render: () => render(),
    onBeforeNavigate: () => {},
    cardEl: document.getElementById("card"),
    navRowEl: document.getElementById("navRow"),
    scoreStarsFrontEl: document.getElementById("scoreStarsFront"),
    scoreStarsBackEl: document.getElementById("scoreStarsBack"),
  });

  const state = engine.state;
  const frontFace = document.getElementById("frontFace");
  const front = { prompt: document.getElementById("frontPrompt"), text: document.getElementById("frontText"), tag: document.getElementById("frontTag") };
  const back = { tag: document.getElementById("backTag"), body: document.getElementById("backBody") };
  const counter = document.getElementById("counter");
  const scopeText = document.getElementById("scopeText");
  const scopeExtras = document.getElementById("scopeExtras");
  const progress = document.getElementById("progress");

  const stop = `onclick="event.stopPropagation()"`;
  const extIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7M9 7h8v8"/></svg>';
  const spotifyIcon = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.6 0 12 0zm5.5 17.3c-.2.3-.6.4-1 .2-2.7-1.6-6-2-10-1.1-.4.1-.7-.2-.8-.5-.1-.4.2-.7.5-.8 4.3-1 8.1-.6 11.1 1.2.3.2.4.7.2 1zm1.5-3.3c-.3.4-.8.5-1.2.3-3-1.9-7.7-2.4-11.3-1.3-.4.1-.9-.1-1-.5-.1-.4.1-.9.5-1 4.1-1.3 9.2-.7 12.7 1.5.3.2.5.7.3 1zm.1-3.4c-3.7-2.2-9.7-2.4-13.2-1.3-.5.2-1.1-.1-1.2-.6-.2-.5.1-1.1.6-1.2 4-1.2 10.7-1 14.9 1.5.5.3.6.9.4 1.3-.3.4-.9.6-1.5.3z"/></svg>';

  const CAT_BADGE_CLASS = { AOTY: "winner", ROTY: "nominee", SOTY: "shortlist", BNA: "special" };

  function categoryBadge(shortCat) {
    const cls = CAT_BADGE_CLASS[shortCat] || "nominee";
    return `<span class="badge ${cls}">${escapeHtml(CAT_LABELS[shortCat] || shortCat)}</span>`;
  }

  function spotifyUrl(c) {
    if (!c.spotify) return null;
    if (c.spotifyType === "album") return `https://open.spotify.com/album/${c.spotify}`;
    if (c.spotifyType === "track") return `https://open.spotify.com/track/${c.spotify}`;
    if (c.spotifyType === "artist") return `https://open.spotify.com/artist/${c.spotify}`;
    return null;
  }

  function artistLink(c) {
    if (c.artistWikipedia) {
      return `<a href="${c.artistWikipedia}" target="_blank" rel="noopener" class="person-link" ${stop}>${escapeHtml(c.artist)}</a>`;
    }
    return escapeHtml(c.artist);
  }

  function detailGrid(c, showYear) {
    const rows = [];
    // Category badge
    rows.push(`<div class="row"><span class="label">Category</span><span class="val">${categoryBadge(c.categoryShort)}</span></div>`);
    // Ceremony year
    if (showYear && c.year) {
      rows.push(`<div class="row"><span class="label">Ceremony</span><span class="val">${c.year}</span></div>`);
    }
    // Artist
    rows.push(`<div class="row"><span class="label">Artist</span><span class="val">${artistLink(c)}</span></div>`);
    // Work
    if (c.work) {
      const sUrl = spotifyUrl(c);
      const workHtml = sUrl
        ? `${escapeHtml(c.work)} <a class="ext" href="${sUrl}" target="_blank" rel="noopener" title="Listen on Spotify" ${stop}>${spotifyIcon}</a>`
        : escapeHtml(c.work);
      rows.push(`<div class="row"><span class="label">${c.categoryShort === "AOTY" ? "Album" : "Song"}</span><span class="val">${workHtml}</span></div>`);
    } else if (c.categoryShort === "BNA") {
      // For BNA, show Spotify link to artist
      const sUrl = spotifyUrl(c);
      if (sUrl) {
        rows.push(`<div class="row"><span class="label">Listen</span><span class="val"><a class="ext" href="${sUrl}" target="_blank" rel="noopener" title="Listen on Spotify" ${stop}>${spotifyIcon} Spotify</a></span></div>`);
      }
    }
    // Description
    if (c.artistDescription) {
      rows.push(`<div class="row"><span class="label">About</span><span class="val">${escapeHtml(c.artistDescription)}</span></div>`);
    }
    return rows.length ? `<div class="detail-grid">${rows.join("")}</div>` : "";
  }

  function render() {
    const ord = engine.activeOrder();
    const { learned, total } = engine.learnedAndTotal();
    const c = engine.currentCard();

    scopeText.textContent = `${state.yearFrom}–${state.yearTo}`;
    const offCats = ALL_CATS.length - state.cats.length;
    const extras = [];
    if (offCats > 0) extras.push(`${state.cats.length}/${ALL_CATS.length} cat`);
    scopeExtras.textContent = extras.length ? "· " + extras.join(" · ") : "";

    if (!c) {
      counter.textContent = `${learned} / ${total}`;
      progress.style.width = total ? `${(learned / total) * 100}%` : "0%";
      frontFace.classList.remove("image-mode");
      front.tag.textContent = "All caught up"; front.prompt.textContent = "";
      front.text.innerHTML = `<span style="font-size:.5em;color:var(--ink-soft);font-family:inherit">Every winner in this scope is learned. Open the deck chip and click <em>Start over</em>, or expand the filter.</span>`;
      back.body.innerHTML = ""; engine.renderScoreStars(null); return;
    }

    counter.textContent = `${state.idx + 1} / ${ord.length}`;
    progress.style.width = `${((state.idx + 1) / ord.length) * 100}%`;
    frontFace.classList.remove("image-mode");

    const wikiLink = c.artistWikipedia
      ? `<a class="ext" href="${c.artistWikipedia}" target="_blank" rel="noopener" title="Wikipedia" ${stop}>${extIcon}</a>`
      : "";
    const sUrl = spotifyUrl(c);
    const spotifyLink = sUrl
      ? `<a class="ext" href="${sUrl}" target="_blank" rel="noopener" title="Spotify" ${stop}>${spotifyIcon}</a>`
      : "";

    if (state.mode === "a2w") {
      // Front: artist name → Back: what they won + year
      front.tag.textContent = "Artist";
      front.prompt.textContent = "What did they win?";
      front.text.innerHTML = `<span>${escapeHtml(c.artist)}</span>`;

      back.tag.textContent = "Award";
      const answerText = c.work
        ? `${CAT_LABELS[c.categoryShort]} (${c.year})`
        : `${CAT_LABELS[c.categoryShort]} (${c.year})`;
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.artist)} ${wikiLink}${spotifyLink}</div>
          <div class="answer"><span>${escapeHtml(answerText)}</span></div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + detailGrid(c, false);

    } else if (state.mode === "w2a") {
      // Front: work title → Back: who won
      front.tag.textContent = c.categoryShort === "AOTY" ? "Album" : "Song";
      front.prompt.textContent = "Who won?";
      front.text.innerHTML = `<span>${escapeHtml(c.work || "—")}</span>`;

      back.tag.textContent = "Winner";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.work || "—")} ${spotifyLink}</div>
          <div class="answer"><span>${artistLink(c)}</span> ${wikiLink}</div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + detailGrid(c, true);

    } else if (state.mode === "y2w") {
      // Front: year + category → Back: who won
      front.tag.textContent = String(c.year);
      front.prompt.textContent = "Who won?";
      front.text.innerHTML = `<span>${escapeHtml(CAT_LABELS[c.categoryShort])}</span>`;

      back.tag.textContent = "Winner";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${c.year} · ${escapeHtml(CAT_LABELS[c.categoryShort])}</div>
          <div class="answer"><span>${artistLink(c)}</span> ${wikiLink}${spotifyLink}</div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + detailGrid(c, false);

    } else {
      // Study mode
      front.tag.textContent = "Study";
      front.prompt.textContent = "";
      front.text.textContent = c.artist;

      back.tag.textContent = "Winner";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${c.year} · ${escapeHtml(CAT_LABELS[c.categoryShort])}</div>
          <div class="answer"><span>${artistLink(c)}</span> ${wikiLink}${spotifyLink}</div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + detailGrid(c, false);
    }

    const backHint = document.getElementById("backFooterHint");
    if (engine.isStudy()) backHint.innerHTML = `<span class="hint-desktop">Study mode · <kbd>←</kbd> <kbd>→</kbd> navigate · pick a quiz mode to start rating</span><span class="hint-touch">Study mode · swipe to navigate</span>`;
    else backHint.innerHTML = `<span class="hint-desktop">Tap to flip back · <kbd>Y</kbd> got it · <kbd>N</kbd> missed</span><span class="hint-touch">Tap to flip back</span>`;
    engine.renderScoreStars(c);
  }

  // Mode switching
  function setMode(m) {
    if (m === state.mode) return;
    const wasStudy = state.mode === "study"; const goingStudy = m === "study";
    if (!goingStudy) state.lastMode = m;
    state.mode = m; state.idx = 0;
    document.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.mode === m));
    engine.persist();
    if (goingStudy) { engine.cardEl.classList.add("flipped"); engine.syncNav(); render(); }
    else if (wasStudy) { engine.cardEl.classList.remove("flipped"); engine.syncNav(); render(); }
    else engine.unflipAndThen(render);
  }

  // Wire UI
  engine.bindStandardUI({ nextBtn: document.getElementById("nextBtn"), prevBtn: document.getElementById("prevBtn"), gotBtn: document.getElementById("gotBtn"), missedBtn: document.getElementById("missedBtn"), shuffleBtn: document.getElementById("shuffleIconBtn"), cardClickIgnore: "a, button", signal });
  document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode), { signal }));
  document.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.mode === state.mode));

  // About modal
  const aboutModal = document.getElementById("aboutModal");
  document.getElementById("grammysCount").textContent = String(TOTAL);
  document.getElementById("grammysYears").textContent = `${minYear}–${maxYear}`;
  const { open: openAbout, close: closeAbout } = DeckEngine.bindModal(aboutModal, document.getElementById("aboutClose"), document.getElementById("aboutBtn"));

  // Deck modal
  const deckModal = document.getElementById("deckModal");
  const catGridEl = document.getElementById("catGrid");
  const deckCountEl = document.getElementById("deckCount");
  const yearFromSel = document.getElementById("yearFrom");
  const yearToSel = document.getElementById("yearTo");
  const yearPresetsEl = document.getElementById("yearPresets");

  const allYears = Array.from(new Set(DATA.filter(d => d.year).map(d => d.year))).sort((a, b) => b - a);
  for (const sel of [yearFromSel, yearToSel]) {
    sel.innerHTML = allYears.map(y => `<option value="${y}">${y}</option>`).join("");
  }
  const YEAR_PRESETS = [
    { label: "1990+", from: 1990, to: maxYear },
    { label: "2000+", from: 2000, to: maxYear },
    { label: "2010+", from: 2010, to: maxYear },
    { label: `All (${minYear}–${maxYear})`, from: minYear, to: maxYear },
  ];
  yearPresetsEl.innerHTML = YEAR_PRESETS.map(p =>
    `<button data-from="${p.from}" data-to="${p.to}">${p.label}</button>`
  ).join("");

  function countInScope() {
    return DATA.filter(c => {
      if (!c.year || c.year < state.yearFrom || c.year > state.yearTo) return false;
      if (!state.cats.includes(c.categoryShort)) return false;
      if (state.mode === "w2a" && c.categoryShort === "BNA") return false;
      return true;
    }).length;
  }

  function syncDeckModal() {
    yearFromSel.value = state.yearFrom;
    yearToSel.value = state.yearTo;
    yearPresetsEl.querySelectorAll("button").forEach(b => {
      b.classList.toggle("on", +b.dataset.from === state.yearFrom && +b.dataset.to === state.yearTo);
    });
    catGridEl.innerHTML = ALL_CATS.map(cat =>
      `<label><input type="checkbox" value="${cat}" ${state.cats.includes(cat) ? "checked" : ""}><span>${escapeHtml(CAT_LABELS[cat])}</span></label>`
    ).join("");
    deckCountEl.innerHTML = `<em>${countInScope()}</em> winners in deck`;
  }

  function applyYearRange(from, to) {
    if (from > to) [from, to] = [to, from];
    state.yearFrom = from;
    state.yearTo = to;
    state.idx = 0;
    engine.persist();
    syncDeckModal();
    engine.unflipAndThen(render);
  }

  const { close: closeDeck } = DeckEngine.bindModal(deckModal, document.getElementById("deckClose"));
  document.getElementById("deckChip").addEventListener("click", () => { syncDeckModal(); DeckEngine.openModal(deckModal); }, { signal });
  yearFromSel.addEventListener("change", () => applyYearRange(+yearFromSel.value, +yearToSel.value), { signal });
  yearToSel.addEventListener("change", () => applyYearRange(+yearFromSel.value, +yearToSel.value), { signal });
  yearPresetsEl.addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    applyYearRange(+b.dataset.from, +b.dataset.to);
  }, { signal });
  catGridEl.addEventListener("change", (e) => {
    const inp = e.target.closest("input"); if (!inp) return;
    const cat = inp.value;
    if (inp.checked && !state.cats.includes(cat)) state.cats.push(cat);
    else if (!inp.checked) state.cats = state.cats.filter(x => x !== cat);
    if (!state.cats.length) state.cats = [cat];
    state.idx = 0; engine.persist(); syncDeckModal(); engine.unflipAndThen(render);
  }, { signal });
  document.getElementById("resetProgressBtn").addEventListener("click", () => { closeDeck(); engine.reset(); }, { signal });

  // Keyboard
  engine.bindKeyboard({ signal, extraKeys(e) {
    switch (e.key) {
      case "n": case "N": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.missed(); return true;
      case "y": case "Y": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.gotIt(); return true;
      case "l": case "L": setMode(engine.isStudy() ? (state.lastMode || "a2w") : "study"); return true;
      case "?": e.preventDefault(); if (aboutModal.hidden) openAbout(); else closeAbout(); return true;
      case "Escape": if (!aboutModal.hidden) closeAbout(); else if (!deckModal.hidden) closeDeck(); return true;
    }
    return false;
  }});

  if (engine.isStudy()) engine.cardEl.classList.add("flipped");
  render();
}
