"""
gen_ruler.py  —  Generate assets/ruler.png for the GunBound overlay.

Requirements:
    pip install Pillow

Run from project root:
    python tools/gen_ruler.py
Output:
    assets/ruler.png  (1600×1200, RGBA transparent)
"""

import os
import sys
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PIL import Image, ImageDraw, ImageFont

from gunbound.storage import ASSETS_DIR

# ── Configuration (must match ruler.py) ───────────────────────────────────────
SCREEN_W   = 1600
SCREEN_H   = 1200
RULER_SIZE = 50    # strip thickness in px
TICK_PX    = 200   # 200 px = 0.125 SD  (1600 px = 1.0 SD)

OUT_FILE   = str(ASSETS_DIR / "ruler.png")

# ── Wind rose cutout ──────────────────────────────────────────────────────────
# The ruler overlay must not cover the wind rose HUD element.
# Rose absolute screen coords on 2560×1440: top-left (1230, 277), size 109×109.
# Ruler window top-left on screen ≈ ((2560-1600)//2, (1440-1200)//2 + 25)
#                                  = (480, 145).
# Rose in ruler PNG coordinates: (1230-480, 277-145) = (750, 132).
# Adjust ROSE_MARGIN for extra clearance if needed.
ROSE_RULER_X = 750
ROSE_RULER_Y = 132
ROSE_RULER_W = 109
ROSE_RULER_H = 109
ROSE_MARGIN  = 10

# ── Colors (R, G, B, A) ────────────────────────────────────────────────────────
TICK_COLOR  = (255, 30,  30,  255)   # red ticks / text
OUTLINE_CLR = (0,   0,   0,  255)   # black outline
GUIDE_CLR   = (220, 60,  60,  160)  # bright red guide lines


def load_font(size):
    """Try Consolas, fall back to default PIL font."""
    candidates = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def draw_outlined_text(draw, xy, text, font, fill, outline, stroke_width=2):
    draw.text(xy, text, font=font, fill=fill,
              stroke_width=stroke_width, stroke_fill=outline)


def fmt_sd(sd):
    s = f"{sd:.3f}".rstrip("0").rstrip(".")
    return s if s else "0"


def main():
    img  = Image.new("RGBA", (SCREEN_W, SCREEN_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_tick = load_font(12)
    font_sd   = load_font(13)

    n_h = SCREEN_W // TICK_PX   # 8 intervals
    n_v = SCREEN_H // TICK_PX   # 6 intervals

    # ── Guide lines (drawn first, behind strips) ───────────────────────────────
    overlay = Image.new("RGBA", (SCREEN_W, SCREEN_H), (0, 0, 0, 0))
    g = ImageDraw.Draw(overlay)

    for i in range(1, n_h):
        px = i * TICK_PX
        dash_len, gap_len = 6, 10
        y = RULER_SIZE
        while y < SCREEN_H:
            g.line([(px, y), (px, min(y + dash_len, SCREEN_H))], fill=GUIDE_CLR, width=2)
            y += dash_len + gap_len

    for i in range(1, n_v):
        py = i * TICK_PX
        dash_len, gap_len = 6, 10
        x = RULER_SIZE
        while x < SCREEN_W:
            g.line([(x, py), (min(x + dash_len, SCREEN_W), py)], fill=GUIDE_CLR, width=2)
            x += dash_len + gap_len

    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # ── Horizontal strip background ────────────────────────────────────────────
    # (transparent — no fill, only ticks/labels drawn)

    draw = ImageDraw.Draw(img)

    # ── Vertical strip background ──────────────────────────────────────────────
    # (transparent — no fill)

    # ── Corner ─────────────────────────────────────────────────────────────────
    # (transparent — no fill)

    # ── Horizontal ticks ───────────────────────────────────────────────────────
    for i in range(n_h + 1):
        px   = min(i * TICK_PX, SCREEN_W - 1)
        sd   = round(i * 0.125, 3)
        label = fmt_sd(sd)

        tick_h = 20 if i % 2 == 0 else 11
        ty = RULER_SIZE - tick_h

        # outlined tick line
        draw.line([(px, RULER_SIZE - 1), (px, ty)], fill=OUTLINE_CLR, width=3)
        draw.line([(px, RULER_SIZE - 1), (px, ty)], fill=TICK_COLOR,  width=1)

        # label
        bbox = draw.textbbox((0, 0), label, font=font_tick, stroke_width=2)
        tw = bbox[2] - bbox[0]
        if px == 0:
            lx = 4
        elif px >= SCREEN_W - 1:
            lx = SCREEN_W - 4 - tw
        else:
            lx = px - tw // 2
        ly = ty - (bbox[3] - bbox[1]) - 2
        draw_outlined_text(draw, (lx, ly), label, font_tick, TICK_COLOR, OUTLINE_CLR)

    # Horizontal bottom border
    draw.line([(0, RULER_SIZE), (SCREEN_W, RULER_SIZE)], fill=OUTLINE_CLR, width=3)
    draw.line([(0, RULER_SIZE), (SCREEN_W, RULER_SIZE)], fill=TICK_COLOR,  width=1)

    # ── Vertical ticks ─────────────────────────────────────────────────────────
    for i in range(n_v + 1):
        py   = min(i * TICK_PX, SCREEN_H - 1)
        sd   = round(i * 0.125, 3)
        label = fmt_sd(sd)

        tick_w = 20 if i % 2 == 0 else 11
        tx = RULER_SIZE - tick_w

        # outlined tick line
        draw.line([(RULER_SIZE - 1, py), (tx, py)], fill=OUTLINE_CLR, width=3)
        draw.line([(RULER_SIZE - 1, py), (tx, py)], fill=TICK_COLOR,  width=1)

        # label
        bbox = draw.textbbox((0, 0), label, font=font_tick, stroke_width=2)
        th = bbox[3] - bbox[1]
        if py == 0:
            ly = 4
        elif py >= SCREEN_H - 1:
            ly = SCREEN_H - 4 - th
        else:
            ly = py - th // 2
        lx = tx - (bbox[2] - bbox[0]) - 4
        draw_outlined_text(draw, (lx, ly), label, font_tick, TICK_COLOR, OUTLINE_CLR)

    # Vertical right border
    draw.line([(RULER_SIZE, 0), (RULER_SIZE, SCREEN_H)], fill=OUTLINE_CLR, width=3)
    draw.line([(RULER_SIZE, 0), (RULER_SIZE, SCREEN_H)], fill=TICK_COLOR,  width=1)

    # ── Corner "SD" label ──────────────────────────────────────────────────────
    bbox = draw.textbbox((0, 0), "SD", font=font_sd, stroke_width=2)
    cx = (RULER_SIZE - (bbox[2] - bbox[0])) // 2
    cy = (RULER_SIZE - (bbox[3] - bbox[1])) // 2
    draw_outlined_text(draw, (cx, cy), "SD", font_sd, TICK_COLOR, OUTLINE_CLR)

    # ── Wind rose cutout (erase all drawn content in that area) ─────────────────
    cx0 = max(0, ROSE_RULER_X - ROSE_MARGIN)
    cy0 = max(0, ROSE_RULER_Y - ROSE_MARGIN)
    cx1 = min(SCREEN_W, ROSE_RULER_X + ROSE_RULER_W + ROSE_MARGIN)
    cy1 = min(SCREEN_H, ROSE_RULER_Y + ROSE_RULER_H + ROSE_MARGIN)
    clear = Image.new("RGBA", (cx1 - cx0, cy1 - cy0), (0, 0, 0, 0))
    img.paste(clear, (cx0, cy0))
    print(f"Wind rose cutout: ({cx0}, {cy0})–({cx1}, {cy1}) cleared")

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    img.save(OUT_FILE, "PNG")
    print(f"Saved {OUT_FILE}  ({SCREEN_W}x{SCREEN_H} RGBA)")


if __name__ == "__main__":
    main()
