---
phase: 17-path-c-mipmap-path-e
plan: 01
subsystem: n8n-workflows
tags: [n8n, mipmap, polling-loop, ortho-harvest, vegetation-trigger, sub-workflow]

requires:
  - phase: 16-package-router-path-a
    provides: Package Router with Path C noOp stub and routing logic
  - phase: 15-ortho-harvester-mipmap
    provides: mipmap_launcher.py and ortho_harvester.py scripts

provides:
  - Path C n8n sub-workflow (sentinel-path-c) for mapping mission automation
  - Live Package Router dispatch to Path C for mapping/site_survey/environmental_survey
  - Conditional Path E vegetation analysis trigger from Path C

affects: [18-path-v-video, path-e-vegetation, package-router]

tech-stack:
  added: []
  patterns: [fire-and-forget-launch-with-polling, wildcard-tif-detection, conditional-webhook-trigger]

key-files:
  created: [n8n/path_c_workflow.json]
  modified: [n8n/package_router.json]

key-decisions:
  - "Wildcard *.tif check in polling loop handles unknown MipMap output filenames"
  - "dir /b used to discover actual GeoTIFF filename before harvest"
  - "Vegetation flag checked via direct Supabase GET (same pattern as Path E)"

patterns-established:
  - "Fire-and-forget + polling: Launch external process, poll output dir with configurable interval/timeout"
  - "Conditional downstream trigger: Check DB flag before firing webhook to next pipeline stage"

requirements-completed: [MPC-03, MPC-06]

duration: 3min
completed: 2026-03-05
---

# Phase 17 Plan 01: Path C MipMap Sub-Workflow Summary

**20-node n8n sub-workflow automating MipMap launch, GeoTIFF polling (120x60s), ortho harvest, and conditional Path E vegetation trigger -- replaces Package Router stub with live dispatch**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-05T16:17:15Z
- **Completed:** 2026-03-05T16:20:15Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created path_c_workflow.json with full node graph: trigger, MipMap launch, parse, failure gate, polling loop (120 attempts x 60s = 2hr timeout), ortho file discovery, harvest, harvest failure gate, vegetation flag check, conditional Path E trigger
- Replaced Package Router noOp stub (node-stub-path-c) with live executeWorkflow node (node-exec-path-c) pointing to sentinel-path-c
- All 397 tests pass, all 21 workflow validation tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Path C sub-workflow JSON** - `bec03f4` (feat)
2. **Task 2: Patch Package Router to replace Path C stub** - `04bee74` (feat)

## Files Created/Modified
- `n8n/path_c_workflow.json` - Path C MipMap automation sub-workflow (20 nodes, polling loop, conditional Path E trigger)
- `n8n/package_router.json` - Updated router: noOp stub replaced with executeWorkflow to sentinel-path-c

## Decisions Made
- Used wildcard `*.tif` check in polling loop since MipMap output filename is not guaranteed (could be orthomosaic.tif, dom.tif, etc.)
- Used `dir /b` command to discover actual GeoTIFF filename before constructing harvest source path
- Vegetation flag check uses direct Supabase HTTP GET (same proven pattern as Path E workflow)
- HTTP POST to Path E uses N8N_BASE_URL env var for webhook URL construction

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Path C is ready for end-to-end testing with MipMap when installed
- Package Router now routes mapping/site_survey/environmental_survey to live Path C
- Path V stub remains for Phase 18

---
*Phase: 17-path-c-mipmap-path-e*
*Completed: 2026-03-05*
