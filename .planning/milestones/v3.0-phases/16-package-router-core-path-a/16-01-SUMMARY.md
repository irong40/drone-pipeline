---
phase: 16-package-router-core-path-a
plan: 01
subsystem: workflow
tags: [n8n, webhook, routing, supabase, processing-jobs]

requires:
  - phase: 19-testing-validation
    provides: "n8n workflow validation tests and integration test step mapping"
  - phase: 14-n8n-env-verification
    provides: "n8n environment verification workflow pattern"
provides:
  - "Central Package Router n8n workflow (sentinel-package-router)"
  - "Webhook endpoint at /package-router for ingest_sorter and folder_watcher"
  - "Processing job creation with step mapping for all 8 package types"
  - "Switch-based routing to Path A, Path C (stub), Path V (stub), Manual Path"
affects: [16-02, 17-path-c, 18-path-v]

tech-stack:
  added: []
  patterns: ["n8n webhook -> normalize -> lookup -> dedup -> template -> steps -> create -> route"]

key-files:
  created: ["n8n/package_router.json"]
  modified: []

key-decisions:
  - "Switch node v3 with fallback output for unknown types routes to Manual Path"
  - "Dual lookup branches: folder_watcher gets mission_id lookup, ingest_sorter gets address/city lookup"
  - "Both branches merge into single Check Duplicate Job node"
  - "Template config fetched from processing_templates but used as metadata pass-through (scripts own their own behavior)"

patterns-established:
  - "Package Router pattern: webhook -> normalize -> branch lookup -> dedup -> template -> build steps -> create job -> dispatch"
  - "Switch node routing: output index maps to path type (0=A, 1=C, 2=V, fallback=Manual)"

requirements-completed: [RTR-01, RTR-02, RTR-03, RTR-04, RTR-05]

duration: 3min
completed: 2026-03-05
---

# Phase 16 Plan 01: Package Router Workflow Summary

**16-node n8n workflow routing all 8 package types through webhook normalization, deduplication, step generation, and sub-workflow dispatch**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-05T15:55:35Z
- **Completed:** 2026-03-05T15:58:35Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Built complete Package Router workflow with 16 n8n nodes covering the full ingest-to-dispatch pipeline
- Webhook entry point at /package-router accepts both ingest_sorter and folder_watcher payloads
- Normalizer Code node embeds full package_router_normalizer.js for payload normalization
- Switch node routes re_standard/real_estate to Path A, mapping types to Path C stub, video to Path V stub, and construction_hybrid/adiat/unknown to Manual Path
- Step mapping in Build Steps Code node replicates exact STEP_MAP from test_package_router_integration.py
- Deduplication check prevents re-processing missions that already have processing_jobs rows

## Task Commits

Each task was committed atomically:

1. **Task 1: Build Package Router main workflow JSON** - `bb92df1` (feat)

## Files Created/Modified
- `n8n/package_router.json` - Central Package Router n8n workflow (16 nodes, 428 lines)

## Decisions Made
- Used Switch node v3 with fallback output instead of explicit construction_hybrid/adiat matching (cleaner, catches unknown types automatically)
- Dual lookup branches: IF Needs Mission Lookup true -> Lookup Mission ID + Merge Mission ID; false -> Lookup Address + Merge Address. Both converge at Check Duplicate Job
- Template config from processing_templates fetched but passed as metadata; scripts use their own step logic
- Path C and Path V use noOp stub nodes with notes for Phase 17/18 replacement

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required. Workflow imports directly into n8n.

## Next Phase Readiness
- Package Router ready for import into n8n at http://localhost:5678
- Plan 16-02 (Path A sub-workflow) can proceed -- Execute Path A node references sentinel-path-a workflow ID
- Path C stub (Phase 17) and Path V stub (Phase 18) are noOp placeholders ready for replacement
- Manual Path dispatches to existing sentinel-manual-path workflow

---
*Phase: 16-package-router-core-path-a*
*Completed: 2026-03-05*
