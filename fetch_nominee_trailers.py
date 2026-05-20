#!/usr/bin/env python3
"""
Backfill: for each nominee in the hand-curated DECK_INLINE block of index.html,
look up the movie on TMDB and inject a `trailer: "<videoId>"` field after `stars: [...]`.
Idempotent: skips entries that already have a trailer field.
"""
import urllib.request, urllib.parse, json, re, time, os, sys
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
    # year here is the ceremony year; release year is usually ceremony - 1
    for ry in (year - 1, year, year - 2):
        url = f"{TMDB}/search/movie?api_key={API_KEY}&query={urllib.parse.quote(title)}&primary_release_year={ry}"
        try:
            data = http_json(url)
        except Exception:
            continue
        results = data.get("results") or []
        if results:
            for r in results:
                if r.get("title", "").lower() == title.lower():
                    return r
            return results[0]
    # last-ditch
    try:
        data = http_json(f"{TMDB}/search/movie?api_key={API_KEY}&query={urllib.parse.quote(title)}")
    except Exception:
        return None
    res = data.get("results") or []
    return res[0] if res else None

def trailer_for(mid):
    try:
        data = http_json(f"{TMDB}/movie/{mid}/videos?api_key={API_KEY}&include_video_language=en,null")
    except Exception:
        return None
    vids = [v for v in data.get("results", []) if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
    if not vids:
        vids = [v for v in data.get("results", []) if v.get("site") == "YouTube" and v.get("type") in ("Teaser", "Trailer")]
    if not vids:
        return None
    vids.sort(key=lambda v: (1 if v.get("official") else 0, v.get("size", 0)), reverse=True)
    return vids[0]["key"]

def main():
    with open("index.html", encoding="utf-8") as f:
        s = f.read()
    deck_block = re.search(r'const DECK_INLINE = \[(.*?)\n  \];', s, re.DOTALL)
    if not deck_block:
        print("DECK_INLINE not found"); sys.exit(1)
    src = deck_block.group(1)

    # Walk year by year. Each block starts with `{ year: NNNN, movie: ...`
    year_blocks = list(re.finditer(r'\{ year: (\d{4}),', src))
    # Find each (year_start, year_end) in src
    boundaries = [(m.start(), int(m.group(1))) for m in year_blocks]
    boundaries.append((len(src), None))

    edits = []  # (absolute_start_in_s, absolute_end, replacement)
    block_offset = deck_block.start(1)

    for i in range(len(boundaries) - 1):
        block_start, year = boundaries[i]
        block_end = boundaries[i + 1][0]
        block_src = src[block_start:block_end]
        if year is None: continue
        # Find each nominee object inside this block
        # Pattern: { movie: "X", stars: [...] }  OR  { movie: "X", stars: [...], trailer: "..." }
        for nom in re.finditer(
            r'\{ movie: "([^"]+)", stars: \[([^\]]*)\](\s*,\s*trailer:\s*"[^"]+")?\s*\}',
            block_src
        ):
            if nom.group(3):
                continue  # already has trailer
            title = nom.group(1)
            # Lookup
            print(f"[{year}] {title}")
            m = find_movie(title, year)
            if not m:
                print("    ! not found"); continue
            tr = trailer_for(m["id"])
            if not tr:
                print("    · no trailer"); continue
            # Compute absolute indices in s, then plan an edit:
            # insert ', trailer: "tr"' before the closing ' }'
            close_idx = block_start + nom.end() - 2  # position of ' }' end-2 -> before final " }"
            # Easier: replace the whole match
            new_text = f'{{ movie: "{title}", stars: [{nom.group(2)}], trailer: "{tr}" }}'
            abs_start = block_offset + block_start + nom.start()
            abs_end = block_offset + block_start + nom.end()
            edits.append((abs_start, abs_end, new_text))
            print(f"    + {tr}")
            time.sleep(0.07)

    # Apply edits in reverse (so positions stay valid)
    edits.sort(reverse=True)
    for st, en, rep in edits:
        s = s[:st] + rep + s[en:]

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(s)
    print(f"\nApplied {len(edits)} nominee trailers")

if __name__ == "__main__":
    main()
