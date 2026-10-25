import json, os, random, sys, time, requests

PROMPT = """You write scripts for a faceless YouTube Shorts series for teenagers and young adults in India.
The content is family-friendly and NOT aimed at young children.
Series name: {series}
Channel niche: {niche}
Style: {style}
Language of ALL narration, the title and the description: {lang} (if Hindi, write in Devanagari and keep common English tech words where they sound natural).
Narration length: about {words} words in total (about {secs} seconds when spoken).
{topic_line}

Earlier videos - do NOT repeat or closely resemble these:
{past}
{winners}
Rules:
- Scene 1 is the hook: the single most surprising fact or question, under 12 words. No greeting, no "today we will talk about".
- Every scene is ONE short sentence (about 8 to 14 words). Plain, relatable language.
- The LAST scene must echo the opening idea so the video loops back into the hook.
- Facts must be accurate and checkable. If you are not sure of a claim, leave it out. No health, medical, legal or money ADVICE; explain things in general terms only.
- No real people, celebrities, brands, logos, or characters from films, games or cartoons, in the text or the image prompts. Describe ideas generically.
- No clickbait lies and no fear-mongering.
- image_prompt: ONE concrete visual in English (subject, setting, mood, camera angle). No text or letters in the image. Vary the composition between scenes.

Return ONLY JSON with this shape:
{{
  "title": "max 60 chars, curiosity-driven, honest, in the video language",
  "description": "2 or 3 short sentences that include 2 or 3 searchable keywords",
  "hashtags": ["3 to 5 words without #"],
  "visual_style": "one consistent art direction used for EVERY image",
  "scenes": [
    {{"text": "one spoken sentence", "image_prompt": "English description of ONE image"}}
  ]
}}
Use 12 to 16 scenes. No emojis in "text"."""

DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]

RETRYABLE = {429, 500, 502, 503, 504}
TRIES_PER_MODEL = 2
BASE_WAIT = 8


def _model_chain(cfg):
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


def _parse_and_validate(resp_json, max_words=None):
    try:
        text = resp_json["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(f"No candidate text in response: {str(resp_json)[:300]}")
    data = json.loads(_clean_json_text(text))
    assert data["title"] and data["visual_style"] and len(data["scenes"]) >= 8, "script too short/incomplete"
    for s in data["scenes"]:
        assert s["text"].strip() and s["image_prompt"].strip(), "empty scene field"
    if max_words:
        n = sum(len(s["text"].split()) for s in data["scenes"])
        assert n <= max_words, f"narration too long ({n} words > {max_words})"
    return data


def generate(cfg, past_titles, topic=None, winners=None):
    key = os.environ["GEMINI_API_KEY"]
    target = int(cfg.get("target_seconds", 38))
    words = int(target * 2.5)
    winners_block = ""
    if winners:
        winners_block = ("Titles that performed best so far (make videos in this spirit, but never repeat them):\n"
                         + "\n".join(f"- {t}" for t in winners) + "\n")
    prompt = PROMPT.format(
        series=cfg.get("series", ""), niche=cfg["niche"], style=cfg.get("style_notes", ""),
        lang=cfg.get("language", "en"), words=words, secs=target,
        past="\n".join(f"- {t}" for t in past_titles) or "(none yet)",
        winners=winners_block,
        topic_line=(f"Make the video about this specific topic: {topic}" if topic
                    else "Pick a fresh, interesting topic yourself that fits the niche."),
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }

    errors = []
    for model in _model_chain(cfg):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(1, TRIES_PER_MODEL + 1):
            tag = f"{model} (try {attempt}/{TRIES_PER_MODEL})"
            try:
                r = requests.post(url, params={"key": key}, json=body, timeout=90)

                if r.status_code in RETRYABLE:
                    msg = f"HTTP {r.status_code}: {r.text[:200]}"
                    errors.append(f"{tag}: {msg}")
                    print(f"WARN {tag} -> {msg}", flush=True)
                    if attempt < TRIES_PER_MODEL:
                        wait = BASE_WAIT * attempt + random.uniform(0, 3)
                        print(f"   retrying in {wait:.0f}s...", flush=True)
                        time.sleep(wait)
                    continue

                if r.status_code == 404:
                    msg = f"HTTP 404 (model unavailable): {r.text[:200]}"
                    errors.append(f"{tag}: {msg}")
                    print(f"WARN {tag} -> {msg}", flush=True)
                    break

                if r.status_code in (400, 401, 403):
                    raise RuntimeError(f"{model} returned HTTP {r.status_code}: {r.text[:300]}")

                r.raise_for_status()
                data = _parse_and_validate(r.json(), max_words=int(words * 1.4))
                print(f"Script generated with {model}", flush=True)
                return data

            except RuntimeError:
                raise
            except (requests.RequestException, ValueError, AssertionError, KeyError) as e:
                errors.append(f"{tag}: {e!r}")
                print(f"WARN {tag} -> {e!r}", flush=True)
                if attempt < TRIES_PER_MODEL:
                    time.sleep(BASE_WAIT * attempt)

        print(f"Moving on from {model}", file=sys.stderr, flush=True)

    raise RuntimeError("Script generation failed on all models:\n  " + "\n  ".join(errors))
