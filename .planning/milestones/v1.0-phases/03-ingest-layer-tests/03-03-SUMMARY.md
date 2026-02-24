---
phase: 03-ingest-layer-tests
plan: 03
subsystem: testing
tags: [pytest, pytest-mock, watchdog, pywin32, threading, debounce, windows-service]

# Dependency graph
requires:
  - phase: 02-test-infrastructure
    provides: pytest config, importorskip stubs, conftest fixtures
provides:
  - 19 unit tests for folder_watcher.py (UNIT-03): parse_mission_number, build_inventory, fire_webhook, MissionFolderHandler debounce/event/lifecycle
  - 8 unit tests for folder_watcher_service.py (UNIT-13): class attributes, SvcStop, SvcDoRun
affects:
  - 04-video-pipeline-tests
  - CI test runs

# Tech tracking
tech-stack:
  added: [watchdog==6.0.0, pywin32==311]
  patterns:
    - mocker.patch('folder_watcher.threading.Timer') to prevent real 60s debounce sleeps
    - SentinelFolderWatcherService.__new__() to bypass pywin32 Win32 API calls in tests
    - build_inventory tested via real tmp_path directory structures

key-files:
  created: []
  modified:
    - tests/test_folder_watcher.py
    - tests/test_folder_watcher_service.py
    - folder_watcher.py

key-decisions:
  - "mocker.patch.object(handler, '_reset_timer') used per-instance to avoid shared state from _triggered set"
  - "SentinelFolderWatcherService instantiated via __new__ (not __init__) — bypasses win32serviceutil.ServiceFramework OS registration and win32event.CreateEvent"
  - "win32event.SetEvent and servicemanager.LogMsg patched at their origin module path, not the import-site"
  - "fake_inventory in _on_debounce_complete test must include total_size_bytes key — used in log statement inside _on_debounce_complete"
  - "datetime.UTC does not exist in Python 3.14 — folder_watcher.py build_inventory fixed to use timezone.utc (same fix applied to ingest_sorter.py in 03-01)"

patterns-established:
  - "Threading timer pattern: always patch 'folder_watcher.threading.Timer' before calling _reset_timer or instantiating handler"
  - "Windows service test pattern: __new__ instantiation + manual attribute set (stop_event, running) + mocker.patch.object(svc, 'ReportServiceStatus')"
  - "Fresh MissionFolderHandler per test function — _triggered set is instance-scoped and prevents re-triggering"

requirements-completed: [UNIT-03, UNIT-13]

# Metrics
duration: 4min
completed: 2026-02-23
---

# Phase 3 Plan 03: folder_watcher + folder_watcher_service Unit Tests Summary

**27 pytest tests covering watchdog debounce logic (timer cancel/guard/daemon), filesystem event routing, webhook payload correctness, and pywin32 Windows service lifecycle (SvcStop/SvcDoRun) without any real threading sleeps or Win32 OS calls**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-23T19:30:00Z
- **Completed:** 2026-02-23T19:35:06Z
- **Tasks:** 1 (TDD — single task, tests written and passed)
- **Files modified:** 3

## Accomplishments

- 19 tests in `tests/test_folder_watcher.py` covering all required behaviors: 5 parse_mission_number cases (valid + None), 5 build_inventory cases (mixed files, empty, photos-only, total_size, Z-suffix), 2 fire_webhook cases (success + RequestException), 3 _reset_timer cases (cancel/guard/daemon), 3 on_created cases (top-level dir, file event, nested-dir ignored), 1 _on_debounce_complete case
- 8 tests in `tests/test_folder_watcher_service.py` covering class attribute assertions (name, display_name, description), SvcStop (running=False + SetEvent + ReportServiceStatus), SvcDoRun (running=True + main() called + LogMsg)
- Auto-fixed `datetime.UTC` bug in `folder_watcher.py` `build_inventory` — same bug as in `ingest_sorter.py` fixed in plan 03-01
- Full test suite passed: 100 tests across all test files, 0 failures

## Task Commits

Each task was committed atomically:

1. **Task 1: Write tests for folder_watcher.py and folder_watcher_service.py** - `6cd9237` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `tests/test_folder_watcher.py` - 19 unit tests for UNIT-03 (replaced test_placeholder stub)
- `tests/test_folder_watcher_service.py` - 8 unit tests for UNIT-13 (replaced test_placeholder stub)
- `folder_watcher.py` - Fixed `datetime.UTC` → `timezone.utc` in `build_inventory` (line 109); added `timezone` to datetime import

## Decisions Made

- Used `mocker.patch.object(handler, "_reset_timer")` per-test-instance to avoid contamination from the `_triggered` set idempotency guard
- Used `__new__` pattern for `SentinelFolderWatcherService` rather than patching `ServiceFramework.__init__` — simpler and more robust against pywin32 version differences
- Patched `win32event.SetEvent` and `servicemanager.LogMsg` at their origin module paths (not import-site) consistent with Phase 2 lazy-import conventions

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `datetime.UTC` AttributeError in `folder_watcher.py`**
- **Found during:** Task 1 (pre-test verification of `build_inventory`)
- **Issue:** `folder_watcher.py` line 109 used `datetime.now(datetime.UTC)` — `datetime.UTC` is not an attribute on the `datetime` class in Python 3.14 (`datetime.UTC` is a module-level constant added in Python 3.11, but accessed as `datetime.UTC` — i.e., from `datetime import datetime; datetime.UTC` — which is wrong; correct form is `from datetime import timezone; timezone.utc`)
- **Fix:** Added `timezone` to the `from datetime import datetime, timezone` import; changed `datetime.UTC` to `timezone.utc`
- **Files modified:** `folder_watcher.py`
- **Verification:** `build_inventory()` returns correct dict with Z-suffix `detected_at`; all 27 tests pass
- **Committed in:** `6cd9237` (Task 1 commit)

**2. [Rule 1 - Bug] Added `total_size_bytes` key to fake inventory in `_on_debounce_complete` test**
- **Found during:** Task 1 (first test run — 26/27 pass)
- **Issue:** `_on_debounce_complete` accesses `inventory['total_size_bytes']` in a log statement. Initial fake inventory dict omitted this key, causing `KeyError`
- **Fix:** Added `"total_size_bytes": 1024` to the mock return value for `build_inventory` in the test
- **Files modified:** `tests/test_folder_watcher.py`
- **Verification:** All 27 tests pass after fix
- **Committed in:** `6cd9237` (same task commit — fix applied before commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both fixes necessary for correctness. No scope creep. Same `datetime.UTC` bug pattern was encountered in plan 03-01 for `ingest_sorter.py`; now closed in `folder_watcher.py` as well.

## Issues Encountered

- `watchdog` and `pywin32` were not installed in the test environment — installed via pip as a prerequisite to running tests (deviation Rule 3 — blocking dependency). No plan change required; dependencies were already in `requirements.txt`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- UNIT-03 and UNIT-13 complete — folder watcher ingest layer fully covered
- Plan 03-04 is the final plan in Phase 3 (video pipeline tests)
- All 100 tests passing with 0 regressions

---
*Phase: 03-ingest-layer-tests*
*Completed: 2026-02-23*
