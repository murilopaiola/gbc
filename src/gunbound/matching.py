"""
matching.py — Data-confidence layer for the GunBound shot calculator.

Combines real training shots with physics suggestions using a two-tier approach:

  Tier 1 (highest confidence): shots from training data with d_sim < MATCH_CLOSE_THRESHOLD.
    Returns the most-sampled angle/power cluster(s) directly.
  Tier 2: physics solver with residual-corrected target SD.
    The residual correction is the mean signed error (simulated − actual) over
    all loose matches. A positive correction means the model overshoots, so the
    solver target is raised to compensate.
"""

import math

from .constants import (
    MATCH_CLOSE_THRESHOLD, MATCH_LOOSE_THRESHOLD, MAX_SUGGESTIONS,
    POWER_MIN, POWER_MAX,
)
from .models import ShotResult
from .physics import simulate_shot, wind_components
from .solver import solve


def find_similar_shots(
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
    qwx, qwy = wind_components(wind_strength, wind_angle)
    results = []
    for d in training_data:
        if d["mobile"] != mobile:
            continue
        dwx, dwy = wind_components(d["wind_strength"], d["wind_angle"])
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


def compute_residual_correction(
    similar_shots: list[tuple[float, dict]],
    cfg: dict,
    mobile: str,
) -> float:
    """Mean signed error (simulate_shot − actual) over nearby training shots.

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
        predicted = simulate_shot(
            d["angle"], d["power"], mobile,
            v_scale, power_exp, wind_x, wind_y,
            d["wind_strength"], d["wind_angle"], d["height_diff"],
        )
        errors.append(predicted - d["actual_sd"])
    return sum(errors) / len(errors)


def _min_angle_for_height(height_diff: float) -> int:
    """Return the minimum practical launch angle when shooter is below target.

    height_diff < 0 means target is above shooter.  Low angles produce a flat
    trajectory that can't arc high enough to reach a nearby elevated target.
    Returns 45 (no restriction) when the shooter is level or above.
    """
    if height_diff >= -0.02:
        return 45
    if height_diff < -0.1:
        return 70
    if height_diff < -0.05:
        return 60
    return 55  # -0.02 to -0.05


def _corrected_power(
    angle: float,
    target_sd: float,
    mobile: str,
    cfg: dict,
    wind_strength: float,
    wind_angle: float,
    height_diff: float,
) -> float:
    """Binary-search power so simulate_shot hits target_sd at the given angle.

    40 iterations give < 0.0001 power resolution. Returns raw value rounded to 2dp.
    Falls back to POWER_MAX if the angle cannot reach target_sd at any power.
    """
    v_scale   = cfg.get("v_scale",      1.45)
    power_exp = cfg.get("power_exp",    1.0)
    wind_x    = cfg.get("wind_x_coeff", 0.10)
    wind_y    = cfg.get("wind_y_coeff", 0.10)
    lo, hi = POWER_MIN, POWER_MAX
    for _ in range(40):
        mid = (lo + hi) / 2
        result = simulate_shot(
            angle, mid, mobile,
            v_scale, power_exp, wind_x, wind_y,
            wind_strength, wind_angle, height_diff,
        )
        if result < target_sd:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2, 2)


def suggest_shots(
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

    similar = find_similar_shots(training_data, mobile, sd,
                                 wind_strength, wind_angle, height_diff)
    close   = [(s, d) for s, d in similar if s < MATCH_CLOSE_THRESHOLD]

    results:     list[ShotResult] = []
    used_angles: set[float]       = set()

    min_angle = _min_angle_for_height(height_diff)

    # ── Tier 1: direct data matches ───────────────────────────────────────────
    for angle, power, n_samples, spread in cluster_training_matches(close):
        if angle < min_angle:
            continue
        if any(abs(angle - a) < 3 for a in used_angles):
            continue
        corrected = _corrected_power(
            angle, sd, mobile, cfg,
            wind_strength, wind_angle, height_diff,
        )
        results.append(ShotResult(
            angle=angle, power=corrected, error=spread,
            source="data", n_samples=n_samples,
        ))
        used_angles.add(angle)
        if len(results) >= MAX_SUGGESTIONS:
            break

    # ── Tier 2: physics with residual correction ──────────────────────────────
    if len(results) < MAX_SUGGESTIONS:
        correction = compute_residual_correction(similar, cfg, mobile)
        adj_target = sd + correction
        for r in solve(adj_target, mobile, cfg,
                       wind_strength, wind_angle, height_diff):
            if len(results) >= MAX_SUGGESTIONS:
                break
            if any(abs(r.angle - a) < 3 for a in used_angles):
                continue
            results.append(r)
            used_angles.add(r.angle)

    return results
