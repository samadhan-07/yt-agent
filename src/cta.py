"""Like / Share / Subscribe banner drawn with Pillow (no emoji fonts needed)."""
from PIL import Image, ImageDraw, ImageFont

SS = 2
WHITE = (255, 255, 255, 255)
BG = (16, 24, 48, 228)
RED = (230, 30, 30, 255)
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _thumb(d, ox, oy, k):
    P = lambda pts: [(ox + x * k, oy + y * k) for x, y in pts]
    d.rectangle([ox + 4 * k, oy + 26 * k, ox + 16 * k, oy + 52 * k], fill=WHITE)
    d.polygon(P([(20, 26), (30, 6), (37, 8), (39, 17), (35, 26), (51, 26), (55, 31),
                 (53, 48), (49, 52), (20, 52)]), fill=WHITE)


def _share(d, ox, oy, k):
    pts = [(46, 12), (16, 30), (46, 48)]
    for a, b in ((0, 1), (1, 2)):
        d.line([ox + pts[a][0] * k, oy + pts[a][1] * k, ox + pts[b][0] * k, oy + pts[b][1] * k],
               fill=WHITE, width=int(4 * k))
    for x, y in pts:
        d.ellipse([ox + (x - 8) * k, oy + (y - 8) * k, ox + (x + 8) * k, oy + (y + 8) * k], fill=WHITE)


def _bell(d, ox, oy, k):
    d.ellipse([ox + 14 * k, oy + 8 * k, ox + 46 * k, oy + 40 * k], fill=WHITE)
    d.rectangle([ox + 14 * k, oy + 24 * k, ox + 46 * k, oy + 40 * k], fill=WHITE)
    d.polygon([(ox + 8 * k, oy + 46 * k), (ox + 52 * k, oy + 46 * k),
               (ox + 46 * k, oy + 36 * k), (ox + 14 * k, oy + 36 * k)], fill=WHITE)
    d.ellipse([ox + 24 * k, oy + 46 * k, ox + 36 * k, oy + 56 * k], fill=WHITE)
    d.ellipse([ox + 27 * k, oy + 3 * k, ox + 33 * k, oy + 10 * k], fill=WHITE)


def make_cta(path, width=760, height=110):
    """Write the banner PNG to `path`."""
    s = SS
    img = Image.new("RGBA", (width * s, height * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, width * s - 1, height * s - 1], radius=(height // 2) * s, fill=BG)
    font = _font(34 * s)
    k = 0.8 * s
    cy = height * s // 2

    def text_at(x, label):
        d.text((x, cy), label, font=font, fill=WHITE, anchor="lm")

    x = 30 * s
    _thumb(d, x, cy - 30 * k, k); text_at(x + 62 * s, "LIKE")
    x = 195 * s
    _share(d, x, cy - 30 * k, k); text_at(x + 62 * s, "SHARE")
    bx0, bx1 = 425 * s, (width - 10) * s
    d.rounded_rectangle([bx0, 10 * s, bx1, (height - 10) * s], radius=((height - 20) // 2) * s, fill=RED)
    _bell(d, bx0 + 22 * s, cy - 30 * k, k)
    text_at(bx0 + 86 * s, "SUBSCRIBE")
    img.resize((width, height), Image.LANCZOS).save(path)
    return path
