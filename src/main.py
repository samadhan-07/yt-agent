import datetime, os, pathlib, random, shutil, sys, time, traceback, yaml
from . import script_gen, tts, imagegen, render, upload, state

# Flush every line so stdout/stderr appear in the correct order in GitHub Actions logs
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

LANGS = {
    "hi": ("Hindi", "hi-IN-MadhurNeural"),
    "en": ("English", "en-US-AndrewNeural"),
    "es": ("Spanish", "es-ES-AlvaroNeural"),
}


def get_random_topic_from_list():
    """Reads all topics from topics.txt and returns one completely at random without modifying the file."""
    topic_file = pathlib.Path("topics.txt")
    if not topic_file.exists():
        return None

    lines = topic_file.read_text(encoding="utf-8").splitlines()
    lines = [line.strip() for line in lines if line.strip()]

    if not lines:
        return None

    next_topic = random.choice(lines)
    print(f"🎲 Randomly Selected Topic from list: {next_topic}")
    return next_topic


def uploaded_today_count(st):
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    return sum(1 for v in st.get("videos", []) if v.get("date") == today)


def make_one(cfg, st, dry_run):
    selected_topic = get_random_topic_from_list() or os.environ.get("TOPIC", "").strip() or None

    data = script_gen.generate(cfg, state.past_titles(st), selected_topic)

    # Universal premium 3D cartoon style application even if cartoon_style config is empty
    base_style = cfg.get("cartoon_style", "").strip()
    style_prefix = base_style + ", " if base_style else ""
    data["visual_style"] = (style_prefix + "premium Pixar-inspired cinematic 3D animation, "
                            "highly detailed polished textures, expressive characters, rich volumetric lighting, "
                            "beautiful depth of field, vibrant colors, vertical 9:16, no text, no captions")

    scenes = data["scenes"]
    print(f"Title: {data['title']}")

    work = pathlib.Path("work")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    narration = " ".join(s["text"].strip() for s in scenes)
    audio = work / "voice.mp3"
    words, dur = tts.synthesize(narration, cfg["voice"], str(audio))
    print(f"Narration: {dur:.1f}s")

    if dur > 59:
        print(f"⚠️ WARNING: Narration is {dur:.1f}s (Over 59s). Continuing compilation anyway.")

    seed = int.from_bytes(os.urandom(3), "big")
    images = []
    for i, s in enumerate(scenes):
        print(f"Generating image {i + 1}/{len(scenes)}")
        try:
            img = imagegen.generate(
                s["image_prompt"], data["visual_style"], str(work / f"img{i}.jpg"),
                seed=seed + i, model=cfg.get("image_model", "flux"),
                delay=cfg.get("image_delay_seconds", 16))
        except Exception as e:
            if not images:
                raise  # nothing to fall back on
            print(f"⚠️ Image {i + 1} failed ({e!r}); reusing the previous image.",
                  file=sys.stderr, flush=True)
            img = images[-1]
        images.append(img)

    final = render.render(scenes, images, audio, [], dur, work)

    tags = data.get("hashtags", []) + cfg.get("extra_tags", [])
    desc = data["description"] + "\n\n" + " ".join("#" + t.replace(" ", "") for t in tags[:5]) + " #Shorts"
    title = data["title"] if "#shorts" in data["title"].lower() else data["title"] + " #Shorts"

    if dry_run:
        out = pathlib.Path("out"); out.mkdir(exist_ok=True)
        shutil.copy(final, out / "preview.mp4")
        print("DRY RUN: saved out/preview.mp4, skipping upload.")
        return

    vid = upload.upload(final, title, desc, tags, cfg.get("privacy", "public"), cfg.get("category_id", "27"))
    print(f"Uploaded: https://youtube.com{vid}")
    st["videos"].append({
        "title": data["title"],
        "id": vid,
        "date": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
    })
    state.save(st)


def main():
    cfg = yaml.safe_load(open("config.yaml"))
    code = os.environ.get("VIDEO_LANGUAGE") or cfg.get("language", "en")
    name, voice = LANGS.get(code, ("English", cfg["voice"]))
    cfg["language"], cfg["voice"] = name, voice
    style = os.environ.get("CARTOON_STYLE", "")
    cfg["cartoon_style"] = "" if style.startswith("None") else style
    dry = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    force = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")
    st = state.load()

    per_run = int(cfg.get("videos_per_run", 1))

    # Makes a second (retry) cron trigger safe: if today's video(s) already went out, exit cleanly.
    if not dry and not force and uploaded_today_count(st) >= per_run:
        print("✅ Today's video is already uploaded. Nothing to do.")
        sys.exit(0)

    failures = 0
    for _ in range(per_run):
        try:
            make_one(cfg, st, dry)
        except Exception as e:
            failures += 1
            print(f"ERROR: {e!r}", file=sys.stderr)
            traceback.print_exc()
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
