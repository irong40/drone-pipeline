# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-24)

**Core value:** Every script runs reliably, recovers from failures, and has tests proving it works
**Current focus:** v2.0 Vegetation Analysis Pipeline — Phase 7 (Environment and Foundation)

## Current Position

Phase: 7 of 13 (Environment and Foundation)
Plan: 2 of TBD in current phase
Status: In progress (07-01 and 07-02 complete)
Last activity: 2026-02-25 — 07-02 complete: Supabase vegetation schema migrations created

Progress: [███████░░░░░░░░░░░░░] 35% (6/13 phases complete — v1.0 shipped; Phase 7 in progress)

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
| 7. Environment and Foundation | 07-02 (schema) | 2 min | 2 | 2026-02-25 |

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table for full history.
Recent decisions affecting v2.0 work:

- [v2.0 roadmap]: Python 3.12 venv (.venv-path-e) separate from system Python 3.14 — DeepForest requires <3.13
- [v2.0 roadmap]: Install PyTorch 2.9.1+cu128 FIRST via --index-url before DeepForest to avoid CPU-only build
- [v2.0 roadmap]: Use predict_tile() for cross-tile NMS rather than manual tile stitching
- [v2.0 roadmap]: Start with --skip-plantnet=true for first missions; enable after baseline established
- [v2.0 roadmap]: Phase 10 (Health) can build in parallel with Phase 9 (Species) if timeline is aggressive — both read from E1 rows
- [07-02]: drone_jobs is the actual missions table — "missions" is a conceptual alias only; all FKs reference public.drone_jobs(id)
- [07-02]: processing_steps.step_name is free TEXT (no ENUM, no CHECK) — confirmed in 20260211120000 migration; new veg step names valid without DDL
- [07-02]: processing_templates uses path_code routing (not package_type) — Path E seeded with path_code='E'
- [07-02]: RLS uses TO service_role role targeting for Python E scripts using service key (not has_role() admin check)

### Pending Todos

None.

### Blockers/Concerns

- ENV: PyTorch CPU silent fallback on RTX 5070 — must assert torch.cuda.get_device_capability()[0] >= 12 in Phase 7
- ENV: PROJ_LIB/PROJ_DATA conflict from QGIS on this machine — clear env vars before rasterio import in all E scripts
- SPE: Species accuracy is 30-55% top-1 — methodology disclaimer in PDF is non-negotiable; do not label as authoritative
- SPE: OpenAI Vision cost overrun risk — enforce max_canopies cap and pre-run cost estimate before first API loop

## Session Continuity

Last session: 2026-02-25
Stopped at: Completed 07-02-PLAN.md — Supabase vegetation schema migrations created and committed
Resume file: None
