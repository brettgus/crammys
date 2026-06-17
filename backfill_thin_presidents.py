#!/usr/bin/env python3
"""
Backfill images for the 8 US Presidents whose `images` arrays fell
below 4 entries after the Claude Haiku vision-verification cleanup.

For each target president:
  1. Pull candidate File: titles from multiple Wikimedia Commons
     entry points:
       - Search:  "<full name>" portrait
                  "<full name>" official
                  "<surname>" president
       - Category:Portraits of <full name>
       - Category:Photographs of <full name>
       - Category:Paintings of <full name>
       - English Wikipedia article page-image (prop=pageimages, piprop=original)
  2. Apply the filename heuristic filter from enrich_presidents.py.
  3. Resolve thumbnail URLs via Commons imageinfo.
  4. Drop URLs that are already in the president's existing `images`.
  5. Verify the remaining candidates with Claude Haiku 4.5 vision
     using the YES/NO/UNCLEAR prompt from verify_president_images.py.
  6. Append YES verdicts (only) until the array has 8 entries (or we
     run out of candidates).

Resumable: progress is written after every president. We never remove
existing entries.

Usage:  python3 backfill_thin_presidents.py
Stdlib only.
"""

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import http.cookiejar

# ── Reuse helpers from sibling scripts ───────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from enrich_presidents import (
    filename_passes_name_filter,
    filter_portrait_files,
    aspect_ratio_ok,
    IMAGE_PREFER_RE,
)

ROOT = os.path.dirname(os.path.abspath(__file__))
DATAFILE = os.path.join(ROOT, "presidents-data.js")
CACHE_PATH = "/tmp/president_image_verifications.json"

UA = "Crammys/1.0 (flashcard app; brett.gustafson@gmail.com)"

MODEL = "claude-haiku-4-5-20251001"
API = "https://api.anthropic.com/v1/messages"

TARGET_IMAGES = 8                # top up to this many total
WIKIMEDIA_RATE_LIMIT = 1.0       # seconds between Commons / Wikipedia calls
ANTHROPIC_RATE_LIMIT = 0.5       # seconds between vision calls
MAX_CANDIDATES_PER_PRES = 25     # cap how many candidates we vision-check

# Term numbers for the 8 thin presidents (from the prompt).
TARGET_TERMS = [1, 3, 16, 25, 26, 32, 33, 40]

# Extra search-query aliases for presidents whose canonical name is
# ambiguous (Roosevelt × 2) or commonly searched under a nickname/initials.
# These are appended to the standard query list inside collect_candidates.
EXTRA_QUERIES = {
    "Franklin D. Roosevelt": [
        '"Franklin Delano Roosevelt" portrait',
        '"FDR" president portrait',
        '"Franklin D. Roosevelt" 1944 portrait',
        '"Franklin D. Roosevelt" 1933',
    ],
    "Theodore Roosevelt": [
        '"Theodore Roosevelt" 1904 portrait',
        '"Theodore Roosevelt" rough rider',
        '"Roosevelt" Theodore portrait',
    ],
    "Harry S. Truman": [
        '"Harry Truman" portrait',
        '"Harry S Truman" portrait',
    ],
}


# ── .env loader (matches sibling scripts) ────────────────────────────
def load_env():
    env_path = os.path.join(ROOT, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env()
ANTHROPIC_KEY      = os.environ.get("ANTHROPIC_API_KEY")
WIKIMEDIA_BOT_USER = os.environ.get("WIKIMEDIA_BOT_USER", "")
WIKIMEDIA_BOT_PASS = os.environ.get("WIKIMEDIA_BOT_PASS", "")

if not ANTHROPIC_KEY:
    print("ANTHROPIC_API_KEY not found in .env or environment", file=sys.stderr)
    sys.exit(1)


# ── HTTP w/ cookie jar (mirrors enrich_presidents.py) ────────────────
_cookies = http.cookiejar.CookieJar()
_opener  = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies))
_opener.addheaders = [("User-Agent", UA)]


def http_json(url, *, data=None, timeout=60, max_retries=4, backoff=4.0):
    for attempt in range(max_retries):
        try:
            if data is not None:
                body = urllib.parse.urlencode(data).encode("utf-8")
                with _opener.open(urllib.request.Request(url, data=body), timeout=timeout) as r:
                    return json.loads(r.read())
            with _opener.open(url, timeout=timeout) as r:
                return json.loads(r.read())
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


def login_wikimedia():
    """Best-effort bot login for higher rate limits. Falls back silently."""
    if not (WIKIMEDIA_BOT_USER and WIKIMEDIA_BOT_PASS):
        print("  (no Wikimedia bot creds; anonymous)", file=sys.stderr)
        return False
    try:
        tok = http_json(
            "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query", "meta": "tokens", "type": "login", "format": "json",
            })
        )
        login_token = tok["query"]["tokens"]["logintoken"]
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
            print(f"  Logged in as {WIKIMEDIA_BOT_USER}", file=sys.stderr)
            return True
        print(f"  Bot login failed ({status}); anonymous", file=sys.stderr)
    except Exception as e:
        print(f"  Bot login error ({e}); anonymous", file=sys.stderr)
    return False


# ── presidents-data.js round-trip (matches sibling scripts) ──────────
def load_presidents_via_node(filepath):
    cmd = [
        "node", "-e",
        (
            "global.window={};"
            f"eval(require('fs').readFileSync('{filepath}','utf8'));"
            "process.stdout.write(JSON.stringify(window.PRESIDENTS_DATA));"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Node eval failed for {filepath}:\n{res.stderr}")
    return json.loads(res.stdout)


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


# Include entryNote/exitNote here so we don't accidentally strip them.
FIELD_ORDER = [
    "name", "wikidata", "term", "yearStart", "yearEnd",
    "party", "vps", "predecessor", "successor",
    "born", "died", "homeState",
    "notable", "summary", "images",
    "entryNote", "exitNote",
    "wikipedia", "spotify",
]


def write_datafile(path, records):
    lines = ["window.PRESIDENTS_DATA = ["]
    for i, rec in enumerate(records):
        obj_parts = []
        # Emit known fields first in canonical order.
        for k in FIELD_ORDER:
            if k not in rec:
                continue
            obj_parts.append(f"  {k}: {js_val(rec[k])}")
        # Then any unexpected extra keys — preserves data we didn't anticipate.
        for k, v in rec.items():
            if k in FIELD_ORDER:
                continue
            obj_parts.append(f"  {k}: {js_val(v)}")
        sep = "," if i < len(records) - 1 else ""
        lines.append("{\n" + ",\n".join(obj_parts) + "\n}" + sep)
    lines.append("];")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ── Commons / Wikipedia search ───────────────────────────────────────
def commons_search_files(query, limit=20):
    """Search Commons File: namespace for `query`. Returns list of titles."""
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",
        "srlimit": str(limit),
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception as e:
        print(f"    Commons search failed ({query!r}): {e}", file=sys.stderr)
        return []
    return [m.get("title", "") for m in d.get("query", {}).get("search", []) if m.get("title")]


def commons_category_files(category, limit=50):
    """Fetch File: members of a Commons category. Tolerates missing categories."""
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "categorymembers",
        "cmtitle": category,
        "cmtype": "file",
        "cmlimit": str(limit),
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception as e:
        print(f"    Commons category failed ({category!r}): {e}", file=sys.stderr)
        return []
    return [m["title"] for m in d.get("query", {}).get("categorymembers", []) if m.get("title")]


def wikipedia_page_image(name):
    """Return the en.wikipedia.org infobox lead image as {url,w,h} or None."""
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
        if not orig.get("source"):
            continue
        if fname and not filename_passes_name_filter(fname):
            return None
        if not aspect_ratio_ok(orig.get("width"), orig.get("height")):
            return None
        return {
            "url": orig["source"],
            "w":   orig.get("width"),
            "h":   orig.get("height"),
            "title": f"File:{fname}" if fname else None,
        }
    return None


def commons_thumbnails(file_titles, width=600):
    """Batch lookup imageinfo for File: titles. Returns dict title→{url,w,h}."""
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
            out[title] = {
                "url": thumb_url,
                "w": info.get("thumbwidth") or info.get("width"),
                "h": info.get("thumbheight") or info.get("height"),
            }
        time.sleep(WIKIMEDIA_RATE_LIMIT)
    return out


# ── Candidate collection ─────────────────────────────────────────────
def collect_candidates(name):
    """Return an ordered, de-duplicated list of File: titles to evaluate.

    Tries multiple Wikimedia entry points, applies the filename
    heuristic, and ranks portrait-y filenames first.
    """
    surname = name.split()[-1]

    queries = [
        f'"{name}" portrait',
        f'"{name}" official',
        f'"{surname}" president',
    ]
    queries.extend(EXTRA_QUERIES.get(name, []))
    categories = [
        f"Category:Portraits of {name}",
        f"Category:Photographs of {name}",
        f"Category:Paintings of {name}",
        f"Category:{name}",
    ]

    seen = set()
    titles = []

    for q in queries:
        for t in commons_search_files(q, limit=20):
            if t not in seen:
                seen.add(t)
                titles.append(t)
        time.sleep(WIKIMEDIA_RATE_LIMIT)

    for cat in categories:
        for t in commons_category_files(cat, limit=50):
            if t not in seen:
                seen.add(t)
                titles.append(t)
        time.sleep(WIKIMEDIA_RATE_LIMIT)

    # Filename filter
    titles = filter_portrait_files(titles)

    # Rank portrait-y filenames first.
    def score(t):
        bare = t[5:] if t.lower().startswith("file:") else t
        return -1 if IMAGE_PREFER_RE.search(bare) else 0
    titles.sort(key=score)

    return titles


# ── Claude vision verification (mirrors verify_president_images.py) ──
PROMPT_TEMPLATE = (
    "You are validating an image that is supposed to depict U.S. President {name}. "
    "The image was sourced from a Wikimedia Commons category labeled for {name}.\n\n"
    "Question: Is this image plausibly a depiction (portrait, photograph, painting, "
    "engraving, drawing, etc.) of {name} himself as the primary subject?\n\n"
    "- Answer YES if the image shows a person or likeness that is consistent with "
    "known depictions of {name} (you may rely on famous portraits, typical period "
    "dress, and general appearance — you do not need to be 100% certain).\n"
    "- Answer NO only if you are confident the image clearly shows something else "
    "as the primary subject (e.g. a different identifiable person, a document, a "
    "building, a landscape, a child, an object, a scene without him).\n"
    "- Answer UNCLEAR if you cannot tell.\n\n"
    "Respond with exactly one word: YES, NO, or UNCLEAR."
)


def url_media_type(url):
    lower = url.lower().split("?", 1)[0]
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def fetch_image_bytes(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        print(f"    Image fetch failed for {url}: {e}", file=sys.stderr)
        return None


def verify_image(url, name, max_retries=3):
    """Return 'YES' / 'NO' / 'UNCLEAR' / None."""
    img_bytes = fetch_image_bytes(url)
    if img_bytes is None:
        return None
    b64 = base64.b64encode(img_bytes).decode()
    body = {
        "model": MODEL,
        "max_tokens": 10,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": url_media_type(url),
                        "data": b64,
                    },
                },
                {"type": "text", "text": PROMPT_TEMPLATE.format(name=name)},
            ],
        }],
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            text = (resp.get("content") or [{}])[0].get("text", "").strip().upper()
            m = re.search(r"\b(YES|NO|UNCLEAR)\b", text)
            return m.group(1) if m else "UNCLEAR"
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore") if hasattr(e, "read") else str(e)
            if e.code in (429, 500, 502, 503, 529):
                wait = 4 * (attempt + 1)
                print(f"    HTTP {e.code} — sleeping {wait}s ({msg[:120]})", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"    HTTP {e.code} for {url}: {msg[:120]}", file=sys.stderr)
            return None
        except Exception as e:
            wait = 2 * (attempt + 1)
            print(f"    Error ({e}) — retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None


# ── Verdict cache (shared with verify_president_images.py) ───────────
def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"  Warning: cache load failed ({e}); starting fresh", file=sys.stderr)
    return {}


def save_cache(cache):
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)
    os.replace(tmp, CACHE_PATH)


# ── Main ────────────────────────────────────────────────────────────
def main():
    print("Backfilling thin presidents…", file=sys.stderr)
    records = load_presidents_via_node(DATAFILE)
    print(f"  Loaded {len(records)} records", file=sys.stderr)

    login_wikimedia()
    cache = load_cache()
    print(f"  Cache: {len(cache)} URLs already verified", file=sys.stderr)

    # Group records by name (Cleveland's two terms share images).
    by_name = {}
    for rec in records:
        by_name.setdefault(rec["name"], []).append(rec)

    # Build target list, in term order, keyed by representative name.
    targets = []
    seen_names = set()
    for term in TARGET_TERMS:
        match = next((r for r in records if r.get("term") == term), None)
        if not match:
            print(f"  No record found for term {term} — skipping", file=sys.stderr)
            continue
        nm = match["name"]
        if nm in seen_names:
            continue
        seen_names.add(nm)
        targets.append(nm)

    final_counts = []  # (name, before, after)

    for i, name in enumerate(targets, 1):
        recs = by_name[name]
        existing = list(recs[0].get("images") or [])
        existing_urls = {img.get("url") for img in existing if img.get("url")}
        starting = len(existing)

        if starting >= TARGET_IMAGES:
            print(f"[{i}/{len(targets)}] {name}: already has {starting} images, skipping",
                  file=sys.stderr)
            final_counts.append((name, starting, starting))
            continue

        # 1) Collect candidates
        candidate_titles = collect_candidates(name)

        # 2) Resolve thumbnail info; drop dupes vs. existing & dimension-bad
        # Cap how many we fetch info for, to limit API spend.
        info_map = commons_thumbnails(candidate_titles[:MAX_CANDIDATES_PER_PRES * 2])

        # 2a) Wikipedia infobox image — append to the candidate pool.
        page_img = wikipedia_page_image(name)
        time.sleep(WIKIMEDIA_RATE_LIMIT)

        ordered_candidates = []  # list of {url, w, h}
        if page_img and page_img.get("url") not in existing_urls:
            ordered_candidates.append({
                "url": page_img["url"],
                "w":   page_img["w"],
                "h":   page_img["h"],
            })

        for title in candidate_titles:
            info = info_map.get(title)
            if not info:
                continue
            url = info.get("url")
            if not url or url in existing_urls:
                continue
            if not aspect_ratio_ok(info.get("w"), info.get("h")):
                continue
            ordered_candidates.append({
                "url": url,
                "w":   info.get("w"),
                "h":   info.get("h"),
            })
            if len(ordered_candidates) >= MAX_CANDIDATES_PER_PRES:
                break

        # De-dupe within the candidate pool itself.
        seen_pool = set()
        deduped = []
        for c in ordered_candidates:
            if c["url"] in seen_pool:
                continue
            seen_pool.add(c["url"])
            deduped.append(c)
        ordered_candidates = deduped

        need = TARGET_IMAGES - starting
        verified_new = []
        rejected = 0
        unclear  = 0
        errored  = 0
        n_verified_this_pres = 0

        for cand in ordered_candidates:
            if len(verified_new) >= need:
                break
            url = cand["url"]
            verdict = cache.get(url)
            if verdict is None:
                verdict = verify_image(url, name)
                n_verified_this_pres += 1
                if verdict is None:
                    errored += 1
                    time.sleep(ANTHROPIC_RATE_LIMIT)
                    continue
                cache[url] = verdict
                save_cache(cache)
                time.sleep(ANTHROPIC_RATE_LIMIT)

            if verdict == "YES":
                verified_new.append(cand)
            elif verdict == "NO":
                rejected += 1
            else:
                unclear += 1

        new_images = existing + verified_new
        ending = len(new_images)

        for r in recs:
            r["images"] = new_images

        # Resumable: save after every president.
        write_datafile(DATAFILE, records)

        print(
            f"[{i}/{len(targets)}] {name}: "
            f"{starting} existing + {len(verified_new)} new candidates verified, "
            f"ending at {ending} images "
            f"(checked {n_verified_this_pres} this run, "
            f"rejected {rejected}, unclear {unclear}, errors {errored})",
            file=sys.stderr,
        )

        final_counts.append((name, starting, ending))

    # Final write (harmless if no changes since last per-iter write).
    write_datafile(DATAFILE, records)

    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("  Final image counts:", file=sys.stderr)
    for name, before, after in final_counts:
        arrow = "→" if before != after else "="
        print(f"    {name}: {before} {arrow} {after}", file=sys.stderr)
    print(f"\n  Cache at {CACHE_PATH}", file=sys.stderr)
    print(f"  Written to {DATAFILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
