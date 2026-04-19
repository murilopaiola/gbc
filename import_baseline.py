"""
import_baseline.py  —  Seed training_data.json with known no-wind shots.
Run once:  python import_baseline.py

To add a new mobile, add an entry to BASELINES below.
Each entry is:
    "mobile_name": {
        "angle":         <degrees>,
        "wind_strength": <0–26>,
        "wind_angle":    <-180–180>,
        "height_diff":   <SD>,
        "shots": [
            (actual_sd, power),
            ...
        ]
    }

Distances are in SD units (1 tela = 1.0 SD = 1600 px).
For range values (e.g. "3.1–3.2"), use the midpoint (3.15).
"""

import json, os

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
TRAINING_FILE = os.path.join(BASE_DIR, "training_data.json")

# ── Baseline data ──────────────────────────────────────────────────────────────

BASELINES = {
    "armor": {
        "angle":         70,
        "wind_strength": 0.0,
        "wind_angle":    0.0,
        "height_diff":   0.0,
        "shots": [
            # (actual_sd, power)
            (0.125, 0.90),
            (0.250, 1.35),
            (0.375, 1.60),
            (0.500, 1.90),
            (0.625, 2.10),
            (0.750, 2.30),
            (0.875, 2.55),
            (1.000, 2.80),
            (1.125, 3.15),
            (1.375, 3.45),
            (1.500, 3.75),
        ],
    },

    "ice": {
        "angle":         70,
        "wind_strength": 0.0,
        "wind_angle":    0.0,
        "height_diff":   0.0,
        "shots": [
            # (actual_sd, power)
            (0.125, 0.85),
            (0.250, 1.30),
            (0.375, 1.55),
            (0.500, 1.85),
            (0.625, 2.05),
            (0.750, 2.25),
            (0.875, 2.50),
            (1.000, 2.75),
            (1.125, 3.05),
            (1.375, 3.35),
            (1.500, 3.65),
        ],
    },
}

# ── Import ─────────────────────────────────────────────────────────────────────

if os.path.exists(TRAINING_FILE):
    with open(TRAINING_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
        data = json.loads(content) if content else []
else:
    data = []

existing = {
    (e["mobile"], e["angle"], e["power"], e["wind_strength"], e["wind_angle"], e["height_diff"], e["actual_sd"])
    for e in data
}

new_entries = []
for mobile, cfg in BASELINES.items():
    for actual_sd, power in cfg["shots"]:
        key = (mobile, cfg["angle"], power, cfg["wind_strength"], cfg["wind_angle"], cfg["height_diff"], actual_sd)
        if key not in existing:
            new_entries.append({
                "mobile":        mobile,
                "angle":         cfg["angle"],
                "power":         power,
                "wind_strength": cfg["wind_strength"],
                "wind_angle":    cfg["wind_angle"],
                "height_diff":   cfg["height_diff"],
                "actual_sd":     actual_sd,
            })

data.extend(new_entries)

with open(TRAINING_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(f"Added {len(new_entries)} entries. Total: {len(data)}")
