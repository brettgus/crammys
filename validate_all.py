#!/usr/bin/env python3
"""
Unified data-validation script for all Crammys decks.

Runs REQUIRED / EXPECTED / SHAPE checks against every deck data file and
prints a clean per-deck report.  Exits 0 when there are no REQUIRED
violations, exits 1 otherwise.

For the Chains deck, defer to validate_chains.py (uses its own JSON
manifest).

Usage:
  python3 validate_all.py            # prints report, exit 1 on REQUIRED fail
  python3 validate_all.py --strict   # also fail on EXPECTED warnings
"""

import json, os, re, subprocess, sys, textwrap

ROOT = os.path.dirname(os.path.abspath(__file__))

# ── Helpers ──────────────────────────────────────────────────────────

def _node_parse(filepath):
    """Return True if Node can eval the file, else an error string."""
    relpath = os.path.relpath(filepath, ROOT)
    # bestpicture-data.js uses ES module `export default` — strip it
    # before eval so Node doesn't choke on bare `export`.
    cmd = [
        "node", "-e",
        (
            "global.window={};"
            "let src=require('fs').readFileSync("
            f"'{filepath}','utf8');"
            "src=src.replace(/^export\\s+default/m,'module.exports=');"
            "eval(src);"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        return True
    return res.stderr.strip().split("\n")[-1]


def _load_js_array(filepath, global_var):
    """Eval a `window.VAR = [...]` file via Node and return the list."""
    cmd = [
        "node", "-e",
        (
            "global.window={};"
            f"eval(require('fs').readFileSync('{filepath}','utf8'));"
            f"process.stdout.write(JSON.stringify(window.{global_var}));"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Node eval failed for {filepath}:\n{res.stderr}")
    return json.loads(res.stdout)


def _load_esm_array(filepath):
    """Load an `export default [...]` file by stripping the export keyword."""
    cmd = [
        "node", "-e",
        (
            "let src=require('fs').readFileSync("
            f"'{filepath}','utf8');"
            "src=src.replace(/^export\\s+default/m,'');"
            "src='module.exports='+src;"
            "let m={exports:{}};"
            "const fn=new Function('module','exports',src);"
            "fn(m,m.exports);"
            "process.stdout.write(JSON.stringify(m.exports));"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Node eval failed for {filepath}:\n{res.stderr}")
    return json.loads(res.stdout)


# ── Per-deck validators ─────────────────────────────────────────────

class DeckReport:
    def __init__(self, name, count):
        self.name = name
        self.count = count
        self.lines = []   # (level, message)  level = ok | warn | error

    def ok(self, msg):
        self.lines.append(("ok", msg))

    def warn(self, msg):
        self.lines.append(("warn", msg))

    def error(self, msg):
        self.lines.append(("error", msg))

    @property
    def errors(self):
        return sum(1 for lv, _ in self.lines if lv == "error")

    @property
    def warnings(self):
        return sum(1 for lv, _ in self.lines if lv == "warn")

    def print(self):
        print(f"\n=== {self.name} ({self.count} entries) ===")
        icons = {"ok": "✓", "warn": "⚠", "error": "✗"}
        for lv, msg in self.lines:
            print(f"  {icons[lv]} {msg}")


# ── Rock & Roll Hall of Fame ────────────────────────────────────────

ROCKHALL_REQUIRED = ["name", "wikidata", "inductions", "category", "type"]
ROCKHALL_EXPECTED = ["image", "description", "summary", "inductedBy",
                     "spotify", "wikipedia", "musicbrainz", "albums"]
ROCKHALL_CATEGORIES = {"Performer", "Early Influence", "Non-Performer",
                       "Musical Excellence", "Inductee", "Single"}

def validate_rockhall():
    fp = os.path.join(ROOT, "rockhall-data.js")
    data = _load_js_array(fp, "ROCKHALL_DATA")
    rpt = DeckReport("Rock & Roll Hall of Fame", len(data))

    # JS syntax
    syn = _node_parse(fp)
    if syn is True:
        rpt.ok("JS syntax valid")
    else:
        rpt.error(f"JS syntax error: {syn}")

    # REQUIRED
    req_missing = {}
    for entry in data:
        name = entry.get("name") or "<unnamed>"
        for f in ROCKHALL_REQUIRED:
            v = entry.get(f)
            if v is None or v == "" or (isinstance(v, list) and not v):
                # year is explicitly allowed to be null
                if f == "year":
                    continue
                req_missing.setdefault(f, []).append(name)
    # year is listed as "can be null for some" — REQUIRED but nullable
    for entry in data:
        name = entry.get("name") or "<unnamed>"
        if "year" not in entry:
            req_missing.setdefault("year", []).append(name)

    if not req_missing:
        rpt.ok("All REQUIRED fields present")
    else:
        for f, names in req_missing.items():
            rpt.error(f"{len(names)} entries missing REQUIRED field '{f}' — e.g. {names[0]}")

    # EXPECTED
    exp_missing = {}
    for entry in data:
        for f in ROCKHALL_EXPECTED:
            v = entry.get(f)
            if v is None or v == "" or (isinstance(v, list) and not v):
                exp_missing.setdefault(f, []).append(entry.get("name", "?"))
    if not exp_missing:
        rpt.ok("All EXPECTED fields present")
    else:
        for f, names in exp_missing.items():
            rpt.warn(f"{len(names)} entries missing EXPECTED field '{f}'")

    # SHAPE
    shape_issues = []

    seen_wikidata = {}
    year_name_pairs = set()
    for entry in data:
        name = entry.get("name") or "<unnamed>"

        # year
        yr = entry.get("year")
        if yr is not None:
            if not isinstance(yr, int) or not (1986 <= yr <= 2026):
                shape_issues.append(("error", f"{name}: year {yr!r} not int in 1986-2026"))

        # type
        t = entry.get("type")
        if t and t not in ("person", "group"):
            shape_issues.append(("error", f"{name}: type {t!r} not 'person' or 'group'"))

        # category
        cat = entry.get("category")
        if cat and cat not in ROCKHALL_CATEGORIES:
            shape_issues.append(("error", f"{name}: category {cat!r} not in {sorted(ROCKHALL_CATEGORIES)}"))

        # inductions
        inductions = entry.get("inductions")
        if isinstance(inductions, list):
            for ind in inductions:
                if not isinstance(ind, dict) or "year" not in ind or "category" not in ind:
                    shape_issues.append(("error", f"{name}: induction entry not {{year, category}}"))

        # image URL
        img = entry.get("image")
        if img and not img.startswith("http"):
            shape_issues.append(("warn", f"{name}: image URL doesn't start with http"))

        # spotify
        sp = entry.get("spotify")
        if sp:
            if not re.fullmatch(r'[A-Za-z0-9]{22}', sp):
                shape_issues.append(("warn", f"{name}: spotify {sp!r} doesn't look like a 22-char ID"))

        # duplicate wikidata
        wd = entry.get("wikidata")
        if wd:
            if wd in seen_wikidata:
                shape_issues.append(("error", f"{name}: duplicate wikidata {wd} (also {seen_wikidata[wd]})"))
            seen_wikidata[wd] = name

        # duplicate name within same year (allow person vs group with same name)
        key = (entry.get("year"), name, entry.get("type"))
        if key in year_name_pairs:
            shape_issues.append(("error", f"{name}: duplicate name+type in year {entry.get('year')}"))
        year_name_pairs.add(key)

    if not shape_issues:
        rpt.ok("All shape checks pass")
    else:
        for lv, msg in shape_issues:
            if lv == "error":
                rpt.error(msg)
            else:
                rpt.warn(msg)

    return rpt


# ── Best Original Song ──────────────────────────────────────────────

SONGS_REQUIRED = ["song", "film", "year", "songwriters"]
SONGS_EXPECTED = ["performers", "spotify", "wikipedia", "summary",
                  "filmDirector", "filmSummary", "filmWikipedia"]

def validate_songs():
    fp = os.path.join(ROOT, "songs-data.js")
    data = _load_js_array(fp, "SONGS_DATA")
    rpt = DeckReport("Best Original Song", len(data))

    syn = _node_parse(fp)
    if syn is True:
        rpt.ok("JS syntax valid")
    else:
        rpt.error(f"JS syntax error: {syn}")

    # REQUIRED
    req_missing = {}
    for entry in data:
        label = f"{entry.get('song','?')} ({entry.get('year','?')})"
        for f in SONGS_REQUIRED:
            v = entry.get(f)
            if v is None or v == "" or (isinstance(v, list) and not v):
                req_missing.setdefault(f, []).append(label)
    if not req_missing:
        rpt.ok("All REQUIRED fields present")
    else:
        for f, names in req_missing.items():
            rpt.error(f"{len(names)} entries missing REQUIRED field '{f}' — e.g. {names[0]}")

    # EXPECTED
    exp_missing = {}
    for entry in data:
        for f in SONGS_EXPECTED:
            v = entry.get(f)
            if v is None or v == "" or (isinstance(v, list) and not v):
                exp_missing.setdefault(f, []).append(entry.get("song", "?"))
    if not exp_missing:
        rpt.ok("All EXPECTED fields present")
    else:
        for f, names in exp_missing.items():
            rpt.warn(f"{len(names)} entries missing EXPECTED field '{f}'")

    # SHAPE
    shape_issues = []
    seen_combos = set()
    for entry in data:
        label = f"{entry.get('song','?')} ({entry.get('year','?')})"

        yr = entry.get("year")
        if yr is not None:
            if not isinstance(yr, int) or not (1935 <= yr <= 2026):
                shape_issues.append(("error", f"{label}: year {yr!r} not int in 1935-2026"))

        sp = entry.get("spotify")
        if sp:
            if not re.fullmatch(r'[A-Za-z0-9]{22}', sp):
                shape_issues.append(("warn", f"{label}: spotify {sp!r} doesn't look like a track ID"))

        sw = entry.get("songwriters")
        if isinstance(sw, list):
            for s in sw:
                if not isinstance(s, str) or not s.strip():
                    shape_issues.append(("error", f"{label}: songwriter entry {s!r} is empty/non-string"))

        combo = (entry.get("song"), entry.get("year"))
        if combo in seen_combos:
            shape_issues.append(("error", f"{label}: duplicate song+year combo"))
        seen_combos.add(combo)

    if not shape_issues:
        rpt.ok("All shape checks pass")
    else:
        for lv, msg in shape_issues:
            if lv == "error":
                rpt.error(msg)
            else:
                rpt.warn(msg)

    return rpt


# ── Grammy Big Four ─────────────────────────────────────────────────

GRAMMYS_REQUIRED = ["category", "categoryShort", "artist", "year"]
GRAMMYS_EXPECTED = ["spotify", "artistWikipedia", "artistDescription"]
GRAMMYS_VALID_SHORT = {"AOTY", "ROTY", "SOTY", "BNA"}
GRAMMYS_SPOTIFY_TYPES = {"album", "track", "artist"}

def validate_grammys():
    fp = os.path.join(ROOT, "grammys-data.js")
    data = _load_js_array(fp, "GRAMMYS_DATA")
    rpt = DeckReport("Grammy Big Four", len(data))

    syn = _node_parse(fp)
    if syn is True:
        rpt.ok("JS syntax valid")
    else:
        rpt.error(f"JS syntax error: {syn}")

    # REQUIRED
    req_missing = {}
    for entry in data:
        label = f"{entry.get('artist','?')} / {entry.get('categoryShort','?')} ({entry.get('year','?')})"
        for f in GRAMMYS_REQUIRED:
            v = entry.get(f)
            if v is None or v == "":
                req_missing.setdefault(f, []).append(label)
    if not req_missing:
        rpt.ok("All REQUIRED fields present")
    else:
        for f, names in req_missing.items():
            rpt.error(f"{len(names)} entries missing REQUIRED field '{f}' — e.g. {names[0]}")

    # EXPECTED — work is expected for non-BNA only
    exp_missing = {}
    for entry in data:
        cs = entry.get("categoryShort")
        check_fields = list(GRAMMYS_EXPECTED)
        if cs != "BNA":
            check_fields.append("work")
        for f in check_fields:
            v = entry.get(f)
            if v is None or v == "":
                exp_missing.setdefault(f, []).append(entry.get("artist", "?"))
    if not exp_missing:
        rpt.ok("All EXPECTED fields present")
    else:
        for f, names in exp_missing.items():
            rpt.warn(f"{len(names)} entries missing EXPECTED field '{f}'")

    # SHAPE
    shape_issues = []
    seen_combos = set()
    for entry in data:
        label = f"{entry.get('artist','?')} / {entry.get('categoryShort','?')} ({entry.get('year','?')})"

        yr = entry.get("year")
        if yr is not None:
            if not isinstance(yr, int) or not (1959 <= yr <= 2026):
                shape_issues.append(("error", f"{label}: year {yr!r} not int in 1959-2026"))

        cs = entry.get("categoryShort")
        if cs and cs not in GRAMMYS_VALID_SHORT:
            shape_issues.append(("error", f"{label}: categoryShort {cs!r} not in {sorted(GRAMMYS_VALID_SHORT)}"))

        # BNA should NOT have a work field
        if cs == "BNA":
            w = entry.get("work")
            if w and w.strip():
                shape_issues.append(("warn", f"{label}: BNA entry has non-empty work field"))

        # Non-BNA SHOULD have work
        if cs and cs != "BNA":
            w = entry.get("work")
            if not w or not w.strip():
                shape_issues.append(("warn", f"{label}: non-BNA entry missing work field"))

        st = entry.get("spotifyType")
        if st and st not in GRAMMYS_SPOTIFY_TYPES:
            shape_issues.append(("error", f"{label}: spotifyType {st!r} not in {sorted(GRAMMYS_SPOTIFY_TYPES)}"))

        combo = (entry.get("artist"), entry.get("categoryShort"), entry.get("year"))
        if combo in seen_combos:
            shape_issues.append(("error", f"{label}: duplicate artist+category+year combo"))
        seen_combos.add(combo)

    if not shape_issues:
        rpt.ok("All shape checks pass")
    else:
        for lv, msg in shape_issues:
            if lv == "error":
                rpt.error(msg)
            else:
                rpt.warn(msg)

    return rpt


# ── Best Picture ────────────────────────────────────────────────────

BP_REQUIRED = ["year", "movie", "director", "stars"]
BP_EXPECTED = ["trailer", "nominees"]

def validate_bestpicture():
    fp = os.path.join(ROOT, "decks", "bestpicture-data.js")
    data = _load_esm_array(fp)
    rpt = DeckReport("Best Picture", len(data))

    syn = _node_parse(fp)
    if syn is True:
        rpt.ok("JS syntax valid")
    else:
        rpt.error(f"JS syntax error: {syn}")

    # REQUIRED
    req_missing = {}
    for entry in data:
        label = f"{entry.get('movie','?')} ({entry.get('year','?')})"
        for f in BP_REQUIRED:
            v = entry.get(f)
            if v is None or v == "" or (isinstance(v, list) and not v):
                req_missing.setdefault(f, []).append(label)
    if not req_missing:
        rpt.ok("All REQUIRED fields present")
    else:
        for f, names in req_missing.items():
            rpt.error(f"{len(names)} entries missing REQUIRED field '{f}' — e.g. {names[0]}")

    # EXPECTED
    exp_missing = {}
    for entry in data:
        for f in BP_EXPECTED:
            v = entry.get(f)
            if v is None or v == "" or (isinstance(v, list) and not v):
                exp_missing.setdefault(f, []).append(entry.get("movie", "?"))
    if not exp_missing:
        rpt.ok("All EXPECTED fields present")
    else:
        for f, names in exp_missing.items():
            rpt.warn(f"{len(names)} entries missing EXPECTED field '{f}'")

    # SHAPE
    shape_issues = []
    seen_years = set()
    for entry in data:
        label = f"{entry.get('movie','?')} ({entry.get('year','?')})"

        yr = entry.get("year")
        if yr is not None:
            if not isinstance(yr, int) or not (1928 <= yr <= 2027):
                shape_issues.append(("error", f"{label}: year {yr!r} not int in 1928-2027"))

        stars = entry.get("stars")
        if isinstance(stars, list):
            if len(stars) < 1 or len(stars) > 5:
                shape_issues.append(("warn", f"{label}: stars has {len(stars)} entries (expected 1-5)"))
            for s in stars:
                if not isinstance(s, str) or not s.strip():
                    shape_issues.append(("error", f"{label}: stars entry {s!r} is empty/non-string"))

        if yr in seen_years:
            shape_issues.append(("error", f"{label}: duplicate year {yr}"))
        seen_years.add(yr)

    if not shape_issues:
        rpt.ok("All shape checks pass")
    else:
        for lv, msg in shape_issues:
            if lv == "error":
                rpt.error(msg)
            else:
                rpt.warn(msg)

    return rpt


# ── Chains ──────────────────────────────────────────────────────────

def validate_chains():
    fp = os.path.join(ROOT, "chains.js")
    rpt = DeckReport("Chains", 0)

    syn = _node_parse(fp)
    if syn is True:
        rpt.ok("JS syntax valid")
    else:
        rpt.error(f"JS syntax error: {syn}")

    rpt.ok("Run validate_chains.py separately for full chain-level checks")
    return rpt


# ── Main ────────────────────────────────────────────────────────────

def main():
    strict = "--strict" in sys.argv
    reports = []

    validators = [
        validate_rockhall,
        validate_songs,
        validate_grammys,
        validate_bestpicture,
        validate_chains,
    ]

    for vfn in validators:
        try:
            rpt = vfn()
        except Exception as exc:
            rpt = DeckReport(vfn.__name__.replace("validate_", "").title(), 0)
            rpt.error(f"Failed to load data: {exc}")
        reports.append(rpt)

    for rpt in reports:
        rpt.print()

    total_errors = sum(r.errors for r in reports)
    total_warnings = sum(r.warnings for r in reports)

    print(f"\nSUMMARY: {total_warnings} warnings, {total_errors} errors")

    if total_errors:
        sys.exit(1)
    if strict and total_warnings:
        sys.exit(1)


if __name__ == "__main__":
    main()
