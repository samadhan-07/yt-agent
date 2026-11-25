import json, os, random, sys, time, requests

PROMPT = """You write scripts for a cartoon-animated YouTube Shorts series for a family audience in India.
The narrator is Bittu, a cheerful cartoon mascot who talks straight to the viewer in a playful, energetic voice.
The content is family-friendly and suitable for all ages, but NOT directed specifically at young children.
Series name: {series}
Channel niche: {niche}
Style: {style}
Language of ALL narration, the title and the description: {lang} (if Hindi, write in Devanagari and keep common English tech words where they sound natural).
Narration length: about {words} words in total (about {secs} seconds when spoken).
{topic_line}
{format_line}

Earlier videos - do NOT repeat or closely resemble these:
{past}
{winners}
Rules:
- Scene 1 is the hook and must stop the scroll in the first 2 seconds. Start immediately with a concrete surprise, shocking number, myth-busting contradiction ("आप जो मानते हैं वो आधा सच है" style), or sharp curiosity question. Under 9 words. Zero filler, zero greetings, zero "आज हम बात करेंगे".
- Scene 2 must raise the stakes or curiosity gap right away so the viewer stays for the payoff.
- Relate it to daily Indian life where it fits (chai, monsoon, trains, cricket in general terms, school, festivals), without brands or real people.
- Every scene is ONE punchy sentence of 5 to 8 words (never more than 9). Plain, conversational language.
- The whole narration must stay close to {words} words. Count the words before you answer.
- The LAST scene must deliver a crisp payoff and echo the opening hook so the video loops smoothly.
- Write in Bittu's playful voice: short natural exclamations are fine, but keep factual accuracy front and center.
- Facts must be accurate and checkable. If you are not sure of a claim, leave it out. No health, medical, legal or money ADVICE; explain things in general terms only.
- No real people, celebrities, brands, logos, or characters from films, games or cartoons, in the text or the image prompts. Describe ideas generically.
- No clickbait lies and no fear-mongering.
- emotion: choose Bittu's visual expression that best matches the sentence (excited, curious, shocked, thinking, happy, or scared).
- image_prompt: ONE colorful cartoon-style BACKGROUND scene in English (setting, clear focal subject, mood, camera angle) that matches the sentence. Place the main visual action in the upper and middle portion of the frame. No people and no characters (the mascot is added later), no text or letters. Vary the composition between scenes.

Return ONLY JSON with this shape:
{{
  "title": "max 60 chars, promises a concrete payoff the video really delivers (a surprising number, 'why', 'truth' or 'secret'), in the video language",
  "description": "2 or 3 short sentences that include 2 or 3 searchable keywords",
  "hashtags": ["3 to 5 words without #"],
  "visual_style": "one consistent art direction used for EVERY image",
  "scenes": [
    {{
      "text": "one spoken sentence",
      "emotion": "one of: excited, curious, shocked, thinking, happy, scared",
      "image_prompt": "English description of ONE image"
    }}
  ]
}}
Use 10 to 12 scenes. No emojis in "text"."""

DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash"]

RETRYABLE = {429, 500, 502, 503, 504}
TRIES_PER_MODEL = 3
BASE_WAIT = 8
MAX_TOTAL_SECONDS = 600
VALID_EMOTIONS = {"excited", "curious", "shocked", "thinking", "happy", "scared"}


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
        emo = str(s.get("emotion", "happy")).strip().lower()
        s["emotion"] = emo if emo in VALID_EMOTIONS else "happy"
    if max_words:
        n = sum(len(s["text"].split()) for s in data["scenes"])
        assert n <= max_words, f"narration too long ({n} words > {max_words})"
    return data


def _word_count(data):
    return sum(len(s["text"].split()) for s in data["scenes"])


def generate(cfg, past_titles, topic=None, winners=None, fmt=None):
    key = os.environ["GEMINI_API_KEY"]
    target = int(cfg.get("target_seconds", 30))
    words = int(target * 2.5)
    winners_block = ""
    if winners:
        winners_block = ("Titles that performed best so far (make videos in this spirit, but never repeat them):\n"
                         + "\n".join(f"- {t}" for t in winners) + "\n")
    base_prompt = PROMPT.format(
        series=cfg.get("series", ""), niche=cfg["niche"], style=cfg.get("style_notes", ""),
        lang=cfg.get("language", "en"), words=words, secs=target,
        past="\n".join(f"- {t}" for t in past_titles) or "(none yet)",
        winners=winners_block,
        format_line=(f"Format of today's video: {fmt}" if fmt else ""),
        topic_line=(f"Make the video about this specific topic: {topic}" if topic
                    else "Pick a fresh topic yourself that would make an Indian family stop scrolling: something surprising, visual and relatable from daily life, nature, space or the body. Avoid dry textbook topics."),
    )
    hard_cap = int(words * 1.65)
    soft_cap = int(words * 1.30)
    feedback = ""

    def make_body():
        return {
            "contents": [{"parts": [{"text": base_prompt + feedback}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
        }

    deadline = time.time() + MAX_TOTAL_SECONDS
    errors = []
    for model in _model_chain(cfg):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(1, TRIES_PER_MODEL + 1):
            tag = f"{model} (try {attempt}/{TRIES_PER_MODEL})"
            try:
                if time.time() > deadline:
                    raise RuntimeError("Script generation gave up after " + str(MAX_TOTAL_SECONDS) + "s:\n  " + "\n  ".join(errors))
                r = requests.post(url, params={"key": key}, json=make_body(), timeout=90)

                if r.status_code in RETRYABLE:
                    msg = f"HTTP {r.status_code}: {r.text[:200]}"
                    errors.append(f"{tag}: {msg}")
                    print(f"WARN {tag} -> {msg}", flush=True)
                    if attempt < TRIES_PER_MODEL:
                        wait = BASE_WAIT * (2 ** (attempt - 1)) + random.uniform(0, 3)
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
                data = _parse_and_validate(r.json(), max_words=hard_cap)
                n = _word_count(data)
                if n > soft_cap:
                    print(f"WARN: script is {n} words (target {words}); video may run long.", flush=True)
                print(f"Script generated with {model} ({n} words, {len(data['scenes'])} scenes)", flush=True)
                return data

            except RuntimeError:
                raise
            except (requests.RequestException, ValueError, AssertionError, KeyError) as e:
                if isinstance(e, AssertionError) and "too long" in str(e):
                    feedback = (f"\n\nYour previous answer was too long. The limit is about {words} words in total. "
                                f"Rewrite with fewer scenes and much shorter sentences (5 to 8 words each).")
                errors.append(f"{tag}: {e!r}")
                print(f"WARN {tag} -> {e!r}", flush=True)
                if attempt < TRIES_PER_MODEL:
                    time.sleep(BASE_WAIT * attempt)

        print(f"Moving on from {model}", file=sys.stderr, flush=True)

    raise RuntimeError("Script generation failed on all models:\n  " + "\n  ".join(errors))
