# GunBound Classic Shot Calculator — Next Steps

This document tracks what is already working and what still needs to be done.
Update it as work progresses.

---

## What is working

- **Physics simulation** — Euler integration, continuous per-step wind force. dt=0.05, up to 1000 steps.
- **Wind decomposition** — `wx = W·sin(θ)`, `wy = W·cos(θ)`. Longer flight = more deflection.
- **Distance bands** — short/mid/long, calibrated independently (min 3 samples each).
- **Coarse→refine solver** — ~4 ms/query. Strong-wind angle cap (>14 bars on mid/long: max 72°), overridden when training data shows a high-angle shot working near the target distance.
- **Calibration** — random search (3000 iterations), weighted least-squares loss `Σ (predicted−actual)² / (1+|actual|)`, auto-runs every 10 shots.
- **Data-confidence layer** — `suggest_shots()` returns data-matched slots (d_sim < 0.08) first; residual correction applied from loose matches (d_sim < 0.15); physics fills remaining slots.
- **Training mode** — `python calc.py --training` for manual entry; `import_baseline.py` for bulk import.
- **Ruler overlay** — `ruler.py` (PNG-based, transparent, snap-to-screen).

---

## Pending — short term


### B. Coordinate descent refinement in calibrator

After random search finds best candidate, run a local refinement loop: nudge each of `v_scale`, `wind_x_coeff`, `wind_y_coeff` by ±small_step, accept if loss improves. ~50 steps. Keeps random search as initializer.

File: `calc.py` — `calibrate_mobile()`

---

### C. Show band name in suggestions

Print `(short / mid / long)` alongside each suggestion in `main()`. One-line change.

File: `calc.py` — `main()`

---

## Pending — medium term

### D. Local re-calibration using nearest neighbours

Once ~50+ shots per mobile are collected, replace per-band random search with fitting over the N=30 most-similar shots by `d_sim`. Produces angle- and wind-specific coefficients instead of one value per range band.

`find_similar_shots()` is already implemented — wire into `recalibrate_all()`.

---

### E. Nonlinear wind scaling

`wind_x_coeff` is currently constant per band. High-angle shots spend more time in the air and deflect more per unit wind. Option: replace with `vx += wx * f(angle) * dt` where `f` is a fitted piecewise or polynomial function.

---

## Decided against

- **`time_scale` as a fitted parameter** — degenerate with `wind_x_coeff` when only final landing SD is observed.
- **Static charts / interpolation** — assumes linear behaviour; GunBound physics is nonlinear.
- **scipy.optimize** — adds a dependency for marginal gain over coordinate descent (item B).
