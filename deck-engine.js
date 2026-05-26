// deck-engine.js — shared card-engine for all Crammys decks (ES module)

const _v = document.querySelector('link[rel="stylesheet"]')?.href?.match(/\?v=([^&]*)/)?.[1] || '';
export function loadScript(src, { onerror } = {}) {
  return new Promise((resolve, reject) => {
    const busted = _v ? `${src}${src.includes('?') ? '&' : '?'}v=${_v}` : src;
    if (document.querySelector(`script[src="${busted}"],script[src="${src}"]`)) { resolve(); return; }
    const s = document.createElement("script");
    s.src = busted;
    s.onload = resolve;
    s.onerror = onerror ? () => { onerror(); resolve(); } : reject;
    document.head.appendChild(s);
  });
}

export function shuffleArray(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

export function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, ch =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[ch]));
}

// ─── Spotify embed helpers ───────────────────────────────────────────
export function openSpotifyEmbed(spotifyId, type = "track") {
  const modal = document.getElementById("spotifyModal");
  const frame = document.getElementById("spotifyFrame");
  if (!modal || !frame) return;
  const theme = document.documentElement.getAttribute("data-theme") === "dark" ? 0 : 1;
  frame.src = `https://open.spotify.com/embed/${type}/${spotifyId}?theme=${theme}`;
  modal.hidden = false;
  document.body.style.overflow = "hidden";
}

export function closeSpotifyEmbed() {
  const modal = document.getElementById("spotifyModal");
  const frame = document.getElementById("spotifyFrame");
  if (!modal) return;
  modal.hidden = true;
  if (frame) frame.src = "about:blank";
  document.body.style.overflow = "";
}

// Expose on window so inline onclick handlers (inside cards that use stopPropagation)
// can call it without needing module scope.
window.openSpotifyEmbed = openSpotifyEmbed;

export class DeckEngine {
  constructor({
    storeKey,
    defaultState,
    migrateState,
    allIds,
    byId,
    cardId,
    activeFilter,
    inScopeFilter,
    isStudyMode,
    render,
    onBeforeNavigate,
    scoreRetired = 3,
    scoreWeights = [4, 2, 1, 0],
    flipMidpoint = 280,
    reshuffleOnWrap = false,
    onShuffle,
    cardEl,
    navRowEl,
    scoreStarsFrontEl,
    scoreStarsBackEl,
  }) {
    this.storeKey = storeKey;
    this.allIds = allIds;
    this.byId = byId;
    this.cardId = cardId;
    this.reshuffleOnWrap = reshuffleOnWrap;
    this._onShuffle = onShuffle || (() => {});
    this.activeFilter = activeFilter;
    this.inScopeFilter = inScopeFilter;
    this.isStudyMode = isStudyMode;
    this._render = render;
    this._onBeforeNavigate = onBeforeNavigate || (() => {});
    this.scoreRetired = scoreRetired;
    this.scoreWeights = scoreWeights;
    this.flipMidpoint = flipMidpoint;
    this.cardEl = cardEl;
    this.navRowEl = navRowEl;
    this.scoreStarsFrontEl = scoreStarsFrontEl;
    this.scoreStarsBackEl = scoreStarsBackEl;

    this.state = this._loadState(defaultState, migrateState);

    const idSet = new Set(this.allIds);
    const valid = Array.isArray(this.state.order)
      && this.state.order.length === this.allIds.length
      && this.state.order.every(id => typeof id === "string" && idSet.has(id));
    if (!valid) {
      this.state.order = this.weightedShuffle(this.allIds);
      this.state.idx = 0;
    }
  }

  _loadState(defaultState, migrateState) {
    try {
      const saved = JSON.parse(localStorage.getItem(this.storeKey) || "null");
      const merged = Object.assign({}, defaultState, saved || {});
      return migrateState ? migrateState(merged) : merged;
    } catch {
      return { ...defaultState };
    }
  }

  persist() {
    localStorage.setItem(this.storeKey, JSON.stringify(this.state));
  }

  scoreOf(id) {
    return this.state.scores[id] || 0;
  }

  setScore(id, score) {
    this.state.scores[id] = Math.max(0, Math.min(this.scoreRetired, score));
    this.persist();
  }

  weightedShuffle(ids) {
    return ids
      .map(id => {
        const w = this.scoreWeights[Math.min(this.scoreOf(id), this.scoreWeights.length - 1)] || 0.1;
        return [id, Math.random() / w];
      })
      .sort((a, b) => a[1] - b[1])
      .map(x => x[0]);
  }

  activeOrder() {
    return this.state.order.filter(id => this.activeFilter(id, this.state));
  }

  currentCard() {
    const ord = this.activeOrder();
    if (!ord.length) return null;
    this.state.idx = ((this.state.idx % ord.length) + ord.length) % ord.length;
    return this.byId.get(ord[this.state.idx]);
  }

  learnedAndTotal() {
    let learned = 0, total = 0;
    for (const id of this.state.order) {
      if (!this.inScopeFilter(id, this.state)) continue;
      total++;
      if (this.scoreOf(id) >= this.scoreRetired) learned++;
    }
    return { learned, total };
  }

  updatePool(allIds, byId) {
    this.allIds = allIds;
    this.byId = byId;
    this.state.order = this.weightedShuffle(allIds);
    this.state.idx = 0;
    this._onShuffle();
  }

  isStudy() {
    return this.isStudyMode(this.state);
  }

  // ─── Card flip ─────────────────────────────────────────────────────

  flip() {
    if (this.isStudy()) return;
    this.cardEl.classList.toggle("flipped");
    this.syncNav();
  }

  unflipAndThen(fn) {
    if (this.isStudy()) { fn(); return; }
    if (this.cardEl.classList.contains("flipped")) {
      this.cardEl.classList.remove("flipped");
      this.syncNav();
      setTimeout(fn, this.flipMidpoint);
    } else {
      fn();
    }
  }

  syncNav() {
    this.navRowEl.classList.toggle("show-back",
      this.cardEl.classList.contains("flipped") && !this.isStudy());
  }

  renderScoreStars(card) {
    const score = card ? this.scoreOf(this.cardId(card)) : 0;
    const html = score > 0 ? "★".repeat(Math.min(score, this.scoreRetired - 1)) : "";
    if (this.scoreStarsFrontEl) this.scoreStarsFrontEl.innerHTML = html;
    if (this.scoreStarsBackEl) this.scoreStarsBackEl.innerHTML = html;
  }

  // ─── Navigation ────────────────────────────────────────────────────

  _advance(o, fromIdx) {
    const nextIdx = (fromIdx + 1) % o.length;
    if (this.reshuffleOnWrap && o.length > 1 && fromIdx === o.length - 1 && nextIdx === 0) {
      this.state.order = this.weightedShuffle(this.allIds);
      this._onShuffle();
      return 0;
    }
    return nextIdx;
  }

  next() {
    const ord = this.activeOrder();
    if (!ord.length) return;
    this._onBeforeNavigate();
    this.unflipAndThen(() => {
      const o = this.activeOrder();
      if (!o.length) return;
      this.state.idx = this._advance(o, this.state.idx % o.length);
      this.persist();
      this._render();
    });
  }

  prev() {
    const ord = this.activeOrder();
    if (!ord.length) return;
    this._onBeforeNavigate();
    this.unflipAndThen(() => {
      const o = this.activeOrder();
      if (!o.length) return;
      this.state.idx = (this.state.idx - 1 + o.length) % o.length;
      this.persist();
      this._render();
    });
  }

  shuffle() {
    this._onBeforeNavigate();
    this.unflipAndThen(() => {
      this.state.order = this.weightedShuffle(this.allIds);
      this.state.idx = 0;
      this._onShuffle();
      this.persist();
      this._render();
    });
  }

  reset() {
    if (!confirm("Start over and forget which cards you've gotten right? This clears every card's score.")) return;
    this._onBeforeNavigate();
    this.unflipAndThen(() => {
      this.state.order = shuffleArray(this.allIds);
      this.state.idx = 0;
      this.state.scores = {};
      this._onShuffle();
      this.persist();
      this._render();
    });
  }

  rate(delta) {
    const c = this.currentCard();
    if (!c) return;
    const id = this.cardId(c);
    if (delta > 0) this.setScore(id, this.scoreOf(id) + 1);
    else this.setScore(id, 0);
    this._onBeforeNavigate();
    this.unflipAndThen(() => {
      const o = this.activeOrder();
      if (!o.length) { this._render(); return; }
      const currentIdx = this.state.idx % o.length;
      if (o[currentIdx] === id) {
        this.state.idx = this._advance(o, currentIdx);
      } else {
        this.state.idx = currentIdx;
      }
      this.persist();
      this._render();
    });
  }

  gotIt() { this.rate(+1); }
  missed() { this.rate(-1); }

  // ─── Touch swipe ───────────────────────────────────────────────────

  bindSwipe(el, { signal } = {}) {
    let tx = 0, ty = 0, dxMax = 0, dyMax = 0;
    el.addEventListener("touchstart", (e) => {
      const t = e.changedTouches[0];
      tx = t.clientX; ty = t.clientY;
      dxMax = 0; dyMax = 0;
    }, { passive: true, signal });
    el.addEventListener("touchmove", (e) => {
      const t = e.changedTouches[0];
      dxMax = Math.max(dxMax, Math.abs(t.clientX - tx));
      dyMax = Math.max(dyMax, Math.abs(t.clientY - ty));
    }, { passive: true, signal });
    el.addEventListener("touchend", (e) => {
      const t = e.changedTouches[0];
      const dx = t.clientX - tx;
      if (Math.abs(dx) > 50 && dxMax > dyMax * 1.5) {
        if (dx < 0) this.next(); else this.prev();
      }
    }, { signal });
  }

  // ─── Tooltip system ────────────────────────────────────────────────

  bindTooltips({ tipEl, selector, tipHTML, signal }) {
    let tipAnchor = null, hideTimer = null, showTimer = null;
    const SHOW_DELAY = 280;

    const positionTip = (el) => {
      const r = el.getBoundingClientRect();
      const tw = tipEl.offsetWidth, th = tipEl.offsetHeight, m = 10;
      let x = r.left + r.width / 2 - tw / 2;
      let y = r.top - th - m;
      if (y < 8) y = r.bottom + m;
      if (y + th > window.innerHeight - 8) y = Math.max(8, window.innerHeight - th - 8);
      x = Math.max(8, Math.min(window.innerWidth - tw - 8, x));
      tipEl.style.left = `${x}px`;
      tipEl.style.top = `${y}px`;
    };

    const showTip = (el) => {
      clearTimeout(hideTimer); clearTimeout(showTimer);
      if (tipAnchor === el && tipEl.classList.contains("visible")) return;
      tipEl.innerHTML = tipHTML(el);
      tipEl.classList.add("visible");
      tipEl.setAttribute("aria-hidden", "false");
      tipAnchor = el;
      positionTip(el);
    };

    const scheduleShow = (el) => {
      clearTimeout(hideTimer);
      if (tipEl.classList.contains("visible")) { if (tipAnchor !== el) showTip(el); return; }
      clearTimeout(showTimer);
      showTimer = setTimeout(() => showTip(el), SHOW_DELAY);
    };

    const hideTip = (immediate) => {
      clearTimeout(hideTimer); clearTimeout(showTimer);
      if (immediate) {
        tipEl.classList.remove("visible");
        tipEl.setAttribute("aria-hidden", "true");
        tipAnchor = null;
      } else {
        hideTimer = setTimeout(() => {
          tipEl.classList.remove("visible");
          tipEl.setAttribute("aria-hidden", "true");
          tipAnchor = null;
        }, 280);
      }
    };

    const HOVER_DEVICE = matchMedia("(hover: hover) and (pointer: fine)").matches;
    if (HOVER_DEVICE) {
      document.addEventListener("mouseover", (e) => {
        const el = e.target.closest(selector);
        if (el) { scheduleShow(el); return; }
        if (e.target.closest("#tooltip")) clearTimeout(hideTimer);
      }, { signal });
      document.addEventListener("mouseout", (e) => {
        const from = e.target.closest(selector) || e.target.closest("#tooltip");
        if (!from) return;
        const to = e.relatedTarget;
        if (to && to.nodeType === 1 && (to.closest(selector) || to.closest("#tooltip"))) return;
        clearTimeout(showTimer);
        hideTip(false);
      }, { signal });
      document.addEventListener("click", (e) => {
        if (e.target.closest(selector) || e.target.closest("#tooltip") || e.target.closest(".ext")) return;
        hideTip(true);
      }, { signal });
    } else {
      document.addEventListener("click", (e) => {
        if (e.target.closest(".ext")) return;
        const el = e.target.closest(selector);
        if (el) {
          e.stopPropagation();
          if (tipAnchor === el && tipEl.classList.contains("visible")) hideTip(true);
          else showTip(el);
          return;
        }
        if (!e.target.closest("#tooltip")) hideTip(true);
      }, { signal });
    }

    window.addEventListener("scroll", () => { if (tipAnchor) positionTip(tipAnchor); }, { passive: true, signal });
    window.addEventListener("resize", () => { if (tipAnchor) positionTip(tipAnchor); }, { signal });

    return hideTip;
  }

  // ─── Keyboard (base bindings) ──────────────────────────────────────

  bindKeyboard({ extraKeys, signal } = {}) {
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.tagName === "SELECT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (extraKeys && extraKeys(e)) return;
      switch (e.key) {
        case " ": e.preventDefault(); this.flip(); break;
        case "ArrowRight": this.next(); break;
        case "ArrowLeft": this.prev(); break;
        case "s": case "S": this.shuffle(); break;
        case "r": case "R": this.reset(); break;
        case "t": case "T": (window.CRAMMYS_toggleTheme || (() => {}))(); break;
      }
    }, { signal });
  }

  // ─── Standard UI wiring ────────────────────────────────────────────

  bindStandardUI({ nextBtn, prevBtn, gotBtn, missedBtn, shuffleBtn, cardClickIgnore, signal }) {
    this.cardEl.addEventListener("click", (e) => {
      if (e.target.closest(cardClickIgnore || "a")) return;
      this.flip();
    }, { signal });
    this.cardEl.addEventListener("keydown", (e) => { if (e.key === "Enter") this.flip(); }, { signal });
    if (nextBtn) nextBtn.addEventListener("click", () => this.next(), { signal });
    if (prevBtn) prevBtn.addEventListener("click", () => this.prev(), { signal });
    if (gotBtn) gotBtn.addEventListener("click", (e) => { e.stopPropagation(); this.gotIt(); }, { signal });
    if (missedBtn) missedBtn.addEventListener("click", (e) => { e.stopPropagation(); this.missed(); }, { signal });
    if (shuffleBtn) shuffleBtn.addEventListener("click", () => this.shuffle(), { signal });
    this.bindSwipe(this.cardEl, { signal });
    if (this.isStudy()) this.cardEl.classList.add("flipped");
    this.syncNav();
  }

  // ─── Modal helpers ─────────────────────────────────────────────────

  static openModal(el) {
    el.hidden = false;
    document.body.style.overflow = "hidden";
  }

  static closeModal(el) {
    if (el.hidden) return;
    el.hidden = true;
    document.body.style.overflow = "";
  }

  static bindModal(backdropEl, closeBtn, openTrigger) {
    const open = () => DeckEngine.openModal(backdropEl);
    const close = () => DeckEngine.closeModal(backdropEl);
    if (closeBtn) closeBtn.addEventListener("click", close);
    backdropEl.addEventListener("click", (e) => { if (e.target === backdropEl) close(); });
    if (openTrigger) openTrigger.addEventListener("click", open);
    return { open, close };
  }
}
