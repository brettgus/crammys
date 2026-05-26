#!/usr/bin/env python3
"""
Fetch Grammy "Big Four" award winners from Wikidata SPARQL.
Enrich with Spotify IDs and Wikipedia URLs.
Output: grammys-data.js  (window.GRAMMYS_DATA = [...])

Usage: python3 fetch_grammys.py

Spotify credentials are read from .env (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET).
Resumable: if grammys-data.js already exists, entries with a non-null spotify field
are skipped on re-run.
"""
import sys, json, os, re, time, base64, urllib.request, urllib.parse, urllib.error, gzip

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
UA = "Crammys/1.0 (flashcard app)"
OUTFILE = "grammys-data.js"


# ── .env loader ──────────────────────────────────────────────────────
def load_dotenv(path=".env"):
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# ── HTTP helpers ─────────────────────────────────────────────────────
def http_get(url, *, headers=None, timeout=90, max_retries=3, backoff=5.0):
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
                return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  HTTP {e.code} -- sleeping {wait:.1f}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  Error ({e}) -- retrying in {wait:.1f}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def http_json(url, **kwargs):
    return json.loads(http_get(url, **kwargs))


def http_post(url, body, *, headers=None, timeout=60, max_retries=3, backoff=5.0):
    hdrs = {
        "User-Agent": UA,
        "Accept": "application/json",
    }
    if headers:
        hdrs.update(headers)
    data_bytes = body.encode("utf-8") if isinstance(body, str) else body
    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=data_bytes, headers=hdrs, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  HTTP {e.code} -- sleeping {wait:.1f}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  Error ({e}) -- retrying in {wait:.1f}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


def sparql_query(query):
    url = WIKIDATA_SPARQL + "?" + urllib.parse.urlencode({
        "query": query, "format": "json"
    })
    return http_json(url, timeout=120)["results"]["bindings"]


# ── Wikidata helpers ─────────────────────────────────────────────────
def val(binding, key, default=None):
    v = binding.get(key, {})
    return v.get("value", default) if isinstance(v, dict) else default


def qid_from_uri(uri):
    if not uri:
        return None
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


# ── Spotify ──────────────────────────────────────────────────────────
class SpotifyClient:
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    SEARCH_URL = "https://api.spotify.com/v1/search"

    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.token_expiry = 0

    def _ensure_token(self):
        if self.token and time.time() < self.token_expiry - 60:
            return
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials"})
        resp = http_post(self.TOKEN_URL, body, headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        self.token = resp["access_token"]
        self.token_expiry = time.time() + resp.get("expires_in", 3600)

    def _search(self, q, stype, limit=5):
        self._ensure_token()
        url = self.SEARCH_URL + "?" + urllib.parse.urlencode({
            "q": q, "type": stype, "limit": str(limit),
        })
        try:
            resp = http_json(url, headers={
                "Authorization": f"Bearer {self.token}",
            })
        except urllib.error.HTTPError as e:
            if e.code == 401:
                self.token = None
                self._ensure_token()
                resp = http_json(url, headers={
                    "Authorization": f"Bearer {self.token}",
                })
            else:
                return None
        return resp

    def search_album(self, album_title, artist_name=None):
        q_parts = [f'album:"{album_title}"']
        if artist_name:
            q_parts.append(f'artist:"{artist_name}"')
        resp = self._search(" ".join(q_parts), "album")
        if not resp:
            return None
        items = resp.get("albums", {}).get("items", [])
        if not items and artist_name:
            resp2 = self._search(f"{album_title} {artist_name}", "album")
            if resp2:
                items = resp2.get("albums", {}).get("items", [])
        if items:
            return items[0]["id"]
        return None

    def search_track(self, track_title, artist_name=None):
        q_parts = [f'track:"{track_title}"']
        if artist_name:
            q_parts.append(f'artist:"{artist_name}"')
        resp = self._search(" ".join(q_parts), "track")
        if not resp:
            return None
        items = resp.get("tracks", {}).get("items", [])
        if not items and artist_name:
            resp2 = self._search(f"{track_title} {artist_name}", "track")
            if resp2:
                items = resp2.get("tracks", {}).get("items", [])
        if items:
            return items[0]["id"]
        return None

    def search_artist(self, artist_name):
        resp = self._search(f'artist:"{artist_name}"', "artist")
        if not resp:
            return None
        items = resp.get("artists", {}).get("items", [])
        if not items:
            resp2 = self._search(artist_name, "artist")
            if resp2:
                items = resp2.get("artists", {}).get("items", [])
        if items:
            return items[0]["id"]
        return None


# ── Wikipedia URLs via Wikidata sitelinks (batch) ────────────────────
def batch_wikipedia_urls(qids):
    result = {}
    for batch_start in range(0, len(qids), 50):
        batch = qids[batch_start:batch_start + 50]
        url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "sitelinks",
            "sitefilter": "enwiki",
            "format": "json",
        })
        try:
            d = http_json(url)
            for qid in batch:
                entity = d.get("entities", {}).get(qid, {})
                sitelinks = entity.get("sitelinks", {})
                enwiki = sitelinks.get("enwiki", {})
                title = enwiki.get("title")
                if title:
                    slug = title.replace(" ", "_")
                    result[qid] = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(slug, safe='/:_')}"
        except Exception as e:
            print(f"    Error batch-fetching sitelinks: {e}", file=sys.stderr)
        time.sleep(1.5)
    return result


# ── Wikidata descriptions (batch) ───────────────────────────────────
def batch_descriptions(qids):
    result = {}
    for batch_start in range(0, len(qids), 50):
        batch = qids[batch_start:batch_start + 50]
        url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
            "action": "wbgetentities",
            "ids": "|".join(batch),
            "props": "descriptions",
            "languages": "en",
            "format": "json",
        })
        try:
            d = http_json(url)
            for qid in batch:
                entity = d.get("entities", {}).get(qid, {})
                descs = entity.get("descriptions", {})
                en_desc = descs.get("en", {})
                desc_val = en_desc.get("value")
                if desc_val:
                    result[qid] = desc_val
        except Exception as e:
            print(f"    Error batch-fetching descriptions: {e}", file=sys.stderr)
        time.sleep(1.0)
    return result


# ── Wikidata entity search (resolve name → QID) ─────────────────────
def search_wikidata_qid(name):
    """Search Wikidata for an entity by name. Returns QID or None."""
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbsearchentities",
        "search": name,
        "language": "en",
        "limit": "3",
        "format": "json",
    })
    try:
        d = http_json(url)
        results = d.get("search", [])
        if results:
            return results[0]["id"]
    except Exception as e:
        print(f"    Error searching for '{name}': {e}", file=sys.stderr)
    return None


# ── Parse existing output for resumability ───────────────────────────
def load_existing():
    if not os.path.isfile(OUTFILE):
        return {}
    with open(OUTFILE, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'window\.GRAMMYS_DATA\s*=\s*', text)
    if not m:
        return {}
    array_text = text[m.end():].rstrip().rstrip(";").rstrip()
    out_lines = []
    for line in array_text.split("\n"):
        stripped = line.lstrip()
        prop_match = re.match(r'^(\w+)(\s*:\s*)', stripped)
        if prop_match and not stripped.startswith('"'):
            indent = line[:len(line) - len(stripped)]
            key = prop_match.group(1)
            rest = stripped[prop_match.end():]
            line = f'{indent}"{key}": {rest}'
        out_lines.append(line)
    json_text = "\n".join(out_lines)
    json_text = re.sub(r',\s*([}\]])', r'\1', json_text)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return {}
    return {_rec_key(r): r for r in data}


def _rec_key(rec):
    return f"{rec.get('categoryShort', '')}|{rec.get('artist', '')}|{rec.get('year', '')}"


# ── SPARQL queries for each Big Four category ───────────────────────
# Q590390  = Grammy Award for Album of the Year
# Q213196  = Grammy Award for Record of the Year
# Q838684  = Grammy Award for Song of the Year
# Q855637  = Grammy Award for Best New Artist

CATEGORIES = [
    {"qid": "Q590390", "name": "Album of the Year", "short": "AOTY", "spotifyType": "album"},
    {"qid": "Q213196", "name": "Record of the Year", "short": "ROTY", "spotifyType": "track"},
    {"qid": "Q838684", "name": "Song of the Year", "short": "SOTY", "spotifyType": "track"},
    {"qid": "Q855637", "name": "Best New Artist", "short": "BNA", "spotifyType": "artist"},
]

# For AOTY, ROTY, SOTY: the award goes to a work, and we want artist + work
SPARQL_WORK_CATEGORY = """
SELECT DISTINCT
  ?artist ?artistLabel ?artistQid
  ?work ?workLabel
  ?ceremonyYear
WHERE {{
  # Find entities that received the award
  ?entity p:P166 ?awardStmt .
  ?awardStmt ps:P166 wd:{cat_qid} .

  # Ceremony date
  OPTIONAL {{
    ?awardStmt pq:P585 ?ceremonyDate .
    BIND(YEAR(?ceremonyDate) AS ?ceremonyYear)
  }}

  # The entity could be the work itself, or a person
  # Try: entity is the work
  OPTIONAL {{ ?entity wdt:P175 ?artistFromWork . }}
  # Try: entity is a person, and the work is via P1686 (for work)
  OPTIONAL {{ ?awardStmt pq:P1686 ?workFromStmt . }}

  BIND(COALESCE(?workFromStmt, ?entity) AS ?work)
  BIND(COALESCE(?artistFromWork, ?entity) AS ?artistCandidate)

  # Get performer of the work
  OPTIONAL {{ ?work wdt:P175 ?workPerformer . }}
  BIND(COALESCE(?workPerformer, ?artistCandidate) AS ?artist)

  BIND(REPLACE(STR(?artist), "http://www.wikidata.org/entity/", "") AS ?artistQid)

  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
ORDER BY ?ceremonyYear
"""

# For Best New Artist: the award goes to a person/group
SPARQL_BNA = """
SELECT DISTINCT
  ?artist ?artistLabel ?artistQid
  ?ceremonyYear
WHERE {
  ?artist p:P166 ?awardStmt .
  ?awardStmt ps:P166 wd:Q855637 .

  OPTIONAL {
    ?awardStmt pq:P585 ?ceremonyDate .
    BIND(YEAR(?ceremonyDate) AS ?ceremonyYear)
  }

  BIND(REPLACE(STR(?artist), "http://www.wikidata.org/entity/", "") AS ?artistQid)

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY ?ceremonyYear
"""


# ── Hardcoded fallback data ──────────────────────────────────────────
# Many early winners are not well-modeled in Wikidata.
FALLBACK_DATA = [
    # Album of the Year
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Frank Sinatra", "work": "Come Dance with Me!", "year": 1960, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Bob Newhart", "work": "The Button-Down Mind of Bob Newhart", "year": 1961, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Judy Garland", "work": "Judy at Carnegie Hall", "year": 1962, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Vaughn Meader", "work": "The First Family", "year": 1963, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Barbra Streisand", "work": "The Barbra Streisand Album", "year": 1964, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Stan Getz and Joao Gilberto", "work": "Getz/Gilberto", "year": 1965, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Frank Sinatra", "work": "September of My Years", "year": 1966, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Frank Sinatra", "work": "A Man and His Music", "year": 1967, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "The Beatles", "work": "Sgt. Pepper's Lonely Hearts Club Band", "year": 1968, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Glen Campbell", "work": "By the Time I Get to Phoenix", "year": 1969, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Blood, Sweat & Tears", "work": "Blood, Sweat & Tears", "year": 1970, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Simon & Garfunkel", "work": "Bridge over Troubled Water", "year": 1971, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Carole King", "work": "Tapestry", "year": 1972, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "George Harrison and friends", "work": "The Concert for Bangladesh", "year": 1973, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Stevie Wonder", "work": "Innervisions", "year": 1974, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Stevie Wonder", "work": "Fulfillingness' First Finale", "year": 1975, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Paul Simon", "work": "Still Crazy After All These Years", "year": 1976, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Stevie Wonder", "work": "Songs in the Key of Life", "year": 1977, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Fleetwood Mac", "work": "Rumours", "year": 1978, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Bee Gees", "work": "Saturday Night Fever", "year": 1979, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Billy Joel", "work": "52nd Street", "year": 1980, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Christopher Cross", "work": "Christopher Cross", "year": 1981, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "John Lennon and Yoko Ono", "work": "Double Fantasy", "year": 1982, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Toto", "work": "Toto IV", "year": 1983, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Michael Jackson", "work": "Thriller", "year": 1984, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Lionel Richie", "work": "Can't Slow Down", "year": 1985, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Phil Collins", "work": "No Jacket Required", "year": 1986, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Paul Simon", "work": "Graceland", "year": 1987, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "U2", "work": "The Joshua Tree", "year": 1988, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "George Michael", "work": "Faith", "year": 1989, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Bonnie Raitt", "work": "Nick of Time", "year": 1990, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Quincy Jones", "work": "Back on the Block", "year": 1991, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Natalie Cole", "work": "Unforgettable... with Love", "year": 1992, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Eric Clapton", "work": "Unplugged", "year": 1993, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Whitney Houston", "work": "The Bodyguard", "year": 1994, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Tony Bennett", "work": "MTV Unplugged", "year": 1995, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Alanis Morissette", "work": "Jagged Little Pill", "year": 1996, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Celine Dion", "work": "Falling into You", "year": 1997, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Bob Dylan", "work": "Time Out of Mind", "year": 1998, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Lauryn Hill", "work": "The Miseducation of Lauryn Hill", "year": 1999, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Santana", "work": "Supernatural", "year": 2000, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Steely Dan", "work": "Two Against Nature", "year": 2001, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Various Artists", "work": "O Brother, Where Art Thou?", "year": 2002, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Norah Jones", "work": "Come Away with Me", "year": 2003, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "OutKast", "work": "Speakerboxxx/The Love Below", "year": 2004, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Ray Charles", "work": "Genius Loves Company", "year": 2005, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "U2", "work": "How to Dismantle an Atomic Bomb", "year": 2006, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Dixie Chicks", "work": "Taking the Long Way", "year": 2007, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Herbie Hancock", "work": "River: The Joni Letters", "year": 2008, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Robert Plant and Alison Krauss", "work": "Raising Sand", "year": 2009, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Taylor Swift", "work": "Fearless", "year": 2010, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Arcade Fire", "work": "The Suburbs", "year": 2011, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Adele", "work": "21", "year": 2012, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Mumford & Sons", "work": "Babel", "year": 2013, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Daft Punk", "work": "Random Access Memories", "year": 2014, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Beck", "work": "Morning Phase", "year": 2015, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Taylor Swift", "work": "1989", "year": 2016, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Adele", "work": "25", "year": 2017, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Bruno Mars", "work": "24K Magic", "year": 2018, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Kacey Musgraves", "work": "Golden Hour", "year": 2019, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Billie Eilish", "work": "When We All Fall Asleep, Where Do We Go?", "year": 2020, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Taylor Swift", "work": "Folklore", "year": 2021, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Jon Batiste", "work": "We Are", "year": 2022, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Harry Styles", "work": "Harry's House", "year": 2023, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Taylor Swift", "work": "Midnights", "year": 2024, "spotifyType": "album"},
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Beyonce", "work": "Cowboy Carter", "year": 2025, "spotifyType": "album"},
    # First Grammy ceremony (1959)
    {"category": "Album of the Year", "categoryShort": "AOTY", "artist": "Henry Mancini", "work": "The Music from Peter Gunn", "year": 1959, "spotifyType": "album"},
    # Record of the Year
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Domenico Modugno", "work": "Nel blu, dipinto di blu (Volare)", "year": 1959, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Bobby Darin", "work": "Mack the Knife", "year": 1960, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Percy Faith", "work": "Theme from A Summer Place", "year": 1961, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Henry Mancini", "work": "Moon River", "year": 1962, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Tony Bennett", "work": "I Left My Heart in San Francisco", "year": 1963, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Henry Mancini", "work": "The Days of Wine and Roses", "year": 1964, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Stan Getz and Astrud Gilberto", "work": "The Girl from Ipanema", "year": 1965, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Herb Alpert & the Tijuana Brass", "work": "A Taste of Honey", "year": 1966, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Frank Sinatra", "work": "Strangers in the Night", "year": 1967, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "5th Dimension", "work": "Up, Up and Away", "year": 1968, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Simon & Garfunkel", "work": "Mrs. Robinson", "year": 1969, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "5th Dimension", "work": "Aquarius/Let the Sunshine In", "year": 1970, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Simon & Garfunkel", "work": "Bridge over Troubled Water", "year": 1971, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Carole King", "work": "It's Too Late", "year": 1972, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Roberta Flack", "work": "The First Time Ever I Saw Your Face", "year": 1973, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Roberta Flack", "work": "Killing Me Softly with His Song", "year": 1974, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Olivia Newton-John", "work": "I Honestly Love You", "year": 1975, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Captain & Tennille", "work": "Love Will Keep Us Together", "year": 1976, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "George Benson", "work": "This Masquerade", "year": 1977, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Eagles", "work": "Hotel California", "year": 1978, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Billy Joel", "work": "Just the Way You Are", "year": 1979, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "The Doobie Brothers", "work": "What a Fool Believes", "year": 1980, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Christopher Cross", "work": "Sailing", "year": 1981, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Kim Carnes", "work": "Bette Davis Eyes", "year": 1982, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Toto", "work": "Rosanna", "year": 1983, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Michael Jackson", "work": "Beat It", "year": 1984, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Tina Turner", "work": "What's Love Got to Do with It", "year": 1985, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "USA for Africa", "work": "We Are the World", "year": 1986, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Steve Winwood", "work": "Higher Love", "year": 1987, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Paul Simon", "work": "Graceland", "year": 1988, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Bobby McFerrin", "work": "Don't Worry, Be Happy", "year": 1989, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Bonnie Raitt", "work": "Nick of Time", "year": 1990, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Phil Collins", "work": "Another Day in Paradise", "year": 1991, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Natalie Cole", "work": "Unforgettable", "year": 1992, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Eric Clapton", "work": "Tears in Heaven", "year": 1993, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Whitney Houston", "work": "I Will Always Love You", "year": 1994, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Sheryl Crow", "work": "All I Wanna Do", "year": 1995, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Seal", "work": "Kiss from a Rose", "year": 1996, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Eric Clapton", "work": "Change the World", "year": 1997, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Shawn Colvin", "work": "Sunny Came Home", "year": 1998, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Celine Dion", "work": "My Heart Will Go On", "year": 1999, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Santana featuring Rob Thomas", "work": "Smooth", "year": 2000, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "U2", "work": "Beautiful Day", "year": 2001, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "U2", "work": "Walk On", "year": 2002, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Norah Jones", "work": "Don't Know Why", "year": 2003, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Coldplay", "work": "Clocks", "year": 2004, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Ray Charles and Norah Jones", "work": "Here We Go Again", "year": 2005, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Green Day", "work": "Boulevard of Broken Dreams", "year": 2006, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Dixie Chicks", "work": "Not Ready to Make Nice", "year": 2007, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Amy Winehouse", "work": "Rehab", "year": 2008, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Robert Plant and Alison Krauss", "work": "Please Read the Letter", "year": 2009, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Kings of Leon", "work": "Use Somebody", "year": 2010, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Lady Antebellum", "work": "Need You Now", "year": 2011, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Adele", "work": "Rolling in the Deep", "year": 2012, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Gotye featuring Kimbra", "work": "Somebody That I Used to Know", "year": 2013, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Daft Punk featuring Pharrell Williams and Nile Rodgers", "work": "Get Lucky", "year": 2014, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Sam Smith", "work": "Stay with Me", "year": 2015, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Mark Ronson featuring Bruno Mars", "work": "Uptown Funk", "year": 2016, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Adele", "work": "Hello", "year": 2017, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Bruno Mars", "work": "24K Magic", "year": 2018, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Childish Gambino", "work": "This Is America", "year": 2019, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Billie Eilish", "work": "Bad Guy", "year": 2020, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Billie Eilish", "work": "Everything I Wanted", "year": 2021, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Silk Sonic", "work": "Leave the Door Open", "year": 2022, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Lizzo", "work": "About Damn Time", "year": 2023, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Miley Cyrus", "work": "Flowers", "year": 2024, "spotifyType": "track"},
    {"category": "Record of the Year", "categoryShort": "ROTY", "artist": "Beyonce", "work": "Texas Hold 'Em", "year": 2025, "spotifyType": "track"},
    # Song of the Year
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Domenico Modugno", "work": "Nel blu, dipinto di blu (Volare)", "year": 1959, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Jimmy Driftwood", "work": "The Battle of New Orleans", "year": 1960, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Ernest Gold", "work": "Theme from Exodus", "year": 1961, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Henry Mancini and Johnny Mercer", "work": "Moon River", "year": 1962, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Leslie Bricusse and Anthony Newley", "work": "What Kind of Fool Am I?", "year": 1963, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Johnny Mercer and Henry Mancini", "work": "Days of Wine and Roses", "year": 1964, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Jerry Herman", "work": "Hello, Dolly!", "year": 1965, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Paul Francis Webster and Johnny Mandel", "work": "The Shadow of Your Smile", "year": 1966, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "John Lennon and Paul McCartney", "work": "Michelle", "year": 1967, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Jim Webb", "work": "Up, Up and Away", "year": 1968, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Bobby Russell", "work": "Little Green Apples", "year": 1969, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Joe South", "work": "Games People Play", "year": 1970, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Paul Simon", "work": "Bridge over Troubled Water", "year": 1971, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Carole King", "work": "You've Got a Friend", "year": 1972, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Ewan MacColl", "work": "The First Time Ever I Saw Your Face", "year": 1973, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Norman Gimbel and Charles Fox", "work": "Killing Me Softly with His Song", "year": 1974, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Marilyn Bergman, Alan Bergman, and Marvin Hamlisch", "work": "The Way We Were", "year": 1975, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Stephen Sondheim", "work": "Send in the Clowns", "year": 1976, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Barbra Streisand and Paul Williams", "work": "Evergreen", "year": 1977, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Joe Brooks", "work": "You Light Up My Life", "year": 1978, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Billy Joel", "work": "Just the Way You Are", "year": 1979, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Kenny Loggins and Michael McDonald", "work": "What a Fool Believes", "year": 1980, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Christopher Cross", "work": "Sailing", "year": 1981, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Donna Weiss and Jackie DeShannon", "work": "Bette Davis Eyes", "year": 1982, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Johnny Christopher, Mark James, and Wayne Carson", "work": "Always on My Mind", "year": 1983, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Sting", "work": "Every Breath You Take", "year": 1984, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Graham Lyle and Terry Britten", "work": "What's Love Got to Do with It", "year": 1985, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Michael Jackson and Lionel Richie", "work": "We Are the World", "year": 1986, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Burt Bacharach and Carole Bayer Sager", "work": "That's What Friends Are For", "year": 1987, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "James Horner, Barry Mann, and Cynthia Weil", "work": "Somewhere Out There", "year": 1988, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Bobby McFerrin", "work": "Don't Worry, Be Happy", "year": 1989, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Larry Henley and Jeff Silbar", "work": "Wind Beneath My Wings", "year": 1990, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Julie Gold", "work": "From a Distance", "year": 1991, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Irving Gordon", "work": "Unforgettable", "year": 1992, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Eric Clapton and Will Jennings", "work": "Tears in Heaven", "year": 1993, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Alan Menken and Tim Rice", "work": "A Whole New World", "year": 1994, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Bruce Springsteen", "work": "Streets of Philadelphia", "year": 1995, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Seal", "work": "Kiss from a Rose", "year": 1996, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Gordon Kennedy, Wayne Kirkpatrick, and Tommy Sims", "work": "Change the World", "year": 1997, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Shawn Colvin and John Leventhal", "work": "Sunny Came Home", "year": 1998, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "James Horner and Will Jennings", "work": "My Heart Will Go On", "year": 1999, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Itaal Shur and Rob Thomas", "work": "Smooth", "year": 2000, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "U2", "work": "Beautiful Day", "year": 2001, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Alicia Keys", "work": "Fallin'", "year": 2002, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Jesse Harris", "work": "Don't Know Why", "year": 2003, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "John Mayer", "work": "Daughters", "year": 2005, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Bono and U2", "work": "Sometimes You Can't Make It on Your Own", "year": 2006, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Dixie Chicks", "work": "Not Ready to Make Nice", "year": 2007, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Amy Winehouse", "work": "Rehab", "year": 2008, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Coldplay", "work": "Viva la Vida", "year": 2009, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Beyonce", "work": "Single Ladies (Put a Ring on It)", "year": 2010, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Lady Antebellum", "work": "Need You Now", "year": 2011, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Adele and Paul Epworth", "work": "Rolling in the Deep", "year": 2012, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "fun.", "work": "We Are Young", "year": 2013, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Lorde", "work": "Royals", "year": 2014, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Sam Smith", "work": "Stay with Me", "year": 2015, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Ed Sheeran", "work": "Thinking Out Loud", "year": 2016, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Adele", "work": "Hello", "year": 2017, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Bruno Mars", "work": "That's What I Like", "year": 2018, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Childish Gambino", "work": "This Is America", "year": 2019, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Billie Eilish", "work": "Bad Guy", "year": 2020, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "H.E.R.", "work": "I Can't Breathe", "year": 2021, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Silk Sonic", "work": "Leave the Door Open", "year": 2022, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Bonnie Raitt", "work": "Just Like That", "year": 2023, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Billie Eilish", "work": "What Was I Made For?", "year": 2024, "spotifyType": "track"},
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Shaboozey", "work": "A Bar Song (Tipsy)", "year": 2025, "spotifyType": "track"},
    # SOTY 2004 was Luther Vandross "Dance with My Father"
    {"category": "Song of the Year", "categoryShort": "SOTY", "artist": "Luther Vandross and Richard Marx", "work": "Dance with My Father", "year": 2004, "spotifyType": "track"},
    # Best New Artist
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Bobby Darin", "work": "", "year": 1960, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Bob Newhart", "work": "", "year": 1961, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Peter Nero", "work": "", "year": 1962, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Robert Goulet", "work": "", "year": 1963, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Ward Swingle", "work": "", "year": 1964, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "The Beatles", "work": "", "year": 1965, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Tom Jones", "work": "", "year": 1966, "spotifyType": "artist"},
    # 1967: no Best New Artist awarded
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Bobbie Gentry", "work": "", "year": 1968, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Jose Feliciano", "work": "", "year": 1969, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Crosby, Stills & Nash", "work": "", "year": 1970, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "The Carpenters", "work": "", "year": 1971, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Carly Simon", "work": "", "year": 1972, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "America", "work": "", "year": 1973, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Bette Midler", "work": "", "year": 1974, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Marvin Hamlisch", "work": "", "year": 1975, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Natalie Cole", "work": "", "year": 1976, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Starland Vocal Band", "work": "", "year": 1977, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Debby Boone", "work": "", "year": 1978, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "A Taste of Honey", "work": "", "year": 1979, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Rickie Lee Jones", "work": "", "year": 1980, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Christopher Cross", "work": "", "year": 1981, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Sheena Easton", "work": "", "year": 1982, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Men at Work", "work": "", "year": 1983, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Culture Club", "work": "", "year": 1984, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Cyndi Lauper", "work": "", "year": 1985, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Sade", "work": "", "year": 1986, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Bruce Hornsby and the Range", "work": "", "year": 1987, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Jody Watley", "work": "", "year": 1988, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Tracy Chapman", "work": "", "year": 1989, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Milli Vanilli", "work": "", "year": 1990, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Mariah Carey", "work": "", "year": 1991, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Marc Cohn", "work": "", "year": 1992, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Arrested Development", "work": "", "year": 1993, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Toni Braxton", "work": "", "year": 1994, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Sheryl Crow", "work": "", "year": 1995, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Hootie & the Blowfish", "work": "", "year": 1996, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "LeAnn Rimes", "work": "", "year": 1997, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Paula Cole", "work": "", "year": 1998, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Lauryn Hill", "work": "", "year": 1999, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Christina Aguilera", "work": "", "year": 2000, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Shelby Lynne", "work": "", "year": 2001, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Alicia Keys", "work": "", "year": 2002, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Norah Jones", "work": "", "year": 2003, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Evanescence", "work": "", "year": 2004, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Maroon 5", "work": "", "year": 2005, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "John Legend", "work": "", "year": 2006, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Carrie Underwood", "work": "", "year": 2007, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Amy Winehouse", "work": "", "year": 2008, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Adele", "work": "", "year": 2009, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Zac Brown Band", "work": "", "year": 2010, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Esperanza Spalding", "work": "", "year": 2011, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Bon Iver", "work": "", "year": 2012, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "fun.", "work": "", "year": 2013, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Macklemore & Ryan Lewis", "work": "", "year": 2014, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Sam Smith", "work": "", "year": 2015, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Meghan Trainor", "work": "", "year": 2016, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Chance the Rapper", "work": "", "year": 2017, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Alessia Cara", "work": "", "year": 2018, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Dua Lipa", "work": "", "year": 2019, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Billie Eilish", "work": "", "year": 2020, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Megan Thee Stallion", "work": "", "year": 2021, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Olivia Rodrigo", "work": "", "year": 2022, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Samara Joy", "work": "", "year": 2023, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Victoria Monet", "work": "", "year": 2024, "spotifyType": "artist"},
    {"category": "Best New Artist", "categoryShort": "BNA", "artist": "Chappell Roan", "work": "", "year": 2025, "spotifyType": "artist"},
]

# De-duplicate fallback (keep first occurrence per key)
_seen_fb = set()
_deduped_fb = []
for fb in FALLBACK_DATA:
    k = _rec_key(fb)
    if k not in _seen_fb:
        _seen_fb.add(k)
        _deduped_fb.append(fb)
FALLBACK_DATA = _deduped_fb


# ── Main ─────────────────────────────────────────────────────────────
def main():
    load_dotenv()

    print("Fetching Grammy Big Four award winners...\n", file=sys.stderr)

    existing = load_existing()
    if existing:
        print(f"  Found {len(existing)} existing entries in {OUTFILE}", file=sys.stderr)

    # --- Step 1: Query Wikidata for each category ---
    print("  [1/4] Querying Wikidata for Big Four winners...", file=sys.stderr)

    records = {}  # key -> record

    for cat in CATEGORIES:
        if cat["short"] == "BNA":
            query = SPARQL_BNA
        else:
            query = SPARQL_WORK_CATEGORY.format(cat_qid=cat["qid"])

        print(f"        Querying {cat['name']}...", file=sys.stderr)
        try:
            rows = sparql_query(query)
            print(f"        -> {len(rows)} rows", file=sys.stderr)
        except Exception as e:
            print(f"        -> Query failed: {e}", file=sys.stderr)
            rows = []

        for r in rows:
            artist_label = val(r, "artistLabel", "")
            artist_qid = val(r, "artistQid", "")
            ceremony_year = val(r, "ceremonyYear")
            work_label = val(r, "workLabel", "") if cat["short"] != "BNA" else ""

            if not artist_label or artist_label.startswith("Q"):
                continue
            if work_label and work_label.startswith("Q"):
                work_label = ""

            year = int(ceremony_year) if ceremony_year else None
            if not year:
                continue

            key = f"{cat['short']}|{artist_label}|{year}"
            if key not in records:
                records[key] = {
                    "category": cat["name"],
                    "categoryShort": cat["short"],
                    "artist": artist_label,
                    "work": work_label,
                    "year": year,
                    "artistWikidata": artist_qid,
                    "artistWikipedia": None,
                    "artistDescription": None,
                    "spotify": None,
                    "spotifyType": cat["spotifyType"],
                }
            else:
                rec = records[key]
                if not rec["work"] and work_label:
                    rec["work"] = work_label
                if not rec["artistWikidata"] and artist_qid:
                    rec["artistWikidata"] = artist_qid

        time.sleep(2)

    print(f"        -> {len(records)} unique entries from Wikidata", file=sys.stderr)

    # --- Step 2: Merge fallback data ---
    print("  [2/4] Merging fallback data...", file=sys.stderr)
    fallback_added = 0
    fallback_updated = 0
    for fb in FALLBACK_DATA:
        key = _rec_key(fb)
        if key not in records:
            records[key] = {
                "category": fb["category"],
                "categoryShort": fb["categoryShort"],
                "artist": fb["artist"],
                "work": fb.get("work", ""),
                "year": fb["year"],
                "artistWikidata": fb.get("artistWikidata", ""),
                "artistWikipedia": None,
                "artistDescription": None,
                "spotify": None,
                "spotifyType": fb["spotifyType"],
            }
            fallback_added += 1
        else:
            rec = records[key]
            if not rec["work"] and fb.get("work"):
                rec["work"] = fb["work"]
                fallback_updated += 1
            if not rec.get("artistWikidata") and fb.get("artistWikidata"):
                rec["artistWikidata"] = fb["artistWikidata"]

    print(f"        -> Added {fallback_added}, updated {fallback_updated} from fallback", file=sys.stderr)

    # Carry forward existing data for resumability
    for key, rec in records.items():
        if key in existing:
            old = existing[key]
            if old.get("spotify") and not rec.get("spotify"):
                rec["spotify"] = old["spotify"]
            if old.get("artistWikipedia") and not rec.get("artistWikipedia"):
                rec["artistWikipedia"] = old["artistWikipedia"]
            if old.get("artistDescription") and not rec.get("artistDescription"):
                rec["artistDescription"] = old["artistDescription"]
            if old.get("artistWikidata") and not rec.get("artistWikidata"):
                rec["artistWikidata"] = old["artistWikidata"]

    # Sort by year, then category order
    cat_order = {"AOTY": 0, "ROTY": 1, "SOTY": 2, "BNA": 3}
    result = sorted(records.values(), key=lambda r: (r["year"] or 9999, cat_order.get(r["categoryShort"], 99)))

    # --- Step 3: Wikipedia URLs + descriptions from Spotify ---
    print("\n  [3/4] Resolving Wikipedia URLs and artist descriptions...", file=sys.stderr)

    # Build Wikipedia URLs from artist names (reliable for well-known artists)
    wiki_set = 0
    for rec in result:
        if not rec.get("artistWikipedia") and rec.get("artist"):
            # Strip "featuring ..." suffixes for cleaner Wikipedia links
            clean = re.split(r'\s+featuring\s+', rec["artist"], flags=re.IGNORECASE)[0]
            clean = re.split(r'\s+and\s+', clean)[0].strip()
            slug = clean.replace(" ", "_")
            rec["artistWikipedia"] = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(slug, safe='/:_')}"
            wiki_set += 1
    print(f"        -> {wiki_set} Wikipedia URLs constructed from artist names", file=sys.stderr)

    # --- Step 4: Spotify ---
    print("\n  [4/4] Looking up Spotify IDs...", file=sys.stderr)
    spotify_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    spotify_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if spotify_id and spotify_secret:
        sp = SpotifyClient(spotify_id, spotify_secret)
        need_spotify = [r for r in result if not r.get("spotify")]
        print(f"        -> {len(need_spotify)} entries need Spotify lookup ({len(result) - len(need_spotify)} cached)", file=sys.stderr)
        found = 0
        for i, rec in enumerate(need_spotify):
            if (i + 1) % 10 == 0 or i == 0:
                print(f"        {i + 1}/{len(need_spotify)}: {rec['artist']} - {rec['work'] or '(artist)'}...", file=sys.stderr)

            sid = None
            if rec["spotifyType"] == "album":
                sid = sp.search_album(rec["work"], rec["artist"])
            elif rec["spotifyType"] == "track":
                sid = sp.search_track(rec["work"], rec["artist"])
            elif rec["spotifyType"] == "artist":
                sid = sp.search_artist(rec["artist"])

            rec["spotify"] = sid
            if sid:
                found += 1
            time.sleep(0.3)
        print(f"        -> Found {found}/{len(need_spotify)} Spotify IDs", file=sys.stderr)
    else:
        print("        -> No Spotify credentials in .env -- skipping", file=sys.stderr)

    # --- Write output ---
    print(f"\n  Writing {OUTFILE}...", file=sys.stderr)

    def js_val(v):
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, str):
            return json.dumps(v, ensure_ascii=False)
        if isinstance(v, list):
            if not v:
                return "[]"
            items = ", ".join(js_val(x) for x in v)
            return f"[{items}]"
        return json.dumps(v, ensure_ascii=False)

    lines = []
    for rec in result:
        obj_parts = []
        obj_parts.append(f"  category: {js_val(rec['category'])}")
        obj_parts.append(f"  categoryShort: {js_val(rec['categoryShort'])}")
        obj_parts.append(f"  artist: {js_val(rec['artist'])}")
        obj_parts.append(f"  work: {js_val(rec.get('work', ''))}")
        obj_parts.append(f"  year: {js_val(rec['year'])}")
        obj_parts.append(f"  artistWikidata: {js_val(rec.get('artistWikidata', ''))}")
        obj_parts.append(f"  artistWikipedia: {js_val(rec.get('artistWikipedia'))}")
        obj_parts.append(f"  artistDescription: {js_val(rec.get('artistDescription'))}")
        obj_parts.append(f"  spotify: {js_val(rec.get('spotify'))}")
        obj_parts.append(f"  spotifyType: {js_val(rec.get('spotifyType', ''))}")
        lines.append("{\n" + ",\n".join(obj_parts) + "\n}")

    js_content = "window.GRAMMYS_DATA = [\n" + ",\n".join(lines) + "\n];\n"
    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write(js_content)

    # --- Summary ---
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Total entries:        {len(result)}", file=sys.stderr)
    years = [r["year"] for r in result if r.get("year")]
    if years:
        print(f"  Year range:           {min(years)} - {max(years)}", file=sys.stderr)
    for cat in CATEGORIES:
        count = sum(1 for r in result if r["categoryShort"] == cat["short"])
        print(f"  {cat['name']:24s}{count}", file=sys.stderr)
    with_spot = sum(1 for r in result if r.get("spotify"))
    print(f"  With Spotify:         {with_spot}", file=sys.stderr)
    with_wiki = sum(1 for r in result if r.get("artistWikipedia"))
    print(f"  With Wikipedia:       {with_wiki}", file=sys.stderr)
    with_desc = sum(1 for r in result if r.get("artistDescription"))
    print(f"  With description:     {with_desc}", file=sys.stderr)
    print(f"\n  Written to {OUTFILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
