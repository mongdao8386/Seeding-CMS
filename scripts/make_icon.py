"""Sinh launcher/seeding.ico cho Seeding.exe: o vuong bo goc mau nhan cua dashboard, chu S.

    python scripts/make_icon.py

Chay lai khi muon doi mau / chu. Khong can cong cu ngoai: chi Pillow (da co trong .venv).
"""

from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "launcher" / "seeding.ico"
ACCENT = (31, 111, 107)  # xanh reu cua nut "Mo trinh duyet" tren dashboard
INK = (255, 250, 243)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = big // 5
    draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=radius, fill=ACCENT)
    font = _font(int(big * 0.72))
    text = "S"
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    w, h = right - left, bottom - top
    draw.text(((big - w) / 2 - left, (big - h) / 2 - top), text, font=font, fill=INK)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [render(s) for s in sizes]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print(f"da ghi {OUT} ({OUT.stat().st_size} bytes, {len(sizes)} co)")


if __name__ == "__main__":
    main()
