---
phase: 12-integration-and-delivery
plan: 01
subsystem: infra
tags: [n8n, workflow, vegetation, path-e, json, package-router]

requires:
  - phase: 11-report-generation
    provides: vegetation_report.py (E4) that generates PDF, maps, GeoJSON, and Supabase summary

provides:
  - n8n Path E workflow JSON (35 nodes, E0-E4 sequence + review gate)
  - Package router patch for vegetation_enabled defaults per template type
  - v1 contract smoke test results for all 4 E scripts

affects:
  - 12-02 (next plan in phase)
  - 13-03 (integration tests reference workflow behavior)

tech-stack:
  added: []
  patterns:
    - "n8n Execute Command node calls Python scripts with --mission-id, --ortho-path, --processing-job-id args"
    - "n8n Code node parses JSON stdout from E scripts; throws on invalid JSON or exit code 1"
    - "n8n Webhook Wait pattern for operator review gate (POST /sentinel-vegetation-resume)"
    - "n8n static data for poll attempt counter (E0 ortho polling)"
    - "Zero-canopy bypass: E1 canopy_count=0 skips E2/E3, routes directly to Set Status — Generating Report"

key-files:
  created:
    - n8n/path_e_workflow.json
    - n8n/package_router_patch.json
  modified: []

key-decisions:
  - "n8n Execute Command nodes use .venv-path-e Python (E:\\Sentinel\\.venv-path-e\\Scripts\\python.exe) — not system Python 3.14 which lacks DeepForest dependencies"
  - "Ortho polling in workflow (E0): 60s interval, 30 attempts max = 30-minute timeout; sets vegetation_status=failed on timeout"
  - "Zero-canopy bypass at E1: canopy_count=0 routes directly to report generation with 'no vegetation detected' note, skipping E2/E3 API calls"
  - "Review gate uses n8n Webhook Wait node (not sleep/polling) — workflow thread pauses until POST /sentinel-vegetation-resume received"
  - "vegetation_report.py (E4) intentionally omits checkpoint import — idempotent by design (reads all data fresh from Supabase on each run)"
  - "health_assessment.py sys.exit(2) omitted — intentional: partial results (some canopies failed index calc) still exit 0 with partial flag in JSON stdout"
  - "Package router: vegetation_enabled=true by default for site_survey and environmental_survey; false for construction_hybrid and real_estate"

patterns-established:
  - "n8n workflow error handling: E script exit code 1 routes to Error Handler — Set Failed node (vegetation_status=failed)"
  - "n8n workflow status ladder: detecting → classifying → assessing → generating_report → review → complete"
  - "Review decisions: exclude (DB flag + E4 regeneration) / flag (DB flag only) / approve (no DB change needed)"

requirements-completed: [INT-01, INT-02, INT-07]

duration: 4min
completed: 2026-02-25
---

# Phase 12 Plan 01: n8n Path E Integration Summary

**35-node n8n workflow wiring E0-E4 vegetation scripts with operator review gate, plus package router enabling vegetation by default for site/environmental surveys**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-25T20:22:51Z
- **Completed:** 2026-02-25T20:26:49Z
- **Tasks:** 2
- **Files modified:** 2 created

## Accomplishments

- Created `n8n/path_e_workflow.json` — 35-node n8n workflow covering the full Path E sequence (E0 ortho check, E1 canopy detection, E2 species classification, E3 health assessment, E4 report generation, operator review gate, decision processing, and completion)
- Created `n8n/package_router_patch.json` — template defaults enabling vegetation for site/environmental surveys and routing condition for Path E trigger
- Verified all 4 E scripts pass v1 pipeline contract (argparse, setup_logging, LOG_DIR, pipeline_status, json.dumps stdout, sys.exit 0/1)

## Task Commits

Each task was committed atomically:

1. **Task 1: n8n Path E workflow JSON** - `82d9ab4` (feat)
2. **Task 2: Package router patch + v1 contract smoke test** - `72dfac4` (feat)

## v1 Contract Smoke Test Results

| Check | canopy_detection.py | species_classification.py | health_assessment.py | vegetation_report.py |
|-------|--------------------|--------------------------|--------------------|---------------------|
| argparse configured | PASS | PASS | PASS | PASS |
| setup_logging / LOG_DIR | PASS | PASS | PASS | PASS |
| pipeline_status import | PASS | PASS | PASS | PASS |
| json.dumps stdout | PASS | PASS | PASS | PASS |
| sys.exit(0) | PASS | PASS | PASS | PASS |
| sys.exit(1) | PASS | PASS | PASS | PASS |
| sys.exit(2) | PASS | PASS | N/A (intentional) | PASS |
| checkpoint import | PASS | PASS | PASS | N/A (idempotent) |
| **Verdict** | **PASS** | **PASS** | **PASS** | **PASS** |

## Files Created/Modified

- `n8n/path_e_workflow.json` — n8n Path E workflow with 35 nodes: trigger, E0 ortho poll loop, status updates, E1-E4 Execute Command nodes, Code nodes parsing JSON stdout, review gate Webhook Wait, decision processing, and error handling
- `n8n/package_router_patch.json` — package router defaults (site_survey/environmental_survey vegetation_enabled=true, construction_hybrid/real_estate vegetation_enabled=false), routing condition spec, Supabase query patterns, migration checklist, and embedded v1 contract smoke test results

## Decisions Made

- **E0 ortho polling:** 60s interval, 30 attempts (30-min timeout) rather than a separate n8n Cron trigger — keeps the workflow self-contained and avoids race conditions
- **Zero-canopy bypass:** E1 canopy_count=0 branches directly to Set Status — Generating Report, skipping E2/E3 entirely to avoid unnecessary API calls ($0 cost for empty sites)
- **Review gate:** n8n Webhook Wait node (not polling) — workflow thread sleeps until operator posts; 7-day timeout before auto-approve
- **E4 checkpoint omission documented:** vegetation_report.py does not import checkpoint because it re-reads all data fresh from Supabase on each run (idempotent), matching the delivery_packaging pattern
- **health_assessment.py sys.exit(2) omission documented:** Health assessment exits 0 even with partial failures (some canopies without index data), flagging partial in JSON stdout rather than exit code

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All 4 E scripts passed v1 contract verification on first check.

## User Setup Required

The n8n workflow requires environment variables in n8n:

| Variable | Value |
|----------|-------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |
| `N8N_BASE_URL` | n8n instance URL (e.g. http://localhost:5678) |

See `n8n/package_router_patch.json` migration_checklist for full setup steps (DB columns, template defaults, workflow activation).

## Next Phase Readiness

- Path E workflow JSON ready for n8n import and activation
- Package router routing condition spec ready for integration into existing n8n Package Router workflow
- v1 contract verified — all 4 E scripts integrate cleanly with n8n Execute Command nodes
- Phase 12-02 (next plan) can build on this foundation

## Self-Check: PASSED

- n8n/path_e_workflow.json: FOUND
- n8n/package_router_patch.json: FOUND
- .planning/phases/12-integration-and-delivery/12-01-SUMMARY.md: FOUND
- Commit 82d9ab4 (Task 1): FOUND
- Commit 72dfac4 (Task 2): FOUND

---
*Phase: 12-integration-and-delivery*
*Completed: 2026-02-25*
