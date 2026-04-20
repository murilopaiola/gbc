# PROJECT_MEMORY.md — GunBound Shot Calculator

Last updated: 2026-04-19 (after height_diff fix, POWER_MAX fix, calibration stability fix, dataset expansion to 104 shots; full src/gunbound/ package refactor)

---

## Project Purpose

Shot calculator for GunBound Classic. Input: target SD, wind, height diff. Output: angle + power suggestions. Self-improving via calibration against real in-game shots recorded in `training_data.json`.

---

## Architecture

### Package layout (post-refactor)

| Path | Status | Notes |
|---|---|---|
| `src/gunbound/` | **Active** | Fully modular package; all new work here |
| `legacy/calc_legacy.py` | Reference only | v1 band-based calibration, v_scale bug, kept for comparison |
| `config/mobiles_v2.json` | Written by `--calibrate` | 4 params per mobile: v_scale, power_exp, wind_x_coeff, wind_y_coeff |
| `config/mobiles.json` | v1 reference only | Per-band per-mobile coefficients, v_scale capped at 1.20 |
| `data/training_data.json` | Shared | 104 shots total (Armor: 93, Ice: 11) |

### Data flow (src/gunbound)

```
data/training_data.json
   ↓ calibration.calibrate() [3-phase]
config/mobiles_v2.json
   ↓ matching.suggest_shots()    ← PRIMARY ENTRY POINT
       Tier 1: find_similar_shots → cluster_training_matches → direct data suggestion
       Tier 2: compute_residual_correction → solver.solve() → residual-corrected physics
ShotResult list → printed to user
```

### Data flow (legacy/calc_legacy.py)

```
data/training_data.json
   ↓ recalibrate_all() [random search]
config/mobiles.json
   ↓ suggest_shots() [data-confidence layer + physics solver]
ShotResult list → printed to user
```

---

## Key Modules / Functions

### src/gunbound/physics.py

| Function | Purpose |
|---|---|
| `effective_gravity(mobile)` | g_eff = 9.8 × g_ref_mobile / 73.5 |
| `default_v_scale(mobile, armor_vs)` | Derive v_scale prior: armor_vs × sqrt(g_mobile/g_armor) |
| `wind_components(W, theta_deg)` | Returns `(int(W·sin θ), int(W·cos θ))` — integer truncation before coeff scaling |
| `simulate_shot(angle, power, mobile, v_scale, power_exp, wind_x_coeff, wind_y_coeff, wind_strength, wind_angle_deg, height_diff)` | Euler integration, position-then-velocity order, per-mobile g |

### src/gunbound/calibration.py

| Function | Purpose |
|---|---|
| `_loss(data, mobile, vs, pe, wx, wy)` | Weighted squared error: w = 1/(0.5 + |actual|) |
| `calibrate(data, mobile)` | 3-phase: A=v_scale+power_exp from no-wind, B=wind coeffs, C=joint descent |
| `recalibrate_all(cfg, training_data)` | Calibrates all mobiles with ≥3 shots, saves to config/mobiles_v2.json |
| `validate(cfg, training_data)` | Per-shot error table, MAE, flags >0.05 SD |

### src/gunbound/solver.py

| Function | Purpose |
|---|---|
| `_solve_for_target(...)` | Angle sweep + binary-search power for each angle |
| `solve(target_sd, mobile, cfg, wind_strength, wind_angle_deg, height_diff)` | Coarse (2° step) → refine (1° subset) → dedup → prefer 45–80° range |

### src/gunbound/matching.py

| Function | Purpose |
|---|---|
| `find_similar_shots(training_data, mobile, sd, ...)` | d_sim proximity metric over training data |
| `cluster_training_matches(close_matches)` | Groups by (angle±3°, power±0.1), returns spread stats |
| `compute_residual_correction(similar_shots, cfg, mobile)` | Mean signed error from nearby shots → target offset |
| `suggest_shots(mobiles_cfg, mobile, sd, ...)` | **PRIMARY ENTRY POINT.** Tier 1 = data match, Tier 2 = residual-corrected physics |

### src/gunbound/storage.py

| Symbol | Purpose |
|---|---|
| `PROJECT_ROOT / CONFIG_DIR / DATA_DIR / ASSETS_DIR` | Canonical path constants, resolved at import time |
| `MOBILES_FILE` | `CONFIG_DIR / "mobiles_v2.json"` |
| `TRAINING_FILE` | `DATA_DIR / "training_data.json"` |
| `load_mobiles() / save_mobiles(cfg)` | JSON round-trip for calibration config |
| `load_training() / save_training(data)` | JSON round-trip for training shots |

### src/gunbound/cli.py

| Function | Purpose |
|---|---|
| `training_mode(mobiles_cfg)` | `python main.py --training` — records shots, recalibrates on exit |
| `main()` | Dispatches `--calibrate` / `--validate` / `--training` / interactive loop; auto-recalibrates every 5 shots |

### legacy/calc_legacy.py (v1) — reference only

| Function | Purpose |
|---|---|
| `simulate_shot(angle, power, cfg, ...)` | Core physics, velocity-then-position order |
| `suggest_shots(...)` | Data-matched (d_sim < 0.08) first, physics fills gaps |
| `find_similar_shots(...)` | d_sim proximity metric over training data |
| `cluster_training_matches(...)` | Groups by (angle±3°, power±0.1), returns spread stats |
| `_compute_residual_correction(...)` | Mean signed error from nearby shots → target offset |
| `calibrate_mobile(data)` | Random search **BUG: v_scale range [0.85, 1.20] too narrow** |
| `recalibrate_all(...)` | Per-mobile per-band calibration |

---

## Physics Model (src/gunbound/physics.py)

### Euler integration

```python
v_init = power ** power_exp * v_scale
vx = v_init * cos(angle)
vy = v_init * sin(angle)
wx = int(W * sin(theta)) * wind_x_coeff   # integer truncation FIRST
wy = int(W * cos(theta)) * wind_y_coeff

# each step dt=0.05:
x  += vx * dt    # position FIRST (engine order)
y  += vy * dt
vx += wx * dt
vy += (wy - g_eff) * dt
# stop when vy < 0 AND y <= 0
# linear interpolation at y=0 crossing to remove dt overshoot
```

### Wind convention (both v1 and v2)

- θ = 0° → straight up (no horizontal push)
- θ = 90° → toward enemy (positive x)
- θ = −90° → away from enemy (negative x)
- θ = ±180° → straight down

### Per-mobile gravity (MOBILE_PHYSICS dict)

```
armor=73.5, mage=71.5, ice=62.5, jd=62.5, boomer=62.5, grub=61.0,
jfrog=54.3, dragon=54.3, lightning=65.0, aduka=65.5, knight=65.5,
asate=76.0, turtle=73.5, raon=81.0, trico=84.0, bigfoot=90.0,
kalsiddon=88.5, nak=93.0
```
Anchor: Armor 73.5 → g_eff = 9.8. All others scaled by ratio.

### Calibrated values (current config/mobiles_v2.json, 93 armor / 11 ice shots)

```
armor: v_scale=1.31502  power_exp=0.97071  wind_x=0.09710  wind_y=0.11745
ice:   v_scale=1.2450   power_exp=1.00000  wind_x=0.1000   wind_y=0.1000
```

---

## Known Bugs / Issues

### [MEDIUM — src/gunbound/physics.py] Systematic nonlinearity in no-wind shots (S-curve)

- **Root cause**: Real game power-to-velocity relationship is NOT purely linear (`v ≠ k * power`). The actual exponent fitted from Armor data is ≈ 1.76, not 2.0.
- **Effect**: Mid-range no-wind shots have errors −0.05 to −0.11 SD (undershoot), short/long range are smaller.
- **Pattern**: Armor at 70°:
  - p=0.9–1.35: err ≈ −0.01 to −0.02 SD (small)
  - p=1.6–2.8: err ≈ −0.07 to −0.11 SD (systematic undershoot)
  - p=3.15+: near zero or slight overshoot
- **Mitigation**: Data-confidence layer in `src/gunbound/matching.py` overrides with direct training lookup for these shots.
- **Possible fix**: Add power exponent `n` as a fitted parameter: `v = v_scale * power^n`. Risk: may overfit short Armor series.

### [MEDIUM — src/gunbound/physics.py] Wind coeff error at obtuse wind angles (≈150°)

- **Affected shots**: armor, a=82, p=2.75/2.60, W=19@150°, h=−0.130 → errors +0.071–0.076 SD (down from +0.13 after height_diff fix)
- **Root cause confirmed**: wx amplification at very high launch angles (82°). At a=82°, `wx=9` (forward) accumulates over the long hang-time → +0.22 SD delta. `wy=−16` (downward) only counters −0.045 SD. Net model error ≈ +0.13 SD before height_diff fix, ≈ +0.07 SD after.
- **NOT a wy sign bug** — the 170° shot (wy=−17, wx=3) fits within +0.003 SD, confirming wy sign is correct.
- **Current mitigation**: `matching.suggest_shots()` returns tier-1 direct data matches for W=19@150° queries (d_sim < 0.08), bypassing the physics error.
- **Fix requires**: More shots at a=75°–85° with forward wind (θ=120°–160°) to constrain wx amplification at high angles. Power-exponent fit may also help indirectly.

### [MINOR — src/gunbound/calibration.py] No-wind v_scale lower than expected

- **Expected**: v_scale ≈ 1.45 (from analytical estimate `sqrt(0.5 * 9.8 / (1.9^2 * sin(140°)))`).
- **Actual after calibration**: v_scale = 1.2812.
- **Cause**: Nonlinear power response — the fitted v_scale is a least-squares compromise over the whole power range.
- **Impact**: Suggestions at 0.5 SD with no wind show power slightly off from the recorded shots. `matching.suggest_shots()` mitigates this for known conditions.

### [KNOWN — src/gunbound/calibration.py] wind_y instability between calibration runs (FIXED)

- **Was**: Phase B used 5000 random trials with no coord-descent → different basin each run → wind_y varied from 0.1165 to 0.1589 across sessions.
- **Fix applied (2026-04-19)**: Added a 400-iteration coord-descent pass after Phase B random search (same pattern as Phase A). wind_y now deterministic across runs.
- **Verified**: 4 consecutive runs all produce v_scale=1.2812, wind_x=0.0978, wind_y=0.1224.

---

## Edge Cases / Gotchas

### height_diff sign convention

- **Convention (FINAL)**: `height_diff > 0` = **shooter is HIGHER than enemy** (positive = more range). `height_diff < 0` = enemy is higher.
- **Training data**: All 16 non-zero entries were negated on 2026-04-19 to match the simulation convention. New entries must follow this convention.
- **Prompt**: User is asked "height diff (positive = you are higher)".
- **Impact of fix**: MAE improved from 0.0405 → improved further after data expansion.

### Negative height_diff (coarse-dt overshoot bug — FIXED)

- **Problem**: When `height_diff < 0`, old stop condition `if y <= 0: break` fired immediately (before projectile rose).
- **Fix 1**: Stop condition changed to `vy < 0 AND y <= 0` (only on the way DOWN).
- **Fix 2**: Linear interpolation at y=0 crossing to avoid coarse-step overshoot: `t_frac = prev_y / (prev_y - y); x = prev_x + (x - prev_x) * t_frac` when `prev_y > 0 and y <= 0`.
- **Location**: `simulate_shot()` in `src/gunbound/physics.py`.

### POWER_MAX constant

- **Old value**: 5.9 (wrong — was leftover from a different scale)
- **Correct value**: 4.0 (GunBound power bar is 0–4)
- **Fix applied (2026-04-19)**: `POWER_MAX = 4.0` in `src/gunbound/constants.py`. Only affects solver upper bound, not simulation or training data.

### Solver range for binary search

- `range(ANGLE_MIN, ANGLE_MAX + 1, int(angle_step))` — if `angle_step < 1`, `int()` gives 0 → `ValueError`.
- **Fix applied**: Refine pass now passes explicit `angle_subset: set[int]` instead of a float step.
- **Location**: `_solve_for_target()` / `solve()` in `src/gunbound/solver.py`.

### Too many low-angle suggestions

- **Problem**: At 0.5 SD with no wind, many angles from 35–55° produce near-identical power. Solver fills 5 slots with 45°, 48°, 51°… and 70°+ never appears.
- **Fix applied**: Two-stage selection in `solve()` (`src/gunbound/solver.py`): prefer shots in 45–80° range, even-space them if > MAX_SUGGESTIONS, fill remainder from outside range.

### Wind coefficient degeneracy

- **Problem**: If v_scale is fitted on shots that include wind, wind coefficients can absorb v_scale error (and vice versa). This was the root cause of the original joint calibration producing wrong v_scale.
- **Fix applied**: 3-phase calibration — Phase A fits v_scale from no-wind shots only.

### Integer wind truncation creates dead zones

- `int(W * sin(θ))` rounds toward zero. For W=1 and θ=5°, `int(0.087) = 0` — no horizontal push at all. This is intentional (matches engine behavior) but means small winds at near-vertical angles are ignored entirely.

### calc.py v1 Euler order mismatch

- `legacy/calc_legacy.py` does velocity-then-position (standard Euler forward). Reference engine does position-then-velocity. This creates a small discrepancy at each step, compounding over long trajectories.
- `src/gunbound/physics.py` matches engine order.

---

## Calibration — 3-Phase Strategy (src/gunbound/calibration.py)

```
Phase A: fit (v_scale, power_exp) ONLY using no-wind shots (wind=0 makes wind_x/y irrelevant)
         5000 random trials in [0.5, 3.0] + coordinate descent (step halving to 1e-8)
Phase B: fix (v_scale, power_exp), fit (wind_x, wind_y) using ALL shots
         5000 random trials in [0.01, 2.0] × [0.01, 2.0]
         + coord-descent refinement on (wx, wy), 400 iters, step halving to 1e-8  ← ADDED 2026-04-19
Phase C: joint coordinate descent from A+B starting point
         500 iterations, step halving to 1e-8
```

Phase B coord-descent was added because without it wind_y varied by ±0.03 between runs (different random basins). Now deterministic.

- `min_shots=3` to run calibration on a mobile.
- Writes to `config/mobiles_v2.json` after fitting.
- Run: `python main.py --calibrate`

---

## Data Schemas

### data/training_data.json entry

```json
{
  "mobile": "armor",
  "angle": 70.0,
  "power": 1.9,
  "wind_strength": 0.0,
  "wind_angle": 0.0,
  "height_diff": 0.0,
  "actual_sd": 0.5
}
```

### config/mobiles_v2.json entry

```json
{
  "armor": {
    "v_scale": 1.31502,
    "power_exp": 0.97071,
    "wind_x_coeff": 0.09710,
    "wind_y_coeff": 0.11745
  }
}
```

### config/mobiles.json entry (v1)

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

## Accuracy History

| Date | Shots | Armor MAE | Ice MAE | Overall MAE | Notes |
|---|---|---|---|---|---|
| 2026-04-19 (baseline) | 51 | 0.0444 | 0.0555 | 0.0468 | Before height_diff fix |
| 2026-04-19 (h fix) | 51 | 0.0342 | 0.0635 | 0.0405 | After negating 16 h entries + recalibrate |
| 2026-04-19 (expanded) | 103 | 0.0260 | 0.0635 | 0.0300 | 92 armor shots, Phase B coord-descent |
| 2026-04-19 (refactor) | 104 | 0.0241 | 0.0297 | 0.0247 | src/gunbound/ package; power_exp fitted |

## Current Accuracy (2026-04-19, 104 shots)

```
Armor (93 shots): MAE = 0.0241 SD
Ice   (11 shots): MAE = 0.0297 SD
Overall (104 shots): MAE = 0.0247 SD
```

Breakdown by shot type:
- No-wind shots (70°, a=45°/55°): S-curve undershoot p=1.6–2.8 (−0.06 to −0.13 SD), good at low/high power
- Wind shots opposing (−95°, −100°): errors 0.01–0.04 SD ✓
- Wind shots at 150°, a=82°: errors +0.07 SD ✗ (wx amplification at high launch angle)
- Wind 90° strong (W=24–26): errors 0.01–0.04 SD ✓
- Wind 180°/−180°: mostly ±0.04 SD ✓ (one outlier a=70,p=1.5,W=20 at −0.044)
- Mixed wind (36°, 50°, 144°, etc.): 0.01–0.05 SD ✓
- Ice (no-wind only): same S-curve pattern, MAE=0.0635 (fewer data points)

---

## Decisions + Rationale

| Decision | Rationale |
|---|---|
| Per-mobile gravity fixed from reference (not fitted) | Degenerate with v_scale on no-wind shots. Fixing it enables cross-mobile transfer and physics grounding. |
| No distance bands in v2 | 9 params per mobile → overfitting. With limited data, per-band wind coeffs are meaningless noise. |
| 3-phase calibration (separate v_scale from wind coeffs) | v_scale ↔ wind_coeff degeneracy. Joint random search produces wrong v_scale when wind shots dominate. |
| Keep SD-based coordinate system | All training data is already in SD. No conversion needed. |
| POWER_MAX = 4.0 | Game bar is 0–4. Old value of 5.9 was wrong. Solver upper bound only — does not affect simulation or training data. |
| height_diff convention: positive = shooter higher | Matches simulation starting condition `y = float(height_diff)`. 16 training entries negated on 2026-04-19 to match. |
| int() truncation on wind before coeff scaling | Matches engine dead-zone behavior. Engine uses integer wind internally. |
| Position-then-velocity Euler order in v2 | Matches reference engine order (confirmed from memory.py analysis). |
| Do NOT add time_scale as fitted parameter | Degenerate with wind_x_coeff when only final SD is observed. |
| Do NOT replace solver with static charts | GunBound physics is nonlinear; charts break at non-standard wind/height. |
| Keep `legacy/calc_legacy.py` as-is (do not port fixes back) | Preserve for comparison. Replaced by `src/gunbound/` package. |

---

## Incomplete Work / TODOs (ordered by priority)

### 1. [DONE] Port data-confidence layer

Completed. Four functions live in `src/gunbound/matching.py`:
- `find_similar_shots` — uses `wind_components` for (wx,wy) comparison
- `cluster_training_matches` — identical logic to legacy
- `compute_residual_correction` — uses `simulate_shot`
- `suggest_shots` — primary entry point; tier 1 = data matches, tier 2 = residual-corrected physics

Constants in `src/gunbound/constants.py`: `MATCH_CLOSE_THRESHOLD=0.08`, `MATCH_LOOSE_THRESHOLD=0.15`.
`ShotResult` in `models.py` has `source: str = 'physics'` and `n_samples: int = 0`.

### 2. [INVESTIGATED — partially mitigated] wx amplification at high launch angles

Shots at a=82°, W=19@150°, h=−0.130 still show err=+0.071–0.076 SD.
Root cause: At a=82°, the long hang time amplifies forward wind (wx=9) to +0.22 SD delta.
Data-confidence layer mitigates via tier-1 direct match. Residual error acceptable for now.

**Fix requires**: More shots at a=75°–85° with forward wind (θ=120°–160°) at various powers.

### 3. [MEDIUM — next priority] Add power exponent to simulation

Try `v_initial = power^n * v_scale` with `n` fitted (one extra param). Expected optimal n ≈ 1.75 from log regression on Armor no-wind data. This would flatten the S-curve.

### 4. [DONE] Port training mode

`python main.py --training` is implemented via `training_mode()` in `src/gunbound/cli.py`. Appends to `data/training_data.json`, auto-recalibrates on exit.

### 5. [LOW] Show angle range label in suggestions

Print context like `(high arc)` for angles > 70°, `(flat arc)` for < 55° so user understands trajectory family.

### 6. [DONE] Refactor into src/gunbound/ package

Completed 2026-04-19. `calc_v2.py` split into 7 modules + `__init__.py` under `src/gunbound/`. Root entrypoint is now `main.py`. Data files moved to `config/`, `data/`, `assets/`. Legacy code in `legacy/calc_legacy.py`. Tools in `tools/`. Scripts in `scripts/`. Validation confirmed: MAE=0.0247 SD (identical behaviour).

---

## Debugging Insights (what failed / what worked)

- **Joint random search for all 3 params simultaneously** → failed. v_scale was corrupted by wind shots. Fix: 3-phase separation.
- **`range(ANGLE_MIN, ANGLE_MAX, int(0.5))`** → `ValueError: range() arg 3 must not be zero`. Fix: separate angle_subset set for refine pass.
- **`if y <= 0: break`** for landing detection → broke negative height_diff shots (stopped before rising). Fix: `if vy < 0 and y <= 0: break`.
- **Dedup by power similarity alone (< 0.03 threshold)** → suppressed high-angle suggestions because power at 65° and 70° can differ < 0.03. Fix: require both `|angle diff| <= 3` AND `|power diff| < 0.08`.
- **5 suggestions all from 45–55° range** → solver finds many near-zero-error shots at low angles. Fix: prefer 45–80° range, even-space if overcrowded.
- **Analytical v_scale estimate ≈ 1.45** → `calibration.calibrate()` converges to 1.2812 (with 92 shots). Gap is due to nonlinear power curve; fitted value is a least-squares compromise, not the true ballistic constant.
- **wind_y variance across calibration runs** → Phase B random search without coord-descent could land in different basins. Fixed by adding 400-iter coord-descent after Phase B (same as Phase A). Now fully deterministic.
- **height_diff convention mismatch** → training data had h>0 = enemy higher, simulation had h>0 = shooter higher. Fixed by negating all 16 non-zero h entries in training_data.json. MAE improved from 0.0468 → 0.0405 immediately.
- **Coarse-dt overshoot for h<0 shots** → `vy0*dt > |h|` caused y to jump past 0 on the first step. Fixed with linear interpolation: `t_frac = prev_y / (prev_y - y); x = prev_x + (x - prev_x) * t_frac`.
- **POWER_MAX = 5.9** → was wrong (game bar is 0–4). Fixed to 4.0. Only affects solver bounds.

---

## File Map

```
src/gunbound/         — PRIMARY package. All active development here.
  constants.py        — MOBILE_PHYSICS, solver params, thresholds
  models.py           — ShotResult dataclass
  physics.py          — effective_gravity, wind_components, simulate_shot
  calibration.py      — calibrate, recalibrate_all, validate
  solver.py           — solve (coarse→refine)
  matching.py         — suggest_shots (primary entry point), find_similar_shots
  storage.py          — load/save helpers; PROJECT_ROOT, CONFIG_DIR, DATA_DIR
  cli.py              — main(), training_mode()
main.py               — Entrypoint (sys.path insert + calls gunbound.cli:main)
config/mobiles_v2.json — v2 calibrated params. Written by --calibrate.
config/mobiles.json   — v1 calibrated params (per-band). Reference only.
data/training_data.json — All recorded shots. Never delete.
assets/ruler.png      — Pre-rendered ruler image.
legacy/calc_legacy.py — v1. Keep for reference.
tools/ruler.py        — On-screen SD ruler overlay.
tools/gen_ruler.py    — Regenerates assets/ruler.png.
tools/memory_reader.py — Game process memory reader (research PoC).
scripts/import_baseline.py — Bulk import shots into training data.
.agents/next_steps_v2.md — Detailed v2 architecture plan + per-mobile v_scale table.
docs/physics.md       — Physics documentation.
AGENTS.md             — This project's AI navigation guide.
```

---

## How to Run

```bash
python main.py                        # interactive calculator — use this
python main.py --calibrate            # recalibrate from data/training_data.json → config/mobiles_v2.json
python main.py --validate             # print per-shot errors and MAE
python main.py --training             # record shots into training data
python scripts/import_baseline.py    # bulk import reference shots
python tools/ruler.py                 # on-screen SD ruler overlay
python tools/gen_ruler.py             # regenerate assets/ruler.png
```
