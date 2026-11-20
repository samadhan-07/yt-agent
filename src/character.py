"""Original cartoon mascot ("Bittu") drawn with Pillow. No downloads, no API keys.

How it works
  1. mouth_levels(): decodes the narration audio and turns its loudness into a mouth
     opening (0 = closed ... 3 = wide) for every video frame (simple lip sync).
  2. render_frames(): draws the mascot for every frame synced to the scene's emotion,
     gestures, and background image ambient color/brightness. render.py overlays them
     on the video with FFmpeg.
"""
import math, os, random, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

INK = (29, 43, 83, 255)
BODY = (255, 183, 3, 255)
BODY_SHADE = (240, 150, 0, 255)
CHEEK = (255, 120, 120, 255)
WHITE = (255, 255, 255, 255)
MOUTH = (90, 26, 26, 255)
TONGUE = (255, 107, 129, 255)
SS = 2  # supersampling: draw at 2x, shrink for smooth edges


def mouth_levels(audio_path, fps, n_frames):
    """Return a list of n_frames ints in 0..3 based on how loud the voice is."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio_path), "-ac", "1", "-ar", "16000",
         "-f", "s16le", "-"], check=True, stdout=subprocess.PIPE).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if x.size == 0:
        return [0] * n_frames
    hop = int(16000 / fps)
    rms = np.array([np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2) + 1e-9)
                    if i * hop < x.size else 0.0 for i in range(n_frames)])
    ref = np.percentile(rms, 90) or 1.0
    env = np.clip(rms / ref, 0, 1.3)
    # light smoothing so the mouth does not flicker
    env = np.convolve(env, np.ones(3) / 3, mode="same")
    levels = []
    for v in env:
        levels.append(0 if v < 0.12 else 1 if v < 0.40 else 2 if v < 0.75 else 3)
    return levels


def _scene_tint(image_path):
    """Extract quantized RGB tint and brightness (0.75..1.07) from a background image."""
    try:
        im = Image.open(image_path).convert("RGB").resize((32, 32))
        arr = np.asarray(im, dtype=np.float32)
        mean_rgb = arr.mean(axis=(0, 1))
        luma = (0.299 * mean_rgb[0] + 0.587 * mean_rgb[1] + 0.114 * mean_rgb[2]) / 255.0
        tint = tuple(int(round(c / 32) * 32) for c in mean_rgb)
        brightness = round(0.75 + 0.32 * float(luma), 2)
        return tint, brightness
    except Exception:
        return (255, 255, 255), 1.0


def _tint_color(rgba, tint_rgb, strength=0.15):
    r = int(rgba[0] * (1 - strength) + tint_rgb[0] * strength)
    g = int(rgba[1] * (1 - strength) + tint_rgb[1] * strength)
    b = int(rgba[2] * (1 - strength) + tint_rgb[2] * strength)
    return (r, g, b, rgba[3])


def _draw(level, blink, bounce, arm, emotion, lean_x, tint_rgb, brightness, size):
    """Draw one contextual pose on a 1200x1200 canvas, return a size x size RGBA image."""
    c = 600 * SS
    img = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = SS

    body_col = _tint_color(BODY, tint_rgb, 0.15)
    shade_col = _tint_color(BODY_SHADE, tint_rgb, 0.15)
    antenna_glow = {
        "excited": (255, 230, 80, 255),
        "shocked": (255, 90, 90, 255),
        "curious": (100, 220, 255, 255),
        "thinking": (180, 140, 255, 255),
        "scared": (130, 200, 255, 255),
    }.get(emotion, CHEEK)

    def E(cx, cy, rx, ry, fill, outline=None, w=0):
        d.ellipse([(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s],
                  fill=fill, outline=outline, width=int(w * s))

    dy = bounce  # vertical bounce in canvas px (negative = up)
    ox = lean_x

    # ground shadow
    E(300 + ox * 0.5, 560, 150 - dy * 0.3, 18, (0, 0, 0, 65))
    # feet
    E(235 + ox * 0.4, 540 + dy * 0.4, 52, 28, shade_col, INK, 6)
    E(365 + ox * 0.4, 540 + dy * 0.4, 52, 28, shade_col, INK, 6)

    # contextual arms
    if emotion == "excited":
        # both arms raised in celebration
        E(120 + ox, 270 + dy - arm, 36, 62, shade_col, INK, 6)
        E(480 + ox, 270 + dy + arm, 36, 62, shade_col, INK, 6)
    elif emotion == "curious":
        # right arm pointing up toward the background visual
        E(115 + ox, 365 + dy + arm * 0.5, 38, 60, shade_col, INK, 6)
        E(475 + ox, 235 + dy - arm * 0.8, 34, 66, shade_col, INK, 6)
    elif emotion in ("shocked", "scared"):
        # hands raised near cheeks
        E(145 + ox, 320 + dy + arm * 0.5, 34, 52, shade_col, INK, 6)
        E(455 + ox, 320 + dy - arm * 0.5, 34, 52, shade_col, INK, 6)
    elif emotion == "thinking":
        # hand near chin
        E(118 + ox, 370 + dy, 38, 60, shade_col, INK, 6)
        E(410 + ox, 405 + dy + arm * 0.4, 34, 50, shade_col, INK, 6)
    else:
        # default friendly wave
        E(112 + ox, 360 + dy + arm * 1.0, 38, 62, shade_col, INK, 6)
        E(488 + ox, 360 + dy - arm * 1.6, 38, 62, shade_col, INK, 6)

    # antenna
    d.line([(300 + ox) * s, (150 + dy) * s, (300 + ox * 1.3) * s, (92 + dy * 1.4) * s],
           fill=INK, width=8 * s)
    E(300 + ox * 1.3, 80 + dy * 1.4, 22, 22, antenna_glow, INK, 6)

    # body
    E(300 + ox, 340 + dy, 168, 190, body_col, INK, 8)
    E(300 + ox, 395 + dy, 105, 100, _tint_color((255, 214, 120, 255), tint_rgb, 0.12))  # belly patch

    # cheeks
    E(185 + ox, 355 + dy, 28, 18, CHEEK)
    E(415 + ox, 355 + dy, 28, 18, CHEEK)

    # eyes
    eye_scale = 1.15 if emotion in ("shocked", "scared") else 0.92 if emotion == "thinking" else 1.0
    pupil_dx = 8 if emotion == "curious" else -6 if emotion == "thinking" else 4
    pupil_dy = -8 if emotion in ("curious", "thinking") else 4

    for ex in (235 + ox, 365 + ox):
        ey = 270 + dy
        if blink and emotion not in ("shocked", "scared"):
            d.line([(ex - 38) * s, ey * s, (ex + 38) * s, ey * s], fill=INK, width=8 * s)
        else:
            E(ex, ey, 40 * eye_scale, 48 * eye_scale, WHITE, INK, 6)
            p_r = 15 if emotion in ("shocked", "scared") else 20
            E(ex + pupil_dx, ey + pupil_dy, p_r, p_r * 1.15, INK)
            E(ex + pupil_dx + 6, ey + pupil_dy - 6, 7, 8, WHITE)

    # eyebrows lift when the voice is loud or surprised
    lift = 10 if (level >= 3 or emotion in ("shocked", "excited")) else 0
    if emotion == "curious":
        d.line([(195 + ox) * s, (205 + dy) * s, (270 + ox) * s, (200 + dy) * s], fill=INK, width=8 * s)
        d.line([(330 + ox) * s, (182 + dy) * s, (405 + ox) * s, (192 + dy) * s], fill=INK, width=8 * s)
    elif emotion == "scared":
        d.line([(195 + ox) * s, (212 + dy) * s, (270 + ox) * s, (194 + dy) * s], fill=INK, width=8 * s)
        d.line([(330 + ox) * s, (194 + dy) * s, (405 + ox) * s, (212 + dy) * s], fill=INK, width=8 * s)
    else:
        d.line([(195 + ox) * s, (205 - lift + dy) * s, (270 + ox) * s, (200 - lift + dy) * s], fill=INK, width=8 * s)
        d.line([(330 + ox) * s, (200 - lift + dy) * s, (405 + ox) * s, (205 - lift + dy) * s], fill=INK, width=8 * s)

    # mouth
    mx, my = 300 + ox, 375 + dy
    if level == 0:
        if emotion == "shocked":
            E(mx, my + 5, 18, 22, MOUTH, INK, 6)
        elif emotion == "thinking":
            d.line([(mx - 28) * s, (my + 5) * s, (mx + 28) * s, (my - 2) * s], fill=INK, width=8 * s)
        else:
            d.arc([(mx - 40) * s, (my - 25) * s, (mx + 40) * s, (my + 15) * s], 20, 160, fill=INK, width=8 * s)
    else:
        rx, ry = [(0, 0), (26, 12), (38, 26), (46, 44)][level]
        E(mx, my + ry * 0.4, rx, ry, MOUTH, INK, 6)
        if level >= 2:
            E(mx, my + ry * 0.9, rx * 0.6, ry * 0.4, TONGUE)

    out = img.resize((size, size), Image.LANCZOS)
    if brightness != 1.0:
        out = ImageEnhance.Brightness(out).enhance(brightness)
    return out


def render_frames(levels, outdir, fps, size=600, seed=7,
                  scenes=None, scene_durs=None, image_paths=None):
    """Write char_00001.png ... into outdir. Returns the ffmpeg input pattern."""
    os.makedirs(outdir, exist_ok=True)
    rng = random.Random(seed)
    n = len(levels)

    # Map each video frame to its active scene's emotion, lean, and background tint
    frame_context = []
    if scenes and scene_durs and image_paths:
        for idx, (sc, dur, img_p) in enumerate(zip(scenes, scene_durs, image_paths)):
            tint, bright = _scene_tint(img_p)
            lean = -18 if idx % 3 == 1 else 18 if idx % 3 == 2 else 0
            count = max(1, int(round(dur * fps)))
            frame_context.extend([(sc.get("emotion", "happy"), lean, tint, bright)] * count)
    while len(frame_context) < n:
        frame_context.append(frame_context[-1] if frame_context else ("happy", 0, (255, 255, 255), 1.0))

    # pick blink moments (every ~2.5-4.5 s, lasting ~5 frames)
    blink = set()
    t = rng.uniform(1.0, 2.0)
    while t < n / fps:
        f = int(t * fps)
        blink.update(range(f, f + 5))
        t += rng.uniform(2.5, 4.5)

    cache = {}
    for i in range(n):
        lv = levels[i]
        emo, lean, tint, bright = frame_context[i]
        talking = lv > 0

        amp = 18 if emo == "excited" else 6 if emo == "thinking" else 14
        freq = 3.6 if emo == "excited" else 2.2 if emo == "thinking" else 3.2
        bounce = -int(round(amp * abs(math.sin(i / fps * math.pi * freq)))) if talking else \
                 -int(round(4 * abs(math.sin(i / fps * math.pi * 1.2))))
        bounce = round(bounce / 3) * 3          # quantise so poses can be cached
        arm = int(round(math.sin(i / fps * math.pi * 2.4) * 3)) * 6

        key = (lv, i in blink, bounce, arm, emo, lean, tint, bright)
        if key not in cache:
            cache[key] = _draw(lv, i in blink, bounce, arm, emo, lean, tint, bright, size)
        cache[key].save(os.path.join(outdir, f"char_{i + 1:05d}.png"), compress_level=1)

    return os.path.join(outdir, "char_%05d.png")
