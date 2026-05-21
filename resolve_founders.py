#!/usr/bin/env python3
"""
For each founder that fetch_founders.py couldn't get (no Wikipedia article, or
the article was a disambiguation page), ask Claude Sonnet (with web_search) to
find the right person and return structured bio data.

Output gets merged into founders.js. Existing good entries are preserved.
"""
import os, json, re, time, sys, threading, urllib.request, urllib.parse, urllib.error, gzip
from concurrent.futures import ThreadPoolExecutor, as_completed

# Unbuffered stdout so progress is visible when redirected to a file.
sys.stdout.reconfigure(line_buffering=True)

# Tunable: how many founder lookups to run in parallel. Anthropic's tier-1 RPM
# limit is comfortably above this; bump if you've got a higher tier.
WORKERS = 5

def _load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env
ENV = _load_env()
KEY = ENV.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
if not KEY:
    print("ANTHROPIC_API_KEY missing"); raise SystemExit(1)

API = "https://api.anthropic.com/v1/messages"

PROMPT = """You are a research assistant resolving the biographical identity of a chain restaurant founder.

The founder's name is **{name}**. They are (co-)founder of **{chain}** (US restaurant chain).

Search the web to identify the right person. Many founders share names with politicians, athletes, etc., so use the chain name as the disambiguator.

Return ONLY valid JSON in this exact shape (no prose, no markdown fences):
{{
  "name": "Canonical full name",
  "description": "One short phrase like 'American businessman, co-founder of {chain}' — under 90 chars",
  "summary": "Two to three sentences of bio — founding role, year if known, anything notable. Plain prose, no markdown.",
  "wikipedia_url": "https://en.wikipedia.org/wiki/... or null if no dedicated article exists",
  "thumb": "https://... direct URL to a small photo of the person, or null"
}}

If you cannot reliably identify the person after searching, return:
{{ "name": "{name}", "found": false }}
"""

def call_claude(name, chain, max_retries=4):
    body = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "tools": [
            {"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
        ],
        "messages": [{
            "role": "user",
            "content": [{"type": "text", "text": PROMPT.format(name=name, chain=chain)}],
        }],
    }
    payload = json.dumps(body).encode()
    for attempt in range(max_retries):
        req = urllib.request.Request(
            API,
            data=payload,
            headers={
                "x-api-key": KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries - 1:
                wait = 30 * (attempt + 1)
                print(f"    429 — sleeping {wait}s and retrying…")
                time.sleep(wait)
                continue
            raise

def extract_text(resp):
    """Pick out the assistant's final text block from a tool-use response."""
    out = []
    for block in resp.get("content") or []:
        if block.get("type") == "text":
            out.append(block.get("text", ""))
    return "\n".join(out).strip()

def extract_json(text):
    """Find the *last* balanced JSON object containing `"name"` in `text`.
    The agent often prefixes the JSON with prose; using the last match avoids
    picking up an example or quoted-citation JSON from the search results."""
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'```', '', text)

    candidates = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            for j in range(i, len(text)):
                if text[j] == "{": depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        chunk = text[i:j+1]
                        try:
                            obj = json.loads(chunk)
                            if isinstance(obj, dict) and ("name" in obj or "found" in obj):
                                candidates.append(obj)
                        except Exception:
                            pass
                        i = j
                        break
        i += 1
    return candidates[-1] if candidates else None

def find_chain_for(name, chains):
    """Return the first chain that lists this founder."""
    for c in chains:
        if name in (c.get("founders") or []):
            return c["name"]
    return None

def needs_resolve(entry):
    """Resume-friendly check: anything missing, marked unresolved, or pointing
    to a disambiguation page is fair game for re-resolution."""
    if not entry: return True
    if entry.get("unresolved"): return True
    desc = (entry.get("description") or "").lower()
    summary = (entry.get("summary") or "").lower()
    if "topics referred to" in desc or "may refer to" in desc: return True
    if "may refer to" in summary: return True
    # No useful content at all
    if not entry.get("summary") and not entry.get("description"): return True
    return False

def resolve_one(name, chain):
    """Run one founder through the agent. Returns the founders.js record."""
    try:
        resp = call_claude(name, chain)
    except Exception as e:
        return None, f"API: {e}"
    text = extract_text(resp)
    rec = extract_json(text)
    if not rec:
        return None, f"no JSON in response. First 200 chars: {text[:200]!r}"
    if rec.get("found") is False:
        return {"name": name, "unresolved": True}, "agent couldn't identify"
    return {
        "name":        rec.get("name") or name,
        "description": rec.get("description"),
        "summary":     rec.get("summary"),
        "thumb":       rec.get("thumb"),
        "page":        rec.get("wikipedia_url"),
        "source":      "agent",
    }, None

def main():
    with open("chains/manifest.json") as f:
        chains = json.load(f)
    existing = {}
    if os.path.exists("founders.js"):
        txt = open("founders.js").read()
        m = re.search(r"window\.FOUNDERS\s*=\s*(\{.*\});\s*$", txt, re.DOTALL)
        if m: existing = json.loads(m.group(1))

    all_founders = sorted({n for c in chains for n in (c.get("founders") or [])})
    todo = [(n, find_chain_for(n, chains) or "a restaurant chain")
            for n in all_founders if needs_resolve(existing.get(n))]
    print(f"Need to resolve: {len(todo)} (parallel workers: {WORKERS})\n")

    out = dict(existing)
    save_lock = threading.Lock()
    def save():
        with save_lock, open("founders.js", "w") as f:
            f.write("window.FOUNDERS = " + json.dumps(out, ensure_ascii=False) + ";\n")

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(resolve_one, name, chain): name for name, chain in todo}
        for fut in as_completed(futures):
            name = futures[fut]
            done += 1
            try:
                rec, err = fut.result()
            except Exception as e:
                print(f"[{done}/{len(todo)}] {name}  ! worker crash: {e}")
                continue
            if rec is None:
                print(f"[{done}/{len(todo)}] {name}  ! {err}")
                continue
            with save_lock:
                out[name] = rec
            save()
            tag = "·" if rec.get("unresolved") else "+"
            note = err or rec.get("description") or "no desc"
            print(f"[{done}/{len(todo)}] {name}  {tag} {note}")

    save()
    resolved = sum(1 for v in out.values() if v and not v.get("unresolved")
                   and (v.get("summary") or v.get("description")))
    print(f"\nDone. {resolved} founders with bio data; {len(out) - resolved} unresolved.")

if __name__ == "__main__":
    main()
