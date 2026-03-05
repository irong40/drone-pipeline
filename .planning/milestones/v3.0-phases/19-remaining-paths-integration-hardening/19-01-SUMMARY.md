---
phase: 19-remaining-paths-integration-hardening
plan: 01
subsystem: n8n-workflows
tags: [n8n, payload-normalization, email-notification, sub-workflow, package-router]

# Dependency graph
requires:
  - phase: 14-environment-setup
    provides: "n8n environment with SUPABASE_URL, SUPABASE_SERVICE_KEY env vars"
provides:
  - "Shared manual-path sub-workflow for Path B/D (manual_path_workflow.json)"
  - "Payload normalizer Code node for Package Router (package_router_normalizer.js)"
  - "Python reference implementation of normalizer (scripts/payload_normalizer.py)"
  - "Package Router patch with folder watcher normalization config"
affects: [19-02-integration-testing, package-router-workflow]

# Tech tracking
tech-stack:
  added: []
  patterns: [execute-sub-workflow-trigger, payload-normalization-code-node, shared-manual-path-pattern]

key-files:
  created:
    - n8n/manual_path_workflow.json
    - n8n/package_router_normalizer.js
    - scripts/payload_normalizer.py
    - tests/test_payload_normalization.py
  modified:
    - n8n/package_router_patch.json

key-decisions:
  - "Single shared sub-workflow for Path B and D with package_type as parameter"
  - "Folder name regex uses non-greedy match for package_type to handle underscores (e.g., construction_hybrid)"
  - "is_fallback flag on folder_watcher payloads enables deduplication check downstream"

patterns-established:
  - "Execute Sub Workflow trigger pattern: sub-workflows receive parameters from Package Router, not webhook"
  - "Dual-source normalization: Code node detects payload source and normalizes before Switch routing"
  - "Python reference implementation mirrors JS Code node logic for testability"

requirements-completed: [PBD-01, PBD-02, FWI-01, FWI-02]

# Metrics
duration: 3min
completed: 2026-03-05
---

# Phase 19 Plan 01: Remaining Paths Integration Hardening Summary

**Shared n8n sub-workflow for Path B/D manual handling with SMTP notification, plus dual-source payload normalizer for folder_watcher/ingest_sorter unification**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-05T15:12:10Z
- **Completed:** 2026-03-05T15:15:23Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Created manual_path_workflow.json sub-workflow that sets processing_jobs status=manual and sends operator email via SMTP
- Built JavaScript Code node normalizer that detects folder_watcher vs ingest_sorter payloads and outputs common format
- Implemented Python reference normalizer with 23 passing tests covering all known package types
- Updated package_router_patch.json with folder watcher normalization config, mission lookup, deduplication check, and manual path routing

## Task Commits

Each task was committed atomically:

1. **Task 1: Create shared manual-path n8n sub-workflow and payload normalizer Code node** - `8710271` (feat)
2. **Task 2: Create Python payload normalizer with tests (RED)** - `b771df2` (test)
3. **Task 2: Create Python payload normalizer with tests (GREEN)** - `1862fc3` (feat)
4. **Task 3: Update package_router_patch.json with folder watcher normalization config** - `dfd5036` (feat)

## Files Created/Modified
- `n8n/manual_path_workflow.json` - Shared sub-workflow for Path B/D: sets status=manual + sends SMTP email to OPERATOR_EMAIL
- `n8n/package_router_normalizer.js` - Code node logic for normalizing both payload types before Package Router Switch
- `scripts/payload_normalizer.py` - Python reference implementation with parse_folder_name and normalize_payload functions
- `tests/test_payload_normalization.py` - 23 pytest tests covering all package types, edge cases, both payload sources
- `n8n/package_router_patch.json` - Added folder_watcher_normalization section and OPERATOR_EMAIL env var

## Decisions Made
- Single shared sub-workflow for Path B and D with package_type passed as parameter (avoids workflow duplication)
- Folder name regex `^SAI_M(\d{4})_(.+?)_(\d{8})$` uses non-greedy match to handle underscored package types like construction_hybrid
- is_fallback flag on folder_watcher payloads enables downstream deduplication (check if processing_jobs row already exists)
- Python implementation placed in scripts/ subdirectory to separate reference code from production pipeline scripts in project root

## Deviations from Plan

None - plan executed exactly as written.

## User Setup Required

External services require manual configuration:
- **SMTP Credential**: Create "SMTP - Operator Notifications" credential in n8n UI > Settings > Credentials > Add Credential > SMTP
- **OPERATOR_EMAIL**: Set in n8n Settings > Variables -- the email address that receives manual-path notifications

## Next Phase Readiness
- All n8n workflow artifacts ready for Plan 02 integration testing
- manual_path_workflow.json can be imported into n8n and linked to Package Router
- package_router_normalizer.js ready to paste into Code node
- 23 passing Python tests validate normalization logic correctness

---
*Phase: 19-remaining-paths-integration-hardening*
*Completed: 2026-03-05*
