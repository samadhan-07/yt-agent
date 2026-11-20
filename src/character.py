"""Realistic 3D-styled Indian little boy mascot ("Bittu") drawn with Pillow.
No downloads, no API keys.

How it works
  1. mouth_levels(): decodes the narration audio and turns its loudness into a mouth
     opening (0 = closed ... 3 = wide) for every video frame (lip sync).
  2. render_frames(): renders Bittu with soft volumetric shading, hair, hoodie, expressive
     eyes, hands, contextual emotions/gestures, and ambient lighting sampled from each
     scene's background image.
"""
import math, os, random, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

# Realistic warm skin, dark hair, and casual outfit palette
SKIN_BASE = (232, 174, 134, 255)
SKIN_LIGHT = (248, 200, 166, 255)
SKIN_SHADOW = (192, 132, 96, 255)
BLUSH = (228, 128, 118, 95)

HAIR_DARK = (24, 20, 22, 255)
HAIR_HIGHLIGHT = (58, 48, 46, 255)

SHIRT_BASE = (36, 112, 214, 255)
SHIRT_LIGHT = (72, 148, 245, 255)
SHIRT_DARK = (22, 74, 152, 255)
HOOD_ACCENT = (255, 168, 38, 255)

IRIS_DARK = (46, 28, 18, 255)
IRIS_WARM = (92, 56, 34, 255)
SCLERA = (250, 250, 252, 255)
WHITE = (255, 255, 255, 255)

LIP_COLOR = (188, 96, 92, 255)
MOUTH_INNER = (78, 24, 28, 255)
TONGUE = (224, 108, 116, 255)
TEETH = (248, 246, 242, 255)

SS = 2  # 2x supersampling for smooth anti-aliased edges


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
    env = np.convolve(env, np.ones(3) / 3, mode="same")
    levels = []
    for v in env:
        levels.append(0 if v < 0.12 else 1 if v < 0.40 else 2 if v < 0.75 else 3)
    return levels


def _scene_tint(image_path):
    """Extract quantized RGB tint and brightness (0.76..1.06) from a background image."""
    try:
        im = Image.open(image_path).convert("RGB").resize((32, 32))
        arr = np.asarray(im, dtype=np.float32)
        mean_rgb = arr.mean(axis=(0, 1))
        luma = (0.299 * mean_rgb[0] + 0.587 * mean_rgb[1] + 0.114 * mean_rgb[2]) / 255.0
        tint = tuple(int(round(c / 32) * 32) for c in mean_rgb)
        brightness = round(0.76 + 0.30 * float(luma), 2)
        return tint, brightness
    except Exception:
        return (255, 255, 255), 1.0


def _tint_color(rgba, tint_rgb, strength=0.14):
    r = int(rgba[0] * (1 - strength) + tint_rgb[0] * strength)
    g = int(rgba[1] * (1 - strength) + tint_rgb[1] * strength)
    b = int(rgba[2] * (1 - strength) + tint_rgb[2] * strength)
    return (r, g, b, rgba[3])


def _draw_hand(d, s, cx, cy, r, skin_base, skin_light, skin_shadow, flip=1):
    """Draw a soft 3D-shaded hand with thumb."""
    # shadow
    d.ellipse([(cx - r + 3) * s, (cy - r + 4) * s, (cx + r + 3) * s, (cy + r + 4) * s], fill=skin_shadow)
    # palm/fist
    d.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s], fill=skin_base)
    # highlight
    d.ellipse([(cx - r * 0.65) * s, (cy - r * 0.7) * s, (cx + r * 0.35) * s, (cy + r * 0.25) * s], fill=skin_light)
    # thumb
    tx = cx - flip * r * 0.78
    ty = cy - r * 0.15
    d.ellipse([(tx - r * 0.38) * s, (ty - r * 0.28) * s, (tx + r * 0.38) * s, (ty + r * 0.28) * s], fill=skin_base)


def _draw(level, blink, bounce, arm, emotion, lean_x, tint_rgb, brightness, size):
    """Draw one realistic 3D-styled little boy pose on a 1200x1200 canvas."""
    c = 600 * SS
    img = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    s = SS

    skin_b = _tint_color(SKIN_BASE, tint_rgb, 0.12)
    skin_l = _tint_color(SKIN_LIGHT, tint_rgb, 0.10)
    skin_s = _tint_color(SKIN_SHADOW, tint_rgb, 0.14)
    shirt_b = _tint_color(SHIRT_BASE, tint_rgb, 0.15)
    shirt_l = _tint_color(SHIRT_LIGHT, tint_rgb, 0.12)
    shirt_d = _tint_color(SHIRT_DARK, tint_rgb, 0.16)
    hood_c = _tint_color(HOOD_ACCENT, tint_rgb, 0.14)

    def E(cx, cy, rx, ry, fill, outline=None, w=0):
        d.ellipse([(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s],
                  fill=fill, outline=outline, width=int(w * s))

    dy = bounce
    ox = lean_x

    # Soft ground/ambient shadow
    E(300 + ox * 0.4, 578, 175 - dy * 0.25, 18, (15, 20, 35, 70))

    # Back hair volume (behind ears and neck)
    E(300 + ox, 232 + dy, 134, 136, HAIR_DARK)

    # Hoodie collar / hood fold behind neck
    E(300 + ox * 0.7, 412 + dy * 0.7, 108, 48, hood_c)
    E(300 + ox * 0.7, 418 + dy * 0.7, 94, 38, shirt_d)

    # Torso / Hoodie shoulders with volumetric 3D shading
    E(300 + ox * 0.6, 515 + dy * 0.5, 152, 125, shirt_d)
    E(296 + ox * 0.6, 508 + dy * 0.5, 142, 116, shirt_b)
    E(284 + ox * 0.6, 486 + dy * 0.5, 106, 78, shirt_l)

    # Hoodie center zipper seam & drawstrings
    d.line([(300 + ox * 0.6) * s, (430 + dy * 0.5) * s, (300 + ox * 0.6) * s, (595 + dy * 0.5) * s],
           fill=shirt_d, width=4 * s)
    for dx_str in (-26, 26):
        sx = 300 + ox * 0.65 + dx_str
        sy0 = 434 + dy * 0.6
        d.line([sx * s, sy0 * s, (sx + dx_str * 0.15) * s, (sy0 + 48) * s], fill=WHITE, width=5 * s)
        E(sx + dx_str * 0.15, sy0 + 50, 5, 7, hood_c)

    # Neck with under-chin shadow
    d.rounded_rectangle([(272 + ox * 0.85) * s, (358 + dy * 0.85) * s,
                         (328 + ox * 0.85) * s, (425 + dy * 0.85) * s],
                        radius=22 * s, fill=skin_b)
    E(300 + ox * 0.9, 376 + dy * 0.9, 34, 18, skin_s)

    # Ears with inner ear shadow
    for side in (-1, 1):
        ex = 300 + ox + side * 124
        ey = 278 + dy
        E(ex, ey, 22, 32, skin_s)
        E(ex - side * 2, ey, 18, 28, skin_b)
        E(ex - side * 3, ey + 2, 10, 17, skin_s)

    # Head shape (childlike round cheeks and soft chin)
    E(300 + ox, 266 + dy, 124, 128, skin_s)          # ambient shadow rim
    E(298 + ox, 263 + dy, 120, 124, skin_b)          # base skin tone
    E(286 + ox, 240 + dy, 88, 84, skin_l)            # forehead & upper-cheek soft light
    # Chubby lower cheeks
    E(236 + ox, 298 + dy, 46, 38, skin_b)
    E(364 + ox, 298 + dy, 46, 38, skin_b)
    # Soft rosy cheek blush
    E(234 + ox, 302 + dy, 30, 18, BLUSH)
    E(366 + ox, 302 + dy, 30, 18, BLUSH)

    # Hair: messy modern side-swept little-boy hairstyle
    E(300 + ox, 175 + dy, 128, 72, HAIR_DARK)
    # Layered front locks / bangs
    bangs = [
        (215, 195, 42, 34),
        (252, 174, 48, 36),
        (298, 168, 54, 38),
        (345, 176, 46, 35),
        (382, 196, 38, 32),
        (276, 192, 34, 24),
        (322, 190, 32, 22),
    ]
    for bx, by, brx, bry in bangs:
        E(bx + ox, by + dy, brx, bry, HAIR_DARK)
    # Soft hair specular highlights
    E(275 + ox, 154 + dy, 42, 12, HAIR_HIGHLIGHT)
    E(324 + ox, 160 + dy, 28, 9, HAIR_HIGHLIGHT)

    # Expressive realistic eyes (sclera, warm brown iris, dark pupil, dual catchlights, upper eyelid)
    eye_scale = 1.12 if emotion in ("shocked", "scared") else 0.90 if emotion == "thinking" else 1.0
    pupil_dx = 7 if emotion == "curious" else -6 if emotion == "thinking" else 2
    pupil_dy = -6 if emotion in ("curious", "thinking") else 2

    for side, ex in ((-1, 250 + ox), (1, 350 + ox)):
        ey = 264 + dy
        if blink and emotion not in ("shocked", "scared"):
            # Closed eyelid crease & eyelashes
            d.arc([(ex - 30) * s, (ey - 10) * s, (ex + 30) * s, (ey + 16) * s],
                  15, 165, fill=HAIR_DARK, width=6 * s)
        else:
            rx, ry = 31 * eye_scale, 27 * eye_scale
            # Eye socket shadow
            E(ex, ey + 2, rx + 3, ry + 3, skin_s)
            # Sclera
            E(ex, ey, rx, ry, SCLERA)
            # Iris
            ir = 17.5 * (0.90 if emotion in ("shocked", "scared") else 1.0)
            ix, iy = ex + pupil_dx, ey + pupil_dy
            E(ix, iy, ir, ir, IRIS_DARK)
            E(ix, iy + 2, ir * 0.78, ir * 0.78, IRIS_WARM)
            # Pupil
            pr = ir * (0.50 if emotion in ("shocked", "scared") else 0.58)
            E(ix, iy, pr, pr, (14, 12, 14, 255))
            # Realistic dual catchlights
            E(ix - ir * 0.35, iy - ir * 0.35, 5.2, 5.2, WHITE)
            E(ix + ir * 0.32, iy + ir * 0.28, 2.6, 2.6, (255, 255, 255, 210))
            # Upper lash line
            d.arc([(ex - rx) * s, (ey - ry) * s, (ex + rx) * s, (ey + ry * 0.6) * s],
                  195, 345, fill=HAIR_DARK, width=5 * s)

    # Eyebrows (expressive dark brown strokes)
    lift = 9 if (level >= 3 or emotion in ("shocked", "excited")) else 0
    if emotion == "curious":
        d.line([(222 + ox) * s, (224 + dy) * s, (276 + ox) * s, (222 + dy) * s], fill=HAIR_DARK, width=7 * s)
        d.line([(324 + ox) * s, (206 + dy) * s, (378 + ox) * s, (214 + dy) * s], fill=HAIR_DARK, width=7 * s)
    elif emotion == "scared":
        d.line([(222 + ox) * s, (228 + dy) * s, (276 + ox) * s, (214 + dy) * s], fill=HAIR_DARK, width=7 * s)
        d.line([(324 + ox) * s, (214 + dy) * s, (378 + ox) * s, (228 + dy) * s], fill=HAIR_DARK, width=7 * s)
    else:
        d.line([(222 + ox) * s, (222 - lift + dy) * s, (276 + ox) * s, (218 - lift + dy) * s], fill=HAIR_DARK, width=7 * s)
        d.line([(324 + ox) * s, (218 - lift + dy) * s, (378 + ox) * s, (222 - lift + dy) * s], fill=HAIR_DARK, width=7 * s)

    # Soft 3D button nose (subtle bridge highlight + nostrils shadow)
    nx, ny = 300 + ox, 294 + dy
    E(nx - 2, ny - 5, 7, 11, skin_l)
    E(nx, ny + 3, 13, 8, skin_s)
    E(nx - 1, ny + 1, 11, 7, skin_b)

    # Mouth & Lip Sync
    mx, my = 300 + ox, 336 + dy
    if level == 0:
        if emotion == "shocked":
            E(mx, my + 4, 15, 18, MOUTH_INNER, LIP_COLOR, 4)
        elif emotion == "thinking":
            d.line([(mx - 22) * s, (my + 4) * s, (mx + 22) * s, (my - 1) * s], fill=LIP_COLOR, width=6 * s)
        else:
            d.arc([(mx - 30) * s, (my - 16) * s, (mx + 30) * s, (my + 14) * s], 18, 162, fill=LIP_COLOR, width=6 * s)
    else:
        rx, ry = [(0, 0), (22, 10), (30, 19), (36, 28)][level]
        # Lip border + inner mouth
        E(mx, my + ry * 0.35, rx + 3, ry + 3, LIP_COLOR)
        E(mx, my + ry * 0.35, rx, ry, MOUTH_INNER)
        # Upper teeth hint when talking
        if level >= 1:
            d.chord([(mx - rx * 0.78) * s, (my - ry * 0.55) * s,
                     (mx + rx * 0.78) * s, (my + ry * 0.25) * s], 180, 360, fill=TEETH)
        # Tongue
        if level >= 2:
            E(mx, my + ry * 0.75, rx * 0.58, ry * 0.38, TONGUE)

    # Contextual Arms & Hands (foreground layer so hands can gesture near chin/cheeks/upward)
    if emotion == "excited":
        # Both hands raised happily
        d.line([(178 + ox * 0.6) * s, (485 + dy * 0.5) * s, (132 + ox) * s, (375 + dy - arm) * s],
               fill=shirt_b, width=38 * s)
        d.line([(422 + ox * 0.6) * s, (485 + dy * 0.5) * s, (468 + ox) * s, (375 + dy + arm) * s],
               fill=shirt_b, width=38 * s)
        _draw_hand(d, s, 130 + ox, 365 + dy - arm, 24, skin_b, skin_l, skin_s, flip=-1)
        _draw_hand(d, s, 470 + ox, 365 + dy + arm, 24, skin_b, skin_l, skin_s, flip=1)
    elif emotion == "curious":
        # Right hand pointing up toward the background scene
        d.line([(418 + ox * 0.6) * s, (485 + dy * 0.5) * s, (462 + ox) * s, (335 + dy - arm * 0.7) * s],
               fill=shirt_b, width=36 * s)
        _draw_hand(d, s, 462 + ox, 322 + dy - arm * 0.7, 23, skin_b, skin_l, skin_s, flip=1)
        # Index finger pointing up
        d.rounded_rectangle([(454 + ox) * s, (282 + dy - arm * 0.7) * s,
                             (468 + ox) * s, (322 + dy - arm * 0.7) * s],
                            radius=7 * s, fill=skin_b)
    elif emotion in ("shocked", "scared"):
        # Hands up near cheeks in surprise
        d.line([(185 + ox * 0.6) * s, (490 + dy * 0.5) * s, (168 + ox) * s, (345 + dy + arm * 0.4) * s],
               fill=shirt_b, width=36 * s)
        d.line([(415 + ox * 0.6) * s, (490 + dy * 0.5) * s, (432 + ox) * s, (345 + dy - arm * 0.4) * s],
               fill=shirt_b, width=36 * s)
        _draw_hand(d, s, 168 + ox, 332 + dy + arm * 0.4, 23, skin_b, skin_l, skin_s, flip=-1)
        _draw_hand(d, s, 432 + ox, 332 + dy - arm * 0.4, 23, skin_b, skin_l, skin_s, flip=1)
    elif emotion == "thinking":
        # Hand resting thoughtfully near chin
        d.line([(410 + ox * 0.6) * s, (495 + dy * 0.5) * s, (346 + ox) * s, (378 + dy + arm * 0.3) * s],
               fill=shirt_b, width=36 * s)
        _draw_hand(d, s, 342 + ox, 368 + dy + arm * 0.3, 22, skin_b, skin_l, skin_s, flip=1)
    else:
        # Friendly welcoming wave with one hand
        d.line([(418 + ox * 0.6) * s, (485 + dy * 0.5) * s, (466 + ox) * s, (395 + dy - arm * 1.2) * s],
               fill=shirt_b, width=36 * s)
        _draw_hand(d, s, 468 + ox, 384 + dy - arm * 1.2, 23, skin_b, skin_l, skin_s, flip=1)

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
            lean = -16 if idx % 3 == 1 else 16 if idx % 3 == 2 else 0
            count = max(1, int(round(dur * fps)))
            frame_context.extend([(sc.get("emotion", "happy"), lean, tint, bright)] * count)
    while len(frame_context) < n:
        frame_context.append(frame_context[-1] if frame_context else ("happy", 0, (255, 255, 255), 1.0))

    # Pick blink moments (every ~2.5-4.5 s, lasting ~5 frames)
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

        amp = 14 if emo == "excited" else 5 if emo == "thinking" else 10
        freq = 3.4 if emo == "excited" else 2.0 if emo == "thinking" else 2.8
        bounce = -int(round(amp * abs(math.sin(i / fps * math.pi * freq)))) if talking else \
                 -int(round(3 * abs(math.sin(i / fps * math.pi * 1.1))))
        bounce = round(bounce / 3) * 3
        arm = int(round(math.sin(i / fps * math.pi * 2.2) * 3)) * 5

        key = (lv, i in blink, bounce, arm, emo, lean, tint, bright)
        if key not in cache:
            cache[key] = _draw(lv, i in blink, bounce, arm, emo, lean, tint, bright, size)
        cache[key].save(os.path.join(outdir, f"char_{i + 1:05d}.png"), compress_level=1)

    return os.path.join(outdir, "char_%05d.png")
