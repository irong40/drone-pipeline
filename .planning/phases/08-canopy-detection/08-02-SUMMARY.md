---
phase: 08-canopy-detection
plan: "02"
subsystem: detection
tags: [python, geopandas, geopackage, geojson, supabase, checkpoint, stdout, deepforest, rasterio]

requires:
  - phase: 08-canopy-detection/08-01
    provides: canopy_detection.py with tiling, DeepForest CUDA inference, NMS, detect_canopies() returning List[Dict]

provides:
  - canopy_detection.py complete with GeoPackage + GeoJSON export (canopy_detections.gpkg, canopy_detections.geojson)
  - vegetation_detections Supabase upsert in chunks of 50, non-fatal on failure
  - Per-tile checkpoint resume using tile_N_M keys; --force clears checkpoint
  - JSON stdout: canopy_count, processing_time_seconds, min/max confidence, gpkg_path, geojson_path, supabase_ok
  - v1 exit code contract: 0=success, 1=fatal, 2=partial
  - Zero-canopy case handled: empty schema-correct files written, exits 0

affects:
  - 09-species-classification (reads E1 rows from vegetation_detections; E1 is now fully wired)
  - 10-health-assessment (reads E1 rows)
  - 11-report-generation (uses canopy_detections.gpkg for map overlays)
  - 12-integration-and-delivery (n8n parses JSON stdout from E1)

tech-stack:
  added: []
  patterns:
    - "Supabase upsert pattern: _get_supabase_client() returns None if credentials missing; non-fatal callers log warning + return False"
    - "Batch upsert: slice rows[batch_start:batch_start+50] in loop; on_conflict='mission_id,detection_index'"
    - "Zero-canopy GeoDataFrame: construct empty GDF with explicit column dtypes before to_file() to avoid schema errors"
    - "detect_canopies() signature extended with completed_tiles (Set[str]) and mission_dir (str) for checkpoint integration"
    - "JSON stdout: print(json.dumps(result)) as final line before sys.exit(); confidences list empty-guarded with None for 0-canopy"
    - "Exit code mapping: CUDA/ortho missing = sys.exit(1) fatal; had_partial_failure = sys.exit(2); success = sys.exit(0)"

key-files:
  created: []
  modified:
    - canopy_detection.py

key-decisions:
  - "Tasks 1 and 2 committed together: both target the same file; intermediate state (write_output_files added but detect_canopies not yet updated) would leave a broken script with mismatched function signatures"
  - "detect_canopies() returns tuple (detections, had_partial_failure, dataset_crs) — main() owns all I/O so the core function remains testable without side effects"
  - "CUDA failure exit code corrected from 2 to 1: CUDA unavailable is fatal (no partial output possible), not partial"
  - "GeoDataFrame for zero-canopy uses explicit dtype casting to avoid geopandas schema inference errors when writing empty GPKG"
  - "Supabase upsert uses on_conflict='mission_id,detection_index' — allows idempotent re-runs after partial failures without duplicate rows"

patterns-established:
  - "E-script output layer: write_output_files() -> upsert_detections_to_supabase() -> print(json.dumps()) -> sys.exit()"
  - "Non-fatal Supabase writes: _get_supabase_client() returns None on missing credentials or import error; callers never crash"
  - "JSON stdout parseable by n8n: print() to stdout, all other output to log file + stderr; last line is always the JSON result"

requirements-completed:
  - DET-03
  - DET-04

duration: 15min
completed: 2026-02-25
---

# Phase 08 Plan 02: Canopy Detection Output Layer Summary

**GeoPackage + GeoJSON export via geopandas, batched Supabase upsert to vegetation_detections, per-tile checkpoint resume, JSON stdout, and v1 exit code contract — canopy_detection.py is now a complete production-ready E1 script**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-02-25T14:33:46Z
- **Completed:** 2026-02-25T14:49:09Z
- **Tasks:** 2 of 2
- **Files modified:** 1

## Accomplishments

- write_output_files() writes GeoPackage + GeoJSON with all 8 canopy attributes; zero-canopy case writes empty schema-correct files rather than skipping
- upsert_detections_to_supabase() batches 50 rows per request, non-fatal (warns + returns False on missing credentials or network failure, never crashes the pipeline)
- detect_canopies() extended with per-tile checkpoint save/skip — restart after kill resumes from the last completed tile
- JSON stdout on final line (n8n-parseable): canopy_count, processing_time_seconds, min/max confidence, file paths, supabase_ok flag
- Exit codes verified present in source: 0=all tiles success, 1=fatal (CUDA/ortho missing/output write failure), 2=partial tile failure
- All 5 plan must-have truths verified by automated checks against real file I/O

## Task Commits

Tasks 1 and 2 were committed together (single file, holistic implementation):

1. **Tasks 1+2: GeoPackage/GeoJSON export, Supabase upsert, checkpoint resume, JSON stdout, exit codes** - `e4732f5` (feat)

**Plan metadata:** (docs commit follows)

Note: Both tasks share canopy_detection.py. Writing Task 1 alone would leave main() still calling the old single-return detect_canopies() while write_output_files() already expected the new 3-tuple return. Single commit avoids broken intermediate state.

## Files Created/Modified

- `canopy_detection.py` — Complete E1 script: tiling + CUDA inference + NMS (08-01) + GeoPackage/GeoJSON export + Supabase upsert + checkpoint resume + JSON stdout + exit codes (08-02)

## Decisions Made

- **Tasks 1+2 single commit:** Both tasks modify the same file; an intermediate state where write_output_files() exists but detect_canopies() still returns a bare list would break main(). Holistic write is safer and simpler.
- **detect_canopies() returns 3-tuple:** (detections, had_partial_failure, dataset_crs). main() owns all I/O side effects (file write, DB write, stdout, exit). Core function stays testable in isolation.
- **CUDA exit code 1 not 2:** CUDA unavailable means zero tiles processed, zero output possible — that is fatal (1), not partial (2). The 08-01 code incorrectly used sys.exit(2). Fixed here.
- **Empty GeoDataFrame dtype cast:** geopandas cannot infer column types from an empty list of geometries. Explicit `.astype({...})` prevents schema mismatch errors when writing to GPKG/GeoJSON with zero rows.
- **Upsert conflict key:** `on_conflict='mission_id,detection_index'` makes re-runs idempotent. If a Supabase write partially succeeds, re-running with the same mission_id will update existing rows rather than insert duplicates.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed CUDA failure exit code from 2 to 1**
- **Found during:** Task 2 (exit code review)
- **Issue:** 08-01 code had `sys.exit(2)` for CUDA assertion failure. Exit code 2 means "partial success — some tiles processed, output produced". CUDA unavailable means zero tiles can run, zero output. That is a fatal error (exit 1).
- **Fix:** Changed CUDA AssertionError handler to `sys.exit(1)`.
- **Files modified:** canopy_detection.py
- **Verification:** inspect.getsource check confirms all three exit codes present; exit code semantics are correct.
- **Committed in:** e4732f5 (task commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: wrong exit code for CUDA failure)
**Impact on plan:** Necessary correctness fix for v1 contract adherence. No scope creep.

## Issues Encountered

- geopandas zero-canopy GeoDataFrame: `gpd.GeoDataFrame(columns=[...], geometry=[], crs=crs)` creates columns but with object dtype. Calling `.to_file(..., driver="GPKG")` on an empty GDF with untyped numeric columns can produce schema warnings in some GDAL versions. Fixed with explicit `.astype({...})` to set numeric columns to float64/int64 before writing.

## User Setup Required

None — the E1 script runs from .venv-path-e with only GeoTIFF input required. Supabase writes are automatically skipped (warning logged) when SUPABASE_URL / SUPABASE_SERVICE_KEY are not set — useful for local testing without credentials.

## Next Phase Readiness

- canopy_detection.py is fully complete and production-ready for all E-path missions
- vegetation_detections rows will be written per-detection with mission_id, geometry_wkt, dimensions, and confidence
- canopy_detections.gpkg / canopy_detections.geojson will be available in the ortho output directory
- JSON stdout is n8n-parseable — n8n reads the last line of stdout to get canopy_count and file paths
- Phase 09 (Species Classification) can read E1 rows from vegetation_detections using mission_id FK

## Self-Check: PASSED

- FOUND: canopy_detection.py (modified)
- FOUND: commit e4732f5 (feat: GeoPackage/GeoJSON, Supabase upsert, checkpoint, JSON stdout, exit codes)
- FOUND: write_output_files() function
- FOUND: upsert_detections_to_supabase() function
- FOUND: per-tile checkpoint save/skip in detect_canopies()
- FOUND: json.dumps(result) stdout in main()
- FOUND: sys.exit(0), sys.exit(1), sys.exit(2) all present
- FOUND: zero-canopy case handled in write_output_files()
- VERIFIED: All 5 must-have truths pass automated checks

---
*Phase: 08-canopy-detection*
*Completed: 2026-02-25*
