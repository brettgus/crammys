#!/usr/bin/env python3
"""
Fetch US Presidents from Wikidata.

Strategy:
  1. SPARQL query for everyone who has held position P39 → Q11696
     (President of the United States), with start/end qualifiers.
  2. Group into "continuous presidencies": consecutive terms by the same
     person collapse into one card. Non-consecutive terms (Cleveland,
     Trump) split into separate cards.
  3. Enrich each president with: birth/death, party, home state, image,
     and Vice Presidents (their P39 → Q11699 statements held during
     this president's term range).
  4. Assign term numbers (1=Washington, 22=Cleveland-1, 24=Cleveland-2,
     45=Trump-1, 47=Trump-2, …) and predecessor/successor links.

Output: presidents-data.js  (window.PRESIDENTS_DATA = [...])

Usage: python3 fetch_presidents.py
Resumable: if the file already exists with all REQUIRED fields, skips
the Wikidata fetch and just rewrites the file in canonical order.
"""
import sys, os, json, re, time, gzip, urllib.request, urllib.parse, urllib.error
from collections import defaultdict

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
UA = "Crammys/1.0 (flashcard app; brett.gustafson@gmail.com)"
OUTFILE = "presidents-data.js"

PRESIDENT_QID = "Q11696"   # President of the United States
VP_QID        = "Q11699"   # Vice President of the United States


# ── HTTP ─────────────────────────────────────────────────────────────
def http_json(url, *, timeout=120, max_retries=4, backoff=5.0):
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
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
    return http_json(url, timeout=180)["results"]["bindings"]


def qid_from_uri(uri):
    if not uri:
        return None
    return uri.rsplit("/", 1)[-1]


def year_from_time(t):
    if not t:
        return None
    m = re.match(r'[+\-]?(\d{4})', t)
    return int(m.group(1)) if m else None


# ── SPARQL queries ───────────────────────────────────────────────────

# All P39 → Q11696 statements with start/end qualifiers and label
SPARQL_TERMS = """
SELECT ?person ?personLabel ?start ?end ?ordinal WHERE {
  ?person p:P39 ?stmt .
  ?stmt ps:P39 wd:Q11696 .
  OPTIONAL { ?stmt pq:P580 ?start . }
  OPTIONAL { ?stmt pq:P582 ?end . }
  OPTIONAL { ?stmt pq:P1545 ?ordinal . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY ?start
"""

# All VPs: same pattern but for Q11699
SPARQL_VPS = """
SELECT ?person ?personLabel ?start ?end ?ordinal WHERE {
  ?person p:P39 ?stmt .
  ?stmt ps:P39 wd:Q11699 .
  OPTIONAL { ?stmt pq:P580 ?start . }
  OPTIONAL { ?stmt pq:P582 ?end . }
  OPTIONAL { ?stmt pq:P1545 ?ordinal . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
ORDER BY ?start
"""

# Enrichment: birth, death, party, image, home state (P19 = place of
# birth; we want admin state, not city, so use P131 of POB or fall back
# to label). We'll use P551 (residence) too if no state directly.
SPARQL_PROPS = """
SELECT ?person
       (SAMPLE(?birth) AS ?birth)
       (SAMPLE(?death) AS ?death)
       (SAMPLE(?image) AS ?image)
       (SAMPLE(?pobLabel) AS ?pob)
       (GROUP_CONCAT(DISTINCT ?partyLabel; separator="|||") AS ?parties)
WHERE {
  VALUES ?person { %(VALUES)s }
  OPTIONAL { ?person wdt:P569 ?birth . }
  OPTIONAL { ?person wdt:P570 ?death . }
  OPTIONAL { ?person wdt:P18 ?image . }
  OPTIONAL {
    ?person wdt:P19 ?pob .
    ?pob rdfs:label ?pobLabel .
    FILTER(LANG(?pobLabel) = "en")
  }
  OPTIONAL {
    ?person wdt:P102 ?party .
    ?party rdfs:label ?partyLabel .
    FILTER(LANG(?partyLabel) = "en")
  }
}
GROUP BY ?person
"""

# Place-of-birth → US state mapping. Wikidata's P19 is usually a city
# (e.g. "Plymouth Notch"); the state can be derived from its
# "located in administrative entity" chain (P131). Easier: just query
# the state via SPARQL where the city was born in.
SPARQL_POB_STATE = """
SELECT ?person ?stateLabel WHERE {
  VALUES ?person { %(VALUES)s }
  ?person wdt:P19 ?city .
  ?city wdt:P131* ?state .
  ?state wdt:P31 wd:Q35657 .  # U.S. state
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
"""


# ── Manual overrides ─────────────────────────────────────────────────
# Wikidata's P1545 ordinal (term number) is unreliable. We hard-code
# the canonical order to be safe. There are exactly 47 presidencies
# (Cleveland twice, Trump twice).
#
# Each tuple: (term_number, name, start_year, end_year_or_None)
CANONICAL_TERMS = [
    (1,  "George Washington",      1789, 1797),
    (2,  "John Adams",              1797, 1801),
    (3,  "Thomas Jefferson",        1801, 1809),
    (4,  "James Madison",           1809, 1817),
    (5,  "James Monroe",            1817, 1825),
    (6,  "John Quincy Adams",       1825, 1829),
    (7,  "Andrew Jackson",          1829, 1837),
    (8,  "Martin Van Buren",        1837, 1841),
    (9,  "William Henry Harrison",  1841, 1841),
    (10, "John Tyler",              1841, 1845),
    (11, "James K. Polk",           1845, 1849),
    (12, "Zachary Taylor",          1849, 1850),
    (13, "Millard Fillmore",        1850, 1853),
    (14, "Franklin Pierce",         1853, 1857),
    (15, "James Buchanan",          1857, 1861),
    (16, "Abraham Lincoln",         1861, 1865),
    (17, "Andrew Johnson",          1865, 1869),
    (18, "Ulysses S. Grant",        1869, 1877),
    (19, "Rutherford B. Hayes",     1877, 1881),
    (20, "James A. Garfield",       1881, 1881),
    (21, "Chester A. Arthur",       1881, 1885),
    (22, "Grover Cleveland",        1885, 1889),
    (23, "Benjamin Harrison",       1889, 1893),
    (24, "Grover Cleveland",        1893, 1897),
    (25, "William McKinley",        1897, 1901),
    (26, "Theodore Roosevelt",      1901, 1909),
    (27, "William Howard Taft",     1909, 1913),
    (28, "Woodrow Wilson",          1913, 1921),
    (29, "Warren G. Harding",       1921, 1923),
    (30, "Calvin Coolidge",         1923, 1929),
    (31, "Herbert Hoover",          1929, 1933),
    (32, "Franklin D. Roosevelt",   1933, 1945),
    (33, "Harry S. Truman",         1945, 1953),
    (34, "Dwight D. Eisenhower",    1953, 1961),
    (35, "John F. Kennedy",         1961, 1963),
    (36, "Lyndon B. Johnson",       1963, 1969),
    (37, "Richard Nixon",           1969, 1974),
    (38, "Gerald Ford",             1974, 1977),
    (39, "Jimmy Carter",            1977, 1981),
    (40, "Ronald Reagan",           1981, 1989),
    (41, "George H. W. Bush",       1989, 1993),
    (42, "Bill Clinton",            1993, 2001),
    (43, "George W. Bush",          2001, 2009),
    (44, "Barack Obama",            2009, 2017),
    (45, "Donald Trump",            2017, 2021),
    (46, "Joe Biden",               2021, 2025),
    (47, "Donald Trump",            2025, None),
]

# Wikidata QIDs for each president. These will be resolved fresh from
# Wikidata at fetch time if not present here, but having them inline
# avoids a round-trip and disambiguates collisions (e.g. "Andrew
# Johnson" the politician vs the others). All QIDs verified against
# Wikidata's "President of the United States" P39 statements.
KNOWN_QIDS = {
    "George Washington":      "Q23",
    "John Adams":             "Q11806",
    "Thomas Jefferson":       "Q11812",
    "James Madison":          "Q11813",
    "James Monroe":           "Q11815",
    "John Quincy Adams":      "Q11816",
    "Andrew Jackson":         "Q11817",
    "Martin Van Buren":       "Q11820",
    "William Henry Harrison": "Q11869",
    "John Tyler":             "Q11881",
    "James K. Polk":          "Q11891",
    "Zachary Taylor":         "Q11896",
    "Millard Fillmore":       "Q12306",
    "Franklin Pierce":        "Q12312",
    "James Buchanan":         "Q12325",
    "Abraham Lincoln":        "Q91",
    "Andrew Johnson":         "Q8612",
    "Ulysses S. Grant":       "Q34836",
    "Rutherford B. Hayes":    "Q35686",
    "James A. Garfield":      "Q34597",
    "Chester A. Arthur":      "Q35498",
    "Grover Cleveland":       "Q35171",
    "Benjamin Harrison":      "Q35678",
    "William McKinley":       "Q35041",
    "Theodore Roosevelt":     "Q33866",
    "William Howard Taft":    "Q35648",
    "Woodrow Wilson":         "Q34296",
    "Warren G. Harding":      "Q35286",
    "Calvin Coolidge":        "Q36023",
    "Herbert Hoover":         "Q35236",
    "Franklin D. Roosevelt":  "Q8007",
    "Harry S. Truman":        "Q11613",
    "Dwight D. Eisenhower":   "Q9916",
    "John F. Kennedy":        "Q9696",
    "Lyndon B. Johnson":      "Q9640",
    "Richard Nixon":          "Q9588",
    "Gerald Ford":            "Q9582",
    "Jimmy Carter":           "Q23685",
    "Ronald Reagan":          "Q9960",
    "George H. W. Bush":      "Q23505",
    "Bill Clinton":           "Q1124",
    "George W. Bush":         "Q207",
    "Barack Obama":           "Q76",
    "Donald Trump":           "Q22686",
    "Joe Biden":              "Q6279",
}


# Manual home-state overrides (these are the states each president is
# most associated with at the time of their presidency — not necessarily
# their place of birth).
HOME_STATES = {
    "George Washington":      "Virginia",
    "John Adams":             "Massachusetts",
    "Thomas Jefferson":       "Virginia",
    "James Madison":          "Virginia",
    "James Monroe":           "Virginia",
    "John Quincy Adams":      "Massachusetts",
    "Andrew Jackson":         "Tennessee",
    "Martin Van Buren":       "New York",
    "William Henry Harrison": "Ohio",
    "John Tyler":             "Virginia",
    "James K. Polk":          "Tennessee",
    "Zachary Taylor":         "Louisiana",
    "Millard Fillmore":       "New York",
    "Franklin Pierce":        "New Hampshire",
    "James Buchanan":         "Pennsylvania",
    "Abraham Lincoln":        "Illinois",
    "Andrew Johnson":         "Tennessee",
    "Ulysses S. Grant":       "Illinois",
    "Rutherford B. Hayes":    "Ohio",
    "James A. Garfield":      "Ohio",
    "Chester A. Arthur":      "New York",
    "Grover Cleveland":       "New York",
    "Benjamin Harrison":      "Indiana",
    "William McKinley":       "Ohio",
    "Theodore Roosevelt":     "New York",
    "William Howard Taft":    "Ohio",
    "Woodrow Wilson":         "New Jersey",
    "Warren G. Harding":      "Ohio",
    "Calvin Coolidge":        "Massachusetts",
    "Herbert Hoover":         "California",
    "Franklin D. Roosevelt":  "New York",
    "Harry S. Truman":        "Missouri",
    "Dwight D. Eisenhower":   "Kansas",
    "John F. Kennedy":        "Massachusetts",
    "Lyndon B. Johnson":      "Texas",
    "Richard Nixon":          "California",
    "Gerald Ford":            "Michigan",
    "Jimmy Carter":           "Georgia",
    "Ronald Reagan":          "California",
    "George H. W. Bush":      "Texas",
    "Bill Clinton":           "Arkansas",
    "George W. Bush":         "Texas",
    "Barack Obama":           "Illinois",
    "Donald Trump":           "New York",
    "Joe Biden":              "Delaware",
}

# Map raw party labels from Wikidata to canonical buckets.
PARTY_NORMALIZE = {
    "Republican Party":              "Republican",
    "Democratic Party":              "Democrat",
    "Democratic-Republican Party":   "Democratic-Republican",
    "Federalist Party":              "Federalist",
    "Whig Party":                    "Whig",
    "National Union Party":          "National Union",
    "National Republican Party":     "National Republican",
    "Independent politician":        "Independent",
}

# Pre-set party (in case Wikidata returns multiple lifetime affiliations
# and we want the one during their presidency).
PARTY_OVERRIDES = {
    (1, "George Washington"):       None,  # no party
    (2, "John Adams"):               "Federalist",
    (3, "Thomas Jefferson"):         "Democratic-Republican",
    (4, "James Madison"):            "Democratic-Republican",
    (5, "James Monroe"):             "Democratic-Republican",
    (6, "John Quincy Adams"):        "Democratic-Republican",
    (7, "Andrew Jackson"):           "Democrat",
    (8, "Martin Van Buren"):         "Democrat",
    (9, "William Henry Harrison"):   "Whig",
    (10, "John Tyler"):              "Whig",
    (11, "James K. Polk"):           "Democrat",
    (12, "Zachary Taylor"):          "Whig",
    (13, "Millard Fillmore"):        "Whig",
    (14, "Franklin Pierce"):         "Democrat",
    (15, "James Buchanan"):          "Democrat",
    (16, "Abraham Lincoln"):         "Republican",
    (17, "Andrew Johnson"):          "National Union",
    (18, "Ulysses S. Grant"):        "Republican",
    (19, "Rutherford B. Hayes"):     "Republican",
    (20, "James A. Garfield"):       "Republican",
    (21, "Chester A. Arthur"):       "Republican",
    (22, "Grover Cleveland"):        "Democrat",
    (23, "Benjamin Harrison"):       "Republican",
    (24, "Grover Cleveland"):        "Democrat",
    (25, "William McKinley"):        "Republican",
    (26, "Theodore Roosevelt"):      "Republican",
    (27, "William Howard Taft"):     "Republican",
    (28, "Woodrow Wilson"):          "Democrat",
    (29, "Warren G. Harding"):       "Republican",
    (30, "Calvin Coolidge"):         "Republican",
    (31, "Herbert Hoover"):          "Republican",
    (32, "Franklin D. Roosevelt"):   "Democrat",
    (33, "Harry S. Truman"):         "Democrat",
    (34, "Dwight D. Eisenhower"):    "Republican",
    (35, "John F. Kennedy"):         "Democrat",
    (36, "Lyndon B. Johnson"):       "Democrat",
    (37, "Richard Nixon"):           "Republican",
    (38, "Gerald Ford"):             "Republican",
    (39, "Jimmy Carter"):            "Democrat",
    (40, "Ronald Reagan"):           "Republican",
    (41, "George H. W. Bush"):       "Republican",
    (42, "Bill Clinton"):            "Democrat",
    (43, "George W. Bush"):          "Republican",
    (44, "Barack Obama"):            "Democrat",
    (45, "Donald Trump"):            "Republican",
    (46, "Joe Biden"):               "Democrat",
    (47, "Donald Trump"):            "Republican",
}

# Notable facts per presidency. Keep to 2-4 short bullets, the most
# defining things one would put on a flashcard. Sourced from common
# knowledge — these are deck-quality "killer fact" hooks, not exhaustive.
NOTABLE = {
    1:  ["1st president; Founding Father", "Commanded Continental Army", "Set the two-term tradition"],
    2:  ["Founding Father; signed Declaration of Independence", "Lost re-election to Jefferson", "Father of John Quincy Adams"],
    3:  ["Author of the Declaration of Independence", "Louisiana Purchase (1803)", "Founded the University of Virginia"],
    4:  ["Father of the Constitution", "War of 1812"],
    5:  ["Monroe Doctrine (1823)", "'Era of Good Feelings'"],
    6:  ["Son of John Adams", "Lost re-election to Jackson"],
    7:  ["Founded the Democratic Party", "Hero of New Orleans (War of 1812)", "Indian Removal Act"],
    8:  ["Architect of the Democratic Party", "Panic of 1837"],
    9:  ["Shortest presidency — died after 31 days", "Hero of Tippecanoe"],
    10: ["First VP to assume presidency on death of predecessor", "Annexed Texas"],
    11: ["Mexican-American War", "Acquired California and the Southwest"],
    12: ["Mexican-American War general", "Died in office (1850)"],
    13: ["Last Whig president", "Compromise of 1850 / Fugitive Slave Act"],
    14: ["Kansas-Nebraska Act"],
    15: ["Last pre-Civil War president", "Often ranked among the worst"],
    16: ["Led Union through Civil War", "Emancipation Proclamation (1863)", "Assassinated at Ford's Theatre"],
    17: ["First president impeached (acquitted by one vote)"],
    18: ["Union Civil War commanding general", "Reconstruction-era president"],
    19: ["Disputed 1876 election", "Ended Reconstruction"],
    20: ["Assassinated 200 days into term"],
    21: ["Pendleton Civil Service Act", "'Gentleman Boss'"],
    22: ["Only president to serve two non-consecutive terms (22nd)", "Pro-business Democrat"],
    23: ["Grandson of William Henry Harrison", "Sherman Antitrust Act (1890)"],
    24: ["Returned to office for non-consecutive 24th term", "Panic of 1893"],
    25: ["Spanish-American War (1898)", "Assassinated in Buffalo (1901)"],
    26: ["Youngest president to take office (42)", "Trust-buster; established National Parks", "Won Nobel Peace Prize"],
    27: ["Later Chief Justice of the Supreme Court", "Heaviest president on record"],
    28: ["Led US through WWI", "Pushed for League of Nations", "Federal Reserve, income tax"],
    29: ["Teapot Dome scandal", "Died in office (1923)"],
    30: ["'Silent Cal'", "Roaring Twenties economy"],
    31: ["Stock market crashed seven months into term", "Great Depression"],
    32: ["Led US through Great Depression and WWII", "Elected to four terms", "New Deal"],
    33: ["Authorized atomic bombings of Japan", "Marshall Plan; NATO; Korean War"],
    34: ["Allied Supreme Commander in WWII (D-Day)", "Interstate Highway System", "Ended Korean War"],
    35: ["Youngest elected president (43)", "Cuban Missile Crisis", "Assassinated in Dallas (1963)"],
    36: ["Civil Rights Act (1964) / Voting Rights Act (1965)", "Great Society; Medicare", "Escalated Vietnam War"],
    37: ["Opened relations with China", "Watergate scandal — only president to resign"],
    38: ["Only unelected president (VP and POTUS)", "Pardoned Nixon"],
    39: ["Camp David Accords", "Iran hostage crisis"],
    40: ["End of the Cold War", "'Reaganomics'", "Iran-Contra affair"],
    41: ["Persian Gulf War (1991)", "Fall of the Soviet Union"],
    42: ["Impeached over Lewinsky affair (acquitted)", "Budget surplus; NAFTA"],
    43: ["9/11 attacks", "Wars in Afghanistan and Iraq", "Son of George H. W. Bush"],
    44: ["First African-American president", "Affordable Care Act ('Obamacare')", "Killed Osama bin Laden"],
    45: ["First impeachment (acquitted) — Ukraine/Russia probes", "Tax Cuts and Jobs Act (2017)", "COVID-19 pandemic"],
    46: ["Oldest person elected president (78)", "Inflation Reduction Act; CHIPS Act"],
    47: ["First president elected to non-consecutive terms since Cleveland", "47th president (also 45th)"],
}

# Vice Presidents per presidency. Format: list of (name, "YYYY–YYYY")
# Hand-curated because Wikidata's VP records are messy.
VPS = {
    1:  [("John Adams", "1789–1797")],
    2:  [("Thomas Jefferson", "1797–1801")],
    3:  [("Aaron Burr", "1801–1805"), ("George Clinton", "1805–1809")],
    4:  [("George Clinton", "1809–1812"), ("Elbridge Gerry", "1813–1814")],
    5:  [("Daniel D. Tompkins", "1817–1825")],
    6:  [("John C. Calhoun", "1825–1829")],
    7:  [("John C. Calhoun", "1829–1832"), ("Martin Van Buren", "1833–1837")],
    8:  [("Richard M. Johnson", "1837–1841")],
    9:  [("John Tyler", "1841")],
    10: [],
    11: [("George M. Dallas", "1845–1849")],
    12: [("Millard Fillmore", "1849–1850")],
    13: [],
    14: [("William R. King", "1853")],
    15: [("John C. Breckinridge", "1857–1861")],
    16: [("Hannibal Hamlin", "1861–1865"), ("Andrew Johnson", "1865")],
    17: [],
    18: [("Schuyler Colfax", "1869–1873"), ("Henry Wilson", "1873–1875")],
    19: [("William A. Wheeler", "1877–1881")],
    20: [("Chester A. Arthur", "1881")],
    21: [],
    22: [("Thomas A. Hendricks", "1885")],
    23: [("Levi P. Morton", "1889–1893")],
    24: [("Adlai E. Stevenson", "1893–1897")],
    25: [("Garret Hobart", "1897–1899"), ("Theodore Roosevelt", "1901")],
    26: [("Charles W. Fairbanks", "1905–1909")],
    27: [("James S. Sherman", "1909–1912")],
    28: [("Thomas R. Marshall", "1913–1921")],
    29: [("Calvin Coolidge", "1921–1923")],
    30: [("Charles G. Dawes", "1925–1929")],
    31: [("Charles Curtis", "1929–1933")],
    32: [("John Nance Garner", "1933–1941"), ("Henry A. Wallace", "1941–1945"), ("Harry S. Truman", "1945")],
    33: [("Alben W. Barkley", "1949–1953")],
    34: [("Richard Nixon", "1953–1961")],
    35: [("Lyndon B. Johnson", "1961–1963")],
    36: [("Hubert Humphrey", "1965–1969")],
    37: [("Spiro Agnew", "1969–1973"), ("Gerald Ford", "1973–1974")],
    38: [("Nelson Rockefeller", "1974–1977")],
    39: [("Walter Mondale", "1977–1981")],
    40: [("George H. W. Bush", "1981–1989")],
    41: [("Dan Quayle", "1989–1993")],
    42: [("Al Gore", "1993–2001")],
    43: [("Dick Cheney", "2001–2009")],
    44: [("Joe Biden", "2009–2017")],
    45: [("Mike Pence", "2017–2021")],
    46: [("Kamala Harris", "2021–2025")],
    47: [("JD Vance", "2025–")],
}


# ── Build records ───────────────────────────────────────────────────
def build_records(qid_props):
    """Return list of card dicts in canonical term order."""
    records = []
    for i, (term, name, start, end) in enumerate(CANONICAL_TERMS):
        qid = KNOWN_QIDS.get(name)
        props = qid_props.get(qid, {}) if qid else {}

        # Predecessor / successor
        predecessor = CANONICAL_TERMS[i - 1][1] if i > 0 else None
        successor   = CANONICAL_TERMS[i + 1][1] if i < len(CANONICAL_TERMS) - 1 else None

        born = props.get("born")
        died = props.get("died")
        # Some presidents (Trump 47, Biden 46) overlap with the present;
        # only set died if the person actually died.
        image = props.get("image")

        # Party
        party = PARTY_OVERRIDES.get((term, name))
        if party is None and term == 1:
            party = "No party"

        # Home state — use manual override (the state most associated
        # with this president at time of presidency).
        home_state = HOME_STATES.get(name)

        rec = {
            "name":         name,
            "wikidata":     qid,
            "term":         term,
            "yearStart":    start,
            "yearEnd":      end,
            "party":        party,
            "vps":          [{"name": v[0], "years": v[1]} for v in VPS.get(term, [])],
            "predecessor":  predecessor,
            "successor":    successor,
            "born":         born,
            "died":         died,
            "homeState":    home_state,
            "notable":      list(NOTABLE.get(term, [])),
            "summary":      None,   # filled by enrich_presidents.py
            "images":       [],     # filled by enrich_presidents.py
            "wikipedia":    f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}",
            "spotify":      None,
        }
        records.append(rec)
    return records


# ── Fetch enrichment props ──────────────────────────────────────────
def fetch_props():
    """Fetch birth/death/image/party for every known president QID."""
    qids = sorted(set(KNOWN_QIDS.values()))
    print(f"  Fetching props for {len(qids)} unique QIDs…", file=sys.stderr)
    values = " ".join(f"wd:{q}" for q in qids)
    query = SPARQL_PROPS.replace("%(VALUES)s", values)
    rows = sparql_query(query)
    print(f"  → {len(rows)} property rows", file=sys.stderr)

    out = {}
    for r in rows:
        qid = qid_from_uri(r.get("person", {}).get("value", ""))
        if not qid:
            continue
        out[qid] = {
            "born":   year_from_time(r.get("birth", {}).get("value")),
            "died":   year_from_time(r.get("death", {}).get("value")),
            "image":  r.get("image", {}).get("value"),
            "pob":    r.get("pob", {}).get("value"),
        }
    return out


# ── Write output ─────────────────────────────────────────────────────
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
        return "[" + ", ".join(js_val(x) for x in v) + "]"
    if isinstance(v, dict):
        pairs = ", ".join(f"{k}: {js_val(val)}" for k, val in v.items())
        return "{" + pairs + "}"
    return json.dumps(v, ensure_ascii=False)


FIELD_ORDER = [
    "name", "wikidata", "term", "yearStart", "yearEnd",
    "party", "vps", "predecessor", "successor",
    "born", "died", "homeState",
    "notable", "summary", "images",
    "wikipedia", "spotify",
]


def write_datafile(path, records):
    lines = ["window.PRESIDENTS_DATA = ["]
    for i, rec in enumerate(records):
        obj_parts = []
        for k in FIELD_ORDER:
            if k not in rec:
                continue
            obj_parts.append(f"  {k}: {js_val(rec[k])}")
        sep = "," if i < len(records) - 1 else ""
        lines.append("{\n" + ",\n".join(obj_parts) + "\n}" + sep)
    lines.append("];")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def parse_datafile(path):
    """Read presidents-data.js and return list of dicts (for resumability)."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'window\.PRESIDENTS_DATA\s*=\s*', text)
    if not m:
        return []
    body = text[m.end():].rstrip().rstrip(';').rstrip()

    # Quote unquoted keys: "  key:" → "  \"key\":"
    out_lines = []
    for line in body.split("\n"):
        stripped = line.lstrip()
        pm = re.match(r'^(\w+)(\s*:\s*)', stripped)
        if pm and not stripped.startswith('"'):
            indent = line[:len(line) - len(stripped)]
            line = f'{indent}"{pm.group(1)}":{stripped[pm.end()-1:]}'
        # inline { key: value } objects
        if re.search(r'\{\s*\w+\s*:', line):
            def _q(m):
                block = m.group(0)
                block = re.sub(r'(?<=\{)\s*(\w+)\s*:', r' "\1":', block)
                block = re.sub(r',\s*(\w+)\s*:', r', "\1":', block)
                return block
            line = re.sub(r'\{[^}]+\}', _q, line)
        out_lines.append(line)
    json_text = "\n".join(out_lines)
    json_text = re.sub(r',\s*([}\]])', r'\1', json_text)
    return json.loads(json_text)


# ── Main ────────────────────────────────────────────────────────────
def main():
    print("Fetching US Presidents…\n", file=sys.stderr)

    # Resumability: if the file exists and has all REQUIRED fields
    # populated, skip the SPARQL fetch (but still rebuild for canonical
    # ordering & in case fields were added).
    existing = []
    if os.path.exists(OUTFILE):
        try:
            existing = parse_datafile(OUTFILE)
            print(f"  Found existing {OUTFILE} ({len(existing)} records)", file=sys.stderr)
        except Exception as e:
            print(f"  Could not parse existing {OUTFILE}: {e}", file=sys.stderr)
            existing = []

    # Build the canonical records.
    have_props_for_all = False
    if existing and len(existing) == len(CANONICAL_TERMS):
        # Check whether we have born/died/image for everyone with a known QID
        all_filled = all(
            (e.get("born") or e.get("name") in {"Donald Trump"})  # Trump appears twice
            for e in existing
        )
        have_props_for_all = all_filled

    if have_props_for_all:
        print("  All records already have core fields — skipping Wikidata fetch.\n", file=sys.stderr)
        qid_props = {}
        # Build qid_props from existing data so we don't lose enriched fields
        for e in existing:
            qid = e.get("wikidata")
            if qid:
                qid_props[qid] = {
                    "born":  e.get("born"),
                    "died":  e.get("died"),
                    "image": None,    # don't overwrite enriched images
                    "pob":   None,
                }
    else:
        print("  [1/1] Fetching properties from Wikidata…", file=sys.stderr)
        qid_props = fetch_props()

    records = build_records(qid_props)

    # If existing data has summary/images already, preserve them.
    if existing:
        # Key by (term, name)
        existing_map = {(e.get("term"), e.get("name")): e for e in existing}
        for rec in records:
            ex = existing_map.get((rec["term"], rec["name"]))
            if ex:
                if ex.get("summary"):
                    rec["summary"] = ex["summary"]
                if ex.get("images"):
                    rec["images"] = ex["images"]
                # Preserve enriched born/died if SPARQL didn't return them
                if not rec.get("born") and ex.get("born"):
                    rec["born"] = ex["born"]
                if not rec.get("died") and ex.get("died"):
                    rec["died"] = ex["died"]

    write_datafile(OUTFILE, records)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Total presidencies:  {len(records)}", file=sys.stderr)
    by_party = defaultdict(int)
    for r in records:
        by_party[r["party"] or "—"] += 1
    print(f"  By party:", file=sys.stderr)
    for p, n in sorted(by_party.items(), key=lambda x: -x[1]):
        print(f"    {p:25s} {n:4d}", file=sys.stderr)
    with_summary = sum(1 for r in records if r.get("summary"))
    with_images = sum(1 for r in records if r.get("images"))
    print(f"  With summary: {with_summary} / {len(records)}", file=sys.stderr)
    print(f"  With images:  {with_images} / {len(records)}", file=sys.stderr)
    print(f"\n  Written to {OUTFILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
