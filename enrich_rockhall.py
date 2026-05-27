#!/usr/bin/env python3
"""
Enrich rockhall-data.js with:
  1. inductedBy  — who presented/inducted them (from Wikipedia list article)
  2. summary     — first paragraph of their Wikipedia article
  3. members     — fill in empty members arrays for groups (best-effort)

Usage: python3 enrich_rockhall.py

Idempotent: skips entries that already have non-null values for these fields.
"""
import sys, json, urllib.request, urllib.parse, urllib.error, gzip, re, time, unicodedata, os

UA = "Crammys/1.0 (flashcard app)"
DATAFILE = "rockhall-data.js"

# Import the shared relevance checker (Layer 3)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate_all import summary_seems_musical


# ── HTTP helper (same pattern as fetch_rockhall.py) ─────────────────
def http_get(url, *, accept="application/json", timeout=60, max_retries=4, backoff=10.0):
    """Fetch URL and return bytes; handles gzip and retries."""
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": accept,
            "Accept-Encoding": "gzip",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = backoff * (2 ** attempt)
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


# ── Parse rockhall-data.js ──────────────────────────────────────────
def parse_datafile(path):
    """Read rockhall-data.js and return list of dicts.
    The file uses JS object syntax (unquoted keys), so we convert to JSON first."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    # Strip the wrapper: window.ROCKHALL_DATA = [...];
    m = re.search(r'window\.ROCKHALL_DATA\s*=\s*\[', text)
    if not m:
        raise ValueError("Cannot find window.ROCKHALL_DATA array in file")

    array_text = text[m.start():]
    # Find the matching end
    array_text = re.sub(r'^window\.ROCKHALL_DATA\s*=\s*', '', array_text)
    # Remove trailing semicolon
    array_text = array_text.rstrip().rstrip(';').rstrip()

    # Convert JS object syntax to JSON by processing line-by-line.
    # This avoids corrupting text inside string values (like "Spanish":).
    out_lines = []
    for line in array_text.split("\n"):
        stripped = line.lstrip()

        # Lines that are property definitions: "  key: value" or "  key: value,"
        # These start with optional whitespace, then a word, then ":"
        prop_match = re.match(r'^(\w+)(\s*:\s*)', stripped)
        if prop_match and not stripped.startswith('"'):
            indent = line[:len(line) - len(stripped)]
            key = prop_match.group(1)
            rest = stripped[prop_match.end():]
            line = f'{indent}"{key}": {rest}'

        # Inline object keys: { year: 1986, category: "Performer" }
        # Only transform inside { } constructs, not inside strings
        if re.search(r'\{\s*\w+\s*:', line):
            # Find { ... } blocks and quote keys inside them
            def _quote_inline_keys(m):
                block = m.group(0)
                block = re.sub(r'(?<=\{)\s*(\w+)\s*:', r' "\1":', block)
                block = re.sub(r',\s*(\w+)\s*:', r', "\1":', block)
                return block
            line = re.sub(r'\{[^}]+\}', _quote_inline_keys, line)

        out_lines.append(line)

    json_text = "\n".join(out_lines)

    # Remove trailing commas before } or ]
    json_text = re.sub(r',\s*([}\]])', r'\1', json_text)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        # Show context around the error
        lines = json_text.split('\n')
        lineno = e.lineno - 1
        start = max(0, lineno - 3)
        end = min(len(lines), lineno + 4)
        context = '\n'.join(f"  {i+1:5d} | {lines[i]}" for i in range(start, end))
        raise ValueError(f"JSON parse error at line {e.lineno}, col {e.colno}: {e.msg}\n{context}")

    return data


# ── Write rockhall-data.js ──────────────────────────────────────────
def write_datafile(path, records):
    """Write records back in the same unquoted-keys JS format."""

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

    # Field order — matches existing file, with new fields added
    FIELD_ORDER = [
        "name", "wikidata", "year", "inductions", "category",
        "type", "genres", "country", "born", "died",
        "formed", "disbanded", "image", "description",
        "members", "musicbrainz", "inductedBy", "summary",
    ]

    lines = []
    for rec in records:
        obj_parts = []
        for key in FIELD_ORDER:
            if key not in rec:
                continue
            val = rec[key]
            if key == "inductions":
                induction_items = []
                for ind in val:
                    induction_items.append(
                        f"{{ year: {js_val(ind.get('year'))}, category: {js_val(ind.get('category'))} }}"
                    )
                obj_parts.append(f"  inductions: [{', '.join(induction_items)}]")
            else:
                obj_parts.append(f"  {key}: {js_val(val)}")
        lines.append("{\n" + ",\n".join(obj_parts) + "\n}")

    js_content = "window.ROCKHALL_DATA = [\n" + ",\n".join(lines) + "\n];\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(js_content)


# ── Name normalization (reuse from fetch_rockhall.py) ───────────────
def _strip_diacritics(s):
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize_name(name):
    name = name.strip()
    name = re.sub(r'^The\s+', '', name, flags=re.I)
    name = re.sub(r'\s*\([^)]*\)', '', name)
    name = _strip_diacritics(name)
    name = name.replace('"', '').replace("'", '').replace('“', '').replace('”', '')
    name = re.sub(r'\s+', ' ', name).strip()
    return name.lower()


# ── Step 1: Parse "inducted by" from Wikipedia ──────────────────────

# Column layout per section (0-indexed). These define which column
# holds the inductee name and which holds the induction presenter.
# Column indices: Year=0, Image=1, Name=2, ...
# Performers:         Year(0) Image(1) Name(2) InductedMembers(3) PriorNoms(4) Presenter(5)
# Early Influence:    Year(0) Image(1) Name(2) InductedMembers(3) InductedBy(4)
# Non-Performer:      Year(0) Image(1) Name(2) InductedBy(3)
# Musical Excellence: Year(0) Image(1) Name(2) InductedMembers(3) InductedBy(4)
# Singles:            Year(0) Artist(1) Song(2) Label(3) — no inducted-by column

SECTION_TABLE_LAYOUT = {
    "Performer":         {"name_col": 2, "inducted_by_col": 5, "num_cols": 6},
    "Early Influence":   {"name_col": 2, "inducted_by_col": 4, "num_cols": 5},
    "Non-Performer":     {"name_col": 2, "inducted_by_col": 3, "num_cols": 4},
    "Musical Excellence":{"name_col": 2, "inducted_by_col": 4, "num_cols": 5},
    "Single":            {"name_col": 1, "inducted_by_col": None, "num_cols": 4},
}


def _parse_wiki_table(lines, start, end):
    """Parse a wiki table into rows of cells, handling rowspan.
    Returns list of rows, where each row is a list of cell strings."""
    rows = []
    current_row = []
    # Track rowspan carry-overs: col_idx → (remaining_rows, cell_content)
    rowspan_carry = {}

    i = start
    while i < end:
        line = lines[i].strip()

        if line.startswith("|-"):
            # Row separator: finalize current row and start new one
            if current_row:
                rows.append(current_row)
            current_row = []
            i += 1
            continue

        if line.startswith("!"):
            # Header row — skip
            i += 1
            continue

        if line.startswith("|"):
            cell_text = line[1:].strip()

            # Skip empty cells that are just formatting
            if not cell_text:
                current_row.append("")
                i += 1
                continue

            current_row.append(cell_text)

        i += 1

    # Don't forget the last row
    if current_row:
        rows.append(current_row)

    # Now process rowspan. We need to insert carried-over cells.
    expanded_rows = []
    active_spans = {}  # col_idx → (remaining_rows, cell_content)

    for row in rows:
        expanded = []
        col_idx = 0
        cell_idx = 0

        # Insert any rowspan carry-overs first, then actual cells
        # We need to interleave carried-over cells with actual cells
        while cell_idx < len(row) or col_idx in active_spans:
            if col_idx in active_spans:
                remaining, content = active_spans[col_idx]
                expanded.append(content)
                remaining -= 1
                if remaining <= 0:
                    del active_spans[col_idx]
                else:
                    active_spans[col_idx] = (remaining, content)
                col_idx += 1
            elif cell_idx < len(row):
                cell = row[cell_idx]
                # Check for rowspan
                rs_match = re.match(r'rowspan\s*=\s*"?(\d+)"?\s*\|(.*)$', cell, re.DOTALL)
                if rs_match:
                    span = int(rs_match.group(1))
                    content = rs_match.group(2).strip()
                    expanded.append(content)
                    if span > 1:
                        active_spans[col_idx] = (span - 1, content)
                else:
                    expanded.append(cell)
                cell_idx += 1
                col_idx += 1
            else:
                break

        expanded_rows.append(expanded)

    return expanded_rows


def parse_inducted_by():
    """Parse the Wikipedia 'List of Rock and Roll Hall of Fame inductees'
    article to extract 'inducted by' information.
    Returns dict: normalized_name → list of {year, inducted_by}."""

    print("  Fetching Wikipedia inductee list for 'inducted by' data…", file=sys.stderr)
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "parse",
        "page": "List_of_Rock_and_Roll_Hall_of_Fame_inductees",
        "prop": "wikitext",
        "format": "json",
    })
    d = http_json(url)
    wikitext = d["parse"]["wikitext"]["*"]

    results = {}  # normalized_name → [{year, inducted_by}]

    SECTION_CATEGORIES = {
        "Performers": "Performer",
        "Early/musical influences": "Early Influence",
        "Non-performers (Ahmet Ertegun Award)": "Non-Performer",
        "Award for Musical Excellence": "Musical Excellence",
        "Singles": "Single",
    }

    all_lines = wikitext.split("\n")

    # Find section boundaries and their tables
    sections = []
    current_section = None
    table_start = None

    for i, line in enumerate(all_lines):
        m = re.match(r'^===\s*(.+?)\s*===$', line)
        if m:
            header = m.group(1).strip()
            cat = SECTION_CATEGORIES.get(header)
            if cat:
                current_section = cat
                table_start = None

        if current_section and line.startswith("{|") and table_start is None:
            table_start = i + 1  # skip the {| line itself

        if current_section and table_start is not None and line.startswith("|}"):
            sections.append((current_section, table_start, i))
            current_section = None
            table_start = None

    # Process each section's table
    for category, start, end in sections:
        layout = SECTION_TABLE_LAYOUT.get(category)
        if not layout or layout["inducted_by_col"] is None:
            continue

        name_col = layout["name_col"]
        ib_col = layout["inducted_by_col"]

        table_rows = _parse_wiki_table(all_lines, start, end)

        for row in table_rows:
            # Extract year from column 0
            year = None
            if len(row) > 0:
                ym = re.search(r'(\d{4})', row[0])
                if ym:
                    candidate = int(ym.group(1))
                    if 1980 <= candidate <= 2030:
                        year = candidate

            if not year:
                continue

            # Extract inductee name from name column
            if len(row) <= name_col:
                continue
            name_cell = row[name_col]

            # Extract inducted-by from its column
            if len(row) <= ib_col:
                continue
            ib_cell = row[ib_col]

            inductee_names = _extract_names_from_cell(name_cell)
            inducted_by_text = _clean_wiki_text(ib_cell)

            if inducted_by_text and inductee_names:
                for name in inductee_names:
                    norm = _normalize_name(name)
                    if norm:
                        results.setdefault(norm, []).append({
                            "year": year,
                            "inducted_by": inducted_by_text,
                            "raw_name": name,
                        })

    return results


def _extract_names_from_cell(cell):
    """Extract artist/inductee names from a wiki table cell."""
    names = []

    # Handle sortname templates: {{sortname|First|Last|...}}
    for sm in re.finditer(r'\{\{sortname\|([^}]+)\}\}', cell):
        parts = sm.group(1).split("|")
        if len(parts) >= 3:
            name = f"{parts[0]} {parts[1]}"
            alt_name = parts[2]
            # Clean link targets
            alt_name = re.sub(r'\[\[([^|\]]*\|)?([^\]]*)\]\]', r'\2', alt_name).strip()
            names.append(name.strip())
            if alt_name and alt_name != name.strip():
                names.append(alt_name)
        elif len(parts) >= 2:
            names.append(f"{parts[0]} {parts[1]}".strip())
        elif parts:
            names.append(parts[0].strip())

    # Handle data-sort-value cells
    dsv = re.search(r'data-sort-value="[^"]*"\s*\|(.+)', cell)
    if dsv:
        subcell = dsv.group(1).strip()
        subcell = re.sub(r'\{\{nowrap\|([^}]+)\}\}', r'\1', subcell)
        for lm in re.finditer(r'\[\[([^|\]]+?)(?:\|([^\]]+?))?\]\]', subcell):
            if lm.group(1).startswith(("File:", "Image:", "Category:")):
                continue
            n = lm.group(2) or lm.group(1)
            n = n.strip()
            if not re.match(r'^\d{4}$', n) and len(n) >= 2:
                names.append(n)

    # Handle plain [[links]]
    if not names:
        for lm in re.finditer(r'\[\[([^|\]]+?)(?:\|([^\]]+?))?\]\]', cell):
            if lm.group(1).startswith(("File:", "Image:", "Category:")):
                continue
            n = lm.group(2) or lm.group(1)
            n = n.strip()
            if not re.match(r'^\d{4}$', n) and len(n) >= 2:
                names.append(n)

    # If still no names, try the plain text of the cell
    if not names:
        clean = _clean_wiki_text(cell)
        if clean and len(clean) >= 2 and not re.match(r'^\d{4}$', clean):
            names.append(clean)

    return names


def _clean_wiki_text(text):
    """Remove wiki markup from text, returning plain text."""
    if not text:
        return None
    # Remove style="..." prefixes (e.g. style="white-space: nowrap;"|content)
    text = re.sub(r'style="[^"]*"\s*\|', '', text)
    # Remove ref tags and their contents
    text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.DOTALL)
    text = re.sub(r'<ref[^/]*?/>', '', text)
    # Remove {{Ref|...}} templates (footnote references like {{Ref|N2|[N2]}})
    text = re.sub(r'\{\{[Rr]ef\|[^}]*\}\}', '', text)
    # Remove {{nowrap|...}}
    text = re.sub(r'\{\{nowrap\|([^}]+)\}\}', r'\1', text)
    # Remove {{Hidden sort key|...}}
    text = re.sub(r'\{\{Hidden sort key\|[^}]*\}\}', '', text, flags=re.I)
    # Remove other templates but keep their first argument
    text = re.sub(r'\{\{[^|{}]*\|([^}]*)\}\}', r'\1', text)
    text = re.sub(r'\{\{[^}]*\}\}', '', text)
    # Convert [[link|display]] to display, [[link]] to link
    text = re.sub(r'\[\[([^|\]]*)\|([^\]]*)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', text)
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Remove data-sort-value prefix
    text = re.sub(r'data-sort-value="[^"]*"\s*\|', '', text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove leading/trailing pipes
    text = text.strip('|').strip()
    return text if text else None


def match_inducted_by(name, year, inducted_by_data):
    """Try to find inducted-by info for a given inductee name and year."""
    norm = _normalize_name(name)

    # Direct match
    if norm in inducted_by_data:
        entries = inducted_by_data[norm]
        # Try year match first
        for e in entries:
            if e["year"] == year:
                return e["inducted_by"]
        # Fall back to first entry
        return entries[0]["inducted_by"]

    # Try without "and" → "&" and vice versa
    for src, dst in [(" and ", " & "), (" & ", " and ")]:
        alt = norm.replace(src, dst)
        if alt in inducted_by_data:
            entries = inducted_by_data[alt]
            for e in entries:
                if e["year"] == year:
                    return e["inducted_by"]
            return entries[0]["inducted_by"]

    # Try replacing hyphens
    for repl in [" and ", " "]:
        alt = norm.replace("-", repl)
        if alt in inducted_by_data:
            entries = inducted_by_data[alt]
            for e in entries:
                if e["year"] == year:
                    return e["inducted_by"]
            return entries[0]["inducted_by"]

    # Substring matching
    for key, entries in inducted_by_data.items():
        if len(key) >= 4 and (key in norm or norm in key):
            for e in entries:
                if e["year"] == year:
                    return e["inducted_by"]
            return entries[0]["inducted_by"]

    # Partial match (last name)
    parts = norm.split()
    if len(parts) >= 2:
        for key, entries in inducted_by_data.items():
            if key.endswith(parts[-1]) and parts[0] in key:
                for e in entries:
                    if e["year"] == year:
                        return e["inducted_by"]
                return entries[0]["inducted_by"]

    return None


# ── Step 2: Fetch Wikipedia summaries ───────────────────────────────
def fetch_wikipedia_summary(name, wikidata_id):
    """Fetch the intro paragraph of the Wikipedia article for this artist.
    Try Wikidata sitelinks first, then search by name."""
    MAX_SUMMARY_LEN = 500

    # Strategy 1: Use Wikidata to get Wikipedia article title
    title = _get_wp_title_from_wikidata(wikidata_id)

    # Strategy 2: Search Wikipedia by name
    if not title:
        title = _search_wikipedia_title(name)

    if not title:
        return None

    # Fetch the extract
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "titles": title,
        "prop": "extracts",
        "exintro": "1",
        "explaintext": "1",
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception as e:
        print(f"    Error fetching summary for {name}: {e}", file=sys.stderr)
        return None

    pages = d.get("query", {}).get("pages", {})
    for page_id, page in pages.items():
        if page_id == "-1":
            return None
        extract = page.get("extract", "")
        if not extract:
            return None
        # Take just the first paragraph
        paragraphs = [p.strip() for p in extract.split("\n") if p.strip()]
        if not paragraphs:
            return None
        summary = paragraphs[0]
        # Layer 1: validate the extract mentions music-related terms
        if not summary_seems_musical(summary):
            print(f"    Skipping summary for {name} — extract doesn't mention music terms", file=sys.stderr)
            return None
        # Truncate if too long
        if len(summary) > MAX_SUMMARY_LEN:
            # Try to cut at a sentence boundary
            cut = summary[:MAX_SUMMARY_LEN]
            last_period = cut.rfind(". ")
            if last_period > MAX_SUMMARY_LEN // 2:
                summary = cut[:last_period + 1]
            else:
                summary = cut.rstrip() + "…"
        return summary

    return None


def _get_wp_title_from_wikidata(qid):
    """Get English Wikipedia article title from Wikidata entity sitelinks."""
    if not qid:
        return None
    url = "https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode({
        "action": "wbgetentities",
        "ids": qid,
        "props": "sitelinks",
        "sitefilter": "enwiki",
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception:
        return None

    entity = d.get("entities", {}).get(qid, {})
    sitelinks = entity.get("sitelinks", {})
    enwiki = sitelinks.get("enwiki", {})
    return enwiki.get("title")


def _search_wikipedia_title(name):
    """Search Wikipedia for an article title matching this name."""
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": name,
        "srlimit": "1",
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception:
        return None

    results = d.get("query", {}).get("search", [])
    if results:
        return results[0]["title"]
    return None


# ── Step 3: Fill empty members from Wikipedia infobox ───────────────
def fetch_members_from_wikipedia(name, wikidata_id):
    """Try to get band members from Wikipedia article's infobox wikitext."""
    title = _get_wp_title_from_wikidata(wikidata_id)
    if not title:
        title = _search_wikipedia_title(name)
    if not title:
        return None

    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "parse",
        "page": title,
        "prop": "wikitext",
        "format": "json",
    })
    try:
        d = http_json(url)
    except Exception:
        return None

    wikitext = d.get("parse", {}).get("wikitext", {}).get("*", "")
    if not wikitext:
        return None

    # Look for members/current_members in the infobox
    # Patterns like: | members = ... or | current_members = ...
    members = []
    for field in ["members", "current_members"]:
        pattern = rf'\|\s*{field}\s*=\s*(.*?)(?:\n\||\n\}})'
        m = re.search(pattern, wikitext, re.DOTALL)
        if m:
            member_text = m.group(1)
            # Extract names from various formats:
            # * [[Name]]  or  [[Name|Display]]  or plain text lists
            for lm in re.finditer(r'\[\[([^|\]]+?)(?:\|([^\]]+?))?\]\]', member_text):
                n = lm.group(2) or lm.group(1)
                n = n.strip()
                if n and not n.startswith(("File:", "Image:", "Category:")) and len(n) >= 2:
                    members.append(n)
            if members:
                break
            # Try flatlist or plainlist patterns
            for item in re.finditer(r'\*\s*(.+?)(?:\n|$)', member_text):
                item_text = item.group(1).strip()
                item_text = re.sub(r'\[\[([^|\]]*)\|([^\]]*)\]\]', r'\2', item_text)
                item_text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', item_text)
                item_text = re.sub(r'<[^>]+>', '', item_text)
                item_text = re.sub(r'\{\{[^}]*\}\}', '', item_text)
                item_text = item_text.strip()
                if item_text and len(item_text) >= 2:
                    members.append(item_text)
            if members:
                break

    return sorted(set(members)) if members else None


# ── Main ────────────────────────────────────────────────────────────
def main():
    print("Enriching rockhall-data.js…\n", file=sys.stderr)

    # --- Read existing data ---
    print("  Reading rockhall-data.js…", file=sys.stderr)
    records = parse_datafile(DATAFILE)
    print(f"  → {len(records)} records loaded\n", file=sys.stderr)

    # --- Step 1: Parse inducted-by data ---
    print("  [1/3] Parsing inducted-by data from Wikipedia…", file=sys.stderr)
    inducted_by_data = parse_inducted_by()
    total_entries = sum(len(v) for v in inducted_by_data.values())
    print(f"  → {len(inducted_by_data)} names, {total_entries} inducted-by entries\n", file=sys.stderr)

    # Match inducted-by to our records
    inducted_by_count = 0
    inducted_by_skipped = 0
    for rec in records:
        if rec.get("inductedBy") is not None:
            inducted_by_skipped += 1
            inducted_by_count += 1
            continue
        year = rec.get("year")
        name = rec["name"]
        result = match_inducted_by(name, year, inducted_by_data)
        rec["inductedBy"] = result
        if result:
            inducted_by_count += 1

    print(f"  → inductedBy: {inducted_by_count} found ({inducted_by_skipped} skipped/cached), "
          f"{len(records) - inducted_by_count} missing\n", file=sys.stderr)

    # --- Step 2: Fetch Wikipedia summaries ---
    print("  [2/3] Fetching Wikipedia summaries…", file=sys.stderr)
    summary_count = 0
    summary_skipped = 0
    summary_errors = 0

    # Batch Wikidata sitelink lookups: up to 50 at a time
    # Build list of QIDs that need summaries
    needs_summary = []
    for idx, rec in enumerate(records):
        if rec.get("summary") is not None:
            summary_skipped += 1
            summary_count += 1
            continue
        needs_summary.append(idx)

    # Batch fetch Wikipedia titles from Wikidata
    print(f"  → {len(needs_summary)} summaries to fetch ({summary_skipped} already cached)", file=sys.stderr)

    qid_to_title = {}
    qids_to_lookup = [records[i]["wikidata"] for i in needs_summary if records[i].get("wikidata")]
    # Batch in groups of 50 (Wikidata supports up to 50)
    for batch_start in range(0, len(qids_to_lookup), 50):
        batch = qids_to_lookup[batch_start:batch_start + 50]
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
                    qid_to_title[qid] = title
        except Exception as e:
            print(f"    Error batch-fetching sitelinks: {e}", file=sys.stderr)
        time.sleep(2)

    print(f"  → {len(qid_to_title)} Wikipedia titles resolved from Wikidata", file=sys.stderr)

    # Build title → record index mapping
    # For records without a Wikidata title, try Wikipedia search (one at a time)
    title_to_indices = {}  # title → [record indices]
    no_title_indices = []
    for idx in needs_summary:
        rec = records[idx]
        qid = rec.get("wikidata")
        title = qid_to_title.get(qid)
        if title:
            title_to_indices.setdefault(title, []).append(idx)
        else:
            no_title_indices.append(idx)

    # Search Wikipedia for records without Wikidata sitelinks
    if no_title_indices:
        print(f"  → Searching Wikipedia for {len(no_title_indices)} titles not in Wikidata…", file=sys.stderr)
        for idx in no_title_indices:
            rec = records[idx]
            title = _search_wikipedia_title(rec["name"])
            if title:
                title_to_indices.setdefault(title, []).append(idx)
            else:
                rec["summary"] = None
                summary_errors += 1
            time.sleep(1.5)

    # Batch fetch Wikipedia extracts (up to 20 titles per request)
    all_titles = list(title_to_indices.keys())
    BATCH_SIZE = 20
    print(f"  → Fetching extracts for {len(all_titles)} unique Wikipedia articles in batches of {BATCH_SIZE}…", file=sys.stderr)

    for batch_start in range(0, len(all_titles), BATCH_SIZE):
        batch_titles = all_titles[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(all_titles) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"    Batch {batch_num}/{total_batches} ({len(batch_titles)} titles)…", file=sys.stderr)

        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "titles": "|".join(batch_titles),
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "format": "json",
        })
        try:
            d = http_json(url)
            pages = d.get("query", {}).get("pages", {})

            # Build a normalized-title → extract mapping
            # Wikipedia may redirect/normalize titles, so match via page title
            title_extract = {}
            for page_id, page in pages.items():
                if page_id == "-1":
                    continue
                page_title = page.get("title", "")
                extract = page.get("extract", "")
                if page_title and extract:
                    title_extract[page_title] = extract

            for title in batch_titles:
                extract = title_extract.get(title, "")
                indices = title_to_indices.get(title, [])
                if extract:
                    paragraphs = [p.strip() for p in extract.split("\n") if p.strip()]
                    summary = paragraphs[0] if paragraphs else None
                    # Layer 1: validate the extract mentions music-related terms
                    if summary and not summary_seems_musical(summary):
                        for idx in indices:
                            name = records[idx].get("name", "?")
                            print(f"    Skipping summary for {name} — extract doesn't mention music terms", file=sys.stderr)
                        summary = None
                    if summary and len(summary) > 500:
                        cut = summary[:500]
                        last_period = cut.rfind(". ")
                        if last_period > 250:
                            summary = cut[:last_period + 1]
                        else:
                            summary = cut.rstrip() + "…"
                    for idx in indices:
                        records[idx]["summary"] = summary
                        if summary:
                            summary_count += 1
                        else:
                            summary_errors += 1
                else:
                    for idx in indices:
                        records[idx]["summary"] = None
                        summary_errors += 1

        except Exception as e:
            print(f"    Error fetching batch extracts: {e}", file=sys.stderr)
            for title in batch_titles:
                for idx in title_to_indices.get(title, []):
                    records[idx]["summary"] = None
                    summary_errors += 1

        time.sleep(2)

    print(f"\n  → summaries: {summary_count} found, {summary_errors} missing/errors\n", file=sys.stderr)

    # --- Step 3: Fill empty members ---
    print("  [3/3] Checking for groups with empty members…", file=sys.stderr)
    members_filled = 0
    groups_with_empty = []
    for idx, rec in enumerate(records):
        if rec.get("type") == "group" and not rec.get("members"):
            groups_with_empty.append(idx)

    print(f"  → {len(groups_with_empty)} groups have empty members arrays", file=sys.stderr)

    for count_idx, idx in enumerate(groups_with_empty):
        rec = records[idx]
        name = rec["name"]
        qid = rec.get("wikidata")

        if (count_idx + 1) % 10 == 0 or count_idx == 0:
            print(f"    Checking members… {count_idx + 1}/{len(groups_with_empty)}", file=sys.stderr)

        title = qid_to_title.get(qid)
        if not title:
            title = _search_wikipedia_title(name)
            time.sleep(1.5)
        if not title:
            continue

        # Fetch wikitext for infobox parsing
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
        })
        try:
            d = http_json(url)
            wikitext = d.get("parse", {}).get("wikitext", {}).get("*", "")
            if wikitext:
                members = _parse_members_from_infobox(wikitext)
                if members:
                    rec["members"] = members
                    members_filled += 1
                    print(f"      {name}: found {len(members)} members", file=sys.stderr)
        except Exception as e:
            print(f"    Error fetching members for {name}: {e}", file=sys.stderr)

        time.sleep(2)

    print(f"\n  → Filled members for {members_filled} groups\n", file=sys.stderr)

    # --- Write output ---
    print("  Writing enriched rockhall-data.js…", file=sys.stderr)
    write_datafile(DATAFILE, records)

    # --- Summary ---
    total = len(records)
    has_inducted_by = sum(1 for r in records if r.get("inductedBy"))
    has_summary = sum(1 for r in records if r.get("summary"))
    has_members = sum(1 for r in records if r.get("type") == "group" and r.get("members"))
    total_groups = sum(1 for r in records if r.get("type") == "group")

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Total records:      {total}", file=sys.stderr)
    print(f"  With inductedBy:    {has_inducted_by} ({has_inducted_by*100//total}%)", file=sys.stderr)
    print(f"  With summary:       {has_summary} ({has_summary*100//total}%)", file=sys.stderr)
    print(f"  Groups w/ members:  {has_members}/{total_groups}", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"\n  Written to {DATAFILE}", file=sys.stderr)


def _parse_members_from_infobox(wikitext):
    """Extract members from a Wikipedia infobox in wikitext."""
    members = []

    # Try various infobox member fields
    for field in ["members", "current_members"]:
        # Match the field value which may span multiple lines
        # The field ends at the next | at the start of a line or }}
        pattern = rf'(?m)^\s*\|\s*{field}\s*=\s*(.*?)(?=\n\s*\||\n\}})'
        m = re.search(pattern, wikitext, re.DOTALL)
        if not m:
            continue

        member_text = m.group(1).strip()
        if not member_text:
            continue

        # Extract from {{flatlist}}, {{hlist}}, plain lists, etc.
        # First try [[link]] patterns
        found = []
        for lm in re.finditer(r'\[\[([^|\]]+?)(?:\|([^\]]+?))?\]\]', member_text):
            raw = lm.group(1)
            display = lm.group(2)
            if raw.startswith(("File:", "Image:", "Category:")):
                continue
            n = (display or raw).strip()
            if n and len(n) >= 2:
                found.append(n)

        if found:
            members = found
            break

        # Try bullet list items
        for item in re.finditer(r'\*\s*(.+?)(?:\n|$)', member_text):
            item_text = item.group(1).strip()
            item_text = re.sub(r'\[\[([^|\]]*)\|([^\]]*)\]\]', r'\2', item_text)
            item_text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', item_text)
            item_text = re.sub(r'<[^>]+>', '', item_text)
            item_text = re.sub(r'\{\{[^}]*\}\}', '', item_text)
            item_text = item_text.strip()
            if item_text and len(item_text) >= 2:
                members.append(item_text)

        if members:
            break

    return sorted(set(members)) if members else None


if __name__ == "__main__":
    main()
