import os, pathlib, random, subprocess

W, H, FPS = 1080, 1920, 30
MUSIC_DIR = pathlib.Path("assets/music")
MUSIC_EXT = {".mp3", ".wav", ".m4a", ".ogg"}


def _run(cmd, cwd=None):
    try:
        subprocess.run(cmd, check=True, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        raise RuntimeError("ffmpeg failed: " + (e.stderr or b"").decode(errors="ignore")[-600:])


def _ts(t):
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _format_caption_word(token):
    cleaned = token.replace("{", "").replace("}", "")
    return cleaned.upper() if cleaned.isascii() else cleaned


def make_ass(words, path, group=3, top=False):
    align, marginv = (8, 280) if top else (2, 520)
    lang = os.environ.get("VIDEO_LANGUAGE", "hi").lower()
    font = "Noto Sans Devanagari" if lang in ("hi", "hindi") else "DejaVu Sans"
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},82,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,{align},60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), group):
        chunk = words[i:i + group]
        text = " ".join(_format_caption_word(w[0]) for w in chunk).strip()
        if not text:
            continue
        start = chunk[0][1]
        end = words[i + group][1] if i + group < len(words) else chunk[-1][2] + 0.2
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}")
    pathlib.Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def _motion(i, n):
    """Ken Burns variants so consecutive scenes feel different."""
    mode = i % 4
    if mode == 0:
        return f"1.06+0.18*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if mode == 1:
        return f"1.24-0.18*on/{n}", "(iw-iw/zoom)/2", "(ih-ih/zoom)/2"
    if mode == 2:
        return f"1.14+0.08*on/{n}", f"(iw-iw/zoom)*on/{n}", "(ih-ih/zoom)/2"
    return f"1.14+0.08*on/{n}", f"(iw-iw/zoom)*(1-on/{n})", "(ih-ih/zoom)/2"


def scene_durations(scenes, words, total_dur):
    """Cut each image when its sentence starts being spoken (uses word timings),
    falling back to text length if timings are unavailable."""
    if words and len(words) >= len(scenes):
        counts = [max(len(s["text"].split()), 1) for s in scenes]
        total, n, acc, cuts = sum(counts), len(words), 0, []
        for c in counts[:-1]:
            acc += c
            k = min(max(int(round(acc / total * n)), 1), n - 1)
            cuts.append(words[k][1])
        starts, ends = [0.0] + cuts, cuts + [total_dur]
        durs = [max(e - s, 0.8) for s, e in zip(starts, ends)]
        scale = total_dur / sum(durs)
        return [d * scale for d in durs]
    chars = [max(len(s["text"]), 1) for s in scenes]
    return [total_dur * c / sum(chars) for c in chars]


def _pick_music():
    if not MUSIC_DIR.exists():
        return None
    files = [p for p in sorted(MUSIC_DIR.iterdir()) if p.suffix.lower() in MUSIC_EXT]
    return random.choice(files).resolve() if files else None


def render(scenes, image_paths, audio_path, words, total_dur, workdir, out_name="final.mp4",
           char_pattern=None, char_size=600, char_bottom=340,
           cta_png=None, cta_mode="always", cta_seconds=4.0, cta_bottom=300,
           durs=None):
    workdir = pathlib.Path(workdir)
    music = _pick_music()
    if durs is None:
        durs = scene_durations(scenes, words, total_dur)
    segs = []
    for i, (img, d) in enumerate(zip(image_paths, durs)):
        n = max(int(d * FPS) + 1, 2)
        z, x, y = _motion(i, n)
        vf = (f"scale={W * 3 // 2}:{H * 3 // 2}:force_original_aspect_ratio=increase,"
              f"crop={W * 3 // 2}:{H * 3 // 2},"
              f"zoompan=z='{z}':x='{x}':y='{y}':d={n}:s={W}x{H}:fps={FPS},"
              f"setsar=1,format=yuv420p")
        seg = f"seg{i}.mp4"
        _run(["ffmpeg", "-y", "-i", pathlib.Path(img).name, "-vf", vf,
              "-frames:v", str(n), "-an", "-c:v", "libx264",
              "-preset", "veryfast", "-crf", "23", seg], cwd=workdir)
        segs.append(seg)
    (workdir / "list.txt").write_text("".join(f"file '{s}'\n" for s in segs))
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
          "-c", "copy", "video.mp4"], cwd=workdir)
    make_ass(words, workdir / "captions.ass", top=bool(char_pattern))

    cmd = ["ffmpeg", "-y", "-i", "video.mp4", "-i", pathlib.Path(audio_path).name]
    nxt = 2
    music_idx = char_idx = cta_idx = None
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        print(f"Background music: {music.name}", flush=True)
        music_idx = nxt; nxt += 1
    if char_pattern:
        cmd += ["-framerate", str(FPS), "-i", str(pathlib.Path(char_pattern).relative_to(workdir))]
        char_idx = nxt; nxt += 1
    if cta_png:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total_dur + 2:.2f}",
                "-i", str(pathlib.Path(cta_png).relative_to(workdir))]
        cta_idx = nxt; nxt += 1

    fc = []
    if music:
        fc.append(f"[1:a]volume=1.0[v];[{music_idx}:a]volume=0.10[m];"
                  "[v][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]")
        amap = "[a]"
    else:
        amap = "1:a"

    cur = "0:v"
    if char_pattern:
        ox, oy = (W - char_size) // 2, H - char_size - char_bottom
        fc.append(f"[{cur}][{char_idx}:v]overlay={ox}:{oy}:format=auto[vc]")
        cur = "vc"
    if cta_png:
        from PIL import Image
        cw, ch = Image.open(cta_png).size
        start_t = max(0.0, total_dur - float(cta_seconds)) if cta_mode == "end" else 1.0
        fc.append(f"[{cta_idx}:v]format=rgba,fade=t=in:st={start_t:.2f}:d=0.4:alpha=1[cta]")
        fc.append(f"[{cur}][cta]overlay={(W - cw) // 2}:{H - ch - cta_bottom}:format=auto[vk]")
        cur = "vk"
    if char_pattern or cta_png:
        fc.append(f"[{cur}]ass=captions.ass[vout]")
        vmap = "[vout]"
    elif music:
        fc.append("[0:v]ass=captions.ass[vout]")
        vmap = "[vout]"
    else:
        cmd += ["-vf", "ass=captions.ass"]
        vmap = "0:v"
    if fc:
        cmd += ["-filter_complex", ";".join(fc)]
    cmd += ["-map", vmap, "-map", amap]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out_name]
    _run(cmd, cwd=workdir)
    return workdir / out_name
