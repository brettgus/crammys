#!/usr/bin/env python3
"""
Post-fetch cleanup + ranking:

1. Clean up the 4 founder rows the lazy parser produced (template noise,
   un-split pairs, infobox leaks).
2. Fetch `num_locations` from each chain's Wikipedia infobox and parse
   out an integer.
3. Sort chains by location count and assign each a `rank` field.

Reads / writes chains.js and chains/manifest.json.
"""
import os, json, re, time, urllib.request, urllib.parse, urllib.error, gzip

API = "https://en.wikipedia.org/w/api.php"

# ── HTTP w/ backoff ─────────────────────────────────────────────────
def http_json(url, max_retries=5):
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
        "action": "parse", "page": slug, "format": "json",
        "prop": "wikitext", "section": "0",
    })
    return ((http_json(url).get("parse") or {}).get("wikitext", {}) or {}).get("*", "")

def extract_field(wt, *names):
    for fn in names:
        m = re.search(
            r'\|\s*' + re.escape(fn) + r'\s*=\s*(.+?)(?=\n\s*\|\s*\w|\n\s*\}\})',
            wt, re.DOTALL | re.IGNORECASE,
        )
        if m: return m.group(1).strip()
    return None

# ── (1) Founder cleanup ─────────────────────────────────────────────
# Map of known correct founders for chains whose Wikipedia infobox is missing,
# empty, or otherwise unparseable. Verified against Wikipedia lead paragraphs.
KNOWN_FOUNDERS = {
    "Five Guys":        ["Jerry Murrell", "Janie Murrell"],
    "Wingstop":         ["Antonio Swad", "Bernadette Fiaschetti"],
    "Pei Wei Asian Diner": ["Bill Wang"],
    "Papa Murphy's":    ["Terry Collins"],
    "El Pollo Loco":    ["Juan Francisco Ochoa"],
    "Einstein Bros. Bagels": ["Robert Hammer"],
    "Caribou Coffee":   ["John Puckett", "Kim Puckett"],
    "CAVA":             ["Ted Xenohristos", "Ike Grigoropoulos", "Dimitri Moshovitis", "Brett Schulman"],
    "Arby's":           ["Forrest Raffel", "Leroy Raffel"],
    "Quiznos":          ["Jimmy Lambatos"],
    "Noodles & Company": ["Aaron Kennedy"],
    "MOD Pizza":        ["Scott Svenson", "Ally Svenson"],
    "Blaze Pizza":      ["Elise Wetzel", "Rick Wetzel"],
    # Parser earlier grabbed phrases that mentioned the original company name
    # ("St. Louis Bread Company", "Mike's Giant Submarine Shop"). These are
    # the actual people:
    "Panera Bread":         ["Ken Rosenthal", "Louis Kane", "Ron Shaich"],
    "Jersey Mike's Subs":   ["Peter Cancro"],
    # Dessert / treats — Wikidata P112 was empty for most of these
    "Cinnabon":             ["Rich Komen", "Ray Lindstrom"],
    "Cold Stone Creamery":  ["Donald Sutherland", "Susan Sutherland"],
    "Dairy Queen":          ["J.F. McCullough", "Alex McCullough"],
    "Dippin' Dots":         ["Curt Jones"],
    "Carvel":               ["Tom Carvel"],
    "Wetzel's Pretzels":    ["Rick Wetzel", "Bill Phelps"],
    "Jamba":                ["Kirk Perron"],
}

# ── (2) Locations parsing ──────────────────────────────────────────
def parse_locations(raw):
    """Pull an integer out of a num_locations field like '~13,500 (2024)' or '14,036[1]'."""
    if not raw: return None
    s = re.sub(r'<ref[^>]*?>.*?</ref>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r'<ref[^>]*?/>', '', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', '', s)
    s = re.sub(r'\{\{[^{}]*\}\}', '', s)
    s = re.sub(r'\([^)]*\)', '', s)
    # Match the largest number (sometimes infobox says "X US / Y worldwide")
    nums = re.findall(r'[\d,]+', s)
    if not nums: return None
    parsed = []
    for n in nums:
        n = n.replace(",", "")
        try:
            v = int(n)
            if v >= 50:  # filter out year fragments, page nums, etc.
                parsed.append(v)
        except ValueError:
            pass
    if not parsed: return None
    return max(parsed)

# Hand-known overrides for chains whose Wikipedia infobox doesn't expose
# `num_locations` cleanly (or has wildly stale data). Sourced from recent
# QSR Magazine top-50 / public investor decks; ballpark US-only counts.
KNOWN_LOCATIONS = {
    "Subway":               20100,
    "McDonald's":           13500,
    "Starbucks":            16400,
    "Dunkin'":               9500,
    "Burger King":           7000,
    "Wendy's":               6000,
    "Pizza Hut":             6600,
    "Taco Bell":             7900,
    "Domino's Pizza":        6700,
    "Chick-fil-A":           3000,
    "KFC":                   4000,
    "Popeyes":               2800,
    "Sonic Drive-In":        3500,
    "Arby's":                3300,
    "Jersey Mike's Subs":    2700,
    "Jimmy John's":          2700,
    "Little Caesars":        4400,
    "Papa John's Pizza":     3300,
    "Panera Bread":          2200,
    "Chipotle Mexican Grill":3400,
    "Whataburger":            900,
    "Five Guys":             1400,
    "In-N-Out Burger":        400,
    "Shake Shack":            350,
    "Culver's":               960,
    "Hardee's":              1800,
    "Carl's Jr.":            1100,
    "Raising Cane's":         750,
    "Wingstop":              1900,
    "Bojangles'":             800,
    "Zaxby's":                940,
    "Church's Chicken":      1100,
    "Marco's Pizza":         1000,
    "MOD Pizza":              500,
    "Blaze Pizza":            300,
    "Papa Murphy's":         1100,
    "Firehouse Subs":        1300,
    "Quiznos":                150,
    "Potbelly Sandwich Shop": 425,
    "Qdoba":                  730,
    "Del Taco":               600,
    "El Pollo Loco":          500,
    "Einstein Bros. Bagels":  650,
    "Tim Hortons":            650,    # US locations only
    "Krispy Kreme":           400,
    "Caribou Coffee":         500,
    "Panda Express":         2400,
    "Pei Wei Asian Diner":    100,
    "Sweetgreen":             225,
    "CAVA":                   350,
    "Noodles & Company":      450,
    "Pret a Manger":          100,
    # Dessert / treats
    "Cinnabon":             1500,
    "Cold Stone Creamery":  1000,
    "Baskin-Robbins":       2500,
    "Dairy Queen":          4300,
    "Auntie Anne's":        1500,
    "Dippin' Dots":          340,
    "Carvel":                300,
    "Wetzel's Pretzels":     370,
    "Jamba":                 720,
}

# Hand-known HQs for chains whose Wikidata P159 points at a parent company
# rather than the brand's own HQ. Applied during fix_chains.py.
KNOWN_HQ = {
    "Pizza Hut":      ("Plano", "TX", "United States"),
    "Popeyes":        ("Miami", "FL", "United States"),
    # Wikidata returned a building name ("Lancaster U.S. Post Office building")
    # — strip back to the city.
    "Auntie Anne's":  ("Lancaster", "PA", "United States"),
    # Wikidata blank for Carvel — owned by Atlantic Food Brands / GFG, HQ in Atlanta.
    "Carvel":         ("Atlanta", "GA", "United States"),
}

# Hand-known founding dates / origin cities for chains Wikidata didn't return.
KNOWN_FOUNDED = {
    "Carvel": 1934,
}
KNOWN_ORIGIN = {
    "Carvel":               "Hartsdale",
    "Dairy Queen":          "Joliet",       # IL — first store
    "Auntie Anne's":        "Downingtown",  # PA — first stand
    "Dippin' Dots":         "Lexington",    # KY founding lab
}

def fetch_locations_for(c):
    """Prefer the curated US-only estimate; Wikipedia infoboxes mix worldwide
    and US numbers so they're a worse ranking proxy for a US-focused deck."""
    v = KNOWN_LOCATIONS.get(c["name"])
    if v: return v
    slug = c.get("wiki_slug")
    if slug:
        try:
            wt = get_lead_wikitext(slug)
            raw = extract_field(wt, "num_locations", "locations")
            v = parse_locations(raw)
            if v: return v
        except Exception:
            pass
    return None

# ── Main ────────────────────────────────────────────────────────────
def main():
    with open("chains/manifest.json", encoding="utf-8") as f:
        chains = json.load(f)

    # (1) Founder fixups (always overwrite with curated when present)
    for c in chains:
        if c["name"] in KNOWN_FOUNDERS:
            old = c.get("founders") or []
            new = KNOWN_FOUNDERS[c["name"]]
            if old != new:
                print(f"  founders: {c['name']}  {old} → {new}")
                c["founders"] = new
        # Strip clearly-wrong rows from any leftover noisy parses
        if c.get("founders"):
            bad_markers = ("Company", "Shop", "Restaurant", "Inc.")
            c["founders"] = [f for f in c["founders"] if not any(b in f for b in bad_markers)] or c["founders"]

    # (1b) HQ overrides — fill in chains whose Wikidata P159 was missing,
    # returned a building name, or pointed at the parent's HQ instead of the
    # brand's. Also fill in founded year / origin city when Wikidata blank.
    for c in chains:
        if c["name"] in KNOWN_HQ:
            hq, _state, country = KNOWN_HQ[c["name"]]
            if c.get("hq") != hq:
                print(f"  HQ:  {c['name']}  {c.get('hq') or '(none)'} → {hq}")
                c["hq"] = hq
                c["country"] = country
        if c["name"] in KNOWN_FOUNDED and not c.get("founded"):
            c["founded"] = KNOWN_FOUNDED[c["name"]]
            print(f"  FOUND: {c['name']}  → {c['founded']}")
        if c["name"] in KNOWN_ORIGIN and not c.get("origin"):
            c["origin"] = KNOWN_ORIGIN[c["name"]]
            print(f"  ORIG: {c['name']}  → {c['origin']}")

    # (2) Locations + rank (overwrite any previous values; using curated US estimates)
    print("\n--- Locations ---")
    for c in chains:
        v = fetch_locations_for(c)
        if v:
            c["locations"] = v
            print(f"  {c['name']:30}  {v:>7,}")
        else:
            print(f"  {c['name']:30}  ! no data")
        time.sleep(0.8)

    # (3) Sort & assign rank by location count descending
    chains_sorted = sorted(chains, key=lambda c: -(c.get("locations") or 0))
    for i, c in enumerate(chains_sorted, 1):
        c["rank"] = i

    # Persist
    with open("chains/manifest.json", "w", encoding="utf-8") as f:
        json.dump(chains_sorted, f, ensure_ascii=False, indent=2)
    with open("chains.js", "w", encoding="utf-8") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(chains_sorted, ensure_ascii=False) + ";\n")

    print(f"\nDone. Ranked {len(chains_sorted)} chains.")
    print("\nTop 10:")
    for c in chains_sorted[:10]:
        print(f"  #{c['rank']:2}  {c['name']:30}  {c.get('locations') or '?':>7,} US locations")

if __name__ == "__main__":
    main()
