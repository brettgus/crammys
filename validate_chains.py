#!/usr/bin/env python3
"""
Per-chain data validation. Run after the fetch + fix pipeline to make sure
every chain has the fields the app expects, and that values are well-formed.

Levels:
  REQUIRED — exits non-zero if any chain is missing this. The card can't render.
  EXPECTED — warns but doesn't fail. Optional-but-should-have data.
  SHAPE    — value format checks (HQ should have a comma, founded looks like a
             year, US locations is a positive int, logo file exists, etc.)

Usage:
  python3 validate_chains.py             # prints report, exit 1 on REQUIRED fail
  python3 validate_chains.py --strict    # also fail on EXPECTED warnings
"""
import json, os, re, sys

# Fields the card UI can't render without
REQUIRED = ["name", "category", "founded", "founders", "hq", "locations", "rank", "logo"]
# Useful but optional — chains without these are still usable, just less rich
EXPECTED = ["origin", "summary", "wiki_slug"]

REASONABLE_YEAR_RANGE = (1900, 2026)

VALID_CATEGORIES = {
    "burgers", "chicken", "pizza", "sandwich", "mexican",
    "coffee", "bakery-cafe", "asian", "fast-casual", "dessert",
}

def load():
    with open("chains/manifest.json") as f:
        return json.load(f)

def check(chains, strict=False):
    errors = []   # REQUIRED violations → exit 1
    warns  = []   # EXPECTED + SHAPE violations → exit 1 only with --strict

    seen_names = {}
    seen_logos = {}
    for c in chains:
        name = c.get("name") or "<unnamed>"

        # REQUIRED
        for f in REQUIRED:
            v = c.get(f)
            empty = v is None or v == "" or (isinstance(v, list) and not v)
            if empty:
                errors.append(f"{name}: missing REQUIRED field {f!r}")

        # EXPECTED
        for f in EXPECTED:
            v = c.get(f)
            if v is None or v == "":
                warns.append(f"{name}: missing EXPECTED field {f!r}")

        # ── SHAPE checks ─────────────────────────────────────────────
        # Category in known set
        cat = c.get("category")
        if cat and cat not in VALID_CATEGORIES:
            errors.append(f"{name}: category {cat!r} not in {sorted(VALID_CATEGORIES)}")

        # Founded year is plausible
        founded = c.get("founded")
        if founded is not None:
            try:
                y = int(founded)
                if not REASONABLE_YEAR_RANGE[0] <= y <= REASONABLE_YEAR_RANGE[1]:
                    warns.append(f"{name}: founded year {y} out of {REASONABLE_YEAR_RANGE}")
            except (ValueError, TypeError):
                errors.append(f"{name}: founded {founded!r} is not an integer")

        # HQ should be "City, ST" (or end in a 2-letter region / "D.C.")
        hq = c.get("hq")
        if hq and not re.search(r',\s*[A-Z][A-Za-z.]{1,3}$', hq):
            # Allow non-US HQs we explicitly tag with country code (e.g. ", UK", ", ON")
            warns.append(f"{name}: hq {hq!r} doesn't end in ', ST' (state/province)")

        # Origin similar shape when present
        origin = c.get("origin")
        if origin and "," not in origin:
            warns.append(f"{name}: origin {origin!r} has no state/region suffix")

        # Founders is a list of strings, non-empty when present
        founders = c.get("founders") or []
        if not isinstance(founders, list):
            errors.append(f"{name}: founders is not a list")
        else:
            for f in founders:
                if not isinstance(f, str) or not f.strip():
                    errors.append(f"{name}: founder entry {f!r} is empty/non-string")

        # Locations is a positive integer
        loc = c.get("locations")
        if loc is not None:
            if not isinstance(loc, int) or loc <= 0:
                errors.append(f"{name}: locations {loc!r} must be a positive int")
            elif loc > 100_000:
                warns.append(f"{name}: locations {loc} > 100k (sanity check)")

        # Rank is 1..N and unique
        rank = c.get("rank")
        if rank is not None:
            if not isinstance(rank, int) or rank < 1 or rank > len(chains):
                errors.append(f"{name}: rank {rank!r} not in 1..{len(chains)}")

        # Logo file must exist on disk
        logo = c.get("logo")
        if logo and not os.path.exists(logo):
            errors.append(f"{name}: logo file missing on disk: {logo}")

        # Duplicate detection
        if name in seen_names:
            errors.append(f"{name}: duplicate chain name (also at index {seen_names[name]})")
        seen_names[name] = c.get("rank")
        if logo and logo in seen_logos:
            warns.append(f"{name}: shares logo file with {seen_logos[logo]} ({logo})")
        seen_logos[logo] = name

    # Rank uniqueness
    ranks = [c.get("rank") for c in chains if isinstance(c.get("rank"), int)]
    if len(set(ranks)) != len(ranks):
        dups = sorted({r for r in ranks if ranks.count(r) > 1})
        errors.append(f"duplicate rank values: {dups}")

    return errors, warns

def main():
    strict = "--strict" in sys.argv
    chains = load()
    errors, warns = check(chains, strict=strict)

    if warns:
        print(f"WARNINGS ({len(warns)}):")
        for w in warns: print(f"  · {w}")
        print()
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors: print(f"  ! {e}")
        print()

    print(f"Summary: {len(chains)} chains · {len(errors)} errors · {len(warns)} warnings")
    if errors:
        sys.exit(1)
    if strict and warns:
        sys.exit(1)

if __name__ == "__main__":
    main()
