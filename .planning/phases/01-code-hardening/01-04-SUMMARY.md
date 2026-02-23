---
phase: 01-code-hardening
plan: "04"
subsystem: pipeline-scripts
tags: [supabase, video-grading, graded-path, upsert, gap-10]
dependency_graph:
  requires: [01-03]
  provides: [GAP-10-graded-path-update]
  affects: [video_color_grade.py, video_proxy_gen.py, video_qa.py, delivery_packaging.py]
tech_stack:
  added: []
  patterns: [opt-in-supabase-update, non-fatal-db-write, upsert-on-conflict]
key_files:
  created: []
  modified:
    - video_color_grade.py
key-decisions:
  - "Upsert (on_conflict=mission_id,filename) used — safe even if video_metadata.py has not run yet"
  - "--upload is opt-in; grading without --upload is completely unchanged"
  - "Supabase failures are non-fatal warnings — grade result is never affected by DB errors"
  - "update_graded_path() returns bool so callers can observe success without handling exceptions"
  - "Unique constraint on video_assets(mission_id,filename): NOT VERIFIED in CI (no env vars) — Phase 4 tests should verify or mock the constraint"
patterns-established:
  - "Opt-in Supabase update: --upload + --mission-id flags guard all DB writes"
  - "Non-fatal DB pattern: try/except in isolated function, warning log, bool return"
requirements-completed: [GAP-10]
duration: 1min
completed: 2026-02-23
---

# Phase 01 Plan 04: Supabase graded_path Update Summary

**Opt-in Supabase upsert writes video_assets.graded_path atomically with color grading via --upload/--mission-id flags, closing GAP-10**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-23T18:40:11Z
- **Completed:** 2026-02-23T18:41:05Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Added `update_graded_path(mission_id, filename, graded_path)` function to video_color_grade.py
- Added `--upload` and `--mission-id` CLI arguments — graded_path update is strictly opt-in
- Grading without `--upload` is 100% unchanged from pre-plan behavior
- Supabase failures (network errors, constraint issues) are non-fatal warnings; grade result is unaffected
- `update_graded_path()` is importable for Phase 4 unit tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Supabase graded_path update (GAP-10)** - `124417a` (feat)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `video_color_grade.py` - Added SUPABASE_URL/KEY config constants, update_graded_path() function, --upload/--mission-id argparse args, and call site in grade loop

## Decisions Made

1. **Upsert approach** — `client.table("video_assets").upsert(..., on_conflict="mission_id,filename")` is used. This is safe even when video_metadata.py has not yet run, because upsert will insert the row if it does not exist. The unique constraint check (Step 1 of the plan) returned `SKIP: no env vars` in the execution environment, so the constraint could not be verified at runtime. Phase 4 unit tests should mock or verify the constraint exists in the real DB.

2. **Two-step fallback NOT used** — The constraint check was skipped (no env vars), not failed. The upsert path is the correct primary approach per the plan. If the constraint turns out to be missing in production, the DB migration to add it is the right fix (not switching to two-step SELECT+UPDATE).

3. **`--upload` is opt-in** — Operators who run grading without Supabase credentials or outside a mission context are unaffected.

## Unique Constraint Status

**Constraint check result:** `SKIP: SUPABASE_URL or SUPABASE_SERVICE_KEY not set`

The constraint on `video_assets(mission_id, filename)` could not be verified in the execution environment. Implications for Phase 4:
- If the constraint EXISTS: upsert works as implemented — no changes needed
- If the constraint MISSING: Phase 4 migration should add `UNIQUE(mission_id, filename)` before tests run

Phase 4 unit tests should either mock the Supabase client entirely (bypassing the constraint) or run against a test DB with the constraint applied.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

To use `--upload`, set environment variables before running:

```bash
export SUPABASE_URL=https://<project-ref>.supabase.co
export SUPABASE_SERVICE_KEY=<service-role-key>
python video_color_grade.py path/to/mission --upload --mission-id <uuid>
```

Without these env vars, grading works normally and Supabase update is silently skipped.

## Next Phase Readiness

- GAP-10 closed — `graded_path` is now written atomically with the grade operation
- `update_graded_path()` is exported and importable for Phase 4 unit tests
- Phase 1 complete: all 4 plans done (logging, exit codes, checkpoint/resume, graded_path update)
- Phase 2 can begin: error recovery / retry logic across scripts

---
*Phase: 01-code-hardening*
*Completed: 2026-02-23*

## Self-Check: PASSED

- video_color_grade.py: FOUND
- 01-04-SUMMARY.md: FOUND
- Commit 124417a: FOUND
