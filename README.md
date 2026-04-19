# GunBound Classic Shot Calculator

A physics-simulation + self-learning shot calculator for GunBound Classic. Given the current wind and distance, it suggests angle/power combinations, learns from your real landing results, and refines its model over time.

---

## Quick Start

```
python calc.py
```

To record known shots without the solver (e.g. from a reference table):

```
python calc.py --training
```

For the on-screen ruler, see [Ruler Overlay](#ruler-overlay) below.

---

You will be prompted step by step:

```
Available mobiles: ['ice', 'armor']
Select mobile: ice
SD (screen distance): 1.0
Wind strength (0-26): 10
Wind angle (-180 to 180): 45
Height diff (-2 to 2, default 0): 0

Suggested shots:
1) Angle: 72°, Power: 3.4
2) Angle: 43°, Power: 2.65
3) Angle: 69°, Power: 3.2

Which shot did you use? (1-3 or skip): 1
Where did it land (SD)? 0.95
Shot recorded.

Another shot? (y/n):
```

Every 10 recorded shots the model recalibrates automatically.

---

## Training Mode

Run with `--training` to record shots directly into `training_data.json` without going through the solver. Useful for seeding the model with known reference data (e.g. a no-wind distance table) before you start playing.

```
python calc.py --training
```

You will be prompted for:

| Field | Description |
|---|---|
| `mobile` | Mobile name (selected once per session) |
| `angle` | The angle you fired at |
| `power` | The power level used |
| `wind_strength` | Wind bar value |
| `wind_angle` | Wind direction in degrees |
| `height_diff` | Vertical offset (default 0) |
| `actual_sd` | Where the shot actually landed (SD) |

After you exit the loop, calibration runs automatically on all accumulated data.

> **Tip:** Use `import_baseline.py` to bulk-import a full reference table at once instead of entering shots one by one.

---

## Input Reference

| Field | Range | Description |
|---|---|---|
| `mobile` | `ice`, `armor` | The mobile (tank) you are using |
| `sd` | > 0 | Screen Distance to the target |
| `wind_strength` | 0 – 26 | Wind bar value shown in-game |
| `wind_angle` | -180 – 180 | Wind direction in degrees (see below) |
| `height_diff` | -2 – 2 | Vertical offset: positive = target is higher, negative = lower. Default 0 |

### Wind angle convention

The model's x-axis points **toward the enemy**. Wind angle is defined relative to that axis:

```
       0° = straight up    (wind has no horizontal effect)
      90° = toward enemy   (wind pushes projectile toward the enemy)
     -90° = away from enemy(wind pushes projectile away from the enemy)
  ±180°  = straight down   (wind has no horizontal effect)
```

> **If the enemy is to the right:** enter the wind angle exactly as shown on the in-game compass.
> **If the enemy is to the left:** negate the horizontal component — flip the sign of the angle (e.g. compass shows 90°, enter -90°; compass shows -45°, enter 45°). Purely vertical wind (0° or ±180°) does not need negation.

---

## How It Works

### 1. Physics simulation — `simulate_shot()`

**Initial velocity** (SD/s units):
$$v_x^0 = p \cdot s \cdot \cos\alpha, \quad v_y^0 = p \cdot s \cdot \sin\alpha$$
where $p$ = power, $s$ = `v_scale`, $\alpha$ = launch angle.

**Wind decomposition** (θ = 0° is straight up, 90° is toward enemy):
$$w_x = W \sin\theta, \quad w_y = W \cos\theta$$

**Euler integration** (dt = 0.05, up to 1000 steps, stop when y ≤ 0):
```
vx += wx * wind_x_coeff * dt
vy += wy * wind_y_coeff * dt
x  += vx * dt
y  += vy * dt
vy -= gravity * dt
```

Wind is a **continuous per-step force**, not a one-time impulse — so shots with longer flight times are deflected more, matching real GunBound behaviour. Returns final `x` (= SD).

---

### 2. Solver — `solve_shot_physics_multi()`

Two-pass coarse→refine search (~4 ms):

**Coarse pass** — simulate all combinations:
- Angles: 20°, 25°, …, 85° (step 5°)
- Power: 0.5, 0.75, …, 6.0 (step 0.25)
- Select the best result per 10° angle bin as seeds (ensures diverse angle coverage)

**Refine pass** — around each seed:
- Angles: seed ± 6° (step 1°)
- Power: seed ± 0.3 (step 0.02)

**Candidate selection** — from all refine results, take up to 3 shots satisfying:
$$|\text{angle}_i - \text{angle}_j| \geq 3° \quad \text{and} \quad \text{err} \leq \text{best\_err} + 0.05 \text{ SD}$$

The 0.05 SD cutoff ensures all suggestions are genuinely close to optimal, not just the closest-angle neighbours.

The coefficients used are chosen from the **distance band** matching the target SD (see below).

---

### 3. Distance bands

Physics behaviour varies significantly with range. The model maintains **separate coefficients per band**:

| Band | SD range |
|---|---|
| `short` | 0 – 0.75 |
| `mid` | 0.75 – 1.25 |
| `long` | > 1.25 |

`get_band_name(sd)` returns the band name for a given SD.
`get_effective_cfg(mobile_cfg, sd)` returns the merged config dict (gravity + band coefficients) ready to pass into `simulate_shot()`.

---

### 4. Calibration — `calibrate_mobile()` / `recalibrate_all()`

After every 10 recorded shots, `recalibrate_all()` runs automatically. For each mobile and each distance band it:

1. Filters `training_data.json` to shots in that band. Skips bands with < 3 samples.
2. Optimises parameters $\boldsymbol{\theta} = (s, c_x, c_y)$ (v_scale, wind_x_coeff, wind_y_coeff) by minimising a **distance-weighted least-squares loss**:

$$\mathcal{L}(\boldsymbol{\theta}) = \sum_{i} \frac{(\hat{x}_i(\boldsymbol{\theta}) - x_i)^2}{1 + |x_i|}$$

   where $\hat{x}_i$ = `simulate_shot(...)` output, $x_i$ = recorded `actual_sd`. The denominator down-weights longer shots (higher absolute SD), which have more measurement noise.

3. Search method: **random search**, 3000 iterations, uniform sampling over:
   - $s$ ∈ [0.85, 1.20], $c_x$ ∈ [0.1, 2.0], $c_y$ ∈ [0.05, 1.0]

4. Writes the best $\boldsymbol{\theta}$ back to `mobiles.json` immediately.

---

## Data Files

| File | Purpose |
|---|---|
| `mobiles.json` | Per-mobile physics parameters, split by distance band. **This is the source of truth for the model** — calibration writes here. |
| `training_data.json` | All recorded shots. Each entry stores the full scenario + actual landing SD. Grows over time. |

### `mobiles.json` structure

```json
{
  "ice": {
    "base_angle": 70,
    "gravity": 9.8,
    "bands": {
      "short": { "v_scale": 1.0, "wind_x_coeff": 0.8, "wind_y_coeff": 0.4 },
      "mid":   { "v_scale": 1.0, "wind_x_coeff": 0.8, "wind_y_coeff": 0.4 },
      "long":  { "v_scale": 1.0, "wind_x_coeff": 0.8, "wind_y_coeff": 0.4 }
    }
  }
}
```

### `training_data.json` entry structure

```json
{
  "mobile": "ice",
  "angle": 72,
  "power": 3.4,
  "wind_strength": 10,
  "wind_angle": 45,
  "height_diff": 0.0,
  "actual_sd": 0.95
}
```

---

## Adding a New Mobile

Add an entry to `mobiles.json` following the same structure. Start with `v_scale = 1.0` and the default wind coefficients — the model will calibrate them once you have collected enough shots.

```json
"tank_name": {
  "base_angle": 70,
  "gravity": 9.8,
  "bands": {
    "short": { "v_scale": 1.0, "wind_x_coeff": 0.8, "wind_y_coeff": 0.4 },
    "mid":   { "v_scale": 1.0, "wind_x_coeff": 0.8, "wind_y_coeff": 0.4 },
    "long":  { "v_scale": 1.0, "wind_x_coeff": 0.8, "wind_y_coeff": 0.4 }
  }
}
```

---

## How to Use the Calculator Effectively

### Step 1 — Read your inputs correctly

Before running a query, note down from the game screen:
- **SD:** the number shown on the targeting indicator (distance to target)
- **Wind strength:** the numeric wind value (0–26)
- **Wind angle:** read from the in-game compass. Enter as-is if the enemy is towards teh wind. If the enemy is against it, negate the angle (compass shows 70° → enter -70°). Purely vertical wind (0° or ±180°) never needs negation.
- **Height diff:** estimate positive if the target is higher than you, negative if lower; 0 if roughly flat

### Step 2 — Interpret the 3 suggested shots

The calculator returns 3 shots with at least 3° angular separation. They are all near-optimal solutions — the physics model may not be perfectly calibrated yet, so having alternatives is intentional. Try the first suggestion; if it misses, the other two give you different trajectory options.

### Step 3 — Always record your result

After firing, **always enter the actual landing SD**, even if it was a miss. This is how the model learns. A shot that landed short is just as valuable as a hit — it tells the calibrator that the coefficients need adjusting.

If you skip recording (choose `skip`), no data is collected and the model never improves.

### Step 4 — Understand the calibration cycle

Calibration runs automatically every 10 recorded shots. What happens:

1. All shots are split by distance band (short / mid / long)
2. Each band with ≥ 3 samples is recalibrated independently
3. The new coefficients are written to `mobiles.json` immediately
4. Future queries for that band will use the updated physics

**In the first session**, the model uses default coefficients and suggestions may be off. This is expected — accuracy improves as you feed it real data.

### Step 5 — What to do when shots are consistently wrong

| Symptom | Likely cause | Action |
|---|---|---|
| Always lands short | `v_scale` too low | Keep recording; calibration will raise it |
| Always lands long | `v_scale` too high | Keep recording |
| Wind pushes too much | `wind_x_coeff` too high | Keep recording |
| Wind pushes too little | `wind_x_coeff` too low | Keep recording |
| Short shots OK, long shots off | Band mismatch | Record more long-range shots (> 1.25 SD) |
| Suggestions are random-looking | Too few samples | Need ≥ 3 shots per band before that band calibrates |

### Tips for faster calibration

- **Cover all three bands early.** Try to collect a mix of short (SD < 0.75), mid (0.75–1.25), and long (> 1.25) shots. A band with 0 samples never calibrates.
- **Vary wind conditions.** Shots all recorded with zero wind won't teach the model about wind coefficients.
- **Be consistent with SD reading.** Always read SD the same way from the game screen — inconsistent readings are the main source of noise.
- **Don't record obviously bad inputs.** If you mis-read the wind and the shot landed wildly off, use `skip` rather than recording a corrupted sample.

---

## Ruler Overlay

`ruler.py` is a transparent on-screen ruler you place over the GunBound window to read SD values accurately directly from the game screen.

### Install dependency

```
pip install pywin32
```

### Run

```
python ruler.py
```

The ruler auto-snaps to the GunBound window on startup. A status message appears briefly confirming the position.

### What it shows

| Element | Description |
|---|---|
| Horizontal strip (top) | SD scale 0 → 1.0 across the full width (1600px) |
| Vertical strip (left) | SD scale 0 → 0.75 down the full height (1200px) |
| Major ticks | Every 0.25 SD (every 400px) |
| Minor ticks | Every 0.125 SD (every 200px) |
| Dotted guide lines | Full-screen cross-hairs at every tick |

The background is fully transparent and **click-through** — the game is playable underneath. Only the ruler strips themselves capture input.

### Controls

| Control | Action |
|---|---|
| `R` button (top-right) | Re-snaps to the game window (use if you move the game) |
| `✕` button (top-right) | Closes the ruler |
| `Escape` | Closes the ruler |
| Drag on ruler strip | Manually reposition if auto-snap fails |

### Configuration

At the top of `ruler.py`:

```python
GAME_WINDOW_TITLE = "GunBound"   # substring of the game's taskbar title (case-insensitive)
SCREEN_W = 1600                  # game client area width in pixels
SCREEN_H = 1200                  # game client area height in pixels
```

If the ruler does not snap automatically, check the exact window title in the Windows taskbar and update `GAME_WINDOW_TITLE` accordingly.

### Reading SD from the ruler

The ruler's x-axis starts at x=0 of the game's client area — which corresponds to SD=0 (your character's position, at the left edge of the game). Read the target's horizontal position on the ruler and enter it as the `sd` input in `calc.py`.

If the enemy is to the **left**, remember to negate the wind angle (see [Wind angle convention](#wind-angle-convention)).

---

## Known Limitations

- Physics model has no drag or spin — accuracy depends entirely on learned coefficients.
- Wind effect is linear; real GunBound wind has nonlinear behaviour at extreme angles.
- Calibration is global per band, not angle-specific.
- Solver uses coarse→refine search (~4 ms per query).
- No outlier rejection: one badly recorded shot can skew a band's calibration.
