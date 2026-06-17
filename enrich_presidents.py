#!/usr/bin/env python3
"""
Enrich presidents-data.js with:
  1. summary  — first paragraph of each president's Wikipedia article
                (validated to mention "President", "United States", or
                "American" — same Layer-1 pattern as enrich_rockhall.py
                and enrich_songs.py).
  2. images   — up to 8 portraits per president from Wikimedia Commons,
                stored as [{ url, w, h }, …]. The first image is the
                canonical P18 portrait when available.

Usage:  python3 enrich_presidents.py
Resumable: skips presidents whose `summary` AND `images` are both
already populated.

Reads WIKIMEDIA_BOT_USER / WIKIMEDIA_BOT_PASS from .env for higher
Wikipedia API rate limits (optional — falls back to anonymous).
"""
import sys, os, json, re, time, gzip, urllib.request, urllib.parse, urllib.error, http.cookiejar

UA = "Crammys/1.0 (flashcard app; brett.gustafson@gmail.com)"
BASE = os.path.dirname(os.path.abspath(__file__))
DATAFILE = os.path.join(BASE, "presidents-data.js")

SUMMARY_MAX = 600
IMAGES_PER_PRESIDENT = 8
MIN_GOOD_IMAGES = 4    # if a president falls below this, top up

# ── Strict filter: filenames containing any of these substrings (as
# whole tokens, with underscores acting as word separators) are
# rejected. We build a combined regex below.
#
# Tokens are matched case-insensitively. Each token is wrapped with
# token-boundary anchors so e.g. "desk" matches "Desk_XCI" but not
# "Desktop". Token boundaries treat `_`, `-`, `,`, parentheses, etc.
# as separators (Commons titles use underscores, spaces, and many
# punctuation chars).
IMAGE_EXCLUDE_TOKENS = [
    # Sculpture / death / commemoration
    "tomb", "tombs", "grave", "graves", "memorial", "memorials",
    "statue", "statues", "monument", "monuments", "bust", "busts",
    "sculpture", "sculptures", "cemetery", "burial", "burials",
    "headstone", "headstones", "gravestone", "gravestones",
    "funeral", "funerals", "death", "casket", "coffin", "obituary",
    "obit", "interment",
    # Text / documents / speech
    "signature", "signatures", "autograph", "autographs",
    "document", "documents", "letter", "letters", "speech",
    "speeches", "address", "addresses", "telegram", "telegrams",
    "envelope", "envelopes", "proclamation", "manuscript",
    "manuscripts", "memorandum", "memo", "papers", "diary",
    "diaries", "check", "checks", "certificate", "subscription",
    "deed", "deeds", "treaty", "petition", "memo", "transcript",
    "broadside", "almanac", "newspaper", "headline", "headlines",
    "pamphlet",
    # Buildings / interiors / locations
    "desk", "desks", "chair", "chairs", "office", "offices",
    "room", "rooms", "building", "buildings", "house", "houses",
    "library", "libraries", "museum", "museums", "archives",
    "archive", "birthplace", "residence", "residences", "mansion",
    "mansions", "estate", "estates", "tower", "hall", "park",
    "schoolhouse", "courthouse", "interior", "exterior",
    "homestead", "farmhouse", "cabin", "lobby", "exhibit",
    "gallery", "marker", "plaque",
    # Campaign / events
    "campaign", "campaigns", "rally", "rallies", "supporter",
    "supporters", "convention", "conventions", "podium", "parade",
    "ceremony", "ceremonies", "swearing", "oath", "press",
    # Money / collectibles / consumer goods
    "stamp", "stamps", "coin", "coins", "currency", "banknote",
    "banknotes", "medal", "medals", "poster", "posters", "dollar",
    "handkerchief", "fan", "glass", "ribbon", "ribbons", "badge",
    "badges", "button", "buttons", "pin", "pins", "souvenir",
    "memorabilia", "trinket",
    # Print / illustration
    "cartoon", "cartoons", "caricature", "caricatures", "mural",
    "murals", "illustration", "illustrations", "drawing",
    "drawings", "sketch", "sketches", "engraving", "engravings",
    "lithograph", "lithographs", "etching", "etchings", "woodcut",
    "comic", "advertisement", "advertisements", "ad", "ads",
    # Markers / signs
    "historical", "marker", "sign", "billboard", "roadside",
    # Family / others
    "family", "families", "wife", "wives", "daughter", "daughters",
    "son", "sons", "children", "child", "relatives", "siblings",
    "group", "people", "crowd",
    # Branding
    "logo", "logos", "seal", "seals", "flag", "flags", "emblem",
    "emblems", "crest", "crests", "insignia", "shield", "arms",
    # Maps / charts / scenes / misc
    "map", "maps", "chart", "charts", "census", "battle", "scene",
    "scenes", "battlefield", "war", "military",
    # Recurring junk titles seen in current data
    "annals", "essex", "register", "commonwealth", "appointment",
    "salem", "albemarle", "tagliaferro", "balsa", "michaux",
    "grachtenmuseum", "amsterdam", "keizersgracht",
    "schoolhouse", "drinking",
]

# Tokens for which a filename also containing "portrait" or "headshot"
# is still allowed (real portraits sometimes mention White House, the
# subject leaning on a chair, etc.). Keep this list small — only
# things that legitimately co-occur with portrait files.
IMAGE_EXCLUDE_TOKENS_PORTRAIT_OVERRIDE = {
    "desk", "desks", "chair", "chairs", "office", "offices", "room",
    "rooms", "house", "houses", "library", "libraries", "hall",
    "ribbon", "ribbons", "fan",
}

# Group 1 is the matched token. The token must be preceded and
# followed by a "boundary" — start/end of string, any non-letter/digit
# character. Underscores explicitly count as a separator. Apostrophes
# in titles are uncommon enough to ignore.
_BOUNDARY_BEFORE = r'(?:^|[^A-Za-z0-9])'
_BOUNDARY_AFTER  = r'(?=$|[^A-Za-z0-9])'
IMAGE_EXCLUDE_RE = re.compile(
    _BOUNDARY_BEFORE + r'(' + "|".join(IMAGE_EXCLUDE_TOKENS) + r')' + _BOUNDARY_AFTER,
    re.IGNORECASE,
)

_PORTRAIT_HINT_RE = re.compile(r'(?:^|[^A-Za-z0-9])(portrait|headshot|official_photo)(?=$|[^A-Za-z0-9])', re.IGNORECASE)

# Reject non-image / non-portrait extensions outright.
IMAGE_BAD_EXT_RE = re.compile(
    r'\.(svg|ogg|ogv|webm|pdf|mid|midi|flac|wav|tif|tiff|gif)$',
    re.IGNORECASE,
)
IMAGE_KEEP_EXT = re.compile(r'\.(jpe?g|png)$', re.IGNORECASE)

# Aspect ratio bounds. Anything outside ~0.5 ≤ w/h ≤ 2.0 is suspect:
#   w/h > 2.0  → landscape (room, document, panorama)
#   h/w > 3.0  → very tall (poster, signature, column)
ASPECT_MAX_LANDSCAPE = 2.0   # max w/h
ASPECT_MAX_PORTRAIT  = 3.0   # max h/w

# Tokens that strongly suggest a portrait — used to *prefer* these in
# fallback search and to count them as "definitely good" for the
# re-evaluation pass.
IMAGE_PREFER_RE = re.compile(
    r'(official_portrait|official_photograph|presidential_portrait|'
    r'\bportrait\b|headshot|_by_[A-Z][a-z]+_[A-Z][a-z]+|'
    r'^pres(ident)?[\._]|_pres(ident)?[\._]|_president_of_)',
    re.IGNORECASE,
)


# ── .env loader ──────────────────────────────────────────────────────
def load_env():
    env_path = os.path.join(BASE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()
WIKIMEDIA_BOT_USER = os.environ.get("WIKIMEDIA_BOT_USER", "")
WIKIMEDIA_BOT_PASS = os.environ.get("WIKIMEDIA_BOT_PASS", "")


# ── HTTP w/ cookie jar (for optional bot login) ──────────────────────
_cookies = http.cookiejar.CookieJar()
_opener  = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies))
_opener.addheaders = [("User-Agent", UA), ("Accept-Encoding", "gzip")]

def http_json(url, *, data=None, timeout=60, max_retries=4, backoff=4.0):
    for attempt in range(max_retries):
        try:
            if data is not None:
                body = urllib.parse.urlencode(data).encode("utf-8")
                with _opener.open(urllib.request.Request(url, data=body), timeout=timeout) as r:
                    raw = r.read()
                    if r.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    return json.loads(raw)
            else:
                with _opener.open(url, timeout=timeout) as r:
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


# ── Optional bot login ──────────────────────────────────────────────
def login_wikimedia():
    if not (WIKIMEDIA_BOT_USER and WIKIMEDIA_BOT_PASS):
        print("  (no Wikimedia bot creds; using anonymous access)", file=sys.stderr)
        return False
    try:
        # Get login token
        tok = http_json(
            "https://en.wikipedia.org/w/api.php?"
            + urllib.parse.urlencode({
                "action": "query", "meta": "tokens", "type": "login", "format": "json",
            })
        )
        login_token = tok["query"]["tokens"]["logintoken"]
        # Submit clientlogin
        res = http_json(
            "https://en.wikipedia.org/w/api.php?action=login&format=json",
            data={
                "lgname":     WIKIMEDIA_BOT_USER,
                "lgpassword": WIKIMEDIA_BOT_PASS,
                "lgtoken":    login_token,
            },
        )
        status = res.get("login", {}).get("result")
        if status == "Success":
            print(f"  ✓ Logged in as {WIKIMEDIA_BOT_USER}", file=sys.stderr)
            return True
        print(f"  Bot login failed ({status}); continuing anonymously", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  Bot login error ({e}); continuing anonymously", file=sys.stderr)
        return False


# ── Parse / write presidents-data.js ────────────────────────────────
def parse_datafile(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'window\.PRESIDENTS_DATA\s*=\s*', text)
    if not m:
        raise ValueError("Cannot find window.PRESIDENTS_DATA")
    body = text[m.end():].rstrip().rstrip(';').rstrip()
    out_lines = []
    for line in body.split("\n"):
        stripped = line.lstrip()
        pm = re.match(r'^(\w+)(\s*:\s*)', stripped)
        if pm and not stripped.startswith('"'):
            indent = line[:len(line) - len(stripped)]
            line = f'{indent}"{pm.group(1)}":{stripped[pm.end()-1:]}'
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


# ── Wikipedia summary ────────────────────────────────────────────────
def fetch_summary(name):
    """Fetch intro paragraph for `name` from English Wikipedia."""
    title = name.replace(" ", "_")
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
        d = http_json(url)
    except Exception as e:
        print(f"    Wiki summary fetch failed for {name}: {e}", file=sys.stderr)
        return None

    pages = d.get("query", {}).get("pages", {})
    for pid, page in pages.items():
        if pid == "-1":
            return None
        extract = page.get("extract") or ""
        if not extract:
            return None
        # First paragraph
        para = next((p.strip() for p in extract.split("\n") if p.strip()), "")
        if not para:
            return None
        # Validate: should mention "President" or "United States" or "American"
        lower = para.lower()
        if not any(t in lower for t in ("president", "united states", "american")):
            print(f"    Skipping summary for {name} — extract doesn't mention President/US", file=sys.stderr)
            return None
        # Truncate at a sentence boundary
        if len(para) > SUMMARY_MAX:
            cut = para[:SUMMARY_MAX]
            last_period = cut.rfind(". ")
            if last_period > SUMMARY_MAX // 2:
                para = cut[:last_period + 1]
            else:
                para = cut.rstrip() + "…"
        return para
    return None


# ── Wikimedia Commons images ────────────────────────────────────────
def commons_category_files(name):
    """Fetch up to ~50 file titles from Commons category for `name`."""
    category = f"Category:{name}"
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "file",
        "cmlimit": "50",
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception as e:
        print(f"    Commons category fetch failed for {name}: {e}", file=sys.stderr)
        return []
    members = d.get("query", {}).get("categorymembers", [])
    return [m["title"] for m in members]


def commons_search_files(name, limit=30):
    """Search Commons for File: pages matching this president's name.
    Used as a fallback when the canonical category is too sparse."""
    # Quoted name + "portrait" surfaces photos; widely indexed.
    queries = [
        f'"{name}" portrait',
        f'"{name}" president',
        f'"{name}"',
    ]
    out = []
    seen = set()
    for q in queries:
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "list": "search",
            "srsearch": q,
            "srnamespace": "6",  # File:
            "srlimit": str(limit),
            "format": "json",
        })
        try:
            d = http_json(url)
        except Exception as e:
            print(f"    Commons search failed for {name}: {e}", file=sys.stderr)
            continue
        for m in d.get("query", {}).get("search", []):
            title = m.get("title", "")
            if title and title not in seen:
                seen.add(title)
                out.append(title)
        time.sleep(0.3)
        if len(out) >= limit:
            break
    return out


def commons_thumbnails(file_titles, width=600):
    """Batch-fetch URL + size for a list of File: titles. Returns dict
    title → {url, w, h}."""
    if not file_titles:
        return {}
    out = {}
    BATCH = 25
    for i in range(0, len(file_titles), BATCH):
        batch = file_titles[i:i + BATCH]
        url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "titles": "|".join(batch),
            "prop": "imageinfo",
            "iiprop": "url|size",
            "iiurlwidth": str(width),
            "format": "json",
        })
        try:
            d = http_json(url)
        except Exception as e:
            print(f"    Commons imageinfo failed: {e}", file=sys.stderr)
            continue
        pages = d.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            title = page.get("title", "")
            ii = page.get("imageinfo", [])
            if not ii:
                continue
            info = ii[0]
            thumb_url = info.get("thumburl") or info.get("url")
            if not thumb_url:
                continue
            tw = info.get("thumbwidth") or info.get("width") or width
            th = info.get("thumbheight") or info.get("height") or None
            out[title] = {"url": thumb_url, "w": tw, "h": th}
        time.sleep(0.4)
    return out


def fetch_canonical_portrait(wikidata_qid, width=600):
    """Fetch the canonical P18 portrait from Wikidata, returning
    {url, w, h} or None."""
    if not wikidata_qid:
        return None
    # Get P18 filename via wbgetentities
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetclaims",
        "entity": wikidata_qid,
        "property": "P18",
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception:
        return None
    claims = d.get("claims", {}).get("P18", [])
    if not claims:
        return None
    filename = claims[0].get("mainsnak", {}).get("datavalue", {}).get("value")
    if not filename:
        return None
    # Resolve via Commons imageinfo
    title = f"File:{filename}"
    info = commons_thumbnails([title], width=width)
    return info.get(title)


def filename_passes_name_filter(filename):
    """Pass 1 (filename-only): reject obvious non-portraits without
    needing a network call. Accepts filenames with either spaces or
    underscores — Commons titles use spaces, URLs use underscores."""
    # Normalize for token matching: spaces → underscores
    norm = filename.replace(" ", "_")
    if not IMAGE_KEEP_EXT.search(norm):
        return False
    if IMAGE_BAD_EXT_RE.search(norm):
        return False
    # Check exclude list. If every matched exclude token is in the
    # PORTRAIT_OVERRIDE set AND the filename also contains the word
    # "portrait" / "headshot", let it through.
    matches = [m.group(1).lower() for m in IMAGE_EXCLUDE_RE.finditer(norm)]
    if matches:
        if _PORTRAIT_HINT_RE.search(norm) and all(
            tok in IMAGE_EXCLUDE_TOKENS_PORTRAIT_OVERRIDE for tok in matches
        ):
            return True
        return False
    return True


def filter_portrait_files(file_titles):
    """Filename-pass for a list of `File:...` titles."""
    out = []
    for t in file_titles:
        # Strip 'File:' prefix for filename matching
        bare = t[5:] if t.lower().startswith("file:") else t
        if filename_passes_name_filter(bare):
            out.append(t)
    return out


def aspect_ratio_ok(w, h):
    """Return True if image dimensions look portrait-friendly."""
    if not w or not h:
        # Without dimensions we conservatively allow (we lose
        # nothing by not double-filtering when info is missing).
        return True
    try:
        w, h = int(w), int(h)
    except (TypeError, ValueError):
        return True
    if w <= 0 or h <= 0:
        return False
    if w / h > ASPECT_MAX_LANDSCAPE:
        return False
    if h / w > ASPECT_MAX_PORTRAIT:
        return False
    return True


def image_entry_passes(entry):
    """Re-validate an existing {url, w, h} entry against the new
    filters. Used by the resumable re-evaluation pass."""
    url = (entry or {}).get("url") or ""
    if not url:
        return False
    # Extract the filename portion of the Commons URL. Both /thumb/x/yy/<name>/...
    # and /commons/x/yy/<name> are handled.
    m = re.search(r'/commons/(?:thumb/)?[0-9a-f]/[0-9a-f]+/([^/]+)', url)
    if not m:
        # Unknown URL shape — drop it; we'd rather re-fetch.
        return False
    filename = urllib.parse.unquote(m.group(1))
    # If this is a thumb URL, the captured group is the original
    # filename; the trailing /NNNpx-... after the next slash is the thumb.
    # The capture above stops at the next '/', so we're good.
    if not filename_passes_name_filter(filename):
        return False
    if not aspect_ratio_ok(entry.get("w"), entry.get("h")):
        return False
    return True


def fetch_canonical_wikipedia_infobox(name, width=600):
    """Fallback: pageimage (infobox lead image) from the president's
    Wikipedia article."""
    title = name.replace(" ", "_")
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "titles": title,
        "prop": "pageimages",
        "piprop": "original|name",
        "redirects": "1",
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception:
        return None
    pages = d.get("query", {}).get("pages", {})
    for pid, page in pages.items():
        if pid == "-1":
            continue
        fname = page.get("pageimage")
        orig  = page.get("original") or {}
        if orig.get("source"):
            # Validate filename
            if fname and not filename_passes_name_filter(fname):
                return None
            w_, h_ = orig.get("width"), orig.get("height")
            if not aspect_ratio_ok(w_, h_):
                return None
            return {"url": orig["source"], "w": w_, "h": h_}
    return None


def fetch_images_for(name, wikidata_qid, existing=None):
    """Build a list of {url, w, h} dicts for `name`.

    If `existing` is given, those entries are re-validated against the
    new filter and reused first (preserving order). Then top up from
    Commons until we hit IMAGES_PER_PRESIDENT.
    """
    images = []
    seen_urls = set()

    # 0) Reuse existing entries that still pass the filter
    kept = 0
    dropped = 0
    if existing:
        for entry in existing:
            if image_entry_passes(entry):
                if entry["url"] in seen_urls:
                    continue
                seen_urls.add(entry["url"])
                images.append({
                    "url": entry["url"],
                    "w":   entry.get("w"),
                    "h":   entry.get("h"),
                })
                kept += 1
            else:
                dropped += 1

    # 1) Canonical P18 portrait — always try to put it first if missing.
    have_canonical = False
    for img in images:
        if "wikipedia/commons" in img["url"]:
            # We assume the first kept one is fine; canonical may or
            # may not already be present. We always add the P18 image
            # only if it isn't a dupe.
            break
    if len(images) < IMAGES_PER_PRESIDENT:
        canonical = fetch_canonical_portrait(wikidata_qid)
        if canonical and canonical.get("url") and canonical["url"] not in seen_urls:
            # Even for P18 portraits we honor the aspect check (skip if
            # the file is genuinely off-shape).
            if aspect_ratio_ok(canonical.get("w"), canonical.get("h")):
                # Insert at front for prominence.
                images.insert(0, {
                    "url": canonical["url"],
                    "w":   canonical["w"],
                    "h":   canonical["h"],
                })
                seen_urls.add(canonical["url"])
                have_canonical = True

    # 2) Commons category files
    files = []
    if len(images) < IMAGES_PER_PRESIDENT:
        files = filter_portrait_files(commons_category_files(name))

    # 3) If still short, fall back to Commons search (`"name" portrait`)
    if len(images) + len(files) < IMAGES_PER_PRESIDENT * 3:
        search_files = filter_portrait_files(commons_search_files(name))
        for s in search_files:
            if s not in files:
                files.append(s)

    # 4) Wikipedia infobox image fallback
    if len(images) < IMAGES_PER_PRESIDENT:
        infobox = fetch_canonical_wikipedia_infobox(name)
        if infobox and infobox["url"] not in seen_urls:
            images.append({
                "url": infobox["url"],
                "w":   infobox["w"],
                "h":   infobox["h"],
            })
            seen_urls.add(infobox["url"])

    # 5) Re-rank candidate file titles: portrait-y names first.
    def title_score(t):
        bare = t[5:] if t.lower().startswith("file:") else t
        return -1 if IMAGE_PREFER_RE.search(bare) else 0
    files.sort(key=title_score)

    # 6) Fetch info for ~30 candidates and filter by aspect ratio.
    info_map = commons_thumbnails(files[:30])
    for title in files:
        if len(images) >= IMAGES_PER_PRESIDENT:
            break
        info = info_map.get(title)
        if not info:
            continue
        if info["url"] in seen_urls:
            continue
        if not aspect_ratio_ok(info.get("w"), info.get("h")):
            continue
        seen_urls.add(info["url"])
        images.append({"url": info["url"], "w": info["w"], "h": info["h"]})

    return images, kept, dropped


# ── Main ────────────────────────────────────────────────────────────
def main():
    print("Enriching presidents-data.js…\n", file=sys.stderr)
    records = parse_datafile(DATAFILE)
    print(f"  {len(records)} records loaded\n", file=sys.stderr)

    login_wikimedia()

    # ── Step 1: Summaries ──────────────────────────────────────────
    print("  [1/2] Fetching Wikipedia summaries…", file=sys.stderr)
    # Dedupe by name (Cleveland, Trump → 2 cards each, 1 summary)
    needed = {}
    for rec in records:
        if rec.get("summary"):
            continue
        needed.setdefault(rec["name"], []).append(rec)
    print(f"    {len(needed)} unique presidents need summaries", file=sys.stderr)

    sum_count = 0
    for i, (name, recs) in enumerate(needed.items(), 1):
        print(f"    [{i}/{len(needed)}] {name}…", file=sys.stderr)
        summary = fetch_summary(name)
        if summary:
            sum_count += len(recs)
            for r in recs:
                r["summary"] = summary
        # Save after each successful fetch for resumability
        write_datafile(DATAFILE, records)
        time.sleep(0.7)

    print(f"  → {sum_count} summary rows populated\n", file=sys.stderr)

    # ── Step 2: Images (re-evaluate + top up) ──────────────────────
    print("  [2/2] Re-evaluating + refetching Wikimedia Commons portraits…", file=sys.stderr)

    # Count images before re-evaluation
    img_count_before = sum(len(r.get("images") or []) for r in records)

    # Group by name (handles Cleveland's two terms, Trump's two terms)
    by_name = {}
    for rec in records:
        by_name.setdefault(rec["name"], []).append(rec)

    skipped_already_clean = 0
    total = len(by_name)
    short_after = []      # presidents still under MIN_GOOD_IMAGES at end

    for i, (name, recs) in enumerate(by_name.items(), 1):
        qid = recs[0].get("wikidata")
        existing = recs[0].get("images") or []

        # Pre-check: how many existing pass the new filter?
        existing_kept = [e for e in existing if image_entry_passes(e)]
        if len(existing_kept) >= IMAGES_PER_PRESIDENT:
            # All 8 already pass — skip entirely (resumable)
            print(f"    [{i}/{total}] {name}: all "
                  f"{len(existing_kept)} pass filter, skipping",
                  file=sys.stderr)
            skipped_already_clean += 1
            continue

        try:
            images, kept, dropped = fetch_images_for(name, qid, existing=existing)
        except Exception as e:
            print(f"    [{i}/{total}] {name}: error {e}", file=sys.stderr)
            continue

        new_count = max(0, len(images) - kept)
        print(
            f"    [{i}/{total}] {name}: kept {kept}, "
            f"dropped {dropped}, fetched {new_count} new "
            f"→ {len(images)} total",
            file=sys.stderr,
        )

        if len(images) < MIN_GOOD_IMAGES:
            short_after.append((name, len(images)))

        for r in recs:
            r["images"] = images
        # Resumable: save after every president
        write_datafile(DATAFILE, records)
        time.sleep(0.5)

    img_count_after = sum(len(r.get("images") or []) for r in records)

    # Final write (already saved per-iteration, but harmless)
    write_datafile(DATAFILE, records)

    # Summary
    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    with_summary = sum(1 for r in records if r.get("summary"))
    with_images = sum(1 for r in records if r.get("images"))
    print(f"  With summary: {with_summary} / {len(records)}", file=sys.stderr)
    print(f"  With images:  {with_images} / {len(records)}", file=sys.stderr)
    print(f"  Skipped (already clean): {skipped_already_clean}",
          file=sys.stderr)
    print(f"  Images total: {img_count_before} → {img_count_after}",
          file=sys.stderr)
    if short_after:
        print(f"  Presidents with < {MIN_GOOD_IMAGES} images:",
              file=sys.stderr)
        for n, c in short_after:
            print(f"    • {n}: {c}", file=sys.stderr)
    else:
        print(f"  All presidents have ≥ {MIN_GOOD_IMAGES} images",
              file=sys.stderr)
    print(f"\n  Written to {DATAFILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
