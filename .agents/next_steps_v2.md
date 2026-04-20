# GunBound Calculator v2 — Architecture Plan

## Why v2

### Critical bug in calc.py
`calibrate_mobile()` searches `v_scale` in `[0.85, 1.20]`.
Analytical estimate from Armor training data (power=1.9 → 0.5 SD at 70°):

```
x = (p·v)²·sin(2α)/g  →  v = sqrt(x·g / (p²·sin(2α)))
  = sqrt(0.5·9.8 / (1.9²·sin(140°))) ≈ 1.45
```

The true optimum (~1.45) lies **outside** the search range.
The calibrator is maxing out at 1.20 and the model is systematically wrong.

### Fixed gravity for all mobiles
calc.py uses `gravity=9.8` for every mobile.
From reference reverse-engineering, actual per-mobile gravity spans:
- JFrog: 54.3  (lightest — goes farthest)
- Nak:   93.0  (heaviest — shortest range)
That's a **70% range** that v_scale cannot fully compensate per-band.

### Per-band overcomplexity
3 parameters × 3 bands = 9 parameters per mobile.
With limited wind data, wind_x_coeff and wind_y_coeff are fitted on noise.
All 9 params change together during calibration with no physics grounding.

---

## v2 Design

### Core principles

1. **Per-mobile gravity is FIXED from reference** (not fitted):
   ```
   g_mobile = 9.8 × (g_ref_mobile / g_ref_armor)
   ```
   Armor=9.8 (anchor), Ice=8.33, Nak=12.40, JFrog=7.24, etc.
   This removes gravity as a fitted degree of freedom.

2. **No distance bands** — one `(v_scale, wind_x_coeff, wind_y_coeff)` per mobile.
   3 params vs 9 params. Less overfitting, more data per calibration point.

3. **Corrected v_scale search range**: `[0.5, 3.0]` (was `[0.85, 1.20]`).

4. **Integer wind truncation** matching engine behavior:
   ```python
   wx = int(W · sin(θ))  # applied BEFORE wind_coeff scaling
   wy = int(W · cos(θ))
   ```

5. **Integration order: position then velocity** (matching reference engine order).
   Current calc.py does velocity then position — this is the Störmer-Verlet discrepancy.

6. **New mobile auto-initialization** from reference gravity ratio:
   ```
   v_scale_new = v_scale_armor × sqrt(g_new / g_armor)
   ```
   Wind defaults from reference `projectile_speed` ratio.
   A new mobile gets a usable prior estimate **with zero training shots**.

7. **Calibration: random search + coordinate descent**:
   - Phase 1: 5000 random trials over `[0.5,3.0]×[0.01,2.0]×[0.01,2.0]`
   - Phase 2: coordinate descent refinement from best candidate

---

## Expected improvements

| Metric | calc.py (v1) | calc_v2.py (expected) |
|---|---|---|
| Armor no-wind MAE | ~0.15 SD (v_scale bug) | < 0.01 SD |
| Armor wind MAE | unknown (wind coeffs random) | < 0.05 SD |
| New mobile (no data) | needs 3+ shots per band | derived from reference gravity ratio |
| Calibration params | 9 per mobile | 3 per mobile |

---

## Implementation plan

### Phase 1 — Core (calc_v2.py)
- [x] `MOBILE_PHYSICS` dict — gravity + projectile_speed for 18 mobiles
- [x] `effective_gravity(mobile)` — per-mobile g in SD-based units
- [x] `default_v_scale(mobile, armor_v_scale)` — init for uncalibrated mobiles
- [x] `wind_components_v2(W, theta_deg)` — with int() truncation
- [x] `simulate_shot_v2(...)` — position-before-velocity Euler, per-mobile g

### Phase 2 — Calibration (calc_v2.py)
- [x] `_loss_v2(data, mobile, v_scale, wx, wy)` — weighted squared error
- [x] `calibrate_v2(data, mobile)` — random search + coordinate descent
- [x] `recalibrate_all_v2(cfg, training_data)` — per-mobile, no bands

### Phase 3 — Validation (calc_v2.py)
- [x] `validate_v2(cfg, training_data)` — per-shot errors, MAE, max error
- [ ] Compare MAE before/after vs calc.py v1 baseline

### Phase 4 — Calculator (calc_v2.py)
- [x] `solve_v2(...)` — coarse→refine solver using simulate_shot_v2
- [x] `main()` — `--calibrate`, `--validate`, default = solve loop

### Phase 5 — Integration
- [x] Port data-confidence layer (`find_similar_shots_v2`, `cluster_training_matches`, `_compute_residual_correction_v2`, `suggest_shots_v2`) to calc_v2.py
  - `ShotResult` extended with `source` and `n_samples` fields
  - `MATCH_CLOSE_THRESHOLD=0.08`, `MATCH_LOOSE_THRESHOLD=0.15` added
  - `main()` now calls `suggest_shots_v2` (primary entry point)
- [x] Port training mode — `python calc_v2.py --training` → `training_mode_v2()`, auto-recalibrates every 5 new shots
- [ ] Port strong-wind angle cap (with real per-mobile gravity, cap may change)

### Phase 6 — Physics improvements (after more training data)
- [x] **Power exponent fit**: `v_initial = power^power_exp * v_scale` with `power_exp` fitted per mobile.
  - Armor: `power_exp=0.9728` (slight sub-linear), Ice: `power_exp=0.8445`
  - Ice MAE improved from 0.0635 → 0.0297 (-53%). Overall MAE 0.0300 → 0.0254.
  - Theoretical value from log-log regression on no-wind Armor data: n≈0.88 (`sd ∝ power^1.76`).
  - Phase A of calibration now jointly fits `(v_scale, power_exp)` from no-wind shots. Search range `[0.3, 1.5]`.
  - Phase C joint descent operates on all 4 params: `(v_scale, power_exp, wind_x, wind_y)`.
- [ ] **wx amplification at high angles (80°+)**: at nearly-vertical launch angles, forward wind accumulates over long flight time and dominates. Mitigated by data-confidence layer (tier-1 direct data match). Fix requires more training shots at a=75°–85° with forward wind (θ=120°–160°), then recalibrate.
  - `wy bug` at θ≈150° is actually a **wx amplification** issue, not a sign error.
  - At a=82°, W=19@150°: wx_int=9, wy_int=−16. wx alone contributes +0.22 SD delta; wy contributes −0.045 SD. Model overshoots by +0.07 SD after height_diff fix.

---

## Per-mobile initial v_scale estimates

Derived from `v_scale_armor=1.45`, formula: `v_scale = 1.45 × sqrt(g_eff / 9.8)`

| Mobile | g_ref | g_eff | v_scale_init |
|---|---|---|---|
| armor | 73.5 | 9.800 | 1.450 |
| mage | 71.5 | 9.534 | 1.430 |
| ice | 62.5 | 8.333 | 1.337 |
| jd | 62.5 | 8.333 | 1.337 |
| boomer | 62.5 | 8.333 | 1.337 |
| grub | 61.0 | 8.133 | 1.321 |
| jfrog | 54.3 | 7.240 | 1.247 |
| lightning | 65.0 | 8.667 | 1.363 |
| aduka | 65.5 | 8.733 | 1.369 |
| knight | 65.5 | 8.733 | 1.369 |
| turtle | 73.5 | 9.800 | 1.450 |
| asate | 76.0 | 10.133 | 1.475 |
| raon | 81.0 | 10.800 | 1.522 |
| trico | 84.0 | 11.200 | 1.550 |
| bigfoot | 90.0 | 12.000 | 1.604 |
| kalsiddon | 88.5 | 11.800 | 1.592 |
| nak | 93.0 | 12.400 | 1.631 |
| dragon | 54.3 | 7.240 | 1.247 |

---

## Files

| File | Role |
|---|---|
| `calc_v2.py` | New implementation (this sprint) |
| `mobiles_v2.json` | Per-mobile v2 config (no bands, auto-created) |
| `calc.py` | Kept for comparison during transition |
| `training_data.json` | Shared — same format, unchanged |

---

## Decisions

- Keep SD-based coordinate system (no switch to map units)
- Keep power scale 0.5–6.0 (all training data stays valid)
- Per-mobile gravity is a PRIOR from reference — **not re-fitted from data**
  (degenerate with v_scale on no-wind shots; fixing it enables cross-mobile transfer)
- `projectile_speed` is used as a default wind coefficient PRIOR for new mobiles only.
  For calibrated mobiles, wind coefficients are fitted freely.
- int() truncation on wind components applied before coeff scaling, not after
