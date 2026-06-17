import { DeckEngine, loadScript, escapeHtml } from '../deck-engine.js';

export const meta = { id: "presidents", emoji: "🇺🇸", name: "US Presidents" };

export const segments = `
  <button data-mode="y2p" class="on">Years → President</button>
  <button data-mode="p2y">President → Years</button>
  <button data-mode="n2p">Number → President</button>
  <button data-mode="i2p">Image → President</button>
  <button data-mode="study">Study</button>`;

export const frontExtras = `
  <div class="image-stage" id="portraitStage" hidden>
    <img id="portraitEl" alt="" />
    <div class="image-overlay">
      <div class="corner"><span>Portrait</span></div>
      <div class="bottom">
        <div class="image-controls">
          <span class="image-dots" id="portraitDots" aria-hidden="true"></span>
          <button class="image-stack-btn" id="portraitRerollBtn" title="More portraits" aria-label="More portraits">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="14" height="14" rx="2"/><path d="M7 3h12a2 2 0 0 1 2 2v12"/></svg>
          </button>
        </div>
        <div class="prompt">Which president is this?</div>
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
      <h3 class="panel-title">US Presidents · Crammys</h3>
      <p class="panel-sub">Flashcards for all <span id="presCount">47</span> US presidencies (<span id="presYears">1789–present</span>). Cleveland and Trump each get two cards for their non-consecutive terms.</p>
      <div class="about-section"><h4>Keyboard shortcuts</h4>
        <div class="kbd-grid">
          <div><kbd>Space</kbd> reveal answer</div>
          <div><kbd>←</kbd> <kbd>→</kbd> previous / next</div>
          <div><kbd>Y</kbd> got it</div>
          <div><kbd>N</kbd> missed</div>
          <div><kbd>S</kbd> shuffle</div>
          <div><kbd>R</kbd> reset progress</div>
          <div><kbd>L</kbd> toggle Study mode</div>
          <div><kbd>↑</kbd> <kbd>↓</kbd> cycle portraits (image mode)</div>
          <div><kbd>T</kbd> toggle theme</div>
          <div><kbd>?</kbd> this dialog</div>
          <div><kbd>Esc</kbd> close any popup</div>
        </div>
      </div>
      <div class="about-section"><h4>Data &amp; credits</h4>
        <p>President data from <a href="https://www.wikidata.org/" target="_blank" rel="noopener">Wikidata</a> and
          <a href="https://en.wikipedia.org/wiki/List_of_presidents_of_the_United_States" target="_blank" rel="noopener">Wikipedia</a>.
          Portraits from <a href="https://commons.wikimedia.org/" target="_blank" rel="noopener">Wikimedia Commons</a> (various public-domain and government-work licenses).
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
      <p class="panel-sub">Filter by era and party.</p>
      <h4 class="panel-section">Year range</h4>
      <div class="range-presets" id="yearPresets"></div>
      <div class="range-inputs">
        <label>From <select id="yearFrom"></select></label>
        <span class="range-dash">–</span>
        <label>To <select id="yearTo"></select></label>
      </div>
      <h4 class="panel-section">Party</h4>
      <div class="option-grid" id="partyGrid"></div>
      <label class="toggle-row" style="margin-top:14px">
        <input type="checkbox" id="hardModeChk">
        <span>
          <strong>Hard mode</strong>
          <em>Years → President shows a single year instead of the term range</em>
        </span>
      </label>
      <div class="panel-foot">
        <span id="deckCount" class="panel-count"></span>
        <button class="link-danger" id="resetProgressBtn" title="Clear every card's score and start fresh">Start over</button>
      </div>
    </div>
  </div>`;

export async function init({ signal }) {
  await loadScript("presidents-data.js?v=1");

  const DATA = window.PRESIDENTS_DATA || [];
  if (!DATA.length) {
    document.querySelector(".card-stage").innerHTML =
      `<div style="text-align:center;padding:60px 20px;color:var(--ink-soft)">No data yet — run <code>python3 fetch_presidents.py</code> then <code>python3 enrich_presidents.py</code> to populate <code>presidents-data.js</code>.</div>`;
    return;
  }

  const cardId = (c) => `${c.term}::${c.name}`;
  const BY_ID = new Map(DATA.map(c => [cardId(c), c]));
  const allIds = DATA.map(cardId);
  const TOTAL = DATA.length;
  const SCORE_RETIRED = 3;

  // Party buckets — group the historical parties into three columns so
  // we don't drown the user in seven different checkboxes.
  function partyBucket(party) {
    if (!party) return "Other";
    if (party === "Democrat") return "Democrat";
    if (party === "Republican") return "Republican";
    return "Other";
  }
  const ALL_PARTIES = ["Democrat", "Republican", "Other"];

  const minYear = Math.min(...DATA.map(d => d.yearStart));
  const maxYear = Math.max(...DATA.map(d => (d.yearEnd || new Date().getFullYear())));

  const imageChoice = new Map();

  const engine = new DeckEngine({
    storeKey: "crammys-presidents-v1",
    defaultState: {
      mode: "y2p", idx: 0, order: null, scores: {},
      parties: ALL_PARTIES.slice(),
      yearFrom: 1953,
      yearTo: maxYear,
      hardMode: false,
      lastMode: "y2p",
    },
    migrateState(s) {
      if (!s.scores || typeof s.scores !== "object") s.scores = {};
      if (!Array.isArray(s.parties) || !s.parties.length) s.parties = ALL_PARTIES.slice();
      if (typeof s.yearFrom !== "number") s.yearFrom = 1953;
      if (typeof s.yearTo !== "number") s.yearTo = maxYear;
      s.yearFrom = Math.max(minYear, Math.min(maxYear, s.yearFrom));
      s.yearTo = Math.max(minYear, Math.min(maxYear, s.yearTo));
      if (s.yearFrom > s.yearTo) s.yearFrom = s.yearTo;
      if (typeof s.hardMode !== "boolean") s.hardMode = false;
      if (!s.lastMode || s.lastMode === "study") s.lastMode = "y2p";
      return s;
    },
    allIds, byId: BY_ID, cardId,
    onShuffle: () => { imageChoice.clear(); hardYearCache.clear(); },
    activeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      const startsInRange = c.yearStart <= state.yearTo;
      const endsInRange = (c.yearEnd || maxYear) >= state.yearFrom;
      if (!(startsInRange && endsInRange)) return false;
      if (!state.parties.includes(partyBucket(c.party))) return false;
      if (engine.scoreOf(id) >= SCORE_RETIRED) return false;
      if (state.mode === "i2p" && !(c.images && c.images.length)) return false;
      return true;
    },
    inScopeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      const startsInRange = c.yearStart <= state.yearTo;
      const endsInRange = (c.yearEnd || maxYear) >= state.yearFrom;
      if (!(startsInRange && endsInRange)) return false;
      if (!state.parties.includes(partyBucket(c.party))) return false;
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
  const portraitStage = document.getElementById("portraitStage");
  const portraitEl = document.getElementById("portraitEl");
  const portraitDots = document.getElementById("portraitDots");

  const stop = `onclick="event.stopPropagation()"`;
  const extIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7M9 7h8v8"/></svg>';

  // ── Image picker (modeled on bestpicture.js) ──
  function pickImage(c, opts = {}) {
    const imgs = c.images || [];
    if (!imgs.length) return null;
    const n = imgs.length;
    const key = cardId(c);
    let idx;
    if (typeof opts.step === "number" && imageChoice.has(key)) {
      idx = ((imageChoice.get(key) + opts.step) % n + n) % n;
    } else if (opts.reroll && imageChoice.has(key)) {
      const prev = imageChoice.get(key);
      idx = (prev + 1 + Math.floor(Math.random() * (n - 1))) % n;
    } else if (imageChoice.has(key)) {
      idx = Math.min(imageChoice.get(key), n - 1);
    } else {
      idx = 0;  // Default to first (canonical) portrait
    }
    imageChoice.set(key, idx);
    return imgs[idx];
  }
  function renderPortraitDots(c) {
    const imgs = c.images || [];
    if (!imgs.length) { portraitDots.innerHTML = ""; return; }
    const sel = imageChoice.get(cardId(c)) ?? 0;
    portraitDots.innerHTML = imgs.map((_, i) => `<span${i === sel ? ' class="on"' : ""}></span>`).join("");
  }
  function setPortrait(c, opts) {
    const img = pickImage(c, opts);
    if (!img) {
      portraitEl.removeAttribute("src");
      portraitEl.alt = "";
      portraitDots.innerHTML = "";
      return;
    }
    portraitStage.classList.add("loading");
    portraitEl.onload = () => portraitStage.classList.remove("loading");
    portraitEl.onerror = () => portraitStage.classList.remove("loading");
    portraitEl.src = img.url;
    portraitEl.alt = "";
    renderPortraitDots(c);
  }
  function rerollPortrait() { const c = engine.currentCard(); if (c) setPortrait(c, { reroll: true }); }
  function stepPortrait(delta) {
    if (state.mode !== "i2p") return;
    const c = engine.currentCard();
    if (c) setPortrait(c, { step: delta });
  }

  // ── Helpers ──
  function fmtYears(c) {
    if (c.yearEnd) return `${c.yearStart}–${c.yearEnd}`;
    return `${c.yearStart}–present`;
  }
  // Per-card random year cache so the same card always shows the same
  // hard-mode year until reshuffled (avoids the prompt changing mid-flip).
  const hardYearCache = new Map();
  function singleYear(c) {
    const key = cardId(c);
    if (!hardYearCache.has(key)) {
      // The inauguration year belongs to the incoming president (they
      // serve ~11 months of it), so the final year of a term belongs to
      // the successor.  Pick from [yearStart, yearEnd-1].  For incumbents
      // (yearEnd=null), pick up to current year.  For one-year terms
      // (W.H. Harrison, Garfield), just use yearStart.
      const last = c.yearEnd ? c.yearEnd - 1 : new Date().getFullYear();
      const lo = c.yearStart;
      const hi = Math.max(lo, last);
      hardYearCache.set(key, lo + Math.floor(Math.random() * (hi - lo + 1)));
    }
    return hardYearCache.get(key);
  }
  function ordinal(n) {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }
  function wikiLink(name) {
    if (!name) return "—";
    const slug = encodeURIComponent(name.replace(/ /g, "_"));
    return `<a href="https://en.wikipedia.org/wiki/${slug}" target="_blank" rel="noopener" class="person-link" ${stop}>${escapeHtml(name)}</a>`;
  }
  function partyBadge(party) {
    if (!party) return "";
    const cls = party === "Democrat" ? "nominee" : (party === "Republican" ? "winner" : "");
    return `<span class="badge ${cls}">${escapeHtml(party)}</span>`;
  }
  function termsServedNote(c) {
    // Count how many P39 terms this presidency includes. For our data,
    // it's implicit — Eisenhower served 2, FDR 4, etc.
    const yrs = (c.yearEnd || new Date().getFullYear()) - c.yearStart;
    // 4-year terms — round up because last term may be partial.
    const terms = Math.max(1, Math.round(yrs / 4));
    if (terms <= 1) return "";
    return ` <span class="credits subtle" style="display:inline">· ${terms} terms</span>`;
  }

  const SUMMARY_PREVIEW = 260;
  function aboutBlock(c) {
    if (!c.summary) return "";
    const s = c.summary;
    if (s.length <= SUMMARY_PREVIEW) return escapeHtml(s);
    const cut = s.slice(0, SUMMARY_PREVIEW);
    const lastSpace = cut.lastIndexOf(" ");
    const safe = lastSpace > SUMMARY_PREVIEW - 50 ? cut.slice(0, lastSpace) : cut;
    const preview = escapeHtml(safe);
    const rest = escapeHtml(s.slice(safe.length));
    return `<span class="about-preview">${preview}</span><span class="about-rest" hidden> ${rest}</span><button class="more-toggle" data-more ${stop}>…more</button>`;
  }

  function detailGrid(c, opts = {}) {
    const rows = [];
    // Term
    rows.push(`<div class="row"><span class="label">Term</span><span class="val">${ordinal(c.term)} President${termsServedNote(c)}</span></div>`);
    // Years
    rows.push(`<div class="row"><span class="label">Years</span><span class="val">${escapeHtml(fmtYears(c))}</span></div>`);
    // Party
    if (c.party) rows.push(`<div class="row"><span class="label">Party</span><span class="val">${partyBadge(c.party)}</span></div>`);
    // Took office / Left office (predecessor + successor are mentioned
    // in these notes, so we don't render separate rows for them).
    if (c.entryNote) rows.push(`<div class="row"><span class="label">Took office</span><span class="val">${escapeHtml(c.entryNote)}</span></div>`);
    if (c.exitNote) rows.push(`<div class="row"><span class="label">Left office</span><span class="val">${escapeHtml(c.exitNote)}</span></div>`);
    // VP(s)
    if (c.vps && c.vps.length) {
      const vpStr = c.vps.map(v => `${wikiLink(v.name)} <span style="color:var(--ink-faint)">(${escapeHtml(v.years)})</span>`).join("<br>");
      rows.push(`<div class="row"><span class="label">${c.vps.length > 1 ? "Vice Presidents" : "Vice President"}</span><span class="val">${vpStr}</span></div>`);
    }
    // Born (with state)
    if (c.born) {
      const stateNote = c.homeState ? ` <span style="color:var(--ink-faint)">(${escapeHtml(c.homeState)})</span>` : "";
      rows.push(`<div class="row"><span class="label">Born</span><span class="val">${c.born}${stateNote}</span></div>`);
    } else if (c.homeState) {
      rows.push(`<div class="row"><span class="label">State</span><span class="val">${escapeHtml(c.homeState)}</span></div>`);
    }
    // Died
    if (c.died) {
      rows.push(`<div class="row"><span class="label">Died</span><span class="val">${c.died}</span></div>`);
    }
    // Notable
    if (c.notable && c.notable.length) {
      const bullets = c.notable.map(n => `<div>· ${escapeHtml(n)}</div>`).join("");
      rows.push(`<div class="row"><span class="label">Notable</span><span class="val">${bullets}</span></div>`);
    }
    // About
    if (c.summary) {
      rows.push(`<div class="row"><span class="label">About</span><span class="val">${aboutBlock(c)}</span></div>`);
    }
    return rows.length ? `<div class="detail-grid">${rows.join("")}</div>` : "";
  }

  function studyPortraitHTML(c) {
    if (!c.images || !c.images.length) return "";
    return `<div class="study-photo"><img src="${c.images[0].url}" alt="" loading="lazy"></div>`;
  }

  function render() {
    const ord = engine.activeOrder();
    const { learned, total } = engine.learnedAndTotal();
    const c = engine.currentCard();

    scopeText.textContent = `${state.yearFrom}–${state.yearTo}`;
    const offParties = ALL_PARTIES.length - state.parties.length;
    scopeExtras.textContent = offParties > 0 ? `· ${state.parties.length}/${ALL_PARTIES.length} party` : "";

    if (!c) {
      counter.textContent = `${learned} / ${total}`;
      progress.style.width = total ? `${(learned / total) * 100}%` : "0%";
      frontFace.classList.remove("image-mode"); portraitStage.hidden = true;
      front.tag.textContent = "All caught up";
      front.prompt.textContent = "";
      front.text.innerHTML = `<span style="font-size:.5em;color:var(--ink-soft);font-family:inherit">Every president in this scope is learned. Open the deck chip and click <em>Start over</em>, or expand the filter.</span>`;
      back.body.innerHTML = "";
      engine.renderScoreStars(null);
      return;
    }

    counter.textContent = `${state.idx + 1} / ${ord.length}`;
    progress.style.width = `${((state.idx + 1) / ord.length) * 100}%`;

    const isImage = state.mode === "i2p";
    frontFace.classList.toggle("image-mode", isImage);
    portraitStage.hidden = !isImage;

    if (isImage) {
      setPortrait(c);
    } else if (state.mode === "study") {
      front.tag.textContent = "Study";
      front.prompt.textContent = "";
      front.text.innerHTML = `<span>${escapeHtml(c.name)}</span>`;
    } else if (state.mode === "p2y") {
      front.tag.textContent = "President";
      front.prompt.textContent = "Served when?";
      front.text.innerHTML = `<span>${escapeHtml(c.name)}</span>`;
    } else if (state.mode === "n2p") {
      front.tag.textContent = "Term";
      front.prompt.textContent = "Who was the";
      front.text.innerHTML = `<span>${ordinal(c.term)}</span><span style="width:100%;font-size:13px;color:var(--ink-soft);margin-top:8px;font-family:inherit;letter-spacing:.04em;text-transform:uppercase;font-weight:400">President?</span>`;
    } else {
      // y2p — single year in hard mode, range otherwise
      front.tag.textContent = state.hardMode ? "Year" : "Term";
      front.prompt.textContent = "Who was president in";
      const shown = state.hardMode ? singleYear(c) : fmtYears(c);
      front.text.innerHTML = `<span>${escapeHtml(String(shown))}</span>`;
    }

    // Back
    const showStudyPhoto = state.mode !== "i2p";
    const photoHTML = showStudyPhoto ? studyPortraitHTML(c) : "";
    const wikiUrl = c.wikipedia || `https://en.wikipedia.org/wiki/${encodeURIComponent(c.name)}`;
    const links = `<a class="ext" href="${wikiUrl}" target="_blank" rel="noopener" title="Wikipedia" ${stop}>${extIcon}</a>`;

    let headerBlock;
    if (state.mode === "y2p" || state.mode === "n2p") {
      back.tag.textContent = "President";
      headerBlock = `<div class="study-anchor">
        ${photoHTML}
        <div class="study-info">
          <div class="prompt">${escapeHtml(fmtYears(c))} · ${ordinal(c.term)}</div>
          <div class="answer"><span>${escapeHtml(c.name)}</span> ${links}</div>
        </div>
      </div>`;
    } else if (state.mode === "p2y") {
      back.tag.textContent = "Term";
      headerBlock = `<div class="study-anchor">
        ${photoHTML}
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.name)} ${links}</div>
          <div class="answer"><span>${escapeHtml(fmtYears(c))}</span></div>
          <div class="credits subtle">${ordinal(c.term)} President</div>
        </div>
      </div>`;
    } else {
      // i2p or study
      back.tag.textContent = state.mode === "study" ? "Study" : "President";
      headerBlock = `<div class="study-anchor">
        ${photoHTML}
        <div class="study-info">
          <div class="prompt">${ordinal(c.term)} President · ${escapeHtml(fmtYears(c))}</div>
          <div class="answer"><span>${escapeHtml(c.name)}</span> ${links}</div>
        </div>
      </div>`;
    }

    back.body.innerHTML = headerBlock + detailGrid(c);

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
    state.mode = m;
    state.idx = 0;
    document.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.mode === m));
    engine.persist();
    if (goingStudy) { engine.cardEl.classList.add("flipped"); engine.syncNav(); render(); }
    else if (wasStudy) { engine.cardEl.classList.remove("flipped"); engine.syncNav(); render(); }
    else engine.unflipAndThen(render);
  }

  // Wire UI
  engine.bindStandardUI({
    nextBtn: document.getElementById("nextBtn"),
    prevBtn: document.getElementById("prevBtn"),
    gotBtn: document.getElementById("gotBtn"),
    missedBtn: document.getElementById("missedBtn"),
    shuffleBtn: document.getElementById("shuffleIconBtn"),
    cardClickIgnore: "a, button, .more-toggle",
    signal,
  });
  document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => setMode(b.dataset.mode), { signal }));
  document.querySelectorAll(".seg button").forEach(b => b.classList.toggle("on", b.dataset.mode === state.mode));

  // Portrait reroll button
  document.getElementById("portraitRerollBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    rerollPortrait();
  }, { signal });

  // "…more" expansion for About paragraph
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".more-toggle[data-more]");
    if (!btn) return;
    e.stopPropagation();
    const row = btn.closest(".row");
    if (!row) return;
    const rest = row.querySelector(".about-rest");
    if (rest) { rest.hidden = false; btn.remove(); }
  }, { signal });

  // About modal
  const aboutModal = document.getElementById("aboutModal");
  document.getElementById("presCount").textContent = String(TOTAL);
  document.getElementById("presYears").textContent = `${minYear}–present`;
  const { open: openAbout, close: closeAbout } = DeckEngine.bindModal(aboutModal, document.getElementById("aboutClose"), document.getElementById("aboutBtn"));

  // Deck modal
  const deckModal = document.getElementById("deckModal");
  const partyGridEl = document.getElementById("partyGrid");
  const deckCountEl = document.getElementById("deckCount");
  const yearFromSel = document.getElementById("yearFrom");
  const yearToSel = document.getElementById("yearTo");
  const yearPresetsEl = document.getElementById("yearPresets");

  // Year picker uses each presidency's start year (47 distinct values).
  const startYears = Array.from(new Set(DATA.map(d => d.yearStart))).sort((a, b) => b - a);
  // Also include maxYear as an "end" option for the end picker.
  const yearOptionsHTML = startYears.map(y => `<option value="${y}">${y}</option>`).join("");
  yearFromSel.innerHTML = yearOptionsHTML;
  yearToSel.innerHTML = `<option value="${maxYear}">${maxYear} (now)</option>` + yearOptionsHTML;

  const YEAR_PRESETS = [
    { label: "1981+", from: 1981, to: maxYear },
    { label: "2001+", from: 2001, to: maxYear },
    { label: "1953+", from: 1953, to: maxYear },
    { label: `All (${minYear}–${maxYear})`, from: minYear, to: maxYear },
  ];
  yearPresetsEl.innerHTML = YEAR_PRESETS.map(p =>
    `<button data-from="${p.from}" data-to="${p.to}">${p.label}</button>`
  ).join("");

  function countInScope() {
    return DATA.filter(c => {
      const startsInRange = c.yearStart <= state.yearTo;
      const endsInRange = (c.yearEnd || maxYear) >= state.yearFrom;
      if (!(startsInRange && endsInRange)) return false;
      if (!state.parties.includes(partyBucket(c.party))) return false;
      return true;
    }).length;
  }

  function syncDeckModal() {
    yearFromSel.value = state.yearFrom;
    yearToSel.value = state.yearTo;
    yearPresetsEl.querySelectorAll("button").forEach(b => {
      b.classList.toggle("on", +b.dataset.from === state.yearFrom && +b.dataset.to === state.yearTo);
    });
    partyGridEl.innerHTML = ALL_PARTIES.map(p =>
      `<label><input type="checkbox" value="${p}" ${state.parties.includes(p) ? "checked" : ""}><span>${escapeHtml(p)}</span></label>`
    ).join("");
    document.getElementById("hardModeChk").checked = !!state.hardMode;
    deckCountEl.innerHTML = `<em>${countInScope()}</em> presidencies in deck`;
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
  partyGridEl.addEventListener("change", (e) => {
    const inp = e.target.closest("input"); if (!inp) return;
    const p = inp.value;
    if (inp.checked && !state.parties.includes(p)) state.parties.push(p);
    else if (!inp.checked) state.parties = state.parties.filter(x => x !== p);
    if (!state.parties.length) state.parties = [p];
    state.idx = 0; engine.persist(); syncDeckModal(); engine.unflipAndThen(render);
  }, { signal });
  document.getElementById("hardModeChk").addEventListener("change", (e) => {
    state.hardMode = e.target.checked;
    hardYearCache.clear();
    engine.persist();
    engine.unflipAndThen(render);
  }, { signal });
  document.getElementById("resetProgressBtn").addEventListener("click", () => { closeDeck(); engine.reset(); }, { signal });

  // Keyboard
  engine.bindKeyboard({ signal, extraKeys(e) {
    switch (e.key) {
      case "n": case "N": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.missed(); return true;
      case "y": case "Y": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.gotIt(); return true;
      case "l": case "L": setMode(engine.isStudy() ? (state.lastMode || "y2p") : "study"); return true;
      case "ArrowDown": stepPortrait(+1); return true;
      case "ArrowUp": stepPortrait(-1); return true;
      case "?": e.preventDefault(); if (aboutModal.hidden) openAbout(); else closeAbout(); return true;
      case "Escape": if (!aboutModal.hidden) closeAbout(); else if (!deckModal.hidden) closeDeck(); return true;
    }
    return false;
  }});

  if (engine.isStudy()) engine.cardEl.classList.add("flipped");
  render();
}
