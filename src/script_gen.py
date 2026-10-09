import json, os, time, requests

PROMPT = """You write scripts for faceless, fully AI-generated YouTube Shorts.
Channel niche: {niche}
Style: {style}
Language: {lang}
Narration length: about {words} words total (must be under 55 seconds when spoken).

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

def generate(cfg, past_titles):
    key = os.environ["GEMINI_API_KEY"]
    model = cfg.get("gemini_model", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = PROMPT.format(
        niche=cfg["niche"], style=cfg.get("style_notes", ""), lang=cfg.get("language", "en"),
        words=int(cfg.get("target_seconds", 40) * 2.5),
        past="\n".join(f"- {t}" for t in past_titles) or "(none yet)",
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 1.0},
    }
    last = None
    for attempt in range(3):
        try:
            r = requests.post(url, params={"key": key}, json=body, timeout=90)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
            assert data["title"] and data["visual_style"] and len(data["scenes"]) >= 4
            for s in data["scenes"]:
                assert s["text"].strip() and s["image_prompt"].strip()
            return data
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Script generation failed: {last}")
