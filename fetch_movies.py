#!/usr/bin/env python3
"""
Fetch a short blurb (overview, release date, runtime, rating) for every movie
in the deck — winners and nominees — and write movies.js for the app.

Output: movies.js with window.MOVIES keyed by title.
"""
import urllib.request, urllib.parse, json, re, os, time
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
UA = "BPFlashcards/1.0"

def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

def find_movie(title, year):
    for ry in (year - 1, year, year - 2):
        try:
            d = http_json(f"{TMDB}/search/movie?api_key={API_KEY}"
                          f"&query={urllib.parse.quote(title)}&primary_release_year={ry}")
        except Exception:
            continue
        for r in d.get("results") or []:
            if r.get("title", "").lower() == title.lower():
                return r["id"]
        if d.get("results"):
            return d["results"][0]["id"]
    try:
        d = http_json(f"{TMDB}/search/movie?api_key={API_KEY}&query={urllib.parse.quote(title)}")
        return (d.get("results") or [{}])[0].get("id")
    except Exception:
        return None

def details(mid):
    try:
        return http_json(f"{TMDB}/movie/{mid}?api_key={API_KEY}")
    except Exception:
        return None

def collect_movies():
    """Return list of (title, ceremony_year, tmdb_id_or_None) for every film in the deck."""
    items = []
    seen = set()

    # 1. Inline DECK from index.html (1997-2025 hand-curated)
    with open("index.html", encoding="utf-8") as f:
        s = f.read()
    deck_block = re.search(r'const DECK_INLINE = \[(.*?)\n  \];', s, re.DOTALL)
    if deck_block:
        src = deck_block.group(1)
        # Walk year by year
        years = list(re.finditer(r'\{ year: (\d{4}),\s*movie: "([^"]+)"', src))
        for i, m in enumerate(years):
            year = int(m.group(1))
            winner_title = m.group(2)
            block_start = m.end()
            block_end = years[i+1].start() if i+1 < len(years) else len(src)
            block = src[block_start:block_end]
            if winner_title not in seen:
                seen.add(winner_title)
                items.append((winner_title, year, None))
            for nom in re.finditer(r'\{ movie: "([^"]+)"', block):
                t = nom.group(1)
                if t not in seen:
                    seen.add(t)
                    items.append((t, year, None))

    # 2. deck_extension.json (1947-1996 auto-fetched, has tmdb_id for winners)
    if os.path.exists("deck_extension.json"):
        with open("deck_extension.json", encoding="utf-8") as f:
            ext = json.load(f)
        for e in ext:
            year = e["year"]
            t = e["movie"]
            if t not in seen:
                seen.add(t)
                items.append((t, year, e.get("tmdb_id")))
            for n in e.get("nominees") or []:
                t = n["movie"]
                if t not in seen:
                    seen.add(t)
                    items.append((t, year, None))

    return items

def main():
    items = collect_movies()
    print(f"Movies to look up: {len(items)}")

    out = {}
    for i, (title, year, mid) in enumerate(items, 1):
        if not mid:
            mid = find_movie(title, year)
        if not mid:
            print(f"[{i}/{len(items)}] {title} ({year})  ! no TMDB match")
            continue
        d = details(mid)
        if not d:
            print(f"[{i}/{len(items)}] {title} ({year})  ! no details")
            continue
        out[title] = {
            "id": mid,
            "imdb_id": d.get("imdb_id"),
            "overview": (d.get("overview") or "").strip(),
            "release_date": d.get("release_date"),
            "runtime": d.get("runtime"),
            "rating": round(d.get("vote_average") or 0, 1),
            "tagline": (d.get("tagline") or "").strip() or None,
            "original_title": d.get("original_title") if d.get("original_title") != d.get("title") else None,
        }
        print(f"[{i}/{len(items)}] {title} ({year})  · {out[title]['runtime'] or '?'} min · ⭐ {out[title]['rating']}")
        time.sleep(0.07)

    js = "window.MOVIES = " + json.dumps(out, ensure_ascii=False) + ";\n"
    with open("movies.js", "w", encoding="utf-8") as f:
        f.write(js)
    print(f"\nDone. {len(out)} entries → movies.js")

if __name__ == "__main__":
    main()
