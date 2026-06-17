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

# Filter out Commons files that are clearly not portraits.
IMAGE_EXCLUDE_RE = re.compile(
    r'(tomb|memorial|statue|gravestone|signature|grave\b|sculpture|bust|'
    r'plaque|coin|stamp|mural|monument|cemetery|burial|headstone|'
    r'\.svg$|\.ogg$|\.ogv$|\.webm$|\.pdf$|\.mid$|\.midi$|\.flac$|\.wav$)',
    re.IGNORECASE,
)
IMAGE_KEEP_EXT = re.compile(r'\.(jpe?g|png|tiff?|gif)$', re.IGNORECASE)


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


def filter_portrait_files(file_titles):
    """Keep only JPG/PNG/TIFF/GIF that don't match the exclusion list."""
    out = []
    for t in file_titles:
        if not IMAGE_KEEP_EXT.search(t):
            continue
        if IMAGE_EXCLUDE_RE.search(t):
            continue
        out.append(t)
    return out


def fetch_images_for(name, wikidata_qid):
    """Return list of {url, w, h} dicts, P18 first, then top Commons
    category files."""
    images = []
    # 1) Canonical P18 first
    canonical = fetch_canonical_portrait(wikidata_qid)
    canonical_url = None
    if canonical and canonical.get("url"):
        images.append({"url": canonical["url"], "w": canonical["w"], "h": canonical["h"]})
        canonical_url = canonical["url"]

    # 2) Commons category files
    files = commons_category_files(name)
    files = filter_portrait_files(files)

    # If the canonical category was empty or all-non-portraits, fall
    # back to Commons file search. Modern presidents in particular have
    # categories that only contain subcategories and audio files.
    if len(files) < IMAGES_PER_PRESIDENT:
        search_files = filter_portrait_files(commons_search_files(name))
        # Append search results, dedupe later
        for s in search_files:
            if s not in files:
                files.append(s)

    # Get thumbnails (up to 40 candidates)
    info_map = commons_thumbnails(files[:40])
    seen_urls = {canonical_url} if canonical_url else set()
    for title in files:
        if len(images) >= IMAGES_PER_PRESIDENT:
            break
        info = info_map.get(title)
        if not info:
            continue
        if info["url"] in seen_urls:
            continue
        seen_urls.add(info["url"])
        images.append({"url": info["url"], "w": info["w"], "h": info["h"]})

    return images


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

    # ── Step 2: Images ──────────────────────────────────────────────
    print("  [2/2] Fetching Wikimedia Commons portraits…", file=sys.stderr)
    needed_img = {}
    for rec in records:
        if rec.get("images"):
            continue
        needed_img.setdefault(rec["name"], []).append(rec)
    print(f"    {len(needed_img)} unique presidents need images", file=sys.stderr)

    img_count = 0
    for i, (name, recs) in enumerate(needed_img.items(), 1):
        qid = recs[0].get("wikidata")
        print(f"    [{i}/{len(needed_img)}] {name} ({qid})…", file=sys.stderr)
        try:
            images = fetch_images_for(name, qid)
        except Exception as e:
            print(f"      error: {e}", file=sys.stderr)
            images = []
        if images:
            img_count += len(recs) * len(images)
            for r in recs:
                r["images"] = images
            print(f"      → {len(images)} images", file=sys.stderr)
        else:
            print(f"      → no images found", file=sys.stderr)
        # Save after each successful fetch for resumability
        write_datafile(DATAFILE, records)
        time.sleep(0.7)

    print(f"  → {img_count} image entries populated\n", file=sys.stderr)

    # Final write (already saved per-iteration, but harmless)
    write_datafile(DATAFILE, records)

    # Summary
    print("=" * 60, file=sys.stderr)
    with_summary = sum(1 for r in records if r.get("summary"))
    with_images = sum(1 for r in records if r.get("images"))
    print(f"  With summary: {with_summary} / {len(records)}", file=sys.stderr)
    print(f"  With images:  {with_images} / {len(records)}", file=sys.stderr)
    print(f"\n  Written to {DATAFILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
