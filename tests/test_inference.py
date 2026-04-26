"""
tests/test_inference.py — Unit tests for src/gunbound/inference.py

Covers:
  - SC-002: Armor self-consistency (compute_priors applied to Armor reproduces Armor's values)
  - FR-007 / SC-004: All 18 mobiles have all four parameters after compute_priors
  - FR-005: apply_priors does not overwrite fully-calibrated mobiles (armor, ice)
  - FR-001: v_scale follows the gravity-ratio formula
  - FR-002: wind coefficients follow the projectile_speed-ratio formula
  - FR-006: apply_priors(dry_run=True) never calls save_mobiles
  - Edge case: compute_priors raises KeyError on empty/missing armor config
"""

import math
from unittest.mock import patch

import pytest

from gunbound.constants import MOBILE_PHYSICS
from gunbound.inference import apply_priors, compute_priors
from gunbound.storage import load_mobiles


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def real_cfg():
    """Load the actual mobiles_v2.json config (armor and ice are fully calibrated)."""
    return load_mobiles()


@pytest.fixture
def minimal_cfg():
    """Minimal config: only armor, fully calibrated."""
    return {
        "armor": {
            "v_scale": 1.319326,
            "power_exp": 0.958738,
            "wind_x_coeff": 0.096592,
            "wind_y_coeff": 0.095043,
        }
    }


# ── T005: SC-002 — Armor self-consistency ─────────────────────────────────────

def test_compute_priors_armor_self_consistency(real_cfg):
    """Inferred priors for Armor must reproduce Armor's own calibrated values."""
    priors = compute_priors(real_cfg)
    armor_prior = priors["armor"]
    armor_cfg = real_cfg["armor"]

    assert armor_prior["v_scale"]      == pytest.approx(armor_cfg["v_scale"],      abs=1e-4)
    assert armor_prior["wind_x_coeff"] == pytest.approx(armor_cfg["wind_x_coeff"], abs=1e-4)
    assert armor_prior["wind_y_coeff"] == pytest.approx(armor_cfg["wind_y_coeff"], abs=1e-4)
    assert armor_prior["power_exp"]    == pytest.approx(armor_cfg["power_exp"],    abs=1e-6)


# ── T006: FR-007 / SC-004 — All 18 mobiles present with all 4 params ────────

def test_all_mobiles_have_four_params(real_cfg):
    """compute_priors must return all 18 MOBILE_PHYSICS mobiles, each with 4 keys."""
    priors = compute_priors(real_cfg)
    required_keys = {"v_scale", "power_exp", "wind_x_coeff", "wind_y_coeff"}

    for mobile in MOBILE_PHYSICS:
        assert mobile in priors, f"Missing mobile in priors: {mobile}"
        missing = required_keys - priors[mobile].keys()
        assert not missing, f"{mobile} is missing keys: {missing}"

    for mobile, params in priors.items():
        for key, val in params.items():
            assert val > 0, f"{mobile}.{key} must be positive, got {val}"


# ── T007: FR-005 — apply_priors does not overwrite fitted mobiles ─────────────

def test_apply_priors_does_not_overwrite_fitted(real_cfg):
    """Mobiles with 'power_exp' already present must not be modified by apply_priors."""
    import copy
    original_armor = copy.deepcopy(real_cfg["armor"])
    original_ice   = copy.deepcopy(real_cfg["ice"])

    apply_priors(real_cfg, dry_run=True)

    assert real_cfg["armor"] == original_armor, "armor was modified — must be skipped"
    assert real_cfg["ice"]   == original_ice,   "ice was modified — must be skipped"


# ── T011: FR-001 — v_scale follows sqrt(g_mobile / g_armor) ──────────────────

def test_inferred_v_scale_follows_gravity_ratio(minimal_cfg):
    """v_scale for every mobile must equal armor_vs * sqrt(g_mobile / g_armor)."""
    priors = compute_priors(minimal_cfg)
    armor_vs = minimal_cfg["armor"]["v_scale"]
    g_armor  = MOBILE_PHYSICS["armor"]["gravity"]

    for mobile, phys in MOBILE_PHYSICS.items():
        expected = armor_vs * math.sqrt(phys["gravity"] / g_armor)
        actual   = priors[mobile]["v_scale"]
        assert actual == pytest.approx(expected, abs=1e-4), (
            f"{mobile}: expected v_scale={expected:.6f}, got {actual:.6f}"
        )


# ── T012: FR-002 — wind coefficients follow ps_mobile / ps_armor ─────────────

def test_inferred_wind_coeffs_follow_speed_ratio(minimal_cfg):
    """wind_x_coeff / wind_y_coeff must scale by projectile_speed ratio."""
    priors = compute_priors(minimal_cfg)
    armor_wx = minimal_cfg["armor"]["wind_x_coeff"]
    armor_wy = minimal_cfg["armor"]["wind_y_coeff"]
    ps_armor  = MOBILE_PHYSICS["armor"]["projectile_speed"]

    for mobile, phys in MOBILE_PHYSICS.items():
        ratio    = phys["projectile_speed"] / ps_armor
        exp_wx   = armor_wx * ratio
        exp_wy   = armor_wy * ratio
        assert priors[mobile]["wind_x_coeff"] == pytest.approx(exp_wx, abs=1e-4), (
            f"{mobile}: wind_x expected {exp_wx:.6f}"
        )
        assert priors[mobile]["wind_y_coeff"] == pytest.approx(exp_wy, abs=1e-4), (
            f"{mobile}: wind_y expected {exp_wy:.6f}"
        )


# ── T015: FR-006 — dry_run=True must not call save_mobiles ───────────────────

def test_apply_priors_dry_run_does_not_save(minimal_cfg):
    """apply_priors(dry_run=True) must never call save_mobiles."""
    with patch("gunbound.inference.save_mobiles") as mock_save:
        apply_priors(minimal_cfg, dry_run=True)
        mock_save.assert_not_called()


# ── T018: Edge case — missing armor raises KeyError ──────────────────────────

def test_compute_priors_raises_on_missing_armor():
    """compute_priors({}) must raise KeyError mentioning 'armor'."""
    with pytest.raises(KeyError, match="armor"):
        compute_priors({})


def test_compute_priors_raises_on_incomplete_armor():
    """compute_priors must raise KeyError if armor is missing required keys."""
    with pytest.raises(KeyError):
        compute_priors({"armor": {"v_scale": 1.3}})  # missing power_exp, wind coeffs
