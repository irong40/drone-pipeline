---
phase: 04-video-pipeline-tests
plan: 1
subsystem: testing
tags: [pytest, pytest-mock, ffmpeg, ffprobe, supabase, video-processing, unit-tests]

requires:
  - phase: 02-test-infrastructure
    provides: pytest infrastructure (conftest.py, mock_supabase_client, mock_ffmpeg fixtures)
  - phase: 01-code-hardening
    provides: video_color_grade.py and video_metadata.py production implementations
provides:
  - UNIT-04 test suite for video_color_grade.py (15 tests)
  - UNIT-05 test suite for video_metadata.py (24 tests)
  - conftest.py extended with .single() chain stub for video_qa plan
affects:
  - 04-02-video-qa-srt-tests (uses conftest .single() stub added here)

tech-stack:
  added: []
  patterns:
    - "sys.modules injection for unavailable third-party packages (supabase)"
    - "autouse fixture stub per test file to avoid module-level import errors"
    - "module-level constant patching: mocker.patch('module.CONSTANT', value) not os.environ"

key-files:
  created:
    - tests/test_video_color_grade.py
    - tests/test_video_metadata.py
  modified:
    - tests/conftest.py

key-decisions:
  - "sys.modules injection for supabase: mocker.patch('supabase.create_client') requires the module to be importable; since supabase is not installed in CI, inject a fake types.ModuleType stub via mocker.patch.dict(sys.modules) in an autouse fixture"
  - "autouse=True on stub_supabase_module fixture: applies to every test in the file without requiring explicit fixture request, consistent with Phase 2 decision to NOT use autouse on mock_ffmpeg (subprocess risk) but safe here since supabase stub has no side effects"
  - "Module-level constant patching confirmed: mocker.patch('video_color_grade.SUPABASE_URL', value) patches the already-evaluated module constant, not the os.environ source"

patterns-established:
  - "Pattern: sys.modules stub fixture (autouse) per file for packages not installed in CI"
  - "Pattern: conftest extension for new mock chains (.single()) done non-breakingly by appending to existing fixture"

requirements-completed: [UNIT-04, UNIT-05]

duration: 2min
completed: 2026-02-23
---

# Phase 4 Plan 1: Video Color Grade + Metadata Tests Summary

**39 unit tests for video_color_grade.py and video_metadata.py using sys.modules supabase stub, verifying LUT selection, FFmpeg command structure, ffprobe JSON parsing, and Supabase upsert/update/insert branches**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T19:54:24Z
- **Completed:** 2026-02-23T19:57:01Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Replaced placeholder stubs in both test files with real unit tests (39 total, 0 placeholder)
- UNIT-04: 15 tests covering get_lut_path (8 platforms/overrides), grade_video (4 command structure), update_graded_path (3 upsert payload)
- UNIT-05: 24 tests covering normalize_codec (7), extract_sequence_number (4), probe_video (5 ffprobe parsing), find_graded_file (2), check_lrf_proxy (2), upload_metadata (4 update/insert branches)
- Extended conftest.py with `.single()` chain stub (non-breaking, required by plan 04-02 for video_qa tests)
- All 39 new tests pass; 72 existing ingest-layer tests unaffected

## Task Commits

Each task was committed atomically:

1. **Task 1: Unit tests for video_color_grade.py (UNIT-04) + conftest .single() extension** - `aaad0d4` (test)
2. **Task 2: Unit tests for video_metadata.py (UNIT-05)** - `e41c801` (test)
3. **Task 3: Full suite verification** - (no files changed — verification only)

## Files Created/Modified

- `tests/test_video_color_grade.py` - 15 tests: LUT selection per platform (m4e/m3e/mini4pro/unknown/missing/override), grade_video FFmpeg command, update_graded_path upsert payload
- `tests/test_video_metadata.py` - 24 tests: codec normalization, sequence extraction, ffprobe JSON parsing (4K H.264, fractional fps, failure cases), filesystem helpers, upload_metadata update/insert/skip/raise branches
- `tests/conftest.py` - Added `.single().execute().data = None` chain stub to mock_supabase_client

## Decisions Made

- **sys.modules injection for supabase**: `supabase` is not installed in CI (not in requirements.txt, just lazy-imported by scripts). `mocker.patch("supabase.create_client")` fails with `ModuleNotFoundError`. Fix: inject a `types.ModuleType("supabase")` stub via `mocker.patch.dict(sys.modules)` in an `autouse=True` fixture per test file. Same approach used in Phase 03 for `exiftool`.
- **Module-level constant patching confirmed**: `SUPABASE_URL = os.environ.get(...)` runs at import time; patching `os.environ` afterward has no effect. Must use `mocker.patch("video_color_grade.SUPABASE_URL", "value")` to patch the already-evaluated module constant. Confirmed working for both `video_color_grade` and `video_metadata`.
- **conftest .single() stub**: Added as a single non-breaking line rather than inline per test to keep test files cleaner and match the conftest's existing pattern for pre-configuring all common chain variants.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] sys.modules injection for uninstalled supabase package**
- **Found during:** Task 1 (test_update_graded_path_calls_upsert_with_correct_payload)
- **Issue:** `mocker.patch("supabase.create_client")` raised `ModuleNotFoundError: No module named 'supabase'` — supabase is not installed in the test environment (it is lazy-imported by production scripts only)
- **Fix:** Added `stub_supabase_module` autouse fixture in both test files that injects a `types.ModuleType("supabase")` stub into `sys.modules` when supabase is absent. Consistent with Phase 03 pattern for `exiftool`.
- **Files modified:** tests/test_video_color_grade.py, tests/test_video_metadata.py
- **Verification:** All 15 + 24 tests pass with supabase uninstalled
- **Committed in:** aaad0d4 (Task 1 commit), e41c801 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (blocking — missing module)
**Impact on plan:** Required for test execution in CI without installing supabase. No scope creep.

## Issues Encountered

None beyond the supabase module blocker documented above.

## Next Phase Readiness

- Plan 04-02 (SRT parser + QA tests) can proceed — conftest .single() stub is in place
- Both UNIT-04 and UNIT-05 requirements satisfied
- sys.modules injection pattern is now established for video pipeline tests — apply same approach in 04-02 and 04-03 if supabase mock tests are needed

## Self-Check: PASSED

- FOUND: tests/test_video_color_grade.py
- FOUND: tests/test_video_metadata.py
- FOUND: tests/conftest.py
- FOUND: .planning/phases/04-video-pipeline-tests/04-01-SUMMARY.md
- FOUND commit: aaad0d4 (Task 1)
- FOUND commit: e41c801 (Task 2)

---
*Phase: 04-video-pipeline-tests*
*Completed: 2026-02-23*
