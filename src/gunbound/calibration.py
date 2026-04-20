"""
calibration.py — Parameter fitting and validation for the GunBound shot calculator.

Calibration is a 3-phase process per mobile:
  Phase A: Fit (v_scale, power_exp) from no-wind shots only.
  Phase B: Fix (v_scale, power_exp), fit (wind_x_coeff, wind_y_coeff) from all shots.
  Phase C: Joint coordinate-descent refinement of all 4 parameters.

This separation prevents the v_scale ↔ wind_coeff degeneracy that corrupts
single-phase joint fits on mixed wind/no-wind datasets.
"""

import random
from collections import defaultdict

from .physics import simulate_shot
from .storage import save_mobiles


def _loss(
    data: list,
    mobile: str,
    v_scale: float,
    power_exp: float,
    wind_x: float,
    wind_y: float,
) -> float:
    """Weighted squared error over a set of shots for one mobile."""
    total = 0.0
    for d in data:
        pred   = simulate_shot(
            d["angle"], d["power"], mobile,
            v_scale, power_exp, wind_x, wind_y,
            d["wind_strength"], d["wind_angle"], d["height_diff"],
        )
        actual = d["actual_sd"]
        # Weight: down-weight long shots slightly so short-range isn't dominated
        w      = 1.0 / (0.5 + abs(actual))
        total += w * (pred - actual) ** 2
    return total


def calibrate(
    data: list,
    mobile: str,
    iterations: int = 5000,
) -> tuple[float, float, float, float]:
    """Fit (v_scale, power_exp, wind_x_coeff, wind_y_coeff) for one mobile.

    Returns
    -------
    (v_scale, power_exp, wind_x_coeff, wind_y_coeff)
    """
    no_wind  = [d for d in data if d["wind_strength"] < 0.5]
    has_wind = [d for d in data if d["wind_strength"] >= 0.5]

    # ── Phase A: (v_scale, power_exp) from no-wind shots ─────────────────
    vs_data = no_wind if no_wind else data

    def loss_vs_pe(v, pe):
        return _loss(vs_data, mobile, v, pe, 0.0, 0.0)

    best_vs      = 1.45
    best_pe      = 0.88
    best_vs_loss = loss_vs_pe(best_vs, best_pe)
    for _ in range(iterations):
        v    = random.uniform(0.5, 3.0)
        pe   = random.uniform(0.3, 1.5)
        loss = loss_vs_pe(v, pe)
        if loss < best_vs_loss:
            best_vs_loss = loss
            best_vs, best_pe = v, pe

    # 2D coordinate-descent refinement of (v_scale, power_exp)
    step     = 0.05
    bounds_a = [(0.5, 3.0), (0.3, 1.5)]
    for _ in range(500):
        improved = False
        for axis in range(2):
            current = [best_vs, best_pe]
            for sign in (+1.0, -1.0):
                trial = current.copy()
                lo, hi = bounds_a[axis]
                trial[axis] = max(lo, min(hi, trial[axis] + sign * step))
                loss = loss_vs_pe(trial[0], trial[1])
                if loss < best_vs_loss:
                    best_vs_loss = loss
                    best_vs, best_pe = trial
                    improved = True
                    break
        if not improved:
            step *= 0.5
            if step < 1e-8:
                break

    # ── Phase B: wind coefficients (v_scale, power_exp fixed) ─────────────
    best_wx, best_wy = 0.10, 0.10
    if has_wind:
        best_wind_loss = _loss(data, mobile, best_vs, best_pe, best_wx, best_wy)
        for _ in range(iterations):
            wx   = random.uniform(0.01, 2.0)
            wy   = random.uniform(0.01, 2.0)
            loss = _loss(data, mobile, best_vs, best_pe, wx, wy)
            if loss < best_wind_loss:
                best_wind_loss = loss
                best_wx, best_wy = wx, wy

    # ── Phase B refinement: coordinate-descent on (wx, wy) ─────────────────
    if has_wind:
        step_b = 0.02
        for _ in range(400):
            improved = False
            for axis in range(2):
                current = [best_wx, best_wy]
                for sign in (+1.0, -1.0):
                    trial = current.copy()
                    trial[axis] = max(0.01, min(2.0, trial[axis] + sign * step_b))
                    loss = _loss(data, mobile, best_vs, best_pe, trial[0], trial[1])
                    if loss < best_wind_loss:
                        best_wind_loss = loss
                        best_wx, best_wy = trial
                        improved = True
                        break
            if not improved:
                step_b *= 0.5
                if step_b < 1e-8:
                    break

    # ── Phase C: joint coordinate-descent on all 4 params ──────────────────
    vs, pe, wx, wy = best_vs, best_pe, best_wx, best_wy
    best_joint     = _loss(data, mobile, vs, pe, wx, wy)
    step           = 0.02
    bounds         = [(0.5, 3.0), (0.3, 1.5), (0.01, 2.0), (0.01, 2.0)]

    for _ in range(500):
        improved = False
        for axis in range(4):
            current = [vs, pe, wx, wy]
            for sign in (+1.0, -1.0):
                trial        = current.copy()
                trial[axis] += sign * step
                lo, hi       = bounds[axis]
                trial[axis]  = max(lo, min(hi, trial[axis]))
                loss         = _loss(data, mobile, *trial)
                if loss < best_joint:
                    best_joint = loss
                    vs, pe, wx, wy = trial
                    improved   = True
                    break
        if not improved:
            step *= 0.5
            if step < 1e-8:
                break

    return (vs, pe, wx, wy)


def recalibrate_all(
    mobiles_cfg: dict,
    training_data: list,
    min_shots: int = 3,
) -> dict:
    """Calibrate every mobile that has enough training shots.

    Saves results to config/mobiles_v2.json after fitting.
    """
    by_mobile: dict[str, list] = defaultdict(list)
    for d in training_data:
        by_mobile[d["mobile"]].append(d)

    for mobile, shots in sorted(by_mobile.items()):
        if len(shots) < min_shots:
            print(f"  {mobile}: {len(shots)} shot(s) — need {min_shots} to calibrate, skipping.")
            continue

        print(f"  {mobile}: fitting on {len(shots)} shot(s)…", end=" ", flush=True)
        v_scale, power_exp, wind_x, wind_y = calibrate(shots, mobile)

        if mobile not in mobiles_cfg:
            mobiles_cfg[mobile] = {}

        mobiles_cfg[mobile]["v_scale"]      = round(v_scale,    6)
        mobiles_cfg[mobile]["power_exp"]    = round(power_exp,  6)
        mobiles_cfg[mobile]["wind_x_coeff"] = round(wind_x,     6)
        mobiles_cfg[mobile]["wind_y_coeff"] = round(wind_y,     6)
        print(f"v_scale={v_scale:.4f}  power_exp={power_exp:.4f}  wind_x={wind_x:.4f}  wind_y={wind_y:.4f}")

    save_mobiles(mobiles_cfg)
    return mobiles_cfg


def validate(mobiles_cfg: dict, training_data: list) -> None:
    """Print per-shot prediction errors for all training shots.

    Shows MAE, max error, and flags shots with error > 0.05 SD.
    """
    from .physics import effective_gravity  # local import to avoid circular at module level

    by_mobile: dict[str, list] = defaultdict(list)
    for d in training_data:
        by_mobile[d["mobile"]].append(d)

    overall_errors = []

    for mobile, shots in sorted(by_mobile.items()):
        cfg        = mobiles_cfg.get(mobile, {})
        v_scale    = cfg.get("v_scale",      1.45)
        power_exp  = cfg.get("power_exp",    1.0)
        wind_x     = cfg.get("wind_x_coeff", 0.10)
        wind_y     = cfg.get("wind_y_coeff", 0.10)
        g_eff      = effective_gravity(mobile)

        errors = []
        for d in shots:
            pred = simulate_shot(
                d["angle"], d["power"], mobile,
                v_scale, power_exp, wind_x, wind_y,
                d["wind_strength"], d["wind_angle"], d["height_diff"],
            )
            errors.append(pred - d["actual_sd"])

        mae     = sum(abs(e) for e in errors) / len(errors)
        max_err = max(abs(e) for e in errors)
        overall_errors.extend(errors)

        print(f"\n{'─'*70}")
        print(f"  {mobile.upper()}  ({len(shots)} shots)")
        print(f"  g_eff={g_eff:.3f}  v_scale={v_scale:.4f}  power_exp={power_exp:.4f}  "
              f"wind_x={wind_x:.4f}  wind_y={wind_y:.4f}")
        print(f"  MAE={mae:.4f} SD   max_err={max_err:.4f} SD")
        print(f"{'─'*70}")

        for d, err in zip(shots, errors):
            flag = "  ←" if abs(err) > 0.05 else ""
            print(
                f"  a={d['angle']:5.1f}° p={d['power']:.2f} "
                f"W={d['wind_strength']:4.0f}@{d['wind_angle']:+6.0f}° "
                f"h={d['height_diff']:+.3f} | "
                f"pred={d['actual_sd'] + err:.3f}  actual={d['actual_sd']:.3f}  "
                f"err={err:+.4f}{flag}"
            )

    if overall_errors:
        overall_mae = sum(abs(e) for e in overall_errors) / len(overall_errors)
        print(f"\n{'═'*70}")
        print(f"  OVERALL  ({len(overall_errors)} shots)  MAE={overall_mae:.4f} SD")
        print(f"{'═'*70}")
