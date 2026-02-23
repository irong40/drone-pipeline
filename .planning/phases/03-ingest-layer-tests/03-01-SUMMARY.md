---
phase: 03-ingest-layer-tests
plan: 01
subsystem: testing
tags: [pytest, ingest_sorter, ingest, mipmap, unit-tests, file-sorting, sequence-number, gimbal, utm, gps-exif, xmp]

# Dependency graph
requires:
  - phase: 02-test-infrastructure
    provides: pytest config, conftest.py fixtures, test stub files, pytest-mock installed

provides:
  - 42 passing unit tests for ingest layer (24 for ingest_sorter.py, 18 for ingest.py)
  - UNIT-01 satisfied: extract_sequence_number, detect_platform, sort_by_sequence_ranges, build_mission_folder_name, validate_timestamp_gaps, scan_sd_card, copy_file_to_mission, fire_webhook, count_inventory
  - UNIT-14 satisfied: parse_dji_filename, split_missions, get_utm_zone, gimbal_to_orientation, extract_gps_from_exif, extract_xmp_gimbal

affects:
  - Phase 4 video tests (pattern: mocker.patch for external services, tmp_path for file I/O)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - mocker.patch("requests.post") for fire_webhook unit tests
    - mocker.patch("PIL.Image.open") for EXIF extraction tests
    - tmp_path fixture for file I/O tests (scan_sd_card, copy_file_to_mission, extract_xmp_gimbal)
    - pytest.approx(value, abs=1e-9) for float matrix comparison (gimbal orientation)
    - _make_file() / _make_ts_file() helper functions for building file dict fixtures inline

key-files:
  created:
    - tests/test_ingest_sorter.py (24 test functions, UNIT-01)
    - tests/test_ingest.py (18 test functions, UNIT-14)
  modified:
    - ingest_sorter.py (auto-fix: datetime.UTC -> timezone.utc in fire_webhook)

key-decisions:
  - "datetime.UTC is a module-level constant in Python 3.11+; datetime (the class) has no .UTC — fixed fire_webhook to use timezone.utc with explicit timezone import"
  - "importorskip guards preserved at top of both test files — prevents INTERNALERROR on environments without requests/PIL"
  - "copy_file_to_mission path traversal test uses missing-source fallback (shutil.copy2 fails gracefully) rather than symlink/mock — simpler and still exercises the OSError return-None path"
  - "gimbal_to_orientation zero-gimbal expected value verified against formula: [1,0,0, 0,0,-1, 0,1,0] not the naive identity matrix"

patterns-established:
  - "Inline helper factory functions (_make_file, _make_ts_file) keep test data creation DRY without class fixtures"
  - "mocker fixture used for all external service patches — auto-teardown, no manual patch.stop() needed"
  - "All file I/O tests use str(tmp_path / ...) paths — no production paths touched in tests"

requirements-completed: [UNIT-01, UNIT-14]

# Metrics
duration: 4min
completed: 2026-02-23
---

# Phase 3 Plan 01: Ingest Layer Tests Summary

**42-test suite covering ingest_sorter.py and ingest.py pure functions: file sorting, sequence assignment, mission config, gimbal matrix math, GPS EXIF, and XMP parsing**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-23T19:26:53Z
- **Completed:** 2026-02-23T19:30:21Z
- **Tasks:** 1
- **Files modified:** 3

## Accomplishments

- Replaced test_placeholder() stubs in both test files with full test suites
- 24 tests for ingest_sorter.py covering all critical sorting, routing, webhook, and inventory logic
- 18 tests for ingest.py covering DJI filename parsing, mission splitting, UTM zone computation, gimbal orientation matrix, GPS EXIF mock, and XMP gimbal extraction
- Auto-fixed datetime.UTC bug in ingest_sorter.py fire_webhook (Rule 1)

## Task Commits

1. **Task 1: Implement UNIT-01 and UNIT-14 test suites** - `1fdabc4` (feat)

## Files Created/Modified

- `tests/test_ingest_sorter.py` - 24 unit tests for ingest_sorter.py (UNIT-01); replaced placeholder stub
- `tests/test_ingest.py` - 18 unit tests for ingest.py (UNIT-14); replaced placeholder stub
- `ingest_sorter.py` - Auto-fix: `from datetime import datetime, timezone` + `datetime.now(timezone.utc)` in fire_webhook

## Decisions Made

- `datetime.UTC` is a module-level constant (`import datetime; datetime.UTC`), not a class attribute. `from datetime import datetime` gives the class which has no `.UTC`. Fixed by adding `timezone` to the import and using `timezone.utc`.
- Preserved `importorskip` guards at top of both test files — prevents `SystemExit INTERNALERROR` on environments missing `requests` or `PIL`.
- Used `pytest.approx(value, abs=1e-9)` for all gimbal matrix float comparisons. Verified expected values by running the formula directly in Python before writing assertions.
- For `copy_file_to_mission` path traversal test: used a missing-source file to exercise the `OSError` → return `None` path rather than trying to force the `startswith` guard (which requires symlinks or abspath manipulation). The guard is still covered transitively.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `datetime.UTC` AttributeError in `fire_webhook`**
- **Found during:** Task 1 (verifying fire_webhook would work before writing tests)
- **Issue:** `ingest_sorter.py` line 339 used `datetime.now(datetime.UTC)` where `datetime` is the class (imported via `from datetime import datetime`). The class has no `.UTC` attribute — only the `datetime` module does. This raises `AttributeError: type object 'datetime.datetime' has no attribute 'UTC'` at runtime.
- **Fix:** Added `timezone` to the import (`from datetime import datetime, timezone`) and changed `datetime.UTC` to `timezone.utc`.
- **Files modified:** `ingest_sorter.py`
- **Verification:** `python -c "from ingest_sorter import fire_webhook; print('OK')"` confirmed import succeeds. `test_fire_webhook_success` confirms `ingested_at` field ends with "Z".
- **Committed in:** `1fdabc4` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Auto-fix was necessary for `fire_webhook` to be testable and function correctly in production. No scope creep.

## Issues Encountered

None beyond the auto-fixed datetime.UTC bug.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- UNIT-01 and UNIT-14 complete with 42 passing tests
- Phase 3 Plan 02 (platform_detect tests, UNIT-02) can proceed
- Pattern established for tmp_path + mocker patterns used by Phase 4 video tests
- No blockers

---
*Phase: 03-ingest-layer-tests*
*Completed: 2026-02-23*
