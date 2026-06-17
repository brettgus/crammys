#!/usr/bin/env python3
"""
Enrich presidents-data.js with `entryNote` and `exitNote` fields —
one-line descriptions of how each president took and left office.

Hand-curated per presidency (47 records, since Cleveland and Trump
are split into two cards each for non-consecutive terms).

Usage:  python3 enrich_president_terms.py
Idempotent: if an entry already has both `entryNote` and `exitNote`
populated, it is left untouched.
"""
import os, re, json, sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATAFILE = os.path.join(BASE, "presidents-data.js")


# ── Parse / write (mirrors enrich_presidents.py) ────────────────────
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
    "entryNote", "exitNote",
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


# ── Hand-curated notes keyed by term number ─────────────────────────
# Each value is (entryNote, exitNote).
NOTES = {
    1: (
        "Unanimously elected by Electoral College in 1789",
        "Did not seek third term (succeeded by John Adams)",
    ),
    2: (
        "Won 1796 election (succeeded Washington)",
        "Lost 1800 re-election to Thomas Jefferson",
    ),
    3: (
        "Won 1800 election (defeated incumbent John Adams)",
        "Did not seek third term (succeeded by James Madison)",
    ),
    4: (
        "Won 1808 election (open seat after Jefferson declined third term)",
        "End of two terms (succeeded by James Monroe)",
    ),
    5: (
        "Won 1816 election (open seat after Madison declined third term)",
        "End of two terms (succeeded by John Quincy Adams)",
    ),
    6: (
        "Won 1824 election in contingent House vote (open seat after Monroe)",
        "Lost 1828 re-election to Andrew Jackson",
    ),
    7: (
        "Won 1828 election (defeated incumbent John Quincy Adams)",
        "Did not seek third term (succeeded by Martin Van Buren)",
    ),
    8: (
        "Won 1836 election (succeeded Jackson)",
        "Lost 1840 re-election to William Henry Harrison",
    ),
    9: (
        "Won 1840 election (defeated incumbent Van Buren)",
        "Died in office April 1841 of pneumonia (succeeded by John Tyler)",
    ),
    10: (
        "Succeeded W. H. Harrison (death from pneumonia, April 1841)",
        "Did not seek election in his own right (succeeded by James K. Polk)",
    ),
    11: (
        "Won 1844 election (open seat after Tyler not nominated)",
        "Did not seek re-election (succeeded by Zachary Taylor)",
    ),
    12: (
        "Won 1848 election (open seat after Polk declined re-election)",
        "Died in office July 1850 of gastroenteritis (succeeded by Millard Fillmore)",
    ),
    13: (
        "Succeeded Taylor (death from gastroenteritis, July 1850)",
        "Lost Whig nomination in 1852 (succeeded by Franklin Pierce)",
    ),
    14: (
        "Won 1852 election (open seat after Fillmore denied nomination)",
        "Lost Democratic nomination in 1856 (succeeded by James Buchanan)",
    ),
    15: (
        "Won 1856 election (succeeded Pierce)",
        "Did not seek re-election (succeeded by Abraham Lincoln)",
    ),
    16: (
        "Won 1860 election (open seat after Buchanan declined re-election)",
        "Assassinated April 1865 by John Wilkes Booth (succeeded by Andrew Johnson)",
    ),
    17: (
        "Succeeded Lincoln (assassination, April 1865)",
        "Lost Democratic nomination in 1868 (succeeded by Ulysses S. Grant)",
    ),
    18: (
        "Won 1868 election (open seat after Andrew Johnson)",
        "Did not seek third term (succeeded by Rutherford B. Hayes)",
    ),
    19: (
        "Won disputed 1876 election via Compromise of 1877 (succeeded Grant)",
        "Did not seek re-election (succeeded by James A. Garfield)",
    ),
    20: (
        "Won 1880 election (open seat after Hayes declined re-election)",
        "Assassinated September 1881 by Charles Guiteau (succeeded by Chester A. Arthur)",
    ),
    21: (
        "Succeeded Garfield (assassination, September 1881)",
        "Lost Republican nomination in 1884 (succeeded by Grover Cleveland)",
    ),
    22: (
        "Won 1884 election (succeeded Arthur)",
        "Lost 1888 re-election to Benjamin Harrison",
    ),
    23: (
        "Won 1888 election (defeated incumbent Cleveland)",
        "Lost 1892 re-election to Grover Cleveland",
    ),
    24: (
        "Won 1892 election (defeated incumbent Benjamin Harrison)",
        "End of term (succeeded by McKinley)",
    ),
    25: (
        "Won 1896 election (open seat after Cleveland declined re-election)",
        "Assassinated September 1901 by Leon Czolgosz (succeeded by Theodore Roosevelt)",
    ),
    26: (
        "Succeeded McKinley (assassination, September 1901)",
        "Did not seek re-election in 1908 (succeeded by William Howard Taft)",
    ),
    27: (
        "Won 1908 election (succeeded Theodore Roosevelt)",
        "Lost 1912 re-election to Woodrow Wilson (split GOP vote with T. Roosevelt)",
    ),
    28: (
        "Won 1912 election (three-way race with Taft and T. Roosevelt)",
        "Did not seek re-election after stroke (succeeded by Warren G. Harding)",
    ),
    29: (
        "Won 1920 election (open seat after Wilson)",
        "Died in office August 1923 of heart attack (succeeded by Calvin Coolidge)",
    ),
    30: (
        "Succeeded Harding (death from heart attack, August 1923)",
        "Did not seek re-election (succeeded by Herbert Hoover)",
    ),
    31: (
        "Won 1928 election (open seat after Coolidge declined re-election)",
        "Lost 1932 re-election to Franklin D. Roosevelt",
    ),
    32: (
        "Won 1932 election (defeated incumbent Hoover)",
        "Died in office April 1945 of cerebral hemorrhage (succeeded by Harry S. Truman)",
    ),
    33: (
        "Succeeded FDR (death from cerebral hemorrhage, April 1945)",
        "Did not seek re-election in 1952 (succeeded by Dwight D. Eisenhower)",
    ),
    34: (
        "Won 1952 election (open seat after Truman declined re-election)",
        "End of two-term limit (succeeded by John F. Kennedy)",
    ),
    35: (
        "Won 1960 election (open seat after Eisenhower term-limited)",
        "Assassinated November 1963 by Lee Harvey Oswald (succeeded by Lyndon B. Johnson)",
    ),
    36: (
        "Succeeded JFK (assassination, November 1963)",
        "Did not seek re-election (succeeded by Richard Nixon)",
    ),
    37: (
        "Won 1968 election (open seat after LBJ declined re-election)",
        "Resigned August 1974 amid Watergate (succeeded by Gerald Ford)",
    ),
    38: (
        "Succeeded Nixon (resignation, August 1974)",
        "Lost 1976 election to Jimmy Carter",
    ),
    39: (
        "Won 1976 election (defeated incumbent Ford)",
        "Lost 1980 re-election to Ronald Reagan",
    ),
    40: (
        "Won 1980 election (defeated incumbent Carter)",
        "End of two-term limit (succeeded by George H. W. Bush)",
    ),
    41: (
        "Won 1988 election (open seat after Reagan term-limited)",
        "Lost 1992 re-election to Bill Clinton",
    ),
    42: (
        "Won 1992 election (defeated incumbent George H. W. Bush)",
        "End of two-term limit (succeeded by George W. Bush)",
    ),
    43: (
        "Won 2000 election (open seat after Clinton term-limited)",
        "End of two-term limit (succeeded by Barack Obama)",
    ),
    44: (
        "Won 2008 election (open seat after George W. Bush term-limited)",
        "End of two-term limit (succeeded by Donald Trump)",
    ),
    45: (
        "Won 2016 election (succeeded Obama)",
        "Lost 2020 re-election to Joe Biden",
    ),
    46: (
        "Won 2020 election (defeated incumbent Trump)",
        "Did not seek re-election (succeeded by Donald Trump)",
    ),
    47: (
        "Won 2024 election (defeated Kamala Harris, first non-consecutive return since Cleveland)",
        "Currently serving",
    ),
}


def main():
    print("Enriching presidents-data.js with entry/exit notes…\n",
          file=sys.stderr)
    records = parse_datafile(DATAFILE)
    print(f"  {len(records)} records loaded", file=sys.stderr)

    if len(records) != 47:
        print(f"  WARNING: expected 47 records, got {len(records)}",
              file=sys.stderr)

    # Sanity-check: every term we have a note for, every record needs a note
    have_terms = {r.get("term") for r in records}
    note_terms = set(NOTES.keys())
    missing_notes = have_terms - note_terms
    extra_notes = note_terms - have_terms
    if missing_notes:
        print(f"  ERROR: no NOTES entry for terms: {sorted(missing_notes)}",
              file=sys.stderr)
        sys.exit(1)
    if extra_notes:
        print(f"  WARNING: NOTES has unused terms: {sorted(extra_notes)}",
              file=sys.stderr)

    updated = 0
    skipped = 0
    for i, rec in enumerate(records, 1):
        term = rec.get("term")
        name = rec.get("name", "?")
        if rec.get("entryNote") and rec.get("exitNote"):
            skipped += 1
            print(f"  [{i}/{len(records)}] {name} (term {term}): already has notes, skipping",
                  file=sys.stderr)
            continue
        entry, exit_ = NOTES[term]
        rec["entryNote"] = entry
        rec["exitNote"] = exit_
        updated += 1
        print(f"  [{i}/{len(records)}] {name} (term {term}): set entry/exit notes",
              file=sys.stderr)

    write_datafile(DATAFILE, records)

    print("", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Updated: {updated}", file=sys.stderr)
    print(f"  Skipped (already populated): {skipped}", file=sys.stderr)
    print(f"  Written to {DATAFILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
