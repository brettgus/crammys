#!/usr/bin/env python3
"""
Fetch TMDB person data + profile photos for every director/star in the deck.
Writes people.js (window.PEOPLE = {...}) and people/*.jpg for the app.

Run: python3 fetch_people.py
"""
import urllib.request, urllib.parse, json, os, re, sys, time
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
BASE = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w185"

# Duos / collective director credits → list the individuals
DUO_SPLIT = {
    "Joel & Ethan Coen": ["Joel Coen", "Ethan Coen"],
    "Daniel Kwan & Daniel Scheinert": ["Daniel Kwan", "Daniel Scheinert"],
}

# When TMDB search ambiguates, pin the right id
ID_OVERRIDES = {
    "Daniel Kwan": 1397778,
    "Daniel Scheinert": 1397779,
}

def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

def download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(path, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"    ! download failed: {e}")
        return False

def extract_names_from_html():
    with open("index.html", "r", encoding="utf-8") as f:
        s = f.read()
    # Limit search to the DECK array region (now named DECK_INLINE)
    deck_match = re.search(r'const DECK_INLINE = \[(.*?)\n  \];', s, re.DOTALL)
    if not deck_match:
        deck_match = re.search(r'const DECK = \[(.*?)\n  \];', s, re.DOTALL)
    if not deck_match:
        print("Could not find DECK in index.html"); sys.exit(1)
    deck_src = deck_match.group(1)

    directors = list(re.findall(r'director:\s*"([^"]+)"', deck_src))
    stars = []
    for arr in re.findall(r'stars:\s*\[([^\]]+)\]', deck_src):
        stars.extend(re.findall(r'"((?:[^"\\]|\\.)*)"', arr))

    # Also pull from auto-fetched extension JSON, if present
    if os.path.exists("deck_extension.json"):
        import json
        with open("deck_extension.json", encoding="utf-8") as f:
            ext = json.load(f)
        for entry in ext:
            if entry.get("director"): directors.append(entry["director"])
            stars.extend(entry.get("stars") or [])
            for n in entry.get("nominees") or []:
                stars.extend(n.get("stars") or [])

    return directors, stars

def get_person(name):
    if name in ID_OVERRIDES:
        pid = ID_OVERRIDES[name]
        try:
            return fetch_json(f"{BASE}/person/{pid}?api_key={API_KEY}")
        except Exception:
            return None
    try:
        data = fetch_json(f"{BASE}/search/person?api_key={API_KEY}&query={urllib.parse.quote(name)}")
    except Exception as e:
        print(f"    ! search failed: {e}"); return None
    results = data.get("results", [])
    if not results:
        return None
    # exact name match preferred
    exact = [r for r in results if r.get("name", "").lower() == name.lower()]
    chosen = (exact or results)[0]
    try:
        return fetch_json(f"{BASE}/person/{chosen['id']}?api_key={API_KEY}")
    except Exception:
        return chosen

def get_known_for(pid):
    try:
        data = fetch_json(f"{BASE}/person/{pid}/combined_credits?api_key={API_KEY}")
    except Exception:
        return []
    cast = data.get("cast", []) + data.get("crew", [])
    seen = set(); items = []
    for c in cast:
        title = c.get("title") or c.get("name")
        if not title or title in seen: continue
        seen.add(title)
        items.append({
            "title": title,
            "year": (c.get("release_date") or c.get("first_air_date") or "")[:4],
            "popularity": c.get("popularity", 0),
            "vote_count": c.get("vote_count", 0),
        })
    items.sort(key=lambda x: (x["vote_count"], x["popularity"]), reverse=True)
    return [{"title": it["title"], "year": it["year"]} for it in items[:3]]

def short_role(person):
    # Pick a one-word role: "Actor" / "Director" / etc.
    dept = person.get("known_for_department")
    if dept == "Acting": return "Actor"
    if dept == "Directing": return "Director"
    if dept == "Writing": return "Writer"
    if dept: return dept
    return None

def country_from_place(place):
    if not place: return None
    parts = [p.strip() for p in place.split(",")]
    return parts[-1] if parts else None

def main():
    os.makedirs("people", exist_ok=True)
    directors, stars = extract_names_from_html()

    # Expand duos
    name_set = set()
    for n in directors:
        if n in DUO_SPLIT:
            name_set.update(DUO_SPLIT[n])
        else:
            name_set.add(n)
    name_set.update(stars)
    names = sorted(name_set)
    print(f"Resolving {len(names)} unique people…\n")

    people = {}
    for i, name in enumerate(names, 1):
        print(f"[{i}/{len(names)}] {name}")
        p = get_person(name)
        if not p:
            print(f"    ! not found"); people[name] = None; continue
        pid = p.get("id")
        record = {
            "id": pid,
            "imdb_id": p.get("imdb_id"),
            "name": p.get("name", name),
            "born": p.get("birthday"),
            "died": p.get("deathday"),
            "place": p.get("place_of_birth"),
            "country": country_from_place(p.get("place_of_birth")),
            "role": short_role(p),
        }
        # Profile image
        prof = p.get("profile_path")
        if prof:
            ext = os.path.splitext(prof)[1] or ".jpg"
            local_name = f"{slug(name)}-{pid}{ext}"
            local_path = os.path.join("people", local_name)
            if download(f"{IMG_BASE}{prof}", local_path):
                record["img"] = f"people/{local_name}"
                record["tmdb_img"] = prof  # CDN path for hosted versions
        # Known for
        record["knownFor"] = get_known_for(pid)
        people[name] = record
        print(f"    + {record.get('country','?')} · {len(record.get('knownFor',[]))} credits · img={'y' if 'img' in record else 'n'}")
        time.sleep(0.12)

    # Compose output, including duo aliases that point to the duo's individuals
    out = {}
    for k, v in people.items():
        if v: out[k] = v
    for duo, members in DUO_SPLIT.items():
        out[duo] = {
            "duo": [people.get(m) for m in members if people.get(m)],
            "name": duo,
        }

    js = "window.PEOPLE = " + json.dumps(out, ensure_ascii=False) + ";\n"
    with open("people.js", "w", encoding="utf-8") as f:
        f.write(js)
    with open("people/manifest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nDone. {len(out)} entries → people.js")

if __name__ == "__main__":
    main()
