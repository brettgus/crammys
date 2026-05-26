#!/usr/bin/env python3
"""
Enrich rockhall-data.js with studio album discographies from MusicBrainz.

Usage:  python3 enrich_discography.py

For each artist with a MusicBrainz ID, fetches up to 10 studio albums
(release-groups of primary type "Album") sorted by release date.

Resumable: skips entries that already have a non-empty `albums` array.
Progress output goes to stderr.
"""
import sys, json, re, time, urllib.request, urllib.parse, urllib.error, gzip

UA = "Crammys/1.0 (brett.gustafson@gmail.com)"
DATAFILE = "rockhall-data.js"
MB_BASE = "https://musicbrainz.org/ws/2"
MAX_ALBUMS = 10
SLEEP_BETWEEN = 1.1  # MusicBrainz rate-limit: 1 req/sec


# ── HTTP helper ─────────────────────────────────────────────────────
def http_get(url, *, timeout=30, max_retries=5, backoff=3.0):
    """Fetch URL with retries and exponential backoff on 503."""
    hdrs = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
    }
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
                wait = backoff * (2 ** attempt)
                print(f"  HTTP {e.code} — retrying in {wait:.1f}s…", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt < max_retries - 1:
                wait = backoff * (2 ** attempt)
                print(f"  Error ({e}) — retrying in {wait:.1f}s…", file=sys.stderr)
                time.sleep(wait)
                continue
            raise


# ── Parse rockhall-data.js ──────────────────────────────────────────
def parse_datafile(path):
    """Read rockhall-data.js and return list of dicts."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    m = re.search(r'window\.ROCKHALL_DATA\s*=\s*\[', text)
    if not m:
        raise ValueError("Cannot find window.ROCKHALL_DATA array in file")

    array_text = text[m.start():]
    array_text = re.sub(r'^window\.ROCKHALL_DATA\s*=\s*', '', array_text)
    array_text = array_text.rstrip().rstrip(';').rstrip()

    out_lines = []
    for line in array_text.split("\n"):
        stripped = line.lstrip()

        prop_match = re.match(r'^(\w+)(\s*:\s*)', stripped)
        if prop_match and not stripped.startswith('"'):
            indent = line[:len(line) - len(stripped)]
            key = prop_match.group(1)
            rest = stripped[prop_match.end():]
            line = f'{indent}"{key}": {rest}'

        if re.search(r'\{\s*\w+\s*:', line):
            def _quote_inline_keys(m):
                block = m.group(0)
                block = re.sub(r'(?<=\{)\s*(\w+)\s*:', r' "\1":', block)
                block = re.sub(r',\s*(\w+)\s*:', r', "\1":', block)
                return block
            line = re.sub(r'\{[^}]+\}', _quote_inline_keys, line)

        out_lines.append(line)

    json_text = "\n".join(out_lines)
    json_text = re.sub(r',\s*([}\]])', r'\1', json_text)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        lines = json_text.split('\n')
        lineno = e.lineno - 1
        start = max(0, lineno - 3)
        end = min(len(lines), lineno + 4)
        context = '\n'.join(f"  {i+1:5d} | {lines[i]}" for i in range(start, end))
        raise ValueError(f"JSON parse error at line {e.lineno}, col {e.colno}: {e.msg}\n{context}")

    return data


# ── Write rockhall-data.js ──────────────────────────────────────────
def js_val(v):
    """Convert a Python value to JS literal with unquoted keys."""
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


FIELD_ORDER = [
    "name", "wikidata", "year", "inductions", "category",
    "type", "genres", "country", "born", "died",
    "formed", "disbanded", "image", "description",
    "members", "musicbrainz", "spotify",
    "inductedBy", "summary", "wikipedia",
    "albums",
]


def write_datafile(path, records):
    """Write records back in the same unquoted-keys JS format."""
    lines = []
    for rec in records:
        obj_parts = []
        written = set()
        for key in FIELD_ORDER:
            if key not in rec:
                continue
            val = rec[key]
            written.add(key)
            if key == "inductions":
                induction_items = []
                for ind in val:
                    induction_items.append(
                        f"{{ year: {js_val(ind.get('year'))}, category: {js_val(ind.get('category'))} }}"
                    )
                obj_parts.append(f"  inductions: [{', '.join(induction_items)}]")
            elif key == "albums":
                if val:
                    album_items = []
                    for alb in val:
                        album_items.append(f"{{ title: {js_val(alb.get('title'))}, year: {js_val(alb.get('year'))} }}")
                    obj_parts.append(f"  albums: [{', '.join(album_items)}]")
                else:
                    obj_parts.append(f"  albums: []")
            else:
                obj_parts.append(f"  {key}: {js_val(val)}")
        # Any extra fields not in FIELD_ORDER
        for key, val in rec.items():
            if key not in written:
                obj_parts.append(f"  {key}: {js_val(val)}")
        lines.append("{\n" + ",\n".join(obj_parts) + "\n}")

    js_content = "window.ROCKHALL_DATA = [\n" + ",\n".join(lines) + "\n];\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(js_content)


# ── MusicBrainz fetcher ─────────────────────────────────────────────
def fetch_studio_albums(mbid):
    """Fetch studio albums for an artist from MusicBrainz.
    Returns list of { title, year } dicts sorted by year, up to MAX_ALBUMS."""
    url = f"{MB_BASE}/release-group?artist={mbid}&type=album&limit=100&fmt=json"
    data = http_get(url)

    albums = []
    for rg in data.get("release-groups", []):
        # Only primary type "Album" — skip compilations, EPs, singles, etc.
        primary = rg.get("primary-type", "")
        if primary != "Album":
            continue
        # Exclude entries with secondary types (live, compilation, remix, etc.)
        secondary = rg.get("secondary-types", [])
        if secondary:
            continue

        title = rg.get("title", "")
        frd = rg.get("first-release-date", "")
        year = None
        if frd and len(frd) >= 4:
            try:
                year = int(frd[:4])
            except ValueError:
                pass

        if title:
            albums.append({"title": title, "year": year})

    # Sort by year (None last)
    albums.sort(key=lambda a: (a["year"] is None, a["year"] or 9999))

    # Take up to MAX_ALBUMS
    return albums[:MAX_ALBUMS]


# ── Main ────────────────────────────────────────────────────────────
def main():
    print("Loading rockhall-data.js…", file=sys.stderr)
    records = parse_datafile(DATAFILE)
    total = len(records)
    print(f"Loaded {total} records", file=sys.stderr)

    fetched = 0
    skipped = 0
    no_mbid = 0
    errors = 0

    for i, rec in enumerate(records):
        name = rec.get("name", "?")

        # Resumable: skip if already has albums
        if rec.get("albums") and len(rec["albums"]) > 0:
            skipped += 1
            continue

        mbid = rec.get("musicbrainz")
        if not mbid:
            no_mbid += 1
            print(f"[{i+1}/{total}] {name} — no MusicBrainz ID, skipping", file=sys.stderr)
            continue

        try:
            albums = fetch_studio_albums(mbid)
            rec["albums"] = albums
            fetched += 1
            print(f"[{i+1}/{total}] {name} ({len(albums)} albums)", file=sys.stderr)
        except Exception as e:
            errors += 1
            print(f"[{i+1}/{total}] {name} — ERROR: {e}", file=sys.stderr)
            rec["albums"] = []

        # Save progress after each fetch (resumable)
        write_datafile(DATAFILE, records)

        # Rate limit
        time.sleep(SLEEP_BETWEEN)

    # Final write
    write_datafile(DATAFILE, records)

    print(f"\n── Done ──", file=sys.stderr)
    print(f"Fetched:  {fetched}", file=sys.stderr)
    print(f"Skipped:  {skipped} (already had albums)", file=sys.stderr)
    print(f"No MBID:  {no_mbid}", file=sys.stderr)
    print(f"Errors:   {errors}", file=sys.stderr)
    has_albums = sum(1 for r in records if r.get("albums"))
    print(f"Total with albums: {has_albums}/{total}", file=sys.stderr)


if __name__ == "__main__":
    main()
