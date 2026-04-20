"""
calc_v2.py — Physics-grounded GunBound shot calculator

Key differences from calc.py:
  1. Per-mobile gravity fixed from reference reverse-engineering (not fitted)
  2. No distance bands — one (v_scale, wind_x_coeff, wind_y_coeff) per mobile
  3. v_scale search range corrected to [0.5, 3.0]
  4. Integer wind truncation matching engine behavior
  5. Euler order: position then velocity (matches reference engine)
  6. Calibration: random search + coordinate descent (no per-band splits)
  7. New mobile auto-init from reference gravity ratio

Usage:
  python calc_v2.py                # calculator loop
  python calc_v2.py --calibrate    # recalibrate all mobiles from training_data.json
  python calc_v2.py --validate     # print per-shot errors for all training shots
"""

import json
import math
import os
import random
import sys
from collections import defaultdict
from dataclasses import dataclass, field

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
TRAINING_FILE = os.path.join(BASE_DIR, "training_data.json")
MOBILES_FILE  = os.path.join(BASE_DIR, "mobiles_v2.json")

# ─────────────────────────────────────────────────────────────────────────────
# Per-mobile physics constants from reference reverse-engineering (memory.py)
#
# gravity:          game-internal downward acceleration (arbitrary units).
#                   Ratio matters — all mobiles are normalised relative to Armor.
# projectile_speed: used as wind-coefficient PRIOR for uncalibrated mobiles.
#                   In the reference it scales wind acceleration (not launch v).
# ─────────────────────────────────────────────────────────────────────────────
MOBILE_PHYSICS: dict[str, dict] = {
    "armor":     {"gravity": 73.5,  "projectile_speed": 0.740},
    "mage":      {"gravity": 71.5,  "projectile_speed": 0.780},
    "nak":       {"gravity": 93.0,  "projectile_speed": 0.990},
    "trico":     {"gravity": 84.0,  "projectile_speed": 0.870},
    "bigfoot":   {"gravity": 90.0,  "projectile_speed": 0.740},
    "boomer":    {"gravity": 62.5,  "projectile_speed": 1.395},
    "raon":      {"gravity": 81.0,  "projectile_speed": 0.827},
    "lightning": {"gravity": 65.0,  "projectile_speed": 0.720},
    "jd":        {"gravity": 62.5,  "projectile_speed": 0.625},
    "asate":     {"gravity": 76.0,  "projectile_speed": 0.765},
    "ice":       {"gravity": 62.5,  "projectile_speed": 0.625},
    "turtle":    {"gravity": 73.5,  "projectile_speed": 0.740},
    "grub":      {"gravity": 61.0,  "projectile_speed": 0.650},
    "aduka":     {"gravity": 65.5,  "projectile_speed": 0.695},
    "knight":    {"gravity": 65.5,  "projectile_speed": 0.695},
    "kalsiddon": {"gravity": 88.5,  "projectile_speed": 0.905},
    "jfrog":     {"gravity": 54.3,  "projectile_speed": 0.670},
    "dragon":    {"gravity": 54.3,  "projectile_speed": 0.670},
}

_ARMOR_G_REF = MOBILE_PHYSICS["armor"]["gravity"]   # 73.5  (normalisation anchor)
_G_BASE      = 9.8                                   # effective g for Armor in SD units


# ─────────────────────────────────────────────────────────────────────────────
# Calibration constants
# ─────────────────────────────────────────────────────────────────────────────
SOLVER_COARSE_STEP  = 2      # degrees, coarse angle sweep
SOLVER_REFINE_STEP  = 0.5    # degrees, refinement sweep
SOLVER_POWER_STEPS  = 40     # power grid points per angle
ANGLE_MIN           = 35
ANGLE_MAX           = 89
POWER_MIN           = 0.5
POWER_MAX           = 4.0
MAX_SUGGESTIONS     = 5

# Data-confidence thresholds (same scale as calc.py)
MATCH_CLOSE_THRESHOLD = 0.08   # d_sim below this → direct data suggestion
MATCH_LOOSE_THRESHOLD = 0.15   # d_sim below this → residual correction applied


# ─────────────────────────────────────────────────────────────────────────────
# Helper physics functions
# ─────────────────────────────────────────────────────────────────────────────

def effective_gravity(mobile: str) -> float:
    """Return the effective gravity for a mobile in SD/step² units.

    Uses the real per-mobile gravity ratio from reference reverse-engineering.
    Falls back to Armor gravity if the mobile is unknown.
    """
    phys = MOBILE_PHYSICS.get(mobile, MOBILE_PHYSICS["armor"])
    return _G_BASE * phys["gravity"] / _ARMOR_G_REF


def default_v_scale(mobile: str, armor_v_scale: float) -> float:
    """Derive an initial v_scale for a mobile from Armor's fitted v_scale.

    Derivation: for same power/angle/range, x ∝ v_scale²/g
    → v_scale_mobile = v_scale_armor × sqrt(g_mobile / g_armor)
    """
    g_mobile = effective_gravity(mobile)
    g_armor  = effective_gravity("armor")
    return armor_v_scale * math.sqrt(g_mobile / g_armor)


def wind_components_v2(W: float, theta_deg: float) -> tuple[int, int]:
    """Decompose wind (W, theta) into integer (wx, wy) components.

    Convention (same as calc.py):
      theta = 0°   → straight up  (no horizontal push)
      theta = 90°  → toward enemy (positive x)
      theta = -90° → away from enemy (negative x)
      theta = 180° → straight down

    Integer truncation is applied before wind_coeff scaling to match
    the reference engine's dead-zone behaviour.
    """
    theta = math.radians(theta_deg)
    wx = int(W * math.sin(theta))
    wy = int(W * math.cos(theta))
    return wx, wy


# ─────────────────────────────────────────────────────────────────────────────
# Core physics simulation
# ─────────────────────────────────────────────────────────────────────────────

def simulate_shot_v2(
    angle_deg: float,
    power: float,
    mobile: str,
    v_scale: float,
    power_exp: float,
    wind_x_coeff: float,
    wind_y_coeff: float,
    wind_strength: float,
    wind_angle_deg: float,
    height_diff: float,
) -> float:
    """Simulate a shot and return the landing x-distance in SD units.

    Euler integration with:
      - Per-mobile gravity (from MOBILE_PHYSICS, fixed)
      - Integer wind truncation before coeff scaling (engine accuracy)
      - Position-before-velocity update order (matches reference engine)

    Parameters
    ----------
    angle_deg     : launch angle in degrees (0=horizontal, 90=straight up)
    power         : power bar value (0–4 scale, practical range 0.5–4.0)
    mobile        : mobile name (must be in MOBILE_PHYSICS or mobiles_v2.json)
    v_scale       : velocity scale factor (fitted per mobile)
    power_exp     : power exponent (v_init = power^power_exp * v_scale). Fitted
                    per mobile; corrects the nonlinear power-to-velocity curve.
    wind_x_coeff  : horizontal wind coefficient (fitted per mobile)
    wind_y_coeff  : vertical wind coefficient (fitted per mobile)
    wind_strength : wind strength in game bars (0–26)
    wind_angle_deg: wind direction (convention: 0=up, 90=toward enemy)
    height_diff   : signed height offset, positive = shooter higher than target
    """
    g = effective_gravity(mobile)

    v_init = (power ** power_exp) * v_scale
    vx = v_init * math.cos(math.radians(angle_deg))
    vy = v_init * math.sin(math.radians(angle_deg))

    wx_int, wy_int = wind_components_v2(wind_strength, wind_angle_deg)
    wx = wx_int * wind_x_coeff
    wy = wy_int * wind_y_coeff

    x, y = 0.0, float(height_diff)
    dt   = 0.05
    prev_x, prev_y = x, y

    for _ in range(2000):
        prev_x, prev_y = x, y
        x  += vx * dt       # position update FIRST (matches reference engine order)
        y  += vy * dt
        vx += wx * dt       # velocity update after
        vy += (wy - g) * dt  # wind_y lifts (+wy), gravity pulls down (-g)
        # Stop on the way DOWN only.
        # Linear interpolation corrects the coarse-dt overshoot at the y=0 crossing
        # (critical for h<0 where the starting position is below y=0).
        if vy < 0 and y <= 0.0:
            if prev_y > 0.0:
                t_frac = prev_y / (prev_y - y)   # fraction of last step to y=0
                x = prev_x + (x - prev_x) * t_frac
            break

    return x


# ─────────────────────────────────────────────────────────────────────────────
# Calibration
# ─────────────────────────────────────────────────────────────────────────────

def _loss_v2(
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
        pred   = simulate_shot_v2(
            d["angle"], d["power"], mobile,
            v_scale, power_exp, wind_x, wind_y,
            d["wind_strength"], d["wind_angle"], d["height_diff"],
        )
        actual = d["actual_sd"]
        # Weight: down-weight long shots slightly so short-range isn't dominated
        w      = 1.0 / (0.5 + abs(actual))
        total += w * (pred - actual) ** 2
    return total


def calibrate_v2(
    data: list,
    mobile: str,
    iterations: int = 5000,
) -> tuple[float, float, float]:
    """Fit (v_scale, power_exp, wind_x_coeff, wind_y_coeff) for one mobile.

    Phase A: Fit (v_scale, power_exp) jointly from no-wind shots.
             No-wind shots give an unambiguous signal — wind coefficients are
             irrelevant when wind_strength == 0.
             power_exp corrects the nonlinear power-to-velocity S-curve.
    Phase B: Fix (v_scale, power_exp). Fit (wind_x, wind_y) from all shots.
             Separating this phase prevents v_scale from being corrupted by
             the v_scale ↔ wind_coeff degeneracy present in wind shots.
    Phase C: Joint coordinate-descent refinement across all 4 params.

    Returns
    -------
    (v_scale, power_exp, wind_x_coeff, wind_y_coeff)
    """
    no_wind  = [d for d in data if d["wind_strength"] < 0.5]
    has_wind = [d for d in data if d["wind_strength"] >= 0.5]

    # ── Phase A: (v_scale, power_exp) from no-wind shots ─────────────────
    vs_data = no_wind if no_wind else data

    def loss_vs_pe(v, pe):
        return _loss_v2(vs_data, mobile, v, pe, 0.0, 0.0)

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
    step   = 0.05
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
        best_wind_loss = _loss_v2(data, mobile, best_vs, best_pe, best_wx, best_wy)
        for _ in range(iterations):
            wx   = random.uniform(0.01, 2.0)
            wy   = random.uniform(0.01, 2.0)
            loss = _loss_v2(data, mobile, best_vs, best_pe, wx, wy)
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
                    loss = _loss_v2(data, mobile, best_vs, best_pe, trial[0], trial[1])
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
    best_joint     = _loss_v2(data, mobile, vs, pe, wx, wy)
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
                loss         = _loss_v2(data, mobile, *trial)
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


def recalibrate_all_v2(
    mobiles_cfg: dict,
    training_data: list,
    min_shots: int = 3,
) -> dict:
    """Calibrate every mobile that has enough training shots.

    Saves results to mobiles_v2.json after fitting.
    """
    by_mobile: dict[str, list] = defaultdict(list)
    for d in training_data:
        by_mobile[d["mobile"]].append(d)

    for mobile, shots in sorted(by_mobile.items()):
        if len(shots) < min_shots:
            print(f"  {mobile}: {len(shots)} shot(s) — need {min_shots} to calibrate, skipping.")
            continue

        print(f"  {mobile}: fitting on {len(shots)} shot(s)…", end=" ", flush=True)
        v_scale, power_exp, wind_x, wind_y = calibrate_v2(shots, mobile)

        if mobile not in mobiles_cfg:
            mobiles_cfg[mobile] = {}

        mobiles_cfg[mobile]["v_scale"]      = round(v_scale,    6)
        mobiles_cfg[mobile]["power_exp"]    = round(power_exp,  6)
        mobiles_cfg[mobile]["wind_x_coeff"] = round(wind_x,     6)
        mobiles_cfg[mobile]["wind_y_coeff"] = round(wind_y,     6)
        print(f"v_scale={v_scale:.4f}  power_exp={power_exp:.4f}  wind_x={wind_x:.4f}  wind_y={wind_y:.4f}")

    _save_mobiles(mobiles_cfg)
    return mobiles_cfg


# ─────────────────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────────────────

def validate_v2(mobiles_cfg: dict, training_data: list) -> None:
    """Print per-shot prediction errors for all training shots.

    Shows MAE, max error, and flags shots with error > 0.05 SD.
    """
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
            pred = simulate_shot_v2(
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


# ─────────────────────────────────────────────────────────────────────────────
# File I/O
# ─────────────────────────────────────────────────────────────────────────────

def _load_mobiles() -> dict:
    if os.path.exists(MOBILES_FILE):
        with open(MOBILES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_mobiles(cfg: dict) -> None:
    with open(MOBILES_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print(f"  Saved → {MOBILES_FILE}")


def _load_training() -> list:
    if not os.path.exists(TRAINING_FILE):
        return []
    with open(TRAINING_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Solver
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ShotResult:
    angle:     float
    power:     float
    error:     float
    source:    str = "physics"   # "physics" or "data"
    n_samples: int = 0            # training shots backing a "data" suggestion


def _solve_for_target(
    target_sd: float,
    mobile: str,
    cfg: dict,
    wind_strength: float,
    wind_angle_deg: float,
    height_diff: float,
    angle_step: float,
    power_steps: int,
    angle_subset: set[int] | None = None,
) -> list[ShotResult]:
    """Sweep angles and binary-search power for each angle."""
    v_scale   = cfg.get("v_scale",      1.45)
    power_exp = cfg.get("power_exp",    1.0)
    wind_x    = cfg.get("wind_x_coeff", 0.10)
    wind_y    = cfg.get("wind_y_coeff", 0.10)

    results = []

    def _sim(a, p):
        return simulate_shot_v2(a, p, mobile, v_scale, power_exp, wind_x, wind_y,
                                 wind_strength, wind_angle_deg, height_diff)

    if angle_subset is not None:
        angles = sorted(angle_subset)
    else:
        step = max(1, int(angle_step))
        angles = list(range(ANGLE_MIN, ANGLE_MAX + 1, step))

    for angle in angles:
        lo, hi = POWER_MIN, POWER_MAX
        x_lo   = _sim(angle, lo)
        x_hi   = _sim(angle, hi)

        # Skip if target is outside the reachable range for this angle
        if target_sd < min(x_lo, x_hi) - 0.05:
            continue
        if target_sd > max(x_lo, x_hi) + 0.05:
            continue

        # Binary search for power
        for _ in range(30):
            mid   = (lo + hi) / 2
            x_mid = _sim(angle, mid)
            if x_mid < target_sd:
                lo = mid
            else:
                hi = mid

        best_p = (lo + hi) / 2
        err    = _sim(angle, best_p) - target_sd
        results.append(ShotResult(angle=float(angle), power=round(best_p, 2), error=err))

    return results


def solve_v2(
    target_sd: float,
    mobile: str,
    cfg: dict,
    wind_strength: float,
    wind_angle_deg: float,
    height_diff: float,
) -> list[ShotResult]:
    """Coarse→refine solver for v2.

    Returns up to MAX_SUGGESTIONS ShotResult objects sorted by angle.
    """
    # Coarse pass
    coarse = _solve_for_target(
        target_sd, mobile, cfg, wind_strength, wind_angle_deg, height_diff,
        angle_step=SOLVER_COARSE_STEP, power_steps=SOLVER_POWER_STEPS,
    )

    # Refine: expand ±3° around each coarse hit, sweep every integer degree
    refined_angles: set[int] = set()
    for r in coarse:
        for da in range(-3, 4):
            a = int(r.angle) + da
            if ANGLE_MIN <= a <= ANGLE_MAX:
                refined_angles.add(a)

    # If no coarse hits at all, sweep everything at integer steps
    if not refined_angles:
        refined_angles = set(range(ANGLE_MIN, ANGLE_MAX + 1))

    refined = _solve_for_target(
        target_sd, mobile, cfg, wind_strength, wind_angle_deg, height_diff,
        angle_step=1, power_steps=SOLVER_POWER_STEPS * 2,
        angle_subset=refined_angles,
    )

    # Keep only the best power per integer angle
    best_by_angle: dict[int, ShotResult] = {}
    for r in refined:
        key = int(round(r.angle))
        if key not in best_by_angle or abs(r.error) < abs(best_by_angle[key].error):
            best_by_angle[key] = r

    results = sorted(best_by_angle.values(), key=lambda r: r.angle)

    # De-duplicate: suppress adjacent angles with nearly identical power
    # Two shots suppressed if within ±3° AND power difference < 0.08
    deduped = []
    for r in results:
        if deduped and abs(r.angle - deduped[-1].angle) <= 3 and abs(r.power - deduped[-1].power) < 0.08:
            continue
        deduped.append(r)

    # Prefer a spread across the angle range; pick up to MAX_SUGGESTIONS
    # biased toward the "useful" GunBound range (roughly 45–80°).
    preferred = [r for r in deduped if 45 <= r.angle <= 80]
    others    = [r for r in deduped if r.angle < 45 or r.angle > 80]

    # Pick evenly-spaced suggestions from preferred range
    if len(preferred) > MAX_SUGGESTIONS:
        step = len(preferred) / MAX_SUGGESTIONS
        preferred = [preferred[int(i * step)] for i in range(MAX_SUGGESTIONS)]

    chosen = preferred[:MAX_SUGGESTIONS]
    remaining_slots = MAX_SUGGESTIONS - len(chosen)
    if remaining_slots > 0:
        chosen = others[:remaining_slots] + chosen

    return sorted(chosen, key=lambda r: r.angle)


# ─────────────────────────────────────────────────────────────────────────────
# Data-confidence layer
# ─────────────────────────────────────────────────────────────────────────────

def find_similar_shots_v2(
    training_data: list,
    mobile: str,
    sd: float,
    wind_strength: float,
    wind_angle: float,
    height_diff: float,
) -> list[tuple[float, dict]]:
    """Return (d_sim, record) pairs for shots within MATCH_LOOSE_THRESHOLD.

    Wind is compared as integer (wx, wy) components — not raw angle — so
    direction reversal and strength are both captured in a single distance.
    Results sorted by d_sim ascending.
    """
    if not training_data:
        return []
    qwx, qwy = wind_components_v2(wind_strength, wind_angle)
    results = []
    for d in training_data:
        if d["mobile"] != mobile:
            continue
        dwx, dwy = wind_components_v2(d["wind_strength"], d["wind_angle"])
        d_sim = math.sqrt(
            ((sd - d["actual_sd"]) / 2) ** 2 +
            ((qwx - dwx) / 26) ** 2 +
            ((qwy - dwy) / 26) ** 2 +
            ((height_diff - d["height_diff"]) / 4) ** 2
        )
        if d_sim < MATCH_LOOSE_THRESHOLD:
            results.append((d_sim, d))
    results.sort(key=lambda x: x[0])
    return results


def cluster_training_matches(
    close_matches: list[tuple[float, dict]],
) -> list[tuple[float, float, int, float]]:
    """Group close data matches into (angle, power, n_samples, spread) clusters.

    Two shots are in the same cluster when within ±3° angle and ±0.1 power.
    spread = std(actual_sd) within cluster (0.0 when n=1).
    Sorted by n_samples descending (most-sampled cluster first).
    """
    clusters: list[list] = []  # [rep_angle, rep_power, [actual_sd, ...]]
    for _, d in close_matches:
        placed = False
        for c in clusters:
            if abs(d["angle"] - c[0]) <= 3 and abs(d["power"] - c[1]) <= 0.1:
                c[2].append(d["actual_sd"])
                placed = True
                break
        if not placed:
            clusters.append([d["angle"], d["power"], [d["actual_sd"]]])
    result = []
    for angle, power, sd_list in clusters:
        n      = len(sd_list)
        mean   = sum(sd_list) / n
        spread = math.sqrt(sum((x - mean) ** 2 for x in sd_list) / n) if n > 1 else 0.0
        result.append((angle, round(power, 2), n, round(spread, 4)))
    result.sort(key=lambda x: -x[2])
    return result


def _compute_residual_correction_v2(
    similar_shots: list[tuple[float, dict]],
    cfg: dict,
    mobile: str,
) -> float:
    """Mean signed error (simulate_shot_v2 − actual) over nearby training shots.

    Positive → model overshoots → caller should raise the physics target SD.
    Negative → model undershoots → caller should lower the physics target SD.
    """
    if not similar_shots:
        return 0.0
    v_scale   = cfg.get("v_scale",      1.45)
    power_exp = cfg.get("power_exp",    1.0)
    wind_x    = cfg.get("wind_x_coeff", 0.10)
    wind_y    = cfg.get("wind_y_coeff", 0.10)
    errors = []
    for _, d in similar_shots:
        predicted = simulate_shot_v2(
            d["angle"], d["power"], mobile,
            v_scale, power_exp, wind_x, wind_y,
            d["wind_strength"], d["wind_angle"], d["height_diff"],
        )
        errors.append(predicted - d["actual_sd"])
    return sum(errors) / len(errors)


def suggest_shots_v2(
    mobiles_cfg: dict,
    mobile: str,
    sd: float,
    wind_strength: float,
    wind_angle: float,
    height_diff: float = 0.0,
    training_data: list | None = None,
) -> list[ShotResult]:
    """Hybrid suggestion: data-matched shots first, physics fills remaining slots.

    Tier 1 (highest confidence): shots from training data with d_sim < MATCH_CLOSE_THRESHOLD.
      Returns the most-sampled angle/power cluster(s).
    Tier 2: physics solver with residual-corrected target SD.
      Residual correction = mean(simulated − actual) over all loose matches.
      Positive correction → raise target so solver aims further.
    """
    training_data = training_data or []
    cfg           = mobiles_cfg.get(mobile, {})

    similar = find_similar_shots_v2(training_data, mobile, sd,
                                     wind_strength, wind_angle, height_diff)
    close   = [(s, d) for s, d in similar if s < MATCH_CLOSE_THRESHOLD]

    results:     list[ShotResult] = []
    used_angles: set[float]       = set()

    # ── Tier 1: direct data matches ───────────────────────────────────────────
    for angle, power, n_samples, spread in cluster_training_matches(close):
        if any(abs(angle - a) < 3 for a in used_angles):
            continue
        results.append(ShotResult(
            angle=angle, power=power, error=spread,
            source="data", n_samples=n_samples,
        ))
        used_angles.add(angle)
        if len(results) >= MAX_SUGGESTIONS:
            break

    # ── Tier 2: physics with residual correction ──────────────────────────────
    if len(results) < MAX_SUGGESTIONS:
        correction = _compute_residual_correction_v2(similar, cfg, mobile)
        adj_target = sd + correction
        for r in solve_v2(adj_target, mobile, cfg,
                           wind_strength, wind_angle, height_diff):
            if len(results) >= MAX_SUGGESTIONS:
                break
            if any(abs(r.angle - a) < 3 for a in used_angles):
                continue
            results.append(r)
            used_angles.add(r.angle)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Training mode
# ─────────────────────────────────────────────────────────────────────────────

def training_mode_v2(mobiles_cfg: dict) -> None:
    """CLI loop: manually record known shots into training_data.json."""
    training_data = _load_training()

    print("=== calc_v2 Training mode — record known shots ===")
    print(f"  Known mobiles: {', '.join(KNOWN_MOBILES)}")

    while True:
        mobile = input("Mobile: ").strip().lower()
        if mobile in KNOWN_MOBILES:
            break
        print(f"  Unknown mobile. Choose from: {', '.join(KNOWN_MOBILES)}")

    added = 0
    while True:
        try:
            print()
            angle         = _prompt_float("Angle (degrees): ", 0.0, 90.0)
            power         = _prompt_float("Power (bars): ", POWER_MIN, POWER_MAX)
            wind_strength = _prompt_float("Wind strength (0–26): ", 0.0, 26.0)
            wind_angle    = _prompt_float(
                "Wind angle (0=up, 90=toward enemy, -90=away, ±180=down): ", -180.0, 180.0
            )
            height_diff   = _prompt_float(
                "Height diff (positive = you are higher than enemy): ", -1.0, 1.0
            )
            actual_sd     = _prompt_float("Actual landing SD: ", 0.05, 5.0)

            sample = {
                "mobile":        mobile,
                "angle":         angle,
                "power":         power,
                "wind_strength": wind_strength,
                "wind_angle":    wind_angle,
                "height_diff":   height_diff,
                "actual_sd":     actual_sd,
            }
            training_data.append(sample)
            with open(TRAINING_FILE, "w", encoding="utf-8") as f:
                json.dump(training_data, f, indent=2)
            added += 1
            print(f"  Recorded. ({added} this session, {len(training_data)} total)")

            again = input("  Another shot? (y/n): ").strip().lower()
            if again != "y":
                break
        except (ValueError, EOFError, KeyboardInterrupt):
            break

    if added > 0:
        shots_for_mobile = [d for d in training_data if d["mobile"] == mobile]
        print(f"\n  Recalibrating {mobile} on {len(shots_for_mobile)} shot(s)…")
        v_scale, power_exp, wind_x, wind_y = calibrate_v2(shots_for_mobile, mobile)
        if mobile not in mobiles_cfg:
            mobiles_cfg[mobile] = {}
        mobiles_cfg[mobile]["v_scale"]      = round(v_scale,    6)
        mobiles_cfg[mobile]["power_exp"]    = round(power_exp,  6)
        mobiles_cfg[mobile]["wind_x_coeff"] = round(wind_x,     6)
        mobiles_cfg[mobile]["wind_y_coeff"] = round(wind_y,     6)
        _save_mobiles(mobiles_cfg)
        print(f"  v_scale={v_scale:.4f}  power_exp={power_exp:.4f}  wind_x={wind_x:.4f}  wind_y={wind_y:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# Main calculator loop
# ─────────────────────────────────────────────────────────────────────────────

def _prompt_float(prompt: str, lo: float, hi: float) -> float:
    while True:
        try:
            val = float(input(prompt))
            if lo <= val <= hi:
                return val
            print(f"  Enter a value between {lo} and {hi}.")
        except ValueError:
            print("  Invalid — enter a number.")


def _prompt_choice(prompt: str, choices: list[str]) -> str:
    choices_lower = [c.lower() for c in choices]
    while True:
        val = input(prompt).strip().lower()
        if val in choices_lower:
            return val
        print(f"  Choose from: {', '.join(choices)}")


KNOWN_MOBILES = sorted(MOBILE_PHYSICS.keys())


def main() -> None:
    # ── CLI flags ──────────────────────────────────────────────────────────
    if "--calibrate" in sys.argv:
        print("\n=== calc_v2 — Calibration ===")
        cfg           = _load_mobiles()
        training_data = _load_training()
        print(f"  Loaded {len(training_data)} training shot(s) from {TRAINING_FILE}")
        recalibrate_all_v2(cfg, training_data)
        print("\nDone.")
        return

    if "--validate" in sys.argv:
        print("\n=== calc_v2 — Validation ===")
        cfg           = _load_mobiles()
        training_data = _load_training()
        print(f"  Loaded {len(training_data)} shot(s) | {len(cfg)} calibrated mobiles\n")
        validate_v2(cfg, training_data)
        return

    mobiles_cfg   = _load_mobiles()
    training_data = _load_training()

    if "--training" in sys.argv:
        training_mode_v2(mobiles_cfg)
        return

    # ── Normal calculator loop ─────────────────────────────────────────────
    print("\n=== GunBound Shot Calculator v2 ===")
    print(f"  Calibrated mobiles: {', '.join(sorted(mobiles_cfg.keys()))}")
    print(f"  Training shots loaded: {len(training_data)}")
    print("  Type 'exit' to quit.\n")

    while True:
        # Mobile
        mobile_input = input("Mobile: ").strip().lower()
        if mobile_input in ("exit", "quit", "q"):
            break
        if mobile_input not in mobiles_cfg:
            if mobile_input in KNOWN_MOBILES:
                print(f"  '{mobile_input}' not calibrated yet — using derived defaults.")
                armor_vs = mobiles_cfg.get("armor", {}).get("v_scale", 1.45)
                mobiles_cfg[mobile_input] = {
                    "v_scale":      default_v_scale(mobile_input, armor_vs),
                    "wind_x_coeff": 0.10,
                    "wind_y_coeff": 0.10,
                }
            else:
                print(f"  Unknown mobile '{mobile_input}'. Known: {', '.join(KNOWN_MOBILES)}")
                continue

        try:
            target_sd     = _prompt_float("Target SD (0.1–3.0): ", 0.1, 3.0)
            wind_strength = _prompt_float("Wind strength (0–26): ", 0.0, 26.0)
            wind_angle    = _prompt_float(
                "Wind angle (0=up, 90=toward enemy, -90=away, ±180=down): ", -180.0, 180.0
            )
            height_diff   = _prompt_float(
                "Height diff (positive = you are higher than enemy, -1.0 to 1.0): ", -1.0, 1.0
            )
        except (EOFError, KeyboardInterrupt):
            break

        shots = suggest_shots_v2(
            mobiles_cfg, mobile_input, target_sd,
            wind_strength, wind_angle, height_diff,
            training_data=training_data,
        )

        if not shots:
            print("  No solution found — check inputs.\n")
            continue

        print(f"\n  Suggestions for {mobile_input.upper()} @ {target_sd} SD  "
              f"(wind {wind_strength}@{wind_angle:+.0f}°  height {height_diff:+.2f}):")
        for i, r in enumerate(shots, 1):
            if r.source == "data":
                tag = f"data: {r.n_samples} shot(s), ±{r.error:.3f} SD spread"
            else:
                tag = f"physics, err {r.error:+.4f} SD"
            print(f"    {i}) angle={r.angle:4.0f}°  power={r.power:.2f}  [{tag}]")
        print()

        # Optional: record the shot used
        choice = input("  Which did you use? (1–5 or Enter to skip): ").strip()
        if choice in [str(i) for i in range(1, len(shots) + 1)]:
            chosen = shots[int(choice) - 1]
            try:
                actual_sd = _prompt_float("  Where did it land (SD)? ", 0.05, 5.0)
            except (EOFError, KeyboardInterrupt):
                print()
                continue
            sample = {
                "mobile":        mobile_input,
                "angle":         chosen.angle,
                "power":         chosen.power,
                "wind_strength": wind_strength,
                "wind_angle":    wind_angle,
                "height_diff":   height_diff,
                "actual_sd":     actual_sd,
            }
            training_data.append(sample)
            with open(TRAINING_FILE, "w", encoding="utf-8") as f:
                json.dump(training_data, f, indent=2)
            print(f"  Recorded. ({len(training_data)} total shots)")

            # Auto-recalibrate after every 5 new shots
            mobile_shots = [d for d in training_data if d["mobile"] == mobile_input]
            if len(mobile_shots) % 5 == 0 and len(mobile_shots) >= 3:
                print(f"  Auto-recalibrating {mobile_input} ({len(mobile_shots)} shots)…", end=" ")
                vs, pe, wx, wy = calibrate_v2(mobile_shots, mobile_input)
                mobiles_cfg[mobile_input]["v_scale"]      = round(vs, 6)
                mobiles_cfg[mobile_input]["power_exp"]    = round(pe, 6)
                mobiles_cfg[mobile_input]["wind_x_coeff"] = round(wx, 6)
                mobiles_cfg[mobile_input]["wind_y_coeff"] = round(wy, 6)
                _save_mobiles(mobiles_cfg)
                print(f"v_scale={vs:.4f}  power_exp={pe:.4f}  wind_x={wx:.4f}  wind_y={wy:.4f}")
        print()


if __name__ == "__main__":
    main()
