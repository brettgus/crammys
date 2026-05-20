#!/usr/bin/env python3
"""
Logo upgrade pass: for every chain, look up Wikidata P154 (logo image) and
download the actual brand mark from Wikimedia Commons. Falls back to the
existing logo if P154 is missing.

This replaces the storefront-photo placeholders (Subway, Tim Hortons, Krispy
Kreme, etc.) that came from Wikipedia's pageimages endpoint.
"""
import os, json, re, time, urllib.request, urllib.parse, urllib.error, gzip

# ── HTTP helpers ─────────────────────────────────────────────────────
def _http(url, max_retries=4, accept_html=False):
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Crammys/1.0 (personal flashcard app)",
            "Accept": "*/*" if accept_html else "application/json",
            "Accept-Encoding": "identity",
        })
        try:
            return urllib.request.urlopen(req, timeout=45)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    429 — sleeping {wait}s and retrying…")
                time.sleep(wait)
                continue
            if e.code == 404 and not accept_html:
                return None
            raise

def http_json(url):
    r = _http(url)
    if not r: return None
    data = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
    return json.loads(data)

# ── Wikidata: find P154 logo filename ───────────────────────────────
def wikidata_logo(qid):
    if not qid: return None
    try:
        d = http_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    except Exception as e:
        print(f"  ! wikidata fetch: {e}"); return None
    if not d: return None
    claims = d["entities"][qid].get("claims", {})
    for c in claims.get("P154", []) or []:
        snak = c.get("mainsnak", {})
        if snak.get("snaktype") != "value": continue
        val = snak.get("datavalue", {}).get("value")
        if isinstance(val, str): return val
    return None

# ── Commons: filename → direct binary download via Special:FilePath ─
def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def download_commons_file(filename, target_dir, display):
    """Hit Special:FilePath which 302s to the canonical Commons URL. Also
    derives the local extension from the redirected URL."""
    safe = urllib.parse.quote(filename.replace(' ', '_'))
    # width=600 keeps SVG/PNG sized for our card. For SVG, Commons re-renders to PNG.
    url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{safe}?width=600"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Crammys/1.0 (personal flashcard app)",
        })
        with urllib.request.urlopen(req, timeout=45) as r:
            data = r.read()
            final_url = r.url
    except Exception as e:
        print(f"  ! download failed: {e}")
        return None
    ext = os.path.splitext(urllib.parse.urlparse(final_url).path)[1] or ".png"
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"): ext = ".png"
    path = os.path.join(target_dir, f"{slug(display)}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path

# ── Main ────────────────────────────────────────────────────────────
def main():
    if not os.path.exists("chains/manifest.json"):
        print("chains/manifest.json missing"); return
    with open("chains/manifest.json", encoding="utf-8") as f:
        chains = json.load(f)

    target_dir = "chains/logos"
    os.makedirs(target_dir, exist_ok=True)

    upgraded = 0
    added = 0
    for c in chains:
        qid = c.get("wiki_id")
        if not qid:
            continue
        # Skip chains that already got a Wikidata-sourced logo on a previous run
        if c.get("logo_filename"):
            continue
        filename = wikidata_logo(qid)
        if not filename:
            print(f"  · {c['name']}: no P154 logo on Wikidata")
            time.sleep(0.4)
            continue
        # Don't re-download if we already have a clean logo file pointing to the same name.
        new_path = download_commons_file(filename, target_dir, c["name"])
        if not new_path:
            time.sleep(0.4)
            continue
        old = c.get("logo")
        # Remove the old file if it differs and is no longer used
        if old and old != new_path and os.path.exists(old):
            try: os.remove(old)
            except: pass
        c["logo"] = new_path
        c["logo_filename"] = filename
        if old:
            upgraded += 1
            print(f"  ↻ {c['name']}: {filename}")
        else:
            added += 1
            print(f"  + {c['name']}: {filename}")
        time.sleep(2.5)  # pacing to dodge wikimedia's bot rate-limit

    with open("chains/manifest.json", "w", encoding="utf-8") as f:
        json.dump(chains, f, ensure_ascii=False, indent=2)
    with open("chains.js", "w", encoding="utf-8") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(chains, ensure_ascii=False) + ";\n")

    have = sum(1 for c in chains if c.get("logo"))
    print(f"\nDone. {upgraded} upgraded, {added} newly added.")
    print(f"Coverage: {have}/{len(chains)} chains have a logo.")

if __name__ == "__main__":
    main()
