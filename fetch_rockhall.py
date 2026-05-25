#!/usr/bin/env python3
"""
Fetch Rock & Roll Hall of Fame inductee data from Wikidata SPARQL.
Output: rockhall-data.js  (window.ROCKHALL_DATA = [...])

Usage: python3 fetch_rockhall.py

Strategy:
  1. Query Wikidata for all entities with P166 → Q179191 (Rock Hall award)
     to get names, induction years, and Wikidata IDs.
  2. Parse the Wikipedia "List of Rock and Roll Hall of Fame inductees"
     article to resolve induction categories (Performer, Early Influence,
     Non-Performer, Musical Excellence) — Wikidata doesn't store these.
  3. Query Wikidata again for enrichment properties (genres, country,
     birth/death, image, members, MusicBrainz ID, etc.).
"""
import sys, json, urllib.request, urllib.parse, urllib.error, gzip, re, time, unicodedata
from collections import defaultdict

WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
UA = "Crammys/1.0 (flashcard app)"

# ── HTTP helper ──────────────────────────────────────────────────────
def http_json(url, *, timeout=90, max_retries=3, backoff=5.0):
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
    return http_json(url, timeout=120)["results"]["bindings"]


def qid_from_uri(uri):
    if not uri:
        return None
    return uri.rsplit("/", 1)[-1] if "/" in uri else uri


def year_from_time(t):
    """Extract year from Wikidata time literal like '+1986-01-01T00:00:00Z'."""
    if not t:
        return None
    m = re.match(r'[+\-]?(\d{4})', t)
    return int(m.group(1)) if m else None


# ── Wikipedia category parser ───────────────────────────────────────
def parse_wikipedia_categories():
    """Parse the Wikipedia 'List of Rock and Roll Hall of Fame inductees'
    article to extract inductee names with their induction category.
    Returns dict: normalized_name → list of {year, category}."""

    print("  Fetching Wikipedia inductee list…", file=sys.stderr)
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "parse",
        "page": "List_of_Rock_and_Roll_Hall_of_Fame_inductees",
        "prop": "wikitext",
        "format": "json",
    })
    d = http_json(url)
    wikitext = d["parse"]["wikitext"]["*"]

    # Category sections and their headers in the wikitext
    SECTION_CATEGORIES = {
        "Performers": "Performer",
        "Early/musical influences": "Early Influence",
        "Non-performers (Ahmet Ertegun Award)": "Non-Performer",
        "Award for Musical Excellence": "Musical Excellence",
        "Singles": "Single",
    }

    results = {}  # normalized_name → [{year, category}]
    current_category = None
    current_year = None
    in_table = False

    for line in wikitext.split("\n"):
        # Detect section headers
        m = re.match(r'^===\s*(.+?)\s*===$', line)
        if m:
            header = m.group(1).strip()
            current_category = SECTION_CATEGORIES.get(header)
            in_table = False
            continue

        # Detect section level 2 (exits Inductees section)
        if re.match(r'^==\s*[^=]', line):
            if "Inductees" not in line:
                current_category = None
            continue

        if not current_category:
            continue

        # Track table start/end
        if line.startswith("{|"):
            in_table = True
            continue
        if line.startswith("|}"):
            in_table = False
            continue

        if not in_table:
            continue

        # Extract year from rowspan rows like: | rowspan="10" | 1986
        ym = re.search(r'(?:rowspan[^|]*\|)?\s*(\d{4})\s*$', line)
        if ym and not re.search(r'sortname|sortkey|File:|Image:', line, re.I):
            candidate = int(ym.group(1))
            if 1980 <= candidate <= 2030:
                current_year = candidate

        # Extract names from sortname templates: {{sortname|First|Last|...}}
        for sm in re.finditer(r'\{\{sortname\|([^}]+)\}\}', line):
            parts = sm.group(1).split("|")
            if len(parts) >= 3:
                # Third part is often a link target/sort key — e.g.
                # {{sortname|The|Comets|Bill Haley & His Comets}}
                # Use both "First Last" and the third part as names
                name = f"{parts[0]} {parts[1]}"
                alt_name = parts[2]
            elif len(parts) >= 2:
                name = f"{parts[0]} {parts[1]}"
                alt_name = None
            else:
                name = parts[0]
                alt_name = None
            # Clean up link targets in name
            name = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', name)
            name = name.strip()
            if alt_name:
                alt_name = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', alt_name).strip()
            for n in [name, alt_name]:
                if not n:
                    continue
                norm = _normalize_name(n)
                if norm and current_year:
                    entry = {
                        "year": current_year,
                        "category": current_category,
                        "raw_name": n,
                    }
                    results.setdefault(norm, []).append(entry)

        # Match data-sort-value entries like:
        # | data-sort-value="5 Royales, The" | [[The "5" Royales]]
        # | data-sort-value="Barry" | [[Jeff Barry]] and [[Ellie Greenwich]]
        # | data-sort-value="Small Faces" | {{nowrap|[[Small Faces|...]]}}
        dsv = re.search(r'data-sort-value="[^"]*"\s*\|(.+)', line)
        if dsv and "sortname" not in line:
            cell = dsv.group(1).strip()
            # Strip {{nowrap|...}} wrappers
            cell = re.sub(r'\{\{nowrap\|([^}]+)\}\}', r'\1', cell)
            # Extract all [[link|display]] or [[link]] names
            names_in_cell = []
            for lm in re.finditer(r'\[\[([^|\]]+?)(?:\|([^\]]+?))?\]\]', cell):
                if lm.group(1).startswith(("File:", "Image:", "Category:")):
                    continue
                n = lm.group(2) or lm.group(1)
                n = n.strip()
                if not re.match(r'^\d{4}$', n) and len(n) >= 2:
                    names_in_cell.append(n)
            # Also try the full cell text stripped of markup for compound names
            clean_cell = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', cell)
            clean_cell = re.sub(r'\{\{[^}]*\}\}', '', clean_cell)
            clean_cell = re.sub(r'<[^>]+>', '', clean_cell)
            clean_cell = re.sub(r'\{\{ref\|[^}]*\}\}', '', clean_cell, flags=re.I)
            clean_cell = clean_cell.strip().rstrip('.')
            if clean_cell and len(clean_cell) >= 2:
                names_in_cell.append(clean_cell)
            for n in names_in_cell:
                norm = _normalize_name(n)
                if norm and current_year:
                    results.setdefault(norm, []).append({
                        "year": current_year,
                        "category": current_category,
                        "raw_name": n,
                    })
            if names_in_cell:
                continue  # already handled

        # Also match [[Name]] links that aren't sortname (some entries)
        # e.g. | [[Little Richard]] or | [[U2]]
        if "sortname" not in line and re.match(r'^\|\s*\[\[', line.strip()):
            for lm in re.finditer(r'\[\[([^|\]]+?)(?:\|([^\]]+?))?\]\]', line):
                # Skip image/file links
                if lm.group(1).startswith(("File:", "Image:", "Category:")):
                    continue
                name = lm.group(2) or lm.group(1)
                name = name.strip()
                # Filter out non-name links (refs, years, etc.)
                if re.match(r'^\d{4}$', name):
                    continue
                if len(name) < 2:
                    continue
                norm = _normalize_name(name)
                if norm and current_year and norm not in results:
                    results.setdefault(norm, []).append({
                        "year": current_year,
                        "category": current_category,
                        "raw_name": name,
                    })

    return results


def _strip_diacritics(s):
    """Remove diacritics: ü→u, é→e, etc."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_name(name):
    """Normalize a name for fuzzy matching."""
    name = name.strip()
    # Remove common prefixes
    name = re.sub(r'^The\s+', '', name, flags=re.I)
    # Remove parenthetical disambiguation
    name = re.sub(r'\s*\([^)]*\)', '', name)
    # Strip diacritics
    name = _strip_diacritics(name)
    # Remove quotation marks
    name = name.replace('"', '').replace("'", '').replace('“', '').replace('”', '')
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name.lower()


# Manual category overrides for Wikidata names that can't be matched
# algorithmically to the Wikipedia list.
MANUAL_CATEGORIES = {
    # Wikidata name → [(year, category), ...]
    "Leiber-Stoller": [(1987, "Non-Performer")],
    "Gerry Goffin": [(1990, "Non-Performer")],
    "Ellie Greenwich": [(2010, "Non-Performer")],
    "Jeff Barry": [(2010, "Non-Performer")],
    "Mann & Weil": [(2010, "Non-Performer")],
    "Jerry Moss": [(2006, "Non-Performer")],
    "Small Faces": [(2012, "Performer")],
    "Nasuhî Ertegün": [(1991, "Non-Performer")],
    "Nasuhi Ertegün": [(1991, "Non-Performer")],
    "In-A-Gadda-Da-Vida": [(2009, "Single")],
    "Lawdy Miss Clawdy": [(2024, "Single")],
}


def match_category(name, wiki_categories):
    """Try to match a Wikidata name to Wikipedia categories."""
    norm = _normalize_name(name)
    if norm in wiki_categories:
        return wiki_categories[norm]

    # Try without "and" → "&" and vice versa
    for src, dst in [(" and ", " & "), (" & ", " and ")]:
        alt = norm.replace(src, dst)
        if alt in wiki_categories:
            return wiki_categories[alt]

    # Try replacing hyphens with " and " or spaces
    for repl in [" and ", " "]:
        alt = norm.replace("-", repl)
        if alt in wiki_categories:
            return wiki_categories[alt]

    # Try substring matching — inductee name contains a wiki key or vice versa
    for key, val in wiki_categories.items():
        if len(key) >= 4 and (key in norm or norm in key):
            return val

    # Try partial match (last name for persons)
    parts = norm.split()
    if len(parts) >= 2:
        for key in wiki_categories:
            if key.endswith(parts[-1]) and parts[0] in key:
                return wiki_categories[key]

    return None


# ── SPARQL queries ───────────────────────────────────────────────────

# Query 1: Core induction data — all entities with the Rock Hall award
SPARQL_INDUCTIONS = """
SELECT ?entity ?entityLabel ?year ?entityDescription ?slug WHERE {
  ?entity p:P166 ?award_stmt .
  ?award_stmt ps:P166 wd:Q179191 .
  OPTIONAL { ?award_stmt pq:P585 ?date . BIND(YEAR(?date) AS ?year) }
  OPTIONAL { ?entity wdt:P3162 ?slug . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
"""

# Query 2: Entity properties (type, genres, country, dates, image, etc.)
SPARQL_PROPERTIES = """
SELECT ?entity ?instanceOf
       (GROUP_CONCAT(DISTINCT ?genreLabel; separator="|||") AS ?genres)
       (GROUP_CONCAT(DISTINCT ?countryLabel; separator="|||") AS ?countries)
       ?inception ?birthDate ?deathDate ?disbanded
       ?image ?musicbrainz
WHERE {
  ?entity p:P166 ?award_stmt .
  ?award_stmt ps:P166 wd:Q179191 .

  OPTIONAL { ?entity wdt:P31 ?instanceOf . }
  OPTIONAL {
    ?entity wdt:P136 ?genre .
    ?genre rdfs:label ?genreLabel .
    FILTER(LANG(?genreLabel) = "en")
  }
  OPTIONAL {
    ?entity wdt:P27 ?citizenship .
    ?citizenship rdfs:label ?countryLabel .
    FILTER(LANG(?countryLabel) = "en")
  }
  OPTIONAL {
    ?entity wdt:P495 ?origin .
    ?origin rdfs:label ?countryLabel .
    FILTER(LANG(?countryLabel) = "en")
  }
  OPTIONAL { ?entity wdt:P571 ?inception . }
  OPTIONAL { ?entity wdt:P569 ?birthDate . }
  OPTIONAL { ?entity wdt:P570 ?deathDate . }
  OPTIONAL { ?entity wdt:P576 ?disbanded . }
  OPTIONAL { ?entity wdt:P18 ?image . }
  OPTIONAL { ?entity wdt:P434 ?musicbrainz . }
}
GROUP BY ?entity ?instanceOf ?inception ?birthDate ?deathDate ?disbanded ?image ?musicbrainz
"""

# Query 3: Band members (P527 = "has part")
SPARQL_MEMBERS = """
SELECT ?entity (GROUP_CONCAT(DISTINCT ?memberLabel; separator="|||") AS ?members)
WHERE {
  ?entity p:P166 ?award_stmt .
  ?award_stmt ps:P166 wd:Q179191 .
  ?entity wdt:P527 ?member .
  ?member rdfs:label ?memberLabel .
  FILTER(LANG(?memberLabel) = "en")
}
GROUP BY ?entity
"""

# Known instance-of QIDs for groups vs persons
GROUP_TYPES = {
    "Q215380",    # musical group
    "Q5741069",   # rock band
    "Q2088357",   # musical ensemble
    "Q9212979",   # musical duo
    "Q4387743",   # rap group
    "Q108439064", # vocal group
    "Q33104069",  # girl group
    "Q131186",    # boy band
}

PERSON_TYPES = {
    "Q5",  # human
}


# ── Main ─────────────────────────────────────────────────────────────
def main():
    print("Fetching Rock & Roll Hall of Fame inductees…\n", file=sys.stderr)

    # --- Step 0: Wikipedia categories ---
    wiki_cats = parse_wikipedia_categories()
    total_wiki = sum(len(v) for v in wiki_cats.values())
    print(f"        → {len(wiki_cats)} names, {total_wiki} induction entries from Wikipedia\n",
          file=sys.stderr)

    # --- Step 1: Inductions from Wikidata ---
    print("  [1/3] Fetching induction data from Wikidata…", file=sys.stderr)
    rows = sparql_query(SPARQL_INDUCTIONS)
    print(f"        → {len(rows)} induction rows", file=sys.stderr)

    # Build inductee dict keyed by QID
    inductees = {}
    for r in rows:
        uri = r.get("entity", {}).get("value", "")
        if not uri:
            continue
        qid = qid_from_uri(uri)
        name = r.get("entityLabel", {}).get("value", "")
        # Skip entries where the label is just the QID (unresolved)
        if name.startswith("Q") and name[1:].isdigit():
            continue
        desc = r.get("entityDescription", {}).get("value")
        slug = r.get("slug", {}).get("value")

        if qid not in inductees:
            inductees[qid] = {
                "name": name,
                "wikidata": qid,
                "description": desc,
                "slug": slug,
                "inductions": [],
                "type": "person",
                "genres": [],
                "country": None,
                "born": None,
                "died": None,
                "formed": None,
                "disbanded": None,
                "image": None,
                "members": [],
                "musicbrainz": None,
            }

        year_val = r.get("year", {}).get("value")
        year = int(year_val) if year_val else None

        # Try to find category from Wikipedia, then manual overrides
        category = "Inductee"  # default
        wiki_match = match_category(name, wiki_cats)
        if wiki_match:
            # Find the matching year entry
            for wm in wiki_match:
                if wm["year"] == year:
                    category = wm["category"]
                    break
            else:
                # If no year match, use the first entry's category
                category = wiki_match[0]["category"]
        elif name in MANUAL_CATEGORIES:
            for mc_year, mc_cat in MANUAL_CATEGORIES[name]:
                if mc_year == year or year is None:
                    category = mc_cat
                    break
            else:
                category = MANUAL_CATEGORIES[name][0][1]

        entry = {"year": year, "category": category}
        if entry not in inductees[qid]["inductions"]:
            inductees[qid]["inductions"].append(entry)

    print(f"        → {len(inductees)} unique inductees", file=sys.stderr)

    # --- Step 2: Properties ---
    print("  [2/3] Fetching entity properties…", file=sys.stderr)
    time.sleep(1.5)
    rows = sparql_query(SPARQL_PROPERTIES)
    print(f"        → {len(rows)} property rows", file=sys.stderr)

    entity_types = defaultdict(set)

    for r in rows:
        uri = r.get("entity", {}).get("value", "")
        qid = qid_from_uri(uri)
        if qid not in inductees:
            continue
        rec = inductees[qid]

        # Instance-of
        inst_uri = r.get("instanceOf", {}).get("value")
        if inst_uri:
            entity_types[qid].add(qid_from_uri(inst_uri))

        # Genres
        genres_str = r.get("genres", {}).get("value", "")
        if genres_str:
            for g in genres_str.split("|||"):
                g = g.strip()
                if g and g not in rec["genres"]:
                    rec["genres"].append(g)

        # Country
        countries_str = r.get("countries", {}).get("value", "")
        if countries_str and not rec["country"]:
            rec["country"] = countries_str.split("|||")[0].strip()

        # Dates
        inception = r.get("inception", {}).get("value")
        birth = r.get("birthDate", {}).get("value")
        death = r.get("deathDate", {}).get("value")
        disb = r.get("disbanded", {}).get("value")

        if inception:
            rec["formed"] = year_from_time(inception)
        if birth:
            rec["born"] = year_from_time(birth)
        if death:
            rec["died"] = year_from_time(death)
        if disb:
            rec["disbanded"] = year_from_time(disb)

        # Image
        img = r.get("image", {}).get("value")
        if img and not rec["image"]:
            rec["image"] = img

        # MusicBrainz
        mb = r.get("musicbrainz", {}).get("value")
        if mb and not rec["musicbrainz"]:
            rec["musicbrainz"] = mb

    # Resolve type from instanceOf
    for qid, types in entity_types.items():
        if qid in inductees:
            if types & GROUP_TYPES:
                inductees[qid]["type"] = "group"
            elif types & PERSON_TYPES:
                inductees[qid]["type"] = "person"

    # --- Step 3: Band members ---
    print("  [3/3] Fetching band members…", file=sys.stderr)
    time.sleep(1.5)
    rows = sparql_query(SPARQL_MEMBERS)
    print(f"        → {len(rows)} member rows", file=sys.stderr)

    for r in rows:
        uri = r.get("entity", {}).get("value", "")
        qid = qid_from_uri(uri)
        if qid not in inductees:
            continue
        members_str = r.get("members", {}).get("value", "")
        if members_str:
            inductees[qid]["members"] = sorted(
                m.strip() for m in members_str.split("|||") if m.strip()
            )

    # --- Post-processing ---
    print("\n  Post-processing…", file=sys.stderr)

    results = []
    for qid, rec in inductees.items():
        # Sort inductions by year
        rec["inductions"].sort(key=lambda x: x["year"] or 9999)
        # Top-level year = earliest induction
        years = [i["year"] for i in rec["inductions"] if i["year"]]
        rec["year"] = min(years) if years else None

        # Sort genres alphabetically
        rec["genres"].sort()

        # For groups: clear person fields; for persons: clear group fields
        if rec["type"] == "group":
            rec["born"] = None
            rec["died"] = None
        else:
            rec["formed"] = None
            rec["disbanded"] = None
            rec["members"] = []

        # Drop the slug field (internal only)
        rec.pop("slug", None)

        results.append(rec)

    # Sort by induction year, then name
    results.sort(key=lambda r: (r["year"] or 9999, r["name"]))

    # --- Write output ---
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
        if isinstance(v, dict):
            pairs = ", ".join(f"{k}: {js_val(val)}" for k, val in v.items())
            return "{" + pairs + "}"
        return json.dumps(v, ensure_ascii=False)

    lines = []
    for rec in results:
        obj_parts = []
        obj_parts.append(f"  name: {js_val(rec['name'])}")
        obj_parts.append(f"  wikidata: {js_val(rec['wikidata'])}")
        obj_parts.append(f"  year: {js_val(rec['year'])}")
        inductions_items = []
        for ind in rec["inductions"]:
            inductions_items.append(
                f"{{ year: {js_val(ind['year'])}, category: {js_val(ind['category'])} }}"
            )
        obj_parts.append(f"  inductions: [{', '.join(inductions_items)}]")
        obj_parts.append(
            f"  category: {js_val(rec['inductions'][0]['category'] if rec['inductions'] else 'Inductee')}"
        )
        obj_parts.append(f"  type: {js_val(rec['type'])}")
        obj_parts.append(f"  genres: {js_val(rec['genres'])}")
        obj_parts.append(f"  country: {js_val(rec['country'])}")
        obj_parts.append(f"  born: {js_val(rec['born'])}")
        obj_parts.append(f"  died: {js_val(rec['died'])}")
        obj_parts.append(f"  formed: {js_val(rec['formed'])}")
        obj_parts.append(f"  disbanded: {js_val(rec['disbanded'])}")
        obj_parts.append(f"  image: {js_val(rec['image'])}")
        obj_parts.append(f"  description: {js_val(rec['description'])}")
        obj_parts.append(f"  members: {js_val(rec['members'])}")
        obj_parts.append(f"  musicbrainz: {js_val(rec['musicbrainz'])}")
        lines.append("{\n" + ",\n".join(obj_parts) + "\n}")

    js_content = "window.ROCKHALL_DATA = [\n" + ",\n".join(lines) + "\n];\n"

    outpath = "rockhall-data.js"
    with open(outpath, "w", encoding="utf-8") as f:
        f.write(js_content)

    # --- Summary ---
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Total inductees:  {len(results)}", file=sys.stderr)
    cat_counts = defaultdict(int)
    for rec in results:
        for ind in rec["inductions"]:
            cat_counts[ind["category"]] += 1
    print(f"  Induction entries by category:", file=sys.stderr)
    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"    {cat:25s} {count:4d}", file=sys.stderr)
    years_all = [r["year"] for r in results if r["year"]]
    if years_all:
        print(f"  Year range:       {min(years_all)} – {max(years_all)}", file=sys.stderr)
    groups = sum(1 for r in results if r["type"] == "group")
    persons = sum(1 for r in results if r["type"] == "person")
    print(f"  Persons: {persons}   Groups: {groups}", file=sys.stderr)
    uncat = sum(1 for r in results if all(i["category"] == "Inductee" for i in r["inductions"]))
    if uncat:
        print(f"  Uncategorized:    {uncat}", file=sys.stderr)
    print(f"\n  Written to {outpath}", file=sys.stderr)


if __name__ == "__main__":
    main()
