import { DeckEngine, loadScript, escapeHtml } from '../deck-engine.js';

export const meta = { id: "songs", emoji: "🎵", name: "Best Original Song" };

export const segments = `
  <button data-mode="s2f" class="on">Song → Film</button>
  <button data-mode="f2s">Film → Song</button>
  <button data-mode="study">Study</button>`;

export const frontExtras = ``;

export const modals = `
  <div class="modal-backdrop" id="aboutModal" hidden>
    <div class="panel panel-wide" role="dialog" aria-label="About">
      <button class="modal-close" id="aboutClose" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <h3 class="panel-title">Best Original Song · Crammys</h3>
      <p class="panel-sub">Flashcards for <span id="songsCount">0</span> Academy Award Best Original Song winners (<span id="songsYears">1935–2025</span>).</p>
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
        <p>Song data from <a href="https://www.wikidata.org/" target="_blank" rel="noopener">Wikidata</a> and
          <a href="https://en.wikipedia.org/wiki/Academy_Award_for_Best_Original_Song" target="_blank" rel="noopener">Wikipedia</a>.
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
      <p class="panel-sub">Filter by ceremony year range.</p>
      <h4 class="panel-section">Ceremony year range</h4>
      <div class="range-presets" id="yearPresets"></div>
      <div class="range-inputs">
        <label>From <select id="yearFrom"></select></label>
        <span class="range-dash">–</span>
        <label>To <select id="yearTo"></select></label>
      </div>
      <div class="panel-foot">
        <span id="deckCount" class="panel-count"></span>
        <button class="link-danger" id="resetProgressBtn" title="Clear every card's score and start fresh">Start over</button>
      </div>
    </div>
  </div>`;

export async function init({ signal }) {
  await loadScript("songs-data.js?v=2");

  const DATA = window.SONGS_DATA || [];
  if (!DATA.length) {
    document.querySelector(".card-stage").innerHTML =
      `<div style="text-align:center;padding:60px 20px;color:var(--ink-soft)">No data yet — run <code>python3 fetch_songs.py</code> to populate <code>songs-data.js</code>.</div>`;
    return;
  }

  const cardId = (c) => c.wikidata || `${c.song}|${c.year}`;
  const BY_ID = new Map(DATA.map(c => [cardId(c), c]));
  const allIds = DATA.map(cardId);
  const TOTAL = DATA.length;
  const SCORE_RETIRED = 3;

  const minYear = Math.min(...DATA.filter(d => d.year).map(d => d.year));
  const maxYear = Math.max(...DATA.filter(d => d.year).map(d => d.year));

  const engine = new DeckEngine({
    storeKey: "crammys-songs-v1",
    defaultState: { mode: "s2f", idx: 0, order: null, scores: {}, yearFrom: 1990, yearTo: maxYear, lastMode: "s2f" },
    migrateState(s) {
      if (!s.scores || typeof s.scores !== "object") s.scores = {};
      if (typeof s.yearFrom !== "number") s.yearFrom = 1990;
      if (typeof s.yearTo !== "number") s.yearTo = maxYear;
      s.yearFrom = Math.max(minYear, Math.min(maxYear, s.yearFrom));
      s.yearTo = Math.max(minYear, Math.min(maxYear, s.yearTo));
      if (s.yearFrom > s.yearTo) s.yearFrom = s.yearTo;
      if (!s.lastMode || s.lastMode === "study") s.lastMode = "s2f";
      return s;
    },
    allIds, byId: BY_ID, cardId,
    activeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      if (!c.year) return false;
      if (c.year < state.yearFrom || c.year > state.yearTo) return false;
      if (engine.scoreOf(id) >= SCORE_RETIRED) return false;
      return true;
    },
    inScopeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      if (!c.year) return false;
      if (c.year < state.yearFrom || c.year > state.yearTo) return false;
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

  function fmtList(arr) {
    if (!arr || !arr.length) return "—";
    if (arr.length === 1) return escapeHtml(arr[0]);
    if (arr.length === 2) return `${escapeHtml(arr[0])} and ${escapeHtml(arr[1])}`;
    return arr.slice(0, -1).map(escapeHtml).join(", ") + ", and " + escapeHtml(arr[arr.length - 1]);
  }
  function linkedName(name) {
    const slug = encodeURIComponent(name.replace(/ /g, "_"));
    return `<a href="https://en.wikipedia.org/wiki/${slug}" target="_blank" rel="noopener" class="person-link" ${stop}>${escapeHtml(name)}</a>`;
  }
  function fmtLinkedList(arr) {
    if (!arr || !arr.length) return "—";
    if (arr.length === 1) return linkedName(arr[0]);
    if (arr.length === 2) return `${linkedName(arr[0])} and ${linkedName(arr[1])}`;
    return arr.slice(0, -1).map(linkedName).join(", ") + ", and " + linkedName(arr[arr.length - 1]);
  }

  function detailGrid(c, showYear) {
    const rows = [];
    if (showYear && c.year) {
      rows.push(`<div class="row"><span class="label">Ceremony</span><span class="val">${c.year} <em>(${c.filmYear || c.year - 1} film)</em></span></div>`);
    }
    if (c.film) {
      rows.push(`<div class="row"><span class="label">Film</span><span class="val">${escapeHtml(c.film)}</span></div>`);
    }
    if (c.songwriters && c.songwriters.length) {
      rows.push(`<div class="row"><span class="label">Written by</span><span class="val">${fmtLinkedList(c.songwriters)}</span></div>`);
    }
    if (c.performers && c.performers.length) {
      rows.push(`<div class="row"><span class="label">Performed by</span><span class="val">${fmtLinkedList(c.performers)}</span></div>`);
    }
    // External links row
    const links = [];
    if (c.spotify) {
      links.push(`<a class="ext" href="https://open.spotify.com/track/${c.spotify}" target="_blank" rel="noopener" title="Listen on Spotify" ${stop}>${spotifyIcon} Spotify</a>`);
    }
    if (c.wikipedia) {
      links.push(`<a class="ext" href="${c.wikipedia}" target="_blank" rel="noopener" title="Wikipedia" ${stop}>${extIcon} Wikipedia</a>`);
    }
    if (links.length) {
      rows.push(`<div class="row"><span class="label">Links</span><span class="val">${links.join(" &nbsp; ")}</span></div>`);
    }
    return rows.length ? `<div class="detail-grid">${rows.join("")}</div>` : "";
  }

  function render() {
    const ord = engine.activeOrder();
    const { learned, total } = engine.learnedAndTotal();
    const c = engine.currentCard();

    scopeText.textContent = `${state.yearFrom}–${state.yearTo}`;
    scopeExtras.textContent = "";

    if (!c) {
      counter.textContent = `${learned} / ${total}`;
      progress.style.width = total ? `${(learned / total) * 100}%` : "0%";
      frontFace.classList.remove("image-mode");
      front.tag.textContent = "All caught up"; front.prompt.textContent = "";
      front.text.innerHTML = `<span style="font-size:.5em;color:var(--ink-soft);font-family:inherit">Every song in this scope is learned. Open the deck chip and click <em>Start over</em>, or expand the filter.</span>`;
      back.body.innerHTML = ""; engine.renderScoreStars(null); return;
    }

    counter.textContent = `${state.idx + 1} / ${ord.length}`;
    progress.style.width = `${((state.idx + 1) / ord.length) * 100}%`;
    frontFace.classList.remove("image-mode");

    const wikiLink = c.wikipedia
      ? `<a class="ext" href="${c.wikipedia}" target="_blank" rel="noopener" title="Wikipedia" ${stop}>${extIcon}</a>`
      : "";
    const spotifyLink = c.spotify
      ? `<a class="ext" href="https://open.spotify.com/track/${c.spotify}" target="_blank" rel="noopener" title="Spotify" ${stop}>${spotifyIcon}</a>`
      : "";

    if (state.mode === "s2f") {
      // Front: song title + performer → Back: film + details
      front.tag.textContent = "Song";
      front.prompt.textContent = "From which film?";
      const performedBy = c.performers && c.performers.length
        ? `<div class="prompt" style="margin-top:8px;font-size:12px">${fmtList(c.performers)}</div>` : "";
      front.text.innerHTML = `<span>${escapeHtml(c.song)}</span>${performedBy}`;

      back.tag.textContent = "Film";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.song)} ${wikiLink}${spotifyLink}</div>
          <div class="answer"><span>${escapeHtml(c.film || "—")}</span></div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + detailGrid(c, true);

    } else if (state.mode === "f2s") {
      // Front: film title + year → Back: song title + details
      front.tag.textContent = "Film";
      front.prompt.textContent = "Which song won?";
      front.text.innerHTML = `<span>${escapeHtml(c.film || "—")} <em>(${c.filmYear || "?"})</em></span>`;

      back.tag.textContent = "Song";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.film || "—")} (${c.filmYear || "?"}) ${wikiLink}</div>
          <div class="answer"><span>${escapeHtml(c.song)}</span> ${spotifyLink}</div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + detailGrid(c, true);

    } else {
      // Study mode
      front.tag.textContent = "Study";
      front.prompt.textContent = "";
      front.text.textContent = c.song;

      back.tag.textContent = "Song";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.film || "—")} (${c.filmYear || "?"})</div>
          <div class="answer"><span>${escapeHtml(c.song)}</span> ${wikiLink}${spotifyLink}</div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + detailGrid(c, true);
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
  document.getElementById("songsCount").textContent = String(TOTAL);
  document.getElementById("songsYears").textContent = `${minYear}–${maxYear}`;
  const { open: openAbout, close: closeAbout } = DeckEngine.bindModal(aboutModal, document.getElementById("aboutClose"), document.getElementById("aboutBtn"));

  // Deck modal
  const deckModal = document.getElementById("deckModal");
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
      return true;
    }).length;
  }

  function syncDeckModal() {
    yearFromSel.value = state.yearFrom;
    yearToSel.value = state.yearTo;
    yearPresetsEl.querySelectorAll("button").forEach(b => {
      b.classList.toggle("on", +b.dataset.from === state.yearFrom && +b.dataset.to === state.yearTo);
    });
    deckCountEl.innerHTML = `<em>${countInScope()}</em> songs in deck`;
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
  document.getElementById("resetProgressBtn").addEventListener("click", () => { closeDeck(); engine.reset(); }, { signal });

  // Keyboard
  engine.bindKeyboard({ signal, extraKeys(e) {
    switch (e.key) {
      case "n": case "N": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.missed(); return true;
      case "y": case "Y": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.gotIt(); return true;
      case "l": case "L": setMode(engine.isStudy() ? (state.lastMode || "s2f") : "study"); return true;
      case "?": e.preventDefault(); if (aboutModal.hidden) openAbout(); else closeAbout(); return true;
      case "Escape": if (!aboutModal.hidden) closeAbout(); else if (!deckModal.hidden) closeDeck(); return true;
    }
    return false;
  }});

  if (engine.isStudy()) engine.cardEl.classList.add("flipped");
  render();
}
