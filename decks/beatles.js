import { DeckEngine, loadScript, escapeHtml } from '../deck-engine.js';

export const meta = { id: "beatles", emoji: "\u{1FAB2}", name: "Beatles Tracklists" };

export const segments = `
  <button data-mode="a2t" class="on">Album → Tracks</button>
  <button data-mode="t2a">Track → Album</button>
  <button data-mode="p2t">Position → Track</button>
  <button data-mode="study">Study</button>`;

export const frontExtras = ``;

export const modals = `
  <div class="modal-backdrop" id="aboutModal" hidden>
    <div class="panel panel-wide" role="dialog" aria-label="About">
      <button class="modal-close" id="aboutClose" aria-label="Close">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <h3 class="panel-title">Beatles Tracklists · Crammys</h3>
      <p class="panel-sub">Flashcards for all <span id="beatlesTrackCount">0</span> tracks across <span id="beatlesAlbumCount">13</span> Beatles UK studio albums (<span id="beatlesYears">1963–1970</span>).</p>
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
        <p>Tracklists from <a href="https://en.wikipedia.org/wiki/The_Beatles_discography" target="_blank" rel="noopener">Wikipedia</a>.
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
      <p class="panel-sub" id="deckSub">All 13 UK studio albums.</p>
      <div class="panel-foot">
        <span id="deckCount" class="panel-count"></span>
        <button class="link-danger" id="resetProgressBtn" title="Clear every card's score and start fresh">Start over</button>
      </div>
    </div>
  </div>`;

export async function init({ signal }) {
  await loadScript("beatles-data.js?v=2");

  const DATA = window.BEATLES_DATA || [];
  if (!DATA.length) {
    document.querySelector(".card-stage").innerHTML =
      `<div style="text-align:center;padding:60px 20px;color:var(--ink-soft)">No data yet.</div>`;
    return;
  }

  // Build flattened track pool
  const SIDE_LABELS = { a: "A", b: "B", c: "C", d: "D" };
  const TRACKS = [];
  for (const album of DATA) {
    for (const [side, tracks] of Object.entries(album.sides)) {
      for (let i = 0; i < tracks.length; i++) {
        TRACKS.push({
          track: tracks[i],
          album: album.album,
          year: album.year,
          side,
          pos: i,
          spotify: album.spotify,
          wikipedia: album.wikipedia,
          _albumData: album,
        });
      }
    }
  }

  const ALBUM_COUNT = DATA.length;
  const TRACK_COUNT = TRACKS.length;

  // Card ID helpers
  const trackCardId = (t) => `${t.album}::${t.side}::${t.pos}`;
  const albumCardId = (a) => a.album;

  const SCORE_RETIRED = 3;
  const stop = `onclick="event.stopPropagation()"`;
  const extIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M7 17L17 7M9 7h8v8"/></svg>';
  const spotifyIcon = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.6 0 12 0zm5.5 17.3c-.2.3-.6.4-1 .2-2.7-1.6-6-2-10-1.1-.4.1-.7-.2-.8-.5-.1-.4.2-.7.5-.8 4.3-1 8.1-.6 11.1 1.2.3.2.4.7.2 1zm1.5-3.3c-.3.4-.8.5-1.2.3-3-1.9-7.7-2.4-11.3-1.3-.4.1-.9-.1-1-.5-.1-.4.1-.9.5-1 4.1-1.3 9.2-.7 12.7 1.5.3.2.5.7.3 1zm.1-3.4c-3.7-2.2-9.7-2.4-13.2-1.3-.5.2-1.1-.1-1.2-.6-.2-.5.1-1.1.6-1.2 4-1.2 10.7-1 14.9 1.5.5.3.6.9.4 1.3-.3.4-.9.6-1.5.3z"/></svg>';

  // Build the pool depending on mode — we'll swap allIds/byId on mode change
  function buildAlbumPool() {
    const byId = new Map(DATA.map(a => [albumCardId(a), a]));
    const allIds = DATA.map(albumCardId);
    return { allIds, byId, cardId: albumCardId };
  }

  function buildTrackPool() {
    const byId = new Map(TRACKS.map(t => [trackCardId(t), t]));
    const allIds = TRACKS.map(trackCardId);
    return { allIds, byId, cardId: trackCardId };
  }

  // Start with album pool — will swap on mode change
  let pool = buildAlbumPool();
  let currentCardId = pool.cardId;

  const engine = new DeckEngine({
    storeKey: "crammys-beatles-v1",
    defaultState: { mode: "a2t", idx: 0, order: null, scores: {}, lastMode: "a2t" },
    migrateState(s) {
      if (!s.scores || typeof s.scores !== "object") s.scores = {};
      if (!s.lastMode || s.lastMode === "study") s.lastMode = "a2t";
      return s;
    },
    allIds: pool.allIds,
    byId: pool.byId,
    cardId: (c) => currentCardId(c),
    activeFilter(id, state) {
      if (engine.scoreOf(id) >= SCORE_RETIRED) return false;
      return true;
    },
    inScopeFilter(id, state) {
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

  // Sync pool to mode
  function syncPool() {
    const isTrackMode = state.mode === "t2a" || state.mode === "p2t";
    const isStudyFromTrack = state.mode === "study" && (state.lastMode === "t2a" || state.lastMode === "p2t");
    if (isTrackMode || isStudyFromTrack) {
      pool = buildTrackPool();
      currentCardId = trackCardId;
    } else {
      pool = buildAlbumPool();
      currentCardId = albumCardId;
    }
    engine.updatePool(pool.allIds, pool.byId);
  }

  // Initial pool sync
  syncPool();

  const frontFace = document.getElementById("frontFace");
  const front = { prompt: document.getElementById("frontPrompt"), text: document.getElementById("frontText"), tag: document.getElementById("frontTag") };
  const back = { tag: document.getElementById("backTag"), body: document.getElementById("backBody") };
  const counter = document.getElementById("counter");
  const scopeText = document.getElementById("scopeText");
  const scopeExtras = document.getElementById("scopeExtras");
  const progress = document.getElementById("progress");

  function sideLabel(s) { return "Side " + SIDE_LABELS[s]; }

  function renderTracklist(albumData, highlightSide, highlightPos) {
    let html = "";
    for (const [side, tracks] of Object.entries(albumData.sides)) {
      html += `<div class="tracklist-side"><strong>${sideLabel(side)}</strong>`;
      html += `<ol class="tracklist" start="1">`;
      for (let i = 0; i < tracks.length; i++) {
        const active = side === highlightSide && i === highlightPos;
        html += `<li class="${active ? "track-highlight" : ""}">${escapeHtml(tracks[i])}</li>`;
      }
      html += `</ol></div>`;
    }
    return html;
  }

  function albumLinks(albumData) {
    const links = [];
    if (albumData.spotify) {
      links.push(`<a class="ext" href="https://open.spotify.com/album/${albumData.spotify}" target="_blank" rel="noopener" title="Listen on Spotify" ${stop}>${spotifyIcon} Spotify</a>`);
    }
    if (albumData.wikipedia) {
      links.push(`<a class="ext" href="${albumData.wikipedia}" target="_blank" rel="noopener" title="Wikipedia" ${stop}>${extIcon} Wikipedia</a>`);
    }
    return links.length ? `<div class="detail-grid"><div class="row"><span class="label">Links</span><span class="val">${links.join(" &nbsp; ")}</span></div></div>` : "";
  }

  function render() {
    const ord = engine.activeOrder();
    const { learned, total } = engine.learnedAndTotal();
    const c = engine.currentCard();

    const isTrackMode = state.mode === "t2a" || state.mode === "p2t";
    const isStudyFromTrack = state.mode === "study" && (state.lastMode === "t2a" || state.lastMode === "p2t");

    scopeText.textContent = (isTrackMode || isStudyFromTrack) ? `${TRACK_COUNT} tracks` : `${ALBUM_COUNT} albums`;
    scopeExtras.textContent = "";

    if (!c) {
      counter.textContent = `${learned} / ${total}`;
      progress.style.width = total ? `${(learned / total) * 100}%` : "0%";
      frontFace.classList.remove("image-mode");
      front.tag.textContent = "All caught up"; front.prompt.textContent = "";
      front.text.innerHTML = `<span style="font-size:.5em;color:var(--ink-soft);font-family:inherit">Every card in this scope is learned. Open the deck chip and click <em>Start over</em>, or switch modes.</span>`;
      back.body.innerHTML = ""; engine.renderScoreStars(null); return;
    }

    counter.textContent = `${state.idx + 1} / ${ord.length}`;
    progress.style.width = `${((state.idx + 1) / ord.length) * 100}%`;
    frontFace.classList.remove("image-mode");

    if (state.mode === "a2t") {
      // Album -> Tracks: front shows album name + year, back shows full tracklist
      front.tag.textContent = "Album";
      front.prompt.textContent = "What are the tracks?";
      front.text.innerHTML = `<span>${escapeHtml(c.album)}</span><div class="prompt" style="margin-top:8px;font-size:13px">${c.year}</div>`;

      back.tag.textContent = "Tracklist";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.album)} (${c.year})</div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + renderTracklist(c, null, null) + albumLinks(c);

    } else if (state.mode === "t2a") {
      // Track -> Album: front shows track name, back shows which album + position
      front.tag.textContent = "Track";
      front.prompt.textContent = "Which album?";
      front.text.innerHTML = `<span>${escapeHtml(c.track)}</span>`;

      back.tag.textContent = "Album";
      const posText = `${sideLabel(c.side)}, Track ${c.pos + 1}`;
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${escapeHtml(c.track)}</div>
          <div class="answer"><span>${escapeHtml(c.album)}</span></div>
          <div class="prompt" style="margin-top:4px;font-size:13px">${posText} · ${c.year}</div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + renderTracklist(c._albumData, c.side, c.pos) + albumLinks(c._albumData);

    } else if (state.mode === "p2t") {
      // Position -> Track: front shows position + album, back shows track name
      const posText = `${sideLabel(c.side)}, Track ${c.pos + 1}`;
      front.tag.textContent = "Position";
      front.prompt.textContent = posText;
      front.text.innerHTML = `<span>${escapeHtml(c.album)}</span><div class="prompt" style="margin-top:8px;font-size:13px">${c.year}</div>`;

      back.tag.textContent = "Track";
      const headerBlock = `<div class="study-anchor">
        <div class="study-info">
          <div class="prompt">${posText} on ${escapeHtml(c.album)} (${c.year})</div>
          <div class="answer"><span>${escapeHtml(c.track)}</span></div>
        </div>
      </div>`;
      back.body.innerHTML = headerBlock + renderTracklist(c._albumData, c.side, c.pos) + albumLinks(c._albumData);

    } else {
      // Study mode
      front.tag.textContent = "Study";
      front.prompt.textContent = "";
      if (isStudyFromTrack) {
        front.text.textContent = c.track;
        back.tag.textContent = "Track";
        const posText = `${sideLabel(c.side)}, Track ${c.pos + 1}`;
        const headerBlock = `<div class="study-anchor">
          <div class="study-info">
            <div class="prompt">${escapeHtml(c.album)} (${c.year})</div>
            <div class="answer"><span>${escapeHtml(c.track)}</span></div>
            <div class="prompt" style="margin-top:4px;font-size:13px">${posText}</div>
          </div>
        </div>`;
        back.body.innerHTML = headerBlock + renderTracklist(c._albumData, c.side, c.pos) + albumLinks(c._albumData);
      } else {
        front.text.textContent = c.album;
        back.tag.textContent = "Album";
        const headerBlock = `<div class="study-anchor">
          <div class="study-info">
            <div class="prompt">${escapeHtml(c.album)} (${c.year})</div>
          </div>
        </div>`;
        back.body.innerHTML = headerBlock + renderTracklist(c, null, null) + albumLinks(c);
      }
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
    syncPool();
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
  document.getElementById("beatlesTrackCount").textContent = String(TRACK_COUNT);
  document.getElementById("beatlesAlbumCount").textContent = String(ALBUM_COUNT);
  const { open: openAbout, close: closeAbout } = DeckEngine.bindModal(aboutModal, document.getElementById("aboutClose"), document.getElementById("aboutBtn"));

  // Deck modal
  const deckModal = document.getElementById("deckModal");
  const deckCountEl = document.getElementById("deckCount");

  function syncDeckModal() {
    const isTrackMode = state.mode === "t2a" || state.mode === "p2t";
    const isStudyFromTrack = state.mode === "study" && (state.lastMode === "t2a" || state.lastMode === "p2t");
    const total = (isTrackMode || isStudyFromTrack) ? TRACK_COUNT : ALBUM_COUNT;
    const unit = (isTrackMode || isStudyFromTrack) ? "tracks" : "albums";
    deckCountEl.innerHTML = `<em>${total}</em> ${unit} in deck`;
  }

  const { close: closeDeck } = DeckEngine.bindModal(deckModal, document.getElementById("deckClose"));
  document.getElementById("deckChip").addEventListener("click", () => { syncDeckModal(); DeckEngine.openModal(deckModal); }, { signal });
  document.getElementById("resetProgressBtn").addEventListener("click", () => { closeDeck(); engine.reset(); }, { signal });

  // Keyboard
  engine.bindKeyboard({ signal, extraKeys(e) {
    switch (e.key) {
      case "n": case "N": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.missed(); return true;
      case "y": case "Y": if (engine.cardEl.classList.contains("flipped") && !engine.isStudy()) engine.gotIt(); return true;
      case "l": case "L": setMode(engine.isStudy() ? (state.lastMode || "a2t") : "study"); return true;
      case "?": e.preventDefault(); if (aboutModal.hidden) openAbout(); else closeAbout(); return true;
      case "Escape": if (!aboutModal.hidden) closeAbout(); else if (!deckModal.hidden) closeDeck(); return true;
    }
    return false;
  }});

  // Set initial pool and render
  syncPool();
  if (engine.isStudy()) engine.cardEl.classList.add("flipped");
  render();
}
