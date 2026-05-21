#!/usr/bin/env python3
"""
Resolve every chain founder's Wikipedia article using REST search with chain
context as the disambiguator, then bulk-fetch summaries.

Why this exists: the old fetch_founders.py did `/page/summary/Peter_Buck`
which lands on Peter Buck the R.E.M. guitarist. Adding the chain name to a
relevance-ranked search ("Peter Buck Subway") returns "Peter Buck
(restaurateur)" as the top hit. This is the Wikipedia-recommended pattern
for human-name disambiguation.

Output: founders.js (window.FOUNDERS = { name → record }).
"""
import os, json, re, time, urllib.request, urllib.parse, urllib.error, gzip

UA = "Crammys/1.0 (personal flashcard app; github.com/brettgus/crammys)"

# Founders confirmed (via prior runs) to have no usable Wikipedia article.
# Reruns skip these so we don't burn rate-limit budget on guaranteed misses.
# To re-confirm if someone got a new article: remove them from this set.
KNOWN_NO_ARTICLE = {
    "Aaron Kennedy", "Alex McCullough", "Ally Svenson", "Anthony Miller",
    "Antonio Swad", "Arthur Randall", "Bernadette Fiaschetti", "Bill Phelps",
    "Bill Wang", "Brett Schulman", "Bryant Keil", "Chris Sorensen",
    "Curt Jones", "Dan and Frank Carney", "David Jameson", "Dimitri Moshovitis",
    "Donald Sutherland", "Ed Hackbarth", "Elise Wetzel", "Forrest Raffel",
    "George Culver", "Ike Grigoropoulos", "J.F. McCullough", "Janie Murrell",
    "Jeffrey Hyman", "Jerry Murrell", "Jimmy Lambatos", "John Puckett",
    "Jonathan Neman", "Juan Francisco Ochoa", "Ken Rosenthal", "Kim Puckett",
    "Lea Culver", "Leroy Raffel", "Louis Kane", "Margaret Karcher",
    "Nathaniel Ru", "Nicolas Jammet", 'Pasquale "Pat" Giammarco',
    "Peter Cancro", "Ray Lindstrom", "Rich Komen", "Rick Wetzel",
    "Robert Hammer", "Robert Hauser", "Robin Sorensen", "Ruth Culver",
    "Scott Svenson", "Susan Sutherland", "Ted Xenohristos", "Terry Collins",
    "Tony Townley", "Wilbur Hardee", "Zach McLeroy",
}

def _write_partial(results):
    """Atomic-ish write: tmp + rename so we never leave a half-flushed file."""
    payload = "window.FOUNDERS = " + json.dumps(results, ensure_ascii=False) + ";\n"
    tmp = "founders.js.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(payload)
    os.replace(tmp, "founders.js")

# ── HTTP plumbing ─────────────────────────────────────────────────────
def _http(url, max_retries=6):
    """More patient retries — Wikipedia's REST search 429s hard and stays
    angry for a while. Backoff goes 5, 10, 20, 40, 80 seconds."""
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 5 * (2 ** attempt)
                print(f"    429 — sleeping {wait}s and retrying…")
                time.sleep(wait); continue
            if e.code == 404:
                return None
            raise

def _strip_excerpt(html):
    """REST search excerpts come with <span class="searchmatch">…</span> markup."""
    if not html: return None
    s = re.sub(r'<[^>]+>', '', html)
    s = re.sub(r'\s+', ' ', s).strip()
    return s or None

# Person-bio markers in Wikipedia's short description ("American businessman",
# "(1947–2015)", "born …"). Used to reject company/place pages that the search
# might bubble up when the founder doesn't have their own article.
_PERSON_MARKERS = ("businessman", "businesswoman", "entrepreneur",
                   "restaurateur", "founder", "co-founder", "philanthropist",
                   "investor", "executive", "industrialist", "magnate",
                   "actor", "actress", "physicist", "chef")
_YEAR_RANGE_RE = re.compile(r'\(\s*\d{4}[\s–\-—]+\d{4}\s*\)|born\s+\d{4}')

def looks_like_person(description):
    if not description: return False
    d = description.lower()
    if any(m in d for m in _PERSON_MARKERS): return True
    if _YEAR_RANGE_RE.search(d): return True
    return False

def _tokens(s):
    """Lowercased word tokens >= 4 chars, with parens content removed."""
    s = re.sub(r'\([^)]*\)', ' ', s or '').lower()
    s = re.sub(r'[^\w\s]', ' ', s)
    return {t for t in s.split() if len(t) >= 4}

def name_match(founder_name, hit_title):
    """Reject results that don't actually mention the founder by name.

    Catches the failure mode where the search bubbles up some other person —
    e.g. "Margaret Karcher" search returning the "Carl Karcher" article, or
    "Tim Horton" returning "Ron Joyce" (his business partner)."""
    f = _tokens(founder_name)
    t = _tokens(hit_title)
    if not f: return True       # Founder name was all short tokens; can't filter
    # Every substantial founder token must appear in the title.
    return f.issubset(t)

# ── Step 1: REST search with chain context ────────────────────────────
def search_founder(name, chain, chain_slug=None):
    """Return the top-ranked Wikipedia page for a founder, scoped by chain.

    Filters out:
    - Disambiguation pages
    - The chain's own article (when the founder has no dedicated page, the
      search would otherwise fall back to the chain page — that's bad data)
    - Pages whose description doesn't read like a person bio
    """
    q = f'"{name}" {chain} founder'
    url = "https://en.wikipedia.org/w/rest.php/v1/search/page?" + urllib.parse.urlencode({
        "q": q, "limit": 5,
    })
    try:
        d = _http(url)
    except Exception as e:
        print(f"    ! search failed for {name}: {e}")
        return None
    pages = (d or {}).get("pages") or []
    for p in pages:
        title = (p.get("title") or "")
        key   = (p.get("key") or "")
        desc  = (p.get("description") or "")
        # Disambiguation
        if title.endswith("(disambiguation)"): continue
        dl = desc.lower()
        if "topics referred to" in dl or "may refer to" in dl: continue
        # Chain's own article (most common false positive — founder without bio)
        if chain_slug and key == chain_slug: continue
        # Heuristic: the description should look like a person bio
        if not looks_like_person(desc): continue
        # The result's title must actually mention the founder (catches
        # "Margaret Karcher" → "Carl Karcher", "Tim Horton" → "Ron Joyce")
        if not name_match(name, title): continue
        return {
            "title": title,
            "key": key,
            "description": desc,
            "thumb": (p.get("thumbnail") or {}).get("url"),
            "excerpt": _strip_excerpt(p.get("excerpt")),
        }
    return None

# ── Step 2: bulk summary fetch via the Action API ─────────────────────
def bulk_summaries(slugs):
    """Fetch intro extract + thumbnail for up to 50 page slugs in one request."""
    if not slugs: return {}
    titles = "|".join(slugs)
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "prop": "extracts|pageimages|info",
        "exintro": "true",
        "exsentences": "3",
        "explaintext": "true",
        "piprop": "thumbnail",
        "pithumbsize": "200",
        "inprop": "url",
        "titles": titles,
        "redirects": "1",
        "format": "json",
        "formatversion": "2",
    })
    d = _http(url) or {}
    out = {}
    for p in (d.get("query") or {}).get("pages") or []:
        out[p.get("title")] = {
            "extract": (p.get("extract") or "").strip(),
            "thumb":   (p.get("thumbnail") or {}).get("source"),
            "url":     p.get("fullurl"),
        }
    # Build slug → record map by normalizing slug → space-title
    by_slug = {}
    for slug in slugs:
        title = slug.replace("_", " ")
        if title in out:
            by_slug[slug] = out[title]
    return by_slug

# ── Top-level resolution ──────────────────────────────────────────────
def resolve_one(name, chain, chain_slug=None):
    """Return (name, record_or_None, log_msg)."""
    hit = search_founder(name, chain, chain_slug=chain_slug)
    if not hit:
        return name, None, f"no match"
    return name, hit, f"→ {hit['title']}"

def load_existing():
    """Read any previous founders.js so the script is resumable."""
    if not os.path.exists("founders.js"):
        return {}
    try:
        txt = open("founders.js").read()
        m = re.search(r"window\.FOUNDERS\s*=\s*(\{.*\});\s*$", txt, re.DOTALL)
        return json.loads(m.group(1)) if m else {}
    except Exception:
        return {}

def main():
    import sys
    sys.stdout.reconfigure(line_buffering=True)

    with open("chains/manifest.json", encoding="utf-8") as f:
        chains = json.load(f)

    # Collect (name, chain, chain_slug) tuples. Use the first chain that
    # lists each founder; pass the chain's wiki_slug so the search can reject
    # any hit that points to the chain itself.
    pairs = {}
    for c in chains:
        for n in c.get("founders") or []:
            if n not in pairs:
                pairs[n] = (c["name"], c.get("wiki_slug"))

    # Resume: skip founders we already resolved on a previous run.
    existing = load_existing()
    def needs_resolve(name):
        e = existing.get(name)
        if not e: return True
        if e.get("unresolved"): return True
        if not (e.get("summary") or e.get("description")): return True
        return False
    # Skip founders we've already confirmed have no Wikipedia article.
    out = dict(existing)
    skipped = 0
    for name in list(pairs):
        if name in KNOWN_NO_ARTICLE and name not in out:
            out[name] = {"name": name, "unresolved": True}
            skipped += 1

    todo = [(n, chain, slug) for n, (chain, slug) in pairs.items()
            if n not in KNOWN_NO_ARTICLE and needs_resolve(n)]
    print(f"Resolving {len(todo)}/{len(pairs)} founders "
          f"({skipped} pre-marked as no-article, "
          f"{len(pairs)-len(todo)-skipped} already cached).\n")

    saved_count = 0

    # Sequential search — Wikipedia's REST search is rate-limit-prickly. The
    # `excerpt` field on each search hit is itself a usable summary, so no
    # second bulk-fetch round is needed.
    for i, (name, chain, chain_slug) in enumerate(todo, 1):
        try:
            _, hit, msg = resolve_one(name, chain, chain_slug=chain_slug)
        except Exception as e:
            print(f"[{i}/{len(todo)}] {name}  ! {e}")
            continue
        print(f"[{i}/{len(todo)}] {name:30}  {msg}")
        if hit:
            out[name] = {
                "name":        hit.get("title") or name,
                "description": hit.get("description"),
                "summary":     hit.get("excerpt"),
                "thumb":       hit.get("thumb"),
                "page":        f"https://en.wikipedia.org/wiki/{hit.get('key')}" if hit.get('key') else None,
                "source":      "rest-search",
            }
        else:
            out[name] = {"name": name, "unresolved": True}
        saved_count += 1
        if saved_count % 10 == 0:
            _write_partial(out)
        time.sleep(1.2)

    _write_partial(out)

    resolved = sum(1 for n in pairs
                   if out.get(n) and not out[n].get("unresolved")
                   and (out[n].get("summary") or out[n].get("description")))
    print(f"\nDone. {resolved}/{len(pairs)} founders resolved.")

if __name__ == "__main__":
    main()
