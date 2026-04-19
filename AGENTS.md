# AGENTS.md — Project Navigation for AI Agents

Start here. This file tells you what the project does, where everything lives, what is already done, and what the rules are before you touch anything.

---

## What this project is

A shot calculator for **GunBound Classic**. Given a target distance (SD), wind, and height difference, it suggests angle + power combinations. It improves over time by learning from real in-game results via a calibration loop.

---

## File map

| File | Purpose |
|---|---|
| `calc.py` | **Main file.** Physics simulation, solver, calibration, training mode, data-confidence layer. All core logic lives here. |
| `mobiles.json` | Per-mobile calibrated physics parameters (v_scale, wind coefficients), split by distance band. Written by calibration. |
| `training_data.json` | All recorded shots. Grows over time. Never delete entries manually. |
| `import_baseline.py` | Bulk-imports known reference shots into `training_data.json`. |
| `ruler.py` | Transparent on-screen ruler overlay for reading SD from the game window. |
| `gen_ruler.py` | Generates `ruler.png` (run once, or after changing ruler config). |
| `ruler.png` | Pre-rendered ruler image loaded by `ruler.py`. |
| `physics.md` | Full documentation of the physics model, equations, parameters, and known limitations. **Read this before touching physics or calibration code.** |
| `next_steps.md` | Pending work items with file/function pointers. Check here before starting any new task. |
| `README.md` | User-facing documentation: how to run, input reference, wind convention, calibration cycle. |
| `calibration.json` | Legacy / scratch file. Not used by `calc.py`. |
| `calc.md` | Legacy notes. Not authoritative. |

---

## Key functions in `calc.py`

| Function | What it does |
|---|---|
| `simulate_shot(angle, power, cfg, wind_strength, wind_angle, height_diff)` | Core physics. Returns final x (= SD). |
| `wind_components(W, theta)` | Decomposes wind into `(wx, wy)`. θ=0 is straight up, θ=90 is toward enemy. |
| `get_effective_cfg(mobile_cfg, sd)` | Returns merged config dict (gravity + band coefficients) for the band matching `sd`. |
| `solve_shot_physics_multi(...)` | Coarse→refine solver. Returns physics-only `ShotResult` list. |
| `suggest_shots(...)` | **Primary entry point for suggestions.** Data-matched results first, physics fills remainder. |
| `find_similar_shots(...)` | Scans training data by `d_sim` proximity metric. |
| `cluster_training_matches(close_matches)` | Groups close matches into angle/power clusters with spread stats. |
| `_compute_residual_correction(...)` | Mean signed error over nearby training shots. Applied as target offset. |
| `calibrate_mobile(data)` | Random search over (v_scale, wind_x_coeff, wind_y_coeff) for a single band dataset. |
| `recalibrate_all(mobiles, training_data)` | Iterates all mobiles × bands, calls `calibrate_mobile`, writes `mobiles.json`. |
| `training_mode()` | CLI loop for manual shot entry. Invoked via `python calc.py --training`. |
| `main()` | Normal calculator loop. Calls `suggest_shots()` and optionally records results. |

---

## Data schemas

### `training_data.json` entry
```json
{
  "mobile": "armor",
  "angle": 70,
  "power": 2.5,
  "wind_strength": 10,
  "wind_angle": 45,
  "height_diff": 0.0,
  "actual_sd": 0.87
}
```

### `mobiles.json` entry
```json
{
  "armor": {
    "base_angle": 70,
    "gravity": 9.8,
    "bands": {
      "short": { "v_scale": 1.15, "wind_x_coeff": 0.10, "wind_y_coeff": 0.37 },
      "mid":   { "v_scale": 1.20, "wind_x_coeff": 0.87, "wind_y_coeff": 0.43 },
      "long":  { "v_scale": 1.05, "wind_x_coeff": 0.80, "wind_y_coeff": 0.40 }
    }
  }
}
```

---

## Constants worth knowing

All in `calc.py`, near the top of the physics section:

| Constant | Value | Meaning |
|---|---|---|
| `STRONG_WIND_THRESHOLD` | 14 | Wind bars above which high angles are capped |
| `STRONG_WIND_ANGLE_MAX` | 72 | Max angle when strong wind + mid/long band |
| `HIGH_ANGLE_SD_TOL` | 0.15 | SD proximity to override the angle cap from training data |
| `MATCH_CLOSE_THRESHOLD` | 0.08 | `d_sim` below this → direct data suggestion |
| `MATCH_LOOSE_THRESHOLD` | 0.15 | `d_sim` below this → residual correction only |

---

## Wind angle convention

- **0°** — straight up (no horizontal effect)
- **1 - 179°** — toward enemy (pushes projectile forward)
- **-1 - -179°** — against enemy (pushes projectile backward)
- **180° / −180°** — straight down (shortens range)
- Negative angles → away from enemy side

---

## Rules before making changes

1. **Read `physics.md`** before touching `simulate_shot`, `wind_components`, or calibration.
2. **Read `next_steps.md`** before starting any new feature — it lists pending work with exact file/function pointers.
3. **Do not clear `training_data.json`** — entries are cumulative and irreplaceable without re-playing.
4. **Do not add `time_scale` as a fitted parameter** — it is degenerate with `wind_x_coeff`. See `physics.md` §6.
5. **Do not replace the solver with static charts** — GunBound physics is nonlinear; charts break at non-standard wind/height.
6. **`suggest_shots()` is the public API**, not `solve_shot_physics_multi()`. Call `suggest_shots()` from `main()` and any new entry points.
7. After editing `calc.py`, verify with: `python calc.py` → armor → SD 0.5 → wind 0 → angle 0. Should suggest power ≈ 1.9, err < 0.02 SD.

---

## How to run

```bash
python calc.py                 # normal calculator
python calc.py --training      # manual shot recording mode
python import_baseline.py      # bulk import reference shots
python ruler.py                # on-screen SD ruler overlay
python gen_ruler.py            # regenerate ruler.png (run after ruler config changes)
```
