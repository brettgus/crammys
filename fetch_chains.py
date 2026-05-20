#!/usr/bin/env python3
"""
Fetch metadata + logos for the top ~50 US fast-food / fast-casual chains.
Sources: Wikipedia REST API (summary, page image) and Wikidata (founder,
founding year, HQ, parent company, country of origin).

Output:
  chains.js          → window.CHAINS_DECK = [...]
  chains/manifest.json
  chains/logos/<slug>.<ext>   (local cache of each chain's logo)
"""
import os, json, re, time, urllib.request, urllib.parse, urllib.error, gzip

# ── HTTP helpers ──────────────────────────────────────────────────────
def _http(url, *, max_retries=4, backoff=2.0):
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Crammys/1.0 (personal flashcard app; contact via github.com/brettgus/crammys)",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data, r.headers
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = backoff ** (attempt + 1)
                print(f"    429 — sleeping {wait:.1f}s and retrying…")
                time.sleep(wait)
                continue
            raise

def http_json(url):
    data, _ = _http(url)
    return json.loads(data)

def http_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Crammys/1.0"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read()

# ── Chain list ────────────────────────────────────────────────────────
# (display, wiki article slug, category). Categories: burgers, chicken,
# pizza, sandwich, mexican, coffee, bakery-cafe, asian, fast-casual.
CHAINS = [
    # Burgers
    ("McDonald's",          "McDonald's",                "burgers"),
    ("Burger King",         "Burger_King",               "burgers"),
    ("Wendy's",             "Wendy's",                   "burgers"),
    ("Five Guys",           "Five_Guys",                 "burgers"),
    ("In-N-Out Burger",     "In-N-Out_Burger",           "burgers"),
    ("Shake Shack",         "Shake_Shack",               "burgers"),
    ("Whataburger",         "Whataburger",               "burgers"),
    ("Culver's",            "Culver's",                  "burgers"),
    ("Hardee's",            "Hardee's",                  "burgers"),
    ("Carl's Jr.",          "Carl's_Jr.",                "burgers"),
    # Chicken
    ("Chick-fil-A",         "Chick-fil-A",               "chicken"),
    ("KFC",                 "KFC",                       "chicken"),
    ("Popeyes",             "Popeyes",                   "chicken"),
    ("Raising Cane's",      "Raising_Cane's_Chicken_Fingers", "chicken"),
    ("Wingstop",            "Wingstop",                  "chicken"),
    ("Bojangles'",          "Bojangles'",                "chicken"),
    ("Zaxby's",             "Zaxby's",                   "chicken"),
    ("Church's Chicken",    "Church's_Chicken",          "chicken"),
    # Pizza
    ("Domino's Pizza",      "Domino's_Pizza",            "pizza"),
    ("Pizza Hut",           "Pizza_Hut",                 "pizza"),
    ("Papa John's Pizza",   "Papa_John's_Pizza",         "pizza"),
    ("Little Caesars",      "Little_Caesars",            "pizza"),
    ("Marco's Pizza",       "Marco's_Pizza",             "pizza"),
    ("MOD Pizza",           "MOD_Pizza",                 "pizza"),
    ("Blaze Pizza",         "Blaze_Pizza",               "pizza"),
    ("Papa Murphy's",       "Papa_Murphy's",             "pizza"),
    # Sandwich / sub
    ("Subway",              "Subway_(restaurant)",       "sandwich"),
    ("Jersey Mike's Subs",  "Jersey_Mike's_Subs",        "sandwich"),
    ("Jimmy John's",        "Jimmy_John's",              "sandwich"),
    ("Firehouse Subs",      "Firehouse_Subs",            "sandwich"),
    ("Arby's",              "Arby's",                    "sandwich"),
    ("Quiznos",             "Quiznos",                   "sandwich"),
    ("Potbelly Sandwich Shop","Potbelly_Sandwich_Shop",  "sandwich"),
    # Mexican
    ("Taco Bell",           "Taco_Bell",                 "mexican"),
    ("Chipotle Mexican Grill", "Chipotle_Mexican_Grill", "mexican"),
    ("Qdoba",               "Qdoba",                     "mexican"),
    ("Del Taco",            "Del_Taco",                  "mexican"),
    ("El Pollo Loco",       "El_Pollo_Loco",             "mexican"),
    # Bakery-cafe
    ("Panera Bread",        "Panera_Bread",              "bakery-cafe"),
    ("Einstein Bros. Bagels","Einstein_Bros._Bagels",    "bakery-cafe"),
    ("Pret a Manger",       "Pret_a_Manger",             "bakery-cafe"),
    # Coffee
    ("Starbucks",           "Starbucks",                 "coffee"),
    ("Dunkin'",             "Dunkin'",                   "coffee"),
    ("Tim Hortons",         "Tim_Hortons",               "coffee"),
    ("Krispy Kreme",        "Krispy_Kreme",              "coffee"),
    ("Caribou Coffee",      "Caribou_Coffee",            "coffee"),
    # Asian / fast-casual
    ("Panda Express",       "Panda_Express",             "asian"),
    ("Pei Wei Asian Diner", "Pei_Wei_Asian_Diner",       "asian"),
    ("Sweetgreen",          "Sweetgreen",                "fast-casual"),
    ("CAVA",                "Cava_(restaurant)",         "fast-casual"),
    ("Noodles & Company",   "Noodles_%26_Company",       "fast-casual"),
]

# ── Wikidata helpers ──────────────────────────────────────────────────
LABEL_CACHE = {}
def wd_label(qid):
    if not qid or not qid.startswith("Q"): return None
    if qid in LABEL_CACHE: return LABEL_CACHE[qid]
    try:
        d = http_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
        labels = d["entities"][qid].get("labels", {})
        l = (labels.get("en") or {}).get("value")
        LABEL_CACHE[qid] = l
        return l
    except Exception:
        return None

def first_value(claim_list, kind="entity"):
    """kind='entity' → Q-id; 'time' → ISO date string; 'string' → raw string"""
    if not claim_list: return None
    snak = claim_list[0].get("mainsnak", {})
    if snak.get("snaktype") != "value": return None
    val = snak.get("datavalue", {}).get("value")
    if isinstance(val, dict):
        if "id" in val: return val["id"]
        if "time" in val: return val["time"]
        if "amount" in val: return val["amount"]
    return val

def all_entity_values(claim_list):
    out = []
    for c in claim_list or []:
        snak = c.get("mainsnak", {})
        if snak.get("snaktype") != "value": continue
        v = snak.get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out

def year_of(time_str):
    if not time_str: return None
    m = re.match(r'[+\-]?(\d{4})', time_str)
    return int(m.group(1)) if m else None

# ── Per-chain fetcher ─────────────────────────────────────────────────
def fetch_chain(display, wiki, category):
    print(f"--- {display}")
    # 1. Wikipedia summary
    try:
        summary = http_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki}")
    except Exception as e:
        print(f"  ! summary failed: {e}"); return None
    qid = summary.get("wikibase_item")
    extract = summary.get("extract") or ""
    description = summary.get("description")
    thumb = (summary.get("thumbnail") or {}).get("source")
    original = (summary.get("originalimage") or {}).get("source")

    rec = {
        "name": display,
        "category": category,
        "wiki_id": qid,
        "wiki_slug": wiki,
        "description": description,
        "summary": extract[:320] if extract else None,
        "logo_url": original or thumb,
    }

    # 2. Wikidata entity
    if qid:
        try:
            ent = http_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")["entities"][qid]
            claims = ent.get("claims", {})
            # Founders (multi)
            founders_q = all_entity_values(claims.get("P112"))
            rec["founders"] = [wd_label(q) for q in founders_q if wd_label(q)]
            # Founded year
            rec["founded"] = year_of(first_value(claims.get("P571")))
            # HQ location (current)
            hq_q = first_value(claims.get("P159"))
            rec["hq"] = wd_label(hq_q)
            # Location of formation (original founding place)
            origin_q = first_value(claims.get("P740"))
            rec["origin"] = wd_label(origin_q)
            # Parent organization
            parent_q = first_value(claims.get("P749"))
            rec["parent"] = wd_label(parent_q)
            # Country
            country_q = first_value(claims.get("P17"))
            rec["country"] = wd_label(country_q)
        except Exception as e:
            print(f"  ! wikidata failed: {e}")

    print(f"  · founded={rec.get('founded')}  HQ={rec.get('hq')}  origin={rec.get('origin')}  parent={rec.get('parent')}")
    return rec

# ── Logo download ─────────────────────────────────────────────────────
def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def download_logo(url, path):
    if not url: return False
    if os.path.exists(path) and os.path.getsize(path) > 256: return True
    try:
        with open(path, "wb") as f:
            f.write(http_bytes(url))
        return True
    except Exception as e:
        print(f"    ! logo download failed: {e}")
        return False

# ── Main ──────────────────────────────────────────────────────────────
def main():
    os.makedirs("chains/logos", exist_ok=True)
    # Resume: load previously-fetched chains from manifest.json so a re-run only fetches missing ones.
    existing = {}
    if os.path.exists("chains/manifest.json"):
        with open("chains/manifest.json", encoding="utf-8") as f:
            for rec in json.load(f):
                existing[rec["name"]] = rec
    out = []
    for display, wiki, category in CHAINS:
        if display in existing:
            rec = existing[display]
            # Retry logo download if we have a URL but no local file
            if not rec.get("logo") and rec.get("logo_url"):
                ext = os.path.splitext(urllib.parse.urlparse(rec["logo_url"]).path)[1] or ".png"
                local = f"chains/logos/{slug(display)}{ext}"
                if download_logo(rec["logo_url"], local):
                    rec["logo"] = local
                    print(f"=== {display}  (logo retried ✓)")
                else:
                    print(f"=== {display}  (cached, logo still missing)")
            else:
                print(f"=== {display}  (cached)")
            out.append(rec)
            continue
        rec = fetch_chain(display, wiki, category)
        if not rec: continue
        url = rec.get("logo_url")
        if url:
            ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".png"
            local = f"chains/logos/{slug(display)}{ext}"
            if download_logo(url, local):
                rec["logo"] = local
        out.append(rec)
        # Incremental save so the next resume doesn't lose ground.
        with open("chains/manifest.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        time.sleep(1.2)  # Wikipedia REST + Wikidata together; be gentle

    with open("chains.js", "w", encoding="utf-8") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(out, ensure_ascii=False) + ";\n")
    with open("chains/manifest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nDone. {len(out)} chains → chains.js")

if __name__ == "__main__":
    main()
