#!/usr/bin/env python3
"""
Use Claude Haiku 4.5 vision to flag images that visibly display the movie title
(or other clearly-identifying text). Image-mode pickers should skip the flagged
images so they don't spoil the answer.

Resumable: writes results incrementally to spoilers.json + spoilers.js.
Reads the API key from .env (ANTHROPIC_API_KEY=...) or the environment.
"""
import os, json, base64, urllib.request, urllib.error, time, sys

MODEL = "claude-haiku-4-5"
API = "https://api.anthropic.com/v1/messages"

def load_env():
    env = {}
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

ENV = load_env()
API_KEY = ENV.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    print("ANTHROPIC_API_KEY not found in .env or environment"); sys.exit(1)

PROMPT = (
    'You are helping QA a movie-trivia flashcard. The user has to guess the film "{title}" '
    'from this image. If this image clearly displays the movie title text, opening credits, '
    'a title card, a marquee, or any prominent text that would tip off the answer, reply with '
    'just one word: YES. Otherwise reply with just one word: NO. '
    'Background props (street signs, newspapers) should not count unless they explicitly name the film.'
)

def check_image(path, title):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    body = {
        "model": MODEL,
        "max_tokens": 5,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": PROMPT.format(title=title)},
            ],
        }],
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={
            "x-api-key": API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"HTTP {e.code}: {msg}")
    text = resp.get("content", [{}])[0].get("text", "").strip().upper()
    return text.startswith("YES")

def save(spoilers):
    with open("spoilers.json", "w", encoding="utf-8") as f:
        json.dump(spoilers, f, indent=1)
    # JS shim for the app + review page (no fetch over file://)
    with open("spoilers.js", "w", encoding="utf-8") as f:
        f.write("window.SPOILERS = " + json.dumps(spoilers, ensure_ascii=False) + ";\n")

def main():
    if not os.path.exists("images/manifest.json"):
        print("images/manifest.json missing — run fetch_images.py first"); sys.exit(1)
    with open("images/manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    spoilers = {}
    if os.path.exists("spoilers.json"):
        with open("spoilers.json", encoding="utf-8") as f:
            spoilers = json.load(f)
        print(f"Resuming from {len(spoilers)} cached results.")

    total = sum(len(m.get("images") or []) for m in manifest)
    seen = 0
    for me in manifest:
        title = me["movie"]
        for img in me.get("images") or []:
            seen += 1
            fname = img["f"]
            if fname in spoilers:
                continue
            path = os.path.join("images", fname)
            if not os.path.exists(path):
                continue
            try:
                is_spoiler = check_image(path, title)
            except Exception as e:
                print(f"[{seen}/{total}] {fname}  ! {e}")
                time.sleep(2)
                continue
            spoilers[fname] = is_spoiler
            print(f"[{seen}/{total}] {fname}  {'🚫 SPOILER' if is_spoiler else '✓ ok'}  · {title}")
            if seen % 5 == 0:
                save(spoilers)
            time.sleep(0.15)
    save(spoilers)
    flagged = sum(1 for v in spoilers.values() if v)
    print(f"\nDone. {flagged} of {len(spoilers)} flagged as spoilers.")
    print("Run review.html to eyeball + override.")

if __name__ == "__main__":
    main()
