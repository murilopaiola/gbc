"""
physics.py — Core physics simulation for the GunBound shot calculator.

Key design decisions:
  1. Per-mobile gravity is fixed from reference reverse-engineering (not fitted).
  2. Integer wind truncation matches the engine's dead-zone behaviour.
  3. Euler order: position-before-velocity (matches reference engine).
  4. Linear interpolation at the y=0 crossing eliminates dt overshoot.
"""

import math

from .constants import MOBILE_PHYSICS, _ARMOR_G_REF, _G_BASE


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


def wind_components(W: float, theta_deg: float) -> tuple[int, int]:
    """Decompose wind (W, theta) into integer (wx, wy) components.

    Convention:
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


def simulate_shot(
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
    angle_deg      : launch angle in degrees (0=horizontal, 90=straight up)
    power          : power bar value (0–4 scale, practical range 0.5–4.0)
    mobile         : mobile name (must be in MOBILE_PHYSICS or mobiles_v2.json)
    v_scale        : velocity scale factor (fitted per mobile)
    power_exp      : power exponent (v_init = power^power_exp * v_scale). Fitted
                     per mobile; corrects the nonlinear power-to-velocity curve.
    wind_x_coeff   : horizontal wind coefficient (fitted per mobile)
    wind_y_coeff   : vertical wind coefficient (fitted per mobile)
    wind_strength  : wind strength in game bars (0–26)
    wind_angle_deg : wind direction (convention: 0=up, 90=toward enemy)
    height_diff    : signed height offset, positive = shooter higher than target
    """
    g = effective_gravity(mobile)

    v_init = (power ** power_exp) * v_scale
    vx = v_init * math.cos(math.radians(angle_deg))
    vy = v_init * math.sin(math.radians(angle_deg))

    wx_int, wy_int = wind_components(wind_strength, wind_angle_deg)
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
