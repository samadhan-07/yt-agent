"""Minimalist voice-reactive ambient orb overlay for philosophical essays.
When character.enabled is false in config.yaml, this module is skipped completely."""
import math, os, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SS = 2


def mouth_levels(audio_path, fps, n_frames):
    """Return a list of n_frames ints in 0..3 based on vocal amplitude."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(audio_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if x.size == 0:
        return [0] * n_frames
    hop = int(16000 / fps)
    rms = np.array(
        [
            np.sqrt(np.mean(x[i * hop : (i + 1) * hop] ** 2) + 1e-9)
            if i * hop < x.size
            else 0.0
            for i in range(n_frames)
        ]
    )
    ref = np.percentile(rms, 90) or 1.0
    env = np.clip(rms / ref, 0, 1.3)
    env = np.convolve(env, np.ones(5) / 5, mode="same")
    return [0 if v < 0.12 else 1 if v < 0.40 else 2 if v < 0.75 else 3 for v in env]


def _draw_orb(level, phase, size):
    c = 240 * SS
    img = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")
    cx = cy = c // 2

    base_r = (36 + level * 7 + math.sin(phase) * 3) * SS
    # Soft warm ochre outer aura
    for step, alpha in ((1.65, 22), (1.32, 42), (1.0, 95)):
        r = base_r * step
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(226, 178, 112, alpha))

    # Crisp inner ring
    ring_r = (48 + level * 4) * SS
    d.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=(242, 224, 192, 130),
        width=2 * SS,
    )

    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def render_frames(
    levels, outdir, fps, size=180, seed=7, scenes=None, scene_durs=None, image_paths=None
):
    """Write char_00001.png ... into outdir. Returns the ffmpeg input pattern."""
    os.makedirs(outdir, exist_ok=True)
    n = len(levels)
    cache = {}
    for i in range(n):
        lv = levels[i]
        phase_bucket = int(round((i / fps) * 4)) % 16
        key = (lv, phase_bucket, size)
        if key not in cache:
            cache[key] = _draw_orb(lv, phase_bucket * (math.pi / 8), size)
        cache[key].save(os.path.join(outdir, f"char_{i + 1:05d}.png"), compress_level=1)

    return os.path.join(outdir, "char_%05d.png")
