---
phase: 18-path-v-video-pipeline
plan: 02
subsystem: n8n-workflows
tags: [n8n, sub-workflow, video-pipeline, wait-node, webhook, package-router]

requires:
  - phase: 18-path-v-video-pipeline
    plan: 01
    provides: PipelineStatusReporter integrated into all 6 V-path scripts
provides:
  - Path V sub-workflow (sentinel-path-v) with V1-V4 auto chain, V5 Wait gate, V6 + delivery
  - Package Router dispatches video missions to Path V sub-workflow (stub removed)
affects: [17-path-c-e-connections]

tech-stack:
  added: []
  patterns: [Execute Command -> Parse Result -> IF Failed -> Stop on Failure chain, Wait node with webhook resume for manual gate]

key-files:
  created:
    - n8n/path_v_workflow.json
  modified:
    - n8n/package_router.json

key-decisions:
  - "30-node workflow structure: 7 Execute Command, 7 Parse, 6 IF, 6 Stop, 3 V5 gate nodes, 1 trigger"
  - "V5 Gate Setup code node provides operator instructions before Wait pause"
  - "V5 Resume Check is informational only (does not block) -- V6 will error if masters missing"
  - "Package Router uses workflowId string reference matching Path A/C pattern"

patterns-established:
  - "Multi-step Execute Command chain with per-step exit code guards and Stop on Failure branches"
  - "Wait node manual gate pattern: Gate Setup -> Wait (webhook) -> Resume Check -> continue"

requirements-completed: [PHV-01, PHV-02, PHV-03, PHV-05]

duration: 2min
completed: 2026-03-05
---

# Phase 18 Plan 02: Path V n8n Sub-Workflow and Package Router Dispatch Summary

**30-node Path V sub-workflow with V1-V4 auto chain, V5 DaVinci Resolve wait gate (webhook resume), V6 export + delivery packaging**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T16:19:22Z
- **Completed:** 2026-03-05T16:21:47Z
- **Tasks:** 2
- **Files created:** 1
- **Files modified:** 1

## Accomplishments
- Built path_v_workflow.json with 30 nodes covering the complete video pipeline
- V1 color grade, V1.5 metadata, V2 SRT telemetry, V3 QA, V4 proxy gen run sequentially with exit code guards
- V5 Wait node pauses for DaVinci Resolve manual editing with webhook suffix v5-resolve-complete
- V6 format export and delivery packaging run after operator resumes
- Replaced NoOp stub in Package Router with Execute Sub Workflow node referencing sentinel-path-v

## Task Commits

Each task was committed atomically:

1. **Task 1: Build Path V sub-workflow JSON** - `bbc2cc5` (feat)
2. **Task 2: Patch Package Router to dispatch video to Path V** - `705caa9` (feat)

## Files Created/Modified
- `n8n/path_v_workflow.json` - New 30-node sub-workflow (596 lines): trigger, V1-V4 chains, V5 gate + Wait + resume, V6 chain, delivery chain
- `n8n/package_router.json` - Replaced NoOp stub with Execute Sub Workflow node for Path V

## Decisions Made
- 30-node structure with consistent Execute -> Parse -> IF -> Stop pattern for all 6 automated steps plus delivery
- V5 Gate Setup provides operator instructions (proxy location, DaVinci Resolve workflow, master output path, resume URL)
- V5 Resume Check is informational -- does not block execution (V6 will error naturally if masters are missing)
- Package Router workflowId uses string reference "sentinel-path-v" matching existing Path A/C pattern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - workflow JSON files are ready for n8n import.

## Next Phase Readiness
- Path V video pipeline is fully wired: Package Router -> Path V sub-workflow -> V1-V4 -> Wait -> V6 -> Delivery
- All scripts self-report via PipelineStatusReporter (from 18-01)
- Operator resumes V5 gate by POSTing to {N8N_BASE_URL}/webhook-waiting/{executionId}/v5-resolve-complete

---
*Phase: 18-path-v-video-pipeline*
*Completed: 2026-03-05*

## Self-Check: PASSED
