# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-24)

**Core value:** Every script runs reliably, recovers from failures, and has tests proving it works
**Current focus:** v2.0 Vegetation Analysis Pipeline — Phase 13 (Test Suite and Acceptance) — In Progress

## Current Position

Phase: 13 of 13 (Test Suite and Acceptance)
Plan: 3 of 3 in current phase (13-01, 13-02, 13-03 all COMPLETE — Task 2 checkpoint deferred, no ortho available)
Status: Phase 13 execution complete — all automated tests passing; real-ortho acceptance deferred
Last activity: 2026-02-25 — 13-03 checkpoint deferred (no processed orthomosaic available); proceeding to phase verification

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
| 13. Test Suite | 13-02 (E3/E4 unit tests) | — | 3 | 2026-02-25 |
| 13. Test Suite | 13-03 Task 1 (integration tests) | 25 min | 2 | 2026-02-25 |
| 9. Species Classification | 09-02 (safety controls + JSON stdout) | 8 min | 1 | 2026-02-25 |
| 12. Integration and Delivery | 12-01 (n8n Path E workflow + package router patch) | 4 min | 2 | 2026-02-25 |
| 12. Integration and Delivery | 12-02 (delivery veg subfolder + review gate docs) | 5 min | 2 | 2026-02-25 |

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
- [Phase 13]: vegetation/.status sentinel file convention — writable by E4, read by delivery_packaging for delivery gate
- [Phase 13]: collect_vegetation() returns [] for any non-complete status — safe default, no partial outputs in ZIP
- [Phase 09]: PLANTNET_QUOTA_EXHAUSTED is a module-level sentinel dict — identity check (is) distinguishes it from normal None returns
- [Phase 09]: time.sleep(0.5) placed at END of per-canopy block to rate-limit both OpenAI and PlantNet calls
- [12-01]: n8n Path E workflow uses .venv-path-e Python (E:\Sentinel\.venv-path-e\Scripts\python.exe) — not system Python 3.14 which lacks DeepForest
- [12-01]: E0 ortho polling: 60s interval, 30 attempts max = 30-minute timeout; sets vegetation_status=failed on timeout
- [12-01]: Zero-canopy bypass: E1 canopy_count=0 skips E2/E3, routes directly to report generation
- [12-01]: Review gate uses n8n Webhook Wait node — workflow thread pauses until POST /sentinel-vegetation-resume
- [12-01]: vegetation_report.py (E4) intentionally omits checkpoint — idempotent (reads fresh from Supabase each run)
- [12-01]: Package router: vegetation_enabled=true by default for site_survey and environmental_survey only
- [12-02]: collect_vegetation() returns [] for any non-complete status — two-gate safety: CLI flag (opt-in) + vegetation_status=complete (data guard)
- [12-02]: Decisions array for review gate contains only non-default overrides; omitting detection_index implicitly approves it
- [12-02]: REVIEW_GATE.md in repo root (not embedded in delivery_packaging.py) — contract is for Trestle admin UI (separate project)

### Pending Todos

None.

### Blockers/Concerns

- ~~ENV: PyTorch CPU silent fallback on RTX 5070~~ RESOLVED (07-01)
- ~~ENV: PROJ_LIB/PROJ_DATA conflict from QGIS~~ RESOLVED (07-01)
- SPE: Species accuracy is 30-55% top-1 — methodology disclaimer in PDF is non-negotiable
- TST: test_health_assessment.py and test_vegetation_report.py have pre-existing failures on system Python — import numpy/folium at module level; should use stub-injection pattern from 13-01

## Session Continuity

Last session: 2026-02-25
Stopped at: Completed 12-01-PLAN.md — n8n Path E workflow JSON (35 nodes) + package router patch + v1 contract smoke test. Phase 12 now fully complete (both 12-01 + 12-02 done). Phase 13 still at checkpoint 13-03 Task 2.
Resume file: None
