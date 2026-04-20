# Wind Reader — Design Study & Implementation Plan

## 1. What the reader needs to do

Continuously capture the wind rose from the game window and write two values to `data/wind.json`:
- **Strength**: integer 0–26 (the number shown in the center of the rose)
- **Angle**: float 0–360° (direction the needle tip points)

---

## 2. Root cause analysis of current failures

### 2.1 Template pixel mismatch (primary issue)

The templates in `data/00.png … 26.png` were captured as 108×108 rose crops, while `capture_rose()` grabs 109×109 pixels. Even a 1px size difference shifts the crop onto different pixels.

More critically: the existing templates were captured outside a live game session (or from a different session). When the game renders the rose, exact RGB values depend on:
- Background scene colour bleeding into the disc edges
- Anti-aliasing at the digit outlines
- Monitor ICC profile / GPU driver colour pipeline

So the correct template can score MAE=17–42 on a live frame, while the runner-up is only 5–10 MAE behind. That margin is too narrow to be reliable.

**Evidence from debug output:**

| Run | Correct template | MAE | Runner-up | MAE | Margin | Result |
|-----|-----------------|-----|-----------|-----|--------|--------|
| wind=18 | 18 | 5.63 | 10 | 24.01 | 18.4 | ✓ correct |
| wind=18 | 18 | 14.53 | 16 | 21.72 | 7.2 | ✓ correct |
| wind=18 | 16 | 17.22 | 18 | 20.86 | 3.6 | ✗ wrong winner |
| wind=21 | 21 | 29.03 | 01 | 34.20 | 5.2 | ✓ correct (barely) |
| wind=01 | 01 | 17.62 | 07 | 31.59 | 14.0 | ✓ correct |

### 2.2 Jitter search addresses position drift but not pixel mismatch

The ±2px offset search (25 positions) handles sub-pixel positioning errors. However:
- The "best" offset varies per frame **and per digit** (`(-1,+1)` for wind 18 vs `(-1,+2)` for wind 21) — this is not a fixed calibration error, it is the search finding slightly different pseudo-optima in mismatched template space
- It can accidentally find a lower MAE at the wrong offset for the wrong template

Baking the offset into the constants is therefore **not** a valid fix.

### 2.3 Needle interference

The needle rotates through the digit crop area on every frame. When it does:
- ~6–15% of crop pixels shift from background-dark to needle-bright
- MAE for the correct template inflates by ~10–25
- If two templates differ mainly in those pixels, the corrupted frame picks the wrong winner

### 2.4 WindBuffer limitation

The 5-frame majority vote handles needle-induced **flicker** (18→16→18→18→18 correctly reports 18). It does **not** help when the wrong template consistently wins every frame (e.g. 18 always reads 16 because templates are mismatched).

---

## 3. Approaches considered

### A — Re-capture all templates from the live game ✅ RECOMMENDED

**How:** Add `--capture N` CLI flag. While wind=N is shown on screen, capture one live frame and save the 109×109 rose crop as `data/NN.png` (overwrite existing). User captures ~10–15 values during gameplay.

**Why it works:** Templates and live frames come from the exact same rendering pipeline. Self-match MAE becomes ~0. Needle-corrupted MAE rises to ~5–15 (only needle pixels differ). Gap between correct and wrong template becomes 30+ MAE — reliable.

**Pros:**
- No algorithm changes needed
- Fixes root cause completely
- Threshold can be tightened to 20 after re-capture

**Cons:**
- Requires user effort (one command per wind value, during play)
- Must be redone if game moves to a different monitor or resolution changes
- Values 08, 22, 24 remain untemplated until seen in game (jitter search covers them approximately)

**Verdict:** Do this first. Everything else is secondary.

---

### B — Edge-based matching

**How:** Before MAE, apply horizontal + vertical 1st-derivative (magnitude) to both query and template. Match on edge images.

**Why it helps:** Edges are invariant to overall brightness offset (monitor gamma, ICC profile). Needle arm pixels produce edges only at the 2px arm boundary — needle interference drops from ~15 MAE to ~3 MAE.

**Pros:** More robust across sessions, lighting changes

**Cons:** Pillow has no built-in Sobel; requires manual 3×3 kernel

**Verdict:** Good follow-up after A. Not a substitute.

---

### C — Binarize on outline pixels only

**How:** Classify pixel < threshold → 1 (dark outline), else 0. Match on binary images.

**Verdict:** Threshold must match actual digit outline darkness — requires well-matched templates anyway. Overlap-ratio metric scored 0.579 for correct template on wind2.png (tested, failed). Approach A + binarized matching would be robust, but A alone is sufficient.

---

### D — Larger jitter search (±4px)

**Verdict:** Does not fix template mismatch. Wrong template can still win at some offset. 81 positions is 3× slower than the current 25. Reject.

---

### E — Temporal consistency filter

**How:** Only commit to a new strength value if it holds for N consecutive majority votes.

**Verdict:** Minor improvement for edge cases. Implement last if needed.

---

## 4. Implementation plan

### Phase 1 — Template re-capture (fixes root cause)

1. Add `--capture N` to `main()` argparse
2. Implement `run_capture(n)` in `wind_reader.py`:
   - Capture one frame via `capture_rose()`
   - Save 109×109 crop to `data/{n:02d}.png` (overwrite)
   - Call `_load_strength_templates.cache_clear()`
   - Print detected strength as cross-check
3. User re-captures during gameplay — priority: **0, 1, 4, 7, 10, 14, 18, 19, 21, 25, 26**
4. Run `--test` → verify self-test MAE < 5 for all re-captured templates
5. Run `--debug` in-game → verify live MAE < 15, gap to runner-up > 15
6. Tighten `OCR_MAE_LIMIT` from 50 → 20

### Phase 2 — Edge-based matching (robustness, after Phase 1)

Replace `_grayscale_crop` with `_edge_crop`:
```
edge(x,y) = |gray(x,y) - gray(x-1,y)| + |gray(x,y) - gray(x,y-1)|
```
Use edge tuples for both template storage and live matching. Makes matcher invariant to brightness offset; reduces needle contribution to arm edges only (~2px wide).

### Phase 3 — Reduce jitter search

After Phase 1+2, offset will consistently be (0,0). Replace ±2px search (25 positions) with ±1px search (9 positions). 3× faster per frame.

---

## 5. What NOT to do

| Idea | Why not |
|------|---------|
| Mask the needle arm | Masking 40%+ of crop kills discriminability — tested, confirmed failed |
| Overlap-ratio metric | Needle makes it collapse (wind2.png scored 0.579 for correct template) |
| Bake a fixed offset into constants | Optimal offset varies per digit because templates are mismatched |
| Expand jitter to ±4px without fixing templates | Wrong template still wins, just at a different offset |

---

## 6. Current state

| Component | Status | Notes |
|-----------|--------|-------|
| Direction detection | ✅ Working | Parabolic sub-step, <0.5° error |
| WindBuffer majority vote | ✅ Working | 5-frame, 60% threshold |
| `write_wind` + `wind.json` | ✅ Working | Includes `stable` field |
| Strength self-test | ✅ Passes | Trivially — same files both sides (MAE≈0) |
| Strength live detection | ⚠️ Unreliable | MAE 17–42, narrow margin, needle flicker |
| Template library | ⚠️ Incomplete | 24/27 values; templates NOT from live game |
| `--capture N` flag | ❌ Not implemented | Needed for Phase 1 |
