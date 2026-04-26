"""
inference.py — Physics-derived parameter priors for uncalibrated mobiles.

Computes best-guess starting values for (v_scale, power_exp, wind_x_coeff,
wind_y_coeff) from the known gravity and projectile_speed constants of each
mobile, anchored to Armor's fully-fitted calibration.

Formulas
--------
v_scale:       armor_v_scale × sqrt(g_mobile / g_armor)
wind_x_coeff:  armor_wind_x  × (ps_mobile / ps_armor)
wind_y_coeff:  armor_wind_y  × (ps_mobile / ps_armor)
power_exp:     armor_power_exp  (no reliable physics derivation from 2 points)

Fitted sentinel
---------------
A mobile is treated as *fully calibrated* and protected from overwrite if and
only if its current config entry contains the "power_exp" key.  As of the
initial release this applies to "armor" and "ice".

Public API
----------
compute_priors(cfg)          -> dict[str, dict]   pure, no side-effects
apply_priors(cfg, dry_run)   -> dict              may write to disk
"""

from .constants import MOBILE_PHYSICS
from .physics import default_v_scale
from .storage import save_mobiles


def compute_priors(cfg: dict) -> dict[str, dict]:
    """Return inferred priors for every mobile in MOBILE_PHYSICS.

    Parameters
    ----------
    cfg : dict
        Current mobiles_v2.json config (as returned by load_mobiles()).
        Must contain a fully-calibrated "armor" entry with all four keys.

    Returns
    -------
    dict mapping every mobile name to a 4-key parameter dict.
    Does NOT modify cfg. Does NOT write to disk.

    Raises
    ------
    KeyError
        If cfg["armor"] is missing or lacks any of the four required keys.
    """
    armor = cfg.get("armor")
    if armor is None:
        raise KeyError(
            "armor entry is missing from config — run --calibrate first to fit Armor."
        )
    for key in ("v_scale", "power_exp", "wind_x_coeff", "wind_y_coeff"):
        if key not in armor:
            raise KeyError(
                f"armor config is missing '{key}' — run --calibrate first to fit Armor."
            )

    armor_vs = armor["v_scale"]
    armor_pe = armor["power_exp"]
    armor_wx = armor["wind_x_coeff"]
    armor_wy = armor["wind_y_coeff"]
    ps_armor = MOBILE_PHYSICS["armor"]["projectile_speed"]

    priors: dict[str, dict] = {}
    for mobile, phys in MOBILE_PHYSICS.items():
        ps_mobile = phys["projectile_speed"]
        speed_ratio = ps_mobile / ps_armor
        priors[mobile] = {
            "v_scale":      default_v_scale(mobile, armor_vs),
            "power_exp":    armor_pe,
            "wind_x_coeff": round(armor_wx * speed_ratio, 6),
            "wind_y_coeff": round(armor_wy * speed_ratio, 6),
        }

    return priors


def apply_priors(cfg: dict, dry_run: bool = False) -> dict:
    """Update cfg in-place with inferred priors for uncalibrated mobiles.

    A mobile is considered *fully calibrated* (and therefore skipped) if its
    current entry in cfg already contains the "power_exp" key.

    Parameters
    ----------
    cfg : dict
        Current mobiles_v2.json config, modified in-place.
    dry_run : bool
        If True, skip writing to disk. cfg is still modified in-place so
        callers can inspect the result.

    Returns
    -------
    dict
        The updated cfg (same object as input).
    """
    priors = compute_priors(cfg)

    for mobile, prior in priors.items():
        existing = cfg.get(mobile, {})
        if "power_exp" in existing:
            continue
        cfg[mobile] = prior

    if not dry_run:
        save_mobiles(cfg)

    return cfg
