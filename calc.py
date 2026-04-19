import json
import os
import math
import random
import sys
from dataclasses import dataclass

# ------------------------
# Models
# ------------------------

@dataclass
class ShotResult:
    angle: float
    power: float
    error: float       # SD spread (data match) or solver error (physics)
    source: str = "physics"   # "data" or "physics"
    n_samples: int = 0        # number of training shots behind this suggestion


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRAINING_FILE = os.path.join(BASE_DIR, "training_data.json")
MOBILES_FILE = os.path.join(BASE_DIR, "mobiles.json")

def load_mobiles():
    with open(MOBILES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_mobiles(mobiles):
    with open(MOBILES_FILE, "w", encoding="utf-8") as f:
        json.dump(mobiles, f, indent=2)

# ------------------------
# Persistence
# ------------------------

def load_training_data():
    if not os.path.exists(TRAINING_FILE):
        return []
    with open(TRAINING_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_training_data(data):
    with open(TRAINING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ------------------------
# Band helpers
# ------------------------

BAND_THRESHOLDS = [
    ("short", 0.0,  0.75),
    ("mid",   0.75, 1.25),
    ("long",  1.25, float("inf")),
]

def get_band_name(sd):
    for name, lo, hi in BAND_THRESHOLDS:
        if lo <= sd < hi:
            return name
    return "long"

def get_effective_cfg(mobile_cfg, sd):
    band = get_band_name(sd)
    band_params = mobile_cfg["bands"][band]
    return {
        "gravity": mobile_cfg["gravity"],
        "v_scale": band_params["v_scale"],
        "wind_x_coeff": band_params["wind_x_coeff"],
        "wind_y_coeff": band_params["wind_y_coeff"],
    }

# ------------------------
# Physics
# ------------------------

def wind_components(W, theta):
    θ = math.radians(theta)
    wx = W * math.sin(θ)
    wy = W * math.cos(θ)
    return wx, wy

def simulate_shot(angle_deg, power, mobile_cfg, wind_strength, wind_angle, height_diff):
    g = mobile_cfg["gravity"]
    v_scale = mobile_cfg["v_scale"]

    vx = power * v_scale * math.cos(math.radians(angle_deg))
    vy = power * v_scale * math.sin(math.radians(angle_deg))

    wx, wy = wind_components(wind_strength, wind_angle)

    x = 0.0
    y = float(height_diff)
    dt = 0.05

    for _ in range(1000):
        vx += wx * mobile_cfg["wind_x_coeff"] * dt
        vy += wy * mobile_cfg["wind_y_coeff"] * dt
        x += vx * dt
        y += vy * dt
        vy -= g * dt
        if y <= 0:
            break

    return x

STRONG_WIND_THRESHOLD = 14   # wind bars above which high angles become unstable
STRONG_WIND_ANGLE_MAX  = 72  # inclusive upper bound when strong wind + mid/long
HIGH_ANGLE_SD_TOL      = 0.15  # how close a training shot's actual_sd must be to trust it
MATCH_CLOSE_THRESHOLD  = 0.08  # d_sim below this → use as a direct data suggestion
MATCH_LOOSE_THRESHOLD  = 0.15  # d_sim below this → use for residual correction

def _has_high_angle_evidence(training_data, mobile, band, wind_strength, target_sd):
    """Return True if training data contains a successful high-angle shot under
    strong-wind conditions close to the requested distance."""
    if not training_data:
        return False
    for d in training_data:
        if (
            d["mobile"] == mobile
            and get_band_name(d["actual_sd"]) == band
            and d["wind_strength"] > STRONG_WIND_THRESHOLD
            and d["angle"] > STRONG_WIND_ANGLE_MAX
            and abs(d["actual_sd"] - target_sd) <= HIGH_ANGLE_SD_TOL
        ):
            return True
    return False

def solve_shot_physics_multi(mobiles, mobile, sd, wind_strength, wind_angle, height_diff=0.0, top_k=3, training_data=None):
    cfg = mobiles[mobile]
    target = sd
    effective_cfg = get_effective_cfg(cfg, target)

    # Cap max angle for strong winds on mid/long shots: high-angle trajectories
    # spend much longer in the air and can snap back entirely, making them
    # unreliable in practice even if the simulation finds a mathematical solution.
    # Exception: if training data shows a high-angle shot working near this
    # distance under similar wind, trust the evidence and open the full range.
    band = get_band_name(target)
    if (
        wind_strength > STRONG_WIND_THRESHOLD
        and band in ("mid", "long")
        and not _has_high_angle_evidence(training_data, mobile, band, wind_strength, target)
    ):
        a_hi = STRONG_WIND_ANGLE_MAX + 1   # +1 because range() is exclusive
    else:
        a_hi = 86

    # ── Coarse pass: angle step 5°, power step 0.25 ───────────────────────────
    coarse = []
    for angle in range(20, a_hi, 5):
        for power in [x * 0.25 for x in range(2, 25)]:  # 0.5 … 6.0
            dist = simulate_shot(angle, power, effective_cfg, wind_strength, wind_angle, height_diff)
            coarse.append((abs(dist - target), angle, power))

    coarse.sort(key=lambda x: x[0])

    # Pick the best coarse seed from each 10° angle bin so the refine pass
    # always explores diverse angle regions, not just the locally best cluster.
    bins: dict[int, tuple] = {}
    for entry in coarse:
        _, angle, _ = entry
        b = angle // 10
        if b not in bins:
            bins[b] = entry
    seeds = sorted(bins.values(), key=lambda x: x[0])[:15]

    # ── Refine pass: ±6° around each seed angle, fine power step 0.02 ─────────
    seen = set()
    candidates = []
    for _, seed_angle, seed_power in seeds:
        for angle in range(max(20, seed_angle - 6), min(a_hi, seed_angle + 7)):
            if angle in seen:
                continue
            seen.add(angle)
            p_lo = max(0.5,  round(seed_power - 0.3, 2))
            p_hi = min(6.0,  round(seed_power + 0.3, 2))
            p = p_lo
            while p <= p_hi + 1e-9:
                dist = simulate_shot(angle, p, effective_cfg, wind_strength, wind_angle, height_diff)
                candidates.append((abs(dist - target), angle, round(p, 2)))
                p = round(p + 0.02, 2)

    candidates.sort(key=lambda x: x[0])

    best_err = candidates[0][0] if candidates else 0.0
    err_cutoff = best_err + 0.05

    results = []
    used_angles = set()

    for err, angle, power in candidates:
        if err > err_cutoff:
            break
        if any(abs(angle - a) < 3 for a in used_angles):
            continue
        results.append(ShotResult(angle=angle, power=round(power, 2), error=round(err, 4)))
        used_angles.add(angle)
        if len(results) >= top_k:
            break

    return results

# ------------------------
# Data-confidence layer
# ------------------------

def find_similar_shots(training_data, mobile, sd, wind_strength, wind_angle, height_diff):
    """Return (d_sim, record) pairs for training shots within MATCH_LOOSE_THRESHOLD,
    sorted by d_sim ascending. Wind is compared as effect components (wx, wy),
    not raw angle, so direction reversal and strength are both captured."""
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


def cluster_training_matches(close_matches):
    """Group close data matches into (angle, power) clusters.
    Returns list of (angle, power, n_samples, spread) sorted by n_samples desc.
    spread = std(actual_sd) within the cluster."""
    clusters = []  # each entry: [rep_angle, rep_power, [actual_sd, ...]]
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
        n = len(sd_list)
        mean = sum(sd_list) / n
        spread = math.sqrt(sum((x - mean) ** 2 for x in sd_list) / n) if n > 1 else 0.0
        result.append((angle, round(power, 2), n, round(spread, 4)))
    result.sort(key=lambda x: -x[2])  # most-sampled cluster first
    return result


def _compute_residual_correction(similar_shots, mobiles, mobile):
    """Mean signed error (simulate − actual) over nearby training shots.
    Positive → model overshoots; caller compensates by raising the physics target SD."""
    if not similar_shots:
        return 0.0
    cfg = mobiles[mobile]
    errors = []
    for _, d in similar_shots:
        effective_cfg = get_effective_cfg(cfg, d["actual_sd"])
        predicted = simulate_shot(
            d["angle"], d["power"], effective_cfg,
            d["wind_strength"], d["wind_angle"], d["height_diff"]
        )
        errors.append(predicted - d["actual_sd"])
    return sum(errors) / len(errors)


def suggest_shots(mobiles, mobile, sd, wind_strength, wind_angle, height_diff=0.0, top_k=3, training_data=None):
    """Hybrid suggestion: data-matched shots first, physics estimates fill remaining slots.
    Physics target is residual-corrected when nearby training shots are available."""
    training_data = training_data or []

    similar = find_similar_shots(training_data, mobile, sd, wind_strength, wind_angle, height_diff)
    close   = [(s, d) for s, d in similar if s < MATCH_CLOSE_THRESHOLD]

    results     = []
    used_angles = set()

    # ── Tier 1: direct data matches (highest confidence) ─────────────────────
    for angle, power, n_samples, spread in cluster_training_matches(close):
        if any(abs(angle - a) < 3 for a in used_angles):
            continue
        results.append(ShotResult(angle=angle, power=power, error=spread,
                                   source="data", n_samples=n_samples))
        used_angles.add(angle)
        if len(results) >= top_k:
            break

    # ── Tier 2: physics, adjusted by local residual ───────────────────────────
    if len(results) < top_k:
        correction = _compute_residual_correction(similar, mobiles, mobile)
        adj_target = sd + correction   # positive correction → model overshoots → aim higher
        for r in solve_shot_physics_multi(
            mobiles, mobile, adj_target, wind_strength, wind_angle,
            height_diff, top_k=top_k, training_data=training_data
        ):
            if len(results) >= top_k:
                break
            if any(abs(r.angle - a) < 3 for a in used_angles):
                continue
            results.append(r)
            used_angles.add(r.angle)

    return results


# ------------------------
# Calibration
# ------------------------

def calibrate_mobile(data, iterations=3000):
    best = None
    best_err = float("inf")

    for _ in range(iterations):
        candidate = (
            random.uniform(0.85, 1.20),   # v_scale
            random.uniform(0.1,  2.0),    # wind_x_coeff  (continuous force, ~0.8 nominal)
            random.uniform(0.05, 1.0),    # wind_y_coeff  (continuous force, ~0.4 nominal)
        )

        v_scale, wind_x, wind_y = candidate

        total_error = 0.0

        for d in data:
            cfg = {
                "gravity": 9.8,
                "v_scale": v_scale,
                "wind_x_coeff": wind_x,
                "wind_y_coeff": wind_y,
            }

            predicted = simulate_shot(
                d["angle"],
                d["power"],
                cfg,
                d["wind_strength"],
                d["wind_angle"],
                d["height_diff"]
            )

            actual = d["actual_sd"]
            weight = 1.0 / (1.0 + abs(actual))
            total_error += weight * (predicted - actual) ** 2

        if total_error < best_err:
            best_err = total_error
            best = candidate

    return best

def recalibrate_all(mobiles, training_data):
    changed = False

    for mobile in mobiles.keys():
        mobile_data = [d for d in training_data if d["mobile"] == mobile]

        for band_name, lo, hi in BAND_THRESHOLDS:
            band_data = [d for d in mobile_data if lo <= d["actual_sd"] < hi]

            if len(band_data) < 3:
                if band_data:
                    print(f"  {mobile}/{band_name}: {len(band_data)} sample(s), need 3 to calibrate.")
                continue

            v_scale, wx, wy = calibrate_mobile(band_data)
            mobiles[mobile]["bands"][band_name]["v_scale"] = v_scale
            mobiles[mobile]["bands"][band_name]["wind_x_coeff"] = wx
            mobiles[mobile]["bands"][band_name]["wind_y_coeff"] = wy

            print(f"  {mobile}/{band_name}: v_scale={v_scale:.4f}, wind_x={wx:.4f}, wind_y={wy:.4f}")
            changed = True

    if changed:
        save_mobiles(mobiles)

# ------------------------
# Training mode
# ------------------------

def training_mode():
    """Manually record known shots into training_data.json (no solver)."""
    mobiles = load_mobiles()
    training_data = load_training_data()

    print("=== Training mode — record known shots ===")
    print("Available mobiles:", list(mobiles.keys()))

    while True:
        mobile = input("Select mobile: ").strip().lower()
        if mobile in mobiles:
            break
        print(f"Unknown mobile '{mobile}'. Choose from: {list(mobiles.keys())}")

    added = 0
    while True:
        try:
            print()
            angle = float(input("Angle (degrees): "))
            power = float(input("Power (bars): "))

            wind_strength = float(input("Wind strength (0-26): "))
            if not 0 <= wind_strength <= 26:
                print("Invalid wind strength, skipping.")
                continue

            while True:
                wind_angle = float(input("Wind angle (-180 to 180): "))
                if -180 <= wind_angle <= 180:
                    break
                print("Wind angle must be between -180 and 180.")

            height_diff_input = input("Height diff (default 0): ").strip()
            height_diff = float(height_diff_input) if height_diff_input else 0.0

            actual_sd = float(input("Actual landing SD: "))

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
            save_training_data(training_data)
            added += 1
            print(f"Recorded. ({added} added this session, {len(training_data)} total)")

            again = input("Another shot? (y/n): ").strip().lower()
            if again != "y":
                break

        except ValueError as e:
            print("Invalid input:", e)

    if added > 0:
        print(f"\nSaved {added} sample(s). Recalibrating...")
        recalibrate_all(mobiles, training_data)


# ------------------------
# Main
# ------------------------

def main():
    if "--training" in sys.argv:
        training_mode()
        return

    mobiles = load_mobiles()
    training_data = load_training_data()

    print("Available mobiles:", list(mobiles.keys()))
    while True:
        mobile = input("Select mobile: ").strip().lower()
        if mobile in mobiles:
            break
        print(f"Unknown mobile '{mobile}'. Choose from: {list(mobiles.keys())}")

    while True:
        try:
            sd = float(input("SD (screen distance): "))
            if sd <= 0:
                print("SD must be positive.")
                continue

            wind_strength = float(input("Wind strength (0-26): "))
            if not 0 <= wind_strength <= 26:
                print("Invalid wind strength.")
                continue

            while True:
                wind_angle = float(input("Wind angle (-180 to 180): "))
                if -180 <= wind_angle <= 180:
                    break
                print("Wind angle must be between -180 and 180.")

            height_diff_input = input("Height diff (-2 to 2, default 0): ").strip()
            height_diff = float(height_diff_input) if height_diff_input else 0.0
            if not -2 <= height_diff <= 2:
                print("Height diff out of range, using 0.")
                height_diff = 0.0

            results = suggest_shots(
                mobiles,
                mobile,
                sd,
                wind_strength,
                wind_angle,
                height_diff,
                training_data=training_data,
            )

            print("Suggested shots:")
            for i, r in enumerate(results, 1):
                if r.source == "data":
                    tag = f"[data: {r.n_samples} shot(s), ±{r.error:.3f} SD spread]"
                else:
                    tag = f"[physics, err ±{r.error} SD]"
                print(f"{i}) Angle: {r.angle}°, Power: {r.power}  {tag}")

            choice = input("Which shot did you use? (1-3 or skip): ").strip().lower()

            if choice in ["1", "2", "3"]:
                idx = int(choice) - 1
                if idx >= len(results):
                    print("That option does not exist.")
                    continue

                chosen = results[idx]
                actual_sd = float(input("Where did it land (SD)? "))

                sample = {
                    "mobile": mobile,
                    "angle": chosen.angle,
                    "power": chosen.power,
                    "wind_strength": wind_strength,
                    "wind_angle": wind_angle,
                    "height_diff": height_diff,
                    "actual_sd": actual_sd
                }

                training_data.append(sample)
                save_training_data(training_data)
                print("Shot recorded.")

                if len(training_data) % 10 == 0:
                    print("Recalibrating...")
                    recalibrate_all(mobiles, training_data)

            again = input("Another shot? (y/n): ").strip().lower()
            if again != "y":
                break

        except ValueError as e:
            print("Invalid input:", e)

if __name__ == "__main__":
    main()
