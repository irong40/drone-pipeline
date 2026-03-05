---
phase: 16-package-router-core-path-a
plan: 02
subsystem: automation
tags: [n8n, workflow, delivery-packaging, pipeline-status, real-estate]

requires:
  - phase: 15-foundation-scripts-schema
    provides: "pipeline_status.py PipelineStatusReporter + add_pipeline_args"
  - phase: 16-package-router-core-path-a
    provides: "16-01 Package Router normalizer and workflow scaffold"
provides:
  - "Path A n8n sub-workflow (n8n/path_a_workflow.json) for real estate photo processing"
  - "delivery_packaging.py with PipelineStatusReporter integration"
affects: [17-path-cv-gpu-pipeline, 18-error-recovery-notifications]

tech-stack:
  added: []
  patterns:
    - "Sub-workflow per path type with executeWorkflowTrigger entry"
    - "Script self-reporting via PipelineStatusReporter (n8n only checks exit codes)"
    - "Extracted _run_packaging() for clean try/except/reporter pattern"

key-files:
  created:
    - n8n/path_a_workflow.json
  modified:
    - delivery_packaging.py

key-decisions:
  - "Extracted core logic into _run_packaging() for clean reporter try/except wrapping"
  - "Dry-run mode skips reporter.start() entirely — no Supabase side effects"
  - "sys.exit errors in _run_packaging() converted to RuntimeError for reporter.fail() to catch"

patterns-established:
  - "Script status integration pattern: create reporter early, start() after dry-run guard, complete()/fail() via try/except"
  - "Path A sub-workflow: trigger -> color grade -> parse -> IF failed -> delivery -> parse result"

requirements-completed: [PHA-01, PHA-02, PHA-03]

duration: 3min
completed: 2026-03-05
---

# Phase 16 Plan 02: Path A Sub-Workflow + Delivery Packaging Status Summary

**Path A n8n sub-workflow with color grade and delivery packaging steps, plus PipelineStatusReporter integration in delivery_packaging.py**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-05T15:55:07Z
- **Completed:** 2026-03-05T15:58:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- delivery_packaging.py now accepts --processing-job-id and reports start/complete/fail to Supabase via PipelineStatusReporter
- Path A sub-workflow chains color grading then delivery packaging with IF-node failure gate
- Both scripts self-report status; n8n only checks exit codes (no double-updating)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add PipelineStatusReporter to delivery_packaging.py** - `367051d` (feat)
2. **Task 2: Build Path A sub-workflow JSON** - `f747684` (feat)

## Files Created/Modified
- `delivery_packaging.py` - Added PipelineStatusReporter import, --processing-job-id arg, reporter start/complete/fail, extracted _run_packaging()
- `n8n/path_a_workflow.json` - 7-node Path A sub-workflow: trigger, color grade, parse, IF failed, delivery packaging, parse result, stop on failure

## Decisions Made
- Extracted core packaging logic into `_run_packaging()` helper to enable clean try/except wrapping with reporter.complete()/fail() — avoids cluttering main() with nested try blocks
- Converted sys.exit() calls inside packaging logic to RuntimeError raises so the reporter.fail() handler in main() can catch them before exit
- Dry-run mode returns before reporter.start() is called, ensuring no Supabase status updates on dry runs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Converted sys.exit to RuntimeError in _run_packaging**
- **Found during:** Task 1 (PipelineStatusReporter integration)
- **Issue:** Original code used sys.exit() for error conditions (no photos, no videos, no files). SystemExit bypasses except Exception handlers, so reporter.fail() would never fire
- **Fix:** Converted sys.exit() calls to raise RuntimeError() in _run_packaging(). main() re-raises SystemExit separately and catches Exception for reporter.fail()
- **Files modified:** delivery_packaging.py
- **Verification:** import OK, --help shows --processing-job-id
- **Committed in:** 367051d (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential for reporter.fail() to work correctly on error paths. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Path A sub-workflow ready for import into n8n
- Package Router (16-01) can now call Path A via Execute Sub Workflow node
- delivery_packaging.py backward compatible (works without --processing-job-id)
- Ready for Phase 17 (Path C/V GPU pipeline) and Phase 18 (error recovery)

---
*Phase: 16-package-router-core-path-a*
*Completed: 2026-03-05*
