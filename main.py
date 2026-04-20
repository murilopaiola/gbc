"""
main.py — Entrypoint for the GunBound shot calculator.

Usage:
  python main.py                  # interactive calculator loop
  python main.py --calibrate      # recalibrate all mobiles from training data
  python main.py --validate       # print per-shot errors for all training shots
  python main.py --training       # record new shots into training data
"""

import sys
import os

# Allow running directly without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from gunbound.cli import main

if __name__ == "__main__":
    main()
