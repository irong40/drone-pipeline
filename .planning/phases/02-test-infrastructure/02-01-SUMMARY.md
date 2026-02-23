---
phase: 02-test-infrastructure
plan: 01
subsystem: testing
tags: [pytest, pytest-mock, fixtures, mock, supabase, gdrive, ffmpeg, subprocess]

# Dependency graph
requires: []
provides:
  - pytest.ini with testpaths=tests, pythonpath=., markers slow/integration
  - tests/__init__.py empty marker for test discovery
  - tests/conftest.py with three shared fixtures: mock_supabase_client, mock_drive_client, mock_ffmpeg
  - pytest>=7.0 and pytest-mock>=3.10 in requirements.txt
affects:
  - 02-test-infrastructure (plans 02+)
  - 03-unit-tests
  - 04-integration-tests
  - 05-video-pipeline-tests
  - 06-e2e-tests

# Tech tracking
tech-stack:
  added: [pytest>=7.0.0, pytest-mock>=3.10.0]
  patterns:
    - "Lazy-import patch pattern: patch 'supabase.create_client' not 'module_name.create_client'"
    - "MagicMock chain stubs: pre-configure .execute().data to avoid AttributeError on chains"
    - "CompletedProcess(returncode=0) as default subprocess.run mock return value"

key-files:
  created:
    - pytest.ini
    - tests/__init__.py
    - tests/conftest.py
  modified:
    - requirements.txt

key-decisions:
  - "Lazy-import patch target is 'supabase.create_client' not call-site module — scripts never bind create_client at module level"
  - "mock_ffmpeg uses mocker.patch (pytest-mock) not unittest.mock.patch — automatic teardown after each test"
  - "No autouse=True on any fixture — opt-in only, prevents silent subprocess.run mocking in pure-Python tests"
  - "pytest>=7.0 pinned because pythonpath= config option was added in 7.0"
  - "pytest and pytest-mock added to requirements.txt under Testing section (deviation: auto-added missing deps)"

patterns-established:
  - "Fixture scope: all three fixtures are function-scoped (default) — no session or module scope"
  - "MagicMock chain depth: one level of chained .return_value per method, MagicMock auto-generates deeper chains"
  - "Drive mock returns dict not MagicMock for execute() — matches real API response structure"

requirements-completed: [TEST-01]

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 2 Plan 01: pytest Infrastructure Setup Summary

**pytest.ini + tests/conftest.py with mock_supabase_client, mock_drive_client, mock_ffmpeg fixtures covering all external services the pipeline touches**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T19:05:14Z
- **Completed:** 2026-02-23T19:06:27Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- pytest.ini configured at repo root: testpaths=tests, pythonpath=. (no sys.path hacks needed in test files), addopts=-ra --tb=short, markers slow/integration
- tests/__init__.py empty file enables test discovery and future relative imports
- tests/conftest.py with three shared fixtures covering every external service: Supabase (MagicMock table chain), Google Drive (MagicMock files chain), FFmpeg/subprocess (pytest-mock mocker.patch)
- pytest>=7.0 and pytest-mock>=3.10 added to requirements.txt

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pytest.ini and tests/__init__.py** - `4f4ff5b` (chore)
2. **Task 2: Create tests/conftest.py with three shared fixtures** - `796c9f1` (feat)
3. **Deviation: Add pytest deps to requirements.txt** - `67bf239` (chore)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `pytest.ini` - pytest configuration: testpaths, pythonpath, addopts, filterwarnings, markers
- `tests/__init__.py` - empty marker file for test discovery
- `tests/conftest.py` - three shared fixtures for Supabase, Drive, FFmpeg mocking
- `requirements.txt` - added pytest>=7.0.0 and pytest-mock>=3.10.0

## Decisions Made

- **Lazy-import patch target:** All pipeline scripts call `create_client()` inside functions, never at module level. So the correct patch target is `"supabase.create_client"` not `"video_qa.create_client"`. This is documented in the fixture docstring as a pitfall for Phase 3/4 test authors.
- **No autouse=True:** Fixtures are opt-in. Making `mock_ffmpeg` autouse would silently intercept subprocess.run in tests that test pure Python logic with no FFmpeg calls — masking bugs.
- **CompletedProcess default:** `mock_ffmpeg` defaults to `returncode=0` (success). Tests that want to test failure paths override with `.return_value = subprocess.CompletedProcess(args=[], returncode=1, ...)`.
- **Drive mock returns dict:** `files().list().execute()` returns `{"files": [], "nextPageToken": None}` — a real dict, not MagicMock — because pipeline code calls `result["files"]` (dict key access), which fails on MagicMock.
- **pytest 7.0+ pinned:** The `pythonpath = .` option in pytest.ini was added in pytest 7.0. Lower versions silently ignore it and sys.path manipulation would fail. Version pin prevents silent breakage.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Installed pytest and pytest-mock, added to requirements.txt**
- **Found during:** Task 1 (pre-flight check)
- **Issue:** pytest and pytest-mock were not installed (`No module named pytest`) and not in requirements.txt
- **Fix:** Ran `pip install pytest pytest-mock`, then added both to requirements.txt under a new `# Testing` section
- **Files modified:** requirements.txt
- **Verification:** `python -m pytest --collect-only` exits 5 (no tests, no errors). `pip show pytest pytest-mock` confirms installation.
- **Committed in:** `67bf239` (separate chore commit)

---

**Total deviations:** 1 auto-fixed (missing critical dependency)
**Impact on plan:** pytest is required for all Phase 2-6 plans. Fix is essential. No scope creep.

## Issues Encountered

None beyond the missing pytest dependency addressed above.

## User Setup Required

None — pytest and pytest-mock were installed automatically. No external service configuration required.

## Pitfalls for Phase 3/4 Test Authors

1. **Lazy import patch scope:** Use `mocker.patch("supabase.create_client", ...)` not `mocker.patch("video_qa.create_client", ...)`. All pipeline scripts import lazily inside functions — the name is never bound at module level.

2. **LOG_DIR constant:** Scripts with file logging call `setup_logging(log_dir=LOG_DIR)` at the top of functions. The LOG_DIR path (`E:/Processing/logs/` etc.) won't exist in CI. Either mock `setup_logging` or patch `LOG_DIR` to `tmp_path` in tests.

3. **pywin32 import guard:** `folder_watcher_service.py` imports `win32serviceutil` at the top. Tests running on Linux CI will fail on import. Use `pytest.importorskip("win32serviceutil")` or `@pytest.mark.skipif(sys.platform != "win32", ...)`.

4. **Drive mock dict keys:** The Drive mock returns `{"files": [], "nextPageToken": None}` for `list().execute()`. Code that accesses `result.get("files")` or `result["files"]` works. Code that does `result.files` would fail — use dict access in pipeline code.

5. **mock_ffmpeg side_effect for multi-call scripts:** `video_color_grade.py` calls FFmpeg twice (grade + compress). Use `mock_ffmpeg.side_effect = [result1, result2]` to return different results per call.

## Next Phase Readiness

- Test scaffolding is complete. Phase 2 Plan 02 can proceed to verify package requirements (coverage, etc.)
- Phase 3/4/5/6 test files can `from tests.conftest import *` or just declare fixture parameters — pytest auto-discovers conftest.py
- `import ingest_sorter` works in test files without any sys.path manipulation (pythonpath=. handles it)

---
*Phase: 02-test-infrastructure*
*Completed: 2026-02-23*

## Self-Check: PASSED

| Item | Status |
|------|--------|
| pytest.ini | FOUND |
| tests/__init__.py | FOUND |
| tests/conftest.py | FOUND |
| 02-01-SUMMARY.md | FOUND |
| Commit 4f4ff5b (pytest.ini + __init__.py) | FOUND |
| Commit 796c9f1 (conftest.py) | FOUND |
| Commit 67bf239 (requirements.txt) | FOUND |
| `pytest --collect-only` exit 5 | PASS |
