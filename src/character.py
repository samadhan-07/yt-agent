"""Original cartoon mascot ("Bittu") drawn with Pillow. No downloads, no API keys.

How it works
  1. mouth_levels(): decodes the narration audio and turns its loudness into a mouth
     opening (0 = closed ... 3 = wide) for every video frame (simple lip sync).
  2. render_frames(): draws the mascot for every frame (blinking, bouncing, waving)
     as transparent PNGs. render.py overlays them on the video with FFmpeg.
"""
import math, os, random, subprocess
import numpy as np
from PIL import Image, ImageDraw

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


def _draw(level, blink, bounce, arm, size):
    """Draw one pose on a 1200x1200 canvas, return a size x size RGBA image."""
    c = 600 * SS
    img = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = SS

    def E(cx, cy, rx, ry, fill, outline=None, w=0):
        d.ellipse([(cx - rx) * s, (cy - ry) * s, (cx + rx) * s, (cy + ry) * s],
                  fill=fill, outline=outline, width=int(w * s))

    dy = bounce  # vertical bounce in canvas px (negative = up)
    # ground shadow
    E(300, 560, 150 - dy * 0.3, 18, (0, 0, 0, 55))
    # feet
    E(235, 540 + dy * 0.4, 52, 28, BODY_SHADE, INK, 6)
    E(365, 540 + dy * 0.4, 52, 28, BODY_SHADE, INK, 6)
    # arms (one waves)
    E(112, 360 + dy + arm * 1.0, 38, 62, BODY_SHADE, INK, 6)
    E(488, 360 + dy - arm * 1.6, 38, 62, BODY_SHADE, INK, 6)
    # antenna
    d.line([300 * s, (150 + dy) * s, 300 * s, (95 + dy * 1.4) * s], fill=INK, width=8 * s)
    E(300, 82 + dy * 1.4, 20, 20, CHEEK, INK, 6)
    # body
    E(300, 340 + dy, 168, 190, BODY, INK, 8)
    E(300, 395 + dy, 105, 100, (255, 214, 120, 255))  # belly patch
    # cheeks
    E(185, 355 + dy, 28, 18, CHEEK)
    E(415, 355 + dy, 28, 18, CHEEK)
    # eyes
    for ex in (235, 365):
        ey = 270 + dy
        if blink:
            d.line([(ex - 38) * s, ey * s, (ex + 38) * s, ey * s], fill=INK, width=8 * s)
        else:
            E(ex, ey, 40, 48, WHITE, INK, 6)
            E(ex + 4, ey + 6, 20, 24, INK)
            E(ex + 11, ey - 3, 7, 8, WHITE)
    # eyebrows lift when the voice is loud
    lift = 8 if level >= 3 else 0
    d.line([195 * s, (205 - lift + dy) * s, 270 * s, (200 - lift + dy) * s], fill=INK, width=8 * s)
    d.line([330 * s, (200 - lift + dy) * s, 405 * s, (205 - lift + dy) * s], fill=INK, width=8 * s)
    # mouth
    mx, my = 300, 375 + dy
    if level == 0:
        d.arc([(mx - 40) * s, (my - 25) * s, (mx + 40) * s, (my + 15) * s], 20, 160, fill=INK, width=8 * s)
    else:
        rx, ry = [(0, 0), (26, 12), (38, 26), (46, 44)][level]
        E(mx, my + ry * 0.4, rx, ry, MOUTH, INK, 6)
        if level >= 2:
            E(mx, my + ry * 0.9, rx * 0.6, ry * 0.4, TONGUE)
    return img.resize((size, size), Image.LANCZOS)


def render_frames(levels, outdir, fps, size=600, seed=7):
    """Write char_00001.png ... into outdir. Returns the ffmpeg input pattern."""
    os.makedirs(outdir, exist_ok=True)
    rng = random.Random(seed)
    n = len(levels)
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
        talking = lv > 0
        bounce = -int(round(14 * abs(math.sin(i / fps * math.pi * 3.2)))) if talking else \
            -int(round(5 * abs(math.sin(i / fps * math.pi * 1.2))))
        bounce = round(bounce / 3) * 3          # quantise so poses can be cached
        arm = int(round(math.sin(i / fps * math.pi * 2.4) * 3)) * 6
        key = (lv, i in blink, bounce, arm)
        if key not in cache:
            cache[key] = _draw(lv, i in blink, bounce, arm, size)
        cache[key].save(os.path.join(outdir, f"char_{i + 1:05d}.png"), compress_level=1)
    return os.path.join(outdir, "char_%05d.png")
