#!/usr/bin/env python3
"""
Append a US state abbreviation (or province for non-US) onto each chain's
hq field, so the back of the card reads "Carpinteria, CA" instead of just
"Carpinteria". 51 chains is small enough to hand-map.
"""
import json

# city → state. Cities that already include the state are left alone.
HQ_STATE = {
    # Burgers
    "Chicago":          "IL",
    "Miami":            "FL",
    "Dublin":           "OH",
    "Lorton":           "VA",
    "Baldwin Park":     "CA",
    "Irvine":           "CA",
    "New York City":    "NY",
    "New York":         "NY",
    "San Antonio":      "TX",
    "Prairie du Sac":   "WI",
    "Franklin":         "TN",
    "Carpinteria":      "CA",
    # Chicken
    "Atlanta":          "GA",
    "Plano":            "TX",
    "Louisville":       "KY",
    "Addison":          "TX",
    "Charlotte":        "NC",
    "Athens":           "GA",
    # Pizza
    "Ann Arbor Charter Township": "MI",
    "Ann Arbor":        "MI",
    "Plano (Texas)":    "TX",
    "Detroit":          "MI",
    "Toledo":           "OH",
    "Bellevue":         "WA",
    "Pasadena":         "CA",
    "Vancouver":        "WA",
    # Sandwich
    "Milford":          "CT",
    "Manasquan":        "NJ",
    "Champaign":        "IL",
    "Jacksonville":     "FL",
    "Sandy Springs":    "GA",
    "Denver":           "CO",
    # Mexican
    "Wheat Ridge":      "CO",
    "Lake Forest":      "CA",
    "Costa Mesa":       "CA",
    # Bakery-cafe / coffee
    "Sunset Hills":     "MO",
    "Lakewood":         "CO",
    "London":           "UK",
    "Seattle":          "WA",
    "Canton":           "MA",
    "Oakville":         "ON",
    "Brooklyn Center":  "MN",
    "Charlotte (NC)":   "NC",
    # Asian / fast-casual
    "Rosemead":         "CA",
    "Scottsdale":       "AZ",
    "Los Angeles":      "CA",
    "Washington, D.C.": "DC",
    "Broomfield":       "CO",
    "Bothell":          "WA",
    "Miami-Dade County":"FL",
    "Georgia":          None,        # Chick-fil-A's manifest just says "Georgia" — already a state
    "Dallas":           "TX",
    "St. Louis":        "MO",
    "Baton Rouge":      "LA",
    "Winston-Salem":    "NC",
    "Culver City":      "CA",
}

def main():
    with open("chains/manifest.json") as f:
        chains = json.load(f)
    for c in chains:
        hq = c.get("hq")
        if not hq: continue
        # Skip if it already has a comma + region (e.g. "Washington, D.C.")
        if "," in hq:
            continue
        if hq not in HQ_STATE:
            print(f"  ! {c['name']:30}  no state mapping for HQ='{hq}'")
            continue
        state = HQ_STATE[hq]
        if state is None:
            # hq is already state-only (e.g. Chick-fil-A → "Georgia"); leave as-is
            continue
        c["hq"] = f"{hq}, {state}"
        print(f"  {c['name']:30}  {hq}  →  {c['hq']}")
    with open("chains/manifest.json", "w") as f:
        json.dump(chains, f, ensure_ascii=False, indent=2)
    with open("chains.js", "w") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(chains, ensure_ascii=False) + ";\n")

if __name__ == "__main__":
    main()
