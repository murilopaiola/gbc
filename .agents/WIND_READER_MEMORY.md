# WIND_READER_MEMORY.md — GunBound Wind Rose Reader

Last updated: 2026-04-19 (initial implementation — radial scoring algorithm working)

---

## Purpose

`tools/wind_reader.py` reads the GunBound wind rose UI element in real time and writes
`data/wind.json` so `main.py` can pre-fill wind input without manual entry.

Extracts:
- **Strength** (0–26, integer) — OCR of the center digit
- **Direction** (0–360°, 0=East/right, CCW) — shape-based needle detection

---

## File Layout

```
tools/wind_reader.py     — main script (all logic here)
assets/wind.png          — reference image: white needle, strength≈0, angle≈234°
assets/wind2.png         — reference image: yellow needle, strength=21, angle≈8°
assets/wind3.png         — reference image: needle pointing up/north, angle≈84°
data/wind.json           — output written continuously while running
data/wind_debug_*.png    — annotated debug images written by --test / --calibrate
```

---

## Capture Region (2560×1440 monitor)

| Constant | Value | Notes |
|---|---|---|
| `ROSE_CLIENT_X` | 1230 | Absolute screen X of top-left of capture box |
| `ROSE_CLIENT_Y` | 277 | Absolute screen Y |
| `ROSE_CAPTURE_W` | 109 | Width (1339 − 1230) |
| `ROSE_CAPTURE_H` | 109 | Height (386 − 277) |
| `ROSE_CENTER_X` | 53 | Rose center X within captured region |
| `ROSE_CENTER_Y` | 55 | Rose center Y within captured region |

Disc edge: left≈13, right≈92, top≈15, bottom≈94 → inner disc radius ≈39 px from center.

The three needle corners (all three: forward tip + 2 rear ends) sit at r≈43–48 px
from center, **outside** the disc boundary. They are in the decorative outer bezel zone.

---

## Needle Geometry

The needle is a **V-shaped arrowhead**. Three distinct bright "corners" are visible:
- **1 forward tip** — the apex of the V, points in the wind direction
- **2 rear ends** — the tail prongs of the V, ~90° apart from each other

Angular relationships (approximate):
- Rear ends are ~90° apart from each other
- Forward tip is ~135° away from each rear end
- This geometry holds regardless of needle color or wind direction

### Needle colors by strength
- Strength 0–1 : white/light gray
- Strength ~5–10 : light yellow
- Strength ~15–21 : saturated yellow-orange
- Strength ~22–26 : orange/red

---

## What Does NOT Work (failed approaches)

### 1. Brightness arc scan on SCAN_RADIUS ring (original approach)
- Sampled brightness at evenly-spaced points on a ring of r=36
- **Failed** because: (a) SCAN_RADIUS=36 didn't reach the actual corners (r=43–48),
  and (b) different needle colors have different brightness — what's "brightest" shifts.

### 2. Pixel brightness threshold in outer annulus (r=36–50)
- Looked for max(R,G,B) > 120 in the outer zone
- **Failed** because: the outer zone (r=36–50) contains fixed compass structural features
  (bezel tabs, compass points) that appear as constant bright clusters at the SAME angles
  in every frame, regardless of needle direction. These drown out the needle entirely.
- Confirmed: at r=36–50, the same 4 cluster means (≈8°, ≈120°, ≈228°, ≈316°) appear
  in BOTH reference images — they are structural, not the needle.

### 3. Inner annulus pixel clustering (r=18–50, MIN_ANNULUS_R=18)
- Collected all bright pixels, clustered by angle, found the most-isolated cluster
- **Failed** because: (a) the disc interior is NOT uniformly dark — it's a textured
  medium-gray, max(R,G,B)≈120–190 everywhere. The threshold of 120 matched the whole
  disc, creating 1000+ candidates with a single merged cluster spanning all angles.

---

## What Works — Final Algorithm

### Inner-disc radial scoring (r=15–38)

**Key insight**: The disc interior IS a textured medium-gray background, but the needle
ARMS add extra brightness along the radials they cross. By scoring each direction by
how much total brightness × warmth accumulates along the radial, the three arm directions
emerge as local peaks even against the noisy background.

**Score formula for angle θ:**
```
score(θ) = Σ_{r=15}^{38}  max(maxRGB(x,y) – BRIGHT_BASE, 0)
                           × (1 + max(R–B, 0) / WARM_FACTOR)
```
where (x,y) = (cx + r·cos θ, cy − r·sin θ)

- `BRIGHT_BASE = 80`: ignores dark pixels; disc background max≈50–70 contributes little
- `WARM_FACTOR = 40.0`: R−B=40 doubles the weight; rewards yellow/orange needles without
  penalising white needles (which have R−B≈0 but high raw brightness)

**Peak finding:**
1. Score every 3° (0–357°)
2. Find local maxima (score ≥ both ±1 and ±2 neighbors)
3. Keep separated peaks (>30°) scoring ≥15% of the maximum peak; up to 5 peaks

**Tip selection:**
- If ≥3 peaks: take the top 3 by score — these are the 3 needle arms
- Find the closest pair (angular distance) = the 2 rear ends (~90° apart)
- The remaining peak = forward tip

**Fallback:**
- If <3 peaks: return the highest-scoring peak

### Verified results on reference images

| Image | Expected | Detected | Error |
|---|---|---|---|
| wind.png (white, str≈0) | ≈234° | 234.0° | 0° |
| wind2.png (yellow, str=21) | ≈8° | 9.0° | 1° |
| wind3.png (needle up/north) | ≈84° | 84.0° | 0° |

---

## Constants (current, tuned values)

| Constant | Value | Purpose |
|---|---|---|
| `SCAN_RADIUS` | 42 | Debug overlay circle radius only (not used in detection) |
| `INNER_SCAN_MIN` | 15 | Inner boundary of radial scan (skip center digit) |
| `INNER_SCAN_MAX` | 38 | Outer boundary of radial scan (just inside bezel) |
| `SCAN_STEP_DEG` | 3 | Angular resolution of sweep |
| `NEEDLE_BRIGHT_BASE` | 80 | Brightness baseline; pixels below this ignored |
| `NEEDLE_WARM_FACTOR` | 40.0 | R−B normalization for yellow/warm needles |
| `MIN_PEAK_SEP_DEG` | 30 | Min angular gap between distinct peaks |
| `OCR_X0, OCR_Y0` | 32, 36 | OCR crop top-left (relative to captured region) |
| `OCR_X1, OCR_Y1` | 73, 71 | OCR crop bottom-right (41×35 px region) |
| `POLL_INTERVAL` | 0.3 s | Live polling interval |

---

## Known Reference Pixel Values (from diagnostic)

### wind.png (white needle, str≈0, angle≈234°)
- Forward tip (26, 89): r=43.4px, ang=231.5°, RGB=(123,134,132), max=134
- Rear end 1  (45,  9): r=46.7px, ang=99.9°,  RGB=(140,146,148), max=148
- Rear end 2  (94, 43): r=42.7px, ang=16.3°,  RGB=(115,125,123), max=125
- Disc interior at r≈25: max≈170–190 (bright textured background)

### wind2.png (yellow needle, str=21, angle≈8°)
- Forward tip (98, 48): r=45.5px, ang=8.8°,   RGB=(115,109,90),  max=115, R-B=25
- Rear end 1  (13, 28): r=48.3px, ang=146.0°, RGB=(114,112,99),  max=114, R-B=15
- Rear end 2  (26, 95): r=48.3px, ang=236.0°, RGB=(115,101,90),  max=115, R-B=25
- Disc interior at r≈15: max≈170+ (warm beige textured background — NOT dark)

---

## Angle Convention

- **0°** = East/right
- **90°** = Up (standard math, CCW positive)
- **180°** = West/left
- **270°** = Down

Conversion from screen coordinates:
```python
angle = math.degrees(math.atan2(-(y - cy), x - cx)) % 360
```
(screen y grows downward, so negate dy for standard CCW)

**Downstream conversion to GunBound game convention** (0=up, ±180=down, ±90=sideways)
is NOT done in wind_reader.py — it must be handled in main.py when consuming wind.json.

---

## OCR (Strength Detection)

- Crops the center digit region (32,36)→(73,71) = 41×35 px
- Upscales 4× with NEAREST resampling
- Converts to grayscale, thresholds at 150 (cream digits on darker background)
- Tesseract `--psm 8 --oem 3` with whitelist `0123456789`
- Returns int 0–26, or -1 if Tesseract not installed / OCR fails

**Status**: Strength OCR worked from the beginning and has NOT been changed.
Requires: `pip install pytesseract` + Tesseract binary installed separately.

---

## Output: data/wind.json

```json
{
  "strength": 21,
  "angle": 9.0,
  "ts": 1745123456.789
}
```

- `strength`: integer 0–26, or -1 if Tesseract not available
- `angle`: float 0–360° (East=0, CCW)
- `ts`: Unix timestamp of last successful read

---

## Usage

```bash
python tools/wind_reader.py               # live polling → writes data/wind.json
python tools/wind_reader.py --test        # run on assets/wind*.png, saves debug images
python tools/wind_reader.py --calibrate   # capture one frame from game, save debug image
```

**--test** produces `data/wind_debug_wind.png` and `data/wind_debug_wind2.png`.
**Debug image overlays:**
- Red circle: SCAN_RADIUS boundary (disc inner edge reference)
- Dim red circle: INNER_SCAN_MIN inner boundary
- Green box: OCR crop region
- Yellow line + dot: detected tip direction and endpoint

---

## Dependencies

| Package | Required for | Install |
|---|---|---|
| `Pillow` | All image operations | Always installed (in requirements.txt) |
| `mss` | Live screen capture | `pip install mss` |
| `pytesseract` | OCR strength number | `pip install pytesseract` + Tesseract binary |
| `pywin32` | Window-relative coords | `pip install pywin32` (optional — falls back to absolute coords) |

**All imports are optional** (guarded with `try/except`). The script runs in `--test` mode
with only `Pillow` installed.

---

## Known Issues / TODOs

### 1. [PENDING] Angle convention conversion in main.py
`wind_reader.py` outputs 0°=East CCW. GunBound `main.py` uses 0°=up, ±180°=down,
+90=toward enemy, −90=away. Conversion must be added when integrating wind.json reading
into `cli.py`. Formula (approximate, assumes enemy is to the right):
```python
game_angle = (90 - wind_reader_angle) % 360  # converts East-CCW to North-CW
# then map to ±180 range
if game_angle > 180: game_angle -= 360
```

### 2. [PENDING] Live integration with main.py / cli.py
`main.py` does not yet read `data/wind.json`. The wind reader runs independently.
Integration would pre-fill wind prompt with last-read values (from wind.json).

### 3. [PENDING] Multi-monitor / window-relative coordinate support
`ROSE_CLIENT_X/Y` are absolute screen coordinates calibrated for a 2560×1440 monitor.
On other resolutions or with the game window moved, these will be wrong.
`pywin32` support is present but only used for `game_client_origin()` which is not
wired into `capture_rose()` yet (capture still uses absolute coords).

### 4. [PENDING] Fine-tune for more needle color variants
Only 2 reference images tested (white str≈0, yellow str=21). Higher-strength colors
(orange str≈22, red str≈26) not yet verified. Algorithm should handle them via warmth
weighting but needs confirmation with real screenshots.

### 5. [INVESTIGATED — NOT needed] Separate white vs. colored needle handling
White needle (str≈0): R−B≈0, max≈130–148. Yellow (str=21): R−B≈15–25, max≈115–115.
Both correctly detected by the unified radial-scoring formula. No branching needed.

---

## Debugging Insights (what we tried and learned)

- **"Sample brightness on SCAN_RADIUS arc"** → finds the warm bezel tabs, not the needle.
  The outer zone (r≥36) is dominated by fixed structural compass features at ≈8°, 120°,
  228°, 316° — same in every frame.

- **"Find the farthest bright pixel from center"** → finds the decorative tabs in the
  outer zone, same problem.

- **"max(R,G,B) > 100 in r=18–50 annulus"** → the disc interior is NOT uniformly dark.
  max≈120–190 throughout the whole disc interior, so thousands of pixels match the
  threshold and form a single merged cluster covering all 360°.

- **SCAN_RADIUS=36 was too small** — the actual needle corners are at r=43–48 px.
  But fixing radius to 50 only exposed the outer-zone structural problem above.

- **Radial scoring in the INNER disc (r=15–38)** — works! The needle body fills the
  disc interior from center to edge. Even though the disc background is not dark, the
  extra brightness along the needle arm creates clearly taller peaks at the correct
  angles. Tested with warmth weighting (R−B factor) for color-independent operation.

- **15% score threshold for peak filtering** — critical to reject minor background noise
  peaks while keeping all 3 needle arms. If set too high (e.g. 50%), the rear arms
  (which score lower than the tip in some orientations) get dropped.

- **Top-3-by-score for tip selection** — more reliable than taking all peaks above
  threshold, since more than 3 peaks can appear (background structure leaks through).
  By anchoring on the top 3 scores, we always get exactly the 3 needle arms for
  well-formed images.
