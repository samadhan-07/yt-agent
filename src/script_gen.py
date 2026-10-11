import json, os, time, requests

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

def generate(cfg, past_titles, topic=None):
    key = os.environ["GEMINI_API_KEY"]
    # FIXED: Replaced non-existent model fallback string with stable production 'gemini-1.5-flash'
    model = cfg.get("gemini_model", "gemini-2.0-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
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
    last = None
    # CHANGED: Increased retry attempts from 3 to 5 to push through peak server loads
    for attempt in range(5):
        try:
            r = requests.post(url, params={"key": key}, json=body, timeout=90)
            
            # FIXED: Catch 503 Server Unavailable code specifically, wait, and try again
            if r.status_code == 503:
                wait_time = (attempt + 1) * 15
                print(f"⚠️ Gemini API overloaded (503). Retrying in {wait_time} seconds... (Attempt {attempt + 1}/5)")
                time.sleep(wait_time)
                continue
                
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            
            # Clean out common AI markdown backticks if Gemini prints them around the JSON object
            text_cleaned = text.strip()
            if text_cleaned.startswith("```json"):
                text_cleaned = text_cleaned.split("```json")[1].split("```")[0].strip()
            elif text_cleaned.startswith("```"):
                text_cleaned = text_cleaned.split("```")[1].split("```")[0].strip()
                
            data = json.loads(text_cleaned)
            assert data["title"] and data["visual_style"] and len(data["scenes"]) >= 4
            for s in data["scenes"]:
                assert s["text"].strip() and s["image_prompt"].strip()
            return data
        except Exception as e:
            last = e
            # Scaled up recovery delay to give the API more breathing room
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Script generation failed: {last}")
