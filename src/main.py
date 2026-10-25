import datetime, os, pathlib, random, shutil, sys, traceback, yaml
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

STYLIZED_LOOK = ("stylized 3D animated illustration, soft cinematic lighting, vibrant colors, "
                 "clean composition, vertical 9:16, no text, no captions, no logos")
REALISTIC_LOOK = ("photorealistic cinematic photography, natural lighting, rich detail, "
                  "vertical 9:16, no text, no captions, no logos")


def summary(msg):
    """Print, and also show on the GitHub run summary page so skips/uploads are visible."""
    print(msg, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def pick_topic(st):
    """Manual TOPIC (workflow input) wins. Otherwise pick an unused line from topics.txt.
    Returns None if the list is empty/used up, so the AI chooses a fresh topic itself."""
    manual = os.environ.get("TOPIC", "").strip()
    if manual:
        return manual
    topic_file = pathlib.Path("topics.txt")
    if not topic_file.exists():
        return None
    lines = [l.strip() for l in topic_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    used = set(st.get("used_topics", []))
    fresh = [l for l in lines if l not in used]
    if not fresh:
        return None
    topic = random.choice(fresh)
    print(f"Selected unused topic from list: {topic} ({len(fresh)} left)")
    return topic


def uploaded_today_count(st):
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    # only count uploads made by THIS pipeline (other tools/old entries must not block it)
    return sum(1 for v in st.get("videos", [])
               if v.get("date") == today and v.get("by") == "yt-agent")


def make_one(cfg, st, dry_run):
    selected_topic = pick_topic(st)
    data = script_gen.generate(cfg, state.past_titles(st), selected_topic, state.top_titles())

    base_style = cfg.get("cartoon_style", "").strip()
    look = cfg.get("visual_style") or (STYLIZED_LOOK if base_style else REALISTIC_LOOK)
    data["visual_style"] = (base_style + ", " if base_style else "") + look

    scenes = data["scenes"]
    print(f"Title: {data['title']}  ({len(scenes)} scenes)")

    work = pathlib.Path("work")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    narration = " ".join(s["text"].strip() for s in scenes)
    audio = work / "voice.mp3"
    words, dur = tts.synthesize(narration, cfg["voice"], str(audio))
    print(f"Narration: {dur:.1f}s")
    if dur > 59:
        print(f"WARNING: narration is {dur:.1f}s (over 59s). Shorter loops perform better.")

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
            print(f"WARN: image {i + 1} failed ({e!r}); reusing the previous image.",
                  file=sys.stderr, flush=True)
            img = images[-1]
        images.append(img)

    if not words:   # some voices return no word timings: spread the words evenly so captions still show
        toks = narration.split()
        step = dur / max(len(toks), 1)
        words = [(w, i * step, (i + 1) * step) for i, w in enumerate(toks)]
    final = render.render(scenes, images, audio, words, dur, work)

    tags = data.get("hashtags", []) + cfg.get("extra_tags", [])
    hashtags = " ".join("#" + t.replace(" ", "") for t in tags[:5]) + " #Shorts"
    parts = [data["description"]]
    if cfg.get("disclosure_line"):
        parts.append(cfg["disclosure_line"])
    parts.append(hashtags)
    desc = "\n\n".join(parts)
    title = data["title"] if "#shorts" in data["title"].lower() else data["title"] + " #Shorts"

    if dry_run:
        out = pathlib.Path("out"); out.mkdir(exist_ok=True)
        shutil.copy(final, out / "preview.mp4")
        summary(f"DRY RUN: saved out/preview.mp4 for '{data['title']}', skipping upload.")
        return

    vid = upload.upload(final, title, desc, tags, cfg.get("privacy", "public"),
                        cfg.get("category_id", "27"))
    summary(f"Uploaded '{data['title']}': https://youtu.be/{vid} (privacy: {cfg.get('privacy', 'public')})")
    st["videos"].append({
        "title": data["title"],
        "id": vid,
        "by": "yt-agent",
        "date": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
    })
    if selected_topic:
        st.setdefault("used_topics", []).append(selected_topic)
    state.save(st)


def main():
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    code = os.environ.get("VIDEO_LANGUAGE") or cfg.get("language", "en")
    name, voice = LANGS.get(code, (code, cfg["voice"]))
    cfg["language"], cfg["voice"] = name, voice
    style = os.environ.get("CARTOON_STYLE", "")
    cfg["cartoon_style"] = "" if style.startswith("None") else style
    dry = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    force = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")
    st = state.load()

    per_run = int(cfg.get("videos_per_run", 1))

    # Makes the retry cron safe: if this pipeline already uploaded today, exit cleanly.
    if not dry and not force and uploaded_today_count(st) >= per_run:
        summary("Today's video was already uploaded by yt-agent. Nothing to do.")
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
