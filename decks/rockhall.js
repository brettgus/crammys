import { DeckEngine, loadScript, escapeHtml } from '../deck-engine.js';

export const meta = { id: "rockhall", emoji: "🎸", name: "Rock & Roll Hall of Fame" };

export const segments = `
  <button data-mode="n2y" class="on">Name → Year</button>
  <button data-mode="p2n">Photo → Name</button>
  <button data-mode="study">Study</button>`;

export const frontExtras = `
  <div class="image-stage" id="photoStage" hidden>
    <img id="photoEl" alt="" />
    <div class="image-overlay">
      <div class="corner"><span>Photo</span></div>
      <div class="bottom">
        <div class="prompt">Who is this?</div>
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
      <h3 class="panel-title">Rock &amp; Roll Hall of Fame · Crammys</h3>
      <p class="panel-sub">Flashcards for <span id="rrhofCount">0</span> Rock &amp; Roll Hall of Fame inductees (<span id="rrhofYears">1986–2024</span>).</p>
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
        <p>Inductee data from <a href="https://www.wikidata.org/" target="_blank" rel="noopener">Wikidata</a> and
          <a href="https://en.wikipedia.org/wiki/List_of_Rock_and_Roll_Hall_of_Fame_inductees" target="_blank" rel="noopener">Wikipedia</a>.
          Photos from <a href="https://commons.wikimedia.org/" target="_blank" rel="noopener">Wikimedia Commons</a> (various licenses).
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
      <p class="panel-sub">Filter by induction category and type.</p>
      <h4 class="panel-section">Induction year range</h4>
      <div class="range-presets" id="yearPresets"></div>
      <div class="range-inputs">
        <label>From <select id="yearFrom"></select></label>
        <span class="range-dash">–</span>
        <label>To <select id="yearTo"></select></label>
      </div>
      <h4 class="panel-section">Category</h4>
      <div class="option-grid" id="catGrid"></div>
      <h4 class="panel-section">Type</h4>
      <div class="option-grid" id="typeGrid"></div>
      <div class="panel-foot">
        <span id="deckCount" class="panel-count"></span>
        <button class="link-danger" id="resetProgressBtn" title="Clear every card's score and start fresh">Start over</button>
      </div>
    </div>
  </div>`;

export async function init({ signal }) {
  await loadScript("rockhall-data.js?v=2");

  const DATA = window.ROCKHALL_DATA || [];
  if (!DATA.length) {
    document.querySelector(".card-stage").innerHTML =
      `<div style="text-align:center;padding:60px 20px;color:var(--ink-soft)">No data yet — run <code>python3 fetch_rockhall.py</code> to populate <code>rockhall-data.js</code>.</div>`;
    return;
  }

  const cardId = (c) => c.wikidata || c.name;
  const BY_ID = new Map(DATA.map(c => [cardId(c), c]));
  const allIds = DATA.map(cardId);
  const TOTAL = DATA.length;
  const SCORE_RETIRED = 3;

  const ALL_CATS = Array.from(new Set(
    DATA.flatMap(c => (c.inductions || []).map(i => i.category)).filter(Boolean)
  )).sort();
  const ALL_TYPES = ["person", "group"];

  const minYear = Math.min(...DATA.filter(d => d.year).map(d => d.year));
  const maxYear = Math.max(...DATA.filter(d => d.year).map(d => d.year));

  const engine = new DeckEngine({
    storeKey: "crammys-rockhall-v1",
    defaultState: { mode: "n2y", idx: 0, order: null, scores: {}, cats: ALL_CATS.slice(), types: ALL_TYPES.slice(), yearFrom: 1990, yearTo: maxYear, lastMode: "n2y" },
    migrateState(s) {
      if (!s.scores || typeof s.scores !== "object") s.scores = {};
      if (!Array.isArray(s.cats) || !s.cats.length) s.cats = ALL_CATS.slice();
      if (!Array.isArray(s.types) || !s.types.length) s.types = ALL_TYPES.slice();
      if (typeof s.yearFrom !== "number") s.yearFrom = 1990;
      if (typeof s.yearTo !== "number") s.yearTo = maxYear;
      s.yearFrom = Math.max(minYear, Math.min(maxYear, s.yearFrom));
      s.yearTo = Math.max(minYear, Math.min(maxYear, s.yearTo));
      if (s.yearFrom > s.yearTo) s.yearFrom = s.yearTo;
      if (!s.lastMode || s.lastMode === "study") s.lastMode = "n2y";
      return s;
    },
    allIds, byId: BY_ID, cardId,
    activeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      if (!c.year) return false;
      if (c.year < state.yearFrom || c.year > state.yearTo) return false;
      if (!state.types.includes(c.type)) return false;
      const cardCats = (c.inductions || []).map(i => i.category);
      if (!cardCats.some(cat => state.cats.includes(cat))) return false;
      if (engine.scoreOf(id) >= SCORE_RETIRED) return false;
      if (state.mode === "p2n" && !c.image) return false;
      return true;
    },
    inScopeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      if (!c.year) return false;
      if (c.year < state.yearFrom || c.year > state.yearTo) return false;
      if (!state.types.includes(c.type)) return false;
      const cardCats = (c.inductions || []).map(i => i.category);
      return cardCats.some(cat => state.cats.includes(cat));
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
  const photoStage = document.getElementById("photoStage");
  const photoEl = document.getElementById("photoEl");

  const stop = `onclick="event.stopPropagation()"`;

  function imageUrl(c, width) {
    if (!c.image) return "";
    const url = c.image.replace(/^http:/, "https:");
    return width ? url + (url.includes("?") ? "&" : "?") + `width=${width}` : url;
  }

  function categoryBadge(cat) {
    const cls = cat === "Performer" ? "winner" : "nominee";
    return `<span class="badge ${cls}">${escapeHtml(cat)}</span>`;
  }

  function lifespan(c) {
    if (c.type === "group") {
      const parts = [];
      if (c.formed) parts.push(`Formed ${c.formed}`);
      if (c.disbanded) parts.push(`disbanded ${c.disbanded}`);
      return parts.join(", ") || "";
    }
    if (c.born && c.died) return `${c.born}–${c.died}`;
    if (c.born) return `b. ${c.born}`;
    return "";
  }

  const SUMMARY_MAX = 320;
  function truncSummary(s) {
    if (!s || s.length <= SUMMARY_MAX) return escapeHtml(s || "");
    const cut = s.slice(0, SUMMARY_MAX);
    const lastSpace = cut.lastIndexOf(" ");
    const safe = lastSpace > SUMMARY_MAX - 50 ? cut.slice(0, lastSpace) : cut;
    return escapeHtml(safe) + `<span style="color:var(--ink-faint)">…</span>`;
  }

  function detailGrid(c, showInductionYear) {
    const rows = [];
    // Induction(s)
    for (const i of (c.inductions || [])) {
      const yr = showInductionYear ? `${i.year || "?"} · ` : "";
      const byLine = c.inductedBy ? ` <span style="color:var(--ink-faint)">by ${escapeHtml(c.inductedBy)}</span>` : "";
      rows.push(`<div class="row"><span class="label">Inducted</span><span class="val">${yr}${categoryBadge(i.category)}${byLine}</span></div>`);
    }
    // Life / Active
    const life = lifespan(c);
    if (life) rows.push(`<div class="row"><span class="label">${c.type === "group" ? "Active" : "Life"}</span><span class="val">${escapeHtml(life)}</span></div>`);
    // Country
    if (c.country) rows.push(`<div class="row"><span class="label">Origin</span><span class="val">${escapeHtml(c.country)}</span></div>`);
    // Genres
    if (c.genres && c.genres.length) rows.push(`<div class="row"><span class="label">Genres</span><span class="val">${c.genres.map(g => escapeHtml(g)).join(" · ")}</span></div>`);
    // Members
    if (c.members && c.members.length) rows.push(`<div class="row"><span class="label">Members</span><span class="val">${c.members.map(m => escapeHtml(m)).join(" · ")}</span></div>`);
    // Albums
    if (c.albums && c.albums.length) {
      const display = c.albums.slice(0, 5);
      const albumStr = display.map(a => `${escapeHtml(a.title)}${a.year ? ` (${a.year})` : ""}`).join(" · ");
      const suffix = c.albums.length > 5 ? " · …" : "";
      rows.push(`<div class="row"><span class="label">Albums</span><span class="val">${albumStr}${suffix}</span></div>`);
    }
    // Summary / blurb
    if (c.summary) rows.push(`<div class="row"><span class="label">About</span><span class="val">${truncSummary(c.summary)}</span></div>`);
    return rows.length ? `<div class="detail-grid">${rows.join("")}</div>` : "";
  }

  function render() {
    const ord = engine.activeOrder();
    const { learned, total } = engine.learnedAndTotal();
    const c = engine.currentCard();

    scopeText.textContent = `${state.yearFrom}–${state.yearTo}`;
    const offCats = ALL_CATS.length - state.cats.length;
    const offTypes = ALL_TYPES.length - state.types.length;
    const extras = [];
    if (offCats > 0) extras.push(`${state.cats.length}/${ALL_CATS.length} cat`);
    if (offTypes > 0) extras.push(state.types[0] === "person" ? "solos" : "groups");
    scopeExtras.textContent = extras.length ? "· " + extras.join(" · ") : "";

    if (!c) {
      counter.textContent = `${learned} / ${total}`;
      progress.style.width = total ? `${(learned / total) * 100}%` : "0%";
      frontFace.classList.remove("image-mode"); photoStage.hidden = true;
      front.tag.textContent = "All caught up"; front.prompt.textContent = "";
      front.text.innerHTML = `<span style="font-size:.5em;color:var(--ink-soft);font-family:inherit">Every inductee in this scope is learned. Open the deck chip and click <em>Start over</em>, or expand the filter.</span>`;
      back.body.innerHTML = ""; engine.renderScoreStars(null); return;
    }

    counter.textContent = `${state.idx + 1} / ${ord.length}`;
    progress.style.width = `${((state.idx + 1) / ord.length) * 100}%`;

    const isPhoto = state.mode === "p2n";
    frontFace.classList.toggle("image-mode", isPhoto);
    photoStage.hidden = !isPhoto;

    if (isPhoto) {
      photoEl.src = imageUrl(c, 600);
      photoEl.alt = "";
    } else if (state.mode === "study") {
      front.tag.textContent = "Study";
      front.prompt.textContent = "";
      front.text.textContent = c.name;
    } else {
      front.tag.textContent = c.type === "group" ? "Group" : "Artist";
      front.prompt.textContent = "Inducted in?";
      front.text.innerHTML = `<span>${escapeHtml(c.name)}</span>`;
    }

    // Back — external links
    const extIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7M9 7h8v8"/></svg>';
    const spotifyIcon = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.6 0 12 0zm5.5 17.3c-.2.3-.6.4-1 .2-2.7-1.6-6-2-10-1.1-.4.1-.7-.2-.8-.5-.1-.4.2-.7.5-.8 4.3-1 8.1-.6 11.1 1.2.3.2.4.7.2 1zm1.5-3.3c-.3.4-.8.5-1.2.3-3-1.9-7.7-2.4-11.3-1.3-.4.1-.9-.1-1-.5-.1-.4.1-.9.5-1 4.1-1.3 9.2-.7 12.7 1.5.3.2.5.7.3 1zm.1-3.4c-3.7-2.2-9.7-2.4-13.2-1.3-.5.2-1.1-.1-1.2-.6-.2-.5.1-1.1.6-1.2 4-1.2 10.7-1 14.9 1.5.5.3.6.9.4 1.3-.3.4-.9.6-1.5.3z"/></svg>';
    const wikiUrl = c.wikipedia || `https://en.wikipedia.org/wiki/${encodeURIComponent(c.name)}`;
    const wikiLink = `<a class="ext" href="${wikiUrl}" target="_blank" rel="noopener" title="Wikipedia" ${stop}>${extIcon}</a>`;
    const spotifyLink = c.spotify
      ? `<button class="ext spotify-play" title="Spotify" onclick="event.stopPropagation();openSpotifyEmbed('${c.spotify}','artist')">${spotifyIcon}</button>`
      : "";

    const showInductionYear = state.mode !== "n2y";
    const hasPhoto = state.mode !== "p2n" && c.image;
    const photoHTML = hasPhoto
      ? `<div class="study-photo"><img src="${imageUrl(c, 300)}" alt="" loading="lazy"></div>` : "";
    const links = `${wikiLink}${spotifyLink}`;
    const desc = c.description ? `<div class="credits subtle">${escapeHtml(c.description)}</div>` : "";

    let headerBlock;
    if (state.mode === "n2y") {
      back.tag.textContent = "Induction";
      headerBlock = `<div class="study-anchor">
        ${photoHTML}
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.name)} ${links}</div>
          <div class="answer"><span>${c.year || "?"}</span></div>
          ${desc}
        </div>
      </div>`;
    } else {
      back.tag.textContent = c.type === "group" ? "Group" : "Artist";
      headerBlock = `<div class="study-anchor">
        ${photoHTML}
        <div class="study-info">
          <div class="prompt">Rock &amp; Roll Hall of Fame</div>
          <div class="answer"><span>${escapeHtml(c.name)}</span> ${links}</div>
          ${desc}
        </div>
      </div>`;
    }

    back.body.innerHTML = headerBlock + detailGrid(c, showInductionYear);

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
  document.getElementById("rrhofCount").textContent = String(TOTAL);
  document.getElementById("rrhofYears").textContent = `${minYear}–${maxYear}`;
  const { open: openAbout, close: closeAbout } = DeckEngine.bindModal(aboutModal, document.getElementById("aboutClose"), document.getElementById("aboutBtn"));

  // Deck modal
  const deckModal = document.getElementById("deckModal");
  const catGridEl = document.getElementById("catGrid");
  const typeGridEl = document.getElementById("typeGrid");
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
      if (!state.types.includes(c.type)) return false;
      const cardCats = (c.inductions || []).map(i => i.category);
      return cardCats.some(cat => state.cats.includes(cat));
    }).length;
  }

  function syncDeckModal() {
    yearFromSel.value = state.yearFrom;
    yearToSel.value = state.yearTo;
    yearPresetsEl.querySelectorAll("button").forEach(b => {
      b.classList.toggle("on", +b.dataset.from === state.yearFrom && +b.dataset.to === state.yearTo);
    });
    catGridEl.innerHTML = ALL_CATS.map(cat =>
      `<label><input type="checkbox" value="${cat}" ${state.cats.includes(cat) ? "checked" : ""}><span>${escapeHtml(cat)}</span></label>`
    ).join("");
    typeGridEl.innerHTML = ALL_TYPES.map(t =>
      `<label><input type="checkbox" value="${t}" ${state.types.includes(t) ? "checked" : ""}><span>${t === "person" ? "Solo artists" : "Groups / bands"}</span></label>`
    ).join("");
    deckCountEl.innerHTML = `<em>${countInScope()}</em> inductees in deck`;
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
  typeGridEl.addEventListener("change", (e) => {
    const inp = e.target.closest("input"); if (!inp) return;
    const t = inp.value;
    if (inp.checked && !state.types.includes(t)) state.types.push(t);
    else if (!inp.checked) state.types = state.types.filter(x => x !== t);
    if (!state.types.length) state.types = [t];
    state.idx = 0; engine.persist(); syncDeckModal(); engine.unflipAndThen(render);
  }, { signal });
  document.getElementById("resetProgressBtn").addEventListener("click", () => { closeDeck(); engine.reset(); }, { signal });

  // Keyboard
  engine.bindKeyboard({ signal, extraKeys(e) {
    switch (e.key) {
      case "n": case "N": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.missed(); return true;
      case "y": case "Y": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.gotIt(); return true;
      case "l": case "L": setMode(engine.isStudy() ? (state.lastMode || "n2y") : "study"); return true;
      case "?": e.preventDefault(); if (aboutModal.hidden) openAbout(); else closeAbout(); return true;
      case "Escape": if (!aboutModal.hidden) closeAbout(); else if (!deckModal.hidden) closeDeck(); return true;
    }
    return false;
  }});

  if (engine.isStudy()) engine.cardEl.classList.add("flipped");
  render();
}
