#!/usr/bin/env python3
"""
Fetch a short Wikipedia summary + thumbnail for every chain founder.
Writes founders.js → window.FOUNDERS = { name → {summary, thumb, page} }.
"""
import json, urllib.request, urllib.parse, urllib.error, gzip, time, os, re

def http_json(url, max_retries=4):
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": "Crammys/1.0 (personal flashcard app)",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            if e.code == 429 and attempt < max_retries - 1:
                w = 2 ** (attempt + 1)
                print(f"    429 — sleeping {w}s"); time.sleep(w); continue
            raise

# Manual page-name overrides — for founders whose Wikipedia article isn't
# at "/wiki/<Name>" because of disambiguation or alternative forms.
PAGE_OVERRIDES = {
    # Default REST API lookups returned 404 or disambiguation pages; these
    # are the actual article titles. Tom Monaghan works as "Tom_Monaghan"
    # — the issue was the script was finding a stale cached None for it.
}

def summary(name):
    title = PAGE_OVERRIDES.get(name, name).replace(" ", "_")
    safe = urllib.parse.quote(title, safe="")
    return http_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe}")

def main():
    with open("chains/manifest.json") as f:
        chains = json.load(f)
    names = sorted({n for c in chains for n in (c.get("founders") or [])})
    print(f"Resolving {len(names)} unique founders…\n")

    existing = {}
    if os.path.exists("founders.js"):
        # Reload existing to keep it resumable
        txt = open("founders.js").read()
        m = re.search(r"window\.FOUNDERS\s*=\s*(\{.*\});\s*$", txt, re.DOTALL)
        if m:
            existing = json.loads(m.group(1))

    out = dict(existing)
    for i, name in enumerate(names, 1):
        if name in out and out[name] and out[name].get("summary"):
            continue
        try:
            s = summary(name)
        except Exception as e:
            print(f"[{i}/{len(names)}] {name}  ! {e}"); continue
        if not s:
            print(f"[{i}/{len(names)}] {name}  · no Wikipedia page"); out[name] = None; continue
        rec = {
            "name": s.get("title") or name,
            "description": s.get("description"),
            "summary": (s.get("extract") or "")[:260],
            "thumb": (s.get("thumbnail") or {}).get("source"),
            "page": (s.get("content_urls") or {}).get("desktop", {}).get("page"),
        }
        out[name] = rec
        print(f"[{i}/{len(names)}] {name}  ✓ {rec['description'] or '?'}")
        # Incremental save
        if i % 5 == 0:
            with open("founders.js", "w") as f:
                f.write("window.FOUNDERS = " + json.dumps(out, ensure_ascii=False) + ";\n")
        time.sleep(0.8)

    with open("founders.js", "w") as f:
        f.write("window.FOUNDERS = " + json.dumps(out, ensure_ascii=False) + ";\n")
    have = sum(1 for v in out.values() if v)
    print(f"\nDone. {have}/{len(names)} founders have a summary.")

if __name__ == "__main__":
    main()
