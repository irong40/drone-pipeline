---
phase: 10-health-assessment
plan: 01
subsystem: vegetation-analysis
tags: [health-assessment, vari, exg, vegetation-indices, openai-vision, checkpoint, supabase]
dependency_graph:
  requires: [canopy_detection.py, vegetation_detections table (E1 rows)]
  provides: [health_assessment.py, health_score+health_status+health_details per canopy]
  affects: [vegetation_report.py (E4 reads health data)]
tech_stack:
  added: [rasterio.mask, shapely.wkt, PIL/Pillow, openai]
  patterns: [VARI/ExG vegetation indices, OpenAI Vision base64 crop, per-canopy checkpoint resume, Supabase batch update]
key_files:
  created: [health_assessment.py]
  modified: []
decisions:
  - "Vision sample selects bottom vision_sample_pct by index_score ascending (worst-looking trees get Vision API)"
  - "Cost threshold guard prevents runaway API spend before vision loop starts"
  - "Checkpoint key format: canopy_{detection_index} — consistent with E1 tile_ keys"
  - "update_health_batch uses individual UPDATE per row (not upsert) since E1 rows already exist"
  - "crop_canopy_image rescales to max 512px for cost control before base64 encoding"
metrics:
  duration_minutes: 3
  completed_date: "2026-02-25"
  tasks_completed: 2
  files_created: 1
  files_modified: 0
requirements_satisfied: [HLT-01, HLT-02, HLT-03, HLT-04, HLT-05, HLT-06]
---

# Phase 10 Plan 01: Health Assessment Summary

**One-liner:** VARI/ExG health scoring with OpenAI Vision qualitative assessment for bottom-30% canopies, checkpoint resume, and Supabase batch update.

## What Was Built

`health_assessment.py` — Step E3 of the vegetation analysis pipeline. Reads all canopy detections from `vegetation_detections` (written by E1), computes RGB-derived vegetation indices per canopy polygon, optionally calls OpenAI Vision for the lowest-scoring 30%, and writes final health scores back to Supabase.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Script scaffold + VARI/ExG computation + health scoring | 967a849 | health_assessment.py |
| 2 | Vision sampling + checkpoint + Supabase + JSON stdout | 967a849 | health_assessment.py (included in T1 commit) |

Note: Both tasks contributed to the same file. Task 1 commit (967a849) contains the complete implementation.

## Key Decisions Made

### Vision sample targets lowest-scoring canopies
The bottom `vision_sample_pct` (default 30%) by `index_score` ascending are selected for Vision API calls. These are the most stressed trees — the ones that will appear on the "attention list" in the E4 report. Higher-scoring healthy trees don't need Vision API confirmation.

### Cost threshold guard before API loop
`estimate_vision_cost(n)` runs before the Vision API loop. If `estimated_cost > cost_threshold` (default $2.00), the loop is skipped with a warning. Prevents accidental runaway billing on large missions.

### Update vs. upsert for Supabase
`update_health_batch()` uses `UPDATE ... WHERE id = ?` per row rather than upsert. E1 already inserted the rows; we're just filling in the health columns. Using UPDATE is semantically correct and avoids any risk of inserting duplicate rows.

### Checkpoint key: `canopy_{detection_index}`
Consistent with E1's `tile_{col}_{row}` format. Per-canopy granularity means a partial run resumes from the exact canopy that failed, preventing re-billing for already-assessed Vision API calls.

### Image crop resized to max 512px
`crop_canopy_image()` rescales canopy crops to max 512px on the longest side before JPEG encoding. Reduces token cost and payload size while retaining enough detail for health assessment. Uses `detail: "low"` in the OpenAI API call for additional cost control.

## Health Score Formula Summary

```
index_score = vari_norm*0.3 + exg_norm*0.2 + green_fraction*0.3 + (1-stress_fraction)*0.2

health_score = index_score*0.4 + vision_score*0.6   # when vision available
health_score = index_score                            # when --skip-vision or not sampled

Status thresholds:
  >= 0.80  -> healthy
  >= 0.60  -> moderate_stress
  >= 0.40  -> stressed
  >= 0.20  -> severe_decline
  <  0.20  -> dead
```

## Requirements Satisfied

- **HLT-01**: VARI and ExG indices computed per pixel for every canopy polygon via `compute_health_indices()`
- **HLT-02**: `compute_index_score()` implements composite formula with documented weights
- **HLT-03**: `compute_health_score()`: 40% index + 60% vision when available; index-only when `--skip-vision`
- **HLT-04**: `health_status()` categorizes into 5 tiers (healthy/moderate_stress/stressed/severe_decline/dead)
- **HLT-05**: Vision sample selects bottom 30% (configurable via `--vision-sample-pct`), checkpoint prevents re-billing
- **HLT-06**: Health data written to `vegetation_detections` via `update_health_batch()`, JSON stdout output

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- [x] health_assessment.py created at C:/Users/redle/drone-pipeline/health_assessment.py
- [x] Commit 967a849 exists
- [x] --help works
- [x] Module imports cleanly
- [x] All mathematical functions verified against hand calculations
- [x] All 4 plan verification criteria satisfied
