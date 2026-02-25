---
phase: 08-canopy-detection
plan: "01"
subsystem: detection
tags: [python, deepforest, rasterio, shapely, geopandas, cuda, geotiff, nms, tiling]

requires:
  - phase: 07-environment-and-foundation
    provides: Python 3.12 venv (.venv-path-e) with DeepForest 2.0, rasterio, shapely, torch 2.10.0+cu128

provides:
  - canopy_detection.py with GeoTIFF tiling (1024px core, 128px overlap), DeepForest CUDA inference, cross-tile NMS
  - Geographic coordinate transform: pixel bounding boxes -> CRS units via rasterio transform
  - Cross-tile NMS: IoU-based greedy suppression in geographic space, configurable threshold
  - Memory-safe tile-by-tile processing: GDAL_CACHEMAX=256, per-tile array cleanup, periodic CUDA cache flush
  - CLI interface: --mission-id, --ortho-path, --tile-size, --overlap, --score-threshold, --iou-threshold, --output-dir, --force

affects:
  - 08-02 (output/IO: will call detect_canopies() and consume the returned detection list)
  - 09-species-classification (reads E1 rows from canopy_detections table)
  - 10-health-assessment (reads E1 rows)
  - 11-report-generation (uses canopy polygons for map overlays)
  - 12-integration-and-delivery

tech-stack:
  added: []
  patterns:
    - "DeepForest v2 import: `from deepforest import main as deepforest_main` — module not auto-exposed on `import deepforest`"
    - "GeoTIFF tiling: compute_tile_windows() returns (Window, core_col_off, core_row_off) tuples; overlap clamped at image edges"
    - "Pixel-to-geo: rasterio_xy(dataset.transform, abs_row, abs_col) converts absolute pixel coords to CRS units"
    - "NMS: sort by confidence descending, greedy suppress lower-confidence overlapping polygons using Shapely IoU"
    - "Memory: del tile arrays after inference, torch.cuda.empty_cache() every 10 tiles"

key-files:
  created:
    - canopy_detection.py
  modified: []

key-decisions:
  - "DeepForest v2 import path is `from deepforest import main as deepforest_main`, not `deepforest.main.deepforest` — top-level module does not re-export submodules"
  - "predict_image() used per tile (not predict_tile()) because we pre-tile ourselves to control overlap and memory"
  - "NMS operates in geographic space (CRS units), not pixel space — avoids coordinate mapping errors from CRS skew"
  - "Tasks 1 and 2 committed in a single pass: scaffold and detection logic were written holistically for correctness"

patterns-established:
  - "E-script entry: PROJ env cleanup -> GDAL_CACHEMAX -> stdlib imports -> geospatial imports -> deepforest import -> pipeline modules"
  - "Type annotation for DeepForest model: deepforest_main.deepforest (after `from deepforest import main as deepforest_main`)"
  - "Tiling return tuple: (Window, core_col_off, core_row_off) — core_*_off are tile origin WITHOUT overlap, used for geographic offset"

requirements-completed:
  - DET-01
  - DET-02
  - DET-05
  - DET-06
  - DET-07

duration: 15min
completed: 2026-02-25
---

# Phase 08 Plan 01: Canopy Detection Summary

**GeoTIFF tiling engine (1024px/128px overlap), DeepForest CUDA inference via predict_image(), and cross-tile IoU-based NMS in geographic coordinates**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-02-25T14:19:57Z
- **Completed:** 2026-02-25T14:34:00Z
- **Tasks:** 2 of 2
- **Files modified:** 1

## Accomplishments

- canopy_detection.py created with complete detection pipeline: tiling -> CUDA inference -> geo transform -> NMS
- Tiling verified: 2048x2048 ortho with 1024px tiles and 128px overlap produces 4 tiles (correct)
- NMS verified: 2 overlapping boxes (IoU > 0.3) suppressed to 1 kept; non-overlapping box retained
- IoU calculation verified: 0.143 for boxes sharing 1/7 of union area (correct)
- PROJ env cleanup verified: importing module with polluted environment clears PROJ_LIB and PROJ_DATA before any rasterio call
- --help shows all required CLI args; module imports clean with no errors

## Task Commits

Each task was committed atomically:

1. **Task 1+2: canopy_detection.py scaffold and detection engine** - `9ae5d92` (feat)

**Plan metadata:** (docs commit follows)

Note: Both tasks share canopy_detection.py. The file was written holistically — scaffold (Task 1) and detection logic (Task 2) were implemented in a single pass to avoid an intermediate state where argparse exists but the detection functions it calls do not. The single commit captures both task deliverables.

## Files Created/Modified

- `canopy_detection.py` - Core detection engine: GeoTIFF tiling, DeepForest CUDA inference, geographic coordinate transform, cross-tile NMS, argparse CLI, pipeline status reporting

## Decisions Made

- **DeepForest v2 import path:** `from deepforest import main as deepforest_main` — `import deepforest` alone does not expose `deepforest.main` as an attribute; must import the submodule explicitly.
- **predict_image() not predict_tile():** We pre-tile the GeoTIFF ourselves to control overlap size and memory profile. Using DeepForest's built-in `predict_tile()` would re-tile internally, losing our overlap/memory controls.
- **NMS in geographic space:** Bounding boxes are converted to CRS units before NMS. This avoids pixel-space errors that arise when CRS has non-square pixels or skew (common in UTM projections from drone orthos).
- **Single commit for both tasks:** Tasks 1 and 2 target the same file. Writing scaffold-only first would leave the module in a broken intermediate state. Both tasks delivered in one holistic write.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed DeepForest v2 import path**
- **Found during:** Task 1 verification (--help test)
- **Issue:** Plan specified `deepforest.main.deepforest` as the type and constructor call. `import deepforest` does not auto-expose `.main`; accessing it raises `AttributeError: module 'deepforest' has no attribute 'main'`.
- **Fix:** Changed import to `from deepforest import main as deepforest_main`. Updated type annotations and constructor call to use `deepforest_main.deepforest`.
- **Files modified:** canopy_detection.py
- **Verification:** `canopy_detection.py --help` exits 0; `import canopy_detection; print('module loads')` succeeds.
- **Committed in:** 9ae5d92 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: wrong DeepForest v2 import path)
**Impact on plan:** Necessary correctness fix. Same root cause as the 07-01 API discovery (DeepForest v2 changed module layout). No scope creep. All must_haves satisfied.

## Issues Encountered

- DeepForest v2 submodule exposure: same pattern as 07-01 — v2 changed both the callable names (predict removed) and the import path (main not auto-exposed). This is now documented as a project-wide pattern for all future E scripts.

## User Setup Required

None — canopy_detection.py requires only the .venv-path-e Python and a GeoTIFF input. No additional external service configuration for the detection engine itself (Supabase write is handled in 08-02).

## Next Phase Readiness

- canopy_detection.py detection engine ready for 08-02 (output/IO layer: GeoJSON export, Supabase write)
- detect_canopies() returns List[Dict] with polygon, geo coords, confidence, label, dimensions — 08-02 consumes this directly
- Key pattern: `from deepforest import main as deepforest_main` established for all future E scripts that use DeepForest

## Self-Check: PASSED

- FOUND: canopy_detection.py
- FOUND: .planning/phases/08-canopy-detection/08-01-SUMMARY.md
- FOUND: commit 9ae5d92 (feat: scaffold + detection engine)
- FOUND: commit aa1bdfb (docs: metadata, STATE, ROADMAP, REQUIREMENTS)
- FOUND: REQUIREMENTS.md — DET-01, DET-02, DET-05, DET-06, DET-07 marked complete
- FOUND: ROADMAP.md — Phase 8 updated (1/2 plans, In Progress)

---
*Phase: 08-canopy-detection*
*Completed: 2026-02-25*
