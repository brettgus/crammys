#!/usr/bin/env python3
"""
Last-mile: hit the rendered HTML of each remaining chain's Wikipedia page
and pull the infobox <img> directly. Wikipedia serves a /static/ thumbnail
URL we can download (no Commons hop needed).
"""
import urllib.request, urllib.parse, gzip, re, os, time, json

REMAINING = [
    "Chipotle_Mexican_Grill",
    "Bojangles'",
    "El_Pollo_Loco",
    "Cava_(restaurant)",
    "Noodles_%26_Company",
]

NAME_FOR_SLUG = {
    "Chipotle_Mexican_Grill": "Chipotle Mexican Grill",
    "Bojangles'":             "Bojangles'",
    "El_Pollo_Loco":          "El Pollo Loco",
    "Cava_(restaurant)":      "CAVA",
    "Noodles_%26_Company":    "Noodles & Company",
}

def http_text(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Crammys/1.0 (personal flashcard app)",
        "Accept": "text/html",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data.decode("utf-8", "ignore")

def http_bytes(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Crammys/1.0 (personal flashcard app)",
    })
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read(), r.url

def slug(s):
    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')

def find_infobox_img(html):
    # The infobox is a <table class="infobox …"> with the brand image near the top.
    m = re.search(r'<table[^>]*class="[^"]*infobox[^"]*"[^>]*>(.*?)</table>', html, re.DOTALL | re.IGNORECASE)
    if not m: return None
    box = m.group(1)
    # First <img>:
    img = re.search(r'<img\b[^>]+src="([^"]+)"', box, re.IGNORECASE)
    if not img: return None
    src = img.group(1)
    if src.startswith("//"): src = "https:" + src
    # Use the size Wikipedia already chose (custom sizes 400 the bot filter)
    return src

def main():
    with open("chains/manifest.json", encoding="utf-8") as f:
        chains = json.load(f)
    by_name = {c["name"]: c for c in chains}

    for slug_ in REMAINING:
        name = NAME_FOR_SLUG[slug_]
        print(f"--- {name}  ({slug_})")
        try:
            html = http_text(f"https://en.wikipedia.org/wiki/{slug_}")
        except Exception as e:
            print(f"  ! page fetch: {e}"); continue
        src = find_infobox_img(html)
        if not src:
            print("  · no infobox <img> found"); continue
        try:
            data, final_url = http_bytes(src)
        except Exception as e:
            print(f"  ! download: {e}"); continue
        ext = os.path.splitext(urllib.parse.urlparse(final_url).path)[1] or ".png"
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".svg", ".webp"): ext = ".png"
        path = os.path.join("chains/logos", f"{slug(name)}{ext}")
        # Remove the old storefront photo if it lived under a different extension
        c = by_name[name]
        old = c.get("logo")
        if old and old != path and os.path.exists(old):
            try: os.remove(old)
            except: pass
        with open(path, "wb") as f:
            f.write(data)
        c["logo"] = path
        c["logo_filename"] = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(final_url).path))
        print(f"  + {path}  ({len(data)} bytes)")
        time.sleep(1.2)

    with open("chains/manifest.json", "w", encoding="utf-8") as f:
        json.dump(chains, f, ensure_ascii=False, indent=2)
    with open("chains.js", "w", encoding="utf-8") as f:
        f.write("window.CHAINS_DECK = " + json.dumps(chains, ensure_ascii=False) + ";\n")
    have = sum(1 for c in chains if c.get("logo"))
    print(f"\nCoverage: {have}/{len(chains)} chains have a logo.")

if __name__ == "__main__":
    main()
