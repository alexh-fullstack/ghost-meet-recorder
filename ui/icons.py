import os
import tempfile
from PIL import Image, ImageDraw, ImageFont

ICO_PATH = os.path.join(tempfile.gettempdir(), "ghost_meet_icon.ico")

_RENDER_SIZE = 512


def make_icon(color, size=64):
    img = Image.new("RGBA", (_RENDER_SIZE, _RENDER_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = _RENDER_SIZE // 10
    draw.ellipse([pad, pad, _RENDER_SIZE - pad, _RENDER_SIZE - pad], fill=color)
    try:
        font = ImageFont.truetype("segoeuib.ttf", int(_RENDER_SIZE * 0.44))
    except OSError:
        font = ImageFont.load_default()
    bbox = font.getbbox("g")
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (_RENDER_SIZE - tw) / 2 - bbox[0]
    y = (_RENDER_SIZE - th) / 2 - bbox[1]
    draw.text((x, y), "g", fill="white", font=font)
    if size != _RENDER_SIZE:
        img = img.resize((size, size), Image.LANCZOS)
    return img


def make_ico(color):
    base = make_icon(color, _RENDER_SIZE)
    sizes = [16, 20, 24, 32, 40, 48, 64, 256]
    imgs = [base.resize((s, s), Image.LANCZOS) for s in sizes]
    imgs[0].save(
        ICO_PATH, format="ICO",
        append_images=imgs[1:],
        sizes=[(s, s) for s in sizes],
    )
    return ICO_PATH