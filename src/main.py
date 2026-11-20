import datetime, os, pathlib, random, shutil, sys, traceback, yaml
from . import script_gen, tts, imagegen, render, upload, state, character, cta

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


def pick_format(cfg, st):
    """Rotate the video format on every upload so consecutive videos feel different."""
    fmts = cfg.get("formats") or []
    if not fmts:
        return None
    return fmts[len(st.get("videos", [])) % len(fmts)]


IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def next_free_slot(cfg, st, min_lead_min=60, horizon_hours=36):
    """Find the next public-release slot (Indian peak times) that nobody has taken yet.
    Returns ("off", None) if scheduling is disabled, ("full", None) if every slot in the next
    horizon_hours is taken, otherwise ("slot", "2026-11-16T02:30:00Z")."""
    times = cfg.get("publish_times_ist") or []
    if not times or not cfg.get("schedule_publish", True):
        return "off", None
    now = datetime.datetime.now(datetime.timezone.utc)
    earliest = now + datetime.timedelta(minutes=min_lead_min)
    latest = now + datetime.timedelta(hours=horizon_hours)
    taken = {v.get("publish_at") for v in st.get("videos", []) if v.get("publish_at")}
    free = []
    for day in range(3):
        d = (now.astimezone(IST) + datetime.timedelta(days=day)).date()
        for hhmm in times:
            hh, mm = (int(x) for x in str(hhmm).split(":"))
            slot = datetime.datetime(d.year, d.month, d.day, hh, mm, tzinfo=IST).astimezone(datetime.timezone.utc)
            iso = slot.strftime("%Y-%m-%dT%H:%M:%SZ")
            if earliest <= slot <= latest and iso not in taken:
                free.append(iso)
    return ("slot", min(free)) if free else ("full", None)


def ist_label(iso):
    dt = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %H:%M IST")


def uploaded_today_count(st):
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    # only count uploads made by THIS pipeline (other tools/old entries must not block it)
    return sum(1 for v in st.get("videos", [])
               if v.get("date") == today and v.get("by") == "yt-agent")


def make_one(cfg, st, dry_run):
    selected_topic = pick_topic(st)
    fmt = pick_format(cfg, st)
    print(f"Format: {fmt}")
    data = script_gen.generate(cfg, state.past_titles(st), selected_topic, state.top_titles(), fmt)

    base_style = cfg.get("cartoon_style", "").strip()
    look = cfg.get("visual_style") or (STYLIZED_LOOK if base_style else REALISTIC_LOOK)
    data["visual_style"] = (base_style + ", " if base_style else "") + look
    char_cfg = cfg.get("character") or {}
    use_char = bool(char_cfg.get("enabled"))
    if use_char:   # the mascot is overlaid later, so the AI images must be empty backgrounds
        data["visual_style"] += (", background scene only, no people, no characters, "
                                 "keep the lower third of the frame simple and uncluttered")

    scenes = data["scenes"]
    print(f"Title: {data['title']}  ({len(scenes)} scenes)")

    work = pathlib.Path("work")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    narration = " ".join(s["text"].strip() for s in scenes)
    audio = work / "voice.mp3"
    rate, pitch = ("+0%", "+0Hz")
    voice = cfg["voice"]
    if use_char:
        voice = cfg.get("cartoon_voice") or voice
        rate, pitch = cfg.get("voice_rate", "+8%"), cfg.get("voice_pitch", "+25Hz")
    try:
        words, dur = tts.synthesize(narration, voice, str(audio), rate, pitch)
    except Exception as e:
        print(f"WARN: voice '{voice}' failed ({e!r}); using the default voice.", file=sys.stderr, flush=True)
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
    durs = render.scene_durations(scenes, words, dur)
    char_pattern = None
    if use_char:
        n_frames = int(dur * render.FPS) + 2
        levels = character.mouth_levels(audio, render.FPS, n_frames)
        size = int(char_cfg.get("size", 600))
        char_pattern = character.render_frames(
            levels, work / "char", render.FPS, size=size,
            scenes=scenes, scene_durs=durs, image_paths=images
        )
        print(f"Mascot frames: {n_frames}", flush=True)
    cta_cfg = cfg.get("cta") or {}
    cta_png = None
    if cta_cfg.get("enabled"):
        cta_png = pathlib.Path(cta.make_cta(work / "cta.png"))
    final = render.render(scenes, images, audio, words, dur, work, char_pattern=pathlib.Path(char_pattern) if char_pattern else None,
                          char_size=int(char_cfg.get("size", 600)), char_bottom=int(char_cfg.get("bottom_margin", 340)),
                          cta_png=cta_png, cta_mode=cta_cfg.get("mode", "always"),
                          cta_seconds=float(cta_cfg.get("seconds", 4)), cta_bottom=int(cta_cfg.get("bottom_margin", 300)),
                          durs=durs)

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

    mode, slot = next_free_slot(cfg, st)
    if mode == "full" and not force:
        summary("All publish slots in the next 36 hours are taken. Video was not uploaded.")
        return
    publish_at = slot if mode == "slot" else None
    vid = upload.upload(final, title, desc, tags, cfg.get("privacy", "public"),
                        cfg.get("category_id", "27"),
                        made_for_kids=bool(cfg.get("made_for_kids", False)),
                        publish_at=publish_at)
    when = f"scheduled public at {ist_label(publish_at)}" if publish_at else f"privacy: {cfg.get('privacy', 'public')}"
    summary(f"Uploaded '{data['title']}': https://youtu.be/{vid} ({when})")
    st["videos"].append({
        "title": data["title"],
        "id": vid,
        "by": "yt-agent",
        "publish_at": publish_at,
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
    cfg["cartoon_voice"] = (cfg.get("cartoon_voices") or {}).get(code)
    char_env = os.environ.get("CHARACTER", "").lower()
    if char_env in ("true", "1", "yes"):
        cfg.setdefault("character", {})["enabled"] = True
    elif char_env in ("false", "0", "no"):
        cfg.setdefault("character", {})["enabled"] = False
    style = os.environ.get("CARTOON_STYLE", "")
    cfg["cartoon_style"] = "" if style.startswith("None") else style
    dry = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")
    force = os.environ.get("FORCE_RUN", "").lower() in ("1", "true", "yes")
    st = state.load()

    per_run = int(cfg.get("videos_per_run", 1))

    # Slot guard: every run fills the next free publish slot. If none is free, stop before
    # spending any API calls.
    mode, slot = next_free_slot(cfg, st)
    if mode == "full" and not dry and not force:
        summary("All publish slots in the next 36 hours are taken. Nothing to do.")
        sys.exit(0)
    if mode == "slot":
        print(f"Next free publish slot: {ist_label(slot)}", flush=True)

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
