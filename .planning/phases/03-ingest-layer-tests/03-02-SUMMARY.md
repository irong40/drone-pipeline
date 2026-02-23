---
phase: 03-ingest-layer-tests
plan: 02
subsystem: testing
tags: [pytest, pyexiftool, pillow, ffprobe, platform-detect, exif, drone, unit-tests]

# Dependency graph
requires:
  - phase: 02-test-infrastructure
    provides: pytest config, conftest.py fixtures, test stub files
provides:
  - 21-test UNIT-02 suite for platform_detect.py covering all detection paths
affects: [04-video-layer-tests, any phase referencing platform_detect.py]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - sys.modules injection for mocking lazy-imported modules not installed in dev env
    - types.ModuleType() + MagicMock context manager protocol for pyexiftool mocking
    - mocker.patch("platform_detect.detect_from_exiftool") for sub-function isolation

key-files:
  created: []
  modified:
    - tests/test_platform_detect.py

key-decisions:
  - "sys.modules injection (mocker.patch.dict) required for exiftool mock — module not installed in dev env, mocker.patch('exiftool.ExifToolHelper') fails with ModuleNotFoundError"
  - "types.ModuleType helper _make_exiftool_mock() reduces boilerplate for 6 exiftool test cases"
  - "detect_platform_from_folder filename_fallback test uses real DJI_NNNN.JPG filename at tmp_path root — no mocking needed since exiftool/PIL both unavailable and folder has no subdirs"

patterns-established:
  - "Lazy-import module mock pattern: inject via sys.modules when module is not installed"
  - "Context manager mock: mock_et_class.return_value.__enter__.return_value = mock_instance"

requirements-completed: [UNIT-02]

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 3 Plan 02: platform_detect.py Unit Tests (UNIT-02) Summary

**21-test suite covering pyexiftool context manager mock, PIL EXIF fallback, ffprobe JSON parsing, metadata text extraction, and folder-level consensus detection for Mini 4 Pro, M4E, and M3E**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T19:26:56Z
- **Completed:** 2026-02-23T19:29:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Replaced test_placeholder() stub with 21 independent test functions covering all UNIT-02 cases
- Solved pyexiftool mocking challenge: since `exiftool` is not installed in dev env, used `sys.modules` injection via `mocker.patch.dict` + `types.ModuleType` to provide a fully configured mock module without requiring the real package
- All detection paths verified: XMP priority over EXIF, EXIF:Model substring match, PIL fallback tag 272, ffprobe format/stream tags, filename fallback, folder consensus

## Task Commits

Each task was committed atomically:

1. **Task 1: RED/GREEN — Write and pass platform_detect.py tests (UNIT-02)** - `a4a3d5e` (feat)

**Plan metadata:** TBD (docs: complete plan)

_Note: Plan was written-and-passing in a single step — source functions existed, tests needed to match actual behavior._

## Files Created/Modified

- `tests/test_platform_detect.py` - Full UNIT-02 test suite replacing placeholder stub (21 test functions)

## Decisions Made

- **sys.modules injection for exiftool mock:** `mocker.patch("exiftool.ExifToolHelper")` raises `ModuleNotFoundError` when `exiftool` package is not installed. Solution: inject a `types.ModuleType("exiftool")` with a `MagicMock()` ExifToolHelper into `sys.modules` via `mocker.patch.dict`. This approach is teardown-safe and doesn't require installing pyexiftool in dev/CI.
- **_extract_metadata_text side_data_list NOT tested:** Plan's behavior section listed a `side_data_list` test case, but the actual source function (lines 222-242) does not process `side_data_list` — it only handles `tags`, `codec_long_name`, and `encoder` stream fields. Test was written to match actual source behavior (codec_long_name field instead).
- **detect_platform_from_folder filename_fallback:** Used DJI_NNNN.JPG filename at tmp_path root. When no photos/jpeg subdir exists and no video/full dir, the function's `os.walk` fallback finds DJI_ prefixed files and calls `detect_from_filename`. No mocking needed since exiftool is unavailable and file has no real EXIF.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Replaced mocker.patch("exiftool.ExifToolHelper") with sys.modules injection**
- **Found during:** Task 1 (first test run)
- **Issue:** `mocker.patch("exiftool.ExifToolHelper")` raises `ModuleNotFoundError: No module named 'exiftool'` because pytest-mock resolves the module path at patch time, requiring the module to be importable even if patched away
- **Fix:** Created `_make_exiftool_mock()` helper using `types.ModuleType("exiftool")` + `mocker.patch.dict("sys.modules", {"exiftool": fake_et})`. This injects a mock module before the function's `import exiftool` runs.
- **Files modified:** `tests/test_platform_detect.py`
- **Verification:** All 6 exiftool tests pass; mocker auto-teardown restores original sys.modules state
- **Committed in:** a4a3d5e (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug in mock strategy)
**Impact on plan:** Required fix for test execution. Pattern is now documented for other scripts that lazy-import optional packages (PIL, exiftool, pywin32).

## Issues Encountered

- Plan specified `mocker.patch("exiftool.ExifToolHelper")` but this approach requires the exiftool module to be installed. Since pyexiftool is not in the dev environment, a `sys.modules` injection pattern was necessary. See Decision above.

## User Setup Required

None - no external service configuration required. All tests run in isolation with mocked dependencies.

## Next Phase Readiness

- UNIT-02 complete: platform_detect.py has full test coverage
- The `sys.modules` injection pattern is now documented and can be reused for any script that lazy-imports optional packages (useful for Phase 4 video pipeline tests that mock ffmpeg/PIL)
- Remaining Phase 3 plans: ingest_sorter.py, folder_watcher.py, ingest.py (Path C / WebODM)

---
*Phase: 03-ingest-layer-tests*
*Completed: 2026-02-23*
