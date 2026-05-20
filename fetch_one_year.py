#!/usr/bin/env python3
"""
Scaffold a single ceremony year for DECK_INLINE.
Usage: python3 fetch_one_year.py 2026

Prints a JS snippet to paste into the top of DECK_INLINE.
Fetches winner + nominees from Wikidata; cast/director/trailer from TMDB.
"""
import sys, os, json, urllib.request, urllib.parse, time, re, gzip, io

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
TMDB_KEY = _ENV.get("TMDB_API_KEY") or os.environ.get("TMDB_API_KEY")
TMDB = "https://api.themoviedb.org/3"
WIKIDATA = "https://query.wikidata.org/sparql"

def http_json(url, headers=None, timeout=60):
    h = {"User-Agent": "BP/1.0", "Accept": "application/json", "Accept-Encoding": "identity"}
    if headers: h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2026

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
  FILTER(YEAR(?ceremony) = %d)
}
""" % YEAR

def tmdb_by_imdb(imdb_id):
    d = http_json(f"{TMDB}/find/{imdb_id}?api_key={TMDB_KEY}&external_source=imdb_id")
    return (d.get("movie_results") or [{}])[0] or None

def credits(mid):
    return http_json(f"{TMDB}/movie/{mid}/credits?api_key={TMDB_KEY}")

def trailer(mid):
    try:
        d = http_json(f"{TMDB}/movie/{mid}/videos?api_key={TMDB_KEY}&include_video_language=en,null")
    except Exception:
        return None
    vids = [v for v in d.get("results", []) if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
    if not vids:
        vids = [v for v in d.get("results", []) if v.get("site") == "YouTube" and v.get("type") in ("Teaser", "Trailer")]
    if not vids:
        return None
    vids.sort(key=lambda v: (1 if v.get("official") else 0, v.get("size", 0)), reverse=True)
    return vids[0]["key"]

def director_of(c):
    for x in c.get("crew") or []:
        if x.get("job") == "Director":
            return x.get("name")
    return None

def top_cast(c, n=3):
    cast = sorted(c.get("cast") or [], key=lambda x: x.get("order", 999))
    return [x["name"] for x in cast[:n]]

def jstr(s):
    return '"' + str(s).replace('\\', '\\\\').replace('"', '\\"') + '"'

def main():
    print(f"Fetching {YEAR} from Wikidata…", file=sys.stderr)
    url = WIKIDATA + "?" + urllib.parse.urlencode({"query": SPARQL, "format": "json"})
    rows = http_json(url)["results"]["bindings"]
    if not rows:
        print(f"No results for {YEAR} — ceremony data may not be on Wikidata yet.", file=sys.stderr); sys.exit(1)

    winner = None
    nominees = []
    seen = set()
    for b in rows:
        imdb = (b.get("imdb") or {}).get("value")
        if not imdb: continue
        title = (b.get("filmLabel") or {}).get("value") or imdb
        uri = (b.get("film") or {}).get("value")
        if uri in seen: continue
        seen.add(uri)
        status = (b.get("status") or {}).get("value")
        if status == "won":
            winner = {"title": title, "imdb": imdb}
        else:
            nominees.append({"title": title, "imdb": imdb})

    if not winner:
        print(f"No winner found for {YEAR}", file=sys.stderr); sys.exit(1)

    print(f"Winner: {winner['title']}", file=sys.stderr)
    print(f"Nominees ({len(nominees)}):", file=sys.stderr)
    for n in nominees:
        print(f"  · {n['title']}", file=sys.stderr)

    # Enrich each via TMDB
    def enrich(f):
        m = tmdb_by_imdb(f["imdb"])
        if not m:
            print(f"  ! TMDB miss for {f['title']}", file=sys.stderr)
            return None
        c = credits(m["id"])
        return {
            "title": m.get("title") or f["title"],
            "director": director_of(c),
            "stars": top_cast(c, 3),
            "trailer": trailer(m["id"]),
        }

    print("\nEnriching via TMDB…", file=sys.stderr)
    w = enrich(winner); time.sleep(0.1)
    if not w: sys.exit(1)
    noms_enriched = []
    for n in nominees:
        e = enrich(n); time.sleep(0.1)
        if e: noms_enriched.append(e)

    # Emit JS snippet to paste into DECK_INLINE
    out = []
    out.append(f'    {{ year: {YEAR}, movie: {jstr(w["title"])}, director: {jstr(w["director"])}, trailer: {jstr(w["trailer"] or "")},')
    out.append(f'      stars: [' + ",".join(jstr(s) for s in w["stars"]) + '],')
    out.append(f'      nominees: [')
    for n in noms_enriched:
        stars_js = ",".join(jstr(s) for s in n["stars"])
        trailer_clause = f', trailer: {jstr(n["trailer"])}' if n["trailer"] else ""
        director_clause = f', director: {jstr(n["director"])}' if n["director"] else ""
        out.append(f'        {{ movie: {jstr(n["title"])}, stars: [{stars_js}]{trailer_clause}{director_clause} }},')
    out.append(f'      ]}},')
    print("\n".join(out))

if __name__ == "__main__":
    main()
