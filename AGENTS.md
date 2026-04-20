# AGENTS.md — Project Navigation for AI Agents

Start here. This file tells you what the project does, where everything lives, what is already done, and what the rules are before you touch anything.

---

## What this project is

A shot calculator for **GunBound Classic**. Given a target distance (SD), wind, and height difference, it suggests angle + power combinations. It improves over time by learning from real in-game results via a calibration loop.

---

## Project layout

```
gunbound/
├── src/gunbound/          # core package — ALL active development here
│   ├── constants.py       # MOBILE_PHYSICS, solver params, thresholds
│   ├── models.py          # ShotResult dataclass
│   ├── physics.py         # effective_gravity, wind_components, simulate_shot
│   ├── calibration.py     # calibrate, recalibrate_all, validate
│   ├── solver.py          # solve (coarse→refine)
│   ├── matching.py        # suggest_shots, find_similar_shots, clustering
│   ├── storage.py         # load/save helpers; PROJECT_ROOT, CONFIG_DIR, DATA_DIR path constants
│   └── cli.py             # main(), training_mode()
├── config/
│   ├── mobiles_v2.json    # v2 calibrated params. Written by --calibrate.
│   └── mobiles.json       # v1 params (per-band). Reference only.
├── data/
│   └── training_data.json # All recorded shots. Never delete entries.
├── assets/
│   └── ruler.png          # Pre-rendered ruler image loaded by tools/ruler.py
├── docs/
│   ├── physics.md         # Full physics model documentation
│   ├── data_collection.md # Shot collection priorities / targets
│   └── memory_analysis.md # Notes from engine memory reverse-engineering
├── legacy/
│   └── calc_legacy.py     # v1 reference (band-based). Keep for comparison.
├── tools/
│   ├── ruler.py           # Transparent on-screen SD ruler overlay
│   ├── gen_ruler.py       # Regenerates assets/ruler.png
│   └── memory_reader.py   # Game process memory reader (PoC, research use)
├── scripts/
│   └── import_baseline.py # Bulk-import reference shots into training data
├── tests/                 # (empty — test suite to be written)
├── .agents/
│   ├── PROJECT_MEMORY.md  # Complete knowledge base. Read before starting work.
│   └── next_steps_v2.md   # Detailed v2 architecture plan + per-mobile v_scale table
├── main.py                # Entrypoint (adds src/ to sys.path, calls gunbound.cli:main)
├── pyproject.toml         # setuptools src layout; `pip install -e .` installs `gunbound` cmd
└── requirements.txt       # Pillow (core); optional heavy deps commented out
```

---

## Key functions — `src/gunbound/` (ACTIVE)

### physics.py
| Function | What it does |
|---|---|
| `effective_gravity(mobile)` | g_eff = 9.8 × g_ref_mobile / 73.5. Falls back to Armor if unknown. |
| `default_v_scale(mobile, armor_v_scale)` | Derive prior v_scale for uncalibrated mobiles: armor_vs × sqrt(g_mobile/g_armor). |
| `wind_components(W, theta_deg)` | Returns `(int(W·sin θ), int(W·cos θ))`. Integer truncation BEFORE coeff scaling. |
| `simulate_shot(angle, power, mobile, v_scale, power_exp, wind_x_coeff, wind_y_coeff, wind_strength, wind_angle_deg, height_diff)` | Core physics. Position-then-velocity Euler. Per-mobile gravity. Returns SD. |

### calibration.py
| Function | What it does |
|---|---|
| `calibrate(data, mobile)` | 3-phase: A=v_scale+power_exp from no-wind, B=wind coeffs fixed, C=joint descent. |
| `recalibrate_all(cfg, training_data)` | Per-mobile calibration; auto-saves to `config/mobiles_v2.json`. |
| `validate(cfg, training_data)` | Per-shot error table + MAE. `python main.py --validate` |

### solver.py
| Function | What it does |
|---|---|
| `solve(target_sd, mobile, cfg, wind_strength, wind_angle_deg, height_diff)` | Coarse→refine sweep. Returns ≤5 `ShotResult`, biased to 45–80° range. |

### matching.py
| Function | What it does |
|---|---|
| `suggest_shots(mobiles_cfg, mobile, sd, wind_strength, wind_angle, height_diff, training_data)` | **PRIMARY ENTRY POINT.** Tier 1: data matches; Tier 2: residual-corrected physics. |
| `find_similar_shots(training_data, mobile, sd, wind_strength, wind_angle, height_diff)` | d_sim proximity search over training data. |
| `cluster_training_matches(close_matches)` | Groups by (angle±3°, power±0.1), returns spread stats. |
| `compute_residual_correction(similar_shots, cfg, mobile)` | Mean signed error from nearby shots → target SD offset. |

### storage.py
| Symbol | What it is |
|---|---|
| `PROJECT_ROOT` | Absolute path to repo root (resolved at import time, cwd-independent). |
| `CONFIG_DIR` | `PROJECT_ROOT / "config"` |
| `DATA_DIR` | `PROJECT_ROOT / "data"` |
| `ASSETS_DIR` | `PROJECT_ROOT / "assets"` |
| `MOBILES_FILE` | `CONFIG_DIR / "mobiles_v2.json"` |
| `TRAINING_FILE` | `DATA_DIR / "training_data.json"` |
| `load_mobiles()` / `save_mobiles(cfg)` | JSON round-trip for calibration config. |
| `load_training()` / `save_training(data)` | JSON round-trip for training shots. |

### cli.py
| Function | What it does |
|---|---|
| `training_mode(mobiles_cfg)` | `python main.py --training` — record shots; auto-recalibrates on exit. |
| `main()` | Dispatches `--calibrate` / `--validate` / `--training` / interactive loop. Auto-recalibrates every 5 shots. |

---

## Data schemas

### `data/training_data.json` entry
```json
{
  "mobile": "armor",
  "angle": 70,
  "power": 2.5,
  "wind_strength": 10,
  "wind_angle": 45,
  "height_diff": 0.0,
  "actual_sd": 0.87
}
```

### `config/mobiles_v2.json` entry (v2 — active)
```json
{
  "armor": {
    "v_scale": 1.31502,
    "power_exp": 0.97071,
    "wind_x_coeff": 0.09710,
    "wind_y_coeff": 0.11745
  }
}
```

### `config/mobiles.json` entry (v1 — reference only, has v_scale bug)
```json
{
  "armor": {
    "base_angle": 70,
    "gravity": 9.8,
    "bands": {
      "short": { "v_scale": 1.15, "wind_x_coeff": 0.10, "wind_y_coeff": 0.37 },
      "mid":   { "v_scale": 1.20, "wind_x_coeff": 0.87, "wind_y_coeff": 0.43 },
      "long":  { "v_scale": 1.05, "wind_x_coeff": 0.80, "wind_y_coeff": 0.40 }
    }
  }
}
```

---

## Constants worth knowing

In `src/gunbound/constants.py`:

| Constant | Value | Meaning |
|---|---|---|
| `ANGLE_MIN` / `ANGLE_MAX` | 35 / 89 | Solver sweep range |
| `POWER_MIN` / `POWER_MAX` | 0.5 / 4.0 | Power bar scale |
| `MAX_SUGGESTIONS` | 5 | Max suggestions returned |
| `SOLVER_COARSE_STEP` | 2 | Coarse angle sweep (degrees) |
| `_ARMOR_G_REF` | 73.5 | Reference gravity for Armor (normalisation anchor) |
| `_G_BASE` | 9.8 | Armor effective gravity in SD/step² units |
| `MATCH_CLOSE_THRESHOLD` | 0.08 | `d_sim` below this → direct data suggestion |
| `MATCH_LOOSE_THRESHOLD` | 0.15 | `d_sim` below this → residual correction only |
| `KNOWN_MOBILES` | sorted list | All 18 supported mobiles extracted from `MOBILE_PHYSICS` |

---

## Wind angle convention

- **0°** — straight up (no horizontal effect)
- **1 – 179°** — toward enemy (pushes projectile forward)
- **−1 – −179°** — against enemy (pushes projectile backward)
- **180° / −180°** — straight down (shortens range)
- Negative angles → away from enemy side

---

## Rules before making changes

1. **Read `.agents/PROJECT_MEMORY.md`** before starting any work — it has the complete knowledge base including all bugs, decisions, and current accuracy.
2. **Read `docs/physics.md`** before touching `simulate_shot`, `wind_components`, or calibration.
3. **Read `.agents/next_steps_v2.md`** before starting any new feature — it lists pending work with exact file/function pointers.
4. **Do not clear `data/training_data.json`** — entries are cumulative and irreplaceable without re-playing.
5. **Do not add `time_scale` as a fitted parameter** — it is degenerate with `wind_x_coeff`. See `docs/physics.md` §6.
6. **Do not replace the solver with static charts** — GunBound physics is nonlinear; charts break at non-standard wind/height.
7. **`suggest_shots()` in `matching.py` is the primary entry point.** It delegates to `solve()` in `solver.py` for physics results.
8. After editing any `src/gunbound/` module, verify with: `python main.py --validate`. Overall MAE should not regress above 0.05 SD.

---

## Known issues to fix next (ordered)

1. **Investigate wx amplification at high launch angles** — shots at a=82°, W=19@150° still err +0.07 SD. Requires more shots at a=75°–85° with forward wind to constrain model.
2. **Add power exponent to simulation** — try `v_init = power^n * v_scale` with `n` fitted. Expected n ≈ 1.75 from Armor no-wind data. Would flatten S-curve undershoot at mid-range.
4. **Write unit tests** — `tests/` is empty. Priority: `physics.simulate_shot`, `solver.solve`, `matching.suggest_shots`.
5. **Fix v_scale range bug in calc_legacy.py** — change `random.uniform(0.85, 1.20)` to `random.uniform(0.5, 3.0)`. One-line fix.

---

## How to run

```bash
python main.py                        # interactive calculator — use this
python main.py --calibrate            # recalibrate from data/training_data.json → config/mobiles_v2.json
python main.py --validate             # print per-shot errors and MAE
python main.py --training             # record shots into training data
python scripts/import_baseline.py    # bulk import reference shots
python tools/ruler.py                 # on-screen SD ruler overlay
python tools/gen_ruler.py             # regenerate assets/ruler.png (after ruler config changes)
```

---

# AGENTS.md

## Memory Usage Rule

* When nearing context window limit, update PROJECT_MEMORY.md with everything learned since last version
* Read `PROJECT_MEMORY.md` before making changes when necessary
* Treat it as the source of truth for:

  * known issues
  * architecture decisions
  * edge cases

## Update Rule

After any significant change:

* update:
  * Issues
  * Decisions
  * Next Steps
* do NOT overwrite — append, update or refine

## Continuation Rule

When starting a new session:

1. Read PROJECT_MEMORY.md
2. Reconstruct context
3. Continue from "Next Steps" if necessary
