import json, os, random, sys, time, requests

PROMPT = """You write scripts for faceless, fully AI-generated YouTube Shorts.
Channel niche: {niche}
Style: {style}
Language: {lang}
Narration length: about {words} words total (must be under 55 seconds when spoken).
{topic_line}

Do NOT repeat or closely resemble these earlier topics:
{past}

Return ONLY JSON with this shape:
{{
  "title": "max 70 chars, curiosity-driven, no clickbait lies",
  "description": "2 short sentences",
  "hashtags": ["3 to 5 words without #"],
  "visual_style": "one consistent art direction used for EVERY image, e.g. 'cinematic digital painting, dramatic lighting, rich colors, vertical 9:16, no text'",
  "scenes": [
    {{"text": "one or two spoken sentences",
      "image_prompt": "a vivid, concrete description of ONE image for this scene (subject, setting, mood, camera angle). English. No text, letters, logos or real people's faces."}}
  ]
}}
Use 6 to 9 scenes. Scene 1 is a strong hook. The last scene is a short closing line.
Facts must be accurate. No emojis in "text"."""

# Used when config.yaml has no gemini_models / gemini_model. Verify these names against
# the models your API key can actually use (Google retires older ones over time).
DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]

# Temporary, server-side problems: worth retrying / switching model
RETRYABLE = {429, 500, 502, 503, 504}
TRIES_PER_MODEL = 2   # quick retries on the same model before moving to the next one
BASE_WAIT = 8         # seconds; grows 8s, 16s... plus jitter


def _model_chain(cfg):
    """config.yaml may define `gemini_models: [a, b, c]` (preferred) or legacy `gemini_model: a`."""
    models = list(cfg.get("gemini_models") or [])
    if not models and cfg.get("gemini_model"):
        models = [cfg["gemini_model"]] + list(cfg.get("gemini_fallbacks") or [])
    return models or DEFAULT_MODELS


def _clean_json_text(text):
    t = text.strip()
    if t.startswith("```json"):
        t = t.split("```json")[1].split("```")[0].strip()
    elif t.startswith("```"):
        t = t.split("```")[1].split("```")[0].strip()
    return t


def _parse_and_validate(resp_json):
    try:
        text = resp_json["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(f"No candidate text in response: {str(resp_json)[:300]}")
    data = json.loads(_clean_json_text(text))
    assert data["title"] and data["visual_style"] and len(data["scenes"]) >= 4, "script too short/incomplete"
    for s in data["scenes"]:
        assert s["text"].strip() and s["image_prompt"].strip(), "empty scene field"
    return data


def generate(cfg, past_titles, topic=None):
    key = os.environ["GEMINI_API_KEY"]
    prompt = PROMPT.format(
        niche=cfg["niche"], style=cfg.get("style_notes", ""), lang=cfg.get("language", "en"),
        words=int(cfg.get("target_seconds", 40) * 2.5),
        past="\n".join(f"- {t}" for t in past_titles) or "(none yet)",
        topic_line=(f"Make the video about this specific topic: {topic}" if topic else "Pick a fresh, interesting topic yourself."),
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }

    errors = []  # every failure is recorded, so the final message is never "None"

    for model in _model_chain(cfg):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(1, TRIES_PER_MODEL + 1):
            tag = f"{model} (try {attempt}/{TRIES_PER_MODEL})"
            try:
                r = requests.post(url, params={"key": key}, json=body, timeout=90)

                if r.status_code in RETRYABLE:
                    msg = f"HTTP {r.status_code}: {r.text[:200]}"
                    errors.append(f"{tag}: {msg}")
                    print(f"⚠️ {tag} -> {msg}", flush=True)
                    if attempt < TRIES_PER_MODEL:
                        wait = BASE_WAIT * attempt + random.uniform(0, 3)
                        print(f"   retrying in {wait:.0f}s...", flush=True)
                        time.sleep(wait)
                    continue

                if r.status_code == 404:
                    # model name doesn't exist / retired for this key -> skip to next model
                    msg = f"HTTP 404 (model unavailable): {r.text[:200]}"
                    errors.append(f"{tag}: {msg}")
                    print(f"⚠️ {tag} -> {msg}", flush=True)
                    break

                if r.status_code in (400, 401, 403):
                    # bad request / bad key / quota-permission problem: another try won't help
                    raise RuntimeError(f"{model} returned HTTP {r.status_code}: {r.text[:300]}")

                r.raise_for_status()
                data = _parse_and_validate(r.json())
                print(f"✅ Script generated with {model}", flush=True)
                return data

            except RuntimeError:
                raise  # fatal config/auth error from above
            except (requests.RequestException, ValueError, AssertionError, KeyError) as e:
                # network error, timeout, bad JSON, or script failed validation -> retry
                errors.append(f"{tag}: {e!r}")
                print(f"⚠️ {tag} -> {e!r}", flush=True)
                if attempt < TRIES_PER_MODEL:
                    time.sleep(BASE_WAIT * attempt)

        print(f"↪️ Moving on from {model}", file=sys.stderr, flush=True)

    raise RuntimeError("Script generation failed on all models:\n  " + "\n  ".join(errors))
