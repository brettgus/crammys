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
    # Origin cities (founding location) not already in the HQ list:
    "Bridgeport":       "CT",
    "Pike Place Market":"WA",
    "San Bernardino":   "CA",
    "Quincy":           "MA",
    "Downey":           "CA",
    "Ypsilanti":        "MI",
    "Wichita":          "KS",
    "Columbus":         "OH",
    "Garden City":      "MI",
    "North Corbin":     "KY",
    "Jeffersontown":    "KY",
    "Boardman":         "OH",
    "Rocky Mount":      "NC",
    "Arlington County": "VA",
    "Anaheim":          "CA",
    "Sauk City":        "WI",
    "Corpus Christi":   "TX",
    "Golden":           "CO",
    "Hamilton":         "ON",
    "Bellevue (WA)":    "WA",
    "Brentwood":        "CA",
    "Boise":            "ID",
    "Burlington":       "VT",
    "Cleveland":        "OH",
    "Decatur":          "AL",
    "Denver (CO)":      "CO",
    "Highland Park":    "IL",
    "Indianapolis":     "IN",
    "Lakewood (CO)":    "CO",
    "Madison":          "WI",
    "Mansfield":        "OH",
    "Memphis":          "TN",
    "Milwaukee":        "WI",
    "Minneapolis":      "MN",
    "Nashville":        "TN",
    "Norwood":          "OH",
    "Oklahoma City":    "OK",
    "Phoenix":          "AZ",
    "Pittsburgh":       "PA",
    "Point Pleasant":   "NJ",
    "Portland":         "OR",
    "Reno":             "NV",
    "Salt Lake City":   "UT",
    "Sandusky":         "OH",
    "Tampa":            "FL",
    "Tucson":           "AZ",
    "Tulsa":            "OK",
    "Wilmington":       "DE",
    "Worcester":        "MA",
    # Dessert / treats batch
    "Sandy Springs":    "GA",   # Cinnabon (also Church's; idempotent)
    "Scottsdale":       "AZ",   # Cold Stone Creamery
    "Canton (MA)":      "MA",
    "Edina":            "MN",   # Dairy Queen
    "Lancaster":        "PA",   # Auntie Anne's
    "Paducah":          "KY",   # Dippin' Dots
    "Greenwich":        "CT",   # Carvel HQ
    "Hartsdale":        "NY",   # Carvel founding city
    "Pasadena (CA)":    "CA",
    "Houston":          "TX",   # Wetzel's Pretzels
    "Emeryville":       "CA",   # Jamba Juice
    "Frisco":           "TX",   # Jamba (newer HQ; brand moved)
    "Whittier":         "CA",   # Cold Stone founding city (also possible)
    "Tempe":            "AZ",   # Cold Stone founding city
    "Glendale":         "CA",   # Baskin-Robbins
    "Burbank":          "CA",
    "Long Beach":       "CA",
    "Ontario":          "CA",
    "Riverside":        "CA",
    "Pomona":           "CA",
    "Joplin":           "MO",
    "Wichita Falls":    "TX",
    "Yermo":            "CA",   # Del Taco founding city
    "Carpinteria (CA)": "CA",
    "Atlanta":          "GA",   # idempotent — already there
    "Hartsdale":        "NY",   # Carvel origin
    "Joliet":           "IL",   # Dairy Queen origin
    "Downingtown":      "PA",   # Auntie Anne's origin
    "Lexington":        "KY",   # Dippin' Dots origin
    "San Luis Obispo":  "CA",   # Jamba origin
    "Redondo Beach":    "CA",   # Wetzel's Pretzels origin
    "Pasadena":         "CA",
    "Emeryville":       "CA",
    "Edina":            "MN",
    "Paducah":          "KY",
    "Scottsdale":       "AZ",
    "Tempe":            "AZ",
    "Lancaster":        "PA",
    "Canton":           "MA",   # already there too
    "Seattle":          "WA",   # Cinnabon origin
    # Origin-city additions for the most recent missing-field audit
    "Kirkwood":         "MO",   # Panera origin
    "Charleston":       "IL",   # Jimmy John's origin
    "Garland":          "TX",   # Wingstop origin
    "Hillsboro":        "OR",   # Papa Murphy's origin
    "Oregon":           "OH",   # Marco's Pizza origin (the Toledo suburb)
    "Statesboro":       "GA",   # Zaxby's origin
    "Rockville":        "MD",   # CAVA origin
    "College Park":     "GA",   # Chick-fil-A HQ
}

def add_state(city):
    if not city: return None
    if "," in city: return city
    s = HQ_STATE.get(city)
    if s is None: return city  # leave alone (None means "already a state name")
    return f"{city}, {s}" if s else None

def main():
    with open("chains/manifest.json") as f:
        chains = json.load(f)
    for c in chains:
        # HQ
        hq = c.get("hq")
        if hq and "," not in hq:
            v = add_state(hq)
            if v and v != hq:
                c["hq"] = v
                print(f"  HQ  {c['name']:30}  {hq}  →  {v}")
            elif hq not in HQ_STATE:
                print(f"  ! HQ  {c['name']:30}  no state mapping for '{hq}'")
        # Origin (founding city)
        origin = c.get("origin")
        if origin and "," not in origin:
            v = add_state(origin)
            if v and v != origin:
                c["origin"] = v
                print(f"  OR  {c['name']:30}  {origin}  →  {v}")
            elif origin not in HQ_STATE:
                print(f"  ! OR  {c['name']:30}  no state mapping for '{origin}'")
    with open("chains/manifest.json", "w") as f:
        json.dump(chains, f, ensure_ascii=False, indent=2)
    with open("chains.js", "w") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(chains, ensure_ascii=False) + ";\n")

if __name__ == "__main__":
    main()
