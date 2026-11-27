import os, pathlib, random, subprocess
from PIL import Image

W, H, FPS = 1920, 1080, 30
MUSIC_DIR = pathlib.Path("assets/music")
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".ogg"}

MOOD_KEYWORDS = {
    "melancholic_piano": ("piano", "melanchol", "sad", "rain", "soft", "solo"),
    "hopeful_ambient": ("hope", "warm", "light", "uplift", "dawn", "ambient"),
    "cinematic_wonder": ("cinema", "wonder", "space", "cosmos", "deep", "epic", "string"),
    "calm_lofi": ("lofi", "chill", "study", "calm", "sleep", "slow"),
}


def _run(cmd, cwd=None):
    try:
        subprocess.run(cmd, check=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError("ffmpeg failed: " + (e.stderr or b"").decode(errors="ignore")[-600:])


def _ts(t):
    h, rem = divmod(max(0.0, float(t)), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _format_caption_word(token):
    return token.replace("{", "").replace("}", "").strip()


def make_ass(words, path, group=7, top=False, mute_windows=None):
    align, marginv = (8, 64) if top else (2, 64)
    lang = os.environ.get("VIDEO_LANGUAGE", "en").lower()
    font = "Noto Sans Devanagari" if lang in ("hi", "hindi") else "DejaVu Sans"
    mute_windows = mute_windows or []

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},40,&H00F2EFE9,&H000000FF,&H80141820,&H64000000,0,0,0,0,100,100,0.4,0,1,2,1,{align},140,140,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), group):
        chunk = words[i:i + group]
        text = " ".join(w for w in (_format_caption_word(item[0]) for item in chunk) if w)
        if not text:
            continue
        start = chunk[0][1]
        raw_end = words[i + group][1] if i + group < len(words) else chunk[-1][2] + 0.25
        end = max(raw_end, start + 0.35)
        mid = 0.5 * (start + end)

        # Skip bottom subtitles while a full-screen quote card is displayed
        if any(w_start <= mid <= w_end for w_start, w_end in mute_windows):
            continue

        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}")
    pathlib.Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def _motion(i, n, visual_type="illustration"):
    """Gentle Ken Burns motion tailored to scene type (minimal zoom on quote cards)."""
    if visual_type == "quote":
        return f"1.00+0.025*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    mode = i % 4
    if mode == 0:
        return f"1.02+0.07*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if mode == 1:
        return f"1.09-0.07*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if mode == 2:
        return f"1.05+0.04*on/{n}", f"(iw-iw/zoom)*on/{n}", "(ih-ih/zoom)/2"
    return f"1.05+0.04*on/{n}", f"(iw-iw/zoom)*(1-on/{n})", "(ih-ih/zoom)/2"


def scene_durations(scenes, words, total_dur):
    """Cut each visual when its corresponding narration begins."""
    if words and len(words) >= len(scenes):
        counts = [max(len(s["text"].split()), 1) for s in scenes]
        total, n, acc, cuts = sum(counts), len(words), 0, []
        for c in counts[:-1]:
            acc += c
            k = min(max(int(round(acc / total * n)), 1), n - 1)
            cuts.append(words[k][1])
        starts, ends = [0.0] + cuts, cuts + [total_dur]
        durs = [max(e - s, 1.5) for s, e in zip(starts, ends)]
        scale = total_dur / sum(durs)
        return [d * scale for d in durs]
    chars = [max(len(s["text"]), 1) for s in scenes]
    return [total_dur * c / sum(chars) for c in chars]


def _synthesize_ambient_fallback(workdir: pathlib.Path, duration: float) -> pathlib.Path:
    """Generate a warm, low-pass filtered ambient harmonic pad if assets/music/ has no tracks."""
    fallback = workdir / "ambient_pad.wav"
    # Warm D-minor9 / F-major7 harmonic drone with slow breathing modulation
    expr = (
        "0.28*sin(2*PI*146.83*t)*(0.7+0.3*sin(2*PI*0.07*t))+"
        "0.24*sin(2*PI*220.00*t)*(0.7+0.3*sin(2*PI*0.05*t+1.1))+"
        "0.20*sin(2*PI*261.63*t)*(0.7+0.3*sin(2*PI*0.06*t+2.3))+"
        "0.16*sin(2*PI*329.63*t)*(0.6+0.4*sin(2*PI*0.04*t+0.7))+"
        "0.12*sin(2*PI*73.42*t)"
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc='{expr}':s=44100:d={duration + 3:.2f}",
            "-af",
            "lowpass=f=650,aecho=0.8:0.88:60:0.35",
            str(fallback),
        ]
    )
    return fallback.resolve()


def _pick_music(mood: str | None = None):
    if not MUSIC_DIR.exists():
        return None
    files = [p for p in sorted(MUSIC_DIR.iterdir()) if p.suffix.lower() in MUSIC_EXT]
    if not files:
        return None
    if mood and mood in MOOD_KEYWORDS:
        keys = MOOD_KEYWORDS[mood]
        matched = [p for p in files if any(k in p.stem.lower() for k in keys)]
        if matched:
            return random.choice(matched).resolve()
    return random.choice(files).resolve()


def _rel_or_abs(p, base):
    p = pathlib.Path(p)
    try:
        return str(p.relative_to(base))
    except ValueError:
        return str(p.resolve())


def render(
    scenes,
    image_paths,
    audio_path,
    words,
    total_dur,
    workdir,
    out_name="final.mp4",
    char_pattern=None,
    char_size=180,
    char_bottom=60,
    cta_png=None,
    cta_mode="end",
    cta_seconds=4.0,
    cta_bottom=80,
    durs=None,
    subtitles=True,
    music_mood=None,
    music_volume=0.11,
):
    workdir = pathlib.Path(workdir).resolve()
    if durs is None:
        durs = scene_durations(scenes, words, total_dur)

    music = _pick_music(music_mood)
    if music is None:
        music = _synthesize_ambient_fallback(workdir, total_dur)
        print("Background music: generated warm ambient harmonic pad", flush=True)
    else:
        print(f"Background music ({music_mood or 'default'}): {music.name}", flush=True)

    segs = []
    quote_windows = []
    cursor = 0.0
    for i, (sc, img, d) in enumerate(zip(scenes, image_paths, durs)):
        vtype = sc.get("visual_type", "illustration")
        if vtype == "quote":
            quote_windows.append((cursor, cursor + d))
        cursor += d

        n = max(int(round(d * FPS)), 2)
        z, x, y = _motion(i, n, visual_type=vtype)
        fade_out_st = max(0.1, d - 0.45)
        vf = (
            f"scale={W * 3 // 2}:{H * 3 // 2}:force_original_aspect_ratio=increase,"
            f"crop={W * 3 // 2}:{H * 3 // 2},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},"
            f"fade=t=in:st=0:d=0.45,fade=t=out:st={fade_out_st:.2f}:d=0.45,"
            f"setsar=1,format=yuv420p"
        )
        seg = f"seg{i}.mp4"
        _run(
            [
                "ffmpeg",
                "-y",
                "-i",
                _rel_or_abs(img, workdir),
                "-vf",
                vf,
                "-frames:v",
                str(n),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "21",
                seg,
            ],
            cwd=workdir,
        )
        segs.append(seg)

    (workdir / "list.txt").write_text("".join(f"file '{s}'\n" for s in segs), encoding="utf-8")
    _run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "video.mp4"],
        cwd=workdir,
    )

    if subtitles:
        make_ass(words, workdir / "captions.ass", top=False, mute_windows=quote_windows)

    cmd = ["ffmpeg", "-y", "-i", "video.mp4", "-i", _rel_or_abs(audio_path, workdir)]
    nxt = 2
    music_idx = char_idx = cta_idx = None
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        music_idx = nxt
        nxt += 1
    if char_pattern:
        cmd += ["-framerate", str(FPS), "-i", _rel_or_abs(char_pattern, workdir)]
        char_idx = nxt
        nxt += 1
    if cta_png:
        cmd += [
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-t",
            f"{total_dur + 2:.2f}",
            "-i",
            _rel_or_abs(cta_png, workdir),
        ]
        cta_idx = nxt
        nxt += 1

    fc = []
    voice_chain = (
        "[1:a]highpass=f=85,"
        "equalizer=f=220:t=q:w=1.2:g=2.5,"
        "equalizer=f=3800:t=q:w=1.5:g=-2.0,"
        "acompressor=threshold=0.125:ratio=3:attack=10:release=120[v]"
    )
    fade_out_music = max(0.5, total_dur - 3.0)
    vol = float(music_volume)
    fc.append(
        f"{voice_chain};"
        f"[{music_idx}:a]volume={vol:.3f},afade=t=in:st=0:d=2.0,afade=t=out:st={fade_out_music:.2f}:d=3.0[m];"
        "[v][m]amix=inputs=2:duration=first:dropout_transition=3,"
        "loudnorm=I=-14:TP=-1.5:LRA=9[a]"
    )
    amap = "[a]"

    cur = "0:v"
    if char_pattern:
        ox, oy = W - char_size - 60, H - char_size - char_bottom
        fc.append(f"[{cur}][{char_idx}:v]overlay={ox}:{oy}:format=auto[vc]")
        cur = "vc"
    if cta_png:
        cw, ch = Image.open(cta_png).size
        start_t = max(0.0, total_dur - float(cta_seconds)) if cta_mode == "end" else 1.0
        fc.append(f"[{cta_idx}:v]format=rgba,fade=t=in:st={start_t:.2f}:d=0.4:alpha=1[cta]")
        fc.append(f"[{cur}][cta]overlay={(W - cw) // 2}:{H - ch - cta_bottom}:format=auto[vk]")
        cur = "vk"

    if subtitles:
        fc.append(f"[{cur}]ass=captions.ass[vout]")
        vmap = "[vout]"
    else:
        vmap = f"[{cur}]"

    cmd += ["-filter_complex", ";".join(fc)]
    cmd += ["-map", vmap, "-map", amap]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        out_name,
    ]
    _run(cmd, cwd=workdir)
    return workdir / out_name
