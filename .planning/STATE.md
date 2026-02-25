# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-24)

**Core value:** Every script runs reliably, recovers from failures, and has tests proving it works
**Current focus:** v2.0 Vegetation Analysis Pipeline — Phase 13 (Test Suite and Acceptance) — In Progress

## Current Position

Phase: 13 of 13 (Test Suite and Acceptance)
Plan: 1 of 4 in current phase (13-01 COMPLETE)
Status: 13-01 complete — E1/E2 unit tests (50 tests); Phase 13 Plans 02-04 remain
Last activity: 2026-02-25 — 13-01 complete: test_canopy_detection.py (26 E1 tests), test_species_classification.py (24 E2 tests), full module stubs for system Python, PLANTNET_QUOTA_EXHAUSTED sentinel committed

Progress: [████████████░░░░░░░░] 60% (Phases 7+8+9+10+11+12 complete; Phase 13 in progress)

## Performance Metrics

**Velocity (v1.0):**
- Total plans completed: 17
- Average duration: 2.2 min
- Total execution time: ~37 min

**v2.0 Plans Completed:**

| Phase | Plan | Duration | Files | Date |
|-------|------|----------|-------|------|
| 7. Environment and Foundation | 07-01 (venv+GPU) | 11 min | 2 | 2026-02-25 |
| 7. Environment and Foundation | 07-02 (schema) | 2 min | 2 | 2026-02-25 |
| 8. Canopy Detection | 08-01 (detection engine) | 15 min | 1 | 2026-02-25 |
| 8. Canopy Detection | 08-02 (output layer) | 15 min | 1 | 2026-02-25 |
| 9. Species Classification | 09-01 (species_classification.py) | 25 min | 1 | 2026-02-25 |
| 10. Health Assessment | 10-01 (health_assessment.py) | 3 min | 1 | 2026-02-25 |
| 11. Report Generation | 11-01 (vegetation_report.py maps) | 3 min | 1 | 2026-02-25 |
| 11. Report Generation | 11-02 (PDF + Supabase summary) | 3 min | 1 | 2026-02-25 |
| 13. Test Suite | 13-01 (E1/E2 unit tests) | 35 min | 3 | 2026-02-25 |

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table for full history.
Recent decisions affecting v2.0 work:

- [v2.0 roadmap]: Python 3.12 venv (.venv-path-e) separate from system Python 3.14 — DeepForest requires <3.13
- [v2.0 roadmap]: Use predict_tile() for cross-tile NMS rather than manual tile stitching
- [v2.0 roadmap]: Start with --skip-plantnet=true for first missions; enable after baseline established
- [07-02]: drone_jobs is the actual missions table — all FKs reference public.drone_jobs(id)
- [07-02]: processing_steps.step_name is free TEXT (no ENUM, no CHECK)
- [07-02]: RLS uses TO service_role role targeting for Python E scripts using service key
- [08-01]: DeepForest v2 import path is from deepforest import main as deepforest_main
- [08-01]: predict_image() used per tile — we pre-tile for overlap control
- [08-01]: NMS operates in geographic space (CRS units) not pixel space
- [Phase 08-canopy-detection]: detect_canopies() returns (detections, had_partial_failure, dataset_crs) tuple
- [Phase 08-canopy-detection]: Supabase upsert on_conflict='mission_id,detection_index'
- [10-01]: Checkpoint key format canopy_{detection_index} — per-canopy granularity
- [09-01]: reconcile() extracts genus from species_scientific (first word)
- [09-01]: cost_threshold guard runs BEFORE classification loop
- [09-01]: run_classification() added as testable orchestration function
- [Phase 11-report-generation]: matplotlib Agg backend set before pyplot import for headless rendering
- [Phase 11-report-generation]: Folium interactive map tier-gated: extended/comprehensive only
- [11-02]: Pie chart temp PNG deferred cleanup after doc.build()
- [11-02]: GPS in attention list uses centroid_lat/centroid_lon from vegetation_detections
- [13-01]: Module-level sys.modules stub injection for E1/E2 tests — before import, not autouse fixtures
- [13-01]: FakePolygon with real AABB geometry replaces shapely for IoU/intersection tests
- [13-01]: Lazy-imported symbols patched via sys.modules[mod].attr not patch("module.Symbol")
- [13-01]: numpy stub needs np.bool_, np.isscalar for pytest.approx compatibility

### Pending Todos

None.

### Blockers/Concerns

- ~~ENV: PyTorch CPU silent fallback on RTX 5070~~ RESOLVED (07-01)
- ~~ENV: PROJ_LIB/PROJ_DATA conflict from QGIS~~ RESOLVED (07-01)
- SPE: Species accuracy is 30-55% top-1 — methodology disclaimer in PDF is non-negotiable
- TST: test_health_assessment.py and test_vegetation_report.py have pre-existing failures on system Python — import numpy/folium at module level; should use stub-injection pattern from 13-01

## Session Continuity

Last session: 2026-02-25
Stopped at: Completed 13-01-PLAN.md — test_canopy_detection.py (26 E1 tests) and test_species_classification.py (24 E2 tests); TST-01/TST-02 satisfied.
Resume file: None
