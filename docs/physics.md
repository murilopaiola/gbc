# GunBound Classic — Physics Model

This document describes the physics model used by the calculator: its assumptions, equations, parameters, known deviations from real game behaviour, and the reasoning behind design decisions.

---

## 1. Coordinate system

```
        y (up)
        |
        |   trajectory
        |  /
        | /  α
        +----------→ x (toward enemy)
      origin
      (shooter)
```

- **x-axis** points toward the enemy. SD (Screen Distance) is measured along this axis.
- **y-axis** points upward.
- `height_diff` is the initial y-position of the projectile: positive = target is higher, negative = lower.
- The shot lands when `y ≤ 0` (ground level). The return value is the final `x`, which equals the SD.

---

## 2. Initial velocity

```
vx₀ = p · s · cos(α)
vy₀ = p · s · sin(α)
```

| Symbol | Meaning |
|---|---|
| `p` | power (bar value, 0.5–6.0) |
| `s` | `v_scale` — per-mobile, per-band calibration coefficient |
| `α` | launch angle in degrees, converted to radians |

`v_scale` absorbs the conversion between the game's power bar units and the SD/s velocity unit used internally. It is fitted from training data, not derived analytically.

---

## 3. Wind model

Wind is specified as a **strength** `W` (0–26 bars) and an **angle** `θ` measured from straight up, clockwise toward the enemy:

```
wx = W · sin(θ)     ← horizontal component (toward enemy = positive)
wy = W · cos(θ)     ← vertical component   (upward = positive)
```

| θ | wx | wy | Effect |
|---|---|---|---|
| 0° | 0 | +W | pure upward — longer range |
| 90° | +W | 0 | toward enemy — shifts landing right |
| 150° | +0.5W | −0.866W | toward enemy + downward |
| 180° | 0 | −W | pure downward — shorter range |
| −90° | −W | 0 | away from enemy |

**If the enemy is to your left**, negate the angle before entering it (compass 70° → enter −70°). Purely vertical wind (0° or ±180°) is unaffected by side.

---

## 4. Euler integration loop

```
dt = 0.05   (time step)
max_steps = 1000

each step:
    vx += wx · cx · dt
    vy += wy · cy · dt
    x  += vx · dt
    y  += vy · dt
    vy -= g · dt
    if y ≤ 0: stop
```

| Symbol | Meaning |
|---|---|
| `cx` | `wind_x_coeff` — horizontal wind scaling, fitted per band |
| `cy` | `wind_y_coeff` — vertical wind scaling, fitted per band |
| `g` | gravity = 9.8 (fixed for all mobiles currently) |

Wind is a **continuous per-step force**, not a one-time impulse. This means shots with longer flight times (higher angles, more power, longer range) accumulate more total deflection from the same wind — which matches observed GunBound behaviour.

Total simulated time before landing ≈ `n_steps · dt`. With `dt = 0.05` and up to 1000 steps, the maximum simulated flight time is 50 s (never reached in practice; most shots land in 20–80 steps).

---

## 5. Distance bands

Physics coefficients vary significantly with range. Three bands are calibrated independently:

| Band | SD range | Typical angle range |
|---|---|---|
| `short` | 0.00 – 0.75 | 45°–85° |
| `mid` | 0.75 – 1.25 | 35°–75° |
| `long` | > 1.25 | 20°–60° |

The band is selected from the **target SD**, not the angle. `get_effective_cfg()` merges the band coefficients with the shared `gravity` into a single config dict passed to `simulate_shot()`.

---

## 6. Calibrated parameters

Per mobile, per band: three parameters are fitted from training data.

| Parameter | Search range | Meaning |
|---|---|---|
| `v_scale` | [0.85, 1.20] | Converts power bar to velocity |
| `wind_x_coeff` | [0.10, 2.00] | Scales horizontal wind force |
| `wind_y_coeff` | [0.05, 1.00] | Scales vertical wind force |

`gravity` is fixed at 9.8 and not fitted. Separating it from `v_scale` would be degenerate given that only the final landing position is observed.

Calibration method: random search over 3000 candidates, minimising:

```
L(θ) = Σᵢ  (x̂ᵢ(θ) − xᵢ)²  /  (1 + |xᵢ|)
```

The denominator down-weights long-range shots, which have higher absolute measurement noise.

---

## 7. Strong-wind angle cap

When `wind_strength > 14` and the target band is `mid` or `long`, the solver caps the search at 72°. Above this threshold, a high-angle shot spends so long in the air that even a moderate headwind can reverse its horizontal motion entirely, making the parabola unreliable in practice.

The cap is overridden automatically if training data contains a confirmed high-angle shot (angle > 72°, same mobile, same band, similar target distance) under strong wind. Constants:

```python
STRONG_WIND_THRESHOLD = 14
STRONG_WIND_ANGLE_MAX = 72
HIGH_ANGLE_SD_TOL     = 0.15  # SD proximity to count as "similar distance"
```

---

## 8. Known deviations from real game physics

| Aspect | Model | Real game |
|---|---|---|
| Drag | None | Likely present (projectiles slow down) |
| Spin / Magnus effect | None | Some mobiles have curving shots |
| Wind profile | Constant force throughout flight | May vary with altitude |
| Gravity | Fixed 9.8 for all mobiles | Per-mobile, unknown |
| Terrain | Only initial y-offset | Slope, obstacles, bounce |
| Multiple shot types | One model per mobile | Ice/Armor have 2 distinct shots |

These gaps are bridged by the fitted coefficients: `v_scale`, `wind_x_coeff`, and `wind_y_coeff` absorb systematic errors, so the model learns to predict correctly even if the underlying equations are approximate.

---

## 9. Similarity metric (data-confidence layer)

When looking up historical shots, proximity is measured as a normalised Euclidean distance across 4 dimensions. Wind is compared as its **effect vector** `(wx, wy)` rather than raw `(W, θ)`, so two shots with the same effective wind but different angle encodings are correctly treated as equivalent:

```
d_sim = sqrt(
    ((Δsd)     / 2 )² +
    ((Δwx)     / 26)² +
    ((Δwy)     / 26)² +
    ((Δheight) / 4 )²
)
```

Denominators normalise each axis to its realistic full range:
- SD range ≈ 0–2 → denominator 2
- wx, wy range ≈ −26 to +26 → denominator 26
- height_diff range ≈ −2 to +2 → denominator 4

| Threshold | Meaning |
|---|---|
| `d_sim < 0.08` | Close match — use as direct suggestion |
| `d_sim < 0.15` | Loose match — use for residual bias correction only |

---

## 10. Physics-derived parameter priors (`inference.py`)

When a mobile has no training data, the calibration system cannot fit its four parameters from observations. Rather than falling back to flat placeholder values, `src/gunbound/inference.py` computes *physics-derived priors* anchored to Armor's fully-fitted calibration.

### 10.1 Fitted sentinel

A mobile is **fully calibrated** if and only if its `config/mobiles_v2.json` entry contains the `"power_exp"` key. Any mobile without that key receives inferred defaults. Currently only `armor` and `ice` are fully calibrated.

### 10.2 v_scale prior

```
v_scale_mobile = v_scale_armor × sqrt(g_mobile / g_armor)
```

**Derivation**: For a fixed angle and power, the landing SD scales approximately linearly with the initial speed. The initial speed scales with `v_scale × sqrt(g)` (from dimensional analysis of the Euler loop: at higher gravity the same power bar produces a proportionally faster projectile). Taking the ratio of two mobiles and solving for the unknown `v_scale`:

```
SD_mobile / SD_armor  ≈  v_scale_mobile × sqrt(g_mobile)
                          ─────────────────────────────────
                          v_scale_armor  × sqrt(g_armor)

  →  v_scale_mobile = v_scale_armor × sqrt(g_mobile / g_armor)
```

The function `physics.default_v_scale()` implements this formula and is the single source of truth.

### 10.3 Wind coefficient priors

```
wind_x_coeff_mobile = wind_x_coeff_armor × (ps_mobile / ps_armor)
wind_y_coeff_mobile = wind_y_coeff_armor × (ps_mobile / ps_armor)
```

where `ps` is `projectile_speed` from `constants.MOBILE_PHYSICS`.

**Derivation**: Wind deflection accumulated over a flight is proportional to `F_wind × t_flight`. A faster projectile (higher `projectile_speed`) spends less time in the air for the same SD, so the same wind force produces less deflection. The wind coefficient must therefore be scaled *up* for faster projectiles to express the same force, and *down* for slower ones. Rearranging:

```
deflection ≈ wind_coeff × W × t_flight  ∝  wind_coeff / ps
```

For two mobiles hitting the same SD under the same wind, deflection is equal, so:

```
wind_coeff_mobile / ps_mobile = wind_coeff_armor / ps_armor
  →  wind_coeff_mobile = wind_coeff_armor × ps_mobile / ps_armor
```

### 10.4 power_exp prior

```
power_exp_mobile = power_exp_armor  (no derivation — copied directly)
```

There is no reliable physics relationship between `power_exp` and per-mobile constants. The exponent captures nonlinearity in the power bar mechanic that is not exposed by the gravity or speed constants. It is therefore copied from Armor until real shots allow fitting.

### 10.5 Accuracy expectation

Inferred priors are not calibrated parameters. They provide a physics-grounded starting point, not a precise fit. Expected accuracy for an uncalibrated mobile using inferred priors:

| Condition | Expected error |
|---|---|
| Zero wind, mid-range | ±0.05 – 0.10 SD |
| Moderate wind | ±0.10 – 0.20 SD |
| Extreme wind or angle | may exceed ±0.25 SD |

Running `--calibrate` with 20+ training shots for the target mobile will replace the priors with fitted values and reduce error to the Armor-level MAE (~0.015 SD).

### 10.6 CLI usage

```bash
python main.py --infer-priors            # compute and write priors for all uncalibrated mobiles
python main.py --infer-priors --dry-run  # preview table without modifying config/mobiles_v2.json
```

Mobiles that are already fully calibrated (have `power_exp` in their config entry) are skipped silently.
