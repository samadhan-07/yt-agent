import json, os, random, sys, time, requests

PROMPT = """You write scripts for a philosophical storytelling and existential psychology YouTube channel inspired by Pursuit of Wonder.
The narrator speaks in a calm, literary, deeply empathetic voice—never lecturing or using clickbait hype.
Series name: {series}
Channel niche: {niche}
Style: {style}
Language of ALL narration, the title, and the description: {lang}.
Narration length: about {words} words in total (about {secs} seconds when spoken at a calm, measured pace).
{topic_line}
{format_line}

Earlier videos - do NOT repeat or closely resemble these:
{past}
{winners}
Rules:
- Structure the script in TWO distinct acts:
  1. Act 1 (First ~45% of scenes): Tell a quiet, vivid story about an ordinary fictional character experiencing a relatable inner conflict (waiting for life to start, feeling unseen in a crowd, clinging to control, or mourning an imagined future). Show their inner world through concrete details rather than lecturing.
  2. Act 2 (Remaining ~55% of scenes): Gently zoom out from the character's story to unpack the deeper psychological or philosophical insight behind it, weaving in relevant thinkers (such as Albert Camus, Søren Kierkegaard, Carl Jung, Fyodor Dostoevsky, Viktor Frankl, Franz Kafka, Alan Watts, or Stoic philosophers) where natural. End with a lingering, comforting reflection.
- Write for the EAR: use lyrical, natural prose with rhythmic variation—mix quiet observations with deeper philosophical sentences, and use commas or ellipses for thoughtful breathing pauses.
- Keep the total narration close to {words} words. Count the words carefully before answering.
- Avoid self-help clichés, numbered lists, loud calls to action, or preachy moralizing.
- No real living celebrities, brands, logos, or copyrighted characters from films or games.
- emotion: choose the subtle narrative mood of each scene (contemplative, melancholic, curious, serene, hopeful, or awe).
- image_prompt: ONE surrealist editorial illustration scene in English matching the metaphor of that moment. Describe concrete visual symbols (e.g., "a lone silhouette standing inside an enormous hourglass filled with tiny clocks instead of sand", "a small wooden boat anchored in a calm sea of clouds under twilight"). Never use abstract nouns like "anxiety" or "philosophy" in image_prompt, and never include text, letters, or watermarks. Vary framing and composition across scenes.

Return ONLY valid JSON with this exact shape:
{{
  "title": "max 65 chars, poetic and thought-provoking title in {lang} (no clickbait, no #Shorts)",
  "description": "2 to 3 reflective sentences summarizing the video's theme with 2 or 3 searchable philosophy/psychology keywords",
  "hashtags": ["3 to 5 relevant single-word tags without #"],
  "visual_style": "one consistent art direction used for EVERY image",
  "scenes": [
    {{
      "text": "one or two spoken sentences for this scene",
      "emotion": "one of: contemplative, melancholic, curious, serene, hopeful, awe",
      "image_prompt": "English description of ONE surrealist visual metaphor scene"
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
    assert data.get("title") and data.get("visual_style") and len(data.get("scenes", [])) >= 6, (
        "script too short/incomplete"
    )
    for s in data["scenes"]:
        assert s.get("text", "").strip() and s.get("image_prompt", "").strip(), "empty scene field"
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
    words = max(110, int(target * 2.15))
    min_scenes = max(8, target // 16)
    max_scenes = max(12, target // 11)

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

    hard_cap = int(words * 1.55)
    soft_cap = int(words * 1.25)
    feedback = ""

    def make_body():
        return {
            "contents": [{"parts": [{"text": base_prompt + feedback}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
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
                    print(f"WARN: script is {n} words (target {words}); episode will run slightly longer.", flush=True)
                print(f"Script generated with {model} ({n} words, {len(data['scenes'])} scenes)", flush=True)
                return data

            except RuntimeError:
                raise
            except (requests.RequestException, ValueError, AssertionError, KeyError) as e:
                if isinstance(e, AssertionError) and "too long" in str(e):
                    feedback = (
                        f"\n\nYour previous draft exceeded the word budget. Keep the total narration close to "
                        f"{words} words across {min_scenes} to {max_scenes} concise, poetic scenes."
                    )
                errors.append(f"{tag}: {e!r}")
                print(f"WARN {tag} -> {e!r}", flush=True)
                if attempt < TRIES_PER_MODEL:
                    time.sleep(BASE_WAIT * attempt)

        print(f"Moving on from {model}", file=sys.stderr, flush=True)

    raise RuntimeError("Script generation failed on all models:\n  " + "\n  ".join(errors))
