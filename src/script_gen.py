import json, os, random, sys, time, requests

PROMPT = """You write 3-minute scripts for a philosophical storytelling and existential psychology YouTube channel inspired by Pursuit of Wonder.
The narrator speaks in a calm, literary, deeply empathetic voice—never lecturing or using clickbait hype.
Series name: {series}
Channel niche: {niche}
Style: {style}
Language of ALL narration, the title, quote text, and the description: {lang}.
Narration length: about {words} words in total (about {secs} seconds when spoken at a calm, measured pace).
{topic_line}
{format_line}

Earlier videos - do NOT repeat or closely resemble these:
{past}
{winners}
Rules:
- Structure the 3-minute essay in TWO distinct acts:
  1. Act 1 (First ~45% of scenes): Tell a quiet, vivid story about an ordinary fictional character experiencing a relatable inner conflict (waiting for life to start, feeling unseen in a crowd, clinging to control, or mourning an imagined future). Show their inner world through concrete sensory details.
  2. Act 2 (Remaining ~55% of scenes): Gently zoom out from the character's story to unpack the deeper psychological or philosophical truth behind it, weaving in insights from thinkers (such as Albert Camus, Søren Kierkegaard, Carl Jung, Fyodor Dostoevsky, Viktor Frankl, Franz Kafka, Alan Watts, or Stoic philosophers). End with a lingering, comforting reflection.
- Write for the EAR: use lyrical, natural prose with rhythmic variation—mix quiet observations with deeper philosophical sentences, and use commas or ellipses for thoughtful breathing pauses.
- Keep the total narration close to {words} words (roughly 30–40 words per scene). Count the words before answering.
- DYNAMIC VISUAL MIX: Vary "visual_type" naturally across the scenes so the video feels like a curated cinema essay:
  * "illustration" (~50% of scenes): surrealist editorial metaphor matching the narrative moment.
  * "nature" (~30% of scenes): tranquil, atmospheric nature scene (misty mountains, quiet ocean horizon, rain on glass, autumn woods) during reflective transitions.
  * "quote" (~20% of scenes, 2 to 3 scenes total): a typographic quote card highlighting either a famous philosopher's aphorism or the single most resonant sentence from that scene.
- image_prompt: Required in English for every scene. For "illustration", describe a concrete surrealist visual metaphor (e.g., "a lone silhouette standing inside an enormous hourglass filled with tiny clocks instead of sand"). For "nature", describe a serene landscape in English (e.g., "a quiet wooden dock extending into a mist-covered mountain lake at dawn"). Never include text, letters, or watermarks in image_prompt.
- quote_text & quote_author: Required when visual_type is "quote" (keep quote_text concise, max 18 words, and quote_author as the thinker's name or "Quiet Thresholds"). Leave as "" for other visual types.
- music_mood: choose the background soundtrack vibe that best fits this episode ("melancholic_piano", "hopeful_ambient", "cinematic_wonder", or "calm_lofi").
- No real living celebrities, brands, logos, or copyrighted characters from films or games.

Return ONLY valid JSON with this exact shape:
{{
  "title": "max 65 chars, poetic and thought-provoking title in {lang} (no clickbait, no #Shorts)",
  "description": "2 to 3 reflective sentences summarizing the video's theme with 2 or 3 searchable philosophy/psychology keywords",
  "hashtags": ["3 to 5 relevant single-word tags without #"],
  "music_mood": "one of: melancholic_piano, hopeful_ambient, cinematic_wonder, calm_lofi",
  "visual_style": "one consistent art direction used for illustration scenes",
  "scenes": [
    {{
      "text": "2 to 3 unhurried spoken sentences for this scene",
      "visual_type": "one of: illustration, nature, quote",
      "emotion": "one of: contemplative, melancholic, curious, serene, hopeful, awe",
      "image_prompt": "English visual description for illustration or nature",
      "quote_text": "Short quote if visual_type is quote, otherwise empty string",
      "quote_author": "Author name if visual_type is quote, otherwise empty string"
    }}
  ]
}}
Use {min_scenes} to {max_scenes} scenes. No emojis in "text"."""

DEFAULT_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-2.5-flash"]

RETRYABLE = {429, 500, 502, 503, 504}
TRIES_PER_MODEL = 3
BASE_WAIT = 8
MAX_TOTAL_SECONDS = 600
VALID_EMOTIONS = {"contemplative", "melancholic", "curious", "serene", "hopeful", "awe"}
VALID_VISUAL_TYPES = {"illustration", "nature", "quote"}
VALID_MOODS = {"melancholic_piano", "hopeful_ambient", "cinematic_wonder", "calm_lofi"}


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
    assert data.get("title") and len(data.get("scenes", [])) >= 6, "script too short/incomplete"

    mood = str(data.get("music_mood", "melancholic_piano")).strip().lower()
    data["music_mood"] = mood if mood in VALID_MOODS else "melancholic_piano"

    for idx, s in enumerate(data["scenes"]):
        assert s.get("text", "").strip(), f"empty text in scene {idx}"
        vtype = str(s.get("visual_type", "illustration")).strip().lower()
        if vtype not in VALID_VISUAL_TYPES:
            vtype = "illustration"
        # Ensure scene 0 is always an engaging visual rather than a text-only quote card
        if idx == 0 and vtype == "quote":
            vtype = "illustration"
        s["visual_type"] = vtype

        if vtype == "quote":
            q_text = str(s.get("quote_text", "")).strip()
            if not q_text:
                # Fallback to the first sentence of narration if quote_text was omitted
                q_text = s["text"].split(".")[0].strip() + "."
            s["quote_text"] = q_text
            s["quote_author"] = str(s.get("quote_author", "")).strip()
            s["image_prompt"] = s.get("image_prompt", "").strip() or "minimalist twilight horizon"
        else:
            assert s.get("image_prompt", "").strip(), f"empty image_prompt in scene {idx}"
            s["quote_text"] = ""
            s["quote_author"] = ""

        emo = str(s.get("emotion", "contemplative")).strip().lower()
        s["emotion"] = emo if emo in VALID_EMOTIONS else "contemplative"

    if max_words:
        n = sum(len(s["text"].split()) for s in data["scenes"])
        assert n <= max_words, f"narration too long ({n} words > {max_words})"
    return data


def _word_count(data):
    return sum(len(s["text"].split()) for s in data["scenes"])


def generate(cfg, past_titles, topic=None, winners=None, fmt=None):
    key = os.environ["GEMINI_API_KEY"]
    target = int(cfg.get("target_seconds", 180))
    # Calibrated for calm, measured narration (~2.15 words/sec at -6% speaking rate)
    words = max(120, int(target * 2.15))
    min_scenes = max(8, target // 18)
    max_scenes = max(12, target // 13)

    winners_block = ""
    if winners:
        winners_block = (
            "Titles that resonated most with viewers (match this depth, never repeat them):\n"
            + "\n".join(f"- {t}" for t in winners)
            + "\n"
        )

    base_prompt = PROMPT.format(
        series=cfg.get("series", ""),
        niche=cfg["niche"],
        style=cfg.get("style_notes", ""),
        lang=cfg.get("language", "English"),
        words=words,
        secs=target,
        min_scenes=min_scenes,
        max_scenes=max_scenes,
        past="\n".join(f"- {t}" for t in past_titles) or "(none yet)",
        winners=winners_block,
        format_line=(f"Narrative format for this episode: {fmt}" if fmt else ""),
        topic_line=(
            f"Explore this specific theme/topic: {topic}"
            if topic
            else "Choose a fresh, deeply human existential or psychological theme (such as the passage of time, quiet loneliness, nostalgia, letting go of control, or finding meaning in an absurd world)."
        ),
    )

    hard_cap = int(words * 1.50)
    soft_cap = int(words * 1.25)
    feedback = ""

    def make_body():
        return {
            "contents": [{"parts": [{"text": base_prompt + feedback}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.9,
                "maxOutputTokens": 6144,
            },
        }

    deadline = time.time() + MAX_TOTAL_SECONDS
    errors = []
    for model in _model_chain(cfg):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(1, TRIES_PER_MODEL + 1):
            tag = f"{model} (try {attempt}/{TRIES_PER_MODEL})"
            try:
                if time.time() > deadline:
                    raise RuntimeError(
                        "Script generation gave up after "
                        + str(MAX_TOTAL_SECONDS)
                        + "s:\n  "
                        + "\n  ".join(errors)
                    )
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
                    print(
                        f"WARN: script is {n} words (target {words}); episode will run slightly longer.",
                        flush=True,
                    )
                mix = {}
                for sc in data["scenes"]:
                    mix[sc["visual_type"]] = mix.get(sc["visual_type"], 0) + 1
                print(
                    f"Script generated with {model} ({n} words, {len(data['scenes'])} scenes, mix={mix})",
                    flush=True,
                )
                return data

            except RuntimeError:
                raise
            except (requests.RequestException, ValueError, AssertionError, KeyError) as e:
                if isinstance(e, AssertionError) and "too long" in str(e):
                    feedback = (
                        f"\n\nYour previous draft exceeded the word budget. Keep the total narration close to "
                        f"{words} words across {min_scenes} to {max_scenes} scenes."
                    )
                errors.append(f"{tag}: {e!r}")
                print(f"WARN {tag} -> {e!r}", flush=True)
                if attempt < TRIES_PER_MODEL:
                    time.sleep(BASE_WAIT * attempt)

        print(f"Moving on from {model}", file=sys.stderr, flush=True)

    raise RuntimeError("Script generation failed on all models:\n  " + "\n  ".join(errors))
