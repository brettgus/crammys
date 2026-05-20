#!/usr/bin/env python3
"""
Backfill: parse Wikipedia infoboxes for chain founders that Wikidata didn't have.

Reads chains.js / chains/manifest.json, for any chain with no `founders`,
fetches the Wikipedia article's lead-section wikitext and extracts the
`founder = …` (or `founders = …`) field from the infobox. Cleans up wikilinks,
HTML, refs, and writes back chains.js + manifest.
"""
import os, json, re, time, urllib.request, urllib.parse, urllib.error, gzip

API = "https://en.wikipedia.org/w/api.php"

def http_json(url, max_retries=4):
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Crammys/1.0 (personal flashcard app)",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    429 — sleeping {wait}s and retrying…")
                time.sleep(wait)
                continue
            raise

def get_lead_wikitext(slug):
    url = API + "?" + urllib.parse.urlencode({
        "action": "parse",
        "page": slug,
        "format": "json",
        "prop": "wikitext",
        "section": "0",
    })
    d = http_json(url)
    return (d.get("parse") or {}).get("wikitext", {}).get("*", "")

def strip_refs(s):
    """Remove <ref>...</ref> blocks and named references."""
    s = re.sub(r'<ref[^>]*?/>', '', s, flags=re.IGNORECASE)
    s = re.sub(r'<ref[^>]*?>.*?</ref>', '', s, flags=re.IGNORECASE | re.DOTALL)
    return s

def extract_field(wikitext, *field_names):
    """Pull the value of an infobox field like `founder = …`. Tries each name in order."""
    for fname in field_names:
        # Match pipe-prefixed field until the next pipe or close braces (one match)
        pattern = re.compile(
            r'\|\s*' + re.escape(fname) + r'\s*=\s*(.+?)(?=\n\s*\|\s*\w|\n\s*\}\})',
            re.DOTALL | re.IGNORECASE
        )
        m = pattern.search(wikitext)
        if m: return m.group(1).strip()
    return None

# Strip nowiki, comments
def strip_comments(s):
    s = re.sub(r'<!--.*?-->', '', s, flags=re.DOTALL)
    s = re.sub(r'<nowiki>(.*?)</nowiki>', r'\1', s, flags=re.DOTALL)
    return s

def parse_founders(raw):
    """Convert raw infobox value (with wikilinks, HTML) into a list of person names."""
    if not raw: return []
    s = strip_refs(raw)
    s = strip_comments(s)
    # Replace <br>, <br/>, <br /> with a separator we'll split on
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
    # Remove HTML tags
    s = re.sub(r'<[^>]+>', '', s)
    # Some templates: {{plainlist|...}} or {{ubl|A|B}} — split on |
    m = re.match(r'\s*\{\{(?:plainlist|hlist|unbulleted list|ubl|flatlist|bulleted list)\s*\|(.*?)\}\}\s*$', s, re.DOTALL | re.IGNORECASE)
    if m:
        s = m.group(1).replace('|', '\n')
    # Remove other templates wholesale (lightly):
    s = re.sub(r'\{\{[^{}]*\}\}', '', s)
    # Split on newlines, " and ", commas (but careful with names having commas)
    parts = re.split(r'\n|;|\s+and\s+|\s+&\s+', s)
    out = []
    for p in parts:
        p = p.strip(" \t,*•·-—")
        if not p: continue
        # Wikilinks: [[Article]] or [[Article|Display]]
        p = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', p)
        p = re.sub(r'\[\[([^\]]+)\]\]', r'\1', p)
        # Drop stray brackets
        p = p.replace('[[', '').replace(']]', '')
        # Drop trailing parenthetical (e.g., "Joe Smith (founder)")
        p = re.sub(r'\s*\([^)]*\)\s*$', '', p)
        p = p.strip(" ,.;:'\"")
        # Throw out if it's clearly junk (numbers, generic words)
        if not p or len(p) < 3: continue
        if p.lower() in ("founder", "founders", "see below", "see article"): continue
        # Throw out if too long (likely a sentence, not a name)
        if len(p) > 60: continue
        out.append(p)
    # Dedupe preserving order
    seen = set(); deduped = []
    for n in out:
        if n.lower() not in seen:
            seen.add(n.lower()); deduped.append(n)
    return deduped

# ── Build the wiki slug → Wikipedia article name mapping from fetch_chains.py
def load_chain_slugs():
    """Mirror fetch_chains.py's CHAINS list so we know the wiki slug per chain."""
    out = {}
    src = open("fetch_chains.py", encoding="utf-8").read()
    for m in re.finditer(r'\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"\)', src):
        display, wiki, _cat = m.group(1), m.group(2), m.group(3)
        out[display] = wiki
    return out

def main():
    if not os.path.exists("chains/manifest.json"):
        print("chains/manifest.json missing — run fetch_chains.py first"); return
    with open("chains/manifest.json", encoding="utf-8") as f:
        chains = json.load(f)
    slug_map = load_chain_slugs()
    n_added = 0
    for c in chains:
        if c.get("founders"):  # already populated
            continue
        slug = slug_map.get(c["name"]) or c.get("wiki_slug")
        if not slug:
            print(f"  ! {c['name']}: no wiki slug"); continue
        print(f"--- {c['name']}  ({slug})")
        try:
            wt = get_lead_wikitext(slug)
        except Exception as e:
            print(f"  ! wikitext fetch failed: {e}"); continue
        raw = extract_field(wt, "founders", "founder")
        if not raw:
            print(f"  · no founder field in infobox"); continue
        founders = parse_founders(raw)
        if not founders:
            print(f"  · couldn't parse founders from: {raw[:80]!r}"); continue
        c["founders"] = founders
        n_added += 1
        print(f"  + {founders}")
        time.sleep(1.0)

    # Save
    with open("chains/manifest.json", "w", encoding="utf-8") as f:
        json.dump(chains, f, ensure_ascii=False, indent=2)
    with open("chains.js", "w", encoding="utf-8") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(chains, ensure_ascii=False) + ";\n")
    print(f"\nDone. Added founders to {n_added} chains.")

if __name__ == "__main__":
    main()
