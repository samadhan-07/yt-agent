"""AI image generation via Pollinations (FLUX). Anonymous tier works but is
rate-limited (~1 request / 15 s). Set POLLINATIONS_API_KEY to lift that."""
import os, time, requests
from urllib.parse import quote

BASE = "https://image.pollinations.ai/prompt/"
_last_call = 0.0

def generate(prompt, style, dest, seed, model="flux", delay=16, width=1080, height=1920):
    global _last_call
    full = f"{prompt}. {style}"
    params = {"width": width, "height": height, "model": model,
              "seed": seed, "nologo": "true", "enhance": "false"}
    headers = {}
    key = os.environ.get("POLLINATIONS_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
        delay = min(delay, 2)
    last = None
    for attempt in range(5):
        wait = delay - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            r = requests.get(BASE + quote(full), params=params, headers=headers, timeout=180)
            ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image")
            if ok and len(r.content) > 10_000:
                with open(dest, "wb") as f:
                    f.write(r.content)
                return dest
            last = f"HTTP {r.status_code} {r.headers.get('content-type')} ({len(r.content)} bytes)"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Image generation failed for '{prompt[:50]}...': {last}")
