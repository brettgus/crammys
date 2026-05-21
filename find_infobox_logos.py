#!/usr/bin/env python3
"""
Scrape each chain's Wikipedia infobox for the logo image filename.
The infobox typically has `| logo = File:Foo logo.svg` or `| image = File:Foo logo.svg`.
Saves matches into chains/manifest.json's logo_filename field for the next
fetch_chain_logos.py run to pick up.
"""
import urllib.request, urllib.parse, json, gzip, time, re, os

# Same target list as search_logos.py
TARGETS = {
    "Dunkin'",
    "Taco Bell",
    "Little Caesars",
    "Chipotle Mexican Grill",
    "Panda Express",
    "Wingstop",
    "Marco's Pizza",
    "Zaxby's",
    "Bojangles'",
    "Einstein Bros. Bagels",
    "MOD Pizza",
    "El Pollo Loco",
    "Caribou Coffee",
    "Noodles & Company",
    "Potbelly Sandwich Shop",
    "CAVA",
    "Blaze Pizza",
    "Pei Wei Asian Diner",
}

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
        except Exception as e:
            if attempt < max_retries - 1 and "429" in str(e):
                w = 2 ** (attempt + 1)
                print(f"    429 — sleeping {w}s"); time.sleep(w); continue
            raise

def get_lead_wikitext(slug):
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "parse", "page": slug, "format": "json",
        "prop": "wikitext", "section": "0",
    })
    return ((http_json(url).get("parse") or {}).get("wikitext", {}) or {}).get("*", "")

def find_logo_filename(wikitext):
    """Try multiple infobox parameter names commonly used for company logos."""
    for field in ("logo", "image", "logo_caption"):
        pattern = re.compile(
            r'\|\s*' + field + r'\s*=\s*(.+?)(?=\n\s*\|\s*\w|\n\s*\}\})',
            re.DOTALL | re.IGNORECASE,
        )
        m = pattern.search(wikitext)
        if not m: continue
        val = m.group(1).strip()
        # Drop refs and templates
        val = re.sub(r'<ref[^>]*?>.*?</ref>', '', val, flags=re.DOTALL | re.IGNORECASE)
        val = re.sub(r'<[^>]+>', '', val)
        # File:Name.ext or [[File:Name.ext|...]]
        m2 = re.search(r'\[?\[?\s*(?:File|Image):\s*([^|\]\n]+\.(?:svg|png|jpg|jpeg))', val, re.IGNORECASE)
        if m2:
            return m2.group(1).strip()
        # Or raw: "Foo logo.svg"
        m2 = re.search(r'([A-Za-z0-9][^\n|]+?\.(?:svg|png|jpg|jpeg))', val)
        if m2:
            return m2.group(1).strip()
    return None

def main():
    with open("chains/manifest.json", encoding="utf-8") as f:
        chains = json.load(f)
    updates = {}
    for c in chains:
        if c["name"] not in TARGETS: continue
        slug = c.get("wiki_slug")
        if not slug: continue
        print(f"--- {c['name']}  ({slug})")
        try:
            wt = get_lead_wikitext(slug)
        except Exception as e:
            print(f"  ! {e}"); continue
        fn = find_logo_filename(wt)
        if fn:
            updates[c["name"]] = fn
            print(f"  + {fn}")
        else:
            print(f"  · no logo field found")
        time.sleep(1.2)
    print("\n# Paste into fetch_chain_logos.py MANUAL_LOGOS:")
    for name, fn in updates.items():
        # Quote handling: use single quotes around the value, double around the key
        key = '"' + name.replace('"', '\\"') + '"'
        print(f'    {key:35} {fn!r},')

if __name__ == "__main__":
    main()
