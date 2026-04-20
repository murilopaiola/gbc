"""
gunbound — GunBound Classic shot calculator package.

Public API:
  suggest_shots  — primary entry point: hybrid data + physics suggestions
  solve          — physics-only solver
  ShotResult     — returned by both suggest_shots and solve
  KNOWN_MOBILES  — list of all supported mobile names
"""

from .constants import KNOWN_MOBILES
from .matching import suggest_shots
from .models import ShotResult
from .solver import solve

__all__ = ["suggest_shots", "solve", "ShotResult", "KNOWN_MOBILES"]
