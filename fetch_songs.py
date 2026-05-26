#!/usr/bin/env python3
"""
Fetch Academy Award Best Original Song winners from Wikidata SPARQL.
Enrich with Spotify track IDs (via client credentials flow) and Wikipedia URLs.
Output: songs-data.js  (window.SONGS_DATA = [...])

Usage: python3 fetch_songs.py

Spotify credentials are read from .env (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET).
Resumable: if songs-data.js already exists, entries with a non-null spotify field
are skipped on re-run.
"""
import sys, json, os, re, time, base64, urllib.request, urllib.parse, urllib.error, gzip

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
UA = "Crammys/1.0 (flashcard app)"
OUTFILE = "songs-data.js"


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
                print(f"  HTTP {e.code} — sleeping {wait:.1f}s…", file=sys.stderr)
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
                print(f"  HTTP {e.code} — sleeping {wait:.1f}s…", file=sys.stderr)
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


def sparql_query(query):
    url = WIKIDATA_SPARQL + "?" + urllib.parse.urlencode({
        "query": query, "format": "json"
    })
    return http_json(url, timeout=120)["results"]["bindings"]


# ── Wikidata helpers ─────────────────────────────────────────────────
def val(binding, key, default=None):
    """Extract a value string from a SPARQL binding row."""
    v = binding.get(key, {})
    return v.get("value", default) if isinstance(v, dict) else default


def qid_from_uri(uri):
    if not uri:
        return None
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


def year_from_time(t):
    if not t:
        return None
    m = re.match(r'[+\-]?(\d{4})', t)
    return int(m.group(1)) if m else None


# ── Spotify ──────────────────────────────────────────────────────────
class SpotifyClient:
    """Minimal Spotify Web API client using client credentials flow."""

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

    def search_track(self, song_title, artist_name=None):
        """Search Spotify for a track. Returns track ID or None."""
        self._ensure_token()
        q_parts = [f'track:"{song_title}"']
        if artist_name:
            q_parts.append(f'artist:"{artist_name}"')
        q = " ".join(q_parts)
        url = self.SEARCH_URL + "?" + urllib.parse.urlencode({
            "q": q, "type": "track", "limit": "5",
        })
        try:
            resp = http_json(url, headers={
                "Authorization": f"Bearer {self.token}",
            })
        except urllib.error.HTTPError as e:
            if e.code == 401:
                # Token expired, refresh and retry
                self.token = None
                self._ensure_token()
                resp = http_json(url, headers={
                    "Authorization": f"Bearer {self.token}",
                })
            else:
                print(f"    Spotify search error for '{song_title}': HTTP {e.code}", file=sys.stderr)
                return None

        tracks = resp.get("tracks", {}).get("items", [])
        if not tracks:
            # Try a broader search without quotes
            q2 = song_title
            if artist_name:
                q2 += " " + artist_name
            url2 = self.SEARCH_URL + "?" + urllib.parse.urlencode({
                "q": q2, "type": "track", "limit": "5",
            })
            try:
                resp2 = http_json(url2, headers={
                    "Authorization": f"Bearer {self.token}",
                })
                tracks = resp2.get("tracks", {}).get("items", [])
            except Exception:
                pass

        if tracks:
            return tracks[0]["id"]
        return None


# ── Wikipedia URLs via Wikidata sitelinks (batch) ────────────────────
def batch_wikipedia_urls(qids):
    """Given a list of QIDs, return dict qid → wikipedia URL."""
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


# ── Parse existing output for resumability ───────────────────────────
def load_existing():
    """If songs-data.js exists, parse and return dict song_key → record."""
    if not os.path.isfile(OUTFILE):
        return {}
    with open(OUTFILE, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'window\.SONGS_DATA\s*=\s*', text)
    if not m:
        return {}
    array_text = text[m.end():].rstrip().rstrip(";").rstrip()
    # Convert JS object syntax → JSON
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
    return {_song_key(r): r for r in data}


def _song_key(rec):
    return f"{rec.get('song', '')}|{rec.get('year', '')}"


# ── SPARQL query ─────────────────────────────────────────────────────
# Q309314 = Academy Award for Best Original Song
# We query for films whose songs received this award.
SPARQL_SONGS = """
SELECT DISTINCT
  ?song ?songLabel
  ?film ?filmLabel
  ?ceremonyYear
  ?filmYear
  (GROUP_CONCAT(DISTINCT ?songwriterLabel; separator="|||") AS ?songwriters)
  (GROUP_CONCAT(DISTINCT ?performerLabel; separator="|||") AS ?performers)
  ?songQid
WHERE {
  # Songs that received the award
  ?song p:P166 ?awardStmt .
  ?awardStmt ps:P166 wd:Q309314 .

  # Ceremony date (point in time on the award statement)
  OPTIONAL {
    ?awardStmt pq:P585 ?ceremonyDate .
    BIND(YEAR(?ceremonyDate) AS ?ceremonyYear)
  }

  # Film the song is from (P1552 = significant work of, or P361 = part of, or P179 = part of the series)
  OPTIONAL { ?song wdt:P361 ?film . ?film wdt:P31/wdt:P279* wd:Q11424 . }
  OPTIONAL { ?song wdt:P1441 ?film . ?film wdt:P31/wdt:P279* wd:Q11424 . }

  # Film release year
  OPTIONAL { ?film wdt:P577 ?filmDate . BIND(YEAR(?filmDate) AS ?filmYear) }

  # Songwriters / composers
  OPTIONAL {
    { ?song wdt:P86 ?songwriter . } UNION { ?song wdt:P676 ?songwriter . }
    ?songwriter rdfs:label ?songwriterLabel .
    FILTER(LANG(?songwriterLabel) = "en")
  }

  # Performers
  OPTIONAL {
    ?song wdt:P175 ?performer .
    ?performer rdfs:label ?performerLabel .
    FILTER(LANG(?performerLabel) = "en")
  }

  BIND(REPLACE(STR(?song), "http://www.wikidata.org/entity/", "") AS ?songQid)

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
GROUP BY ?song ?songLabel ?film ?filmLabel ?ceremonyYear ?filmYear ?songQid
ORDER BY ?ceremonyYear
"""

# Fallback: query using the award-for-work qualifier (pq:P1686)
SPARQL_SONGS_ALT = """
SELECT DISTINCT
  ?song ?songLabel
  ?film ?filmLabel
  ?ceremonyYear
  ?filmYear
  (GROUP_CONCAT(DISTINCT ?songwriterLabel; separator="|||") AS ?songwriters)
  (GROUP_CONCAT(DISTINCT ?performerLabel; separator="|||") AS ?performers)
  ?songQid
WHERE {
  # Films (or songs) where the award statement uses "for work" (P1686)
  ?entity p:P166 ?awardStmt .
  ?awardStmt ps:P166 wd:Q309314 .
  ?awardStmt pq:P1686 ?song .

  OPTIONAL {
    ?awardStmt pq:P585 ?ceremonyDate .
    BIND(YEAR(?ceremonyDate) AS ?ceremonyYear)
  }

  # The entity receiving the award might be a person; the song is in P1686
  OPTIONAL { ?song wdt:P361 ?film . ?film wdt:P31/wdt:P279* wd:Q11424 . }
  OPTIONAL { ?song wdt:P1441 ?film . ?film wdt:P31/wdt:P279* wd:Q11424 . }

  OPTIONAL { ?film wdt:P577 ?filmDate . BIND(YEAR(?filmDate) AS ?filmYear) }

  OPTIONAL {
    { ?song wdt:P86 ?songwriter . } UNION { ?song wdt:P676 ?songwriter . }
    ?songwriter rdfs:label ?songwriterLabel .
    FILTER(LANG(?songwriterLabel) = "en")
  }

  OPTIONAL {
    ?song wdt:P175 ?performer .
    ?performer rdfs:label ?performerLabel .
    FILTER(LANG(?performerLabel) = "en")
  }

  BIND(REPLACE(STR(?song), "http://www.wikidata.org/entity/", "") AS ?songQid)

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
GROUP BY ?song ?songLabel ?film ?filmLabel ?ceremonyYear ?filmYear ?songQid
ORDER BY ?ceremonyYear
"""


# ── Hardcoded fallback data ──────────────────────────────────────────
# Some winners are poorly modeled in Wikidata. This list fills in gaps.
FALLBACK_DATA = [
    {"song": "The Continental", "film": "The Gay Divorcee", "year": 1935, "filmYear": 1934,
     "songwriters": ["Con Conrad", "Herb Magidson"], "performers": ["Ginger Rogers"], "wikidata": "Q7730754"},
    {"song": "Lullaby of Broadway", "film": "Gold Diggers of 1935", "year": 1936, "filmYear": 1935,
     "songwriters": ["Harry Warren", "Al Dubin"], "performers": ["Wini Shaw"], "wikidata": "Q1872255"},
    {"song": "The Way You Look Tonight", "film": "Swing Time", "year": 1937, "filmYear": 1936,
     "songwriters": ["Jerome Kern", "Dorothy Fields"], "performers": ["Fred Astaire"], "wikidata": "Q1066282"},
    {"song": "Sweet Leilani", "film": "Waikiki Wedding", "year": 1938, "filmYear": 1937,
     "songwriters": ["Harry Owens"], "performers": ["Bing Crosby"], "wikidata": "Q7654271"},
    {"song": "Thanks for the Memory", "film": "The Big Broadcast of 1938", "year": 1939, "filmYear": 1938,
     "songwriters": ["Ralph Rainger", "Leo Robin"], "performers": ["Bob Hope", "Shirley Ross"], "wikidata": "Q2399832"},
    {"song": "Over the Rainbow", "film": "The Wizard of Oz", "year": 1940, "filmYear": 1939,
     "songwriters": ["Harold Arlen", "Yip Harburg"], "performers": ["Judy Garland"], "wikidata": "Q209346"},
    {"song": "When You Wish Upon a Star", "film": "Pinocchio", "year": 1941, "filmYear": 1940,
     "songwriters": ["Leigh Harline", "Ned Washington"], "performers": ["Cliff Edwards"], "wikidata": "Q1140279"},
    {"song": "The Last Time I Saw Paris", "film": "Lady Be Good", "year": 1942, "filmYear": 1941,
     "songwriters": ["Jerome Kern", "Oscar Hammerstein II"], "performers": ["Ann Sothern"], "wikidata": "Q6503576"},
    {"song": "White Christmas", "film": "Holiday Inn", "year": 1943, "filmYear": 1942,
     "songwriters": ["Irving Berlin"], "performers": ["Bing Crosby"], "wikidata": "Q207927"},
    {"song": "You'll Never Know", "film": "Hello, Frisco, Hello", "year": 1944, "filmYear": 1943,
     "songwriters": ["Harry Warren", "Mack Gordon"], "performers": ["Alice Faye"], "wikidata": "Q8055759"},
    {"song": "Swinging on a Star", "film": "Going My Way", "year": 1945, "filmYear": 1944,
     "songwriters": ["Jimmy Van Heusen", "Johnny Burke"], "performers": ["Bing Crosby"], "wikidata": "Q3511236"},
    {"song": "It Might as Well Be Spring", "film": "State Fair", "year": 1946, "filmYear": 1945,
     "songwriters": ["Richard Rodgers", "Oscar Hammerstein II"], "performers": ["Louanne Hogan"], "wikidata": "Q6090099"},
    {"song": "On the Atchison, Topeka and the Santa Fe", "film": "The Harvey Girls", "year": 1947, "filmYear": 1946,
     "songwriters": ["Harry Warren", "Johnny Mercer"], "performers": ["Judy Garland"], "wikidata": "Q7090254"},
    {"song": "Zip-a-Dee-Doo-Dah", "film": "Song of the South", "year": 1948, "filmYear": 1946,
     "songwriters": ["Allie Wrubel", "Ray Gilbert"], "performers": ["James Baskett"], "wikidata": "Q2002948"},
    {"song": "Buttons and Bows", "film": "The Paleface", "year": 1949, "filmYear": 1948,
     "songwriters": ["Jay Livingston", "Ray Evans"], "performers": ["Bob Hope"], "wikidata": "Q4001968"},
    {"song": "Baby, It's Cold Outside", "film": "Neptune's Daughter", "year": 1950, "filmYear": 1949,
     "songwriters": ["Frank Loesser"], "performers": ["Esther Williams", "Ricardo Montalban"], "wikidata": "Q2878523"},
    {"song": "Mona Lisa", "film": "Captain Carey, U.S.A.", "year": 1951, "filmYear": 1950,
     "songwriters": ["Jay Livingston", "Ray Evans"], "performers": ["Nat King Cole"], "wikidata": "Q1948042"},
    {"song": "In the Cool, Cool, Cool of the Evening", "film": "Here Comes the Groom", "year": 1952, "filmYear": 1951,
     "songwriters": ["Hoagy Carmichael", "Johnny Mercer"], "performers": ["Bing Crosby", "Jane Wyman"], "wikidata": "Q6016908"},
    {"song": "High Noon (Do Not Forsake Me, Oh My Darlin')", "film": "High Noon", "year": 1953, "filmYear": 1952,
     "songwriters": ["Dimitri Tiomkin", "Ned Washington"], "performers": ["Tex Ritter"], "wikidata": "Q1618096"},
    {"song": "Secret Love", "film": "Calamity Jane", "year": 1954, "filmYear": 1953,
     "songwriters": ["Sammy Fain", "Paul Francis Webster"], "performers": ["Doris Day"], "wikidata": "Q3476195"},
    {"song": "Three Coins in the Fountain", "film": "Three Coins in the Fountain", "year": 1955, "filmYear": 1954,
     "songwriters": ["Jule Styne", "Sammy Cahn"], "performers": ["Frank Sinatra"], "wikidata": "Q2329994"},
    {"song": "Love Is a Many-Splendored Thing", "film": "Love Is a Many-Splendored Thing", "year": 1956, "filmYear": 1955,
     "songwriters": ["Sammy Fain", "Paul Francis Webster"], "performers": ["The Four Aces"], "wikidata": "Q6538757"},
    {"song": "Whatever Will Be, Will Be (Que Sera, Sera)", "film": "The Man Who Knew Too Much", "year": 1957, "filmYear": 1956,
     "songwriters": ["Jay Livingston", "Ray Evans"], "performers": ["Doris Day"], "wikidata": "Q913373"},
    {"song": "All the Way", "film": "The Joker Is Wild", "year": 1958, "filmYear": 1957,
     "songwriters": ["Jimmy Van Heusen", "Sammy Cahn"], "performers": ["Frank Sinatra"], "wikidata": "Q4726268"},
    {"song": "Gigi", "film": "Gigi", "year": 1959, "filmYear": 1958,
     "songwriters": ["Frederick Loewe", "Alan Jay Lerner"], "performers": ["Louis Jourdan"], "wikidata": "Q1524823"},
    {"song": "High Hopes", "film": "A Hole in the Head", "year": 1960, "filmYear": 1959,
     "songwriters": ["Jimmy Van Heusen", "Sammy Cahn"], "performers": ["Frank Sinatra"], "wikidata": "Q3785174"},
    {"song": "Never on Sunday", "film": "Never on Sunday", "year": 1961, "filmYear": 1960,
     "songwriters": ["Manos Hadjidakis"], "performers": ["Melina Mercouri"], "wikidata": "Q3338067"},
    {"song": "Moon River", "film": "Breakfast at Tiffany's", "year": 1962, "filmYear": 1961,
     "songwriters": ["Henry Mancini", "Johnny Mercer"], "performers": ["Audrey Hepburn"], "wikidata": "Q854971"},
    {"song": "Days of Wine and Roses", "film": "Days of Wine and Roses", "year": 1963, "filmYear": 1962,
     "songwriters": ["Henry Mancini", "Johnny Mercer"], "performers": ["Andy Williams"], "wikidata": "Q3018082"},
    {"song": "Call Me Irresponsible", "film": "Papa's Delicate Condition", "year": 1964, "filmYear": 1963,
     "songwriters": ["Jimmy Van Heusen", "Sammy Cahn"], "performers": ["Jackie Gleason"], "wikidata": "Q5023026"},
    {"song": "Chim Chim Cher-ee", "film": "Mary Poppins", "year": 1965, "filmYear": 1964,
     "songwriters": ["Richard M. Sherman", "Robert B. Sherman"], "performers": ["Dick Van Dyke", "Julie Andrews"], "wikidata": "Q1073399"},
    {"song": "The Shadow of Your Smile", "film": "The Sandpiper", "year": 1966, "filmYear": 1965,
     "songwriters": ["Johnny Mandel", "Paul Francis Webster"], "performers": ["Tony Bennett"], "wikidata": "Q3523429"},
    {"song": "Born Free", "film": "Born Free", "year": 1967, "filmYear": 1966,
     "songwriters": ["John Barry", "Don Black"], "performers": ["Matt Monro"], "wikidata": "Q2665620"},
    {"song": "Talk to the Animals", "film": "Doctor Dolittle", "year": 1968, "filmYear": 1967,
     "songwriters": ["Leslie Bricusse"], "performers": ["Rex Harrison"], "wikidata": "Q7680236"},
    {"song": "The Windmills of Your Mind", "film": "The Thomas Crown Affair", "year": 1969, "filmYear": 1968,
     "songwriters": ["Michel Legrand", "Alan Bergman", "Marilyn Bergman"], "performers": ["Noel Harrison"], "wikidata": "Q1753757"},
    {"song": "Raindrops Keep Fallin' on My Head", "film": "Butch Cassidy and the Sundance Kid", "year": 1970, "filmYear": 1969,
     "songwriters": ["Burt Bacharach", "Hal David"], "performers": ["B.J. Thomas"], "wikidata": "Q1501922"},
    {"song": "For All We Know", "film": "Lovers and Other Strangers", "year": 1971, "filmYear": 1970,
     "songwriters": ["Fred Karlin", "Robb Royer", "James Griffin"], "performers": ["Larry Meredith"], "wikidata": "Q5466139"},
    {"song": "Theme from Shaft", "film": "Shaft", "year": 1972, "filmYear": 1971,
     "songwriters": ["Isaac Hayes"], "performers": ["Isaac Hayes"], "wikidata": "Q3987260"},
    {"song": "The Morning After", "film": "The Poseidon Adventure", "year": 1973, "filmYear": 1972,
     "songwriters": ["Al Kasha", "Joel Hirschhorn"], "performers": ["Maureen McGovern"], "wikidata": "Q3521912"},
    {"song": "The Way We Were", "film": "The Way We Were", "year": 1974, "filmYear": 1973,
     "songwriters": ["Marvin Hamlisch", "Alan Bergman", "Marilyn Bergman"], "performers": ["Barbra Streisand"], "wikidata": "Q2538389"},
    {"song": "We May Never Love Like This Again", "film": "The Towering Inferno", "year": 1975, "filmYear": 1974,
     "songwriters": ["Al Kasha", "Joel Hirschhorn"], "performers": ["Maureen McGovern"], "wikidata": "Q7977090"},
    {"song": "I'm Easy", "film": "Nashville", "year": 1976, "filmYear": 1975,
     "songwriters": ["Keith Carradine"], "performers": ["Keith Carradine"], "wikidata": "Q5918918"},
    {"song": "Evergreen", "film": "A Star Is Born", "year": 1977, "filmYear": 1976,
     "songwriters": ["Barbra Streisand", "Paul Williams"], "performers": ["Barbra Streisand"], "wikidata": "Q5417407"},
    {"song": "You Light Up My Life", "film": "You Light Up My Life", "year": 1978, "filmYear": 1977,
     "songwriters": ["Joseph Brooks"], "performers": ["Debby Boone"], "wikidata": "Q8055530"},
    {"song": "Last Dance", "film": "Thank God It's Friday", "year": 1979, "filmYear": 1978,
     "songwriters": ["Paul Jabara"], "performers": ["Donna Summer"], "wikidata": "Q6495758"},
    {"song": "It Goes Like It Goes", "film": "Norma Rae", "year": 1980, "filmYear": 1979,
     "songwriters": ["David Shire", "Norman Gimbel"], "performers": ["Jennifer Warnes"], "wikidata": "Q6090029"},
    {"song": "Fame", "film": "Fame", "year": 1981, "filmYear": 1980,
     "songwriters": ["Michael Gore", "Dean Pitchford"], "performers": ["Irene Cara"], "wikidata": "Q1140499"},
    {"song": "Arthur's Theme (Best That You Can Do)", "film": "Arthur", "year": 1982, "filmYear": 1981,
     "songwriters": ["Burt Bacharach", "Carole Bayer Sager", "Christopher Cross", "Peter Allen"], "performers": ["Christopher Cross"], "wikidata": "Q4799230"},
    {"song": "Up Where We Belong", "film": "An Officer and a Gentleman", "year": 1983, "filmYear": 1982,
     "songwriters": ["Jack Nitzsche", "Buffy Sainte-Marie", "Will Jennings"], "performers": ["Joe Cocker", "Jennifer Warnes"], "wikidata": "Q2497917"},
    {"song": "Flashdance... What a Feeling", "film": "Flashdance", "year": 1984, "filmYear": 1983,
     "songwriters": ["Giorgio Moroder", "Keith Forsey", "Irene Cara"], "performers": ["Irene Cara"], "wikidata": "Q1434095"},
    {"song": "I Just Called to Say I Love You", "film": "The Woman in Red", "year": 1985, "filmYear": 1984,
     "songwriters": ["Stevie Wonder"], "performers": ["Stevie Wonder"], "wikidata": "Q1323577"},
    {"song": "Say You, Say Me", "film": "White Nights", "year": 1986, "filmYear": 1985,
     "songwriters": ["Lionel Richie"], "performers": ["Lionel Richie"], "wikidata": "Q2040064"},
    {"song": "Take My Breath Away", "film": "Top Gun", "year": 1987, "filmYear": 1986,
     "songwriters": ["Giorgio Moroder", "Tom Whitlock"], "performers": ["Berlin"], "wikidata": "Q1073369"},
    {"song": "(I've Had) The Time of My Life", "film": "Dirty Dancing", "year": 1988, "filmYear": 1987,
     "songwriters": ["Franke Previte", "John DeNicola", "Donald Markowitz"], "performers": ["Bill Medley", "Jennifer Warnes"], "wikidata": "Q1069831"},
    {"song": "Let the River Run", "film": "Working Girl", "year": 1989, "filmYear": 1988,
     "songwriters": ["Carly Simon"], "performers": ["Carly Simon"], "wikidata": "Q1822527"},
    {"song": "Under the Sea", "film": "The Little Mermaid", "year": 1990, "filmYear": 1989,
     "songwriters": ["Alan Menken", "Howard Ashman"], "performers": ["Samuel E. Wright"], "wikidata": "Q577775"},
    {"song": "Sooner or Later (I Always Get My Man)", "film": "Dick Tracy", "year": 1991, "filmYear": 1990,
     "songwriters": ["Stephen Sondheim"], "performers": ["Madonna"], "wikidata": "Q3488863"},
    {"song": "Beauty and the Beast", "film": "Beauty and the Beast", "year": 1992, "filmYear": 1991,
     "songwriters": ["Alan Menken", "Howard Ashman"], "performers": ["Celine Dion", "Peabo Bryson"], "wikidata": "Q2334872"},
    {"song": "A Whole New World", "film": "Aladdin", "year": 1993, "filmYear": 1992,
     "songwriters": ["Alan Menken", "Tim Rice"], "performers": ["Brad Kane", "Lea Salonga"], "wikidata": "Q1855902"},
    {"song": "Streets of Philadelphia", "film": "Philadelphia", "year": 1994, "filmYear": 1993,
     "songwriters": ["Bruce Springsteen"], "performers": ["Bruce Springsteen"], "wikidata": "Q1432236"},
    {"song": "Can You Feel the Love Tonight", "film": "The Lion King", "year": 1995, "filmYear": 1994,
     "songwriters": ["Elton John", "Tim Rice"], "performers": ["Elton John"], "wikidata": "Q1032927"},
    {"song": "Colors of the Wind", "film": "Pocahontas", "year": 1996, "filmYear": 1995,
     "songwriters": ["Alan Menken", "Stephen Schwartz"], "performers": ["Vanessa Williams"], "wikidata": "Q2993233"},
    {"song": "You Must Love Me", "film": "Evita", "year": 1997, "filmYear": 1996,
     "songwriters": ["Andrew Lloyd Webber", "Tim Rice"], "performers": ["Madonna"], "wikidata": "Q2606093"},
    {"song": "My Heart Will Go On", "film": "Titanic", "year": 1998, "filmYear": 1997,
     "songwriters": ["James Horner", "Will Jennings"], "performers": ["Celine Dion"], "wikidata": "Q189505"},
    {"song": "When You Believe", "film": "The Prince of Egypt", "year": 1999, "filmYear": 1998,
     "songwriters": ["Stephen Schwartz"], "performers": ["Mariah Carey", "Whitney Houston"], "wikidata": "Q2564289"},
    {"song": "You'll Be in My Heart", "film": "Tarzan", "year": 2000, "filmYear": 1999,
     "songwriters": ["Phil Collins"], "performers": ["Phil Collins"], "wikidata": "Q2606147"},
    {"song": "Things Have Changed", "film": "Wonder Boys", "year": 2001, "filmYear": 2000,
     "songwriters": ["Bob Dylan"], "performers": ["Bob Dylan"], "wikidata": "Q7784455"},
    {"song": "If I Didn't Have You", "film": "Monsters, Inc.", "year": 2002, "filmYear": 2001,
     "songwriters": ["Randy Newman"], "performers": ["Billy Crystal", "John Goodman"], "wikidata": "Q1569714"},
    {"song": "Lose Yourself", "film": "8 Mile", "year": 2003, "filmYear": 2002,
     "songwriters": ["Eminem", "Jeff Bass", "Luis Resto"], "performers": ["Eminem"], "wikidata": "Q483882"},
    {"song": "Into the West", "film": "The Lord of the Rings: The Return of the King", "year": 2004, "filmYear": 2003,
     "songwriters": ["Annie Lennox", "Fran Walsh", "Howard Shore"], "performers": ["Annie Lennox"], "wikidata": "Q945735"},
    {"song": "Al otro lado del río", "film": "The Motorcycle Diaries", "year": 2005, "filmYear": 2004,
     "songwriters": ["Jorge Drexler"], "performers": ["Jorge Drexler"], "wikidata": "Q2831625"},
    {"song": "It's Hard Out Here for a Pimp", "film": "Hustle & Flow", "year": 2006, "filmYear": 2005,
     "songwriters": ["Jordan Houston", "Cedric Coleman", "Paul Beauregard"], "performers": ["Three 6 Mafia"], "wikidata": "Q1546927"},
    {"song": "I Need to Wake Up", "film": "An Inconvenient Truth", "year": 2007, "filmYear": 2006,
     "songwriters": ["Melissa Etheridge"], "performers": ["Melissa Etheridge"], "wikidata": "Q6078012"},
    {"song": "Falling Slowly", "film": "Once", "year": 2008, "filmYear": 2007,
     "songwriters": ["Glen Hansard", "Markéta Irglová"], "performers": ["Glen Hansard", "Markéta Irglová"], "wikidata": "Q1396268"},
    {"song": "Jai Ho", "film": "Slumdog Millionaire", "year": 2009, "filmYear": 2008,
     "songwriters": ["A. R. Rahman", "Gulzar"], "performers": ["Sukhwinder Singh", "Tanvi Shah", "Mahalaxmi Iyer", "Vijay Prakash"], "wikidata": "Q1396254"},
    {"song": "The Weary Kind", "film": "Crazy Heart", "year": 2010, "filmYear": 2009,
     "songwriters": ["Ryan Bingham", "T Bone Burnett"], "performers": ["Ryan Bingham"], "wikidata": "Q3524015"},
    {"song": "We Belong Together", "film": "Toy Story 3", "year": 2011, "filmYear": 2010,
     "songwriters": ["Randy Newman"], "performers": ["Randy Newman"], "wikidata": "Q1552850"},
    {"song": "Man or Muppet", "film": "The Muppets", "year": 2012, "filmYear": 2011,
     "songwriters": ["Bret McKenzie"], "performers": ["Jason Segel", "Walter"], "wikidata": "Q1621399"},
    {"song": "Skyfall", "film": "Skyfall", "year": 2013, "filmYear": 2012,
     "songwriters": ["Adele", "Paul Epworth"], "performers": ["Adele"], "wikidata": "Q2997612"},
    {"song": "Let It Go", "film": "Frozen", "year": 2014, "filmYear": 2013,
     "songwriters": ["Kristen Anderson-Lopez", "Robert Lopez"], "performers": ["Idina Menzel"], "wikidata": "Q15055360"},
    {"song": "Glory", "film": "Selma", "year": 2015, "filmYear": 2014,
     "songwriters": ["Common", "John Legend", "Che Smith"], "performers": ["Common", "John Legend"], "wikidata": "Q18703030"},
    {"song": "Writing's on the Wall", "film": "Spectre", "year": 2016, "filmYear": 2015,
     "songwriters": ["Sam Smith", "Jimmy Napes"], "performers": ["Sam Smith"], "wikidata": "Q20899840"},
    {"song": "City of Stars", "film": "La La Land", "year": 2017, "filmYear": 2016,
     "songwriters": ["Justin Hurwitz", "Benj Pasek", "Justin Paul"], "performers": ["Ryan Gosling", "Emma Stone"], "wikidata": "Q27888326"},
    {"song": "Remember Me", "film": "Coco", "year": 2018, "filmYear": 2017,
     "songwriters": ["Kristen Anderson-Lopez", "Robert Lopez"], "performers": ["Anthony Gonzalez"], "wikidata": "Q37107779"},
    {"song": "Shallow", "film": "A Star Is Born", "year": 2019, "filmYear": 2018,
     "songwriters": ["Lady Gaga", "Mark Ronson", "Anthony Rossomando", "Andrew Wyatt"], "performers": ["Lady Gaga", "Bradley Cooper"], "wikidata": "Q56556519"},
    {"song": "(I'm Gonna) Love Me Again", "film": "Rocketman", "year": 2020, "filmYear": 2019,
     "songwriters": ["Elton John", "Bernie Taupin"], "performers": ["Elton John"], "wikidata": "Q65081885"},
    {"song": "Fight for You", "film": "Judas and the Black Messiah", "year": 2021, "filmYear": 2021,
     "songwriters": ["H.E.R.", "Dernst Emile II", "Tiara Thomas"], "performers": ["H.E.R."], "wikidata": "Q104925291"},
    {"song": "No Time to Die", "film": "No Time to Die", "year": 2022, "filmYear": 2021,
     "songwriters": ["Billie Eilish", "Finneas O'Connell"], "performers": ["Billie Eilish"], "wikidata": "Q87416078"},
    {"song": "Naatu Naatu", "film": "RRR", "year": 2023, "filmYear": 2022,
     "songwriters": ["M. M. Keeravani", "Chandrabose"], "performers": ["Rahul Sipligunj", "Kaala Bhairava"], "wikidata": "Q109936888"},
    {"song": "What Was I Made For?", "film": "Barbie", "year": 2024, "filmYear": 2023,
     "songwriters": ["Billie Eilish", "Finneas O'Connell"], "performers": ["Billie Eilish"], "wikidata": "Q117155553"},
    {"song": "El Mal", "film": "Emilia Pérez", "year": 2025, "filmYear": 2024,
     "songwriters": ["Camille", "Clément Ducol"], "performers": ["Zoe Saldaña"], "wikidata": "Q131576779"},
]


# ── Main ─────────────────────────────────────────────────────────────
def main():
    load_dotenv()

    print("Fetching Academy Award Best Original Song winners…\n", file=sys.stderr)

    # Load existing data for resumability
    existing = load_existing()
    if existing:
        print(f"  Found {len(existing)} existing entries in {OUTFILE}", file=sys.stderr)

    # --- Step 1: Query Wikidata ---
    print("  [1/4] Querying Wikidata for Best Original Song winners…", file=sys.stderr)
    try:
        rows = sparql_query(SPARQL_SONGS)
        print(f"        → {len(rows)} rows from primary query", file=sys.stderr)
    except Exception as e:
        print(f"        → Primary query failed: {e}", file=sys.stderr)
        rows = []

    time.sleep(2)

    try:
        alt_rows = sparql_query(SPARQL_SONGS_ALT)
        print(f"        → {len(alt_rows)} rows from alternate query", file=sys.stderr)
    except Exception as e:
        print(f"        → Alternate query failed: {e}", file=sys.stderr)
        alt_rows = []

    all_rows = rows + alt_rows

    # --- Step 2: Build song records from Wikidata ---
    print("  [2/4] Building song records…", file=sys.stderr)
    songs = {}  # keyed by song_key

    for r in all_rows:
        song_label = val(r, "songLabel", "")
        film_label = val(r, "filmLabel", "")
        ceremony_year = val(r, "ceremonyYear")
        film_year = val(r, "filmYear")
        songwriters_str = val(r, "songwriters", "")
        performers_str = val(r, "performers", "")
        song_qid = val(r, "songQid", "")

        if not song_label or song_label.startswith("Q"):
            continue

        year = int(ceremony_year) if ceremony_year else None
        fy = int(film_year) if film_year else (year - 1 if year else None)

        songwriters = sorted(set(s.strip() for s in songwriters_str.split("|||") if s.strip())) if songwriters_str else []
        performers = sorted(set(s.strip() for s in performers_str.split("|||") if s.strip())) if performers_str else []

        key = f"{song_label}|{year}"
        if key not in songs:
            songs[key] = {
                "song": song_label,
                "film": film_label if film_label and not film_label.startswith("Q") else "",
                "year": year,
                "filmYear": fy,
                "songwriters": songwriters,
                "performers": performers,
                "spotify": None,
                "wikipedia": None,
                "wikidata": song_qid,
            }
        else:
            # Merge in any missing data
            rec = songs[key]
            if not rec["film"] and film_label and not film_label.startswith("Q"):
                rec["film"] = film_label
            if not rec["filmYear"] and fy:
                rec["filmYear"] = fy
            if songwriters and not rec["songwriters"]:
                rec["songwriters"] = songwriters
            elif songwriters:
                rec["songwriters"] = sorted(set(rec["songwriters"] + songwriters))
            if performers and not rec["performers"]:
                rec["performers"] = performers
            elif performers:
                rec["performers"] = sorted(set(rec["performers"] + performers))
            if song_qid and not rec["wikidata"]:
                rec["wikidata"] = song_qid

    print(f"        → {len(songs)} unique songs from Wikidata", file=sys.stderr)

    # --- Merge fallback data ---
    print("  [3/4] Merging fallback data for historical winners…", file=sys.stderr)
    fallback_added = 0
    fallback_updated = 0
    for fb in FALLBACK_DATA:
        key = _song_key(fb)
        if key not in songs:
            songs[key] = {
                "song": fb["song"],
                "film": fb["film"],
                "year": fb["year"],
                "filmYear": fb.get("filmYear"),
                "songwriters": fb.get("songwriters", []),
                "performers": fb.get("performers", []),
                "spotify": None,
                "wikipedia": None,
                "wikidata": fb.get("wikidata", ""),
            }
            fallback_added += 1
        else:
            rec = songs[key]
            if not rec["film"] and fb.get("film"):
                rec["film"] = fb["film"]
                fallback_updated += 1
            if not rec["filmYear"] and fb.get("filmYear"):
                rec["filmYear"] = fb["filmYear"]
            if not rec["songwriters"] and fb.get("songwriters"):
                rec["songwriters"] = fb["songwriters"]
                fallback_updated += 1
            if not rec["performers"] and fb.get("performers"):
                rec["performers"] = fb["performers"]
                fallback_updated += 1
            if not rec["wikidata"] and fb.get("wikidata"):
                rec["wikidata"] = fb["wikidata"]

    print(f"        → Added {fallback_added}, updated {fallback_updated} from fallback", file=sys.stderr)

    # Carry forward existing data (spotify, wikipedia) for resumability
    for key, rec in songs.items():
        if key in existing:
            old = existing[key]
            if old.get("spotify") and not rec.get("spotify"):
                rec["spotify"] = old["spotify"]
            if old.get("wikipedia") and not rec.get("wikipedia"):
                rec["wikipedia"] = old["wikipedia"]

    # Sort by year
    result = sorted(songs.values(), key=lambda r: (r["year"] or 9999, r["song"]))

    # --- Wikipedia URLs ---
    print("\n  Fetching Wikipedia URLs via Wikidata sitelinks…", file=sys.stderr)
    qids_needing_wiki = [r["wikidata"] for r in result if r.get("wikidata") and not r.get("wikipedia")]
    if qids_needing_wiki:
        wiki_urls = batch_wikipedia_urls(qids_needing_wiki)
        print(f"        → {len(wiki_urls)} Wikipedia URLs resolved", file=sys.stderr)
        for rec in result:
            if rec.get("wikidata") and not rec.get("wikipedia"):
                rec["wikipedia"] = wiki_urls.get(rec["wikidata"])
    else:
        print("        → All Wikipedia URLs already cached", file=sys.stderr)

    # --- Spotify ---
    print("\n  [4/4] Looking up Spotify track IDs…", file=sys.stderr)
    spotify_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
    spotify_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
    if spotify_id and spotify_secret:
        sp = SpotifyClient(spotify_id, spotify_secret)
        need_spotify = [r for r in result if not r.get("spotify")]
        print(f"        → {len(need_spotify)} songs need Spotify lookup ({len(result) - len(need_spotify)} cached)", file=sys.stderr)
        found = 0
        for i, rec in enumerate(need_spotify):
            if (i + 1) % 10 == 0 or i == 0:
                print(f"        {i + 1}/{len(need_spotify)}: {rec['song']}…", file=sys.stderr)
            # Try with first performer
            performer = rec["performers"][0] if rec.get("performers") else None
            track_id = sp.search_track(rec["song"], performer)
            if not track_id and rec.get("songwriters"):
                # Try with first songwriter
                track_id = sp.search_track(rec["song"], rec["songwriters"][0])
            if not track_id:
                # Try song title only
                track_id = sp.search_track(rec["song"])
            rec["spotify"] = track_id
            if track_id:
                found += 1
            time.sleep(0.3)  # Rate limiting
        print(f"        → Found {found}/{len(need_spotify)} Spotify tracks", file=sys.stderr)
    else:
        print("        → No Spotify credentials in .env — skipping", file=sys.stderr)

    # --- Write output ---
    print(f"\n  Writing {OUTFILE}…", file=sys.stderr)

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
        obj_parts.append(f"  song: {js_val(rec['song'])}")
        obj_parts.append(f"  film: {js_val(rec['film'])}")
        obj_parts.append(f"  year: {js_val(rec['year'])}")
        obj_parts.append(f"  filmYear: {js_val(rec.get('filmYear'))}")
        obj_parts.append(f"  songwriters: {js_val(rec.get('songwriters', []))}")
        obj_parts.append(f"  performers: {js_val(rec.get('performers', []))}")
        obj_parts.append(f"  spotify: {js_val(rec.get('spotify'))}")
        obj_parts.append(f"  wikipedia: {js_val(rec.get('wikipedia'))}")
        obj_parts.append(f"  wikidata: {js_val(rec.get('wikidata', ''))}")
        lines.append("{\n" + ",\n".join(obj_parts) + "\n}")

    js_content = "window.SONGS_DATA = [\n" + ",\n".join(lines) + "\n];\n"
    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write(js_content)

    # --- Summary ---
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Total songs:          {len(result)}", file=sys.stderr)
    years = [r["year"] for r in result if r.get("year")]
    if years:
        print(f"  Year range:           {min(years)} – {max(years)}", file=sys.stderr)
    with_film = sum(1 for r in result if r.get("film"))
    print(f"  With film:            {with_film}", file=sys.stderr)
    with_sw = sum(1 for r in result if r.get("songwriters"))
    print(f"  With songwriters:     {with_sw}", file=sys.stderr)
    with_perf = sum(1 for r in result if r.get("performers"))
    print(f"  With performers:      {with_perf}", file=sys.stderr)
    with_spot = sum(1 for r in result if r.get("spotify"))
    print(f"  With Spotify:         {with_spot}", file=sys.stderr)
    with_wiki = sum(1 for r in result if r.get("wikipedia"))
    print(f"  With Wikipedia:       {with_wiki}", file=sys.stderr)
    print(f"\n  Written to {OUTFILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
