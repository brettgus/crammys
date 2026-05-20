#!/usr/bin/env python3
"""
Backfill: add a `director: "Name"` field to every nominee in both
  · the hand-curated DECK_INLINE block of index.html (1997-2025)
  · deck_extension.json (1947-1996)

Uses TMDB to look up each nominee's director by title + ceremony year.
Idempotent: skips nominees that already have a director field.
"""
import os, json, re, time, urllib.request, urllib.parse, sys, gzip

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

def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "BP/1.0", "Accept": "application/json", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

def find_movie_id(title, ceremony_year):
    for ry in (ceremony_year - 1, ceremony_year, ceremony_year - 2):
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

def director_for(mid):
    try:
        d = http_json(f"{TMDB}/movie/{mid}/credits?api_key={API_KEY}")
    except Exception:
        return None
    for c in d.get("crew") or []:
        if c.get("job") == "Director":
            return c.get("name")
    return None

# ── 1. Inline DECK_INLINE in index.html ──────────────────────────────────
def patch_inline():
    with open("index.html", encoding="utf-8") as f:
        s = f.read()
    deck = re.search(r'const DECK_INLINE = \[(.*?)\n  \];', s, re.DOTALL)
    if not deck:
        print("DECK_INLINE not found"); return
    src = deck.group(1)
    block_offset = deck.start(1)

    # Walk year-by-year
    years = list(re.finditer(r'\{ year: (\d{4}),', src))
    bounds = [(m.start(), int(m.group(1))) for m in years] + [(len(src), None)]
    edits = []  # (abs_start, abs_end, replacement)

    for i in range(len(bounds) - 1):
        block_start, year = bounds[i]
        block_end = bounds[i + 1][0]
        block = src[block_start:block_end]
        if year is None: continue
        for nom in re.finditer(
            r'\{ movie: "([^"]+)", stars: \[([^\]]*)\](\s*,\s*trailer:\s*"[^"]+")?(\s*,\s*director:\s*"[^"]+")?\s*\}',
            block
        ):
            if nom.group(4):  # already has director
                continue
            title = nom.group(1)
            print(f"[{year}] {title}")
            mid = find_movie_id(title, year)
            if not mid:
                print("    ! TMDB miss"); continue
            d = director_for(mid)
            if not d:
                print("    ! no director listed"); continue
            stars_raw = nom.group(2)
            trailer = nom.group(3) or ""
            new_text = f'{{ movie: "{title}", stars: [{stars_raw}]{trailer}, director: "{d}" }}'
            abs_start = block_offset + block_start + nom.start()
            abs_end = block_offset + block_start + nom.end()
            edits.append((abs_start, abs_end, new_text))
            print(f"    + {d}")
            time.sleep(0.07)

    edits.sort(reverse=True)
    for st, en, rep in edits:
        s = s[:st] + rep + s[en:]
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(s)
    print(f"\nInline: applied {len(edits)} director additions.\n")

# ── 2. deck_extension.json (auto-fetched 1947-1996) ──────────────────────
def patch_extension():
    p = "deck_extension.json"
    if not os.path.exists(p):
        print("deck_extension.json not found"); return
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    n_added = 0
    for entry in data:
        year = entry["year"]
        for nom in entry.get("nominees") or []:
            if nom.get("director"):
                continue
            title = nom["movie"]
            print(f"[{year}] {title}")
            mid = find_movie_id(title, year)
            if not mid:
                print("    ! TMDB miss"); continue
            d = director_for(mid)
            if not d:
                print("    ! no director listed"); continue
            nom["director"] = d
            n_added += 1
            print(f"    + {d}")
            time.sleep(0.07)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Re-emit the JS shim too
    out = []
    for e in data:
        out.append({k: v for k, v in e.items() if k != "tmdb_id"})
    with open("deck_extension.js", "w", encoding="utf-8") as f:
        f.write("window.DECK_EXTENSION = " + json.dumps(out, ensure_ascii=False, indent=1) + ";\n")
    print(f"\nExtension: applied {n_added} director additions.")

if __name__ == "__main__":
    patch_inline()
    patch_extension()
