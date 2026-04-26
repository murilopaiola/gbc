"""
wind_reader.py — GunBound wind rose reader.

Captures the wind rose region from the game window, extracts:
  - Strength : template matching against data/XX.png reference images  (0–26)
  - Direction: inner-disc radial scoring to find the V-needle tip  (0–360°, 0=East, CCW)

Strength algorithm: binarize the digit crop (dark outline pixels) and find the
reference template with minimum SSD.  Add data/XX.png files to expand coverage.

Direction algorithm: score each radial direction r=15–38 by brightness × warmth.
The V-needle has three arms (one forward tip, two rear ends).  The closest pair
are the rear ends; the isolated peak is the tip we report.

Writes data/wind.json continuously while running.
main.py can read that file to pre-fill wind input.

Requirements:
    pip install mss Pillow
    pip install pywin32          (optional – for window-relative coords)

Usage:
    python tools/wind_reader.py               # start polling
    python tools/wind_reader.py --calibrate   # capture + save debug image
    python tools/wind_reader.py --test        # run on assets/wind*.png (no game needed)
    Ctrl+C to stop.

Calibration workflow:
    1. Run with --calibrate while the game is open.
    2. Open data/wind_debug.png and verify the rose is inside the red box.
    3. Adjust ROSE_CLIENT_* constants below until the box is tight around the rose rose.
"""

import sys
import json
import math
import time
import argparse
import ctypes
import functools

# Force UTF-8 output so Unicode characters in print() don't crash on Windows cp1252 terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from collections import deque, Counter
from pathlib import Path

# Allow running from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from gunbound.storage import DATA_DIR, ASSETS_DIR

from PIL import Image, ImageDraw

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    import win32gui
    HAS_PYWIN32 = True
except ImportError:
    HAS_PYWIN32 = False

# Absolute screen coordinates of the wind rose (2560×1440 monitor).
# Rose bounding box top-left: (1230, 277), bottom-right: (1339, 386).
ROSE_CLIENT_X  = 1230  # absolute screen X of capture region
ROSE_CLIENT_Y  = 277   # absolute screen Y of capture region
ROSE_CAPTURE_W = 109   # width  = 1339 - 1230
ROSE_CAPTURE_H = 109   # height = 386  - 277

# Center of the rose within the captured region (pixels).
# Derived from inner-disc edge points: left=13, right=92, top=15, bottom=94.
ROSE_CENTER_X  = 53
ROSE_CENTER_Y  = 55

# Disc boundary radius used only for the debug overlay circle.
SCAN_RADIUS = 42

# Inner disc radial scan zone.  The needle BODY (not just the tips) fills the
# disc interior from the center outward.  Scanning r=15–38 captures the full
# needle arms while staying safely inside the disc and away from the bezel.
INNER_SCAN_MIN = 15   # skip the center digit area
INNER_SCAN_MAX = 38   # just inside the disc–bezel boundary (~39 px)

# Angular step for the radial score sweep (degrees).
SCAN_STEP_DEG = 3

# Pixel brightness baseline: contributions below this are ignored.
# The dark disc background sits at max(R,G,B) ≈ 50–60; 80 gives a clean margin.
NEEDLE_BRIGHT_BASE = 80

# Warmth normalization factor.  Pixels with R–B = NEEDLE_WARM_FACTOR contribute
# twice the base weight.  Rewards yellow/orange needles without penalising white.
NEEDLE_WARM_FACTOR = 40.0

# Minimum angular separation between distinct needle-arm peaks (degrees).
MIN_PEAK_SEP_DEG = 30

# OCR crop: area containing the wind-strength number, relative to capture region.
# Absolute screen coords: (1262, 313) – (1303, 348)  →  minus rose origin (1230, 277).
OCR_X0, OCR_Y0 = 32, 36
OCR_X1, OCR_Y1 = 73, 71

# Maximum mean absolute error (0–255 scale) for a valid strength match.
# Templates captured from the live game score ~0; needle interference adds
# ~5–15 MAE on bad frames.  20 rejects clearly wrong matches while leaving
# room for the worst-case needle hit on the digit crop.
OCR_MAE_LIMIT = 20

# How long to wait between polls (seconds).
POLL_INTERVAL = 0.3

# Number of consecutive frames to accumulate before reporting a stable reading.
# 5 frames × 0.3 s = 1.5 s window.  Increase for more stability, decrease for
# lower latency.  Must be ≥ 3 for majority voting (min_fraction=0.6) to work.
BUFFER_SIZE = 5

# Motion detection: mean absolute pixel diff per channel (0–255) across the
# background zone above which camera movement is declared.
# Static compression noise sits at ~0–3; slow pans reach ~15–30.
# Increase if static scenes trigger false positives; decrease for slow-pan sensitivity.
MOTION_PIXEL_THRESHOLD = 8.0

# Angular outlier rejection: buffer angles deviating more than this (degrees)
# from the provisional circular mean are discarded before computing stable_angle().
# Protects against single-frame background glitches when no full pan is detected.
ANGLE_OUTLIER_THRESHOLD = 20.0

# Output file.
WIND_JSON  = DATA_DIR / "wind.json"
DEBUG_IMG  = DATA_DIR / "wind_debug.png"

# Substring of the game window title used to locate the process (case-insensitive).
GAME_WINDOW_TITLE = "GunBound"


# ── Window helpers ────────────────────────────────────────────────────────────

def _find_game_hwnd():
    if not HAS_PYWIN32:
        return None
    matches = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            if GAME_WINDOW_TITLE.lower() in win32gui.GetWindowText(hwnd).lower():
                matches.append(hwnd)
    win32gui.EnumWindows(_cb, None)
    return matches[0] if matches else None


def game_client_origin() -> tuple[int, int]:
    """Return absolute screen coordinates of the game window's client top-left.

    Falls back to (0, 0) if pywin32 is unavailable or the window is not found.
    """
    hwnd = _find_game_hwnd()
    if hwnd is None:
        return (0, 0)
    return win32gui.ClientToScreen(hwnd, (0, 0))


# ── Capture ───────────────────────────────────────────────────────────────────

def capture_rose(sct) -> Image.Image:
    """Capture the wind rose region and return it as an RGB PIL image."""
    region = {
        "left":   ROSE_CLIENT_X,
        "top":    ROSE_CLIENT_Y,
        "width":  ROSE_CAPTURE_W,
        "height": ROSE_CAPTURE_H,
    }
    raw = sct.grab(region)
    return Image.frombytes("RGB", raw.size, raw.rgb)


# ── Direction helpers ────────────────────────────────────────────────────────

def _circular_mean(angles_deg: list) -> float:
    """Circular mean of a list of angles (degrees), result in [0, 360)."""
    sin_s = sum(math.sin(math.radians(a)) for a in angles_deg)
    cos_s = sum(math.cos(math.radians(a)) for a in angles_deg)
    return math.degrees(math.atan2(sin_s, cos_s)) % 360


def _angular_dist(a1: float, a2: float) -> float:
    """Smallest angular distance between two angles in degrees."""
    d = abs(a1 - a2) % 360
    return min(d, 360.0 - d)


# ── Direction detection ───────────────────────────────────────────────────────

def detect_direction_shape(img: Image.Image) -> tuple:
    """
    Find the forward tip of the V-shaped needle using inner-disc radial scoring

    The V-needle has THREE bright arms visible in the disc interior (r=15–38):
      - One forward arm  (the apex we want to return)
      - Two rear arms    (the tail of the V, ~90° apart from each other)

    Each arm shows up as a peak in a per-angle brightness×warmth score:
      score(θ) = Σ max(maxRGB – BASE, 0) × (1 + max(R–B, 0) / WARM_FACTOR)
    This rewards any bright pixel and gives extra weight to warm/yellow needles
    without penalising white needles (strength 0–1).

    The two rear arms are the CLOSEST angular pair (~90° apart).  The forward
    arm is the one most isolated from that pair (~135° away).

    Convention: 0° = East/right, increases counter-clockwise.

    Returns:
        (angle_degrees, tip_pixel) — tip_pixel is a point in the tip direction
        at the inner-scan boundary, useful for the debug overlay.
    """
    pixels = img.load()
    w, h = img.size
    cx, cy = ROSE_CENTER_X, ROSE_CENTER_Y

    # ─ Score every direction ───────────────────────────────────────────────
    scores = {}
    step = SCAN_STEP_DEG
    for deg in range(0, 360, step):
        rad = math.radians(deg)
        s = 0.0
        for r in range(INNER_SCAN_MIN, INNER_SCAN_MAX + 1):
            x = int(round(cx + r * math.cos(rad)))
            y = int(round(cy - r * math.sin(rad)))
            if 0 <= x < w and 0 <= y < h:
                rv, gv, bv = pixels[x, y]
                bright = max(rv, gv, bv) - NEEDLE_BRIGHT_BASE
                if bright > 0:
                    warmth = 1.0 + max(rv - bv, 0) / NEEDLE_WARM_FACTOR
                    s += bright * warmth
        scores[deg] = s

    # ─ Find local maxima ──────────────────────────────────────────────────
    raw_peaks = []
    for deg in range(0, 360, step):
        p2 = scores[(deg - 2 * step) % 360]
        p1 = scores[(deg - step) % 360]
        n1 = scores[(deg + step) % 360]
        n2 = scores[(deg + 2 * step) % 360]
        if scores[deg] >= p1 and scores[deg] >= n1 and scores[deg] > p2 and scores[deg] > n2:
            raw_peaks.append((scores[deg], deg))
    raw_peaks.sort(reverse=True)

    if not raw_peaks:
        return 0.0, None

    # Keep well-separated peaks with score ≥ 15% of the top peak.
    min_score = raw_peaks[0][0] * 0.15
    peaks = []
    for sc, deg in raw_peaks:
        if sc < min_score:
            break
        if all(_angular_dist(deg, k) > MIN_PEAK_SEP_DEG for k in peaks):
            peaks.append(deg)
        if len(peaks) >= 5:
            break

    if not peaks:
        return 0.0, None

    # ─ Identify the forward tip ───────────────────────────────────────────
    if len(peaks) >= 3:
        # Sort by score descending; consider up to top 3 as needle arms.
        top3 = sorted(peaks, key=lambda d: -scores[d])[:3]
        n = len(top3)
        min_d = float("inf")
        ri, rj = 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                d = _angular_dist(top3[i], top3[j])
                if d < min_d:
                    min_d = d
                    ri, rj = i, j
        rear_mid = _circular_mean([top3[ri], top3[rj]])
        non_rear = [top3[i] for i in range(n) if i not in {ri, rj}]
        tip_deg_grid = max(non_rear, key=lambda d: _angular_dist(d, rear_mid))
    else:
        # Fewer than 3 peaks: return the highest-scoring one.
        tip_deg_grid = peaks[0]

    # ─ Sub-step parabolic interpolation ──────────────────────────────────
    # Fit a parabola through each grid-peak and its two neighbours to find
    # the true maximum between samples.  Reduces angle error from ±3° to < 0.5°.
    def _refine(deg: int) -> float:
        p  = scores[(deg - step) % 360]
        c  = scores[deg]
        n_ = scores[(deg + step) % 360]
        denom = p - 2.0 * c + n_
        if abs(denom) < 1e-9:
            return float(deg)
        return (deg + 0.5 * step * (p - n_) / denom) % 360

    tip_deg = _refine(tip_deg_grid)

    # ─ Compute tip_pixel for debug overlay ───────────────────────────────
    tip_rad = math.radians(tip_deg)
    tip_pixel = (
        int(round(cx + INNER_SCAN_MAX * math.cos(tip_rad))),
        int(round(cy - INNER_SCAN_MAX * math.sin(tip_rad))),
    )

    return round(tip_deg, 1), tip_pixel


# ── Strength template matching ───────────────────────────────────────────────

def _grayscale_crop(img: Image.Image) -> tuple:
    """Extract the digit crop as a flat tuple of raw grayscale values (0–255)."""
    crop = img.crop((OCR_X0, OCR_Y0, OCR_X1, OCR_Y1)).convert("L")
    w, h = crop.size
    px = crop.load()
    return tuple(px[x, y] for y in range(h) for x in range(w))


def _grayscale_crop_shifted(img: Image.Image, dx: int, dy: int) -> tuple:
    """Extract the digit crop shifted by (dx, dy) pixels."""
    crop = img.crop((OCR_X0 + dx, OCR_Y0 + dy, OCR_X1 + dx, OCR_Y1 + dy)).convert("L")
    w, h = crop.size
    px = crop.load()
    return tuple(px[x, y] for y in range(h) for x in range(w))


@functools.lru_cache(maxsize=1)
def _load_strength_templates() -> dict:
    """
    Load all data/XX.png reference images (XX = 00..26) as binary templates.
    Cached after first call — restart the process if templates change.
    Returns {value: binary_tuple}.
    """
    templates = {}
    for path in sorted(DATA_DIR.glob("*.png")):
        try:
            val = int(path.stem)
        except ValueError:
            continue
        if not (0 <= val <= 26):
            continue
        try:
            img = Image.open(str(path)).convert("RGB")
            templates[val] = _grayscale_crop(img)
        except Exception:
            continue
    return templates


def detect_strength(img: Image.Image, _debug: bool = False) -> int:
    """
    Match the digit crop against reference templates stored in data/XX.png.

    Returns the integer wind strength (0–26), or -1 if no template is close
    enough (MAE > OCR_MAE_LIMIT).

    Searches all (dx, dy) offsets in {−2..−2}×{-2..+2} (25 positions) and picks
    the offset+template combination with the lowest MAE.  This makes the matcher
    immune to ≤2px positional drift without any manual re-calibration.
    """
    templates = _load_strength_templates()
    if not templates:
        return -1
    try:
        best_val = -1
        best_mae = float("inf")
        best_dx  = 0
        best_dy  = 0
        offsets  = range(-2, 3)  # -2, -1, 0, +1, +2
        for dy in offsets:
            for dx in offsets:
                query = _grayscale_crop_shifted(img, dx, dy)
                n     = len(query)
                for v, t in templates.items():
                    mae = sum(abs(q - tm) for q, tm in zip(query, t)) / n
                    if mae < best_mae:
                        best_mae = mae
                        best_val = v
                        best_dx  = dx
                        best_dy  = dy
        if _debug:
            # Re-run at best offset to collect per-template scores for display.
            query = _grayscale_crop_shifted(img, best_dx, best_dy)
            n     = len(query)
            scores_list = [(sum(abs(q - tm) for q, tm in zip(query, t)) / n, v)
                           for v, t in templates.items()]
            for mae, v in sorted(scores_list)[:5]:
                print(f"  template {v:02d}: MAE={mae:.2f}")
            print(f"  best={best_val}  MAE={best_mae:.2f}  offset=({best_dx:+d},{best_dy:+d})  limit={OCR_MAE_LIMIT}")
        return best_val if best_mae <= OCR_MAE_LIMIT else -1
    except Exception:
        return -1


# ── Wind JSON writer ──────────────────────────────────────────────────────────

def write_wind(strength: int, angle: float, stable: bool = True) -> None:
    """Persist the latest wind reading to WIND_JSON for main.py to consume."""
    data = {"strength": strength, "angle": angle, "stable": stable, "ts": time.time()}
    WIND_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(str(WIND_JSON), "w") as f:
        json.dump(data, f)


class WindBuffer:
    """
    Rolling buffer that accumulates raw per-frame readings and produces stable
    consensus values via majority voting (strength) and circular mean (angle).

    Usage:
        buf = WindBuffer()
        buf.push(raw_strength, raw_angle)
        if buf.full:
            s = buf.stable_strength()   # int, or -1 if no consensus
            a = buf.stable_angle()      # float degrees
    """

    def __init__(self, size: int = BUFFER_SIZE) -> None:
        self._size = size
        self._strengths: deque = deque(maxlen=size)
        self._angles: deque = deque(maxlen=size)

    @property
    def full(self) -> bool:
        return len(self._strengths) == self._size

    def push(self, strength: int, angle: float) -> None:
        self._strengths.append(strength)
        self._angles.append(angle)

    def clear(self) -> None:
        """Discard all buffered readings (call when camera motion is detected)."""
        self._strengths.clear()
        self._angles.clear()

    def stable_strength(self, min_fraction: float = 0.6) -> int:
        """
        Return the most common valid (≥0) strength if it appears in at least
        `min_fraction` of the buffered readings, otherwise -1.
        """
        valid = [s for s in self._strengths if s >= 0]
        if not valid:
            return -1
        mode_val, mode_count = Counter(valid).most_common(1)[0]
        return mode_val if mode_count / len(valid) >= min_fraction else -1

    def stable_angle(self) -> float:
        """Circular mean of buffered angles, with single-pass outlier trimming.

        Computes a provisional mean, discards any angle further than
        ANGLE_OUTLIER_THRESHOLD degrees from it, then returns the final mean.
        Falls back to all angles if the trimmed set would be empty.
        """
        angles = list(self._angles)
        provisional = _circular_mean(angles)
        kept = [a for a in angles if _angular_dist(a, provisional) <= ANGLE_OUTLIER_THRESHOLD]
        if not kept:
            kept = angles  # safety fallback
        return round(_circular_mean(kept), 1)

# ── Motion detection ──────────────────────────────────────────────────────────

def _build_background_mask() -> list[tuple[int, int]]:
    """Return all pixel coords in the capture region that lie outside the disc.

    The returned list is constant for fixed ROSE_* and SCAN_RADIUS values.
    Call once at startup and pass the result to detect_motion() each frame.
    """
    cx, cy = ROSE_CENTER_X, ROSE_CENTER_Y
    mask = []
    for y in range(ROSE_CAPTURE_H):
        for x in range(ROSE_CAPTURE_W):
            if math.sqrt((x - cx) ** 2 + (y - cy) ** 2) > SCAN_RADIUS:
                mask.append((x, y))
    return mask


def detect_motion(
    prev: Image.Image,
    curr: Image.Image,
    bg_mask: list[tuple[int, int]],
) -> bool:
    """Return True if the background zone changed significantly between frames.

    Computes the mean absolute pixel difference per channel (MAD) across all
    background-zone pixels.  A MAD above MOTION_PIXEL_THRESHOLD indicates
    camera movement.

    Parameters
    ----------
    prev : PIL Image (RGB) — previous captured frame
    curr : PIL Image (RGB) — current captured frame
    bg_mask : precomputed list of (x, y) coords outside the disc
    """
    pp = prev.load()
    cp = curr.load()
    total = 0
    for x, y in bg_mask:
        r1, g1, b1 = pp[x, y]
        r2, g2, b2 = cp[x, y]
        total += abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
    mad = total / (3 * len(bg_mask))
    return mad > MOTION_PIXEL_THRESHOLD


def _annotate_debug(img: Image.Image, angle: float, tip_pixel: tuple[int, int] | None) -> Image.Image:
    """Return an annotated copy of img showing the scan boundary, OCR box, and detected tip."""
    debug = img.copy()
    draw = ImageDraw.Draw(debug)
    r = SCAN_RADIUS
    cx, cy = ROSE_CENTER_X, ROSE_CENTER_Y

    # Scan boundary circle (red) at disc inner edge
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 0, 0))
    # Inner scan zone boundary (dim red)
    ri = INNER_SCAN_MIN
    draw.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], outline=(180, 0, 0))
    # Rose center dot (red)
    draw.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=(255, 0, 0))
    # OCR crop box (green)
    draw.rectangle([OCR_X0, OCR_Y0, OCR_X1, OCR_Y1], outline=(0, 255, 0))

    if tip_pixel is not None:
        tx, ty = tip_pixel
        # Line from center to tip (yellow)
        draw.line([cx, cy, tx, ty], fill=(255, 255, 0), width=2)
        # Dot at tip (yellow)
        draw.ellipse([tx - 3, ty - 3, tx + 3, ty + 3], fill=(255, 255, 0))

    return debug


def run_capture(n: int) -> None:
    """
    Capture the current rose frame and save it as data/{n:02d}.png.

    Use this to re-capture a template while the game shows wind strength N.
    Overwrites any existing template for that value and invalidates the cache.
    """
    if not HAS_MSS:
        print("ERROR: mss not installed.  pip install mss")
        return
    if not (0 <= n <= 26):
        print(f"ERROR: strength must be 0–26, got {n}")
        return

    with mss.mss() as sct:
        img = capture_rose(sct)

    path = DATA_DIR / f"{n:02d}.png"
    img.save(str(path))
    _load_strength_templates.cache_clear()

    detected = detect_strength(img, _debug=True)
    status = "✓ matches" if detected == n else f"✗ detected {detected}"
    print(f"Saved {path}  ({status})")
    print("Re-run --test to verify the full template library.")


def run_calibrate() -> None:
    """
    Capture one frame, run detection, annotate it with overlays,
    and save to data/wind_debug.png for visual verification.
    """
    if not HAS_MSS:
        print("ERROR: mss not installed.  pip install mss")
        return

    game_client_origin()  # ensure pywin32 warning is emitted if missing
    with mss.mss() as sct:
        img = capture_rose(sct)

    angle, tip_pixel = detect_direction_shape(img)
    strength = detect_strength(img, _debug=True)
    debug = _annotate_debug(img, angle, tip_pixel)
    debug.save(str(DEBUG_IMG))

    # Save the raw digit crop so its position can be verified visually.
    crop_path = DATA_DIR / "wind_debug_crop.png"
    img.crop((OCR_X0, OCR_Y0, OCR_X1, OCR_Y1)).save(str(crop_path))
    print(f"Digit crop saved → {crop_path}  (should contain only the wind number)")

    print(f"Detected  →  strength={strength}  angle={angle:.1f}°")
    print(f"Debug image saved → {DEBUG_IMG}")
    print("  Red circle  : outer scan boundary (SCAN_RADIUS)")
    print("  Dim circle  : inner scan min boundary (INNER_SCAN_MIN)")
    print("  Green box   : strength digit crop region")
    print("  Yellow line : detected needle direction")
    print(f"  Capture region: screen ({ROSE_CLIENT_X}, {ROSE_CLIENT_Y}) size {ROSE_CAPTURE_W}×{ROSE_CAPTURE_H}")


# ── Offline test ─────────────────────────────────────────────────────────────

def run_test() -> None:
    """
    Self-test: load every template from data/XX.png and verify detect_strength
    returns the correct value (MAE should be ~0 on a self-match).
    Also tests any wind*.png images found in data/ as live examples.
    """
    templates = _load_strength_templates()
    if not templates:
        print(f"ERROR: no templates found in {DATA_DIR}")
        return

    print(f"Strength templates loaded: {len(templates)}  (from {DATA_DIR})\n")

    # ── Self-test: every template must recognise itself ────────────────────────
    print("Self-test (each template image → must return its own value):")
    n_pass = n_fail = 0
    for v in sorted(templates):
        path = DATA_DIR / f"{v:02d}.png"
        img  = Image.open(str(path)).convert("RGB")
        got  = detect_strength(img)
        if got == v:
            n_pass += 1
        else:
            n_fail += 1
            print(f"  FAIL  {path.name}: expected {v}, got {got}")
            detect_strength(img, _debug=True)
    if n_fail == 0:
        print(f"  All {n_pass} templates ✓\n")
    else:
        print(f"  {n_pass} passed, {n_fail} FAILED\n")

    # ── Live examples: any wind*.png in data/ (excluding debug images) ────────
    test_images = sorted(p for p in DATA_DIR.glob("wind*.png") if "_debug" not in p.name)
    if not test_images:
        return
    print("Live test images:")
    for img_path in test_images:
        img = Image.open(str(img_path)).convert("RGB")
        angle, tip_pixel = detect_direction_shape(img)
        strength = detect_strength(img, _debug=True)
        print(f"  {img_path.name}: strength={strength}  angle={angle:.1f}°")
        debug_path = DATA_DIR / f"wind_debug_{img_path.stem}.png"
        _annotate_debug(img, angle, tip_pixel).save(str(debug_path))
    print(f"  Debug images saved to {DATA_DIR}")


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_reader() -> None:
    if not HAS_MSS:
        print("ERROR: mss not installed.  pip install mss")
        sys.exit(1)

    print(f"Wind reader started  →  {WIND_JSON}")
    n = len(_load_strength_templates())
    if n == 0:
        print("WARNING: no strength templates found in data/.")
        print("         Add data/00.png, data/01.png … data/26.png as reference images.")
    else:
        print(f"Loaded {n} strength templates from {DATA_DIR}")
    if not HAS_PYWIN32:
        print("WARNING: pywin32 not found — using absolute screen coordinates.")
        print("         Install: pip install pywin32")
    print("Ctrl+C to stop.\n")

    buf = WindBuffer()
    bg_mask = _build_background_mask()
    prev_frame: Image.Image | None = None
    last_stable: dict = {"strength": -1, "angle": 0.0}

    with mss.mss() as sct:
        while True:
            try:
                img = capture_rose(sct)

                # ── Motion detection gate ──────────────────────────────────
                if prev_frame is not None and detect_motion(prev_frame, img, bg_mask):
                    buf.clear()
                    write_wind(last_stable["strength"], last_stable["angle"], stable=False)
                    print(
                        f"\r[MOTION]  last: {last_stable['strength']:>3} @"
                        f" {last_stable['angle']:>6.1f}°    ",
                        end="", flush=True,
                    )
                    prev_frame = img
                    time.sleep(POLL_INTERVAL)
                    continue

                raw_angle, _ = detect_direction_shape(img)
                raw_strength = detect_strength(img)
                buf.push(raw_strength, raw_angle)
                if buf.full:
                    strength = buf.stable_strength()
                    angle    = buf.stable_angle()
                    stable   = strength >= 0
                    if stable:
                        last_stable = {"strength": strength, "angle": angle}
                    write_wind(strength, angle, stable=stable)
                    print(
                        f"\rWind: {strength:>3} @ {angle:>6.1f}°"
                        f"  [raw {raw_strength} / {raw_angle:.1f}°]    ",
                        end="", flush=True,
                    )
                else:
                    remaining = BUFFER_SIZE - len(buf._strengths)
                    print(
                        f"\rBuffering… ({remaining} frames left)   ",
                        end="", flush=True,
                    )
                prev_frame = img
            except Exception as exc:
                print(f"\n[error] {exc}")
            time.sleep(POLL_INTERVAL)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="GunBound wind rose reader")
    parser.add_argument(
        "--calibrate", action="store_true",
        help="Capture one frame, save annotated debug image, then exit.",
    )
    parser.add_argument(
        "--test", action="store_true",
        help="Run detection on assets/wind.png and print the result (no game needed).",
    )
    parser.add_argument(
        "--capture", type=int, metavar="N",
        help="Capture current rose frame and save as data/NN.png template, then exit. "
             "Use while the game shows wind strength N (0–26).",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Capture one frame, print MAE scores for all templates, save debug image.",
    )
    args = parser.parse_args()

    if args.capture is not None:
        run_capture(args.capture)
    elif args.calibrate or args.debug:
        run_calibrate()
    elif args.test:
        run_test()
    else:
        run_reader()


if __name__ == "__main__":
    main()
