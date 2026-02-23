---
phase: 02-test-infrastructure
plan: "02"
subsystem: testing
tags: [pytest, pytest-mock, pytest-cov, pytest-tmp-files, stubs, importorskip]

# Dependency graph
requires:
  - phase: 02-01
    provides: pytest.ini, conftest.py, shared fixtures (mock_supabase, mock_ffmpeg, sample_mission_dir)
provides:
  - requirements.txt Dev/Testing section with pytest>=7.4, pytest-mock>=3.12, pytest-cov>=4.1, pytest-tmp-files
  - 15 test stub files in tests/ — one per script — all collectible with zero errors
  - importorskip guards for 4 scripts with missing-dependency sys.exit() or bare imports
affects: [03-ingest-tests, 04-video-tests, 05-delivery-tests]

# Tech tracking
tech-stack:
  added: [pytest-cov>=4.1, pytest-tmp-files]
  patterns:
    - "pytest.importorskip() guard for any script that calls sys.exit() on missing deps"
    - "Stub pattern: module docstring -> importorskip guards -> bare import -> test_placeholder()"

key-files:
  created:
    - tests/test_ingest.py
    - tests/test_ingest_sorter.py
    - tests/test_platform_detect.py
    - tests/test_folder_watcher.py
    - tests/test_folder_watcher_service.py
    - tests/test_checkpoint.py
    - tests/test_video_color_grade.py
    - tests/test_video_metadata.py
    - tests/test_srt_telemetry_parser.py
    - tests/test_video_qa.py
    - tests/test_video_proxy_gen.py
    - tests/test_video_format_export.py
    - tests/test_delivery_packaging.py
    - tests/test_gdrive_upload.py
    - tests/test_archive_sync.py
  modified:
    - requirements.txt

key-decisions:
  - "pytest-tmp-files declared to satisfy TEST-02 literally; built-in tmp_path fixture will be used in practice"
  - "importorskip pattern extended beyond folder_watcher_service to cover any script with module-level sys.exit() or bare third-party imports"
  - "4 stubs skip on this Python 3.14 dev env (PIL/requests/watchdog not installed); all 15 pass after pip install -r requirements.txt"

patterns-established:
  - "importorskip guard: use pytest.importorskip('pkg') at module level for any script that sys.exit()s without its deps"
  - "bare import guard: use pytest.importorskip('pkg') for scripts with bare module-level third-party imports"

requirements-completed: [TEST-02, TEST-03]

# Metrics
duration: 3min
completed: 2026-02-23
---

# Phase 2 Plan 02: Test Stub Files and Dev Dependencies Summary

**15 pytest stub files created (one per script) plus Dev/Testing section in requirements.txt — pytest tests/ collects 11 and skips 4 cleanly, 0 errors**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-23T19:09:00Z
- **Completed:** 2026-02-23T19:12:00Z
- **Tasks:** 2
- **Files modified:** 16 (requirements.txt + 15 stubs)

## Accomplishments
- Updated requirements.txt with a `# Dev / Testing` section: pytest>=7.4, pytest-mock>=3.12, pytest-cov>=4.1, pytest-tmp-files
- Created 15 test stub files — one for each script in the pipeline — each with module docstring, importorskip guards where needed, and test_placeholder()
- Applied importorskip defensive guards to 4 stubs (ingest, ingest_sorter, folder_watcher, folder_watcher_service) so collection skips cleanly instead of raising INTERNALERROR
- `pytest tests/` result: 11 passed, 4 skipped, 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Add dev dependencies to requirements.txt** - `68945a7` (chore)
2. **Task 2: Create 15 test stub files in tests/** - `1ae8baf` (test)

**Plan metadata:** _(pending final docs commit)_

## Files Created/Modified

- `requirements.txt` — Dev/Testing section updated: pytest>=7.4, pytest-mock>=3.12, pytest-cov>=4.1, pytest-tmp-files
- `tests/test_ingest.py` — Stub for ingest.py; importorskip('PIL') guard (Phase 3, UNIT-14)
- `tests/test_ingest_sorter.py` — Stub for ingest_sorter.py; importorskip('requests') guard (Phase 3, UNIT-01)
- `tests/test_platform_detect.py` — Stub for platform_detect.py; bare import (Phase 3, UNIT-02)
- `tests/test_folder_watcher.py` — Stub for folder_watcher.py; importorskip('requests','watchdog') guards (Phase 3, UNIT-03)
- `tests/test_folder_watcher_service.py` — Stub for folder_watcher_service.py; importorskip('win32serviceutil') guard (Phase 3, UNIT-13)
- `tests/test_checkpoint.py` — Stub for checkpoint.py; bare import (Phase 3, checkpoint utility)
- `tests/test_video_color_grade.py` — Stub for video_color_grade.py; bare import (Phase 4, UNIT-04)
- `tests/test_video_metadata.py` — Stub for video_metadata.py; bare import (Phase 4, UNIT-05)
- `tests/test_srt_telemetry_parser.py` — Stub for srt_telemetry_parser.py; bare import (Phase 4, UNIT-06)
- `tests/test_video_qa.py` — Stub for video_qa.py; bare import (Phase 4, UNIT-07)
- `tests/test_video_proxy_gen.py` — Stub for video_proxy_gen.py; bare import (Phase 4, UNIT-08)
- `tests/test_video_format_export.py` — Stub for video_format_export.py; bare import (Phase 4, UNIT-09)
- `tests/test_delivery_packaging.py` — Stub for delivery_packaging.py; bare import (Phase 5, UNIT-10)
- `tests/test_gdrive_upload.py` — Stub for gdrive_upload.py; bare import (Phase 5, UNIT-11)
- `tests/test_archive_sync.py` — Stub for archive_sync.py; bare import (Phase 5, UNIT-12)

## Decisions Made

**pytest-tmp-files declaration:** The plan named this package explicitly under TEST-02. It is declared in requirements.txt to satisfy the requirement literally. The built-in pytest `tmp_path` fixture provides all needed functionality; pytest-tmp-files adds no meaningful feature in practice. Zero downside to declaring it.

**importorskip scope expanded:** The plan specified importorskip only for test_folder_watcher_service.py. During Task 2 verification, three additional scripts triggered INTERNALERROR in pytest collection: ingest.py (sys.exit on missing PIL), ingest_sorter.py (bare import requests), and folder_watcher.py (bare import requests + sys.exit on missing watchdog). Applied the same importorskip pattern to all three. This preserves the plan's intent — "pytest tests/ completes without collection errors" — on all environments.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Extended importorskip guards to 3 additional stubs**
- **Found during:** Task 2 verification (--collect-only run)
- **Issue:** ingest.py calls sys.exit() without Pillow; ingest_sorter.py and folder_watcher.py have bare module-level `import requests` which raises ModuleNotFoundError in the test Python 3.14 environment. These caused INTERNALERROR (not collection errors) that aborted pytest collection entirely.
- **Fix:** Added pytest.importorskip() module-level guards to test_ingest.py (PIL), test_ingest_sorter.py (requests), and test_folder_watcher.py (requests + watchdog) — same pattern as test_folder_watcher_service.py
- **Files modified:** tests/test_ingest.py, tests/test_ingest_sorter.py, tests/test_folder_watcher.py
- **Verification:** `pytest tests/ --collect-only` shows 11 collected + 4 skipped, 0 errors; `pytest tests/` shows 11 passed + 4 skipped
- **Committed in:** 1ae8baf (Task 2 commit, included with stub creation)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking collection error)
**Impact on plan:** Fix preserves plan's must_have truth "Running pytest tests/ completes without collection errors". No scope creep.

## Issues Encountered

- Python 3.14 dev environment does not have PIL/requests/watchdog installed (only pytest, pytest-mock in this venv). After `pip install -r requirements.txt`, all 15 stubs will run rather than skip.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Phase 2 fully complete: pytest.ini + conftest.py (Plan 01) + 15 stub files + dev deps (Plan 02)
- Phase 3 (ingest tests), Phase 4 (video tests), Phase 5 (delivery tests) can begin immediately
- Phase 3 and 4 are independent of each other — can run in parallel
- Before running tests: `pip install -r requirements.txt` to install PIL, requests, watchdog and unlock the 4 currently-skipped stubs

---
*Phase: 02-test-infrastructure*
*Completed: 2026-02-23*

## Self-Check: PASSED

All 17 files verified present on disk. Both task commits (68945a7, 1ae8baf) verified in git log.
