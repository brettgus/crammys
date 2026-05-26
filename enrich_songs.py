#!/usr/bin/env python3
"""
Enrich songs-data.js with Wikipedia song summaries and TMDB film details.

Usage:  python3 enrich_songs.py

Reads TMDB_API_KEY, WIKIMEDIA_BOT_USER, WIKIMEDIA_BOT_PASS from .env.
Resumable: skips entries that already have non-null summary AND filmDirector.
"""
import sys, os, json, urllib.request, urllib.parse, urllib.error, gzip, re, time, subprocess

UA = "Crammys/1.0 (flashcard app)"
BASE = os.path.dirname(os.path.abspath(__file__))

# ── Load .env ────────────────────────────────────────────────────────
def load_env():
    env_path = os.path.join(BASE, ".env")
    if not os.path.exists(env_path):
        print("ERROR: .env not found", file=sys.stderr)
        sys.exit(1)
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
WIKIMEDIA_BOT_USER = os.environ.get("WIKIMEDIA_BOT_USER", "")
WIKIMEDIA_BOT_PASS = os.environ.get("WIKIMEDIA_BOT_PASS", "")

if not TMDB_API_KEY:
    print("ERROR: TMDB_API_KEY not set in .env", file=sys.stderr)
    sys.exit(1)

# ── HTTP helper ──────────────────────────────────────────────────────
def http_get(url, *, headers=None, timeout=30, max_retries=3, backoff=3.0):
    hdrs = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
    if headers:
        hdrs.update(headers)
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  HTTP {e.code} — retrying in {wait:.1f}s…", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  Error ({e}) — retrying in {wait:.1f}s…", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


# ── Read songs-data.js via Node ──────────────────────────────────────
def load_songs():
    js_path = os.path.join(BASE, "songs-data.js")
    json_path = "/tmp/songs_enrich.json"
    subprocess.run([
        "node", "-e",
        f"eval(require('fs').readFileSync({json.dumps(js_path)},'utf8')"
        f".replace('window.SONGS_DATA','var x'));"
        f"require('fs').writeFileSync({json.dumps(json_path)}, JSON.stringify(x))"
    ], check=True)
    with open(json_path) as f:
        return json.load(f)


# ── Write songs-data.js ─────────────────────────────────────────────
def js_val(v, indent=0):
    """Convert a Python value to JS literal with unquoted keys."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        items = ", ".join(js_val(x) for x in v)
        return f"[{items}]"
    if isinstance(v, dict):
        # This shouldn't happen at top level, but just in case
        lines = []
        for k, val in v.items():
            lines.append(f"  {k}: {js_val(val)}")
        return "{\n" + ",\n".join(lines) + "\n}"
    return json.dumps(v)


FIELD_ORDER = [
    "song", "film", "year", "filmYear",
    "songwriters", "performers",
    "spotify", "wikipedia", "wikidata",
    "summary",
    "filmDirector", "filmSummary", "filmWikipedia",
]


def write_songs(songs):
    js_path = os.path.join(BASE, "songs-data.js")
    lines = ["window.SONGS_DATA = ["]
    for i, s in enumerate(songs):
        lines.append("{")
        # Write fields in canonical order, then any extras
        keys_written = set()
        for key in FIELD_ORDER:
            if key in s:
                lines.append(f"  {key}: {js_val(s[key])},")
                keys_written.add(key)
        for key, val in s.items():
            if key not in keys_written:
                lines.append(f"  {key}: {js_val(val)},")
        sep = "," if i < len(songs) - 1 else ""
        lines.append("}" + sep)
    lines.append("];")
    lines.append("")  # trailing newline
    with open(js_path, "w") as f:
        f.write("\n".join(lines))


# ── Wikipedia summary fetcher ────────────────────────────────────────
SUMMARY_MAX = 500

def clean_summary(text):
    """Clean up a Wikipedia extract: strip HTML, collapse whitespace, truncate."""
    if not text:
        return None
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove parenthetical pronunciation guides
    text = re.sub(r'\s*\([^)]*listen[^)]*\)', '', text)
    text = re.sub(r'\s*\([^)]*pronunciation[^)]*\)', '', text, flags=re.I)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return None
    if len(text) <= SUMMARY_MAX:
        return text
    cut = text[:SUMMARY_MAX]
    last_space = cut.rfind(' ')
    if last_space > SUMMARY_MAX - 80:
        cut = cut[:last_space]
    # Try to end at a sentence boundary
    for end in ['. ', '! ', '? ']:
        idx = cut.rfind(end)
        if idx > SUMMARY_MAX - 150:
            cut = cut[:idx + 1]
            break
    else:
        cut = cut.rstrip('.,;:!? ') + '...'
    return cut


def fetch_wiki_summary(title):
    """Fetch the intro extract for a Wikipedia article title."""
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "exintro": "1",
        "explaintext": "1",
        "redirects": "1",
        "format": "json",
    })
    try:
        d = http_get(url)
        pages = d.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1":
                return None
            return clean_summary(page.get("extract", ""))
    except Exception as e:
        print(f"    Wiki extract error: {e}", file=sys.stderr)
        return None


def search_wiki_song(song_name, film_name=None):
    """Search Wikipedia for a song article. Returns (wiki_url, summary) or (None, None).
    Uses a single batched API call to check all candidate titles at once,
    then falls back to Wikipedia search API if none match."""
    # Build candidate titles in priority order
    candidates = [f"{song_name} (song)"]
    if film_name:
        candidates.append(f"{song_name} ({film_name} song)")
    candidates.append(song_name)

    # Batch query all candidates in one API call
    titles_str = "|".join(candidates)
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "titles": titles_str,
        "prop": "extracts|info",
        "exintro": "1",
        "explaintext": "1",
        "redirects": "1",
        "inprop": "url",
        "format": "json",
    })
    try:
        d = http_get(url)
        pages = d.get("query", {}).get("pages", {})

        # Build a map of normalized title -> page data
        # Account for redirects: the API returns a "redirects" array
        redirects = {}
        for r in d.get("query", {}).get("redirects", []):
            redirects[r["from"]] = r["to"]
        normalized = {}
        for n in d.get("query", {}).get("normalized", []):
            normalized[n["from"]] = n["to"]

        # Map each candidate to its resolved page
        title_to_page = {}
        for pid, page in pages.items():
            if pid == "-1" or "missing" in page:
                continue
            title_to_page[page.get("title", "")] = page

        # Check candidates in priority order
        for candidate in candidates:
            # Resolve through normalization and redirects
            resolved = normalized.get(candidate, candidate)
            resolved = redirects.get(resolved, resolved)
            page = title_to_page.get(resolved)
            if not page:
                # Also try direct title match
                for t, p in title_to_page.items():
                    if t.lower() == resolved.lower():
                        page = p
                        break
            if page:
                extract = page.get("extract", "")
                title = page.get("title", "")
                if extract and is_song_related(extract, song_name):
                    wiki_url = page.get("fullurl") or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                    return wiki_url, clean_summary(extract)
    except Exception as e:
        print(f"    Wiki batch error: {e}", file=sys.stderr)

    # Fallback: use Wikipedia search API to find the song article
    time.sleep(2.0)
    return _wiki_search_fallback(song_name, film_name)


def _wiki_search_fallback(song_name, film_name=None):
    """Use Wikipedia opensearch to find a song article by keyword search."""
    query = f'"{song_name}" song'
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": "5",
        "format": "json",
    })
    try:
        d = http_get(url)
        results = d.get("query", {}).get("search", [])
        for hit in results:
            title = hit.get("title", "")
            # Fetch the extract for this result
            time.sleep(1.0)
            ext_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query",
                "titles": title,
                "prop": "extracts|info",
                "exintro": "1",
                "explaintext": "1",
                "redirects": "1",
                "inprop": "url",
                "format": "json",
            })
            d2 = http_get(ext_url)
            pages = d2.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                if pid == "-1" or "missing" in page:
                    continue
                extract = page.get("extract", "")
                if extract and is_song_related(extract, song_name):
                    wiki_url = page.get("fullurl") or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                    return wiki_url, clean_summary(extract)
    except Exception as e:
        print(f"    Wiki search fallback error: {e}", file=sys.stderr)
    return None, None


def is_song_related(extract, song_name):
    """Quick sanity check that the extract is about a song/music."""
    lower = extract.lower()
    keywords = ["song", "music", "singer", "composer", "written by",
                "performed", "soundtrack", "album", "single", "recording",
                "oscar", "academy award", "film", "musical", "lyric",
                "melody", "released", "billboard"]
    return any(kw in lower for kw in keywords)


def get_song_summary(entry):
    """Get Wikipedia summary for a song. Returns (wikipedia_url, summary).
    Skips existing wikipedia URLs since the original data has many bogus URLs
    pointing to unrelated articles. Always does a fresh search."""
    song = entry["song"]
    film = entry.get("film", "")

    # Search for the song article (single batched API call)
    wiki_url, summary = search_wiki_song(song, film)
    return wiki_url, summary


# ── TMDB film fetcher ────────────────────────────────────────────────
def tmdb_get(path, params=None):
    p = {"api_key": TMDB_API_KEY}
    if params:
        p.update(params)
    url = f"https://api.themoviedb.org/3{path}?" + urllib.parse.urlencode(p)
    return http_get(url)


def fetch_film_details(film_title, film_year):
    """Fetch director, summary, and Wikipedia URL for a film from TMDB."""
    if not film_title:
        return None, None, None

    # Search TMDB
    try:
        results = tmdb_get("/search/movie", {
            "query": film_title,
            "year": str(film_year) if film_year else "",
            "include_adult": "false",
        })
    except Exception as e:
        print(f"    TMDB search error: {e}", file=sys.stderr)
        return None, None, None

    hits = results.get("results", [])
    if not hits:
        # Try without year
        try:
            results = tmdb_get("/search/movie", {
                "query": film_title,
                "include_adult": "false",
            })
            hits = results.get("results", [])
        except Exception:
            pass

    if not hits:
        return None, None, None

    # Pick best match
    movie = hits[0]
    movie_id = movie["id"]
    overview = movie.get("overview", "")
    if overview and len(overview) > 300:
        cut = overview[:300]
        last_space = cut.rfind(' ')
        if last_space > 220:
            cut = cut[:last_space]
        # Try to end at sentence
        for end in ['. ', '! ', '? ']:
            idx = cut.rfind(end)
            if idx > 200:
                cut = cut[:idx + 1]
                break
        else:
            cut = cut.rstrip('.,;:!? ') + '...'
        overview = cut

    # Fetch credits for director
    time.sleep(0.25)
    director = None
    try:
        credits = tmdb_get(f"/movie/{movie_id}/credits")
        directors = [c["name"] for c in credits.get("crew", []) if c.get("job") == "Director"]
        if directors:
            director = ", ".join(directors)
    except Exception as e:
        print(f"    TMDB credits error: {e}", file=sys.stderr)

    # Construct Wikipedia URL from film title
    film_wiki = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(film_title.replace(' ', '_'))}"
    # Try to find a better Wikipedia URL by checking if the article exists
    # For films, adding "(film)" or "({year} film)" often helps
    if film_year:
        film_wiki_candidates = [
            film_title,
            f"{film_title} (film)",
            f"{film_title} ({film_year} film)",
        ]
    else:
        film_wiki_candidates = [
            film_title,
            f"{film_title} (film)",
        ]

    film_wiki = resolve_film_wikipedia(film_wiki_candidates)

    return director, overview or None, film_wiki


def resolve_film_wikipedia(candidates):
    """Check which Wikipedia article exists for a film."""
    # Batch check using the API
    titles_str = "|".join(candidates)
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "titles": titles_str,
        "prop": "info",
        "inprop": "url",
        "redirects": "1",
        "format": "json",
    })
    try:
        d = http_get(url)
        pages = d.get("query", {}).get("pages", {})
        # Find existing pages (pid != "-1") and prefer the most specific
        existing = []
        for pid, page in pages.items():
            if pid != "-1" and "missing" not in page:
                existing.append(page)
        if existing:
            # Prefer "(film)" or "(YYYY film)" disambiguation
            for page in existing:
                title = page.get("title", "")
                if "(film)" in title.lower():
                    return page.get("fullurl") or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
            # Otherwise return the first existing
            page = existing[0]
            return page.get("fullurl") or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page['title'].replace(' ', '_'))}"
    except Exception:
        pass
    # Fallback: just use the plain title
    return f"https://en.wikipedia.org/wiki/{urllib.parse.quote(candidates[0].replace(' ', '_'))}"


# ── Main ─────────────────────────────────────────────────────────────
def main():
    print("Loading songs-data.js…", file=sys.stderr)
    songs = load_songs()
    total = len(songs)
    print(f"Loaded {total} songs", file=sys.stderr)

    song_summary_count = 0
    song_summary_new = 0
    film_director_count = 0
    film_director_new = 0
    film_summary_count = 0
    film_summary_new = 0

    for i, entry in enumerate(songs):
        song_name = entry["song"]
        film_name = entry.get("film", "")
        film_year = entry.get("filmYear") or (entry.get("year", 0) - 1)

        need_summary = not entry.get("summary")
        need_film = entry.get("filmDirector") is None

        if not need_summary and not need_film:
            # Already enriched — count existing
            if entry.get("summary"):
                song_summary_count += 1
            if entry.get("filmDirector"):
                film_director_count += 1
            if entry.get("filmSummary"):
                film_summary_count += 1
            continue

        label = f"[{i+1}/{total}]"

        # Fetch song summary
        if need_summary:
            print(f"{label} Song summary: {song_name}…", file=sys.stderr)
            wiki_url, summary = get_song_summary(entry)
            entry["summary"] = summary
            if wiki_url:
                entry["wikipedia"] = wiki_url
            elif entry.get("wikipedia"):
                # Existing URL was bogus (didn't pass sanity check)
                # Clear it rather than keep a wrong URL
                pass
            if summary:
                song_summary_count += 1
                song_summary_new += 1
            time.sleep(5.0)

        # Fetch film details
        if need_film:
            print(f"{label} Film details: {film_name} ({film_year})…", file=sys.stderr)
            director, film_summary, film_wiki = fetch_film_details(film_name, film_year)
            entry["filmDirector"] = director
            entry["filmSummary"] = film_summary
            entry["filmWikipedia"] = film_wiki
            if director:
                film_director_count += 1
                film_director_new += 1
            if film_summary:
                film_summary_count += 1
                film_summary_new += 1
            time.sleep(0.25)

        # Save progress after each entry (resumable)
        write_songs(songs)

    # Final write
    write_songs(songs)

    print(f"\n── Done ──", file=sys.stderr)
    print(f"Song summaries:  {song_summary_count}/{total} ({song_summary_new} new)", file=sys.stderr)
    print(f"Film directors:  {film_director_count}/{total} ({film_director_new} new)", file=sys.stderr)
    print(f"Film summaries:  {film_summary_count}/{total} ({film_summary_new} new)", file=sys.stderr)


if __name__ == "__main__":
    main()
