#!/usr/bin/env python3
"""
Re-fetch the full Wikipedia intro extract for every chain and store it in
the `summary` field (no truncation). chains.html slices to 320 chars for
display and shows the full thing in a hover tooltip.

Originally fetch_chains.py truncated to 320 chars at fetch time, which threw
away data we now want to surface on demand.
"""
import json, os, time, urllib.request, urllib.error, gzip

UA = "Crammys/1.0 (personal flashcard app; github.com/brettgus/crammys)"

def _http(url, max_retries=4):
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                print(f"    429 — sleeping {wait}s and retrying…")
                time.sleep(wait); continue
            if e.code == 404: return None
            raise

def fetch_summary(slug):
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
    d = _http(url)
    return (d or {}).get("extract", "").strip() or None

def main():
    with open("chains/manifest.json", encoding="utf-8") as f:
        chains = json.load(f)
    print(f"Refreshing full Wikipedia intro for {len(chains)} chains…\n")

    for i, c in enumerate(chains, 1):
        slug = c.get("wiki_slug")
        if not slug:
            print(f"[{i}/{len(chains)}] {c['name']:30}  · no wiki_slug, skipping")
            continue
        try:
            full = fetch_summary(slug)
        except Exception as e:
            print(f"[{i}/{len(chains)}] {c['name']:30}  ! {e}")
            continue
        if not full:
            print(f"[{i}/{len(chains)}] {c['name']:30}  · no extract")
            continue
        prev_len = len(c.get("summary") or "")
        c["summary"] = full
        print(f"[{i}/{len(chains)}] {c['name']:30}  {prev_len} → {len(full)} chars")
        time.sleep(0.5)

    with open("chains/manifest.json", "w", encoding="utf-8") as f:
        json.dump(chains, f, ensure_ascii=False, indent=2)
    with open("chains.js", "w", encoding="utf-8") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(chains, ensure_ascii=False) + ";\n")
    print(f"\nDone.")

if __name__ == "__main__":
    main()
