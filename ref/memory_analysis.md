# GunBound Memory Analysis — `memory.py` Reference Study

This document extracts everything useful from `memory.py` (a GitHub PoC that reads GunBound Classic's process memory) for the purpose of improving `calc.py`'s accuracy and enabling auto-read of game state.

---

## 1. Memory Addresses

All offsets are relative to the running process (`GunBound.gme`). `base_address` refers to the main module's base.

### Wind

| Field | How to read |
|---|---|
| Wind speed | `a = read_uint(0x87053c)` → `b = read_uint(0x870140 + a*4)` → `read_bytes(b + 0x1234, 1)[0]` |
| Wind direction | Same `a`, `b` → `read_ushort(b + 0x1235)` (2 bytes, immediately after speed) |

Wind direction from memory uses **standard math convention**: 0° = right side, increases counter-clockwise. This is **different** from `calc.py`'s convention. See §7.

### Per-Player Data (stride 0x18)

Base address for player `index`: `base_address + 0x482A58 + index * 0x18`

| Field | Offset | Type | Notes |
|---|---|---|---|
| Cart X | +0x0 | `ushort` | Map units |
| Cart Y | +0x4 | `ushort` | Map units |
| Cart angle | +0x8 | `int` (signed) | In degrees |
| Facing direction | +0xC | `byte` | 0 = Left, 1 = Right |

### Global / Session Data

| Field | Address | Type | Notes |
|---|---|---|---|
| Player index | `base + 0x4F3929` | `byte` | Index of current player |
| Mobile ID | `base + 0x497368` | `byte` | See §3 for ID map |
| Screen center X | `base + 0x4E98D4` | `ushort` | Map unit at screen center |
| Screen center Y | `base + 0x4E98D8` | `ushort` | Map unit at screen center |

### Angle (alternative read path)

A second angle value is readable at: `read_uint(0x8F4A20)` → pointer + `0x19EC` → `read_int(...)`. This appears to be a "global" cart angle that is combined with the per-player cart angle and facing direction to get the final launch angle. In most use cases reading the per-player angle at `0x482A58 + index*0x18 + 0x8` is sufficient.

---

## 2. Map & Screen Coordinate System

```
Map origin: (0, 0) = top-left corner of the map
X axis:     0 → 1800  (horizontal)
Y axis:     -20 → 1840 (vertical, game-internal; bottom = higher Y value)

Screen size (game window content area): 800 × 600
```

The screen always shows an 800×600 pixel window into the 1800-wide map. `read_screen_center_position()` tells you which map coordinate is at the center of the screen, so you can convert between screen pixels and map units:

```
map_x = screen_center_x - 400 + screen_pixel_x
map_y = screen_center_y - 300 + screen_pixel_y
```

### SD ↔ Map Unit Relationship

`calculate_distance_in_screens` in the reference code is:

```python
distance_in_screens = abs(target_x - source_x) / 800
```

This is likely the same as the `SD` (screen distance) used in `calc.py`. So **1 SD = 800 map units**. The full map is 1800 units wide, meaning the maximum possible SD between two players is ≈ 2.25 SD.

---

## 3. Mobile ID Enum

Read from `base_address + 0x497368` (1 byte).

| ID | Mobile(s) |
|---|---|
| 0 | Armor |
| 1 | Mage |
| 2 | Nak |
| 3 | Trico |
| 4 | BigFoot |
| 5 | Boomer |
| 6 | Raon |
| 7 | Lightning |
| 8 | JD |
| 9 | A.Sate |
| 10 | Ice |
| 11 | Turtle |
| 12 | Grub |
| 13 | Aduka / Knight *(share ID)* |
| 14 | Kalsiddon |
| 15 | JFrog / Dragon *(share ID)* |
| 255 | Random (not yet assigned) |

Aduka+Knight and JFrog+Dragon share IDs, which means the game treats them as identical for physics purposes. They have the same projectile speed and gravity.

---

## 4. Per-Mobile Physics Constants

These are **extracted directly from the game's reference simulation** and represent the real engine values, not fitted approximations.

### Projectile Speed (`projectile_speed`)

The base launch velocity coefficient. Used as a multiplier: `v_init = power_raw * projectile_speed`.

| Mobile | Speed |
|---|---|
| Armor | 0.74 |
| Mage | 0.78 |
| Nak | 0.99 |
| Trico | 0.87 |
| BigFoot | 0.74 |
| Boomer | 1.395 |
| Raon | 0.827 |
| Lightning | 0.72 |
| JD | 0.625 |
| A.Sate | 0.765 |
| Ice | 0.625 |
| Turtle | 0.74 |
| Grub | 0.65 |
| Aduka / Knight | 0.695 |
| JFrog / Dragon | 0.67 |
| Kalsiddon | 0.905 |

### Gravity (`gravity`)

Applied as a constant downward acceleration on `vy` each step. Values are negative (downward).

| Mobile | Gravity |
|---|---|
| Armor | −73.5 |
| Mage | −71.5 |
| Nak | −93.0 |
| Trico | −84.0 |
| BigFoot | −90.0 |
| Boomer | −62.5 |
| Raon | −81.0 |
| Lightning | −65.0 |
| JD | −62.5 |
| A.Sate | −76.0 |
| Ice | −62.5 |
| Turtle | −73.5 |
| Grub | −61.0 |
| Aduka / Knight | −65.5 |
| JFrog / Dragon | −54.3 |
| Kalsiddon | −88.5 |

**Critical gap in `calc.py`:** The current model uses a fixed `gravity = 9.8` for all mobiles and relies on `v_scale` to absorb per-mobile differences. Replacing this with real per-mobile gravity + real `projectile_speed` would remove a major source of fitting error.

---

## 5. Reference Physics Equations

From `generate_coordinates()`:

### Accelerations (constant throughout flight)

```python
# wind_angle: standard math angle, 0° = right, CCW positive
# wind_power: raw integer from memory (0–?)

acceleration_x = int(cos(radians(wind_angle)) * wind_power) * projectile_speed
acceleration_y = int(sin(radians(wind_angle)) * wind_power) * projectile_speed + gravity
```

> **Important:** The wind components are **integer-truncated** before being multiplied by `projectile_speed`. This is not a rounding artefact — it is how the game engine works. The truncation creates a dead zone: winds whose horizontal/vertical component is < 1.0 are treated as zero for that axis.

### Initial Velocity

```python
speed_x = power_raw * cos(radians(angle))
speed_y = power_raw * sin(radians(angle))
```

Where `power_raw` is 0–400 (the raw power bar value in pixels; the bar is 400 px wide).

### Integration (Euler, dt = step_size = 0.05)

```python
x     += speed_x * dt
y     += speed_y * dt
speed_x += acceleration_x * dt
speed_y += acceleration_y * dt
```

Note: the reference code applies acceleration **after** position update (leapfrog variant), while `calc.py` applies wind before the position update. This is a minor difference but worth aligning.

### Landing Condition

The projectile lands when its Y coordinate crosses below the target Y (not y ≤ 0 as in `calc.py`). Landing is interpolated as the average of the last and current positions. For flat terrain this is equivalent, but for height differences it matters.

---

## 6. Power Scale — Reference vs `calc.py`

| Property | Reference code | `calc.py` |
|---|---|---|
| Power range | 0–400 (integer, power bar pixels) | 0.5–6.0 (arbitrary float) |
| Velocity formula | `power_raw * projectile_speed` | `power_calc * v_scale` |

These are equivalent if: `power_calc * v_scale = power_raw * projectile_speed`. Once you know the real `projectile_speed`, the relationship between `calc.py` power and power bar pixels becomes exact. The conversion is:

```
power_bar_pixels = (power_calc * v_scale) / projectile_speed
```

For Armor: if `v_scale ≈ 1.15` and `projectile_speed = 0.74`, then power 2.0 in `calc.py` ≈ `2.0 * 1.15 / 0.74 ≈ 3.1` on the raw 0–400 scale... but this scale is very different. The two systems use different time units. The reference code uses a map-unit coordinate system (1800 wide) while `calc.py` uses SD units (1 SD = 800 map units). A full reconciliation requires knowing the dt time unit; for now treat them as two separate but equivalent simulations.

---

## 7. Wind Convention Mismatch

| Convention | 0° | 90° | Positive direction |
|---|---|---|---|
| **Memory read** (reference code) | Right side of screen | Upward | Counter-clockwise |
| **`calc.py`** | Straight up | Toward enemy | Clockwise toward enemy |

To convert from game memory → `calc.py` convention when the enemy is to the **right**:

```python
# memory_angle: 0=right, CCW positive (standard math)
# calc_angle:   0=up, CW-toward-enemy positive

calc_angle = 90 - memory_angle      # for enemy to the right
# For enemy to the left, the horizontal component flips, which calc.py
# handles via negative angles.
```

When reading wind direction from memory to feed into `calc.py`, this conversion must be applied first.

---

## 8. Special Mechanics

### Nak Backshot (angle ≤ 70°)

Nak has a unique backshot mechanic that is non-physical. When shooting backward with an angle ≤ 70°:

```python
acceleration_y *= -8.0   # gravity is inverted AND amplified 8×
speed_x        *= 2.0    # horizontal speed doubled
```

This produces a downward-curving shot that bounces back. `calc.py` currently has no model for this — it would require a separate simulation branch for Nak.

### Slice Mode (shot release)

The reference code auto-fires by monitoring pixel color on the power bar to detect when power reaches the desired level. Colors that indicate the target power position:

```python
COLOR_1 = (208, 24, 32)   # normal
COLOR_2 = (96,  0,  0)    # darker variant
COLOR_3 = (192, 16,  0)   # another variant
```

Power bar area in screen pixels: x=241, y=565, width=400, height=19.

---

## 9. Angle Reading from Screen (OCR fallback)

The reference code also contains a pixel-based angle reader (no memory needed) using template matching against digit images at fixed screen coordinates:

| Item | Screen region (x, y, w, h) |
|---|---|
| Sign (minus) | (218, 536, 8, 5) |
| Tens digit | (226, 531, 13, 13) |
| Units digit | (239, 531, 13, 13) |

This could be used as a faster alternative to memory reading for the angle only, if digit images are available.

---

## 10. Opportunities for `calc.py`

### Speed

| Idea | How |
|---|---|
| **Auto-read inputs** | Read wind speed, wind direction, height diff (from cart Y positions), and mobile ID directly from memory instead of manual entry. Removes the biggest source of user error. |
| **Auto-read angle** | Read cart angle + facing direction from memory to offer "what should my power be?" given the current in-game angle. |
| **Real-time suggestions** | Run in the background, re-solve every time wind or position changes. |

### Accuracy

| Idea | How |
|---|---|
| **Per-mobile gravity** | Replace fixed `gravity = 9.8` with the real values from §4. This removes a systematic error that `v_scale` currently has to compensate for, especially for outlier mobiles like Boomer (−62.5) vs Nak (−93.0). |
| **Integer wind truncation** | Apply `int()` to wind components before computing acceleration, matching actual engine behavior. Low-speed winds near integer boundaries (e.g., 1.9 → treated as 1.0) are currently modeled incorrectly. |
| **Real projectile_speed** | Use the values from §4 as a starting point or constraint for `v_scale` fitting, reducing the search space and avoiding degenerate fits. |
| **Nak backshot model** | Add a separate simulation branch for Nak backshots using the inverted gravity / doubled speed rules. |
| **Euler order** | Align the integration step order (acceleration-then-position vs position-then-acceleration) with the reference to remove a small systematic drift. |

### Direct Simulation Parity

If you implement the reference physics exactly (map units, integer wind truncation, per-mobile constants, power 0–400), `calc.py`'s simulator would match the real game engine and **eliminate the need for per-band calibration**. The output would still need to be converted back to `calc.py`'s power scale, but accuracy should improve to the extent that training data and residual corrections become a fine-tune layer rather than a load-bearing component.
