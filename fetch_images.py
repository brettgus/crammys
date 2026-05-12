#!/usr/bin/env python3
"""
Fetch a varied set of images for each Best Picture winner from TMDB
and write them to images/ along with a JS manifest the app can load.

Run: python3 fetch_images.py
"""
import urllib.request, urllib.parse, json, os, re, sys, time

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
BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w780"

# (ceremony_year, title) — release year is generally ceremony - 1
DECK = [
    (2025, "Anora"),
    (2024, "Oppenheimer"),
    (2023, "Everything Everywhere All at Once"),
    (2022, "CODA"),
    (2021, "Nomadland"),
    (2020, "Parasite"),
    (2019, "Green Book"),
    (2018, "The Shape of Water"),
    (2017, "Moonlight"),
    (2016, "Spotlight"),
    (2015, "Birdman"),
    (2014, "12 Years a Slave"),
    (2013, "Argo"),
    (2012, "The Artist"),
    (2011, "The King's Speech"),
    (2010, "The Hurt Locker"),
    (2009, "Slumdog Millionaire"),
    (2008, "No Country for Old Men"),
    (2007, "The Departed"),
    (2006, "Crash"),
    (2005, "Million Dollar Baby"),
    (2004, "The Lord of the Rings: The Return of the King"),
    (2003, "Chicago"),
    (2002, "A Beautiful Mind"),
    (2001, "Gladiator"),
    (2000, "American Beauty"),
    (1999, "Shakespeare in Love"),
    (1998, "Titanic"),
    (1997, "The English Patient"),
]

# Some titles need disambiguation (multiple TMDB matches) — pin by id when needed
ID_OVERRIDES = {
    (2006, "Crash"): 1640,           # Paul Haggis 2004
    (2022, "CODA"): 776503,
}

def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def find_movie(title, ceremony_year):
    if (ceremony_year, title) in ID_OVERRIDES:
        mid = ID_OVERRIDES[(ceremony_year, title)]
        return fetch_json(f"{BASE}/movie/{mid}?api_key={API_KEY}")
    for ry in [ceremony_year - 1, ceremony_year - 2, ceremony_year]:
        url = f"{BASE}/search/movie?api_key={API_KEY}&query={urllib.parse.quote(title)}&primary_release_year={ry}"
        data = fetch_json(url)
        if data.get("results"):
            for r in data["results"]:
                if r.get("title", "").lower() == title.lower():
                    return r
            return data["results"][0]
    url = f"{BASE}/search/movie?api_key={API_KEY}&query={urllib.parse.quote(title)}"
    data = fetch_json(url)
    return data["results"][0] if data.get("results") else None

def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(path, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"    ! failed {url}: {e}")
        return False

def load_extension():
    """Yield (year, title, tmdb_id_or_None) for the auto-fetched 1947-1996 entries."""
    p = "deck_extension.json"
    if not os.path.exists(p): return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for e in data:
        out.append((e["year"], e["movie"], e.get("tmdb_id")))
    return out

def collect_nominee_titles():
    """Return [(year, title)] for every nominee in DECK_INLINE + deck_extension.json."""
    nominees = []
    seen = set()
    # Inline (parse HTML)
    if os.path.exists("index.html"):
        with open("index.html", encoding="utf-8") as f:
            html = f.read()
        deck = re.search(r'const DECK_INLINE = \[(.*?)\n  \];', html, re.DOTALL)
        if deck:
            src = deck.group(1)
            yspans = list(re.finditer(r'\{ year: (\d{4}),', src))
            for i, m in enumerate(yspans):
                year = int(m.group(1))
                bs = m.end()
                be = yspans[i+1].start() if i+1 < len(yspans) else len(src)
                for nom in re.finditer(r'\{ movie: "([^"]+)"', src[bs:be]):
                    t = nom.group(1)
                    key = (year, t)
                    if key not in seen:
                        seen.add(key); nominees.append((year, t))
    # Extension
    if os.path.exists("deck_extension.json"):
        with open("deck_extension.json", encoding="utf-8") as f:
            ext = json.load(f)
        for e in ext:
            year = e["year"]
            for n in e.get("nominees") or []:
                t = n["movie"]
                key = (year, t)
                if key not in seen:
                    seen.add(key); nominees.append((year, t))
    return nominees

# Number of backdrops to fetch per film. Nominees get fewer (still gives image variety
# without blowing up disk usage).
N_BACKDROPS_WINNER = 5
N_BACKDROPS_NOMINEE = 3

def fetch_film_images(year, title, hint_id, status, manifest, ext_ids):
    """Fetch images for a single film. Appends to `manifest`. Idempotent on disk."""
    # Resolve TMDB id
    if hint_id:
        mid = hint_id
        try:
            m = fetch_json(f"{BASE}/movie/{mid}?api_key={API_KEY}")
        except Exception as e:
            print(f"  ! tmdb fetch failed: {e}"); return
    elif title in ext_ids:
        mid = ext_ids[title]
        try:
            m = fetch_json(f"{BASE}/movie/{mid}?api_key={API_KEY}")
        except Exception as e:
            print(f"  ! tmdb fetch failed: {e}"); return
    else:
        try:
            m = find_movie(title, year)
        except Exception as e:
            print(f"  ! search failed: {e}"); return
        if not m:
            print("  ! no match"); return
        mid = m["id"]

    try:
        images = fetch_json(f"{BASE}/movie/{mid}/images?api_key={API_KEY}&include_image_language=en,null")
    except Exception as e:
        print(f"  ! images fetch failed: {e}"); return

    backdrops = sorted(images.get("backdrops", []), key=lambda x: x.get("vote_count", 0), reverse=True)
    posters = sorted(images.get("posters", []), key=lambda x: x.get("vote_count", 0), reverse=True)

    n_bd = N_BACKDROPS_WINNER if status == "winner" else N_BACKDROPS_NOMINEE
    chosen = [("bd", b) for b in backdrops[:n_bd]] + [("ps", p) for p in posters[:1]]

    saved = []
    for i, (kind, img) in enumerate(chosen):
        path_remote = img["file_path"]
        url = f"{IMG_BASE}{path_remote}"
        ext = os.path.splitext(path_remote)[1] or ".jpg"
        local_name = f"{year}-{slug(title)}-{kind}-{i}{ext}"
        local_path = os.path.join("images", local_name)
        if download(url, local_path):
            ratio = img.get("aspect_ratio", 1.78)
            saved.append({"f": local_name, "p": path_remote, "r": round(ratio, 3), "k": kind})
        time.sleep(0.04)

    manifest.append({
        "year": year,
        "movie": title,
        "tmdb_id": mid,
        "status": status,
        "images": saved,
    })

def main():
    os.makedirs("images", exist_ok=True)
    manifest = []
    ext_ids = {t: mid for (y, t, mid) in load_extension() if mid}

    # 1. Winners (inline DECK list + extension)
    winners = list(DECK) + [(y, t) for (y, t, _mid) in load_extension()]
    print(f"Winners: {len(winners)}")
    for year, title in winners:
        print(f"--- WIN {year}: {title}")
        fetch_film_images(year, title, None, "winner", manifest, ext_ids)
        time.sleep(0.08)

    # 2. Nominees
    nominees = collect_nominee_titles()
    print(f"\nNominees: {len(nominees)}")
    for year, title in nominees:
        print(f"--- NOM {year}: {title}")
        fetch_film_images(year, title, None, "nominee", manifest, ext_ids)
        time.sleep(0.08)

    # Write a JS-loadable manifest so file:// avoids fetch/CORS issues
    js_payload = "window.MOVIE_IMAGES = " + json.dumps(manifest, ensure_ascii=False) + ";\n"
    with open("images.js", "w", encoding="utf-8") as f:
        f.write(js_payload)
    with open("images/manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\nDone. {len(manifest)} films, manifest written to images.js and images/manifest.json")

if __name__ == "__main__":
    main()
