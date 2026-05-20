#!/usr/bin/env python3
"""
Build the Best Picture deck for ceremony years 1947-1996 from Wikidata + TMDB.

Wikidata gives us the canonical list of nominees + winners (via the
"Academy Award for Best Picture" entity, Q102427) and IMDb IDs.
TMDB enriches each film with director, top-3 cast, and a YouTube trailer ID.

Output: deck_extension.js → window.DECK_EXTENSION = [{ year, movie, director,
                                                        stars, trailer, nominees: [...] }]
"""
import urllib.request, urllib.parse, json, re, os, sys, time
import gzip

def _load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env
_ENV = _load_env()
API_KEY = _ENV.get("TMDB_API_KEY") or os.environ.get("TMDB_API_KEY")
if not API_KEY:
    print("TMDB_API_KEY not found in .env or environment"); raise SystemExit(1)
TMDB = "https://api.themoviedb.org/3"
WIKIDATA = "https://query.wikidata.org/sparql"

# Years we want (ceremony years). Existing app already covers 1997-2025.
YEAR_MIN = 1947
YEAR_MAX = 1996

# Q102427 = Academy Award for Best Picture
# Q11424 = film. Restrict to film entities so producers (who actually receive the Oscar) don't sneak in.
SPARQL = """
SELECT ?film ?filmLabel ?imdb ?ceremony ?status WHERE {
  {
    ?film p:P166 ?st .
    ?st ps:P166 wd:Q102427 .
    OPTIONAL { ?st pq:P585 ?ceremony . }
    BIND("won" AS ?status)
  } UNION {
    ?film p:P1411 ?st .
    ?st ps:P1411 wd:Q102427 .
    OPTIONAL { ?st pq:P585 ?ceremony . }
    BIND("nom" AS ?status)
  }
  ?film wdt:P31/wdt:P279* wd:Q11424 .
  ?film wdt:P345 ?imdb .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
"""

UA = "BPFlashcards/1.0 (personal flashcard app)"

def http_json(url, headers=None, timeout=60):
    h = {"User-Agent": UA, "Accept": "application/json"}
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

def fetch_wikidata():
    url = WIKIDATA + "?" + urllib.parse.urlencode({"query": SPARQL, "format": "json"})
    return http_json(url)["results"]["bindings"]

def parse_year(iso):
    m = re.match(r'(\d{4})', iso or '')
    return int(m.group(1)) if m else None

def tmdb_by_imdb(imdb_id):
    data = http_json(f"{TMDB}/find/{imdb_id}?api_key={API_KEY}&external_source=imdb_id")
    movies = data.get("movie_results") or []
    return movies[0] if movies else None

def tmdb_credits(mid):
    return http_json(f"{TMDB}/movie/{mid}/credits?api_key={API_KEY}")

def tmdb_videos(mid):
    try:
        data = http_json(f"{TMDB}/movie/{mid}/videos?api_key={API_KEY}&include_video_language=en,null")
    except Exception:
        return None
    trailers = [v for v in data.get("results", []) if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
    if not trailers:
        # fall back to teasers
        trailers = [v for v in data.get("results", []) if v.get("site") == "YouTube" and v.get("type") in ("Teaser","Trailer")]
    if not trailers:
        return None
    trailers.sort(key=lambda v: (1 if v.get("official") else 0, v.get("size", 0)), reverse=True)
    return trailers[0]["key"]

def director_of(credits):
    for c in credits.get("crew", []):
        if c.get("job") == "Director":
            return c.get("name")
    return None

def top_cast(credits, n=3):
    cast = sorted(credits.get("cast", []), key=lambda x: x.get("order", 999))
    return [c["name"] for c in cast[:n]]

def build_film_payload(imdb_id, fallback_title):
    mv = tmdb_by_imdb(imdb_id)
    if not mv:
        return {"movie": fallback_title, "director": None, "stars": [], "trailer": None, "tmdb_id": None}
    mid = mv["id"]
    title = mv.get("title") or fallback_title
    try:
        credits = tmdb_credits(mid)
    except Exception as e:
        print(f"      ! credits failed: {e}")
        credits = {}
    director = director_of(credits)
    stars = top_cast(credits, 3)
    trailer = tmdb_videos(mid)
    return {"movie": title, "director": director, "stars": stars, "trailer": trailer, "tmdb_id": mid}

def main():
    print(f"Fetching Wikidata (BP nominees/winners with IMDb ID)…")
    rows = fetch_wikidata()
    print(f"  → {len(rows)} rows")

    by_year = {}
    for b in rows:
        ceremony = (b.get("ceremony") or {}).get("value")
        year = parse_year(ceremony)
        if not year or year < YEAR_MIN or year > YEAR_MAX:
            continue
        imdb = (b.get("imdb") or {}).get("value")
        if not imdb:
            continue
        title = (b.get("filmLabel") or {}).get("value") or ""
        film_uri = (b.get("film") or {}).get("value")
        status = (b.get("status") or {}).get("value")
        d = by_year.setdefault(year, {"winner": None, "nominees": []})
        entry = {"title": title, "imdb": imdb, "uri": film_uri}
        if status == "won":
            d["winner"] = entry
        else:
            d["nominees"].append(entry)

    # Drop duplicates and the winner from nominee list
    for year, info in by_year.items():
        seen = set()
        deduped = []
        for n in info["nominees"]:
            if info["winner"] and n["uri"] == info["winner"]["uri"]:
                continue
            if n["uri"] in seen:
                continue
            seen.add(n["uri"])
            deduped.append(n)
        info["nominees"] = deduped

    deck = []
    years = sorted(by_year.keys())
    print(f"\nResolving {len(years)} years against TMDB…\n")
    for year in years:
        info = by_year[year]
        if not info["winner"]:
            print(f"--- {year}: NO WINNER FROM WIKIDATA — skipping"); continue
        win_title = info["winner"]["title"]
        print(f"--- {year}: {win_title}")
        win = build_film_payload(info["winner"]["imdb"], win_title)
        nominees = []
        for n in info["nominees"]:
            print(f"    · {n['title']}")
            nm = build_film_payload(n["imdb"], n["title"])
            # don't keep tmdb_id on nominees in final output — not needed by app
            nominees.append({"movie": nm["movie"], "stars": nm["stars"], "trailer": nm["trailer"]})
            time.sleep(0.07)
        deck.append({
            "year": year,
            "movie": win["movie"],
            "director": win["director"],
            "stars": win["stars"],
            "trailer": win["trailer"],
            "tmdb_id": win["tmdb_id"],
            "nominees": nominees,
        })
        time.sleep(0.07)

    deck.sort(key=lambda x: -x["year"])

    # Strip tmdb_id from final output (kept above only for fetch_images.py to pick up)
    out = []
    for e in deck:
        e2 = {k: v for k, v in e.items() if k != "tmdb_id"}
        out.append(e2)

    js = "window.DECK_EXTENSION = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n"
    with open("deck_extension.js", "w", encoding="utf-8") as f:
        f.write(js)
    # Also write a JSON the helper scripts can read
    with open("deck_extension.json", "w", encoding="utf-8") as f:
        json.dump(deck, f, ensure_ascii=False, indent=2)
    print(f"\nDone. {len(out)} years → deck_extension.js / deck_extension.json")

if __name__ == "__main__":
    main()
