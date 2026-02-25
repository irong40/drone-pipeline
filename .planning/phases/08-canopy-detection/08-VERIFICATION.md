---
phase: 08-canopy-detection
verified: 2026-02-25T15:30:00Z
status: gaps_found
score: 6/8 must-haves verified
re_verification: false
gaps:
  - truth: "Running canopy_detection.py on a 500MB test orthomosaic completes in under 5 minutes with CUDA and produces a GeoPackage with at least one polygon"
    status: partial
    reason: "Script wiring is complete and CUDA path is correct, but no test run against a real orthomosaic has been verified. Performance ceiling cannot be confirmed without a real execution. Code path is substantively correct; this is a human-only verification item."
    artifacts: []
    missing:
      - "Human test run on a real GeoTIFF orthomosaic (any size) to confirm at least one polygon is produced and timing is acceptable"

  - truth: "had_partial_failure flag is never set to True in the tile loop — exit code 2 is unreachable for per-tile inference failures"
    status: failed
    reason: "run_inference_on_tile() silently returns None on any exception (line 207: 'except Exception: return None'). The tile loop treats None as 'no detections', not as a tile failure. had_partial_failure is initialized to False and no code ever sets it True. The v1 exit code contract promises exit 2 for partial tile failure, but that path is dead code."
    artifacts:
      - path: "canopy_detection.py"
        issue: "Lines 204-207: bare except swallows tile inference errors. Lines 537/631: had_partial_failure=False never mutated. Line 799-802: sys.exit(2) branch is unreachable."
    missing:
      - "In the tile loop, catch inference exceptions separately and set had_partial_failure = True when a tile fails"
      - "Distinguish between 'no detections' (results_df is None after successful inference) and 'inference error' (exception raised) in run_inference_on_tile or in the caller"

  - truth: "step_name='canopy_detection' does not match the DB enum value 'veg_canopy_detection' required by ENV-05"
    status: failed
    reason: "The PipelineStatusReporter is instantiated at line 740 with step_name='canopy_detection'. ENV-05 (Phase 7, complete) extended the processing steps enum with 'veg_canopy_detection'. If the processing_jobs.steps JSONB uses the enum value 'veg_canopy_detection', the reporter's _update_step() will warn 'step not found' and all status reporting will silently no-op."
    artifacts:
      - path: "canopy_detection.py"
        issue: "Line 740: step_name='canopy_detection' — should be 'veg_canopy_detection' per ENV-05 and REQUIREMENTS.md"
    missing:
      - "Change line 740: step_name='canopy_detection' -> step_name='veg_canopy_detection'"

human_verification:
  - test: "Run canopy_detection.py on a real orthomosaic GeoTIFF"
    expected: "Script completes under 5 minutes on a 500MB ortho with CUDA, produces canopy_detections.gpkg with at least one polygon feature"
    why_human: "Cannot verify performance, real DeepForest inference output, or actual GeoPackage polygon count without running the script against real imagery"
  - test: "Kill canopy_detection.py mid-run, then restart with the same arguments (no --force)"
    expected: "Script logs 'Resuming from checkpoint: N tiles already complete' and skips those tiles"
    why_human: "Checkpoint resume requires an actual execution with a file that takes long enough to kill mid-run"
  - test: "Visually inspect canopy_detections.gpkg in QGIS"
    expected: "Polygons appear correctly placed over tree canopies, no gross duplicate inflation at tile seams"
    why_human: "Spatial accuracy and duplicate suppression quality require visual inspection against imagery"
  - test: "Run on a 1GB orthomosaic and monitor RSS"
    expected: "Peak RSS stays under 2GB, no OOM error raised"
    why_human: "Memory profiling requires real execution (e.g., /usr/bin/time -v or psutil monitoring wrapper)"
---

# Phase 8: Canopy Detection Verification Report

**Phase Goal:** Operators can run canopy_detection.py on a real orthomosaic and receive a GeoPackage with individual tree polygons and a Supabase row per detection
**Verified:** 2026-02-25T15:30:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

The phase defines 5 success criteria from the prompt, and 11 plan must-haves across 08-01 and 08-02. I verify all of them.

**From Phase Success Criteria:**

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | Runs on 500MB ortho under 5 min with CUDA, produces GeoPackage with at least one polygon | ? UNCERTAIN | Code path is complete and correct. Cannot confirm without real execution. Flagged for human verification. |
| SC-2 | Canopy count within 30% of manual visual inspection (no duplicate inflation from tile overlap) | ? UNCERTAIN | NMS in geographic space with IoU 0.3 is fully implemented (lines 276-314). Accuracy vs. reality requires human test. |
| SC-3 | Each detection row in vegetation_detections has area_sqm, width_m, height_m, centroid lat/lon, confidence | VERIFIED | Lines 451-458 in upsert_detections_to_supabase() map all five attributes. GeoDataFrame also includes all five (lines 346-351). |
| SC-4 | (Duplicate of SC-3) | VERIFIED | Same evidence as SC-3. |
| SC-5 | 1GB orthomosaic stays under 2GB peak RSS, no OOM error | ? UNCERTAIN | GDAL_CACHEMAX=256 set at line 17. Per-tile del + empty_cache every 10 tiles at lines 572, 575, 579. Memory design is correct; actual RSS limit requires real run. |

**From Plan 08-01 Must-Haves:**

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| P01-T1 | Tiles GeoTIFF into 1024px chunks with 128px overlap | VERIFIED | compute_tile_windows() lines 101-147; defaults tile_size=1024, overlap=128 in argparse lines 667/675 |
| P01-T2 | DeepForest runs on CUDA, returns bounding boxes with confidence scores per tile | VERIFIED | load_deepforest_model() lines 152-167: model.model.to("cuda"), model.model.eval(); run_inference_on_tile() lines 170-217 |
| P01-T3 | Cross-tile NMS with IoU 0.3 removes duplicates | VERIFIED | cross_tile_nms() lines 276-314; default iou_threshold=0.3 at line 687; called at line 627 |
| P01-T4 | Parameters configurable via CLI | VERIFIED | --tile-size, --score-threshold, --iou-threshold all defined in argparse (lines 663-694) and threaded to detect_canopies() |
| P01-T5 | PROJ_LIB/PROJ_DATA cleared before rasterio import | VERIFIED | Lines 14-17: env cleanup runs before any import; rasterio imported at line 31 |
| P01-T6 | 1GB+ ortho under 2GB RSS with GDAL_CACHEMAX=256 | UNCERTAIN | Design correct (GDAL_CACHEMAX=256, del arrays, empty_cache). Runtime verification requires human test. |

**From Plan 08-02 Must-Haves:**

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| P02-T1 | GeoPackage and GeoJSON written with area, width, height, centroid, confidence | VERIFIED | write_output_files() lines 319-395; gdf.to_file(..., driver="GPKG") line 382; all 8 attributes populated |
| P02-T2 | Each detection written to vegetation_detections in Supabase with dimensional attributes | VERIFIED | upsert_detections_to_supabase() lines 419-490; batches 50 rows; conflict key mission_id,detection_index |
| P02-T3 | Checkpoint resume skips already-processed tiles on restart | VERIFIED | load_checkpoint() called at line 733; tile_key checked at line 559; save_checkpoint() called at line 620 per tile |
| P02-T4 | JSON stdout includes canopy_count, processing_time_seconds, min/max confidence | VERIFIED | Lines 787-796; print(json.dumps(result)) at line 796; last line before sys.exit |
| P02-T5 | Exit codes: 0=success, 1=error, 2=partial | PARTIAL | Exit 0 (line 805), exit 1 (lines 717, 722, 760, 776, 813) all reachable. Exit 2 (line 802) is unreachable — had_partial_failure is always False. |

**Score: 6/8 truths fully verified** (SC-1, SC-2, SC-5, P01-T6 are uncertain/human; P02-T5 and step_name mismatch are code-level failures)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `canopy_detection.py` | Core detection with tiling, DeepForest, NMS | VERIFIED | 814 lines. Substantive implementation. All detection, export, and DB functions present. |
| `checkpoint.py` | Checkpoint save/load/clear | VERIFIED | 62 lines. load_checkpoint, save_checkpoint, clear_checkpoint all implemented and called by canopy_detection.py |
| `pipeline_status.py` | PipelineStatusReporter, add_pipeline_args | VERIFIED | 236 lines. PipelineStatusReporter with start/complete/fail. add_pipeline_args present. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| canopy_detection.py tile loop | deepforest predict_image() | CUDA inference per tile | VERIFIED | run_inference_on_tile() calls model.predict_image(image=tile_array, return_plot=False) at line 205; model on CUDA from line 164 |
| canopy_detection.py NMS | shapely intersection/union | IoU calculation | VERIFIED | compute_iou() lines 265-273: poly_a.intersection(poly_b).area / poly_a.union(poly_b).area |
| canopy_detection.py export | geopandas.to_file() | GeoPackage + GeoJSON write | VERIFIED | Lines 382-393: gdf.to_file(gpkg_path, driver="GPKG") and gdf.to_file(geojson_path, driver="GeoJSON") |
| canopy_detection.py | vegetation_detections table | supabase client upsert | VERIFIED | Line 468: client.table("vegetation_detections").upsert(batch, on_conflict="mission_id,detection_index").execute() |
| canopy_detection.py | checkpoint.save_checkpoint | per-tile checkpoint | VERIFIED | Line 620: save_checkpoint(mission_dir, SCRIPT_NAME, completed_tiles) inside tile loop |
| PipelineStatusReporter | processing_jobs steps | step_name lookup | BROKEN | Line 740: step_name="canopy_detection" but ENV-05 enum value is "veg_canopy_detection". Reporter will silently no-op on every call. |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DET-01 | 08-01 | Tiles ortho 1024px/128px overlap, DeepForest CUDA | SATISFIED | compute_tile_windows() + load_deepforest_model() + run_inference_on_tile() |
| DET-02 | 08-01 | Cross-tile NMS IoU 0.3 | SATISFIED | cross_tile_nms() with configurable iou_threshold, default 0.3 |
| DET-03 | 08-02 | GeoPackage + GeoJSON with area, width, height, centroid GPS, confidence | SATISFIED | write_output_files() builds GeoDataFrame with all 8 attributes + to_file() |
| DET-04 | 08-02 | Each canopy written to vegetation_detections with geometry and dimensions | SATISFIED | upsert_detections_to_supabase() with all 8 columns; batched 50 rows |
| DET-05 | 08-01 | tile_size, score_threshold, iou_threshold configurable via CLI | SATISFIED | All three in argparse with defaults; processing_templates.vegetation_config integration is deferred (INT scope) |
| DET-06 | 08-01 | PROJ_LIB/PROJ_DATA cleared before rasterio import | SATISFIED | Lines 14-17 clear both vars before any geospatial import |
| DET-07 | 08-01 | GDAL_CACHEMAX=256, tile memory management for 1GB+ OOM safety | SATISFIED (design) | GDAL_CACHEMAX=256 at line 17; del tile_chw line 572; del tile_hwc line 575; empty_cache every 10 tiles line 579 |

All 7 requirements (DET-01 through DET-07) are covered and satisfied at the code level. DET-07 runtime confirmation requires human verification.

**Orphaned requirements check:** No requirements mapped to Phase 8 in REQUIREMENTS.md beyond DET-01 through DET-07. No orphans.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| canopy_detection.py | 204-207 | `except Exception: return None` — swallows inference errors silently | Warning | Tile inference failures are indistinguishable from "no detections". had_partial_failure never set True. Exit code 2 is unreachable. |
| canopy_detection.py | 537 | `had_partial_failure = False` — never mutated to True | Warning | Dead code: lines 799-802 (exit 2 branch) can never execute during the current implementation. |
| canopy_detection.py | 740 | `step_name="canopy_detection"` — does not match DB enum "veg_canopy_detection" | Blocker | All PipelineStatusReporter calls will silently fail with "step not found" warning. n8n pipeline status tracking will not work. |

---

## Human Verification Required

### 1. End-to-end run on real orthomosaic

**Test:** Run `python canopy_detection.py --mission-id test-001 --ortho-path /path/to/real/orthomosaic.tif`
**Expected:** Completes in under 5 minutes on a 500MB ortho with CUDA. canopy_detections.gpkg is written with at least one polygon feature. JSON stdout on the last line is parseable.
**Why human:** DeepForest inference output depends on real imagery and model weights. Cannot mock the result of predict_image() against actual tree canopies.

### 2. GeoPackage spatial accuracy

**Test:** Open canopy_detections.gpkg in QGIS and overlay on the source orthomosaic.
**Expected:** Polygons fall over tree canopy locations. No gross duplicate inflation at tile boundaries. Canopy count is within 30% of manual visual count.
**Why human:** Spatial accuracy and NMS effectiveness require visual comparison against known reference imagery.

### 3. Checkpoint resume

**Test:** Run on a large ortho, kill with Ctrl-C after several tiles, re-run with the same arguments (no --force).
**Expected:** Startup log shows "Resuming from checkpoint: N tiles already complete" and those tiles are skipped.
**Why human:** Requires a real multi-tile run long enough to interrupt.

### 4. Memory ceiling on 1GB orthomosaic

**Test:** Run on a 1GB+ ortho and track peak RSS (e.g., wrap with `python -c "import resource; ... resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss"` or use psutil).
**Expected:** Peak RSS stays under 2GB, no MemoryError raised.
**Why human:** Memory profiling requires a real execution with real data.

---

## Gaps Summary

**Two code-level gaps found. One human verification cluster.**

**Gap 1 — Step name mismatch (Blocker):** `step_name="canopy_detection"` at line 740 does not match the DB enum value `veg_canopy_detection` established by ENV-05. Every `reporter.start()`, `reporter.complete()`, and `reporter.fail()` call will silently no-op because `_update_step()` will log "step not found" and return False. This means n8n will never see E1 step status transitions. One-line fix: change `"canopy_detection"` to `"veg_canopy_detection"`.

**Gap 2 — had_partial_failure never set True (Warning, exit code contract broken):** `run_inference_on_tile()` catches all exceptions and returns `None`, making tile inference failures indistinguishable from "no trees detected on this tile." The `had_partial_failure` flag initialized at line 537 is never mutated, making the exit-2 branch at lines 799-802 dead code. The v1 contract promises exit 2 for partial success. Fix: in the tile loop, distinguish `results_df is None due to exception` from `results_df is None due to no detections` and set `had_partial_failure = True` for the former.

**Human cluster:** Four items cannot be verified without a real orthomosaic and GPU: end-to-end polygon production, spatial accuracy vs. manual count, checkpoint resume behavior, and 2GB RSS ceiling. These are runtime behaviors — the code design supports all of them correctly.

---

*Verified: 2026-02-25T15:30:00Z*
*Verifier: Claude (gsd-verifier)*
