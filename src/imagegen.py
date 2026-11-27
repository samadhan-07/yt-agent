"""Dynamic visual generator supporting:
1. 'illustration': Surrealist 2D vector artwork via Pollinations (FLUX)
2. 'nature': Atmospheric nature photography (Pexels API if PEXELS_API_KEY is set, else FLUX)
3. 'quote': Local editorial typographic quote card rendered with Pillow
"""
import io, os, textwrap, time, requests
import numpy as np
from urllib.parse import quote
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

BASE = "https://image.pollinations.ai/prompt/"
_last_call = 0.0

QUOTE_PALETTES = [
    ((18, 24, 34), (34, 46, 62), (222, 174, 104)),    # Deep Slate & Warm Ochre
    ((22, 20, 28), (44, 38, 52), (214, 168, 124)),    # Charcoal Plum & Amber
    ((16, 28, 28), (30, 52, 50), (206, 182, 132)),    # Midnight Pine & Sand
]


def _load_font(size: int, italic: bool = False):
    lang = os.environ.get("VIDEO_LANGUAGE", "en").lower()
    if lang in ("hi", "hindi"):
        candidates = [
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansDevanagari-Bold.otf",
            "/usr/share/fonts/truetype/noto/NotoSerifDevanagari-Regular.ttf",
        ]
    elif italic:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
            "georgiai.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
            "georgia.ttf",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_quote_card(
    quote_text: str, author: str, dest: str, seed: int, width: int = 1920, height: int = 1080
) -> str:
    """Render an atmospheric minimalist quote card with subtle film grain."""
    c_outer, c_inner, accent = QUOTE_PALETTES[seed % len(QUOTE_PALETTES)]

    y = np.linspace(-1.0, 1.0, height)[:, None]
    x = np.linspace(-1.0, 1.0, width)[None, :]
    dist = np.clip(np.sqrt(x * x + y * y) / 1.35, 0.0, 1.0)

    bg = np.zeros((height, width, 3), dtype=np.float32)
    for ch in range(3):
        bg[:, :, ch] = c_inner[ch] * (1.0 - dist) + c_outer[ch] * dist

    np_rng = np.random.default_rng(seed)
    grain = np_rng.normal(0.0, 4.2, size=(height, width, 1))
    bg = np.clip(bg + grain, 0, 255).astype(np.uint8)

    img = Image.fromarray(bg, mode="RGB")
    draw = ImageDraw.Draw(img)

    pad = 68
    border_col = tuple(min(255, int(c * 1.45)) for c in c_inner)
    draw.rectangle([pad, pad, width - pad, height - pad], outline=border_col, width=2)

    q_font = _load_font(54, italic=False)
    a_font = _load_font(30, italic=True)

    raw_quote = quote_text.strip().strip('"“”')
    cleaned = f"“{raw_quote}”"
    wrapped_lines = textwrap.wrap(cleaned, width=38)

    line_heights = []
    for line in wrapped_lines:
        bbox = draw.textbbox((0, 0), line, font=q_font)
        line_heights.append((bbox[3] - bbox[1]) + 22)

    total_text_h = sum(line_heights)
    author_gap = 48 if author else 0
    block_h = total_text_h + author_gap + (40 if author else 0)
    cur_y = (height - block_h) // 2

    rule_w = 110
    draw.line(
        [(width - rule_w) // 2, cur_y - 42, (width + rule_w) // 2, cur_y - 42],
        fill=accent,
        width=3,
    )

    for line, lh in zip(wrapped_lines, line_heights):
        bbox = draw.textbbox((0, 0), line, font=q_font)
        lw = bbox[2] - bbox[0]
        draw.text(((width - lw) // 2, cur_y), line, font=q_font, fill=(244, 240, 232))
        cur_y += lh

    if author:
        cur_y += 22
        attr = f"— {author.lstrip('—- ')}"
        bbox = draw.textbbox((0, 0), attr, font=a_font)
        aw = bbox[2] - bbox[0]
        draw.text(((width - aw) // 2, cur_y), attr, font=a_font, fill=accent)

    img.save(dest, format="JPEG", quality=94)
    return str(dest)


def _try_pexels_nature(query: str, dest: str, seed: int, width: int, height: int) -> str | None:
    """Optional real nature photo via Pexels if PEXELS_API_KEY is configured."""
    pexels_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not pexels_key:
        return None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": pexels_key},
            params={"query": query, "orientation": "landscape", "per_page": 10},
            timeout=30,
        )
        r.raise_for_status()
        photos = r.json().get("photos") or []
        if not photos:
            return None
        chosen = photos[seed % len(photos)]
        src_url = chosen["src"].get("large2x") or chosen["src"].get("original")
        img_resp = requests.get(src_url, timeout=60)
        img_resp.raise_for_status()
        img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")

        target_ratio = width / height
        src_w, src_h = img.size
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))
        img = img.resize((width, height), Image.Resampling.LANCZOS)
        img.save(dest, format="JPEG", quality=92)
        return str(dest)
    except Exception:
        return None


def generate(
    prompt,
    style,
    dest,
    seed,
    model="flux",
    delay=16,
    width=1920,
    height=1080,
    visual_type="illustration",
    quote_text="",
    quote_author="",
    nature_style="",
):
    global _last_call
    vtype = (visual_type or "illustration").strip().lower()

    if vtype == "quote" and quote_text:
        return render_quote_card(quote_text, quote_author, dest, seed, width=width, height=height)

    if vtype == "nature":
        pexels_hit = _try_pexels_nature(prompt, dest, seed, width, height)
        if pexels_hit:
            return pexels_hit
        active_style = nature_style or style
    else:
        active_style = style

    full = f"{prompt}. {active_style}"
    params = {
        "width": width,
        "height": height,
        "model": model,
        "seed": seed,
        "nologo": "true",
        "enhance": "false",
    }
    headers = {}
    key = os.environ.get("POLLINATIONS_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
        delay = min(delay, 2)

    last = None
    for attempt in range(5):
        wait = delay - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        try:
            r = requests.get(BASE + quote(full), params=params, headers=headers, timeout=180)
            ok = r.status_code == 200 and r.headers.get("content-type", "").startswith("image")
            if ok and len(r.content) > 10_000:
                img = Image.open(io.BytesIO(r.content)).convert("RGB")
                if img.size != (width, height):
                    img = img.resize((width, height), Image.Resampling.LANCZOS)
                img.save(dest, format="JPEG", quality=92)
                return str(dest)
            last = f"HTTP {r.status_code} {r.headers.get('content-type')} ({len(r.content)} bytes)"
        except Exception as e:
            last = str(e)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Image generation failed for '{prompt[:50]}...': {last}")


def make_thumbnail(bg_image_path: str, hook_text: str, dest: str) -> str:
    """Create a 1280x720 high-contrast YouTube thumbnail from Scene 1's artwork."""
    tw, th = 1280, 720
    base = Image.open(bg_image_path).convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
    base = ImageEnhance.Contrast(base).enhance(1.18)
    base = ImageEnhance.Color(base).enhance(1.15).convert("RGBA")

    grad = np.zeros((th, tw, 4), dtype=np.uint8)
    alpha_ramp = np.linspace(225, 15, tw, dtype=np.uint8)
    grad[:, :, 0] = 12
    grad[:, :, 1] = 16
    grad[:, :, 2] = 24
    grad[:, :, 3] = alpha_ramp[None, :]
    overlay = Image.fromarray(grad, mode="RGBA")

    composed = Image.alpha_composite(base, overlay).convert("RGB")
    draw = ImageDraw.Draw(composed)

    font = _load_font(64, italic=False)
    raw = hook_text.strip()
    display_text = raw.upper() if raw.isascii() else raw
    lines = textwrap.wrap(display_text, width=18)[:3]
    line_h = 84
    total_h = len(lines) * line_h
    start_y = (th - total_h) // 2

    draw.rectangle([60, start_y - 6, 68, start_y + total_h - 6], fill=(235, 180, 92))

    for idx, line in enumerate(lines):
        y = start_y + idx * line_h
        draw.text((92 + 3, y + 3), line, font=font, fill=(8, 10, 16))
        draw.text((92, y), line, font=font, fill=(248, 244, 236))

    composed.save(dest, format="JPEG", quality=93, optimize=True)
    return str(dest)
