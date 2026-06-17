#!/usr/bin/env python3
"""
Use Claude Haiku 4.5 vision to verify that each image in
`presidents-data.js` actually shows the named president as the primary
subject.

For each president × image:
  - Ask Claude: does this clearly show <President Name>?  YES / NO / UNCLEAR
  - Drop NO. Keep YES and UNCLEAR (be conservative — only drop confident rejects).

Resumable: caches per-URL verdicts to /tmp/president_image_verifications.json
so re-runs skip already-verified URLs.

Reads ANTHROPIC_API_KEY from .env (same pattern as scan_spoilers.py).

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
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DATAFILE = os.path.join(ROOT, "presidents-data.js")
CACHE_PATH = "/tmp/president_image_verifications.json"

MODEL = "claude-haiku-4-5-20251001"
API = "https://api.anthropic.com/v1/messages"
RATE_LIMIT_SECONDS = 1.0
MIN_IMAGES_WARN = 4

# Wikimedia blocks the default Anthropic image fetcher's User-Agent (and
# requires a contact UA per their policy), so we download the bytes
# ourselves with a proper UA and send them as base64.
UA = "Crammys/1.0 (flashcard app; brett.gustafson@gmail.com)"

# ── .env loader ──────────────────────────────────────────────────────
def load_env():
    env = {}
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()
API_KEY = ENV.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    print("ANTHROPIC_API_KEY not found in .env or environment", file=sys.stderr)
    sys.exit(1)


# ── Load presidents-data.js via Node (same as validate_all.py) ──────
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


# ── Write presidents-data.js (mirrors enrich_presidents.py) ─────────
FIELD_ORDER = [
    "name", "wikidata", "term", "yearStart", "yearEnd",
    "party", "vps", "predecessor", "successor",
    "born", "died", "homeState",
    "notable", "summary", "images",
    "wikipedia", "spotify",
]


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


# ── Cache ────────────────────────────────────────────────────────────
def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: failed to load cache ({e}); starting fresh", file=sys.stderr)
    return {}


def save_cache(cache):
    tmp = CACHE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=1)
    os.replace(tmp, CACHE_PATH)


# ── Claude vision call ──────────────────────────────────────────────
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
    """Download an image with a proper User-Agent. Returns bytes or None."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        print(f"  Image fetch failed for {url}: {e}", file=sys.stderr)
        return None


def verify_image(url, name, max_retries=3):
    """Return one of: 'YES', 'NO', 'UNCLEAR', or None on error."""
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
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
            text = (resp.get("content") or [{}])[0].get("text", "").strip().upper()
            # Pull the first occurrence of YES/NO/UNCLEAR
            m = re.search(r"\b(YES|NO|UNCLEAR)\b", text)
            if m:
                return m.group(1)
            # If Claude returned something else, treat as UNCLEAR (conservative)
            return "UNCLEAR"
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore") if hasattr(e, "read") else str(e)
            # 429/5xx: back off and retry. Bad image (4xx) — give up.
            if e.code in (429, 500, 502, 503, 529):
                wait = 4 * (attempt + 1)
                print(f"  HTTP {e.code} — sleeping {wait}s ({msg[:200]})", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  HTTP {e.code} for {url}: {msg[:200]}", file=sys.stderr)
            return None
        except Exception as e:
            wait = 2 * (attempt + 1)
            print(f"  Error ({e}) — retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
    return None


# ── Main ────────────────────────────────────────────────────────────
def main():
    print("Verifying president images with Claude Haiku vision…", file=sys.stderr)
    records = load_presidents_via_node(DATAFILE)
    print(f"  Loaded {len(records)} president records", file=sys.stderr)

    cache = load_cache()
    print(f"  Cache: {len(cache)} URLs already verified", file=sys.stderr)

    total_verified = 0
    total_kept = 0
    total_dropped = 0
    short_after = []
    errors = []

    n_presidents = len(records)
    # Group records by name (Cleveland served twice — same images shared)
    # but we'll process each record's images independently; this keeps the
    # logic simple. If two records have the same image URL, the cache
    # handles deduplication.
    for i, rec in enumerate(records, 1):
        name = rec.get("name") or "?"
        images = rec.get("images") or []
        if not images:
            print(f"[{i}/{n_presidents}] {name}: no images, skipping", file=sys.stderr)
            continue

        kept_imgs = []
        dropped_short = []
        for img in images:
            url = img.get("url")
            if not url:
                # Malformed — drop it
                total_dropped += 1
                continue

            verdict = cache.get(url)
            if verdict is None:
                verdict = verify_image(url, name)
                total_verified += 1
                if verdict is None:
                    # Error: be conservative, keep the image
                    errors.append((name, url))
                    kept_imgs.append(img)
                    time.sleep(RATE_LIMIT_SECONDS)
                    continue
                cache[url] = verdict
                save_cache(cache)
                time.sleep(RATE_LIMIT_SECONDS)

            if verdict == "NO":
                total_dropped += 1
                # Capture a short filename for the progress line
                fname = url.rsplit("/", 1)[-1][:60]
                dropped_short.append(fname)
            else:
                # YES or UNCLEAR — keep
                kept_imgs.append(img)
                total_kept += 1

        rec["images"] = kept_imgs

        dropped_label = ""
        if dropped_short:
            dropped_label = f" (dropped {', '.join(dropped_short[:2])}"
            if len(dropped_short) > 2:
                dropped_label += f", +{len(dropped_short)-2} more"
            dropped_label += ")"
        print(
            f"[{i}/{n_presidents}] {name}: kept {len(kept_imgs)}/{len(images)}{dropped_label}",
            file=sys.stderr,
        )

        if len(kept_imgs) < MIN_IMAGES_WARN:
            short_after.append((name, len(kept_imgs)))

        # Save the datafile after every president so a crash mid-run
        # doesn't lose progress.
        write_datafile(DATAFILE, records)

    # Final write (already saved per-iter, but harmless).
    write_datafile(DATAFILE, records)

    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Total images verified this run: {total_verified}", file=sys.stderr)
    print(f"  Total kept (YES + UNCLEAR):    {total_kept}", file=sys.stderr)
    print(f"  Total dropped (NO):            {total_dropped}", file=sys.stderr)
    if errors:
        print(f"  Errors (kept conservatively):  {len(errors)}", file=sys.stderr)
        for n, u in errors[:5]:
            print(f"    • {n}: {u[:80]}", file=sys.stderr)
    if short_after:
        print(f"\n  Presidents now below {MIN_IMAGES_WARN} images:", file=sys.stderr)
        for n, c in short_after:
            print(f"    • {n}: {c} images", file=sys.stderr)
    else:
        print(f"\n  All presidents still have >= {MIN_IMAGES_WARN} images", file=sys.stderr)
    print(f"\n  Written to {DATAFILE}", file=sys.stderr)
    print(f"  Cache at {CACHE_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
