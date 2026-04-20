"""
storage.py — File I/O for calibration config and training data.

All paths are resolved relative to the project root (two levels up from this
file), so the project can be run from any working directory.
"""

import json
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Path constants
# ─────────────────────────────────────────────────────────────────────────────
_SRC_DIR     = Path(__file__).resolve().parent   # src/gunbound/
PROJECT_ROOT = _SRC_DIR.parent.parent            # project root

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR   = PROJECT_ROOT / "data"
ASSETS_DIR = PROJECT_ROOT / "assets"

MOBILES_FILE  = CONFIG_DIR / "mobiles_v2.json"
TRAINING_FILE = DATA_DIR   / "training_data.json"


# ─────────────────────────────────────────────────────────────────────────────
# Calibration config (mobiles_v2.json)
# ─────────────────────────────────────────────────────────────────────────────

def load_mobiles() -> dict:
    """Load per-mobile calibration parameters from config/mobiles_v2.json."""
    if MOBILES_FILE.exists():
        return json.loads(MOBILES_FILE.read_text(encoding="utf-8"))
    return {}


def save_mobiles(cfg: dict) -> None:
    """Write per-mobile calibration parameters to config/mobiles_v2.json."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    MOBILES_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"  Saved → {MOBILES_FILE}")


# ─────────────────────────────────────────────────────────────────────────────
# Training data (training_data.json)
# ─────────────────────────────────────────────────────────────────────────────

def load_training() -> list:
    """Load all recorded training shots from data/training_data.json."""
    if not TRAINING_FILE.exists():
        return []
    return json.loads(TRAINING_FILE.read_text(encoding="utf-8"))


def save_training(data: list) -> None:
    """Write all training shots to data/training_data.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TRAINING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
