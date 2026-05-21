#!/usr/bin/env python3
"""
Search Wikimedia Commons for likely logo filenames for chains where neither
Wikidata P154 nor our hardcoded guesses worked. Prints candidates for
manual review (we'll then add the chosen filename to MANUAL_LOGOS).
"""
import urllib.request, urllib.parse, json, gzip, time

TARGETS = [
    "Dunkin'",
    "Taco Bell",
    "Little Caesars",
    "Chipotle Mexican Grill",
    "Panda Express",
    "Wingstop",
    "Marco's Pizza",
    "Zaxby's",
    "Bojangles'",
    "Einstein Bros. Bagels",
    "MOD Pizza",
    "El Pollo Loco",
    "Caribou Coffee",
    "Noodles & Company",
    "Potbelly Sandwich Shop",
    "CAVA",
    "Blaze Pizza",
    "Pei Wei Asian Diner",
]

def http_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Crammys/1.0 (personal flashcard app)",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return json.loads(data)

def search_commons(query):
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query",
        "list": "search",
        "srsearch": f"{query} logo",
        "srnamespace": "6",  # File:
        "srlimit": "6",
        "format": "json",
    })
    d = http_json(url)
    return [r["title"].replace("File:", "") for r in d.get("query", {}).get("search", [])]

for name in TARGETS:
    print(f"\n--- {name}")
    try:
        hits = search_commons(name)
    except Exception as e:
        print(f"  ! {e}"); continue
    for h in hits:
        print(f"  {h}")
    time.sleep(1.0)
