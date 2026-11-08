"""Render the existing Clarify vector mark with iOS icon margins.

Development tool only. Pillow is required to rasterize this code-owned artwork.
The mark uses the same geometry as ClarifyMark.swift; never stretch its axes.
"""

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BARS = [
    (0.071, 0.403, 0.094, 0.186),
    (0.255, 0.132, 0.093, 0.455),
    (0.255, 0.681, 0.093, 0.188),
    (0.438, 0.041, 0.093, 0.185),
    (0.438, 0.270, 0.093, 0.458),
    (0.438, 0.766, 0.093, 0.193),
    (0.622, 0.132, 0.093, 0.189),
    (0.622, 0.403, 0.093, 0.466),
    (0.806, 0.404, 0.094, 0.186),
]
SIZE, AA = 1024, 4
scale = SIZE * 0.68 / 0.918  # 16% clear space above and below the visible mark.
offset_x, offset_y = SIZE / 2 - 0.4855 * scale, SIZE / 2 - 0.5 * scale
image = Image.new("RGB", (SIZE * AA, SIZE * AA), "black")
draw = ImageDraw.Draw(image)
rects = []
for x, y, width, height in BARS:
    x, y = offset_x + x * scale, offset_y + y * scale
    width, height = width * scale, height * scale
    draw.rounded_rectangle(
        tuple(v * AA for v in (x, y, x + width, y + height)),
        radius=width * AA / 2,
        fill="white",
    )
    rects.append(
        f'  <rect x="{x:.3f}" y="{y:.3f}" width="{width:.3f}" height="{height:.3f}" rx="{width / 2:.3f}" fill="white"/>'
    )
(ROOT / "assets/icon.svg").write_text(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">\n'
    '  <rect width="1024" height="1024" fill="black"/>\n'
    + "\n".join(rects)
    + "\n</svg>\n"
)
image.resize((SIZE, SIZE), Image.Resampling.LANCZOS).save(ROOT / "assets/icon.png")
