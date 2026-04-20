"""
models.py — Data model definitions for the GunBound shot calculator.
"""

from dataclasses import dataclass


@dataclass
class ShotResult:
    """A single shot suggestion returned by the solver or matching layer.

    Attributes
    ----------
    angle     : Launch angle in degrees (35–89).
    power     : Power bar value (0.5–4.0).
    error     : Signed residual error in SD units.
                For physics suggestions: simulate(angle, power) − target_sd.
                For data suggestions: spread (std dev) of matching shots.
    source    : "physics" if derived from the solver, "data" if from training.
    n_samples : Number of training shots backing a "data" suggestion (0 for physics).
    """

    angle:     float
    power:     float
    error:     float
    source:    str = "physics"
    n_samples: int = 0
