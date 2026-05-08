"""
Create a professional .ico file for the accounting system.
Uses Pillow (already installed via qrcode[pil]).
"""
from PIL import Image, ImageDraw, ImageFont
import os, math

def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Background: dark blue gradient via circle
    cx, cy = size // 2, size // 2
    r = size // 2 - 2

    # Draw layered circles for depth effect
    for i in range(r, 0, -1):
        ratio = i / r
        # Deep blue #1a3a6b → teal #0d9488
        rb = int(26 + (13 - 26) * (1 - ratio))
        gb = int(58 + (148 - 58) * (1 - ratio))
        bb = int(107 + (136 - 107) * (1 - ratio))
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=(rb, gb, bb, 255))

    # White circle border
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 200), width=max(1, size // 32))

    # Draw a stylized ledger / calculator symbol
    pad = size * 0.22
    box_left = pad
    box_top = pad * 0.9
    box_right = size - pad
    box_bottom = size - pad * 0.9
    bw = max(1, size // 40)

    # Ledger rectangle
    d.rounded_rectangle(
        [box_left, box_top, box_right, box_bottom],
        radius=size * 0.06,
        fill=(255, 255, 255, 230),
        outline=(200, 235, 255, 255),
        width=bw,
    )

    # Lines inside the ledger (representing rows)
    line_color = (26, 58, 107, 180)
    line_w = max(1, size // 64)
    rows = 4
    inner_top = box_top + size * 0.12
    inner_bottom = box_bottom - size * 0.06
    step = (inner_bottom - inner_top) / (rows + 1)
    for i in range(1, rows + 1):
        y = inner_top + i * step
        d.line(
            [(box_left + size * 0.08, y), (box_right - size * 0.08, y)],
            fill=line_color,
            width=line_w,
        )

    # Vertical divider (two columns)
    div_x = box_left + (box_right - box_left) * 0.62
    d.line(
        [(div_x, box_top + size * 0.06), (div_x, box_bottom - size * 0.04)],
        fill=line_color,
        width=line_w,
    )

    # Small coin / circle in top-left of ledger
    coin_r = size * 0.07
    coin_cx = box_left + (box_right - box_left) * 0.22
    coin_cy = box_top + size * 0.08
    d.ellipse(
        [coin_cx - coin_r, coin_cy - coin_r, coin_cx + coin_r, coin_cy + coin_r],
        fill=(255, 200, 50, 230),
        outline=(200, 150, 30, 200),
        width=max(1, size // 64),
    )

    return img


sizes = [256, 128, 64, 48, 32, 16]
frames = [make_icon(s) for s in sizes]

out_path = os.path.join(os.path.dirname(__file__), "app_icon.ico")
frames[0].save(
    out_path,
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=frames[1:],
)
print(f"Icon created: {out_path}")
