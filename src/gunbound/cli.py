"""
cli.py — Command-line interface for the GunBound shot calculator.

Entry points:
  python main.py                 # interactive calculator loop
  python main.py --calibrate     # recalibrate all mobiles from training data
  python main.py --validate      # print per-shot errors for all training shots
  python main.py --training      # record new shots into training data
"""

import json
import sys

from .calibration import calibrate, recalibrate_all, validate
from .constants import KNOWN_MOBILES, POWER_MIN, POWER_MAX
from .matching import suggest_shots
from .physics import default_v_scale
from .storage import (
    TRAINING_FILE,
    load_mobiles,
    load_training,
    save_mobiles,
    save_training,
)


# ─────────────────────────────────────────────────────────────────────────────
# Input helpers
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


# ─────────────────────────────────────────────────────────────────────────────
# Training mode
# ─────────────────────────────────────────────────────────────────────────────

def training_mode(mobiles_cfg: dict) -> None:
    """CLI loop: manually record known shots into data/training_data.json."""
    training_data = load_training()

    print("=== GunBound Calculator — Training mode ===")
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
            save_training(training_data)
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
        v_scale, power_exp, wind_x, wind_y = calibrate(shots_for_mobile, mobile)
        if mobile not in mobiles_cfg:
            mobiles_cfg[mobile] = {}
        mobiles_cfg[mobile]["v_scale"]      = round(v_scale,    6)
        mobiles_cfg[mobile]["power_exp"]    = round(power_exp,  6)
        mobiles_cfg[mobile]["wind_x_coeff"] = round(wind_x,     6)
        mobiles_cfg[mobile]["wind_y_coeff"] = round(wind_y,     6)
        save_mobiles(mobiles_cfg)
        print(f"  v_scale={v_scale:.4f}  power_exp={power_exp:.4f}  wind_x={wind_x:.4f}  wind_y={wind_y:.4f}")


# ─────────────────────────────────────────────────────────────────────────────
# Main calculator loop
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── CLI flags ──────────────────────────────────────────────────────────
    if "--calibrate" in sys.argv:
        print("\n=== GunBound Calculator — Calibration ===")
        cfg           = load_mobiles()
        training_data = load_training()
        print(f"  Loaded {len(training_data)} training shot(s) from {TRAINING_FILE}")
        recalibrate_all(cfg, training_data)
        print("\nDone.")
        return

    if "--validate" in sys.argv:
        print("\n=== GunBound Calculator — Validation ===")
        cfg           = load_mobiles()
        training_data = load_training()
        print(f"  Loaded {len(training_data)} shot(s) | {len(cfg)} calibrated mobiles\n")
        validate(cfg, training_data)
        return

    mobiles_cfg   = load_mobiles()
    training_data = load_training()

    if "--training" in sys.argv:
        training_mode(mobiles_cfg)
        return

    # ── Normal calculator loop ─────────────────────────────────────────────
    print("\n=== GunBound Shot Calculator ===")
    print(f"  Calibrated mobiles: {', '.join(sorted(mobiles_cfg.keys()))}")
    print(f"  Training shots loaded: {len(training_data)}")
    print("  Type 'exit' to quit.\n")

    # Mobile — asked once at startup
    while True:
        mobile_input = input("Mobile: ").strip().lower()
        if mobile_input in ("exit", "quit", "q"):
            return
        if mobile_input in mobiles_cfg:
            break
        if mobile_input in KNOWN_MOBILES:
            print(f"  '{mobile_input}' not calibrated yet — using derived defaults.")
            armor_vs = mobiles_cfg.get("armor", {}).get("v_scale", 1.45)
            mobiles_cfg[mobile_input] = {
                "v_scale":      default_v_scale(mobile_input, armor_vs),
                "wind_x_coeff": 0.10,
                "wind_y_coeff": 0.10,
            }
            break
        print(f"  Unknown mobile '{mobile_input}'. Known: {', '.join(KNOWN_MOBILES)}")

    print(f"  Mobile set to: {mobile_input.upper()}\n")

    while True:
        try:
            target_sd     = _prompt_float("Target SD (0.1–3.0): ", 0.1, 3.0)
            height_diff   = _prompt_float(
                "Height diff (positive = you are higher, -1.0 to 1.0): ", -1.0, 1.0
            )
            wind_angle    = _prompt_float(
                "Wind angle (0=up, 90=toward enemy, -90=away, ±180=down): ", -180.0, 180.0
            )
            wind_strength = _prompt_float("Wind strength (0–26): ", 0.0, 26.0)
        except (EOFError, KeyboardInterrupt):
            break

        shots = suggest_shots(
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
            save_training(training_data)
            print(f"  Recorded. ({len(training_data)} total shots)")

            # Auto-recalibrate after every 5 new shots
            mobile_shots = [d for d in training_data if d["mobile"] == mobile_input]
            if len(mobile_shots) % 5 == 0 and len(mobile_shots) >= 3:
                print(f"  Auto-recalibrating {mobile_input} ({len(mobile_shots)} shots)…", end=" ")
                vs, pe, wx, wy = calibrate(mobile_shots, mobile_input)
                mobiles_cfg[mobile_input]["v_scale"]      = round(vs, 6)
                mobiles_cfg[mobile_input]["power_exp"]    = round(pe, 6)
                mobiles_cfg[mobile_input]["wind_x_coeff"] = round(wx, 6)
                mobiles_cfg[mobile_input]["wind_y_coeff"] = round(wy, 6)
                save_mobiles(mobiles_cfg)
                print(f"v_scale={vs:.4f}  power_exp={pe:.4f}  wind_x={wx:.4f}  wind_y={wy:.4f}")
        print()


if __name__ == "__main__":
    main()
