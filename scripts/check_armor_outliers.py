"""
Check for outliers in the armor shots dataset.

Outlier detection:
1. Physics residual: simulate each shot and compute |predicted_sd - actual_sd|
2. Statistical: IQR-based outlier flag on residuals
3. Monotonicity: for no-wind shots at same angle, SD should increase with power
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gunbound.storage import load_training, save_training, load_mobiles
from gunbound.physics import simulate_shot

def main():
    parser = argparse.ArgumentParser(description="Check for outliers in the armor shots dataset.")
    parser.add_argument("--delete-outliers", action="store_true",
                        help="Remove detected outliers from training_data.json")
    args = parser.parse_args()

    data = load_training()
    cfg = load_mobiles()

    armor = [s for s in data if s["mobile"] == "armor"]
    print(f"Total armor shots: {len(armor)}\n")

    if "armor" not in cfg:
        print("ERROR: armor not in mobiles_v2.json — run --calibrate first")
        return

    params = cfg["armor"]
    v_scale = params["v_scale"]
    power_exp = params["power_exp"]
    wx = params["wind_x_coeff"]
    wy = params["wind_y_coeff"]

    residuals = []
    for s in armor:
        pred = simulate_shot(
            angle_deg=s["angle"],
            power=s["power"],
            mobile="armor",
            v_scale=v_scale,
            power_exp=power_exp,
            wind_x_coeff=wx,
            wind_y_coeff=wy,
            wind_strength=s["wind_strength"],
            wind_angle_deg=s["wind_angle"],
            height_diff=s["height_diff"],
        )
        err = pred - s["actual_sd"]
        residuals.append(err)

    abs_res = [abs(r) for r in residuals]
    sorted_res = sorted(abs_res)
    n = len(sorted_res)
    q1 = sorted_res[n // 4]
    q3 = sorted_res[(3 * n) // 4]
    iqr = q3 - q1
    threshold = q3 + 1.5 * iqr
    mean_abs = sum(abs_res) / n

    print(f"MAE: {mean_abs:.4f} SD")
    print(f"Q1={q1:.4f}  Q3={q3:.4f}  IQR={iqr:.4f}  Outlier threshold (|err| > {threshold:.4f})\n")

    print(f"{'Idx':>4}  {'A':>3}  {'Pwr':>5}  {'W':>5}  {'WA':>5}  {'H':>5}  {'ActSD':>7}  {'PredSD':>7}  {'Err':>7}  Flag")
    print("-" * 80)

    outliers = []
    for i, (s, err) in enumerate(zip(armor, residuals)):
        pred = s["actual_sd"] + err
        flag = " *** OUTLIER" if abs(err) > threshold else ""
        print(
            f"{i:>4}  {s['angle']:>3}  {s['power']:>5.2f}  "
            f"{s['wind_strength']:>5.1f}  {s['wind_angle']:>5.0f}  "
            f"{s['height_diff']:>5.1f}  {s['actual_sd']:>7.3f}  "
            f"{pred:>7.3f}  {err:>+7.4f}{flag}"
        )
        if abs(err) > threshold:
            outliers.append((i, s, err))

    print()
    if outliers:
        print(f"==> {len(outliers)} outlier(s) found:")
        for idx, s, err in outliers:
            print(f"  [{idx}] angle={s['angle']}, power={s['power']}, "
                  f"wind={s['wind_strength']}@{s['wind_angle']}, "
                  f"height={s['height_diff']}, actual_sd={s['actual_sd']} "
                  f"(err={err:+.4f})")
    else:
        print("No outliers detected.")

    if args.delete_outliers:
        if not outliers:
            print("\nNothing to delete.")
        else:
            outlier_shots = {id(s) for _, s, _ in outliers}
            new_data = [s for s in data if not (s.get("mobile") == "armor" and id(s) in outlier_shots)]
            removed = len(data) - len(new_data)
            save_training(new_data)
            print(f"\nDeleted {removed} outlier shot(s) from training_data.json.")

    # Monotonicity check: no-wind shots at same angle
    print("\n--- Monotonicity check (no-wind shots, grouped by angle) ---")
    no_wind = [s for s in armor if s["wind_strength"] == 0]
    angles = sorted(set(s["angle"] for s in no_wind))
    for angle in angles:
        group = sorted([s for s in no_wind if s["angle"] == angle], key=lambda x: x["power"])
        issues = []
        for j in range(1, len(group)):
            if group[j]["actual_sd"] <= group[j-1]["actual_sd"]:
                issues.append(
                    f"  power {group[j-1]['power']:.2f}→{group[j]['power']:.2f}: "
                    f"SD {group[j-1]['actual_sd']:.3f}→{group[j]['actual_sd']:.3f} (non-increasing!)"
                )
        if issues:
            print(f"angle={angle}: {len(issues)} monotonicity violation(s)")
            for iss in issues:
                print(iss)
        else:
            print(f"angle={angle}: OK ({len(group)} shots)")

if __name__ == "__main__":
    main()
