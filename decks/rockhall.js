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
  await loadScript("rockhall-data.js");

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
    defaultState: { mode: "n2y", idx: 0, order: null, scores: {}, cats: ALL_CATS.slice(), types: ALL_TYPES.slice(), lastMode: "n2y" },
    migrateState(s) {
      if (!s.scores || typeof s.scores !== "object") s.scores = {};
      if (!Array.isArray(s.cats) || !s.cats.length) s.cats = ALL_CATS.slice();
      if (!Array.isArray(s.types) || !s.types.length) s.types = ALL_TYPES.slice();
      if (!s.lastMode || s.lastMode === "study") s.lastMode = "n2y";
      return s;
    },
    allIds, byId: BY_ID, cardId,
    activeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
      if (!state.types.includes(c.type)) return false;
      const cardCats = (c.inductions || []).map(i => i.category);
      if (!cardCats.some(cat => state.cats.includes(cat))) return false;
      if (!c.year) return false;
      if (engine.scoreOf(id) >= SCORE_RETIRED) return false;
      if (state.mode === "p2n" && !c.image) return false;
      return true;
    },
    inScopeFilter(id, state) {
      const c = BY_ID.get(id); if (!c) return false;
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

  function inductionLines(c) {
    return (c.inductions || []).map(i =>
      `<div class="credits"><span class="label">Inducted ${i.year || "?"}</span> ${categoryBadge(i.category)}</div>`
    ).join("");
  }

  function genreChips(c) {
    if (!c.genres || !c.genres.length) return "";
    return `<div class="credits">${c.genres.map(g =>
      escapeHtml(g)
    ).join('<span class="sep">·</span>')}</div>`;
  }

  function membersBlock(c) {
    if (!c.members || !c.members.length) return "";
    const list = c.members.map(m => escapeHtml(m)).join('<span class="sep">·</span>');
    return `<div class="credits"><span class="label">Members</span> ${list}</div>`;
  }

  function render() {
    const ord = engine.activeOrder();
    const { learned, total } = engine.learnedAndTotal();
    const c = engine.currentCard();

    scopeText.textContent = `${TOTAL} inductees`;
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

    // Back
    const wikiUrl = `https://www.wikidata.org/wiki/${c.wikidata}`;
    const extIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7M9 7h8v8"/></svg>';
    const wikiLink = `<a class="ext" href="${wikiUrl}" target="_blank" rel="noopener" title="Wikidata" ${stop}>${extIcon}</a>`;

    let answerBlock;
    if (state.mode === "n2y") {
      back.tag.textContent = "Induction";
      const yearStr = c.year || "?";
      answerBlock = `
        <div class="prompt">${escapeHtml(c.name)} ${wikiLink}</div>
        <div class="answer"><span>${yearStr}</span></div>`;
    } else {
      back.tag.textContent = c.type === "group" ? "Group" : "Artist";
      answerBlock = `
        <div class="prompt">Rock &amp; Roll Hall of Fame</div>
        <div class="answer"><span>${escapeHtml(c.name)}</span> ${wikiLink}</div>`;
    }

    const photo = (state.mode !== "p2n" && c.image)
      ? `<div class="study-anchor"><div class="study-photo"><img src="${imageUrl(c, 300)}" alt="" loading="lazy"></div><div class="study-blurb">${escapeHtml(c.description || "")}</div></div>`
      : (c.description ? `<div class="credits subtle">${escapeHtml(c.description)}</div>` : "");

    const life = lifespan(c);
    const lifeBlock = life ? `<div class="credits"><span class="label">${c.type === "group" ? "Active" : "Life"}</span> ${escapeHtml(life)}${c.country ? ` · ${escapeHtml(c.country)}` : ""}</div>` : "";

    back.body.innerHTML = answerBlock + photo + inductionLines(c) + lifeBlock + genreChips(c) + membersBlock(c);

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

  function syncDeckModal() {
    catGridEl.innerHTML = ALL_CATS.map(cat =>
      `<label><input type="checkbox" value="${cat}" ${state.cats.includes(cat) ? "checked" : ""}><span>${escapeHtml(cat)}</span></label>`
    ).join("");
    typeGridEl.innerHTML = ALL_TYPES.map(t =>
      `<label><input type="checkbox" value="${t}" ${state.types.includes(t) ? "checked" : ""}><span>${t === "person" ? "Solo artists" : "Groups / bands"}</span></label>`
    ).join("");
    const inScope = DATA.filter(c => {
      if (!state.types.includes(c.type)) return false;
      const cardCats = (c.inductions || []).map(i => i.category);
      return cardCats.some(cat => state.cats.includes(cat));
    });
    deckCountEl.innerHTML = `<em>${inScope.length}</em> inductees in deck`;
  }

  const { close: closeDeck } = DeckEngine.bindModal(deckModal, document.getElementById("deckClose"));
  document.getElementById("deckChip").addEventListener("click", () => { syncDeckModal(); DeckEngine.openModal(deckModal); }, { signal });
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
