# Data Collection Priorities

## How to use
Record shots in `--training` mode. After each session run `--calibrate` then `--validate`.
`err` = predicted − actual (negative = model undershoots).

---

## Priority 1 — Diagnose S-curve (Armor, no wind)

Goal: determine if the mid-power undershoot is angle-specific or universal.
Current: only a=70° covered. If a=45° and a=55° show the same arch → power_exp model is insufficient → need piecewise or quadratic power mapping.

| Mobile | Angle | Powers to shoot | Wind | Height | Status |
|--------|-------|-----------------|------|--------|--------|
| armor  | 45°   | 1.6, 1.9, 2.3, 2.8 | 0 | 0 | ❌ missing |
| armor  | 55°   | 1.6, 1.9, 2.3, 2.8 | 0 | 0 | ❌ missing |
| armor  | 65°   | 1.6, 1.9, 2.3, 2.8 | 0 | 0 | ❌ missing |

---

## Priority 2 — High-angle forward wind (Armor)

Goal: fix wx-amplification at a≥80° with forward wind.
Current shots at a=82° W=19@+150° overshoot by +0.07 SD. Need more shots to recalibrate a wind_x angle-dependent correction.

| Mobile | Angle | Power | Wind range | Wind angle | Height | Status |
|--------|-------|-------|------------|------------|--------|--------|
| armor  | 80°   | 2.0–3.0 | 10–20 | +120° to +160° | 0 | ❌ missing |
| armor  | 82°   | 2.0–3.0 | 10–20 | +120° to +160° | 0 | ❌ missing |
| armor  | 85°   | 2.0–3.0 | 10–20 | +120° to +160° | 0 | ❌ missing |

---

## Priority 3 — Re-verify suspect shots

These have large isolated errors inconsistent with neighbors. Re-shoot and correct if wrong.

| Mobile | Angle | Power | Wind | Height | Recorded SD | Pred SD | Error | Issue |
|--------|-------|-------|------|--------|-------------|---------|-------|-------|
| armor  | 70°   | 3.75  | 0    | 0      | 1.500       | 1.557   | +0.057 | Only no-wind a=70° that **over**-predicts — rest all undershoot |
| armor  | 70°   | 4.00  | 17@-90° | 0   | 1.000       | 0.945   | -0.055 | Isolated; all other -90° shots fit well |
| armor  | 62°   | 1.90  | 7@+36° | -0.06 | 0.550     | 0.610   | +0.060 | No nearby shots to cross-check |

---

## Priority 4 — Expand Ice coverage

Ice only has 11 shots all at a=70° no-wind. Needs wind shots and other angles.

| Mobile | Angle | Powers | Wind range | Wind angle | Height | Status |
|--------|-------|--------|------------|------------|--------|--------|
| ice    | 70°   | 1.5–3.0 | 10–20 | +90° | 0 | ❌ missing |
| ice    | 70°   | 1.5–3.0 | 10–20 | -90° | 0 | ❌ missing |
| ice    | 55°   | 1.5–3.0 | 0    | 0   | 0 | ❌ missing |
| ice    | 45°   | 1.5–3.0 | 0    | 0   | 0 | ❌ missing |

---

## Coverage summary

| Mobile | Total shots | No-wind | With wind | Angles covered |
|--------|------------|---------|-----------|----------------|
| armor  | 92         | 29      | 63        | 43°–86°        |
| ice    | 11         | 11      | 0         | 70° only       |
