# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-24)

**Core value:** Every script runs reliably, recovers from failures, and has tests proving it works
**Current focus:** v2.0 Vegetation Analysis Pipeline — Phase 10 (Health Assessment)

## Current Position

Phase: 10 of 13 (Health Assessment)
Plan: 1 of 1 in current phase (PHASE COMPLETE)
Status: Phase 10 complete — moving to Phase 11 (Report Generation)
Last activity: 2026-02-25 — 10-01 complete: health_assessment.py (VARI/ExG indices, health scoring, OpenAI Vision sampling, checkpoint resume, Supabase update, JSON stdout)

Progress: [████████░░░░░░░░░░░░] 40% (8/13 phases complete — v1.0 shipped; Phases 7+8+9+10 complete)

## Performance Metrics

**Velocity (v1.0):**
- Total plans completed: 17
- Average duration: 2.2 min
- Total execution time: ~37 min

**By Phase (v1.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Code Hardening | 4 | ~9 min | 2.2 min |
| 2. Test Infrastructure | 2 | ~4 min | 2.2 min |
| 3. Ingest Layer Tests | 3 | ~7 min | 2.2 min |
| 4. Video Pipeline Tests | 3 | ~7 min | 2.2 min |
| 5. Delivery Layer Tests | 2 | ~4 min | 2.2 min |
| 6. Integration Tests | 3 | ~7 min | 2.2 min |

*v2.0 metrics will be tracked here as plans complete*

**v2.0 Plans Completed:**

| Phase | Plan | Duration | Files | Date |
|-------|------|----------|-------|------|
| 7. Environment and Foundation | 07-01 (venv+GPU) | 11 min | 2 | 2026-02-25 |
| 7. Environment and Foundation | 07-02 (schema) | 2 min | 2 | 2026-02-25 |
| 8. Canopy Detection | 08-01 (detection engine) | 15 min | 1 | 2026-02-25 |
| 8. Canopy Detection | 08-02 (output layer) | 15 min | 1 | 2026-02-25 |
| 10. Health Assessment | 10-01 (health_assessment.py) | 3 min | 1 | 2026-02-25 |

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table for full history.
Recent decisions affecting v2.0 work:

- [v2.0 roadmap]: Python 3.12 venv (.venv-path-e) separate from system Python 3.14 — DeepForest requires <3.13
- [v2.0 roadmap]: Install PyTorch via --index-url before DeepForest to avoid CPU-only build (2.9.1 not published; 2.10.0+cu128 installed)
- [v2.0 roadmap]: Use predict_tile() for cross-tile NMS rather than manual tile stitching
- [v2.0 roadmap]: Start with --skip-plantnet=true for first missions; enable after baseline established
- [v2.0 roadmap]: Phase 10 (Health) can build in parallel with Phase 9 (Species) if timeline is aggressive — both read from E1 rows
- [07-02]: drone_jobs is the actual missions table — "missions" is a conceptual alias only; all FKs reference public.drone_jobs(id)
- [07-02]: processing_steps.step_name is free TEXT (no ENUM, no CHECK) — confirmed in 20260211120000 migration; new veg step names valid without DDL
- [07-02]: processing_templates uses path_code routing (not package_type) — Path E seeded with path_code='E'
- [07-02]: RLS uses TO service_role role targeting for Python E scripts using service key (not has_role() admin check)
- [08-01]: DeepForest v2 import path is `from deepforest import main as deepforest_main` — top-level module does not auto-expose submodules
- [08-01]: predict_image() used per tile (not predict_tile()) — we pre-tile for overlap control; predict_tile() would re-tile internally
- [08-01]: NMS operates in geographic space (CRS units) not pixel space — avoids coordinate errors from CRS skew in UTM projections
- [Phase 08-canopy-detection]: detect_canopies() returns (detections, had_partial_failure, dataset_crs) tuple — main() owns all I/O so core function stays testable
- [Phase 08-canopy-detection]: CUDA failure exit code is 1 (fatal), not 2 (partial) — CUDA unavailable = zero tiles, zero output, unrecoverable
- [Phase 08-canopy-detection]: Supabase upsert on_conflict='mission_id,detection_index' — idempotent re-runs; partial write failures safe to retry
- [10-01]: Vision sample selects bottom vision_sample_pct by index_score ascending — worst-looking trees get Vision API confirmation
- [10-01]: update_health_batch uses individual UPDATE per row (not upsert) since E1 rows already exist in vegetation_detections
- [10-01]: Checkpoint key format canopy_{detection_index} — per-canopy granularity prevents re-billing on vision API calls after partial run
- [10-01]: Cost threshold guard runs before vision loop — aborts if estimated_cost > cost_threshold ($2.00 default)

### Pending Todos

None.

### Blockers/Concerns

- ~~ENV: PyTorch CPU silent fallback on RTX 5070~~ **RESOLVED** (07-01) — torch.cuda.get_device_capability()[0] = 12, sm_120 verified; gate in test_environment.py
- ~~ENV: PROJ_LIB/PROJ_DATA conflict from QGIS~~ **RESOLVED** (07-01) — clear pattern established and tested in test_environment.py; apply to all E scripts
- SPE: Species accuracy is 30-55% top-1 — methodology disclaimer in PDF is non-negotiable; do not label as authoritative
- SPE: OpenAI Vision cost overrun risk — enforce max_canopies cap and pre-run cost estimate before first API loop

## Session Continuity

Last session: 2026-02-25
Stopped at: Completed 10-01-PLAN.md — health_assessment.py: VARI/ExG vegetation indices, health scoring (40/60 index/vision), OpenAI Vision sampling for bottom 30%, checkpoint resume, Supabase batch update, JSON stdout. Phase 10 COMPLETE.
Resume file: None
