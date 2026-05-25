/* Crammys — shared client scripts
 * Theme (dark/light persists across deck pages) + deck-switcher dropdown.
 * Each page should set `window.CURRENT_DECK = "<id>"` BEFORE this file loads.
 */
(function () {
  const DECKS = [
    { id: "bestpicture", name: "Best Picture",      emoji: "🎬", url: "index.html" },
    { id: "chains",      name: "Restaurant Chains", emoji: "🍔", url: "chains.html" },
    { id: "rockhall",    name: "Rock & Roll Hall of Fame", emoji: "🎸", url: "index.html#rockhall" },
  ];
  window.CRAMMYS_DECKS = DECKS;

  // ── Theme ──────────────────────────────────────────────────────────
  const THEME_KEY = "crammys-theme";
  const sun  = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
  const moon = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';

  function setTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem(THEME_KEY, t); } catch (_) {}
    const btn = document.getElementById("themeBtn");
    if (btn) btn.innerHTML = t === "dark" ? sun : moon;
  }
  function readTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (_) { return null; }
  }
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "light";
  }
  function toggleTheme() {
    setTheme(currentTheme() === "dark" ? "light" : "dark");
  }
  // Re-apply (the anti-FOUC inline script already set the attribute, but icon
  // needs to render once #themeBtn exists in the DOM).
  setTheme(readTheme() || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
  document.addEventListener("click", (e) => {
    if (e.target.closest && e.target.closest("#themeBtn")) toggleTheme();
  });
  window.CRAMMYS_setTheme = setTheme;
  window.CRAMMYS_toggleTheme = toggleTheme;

  // ── Deck switcher dropdown ────────────────────────────────────────
  const here = window.CURRENT_DECK || "";
  const btn = document.getElementById("deckBtn");
  const menu = document.getElementById("deckMenu");
  const nameEl = document.getElementById("deckName");
  const emojiEl = document.getElementById("deckEmoji");
  if (btn && menu) {
    const self = DECKS.find(d => d.id === here) || DECKS[0];
    if (nameEl) nameEl.textContent = self.name;
    if (emojiEl) emojiEl.textContent = self.emoji;
    const checkIcon = '<svg class="deck-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';
    menu.innerHTML = DECKS.map(d => `
      <a href="${d.url}" class="${d.id === here ? "current" : ""}" role="menuitem">
        <span class="deck-emoji">${d.emoji}</span>
        <span class="deck-tag">${d.name}</span>
        ${checkIcon}
      </a>
    `).join("");
    function open()  { menu.hidden = false; requestAnimationFrame(() => menu.dataset.open = "true"); btn.setAttribute("aria-expanded","true"); }
    function close() { menu.dataset.open = "false"; btn.setAttribute("aria-expanded","false"); setTimeout(() => { menu.hidden = true; }, 120); }
    btn.addEventListener("click", (e) => { e.stopPropagation(); (menu.dataset.open === "true" ? close() : open()); });
    document.addEventListener("click", (e) => { if (menu.dataset.open === "true" && !menu.contains(e.target) && e.target !== btn) close(); });
    window.addEventListener("keydown", (e) => { if (e.key === "Escape" && menu.dataset.open === "true") close(); });
  }
})();
