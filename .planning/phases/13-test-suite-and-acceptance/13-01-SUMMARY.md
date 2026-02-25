---
phase: 13-test-suite-and-acceptance
plan: 01
subsystem: testing
tags: [pytest, mocking, canopy-detection, species-classification, deepforest, openai, plantnet, supabase, rasterio]

# Dependency graph
requires:
  - phase: 08-canopy-detection
    provides: canopy_detection.py (E1 script with tiling, NMS, GeoJSON, Supabase upsert)
  - phase: 09-species-classification
    provides: species_classification.py (E2 script with OpenAI Vision, PlantNet, reconciliation)
provides:
  - tests/test_canopy_detection.py — 26 E1 unit tests (tiling, NMS, coords, export, checkpoint)
  - tests/test_species_classification.py — 24 E2 unit tests (crop, OpenAI, PlantNet, reconcile, Supabase)
affects: [14-deployment, any phase consuming E1/E2 outputs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level sys.modules stub injection for multi-dep test isolation without package install"
    - "FakePolygon pure-Python class with real geometric ops (intersects, intersection, union, area)"
    - "Lazy-import patching via sys.modules[module].attribute = mock (not patch() which requires module-level binding)"
    - "numpy stub with np.isscalar, np.bool_, np.ndarray for pytest.approx compatibility"

key-files:
  created:
    - tests/test_canopy_detection.py
    - tests/test_species_classification.py
  modified:
    - species_classification.py

key-decisions:
  - "All stubs installed at module level before canopy_detection/species_classification import — autouse fixtures too late for top-level import-time code"
  - "FakePolygon with real AABB geometry ops replaces shapely dependency — IoU, intersection, union computed correctly without real shapely"
  - "Lazy-imported symbols (OpenAI, requests, shapely.geometry.box) must be patched in sys.modules, not as species_classification.Symbol"
  - "numpy stub must include np.bool_, np.isscalar for pytest.approx compatibility on Python 3.14 without numpy"
  - "PLANTNET_QUOTA_EXHAUSTED sentinel committed alongside E2 tests — working-tree enhancement from Phase 09 that hadn't been committed"

patterns-established:
  - "Pre-import stub pattern: _install_stubs() called at module top before all from-module imports"
  - "Context-manager mock dataset: MagicMock with __enter__/__exit__ for rasterio.open pattern"

requirements-completed:
  - TST-01
  - TST-02

# Metrics
duration: 35min
completed: 2026-02-25
---

# Phase 13 Plan 01: Test Suite and Acceptance — E1/E2 Unit Tests Summary

**50 unit tests for canopy_detection.py (E1) and species_classification.py (E2) running on system Python 3.14 with complete module stubs for torch, deepforest, rasterio, shapely, numpy, geopandas, openai, and supabase.**

## Performance

- **Duration:** 35 min
- **Started:** 2026-02-25T23:00:00Z
- **Completed:** 2026-02-25T23:35:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- 26 E1 tests: tiling dimensions/edge-handling/overlap, NMS suppress/keep/empty, pixel-to-geo transform, GeoJSON/GPKG schema, Supabase payload structure, checkpoint resume, zero-detection path, PROJ_LIB env cleanup
- 24 E2 tests: crop_canopy padding/edge/bands, OpenAI parse/failure/clamp, PlantNet parse/skip/quota-exhausted, reconcile genus-match/mismatch/no-plantnet/clamp, cost abort/proceed, max_canopies cap, checkpoint skip, Supabase batch update
- All 50 new tests pass; original 266 baseline tests continue to pass
- Committed PLANTNET_QUOTA_EXHAUSTED sentinel enhancement to species_classification.py (working-tree fix from Phase 09 that hadn't been committed)

## Task Commits

Each task was committed atomically:

1. **Task 1: test_canopy_detection.py** - `6f0838a` (feat)
2. **Task 2: test_species_classification.py + species_classification.py enhancement** - `f13b422` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `tests/test_canopy_detection.py` — 26 unit tests for E1 canopy detection pipeline
- `tests/test_species_classification.py` — 24 unit tests for E2 species classification pipeline
- `species_classification.py` — Added PLANTNET_QUOTA_EXHAUSTED sentinel, quota tracking, time.sleep(0.5) rate limiting, cross-validated count and avg_confidence in summary return

## Decisions Made

- All module stubs installed at module level before source imports — autouse fixtures fire too late for top-level import-time code in canopy_detection.py and species_classification.py.
- FakePolygon with real AABB geometry provides correct IoU, intersection, and union math without requiring shapely package.
- Lazy-imported symbols (openai.OpenAI, requests.post, shapely.geometry.box) must be patched by directly setting `sys.modules[module].attr = mock` rather than using `patch("module.Symbol")`.
- numpy stub includes np.bool_, np.isscalar, np.ndarray, np.float64 to satisfy pytest.approx internals on Python 3.14 where numpy is unavailable.
- PLANTNET_QUOTA_EXHAUSTED sentinel committed with E2 test file since tests depend on it and it was an uncommitted working-tree enhancement.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Complete numpy/shapely stubs required — packages not installed in system Python**
- **Found during:** Task 1 (test_canopy_detection.py execution)
- **Issue:** System Python 3.14 only has pytest, requests, pillow, pywin32, watchdog. No numpy, shapely, rasterio, torch, geopandas. The plan assumed stubs would be needed but didn't specify extent.
- **Fix:** Built FakePolygon pure-Python class with real geometric ops, stub numpy module with all pytest.approx-required attributes (np.bool_, np.isscalar, np.ndarray), full rasterio/windows/transform stubs, and pandas stub for zero-detection branch.
- **Files modified:** tests/test_canopy_detection.py (stub design)
- **Verification:** All 26 E1 tests pass on system Python
- **Committed in:** 6f0838a (Task 1 commit)

**2. [Rule 3 - Blocking] Lazy-import patching required for OpenAI, requests, shapely.geometry.box**
- **Found during:** Task 2 (test_species_classification.py execution)
- **Issue:** species_classification.py imports OpenAI, requests, and shapely.geometry.box INSIDE function bodies (lazy imports). `patch("species_classification.OpenAI")` fails with AttributeError since the attribute is never bound at module level.
- **Fix:** Patched directly via `sys.modules["openai"].OpenAI = mock_cls` and `sys.modules["requests"].post = mock_fn` and `sys.modules["shapely.geometry"].box = tracking_fn`.
- **Files modified:** tests/test_species_classification.py
- **Verification:** All 24 E2 tests pass including OpenAI/PlantNet/padding tests
- **Committed in:** f13b422 (Task 2 commit)

**3. [Rule 1 - Bug] PLANTNET_QUOTA_EXHAUSTED sentinel committed (missing from prior phase commit)**
- **Found during:** Task 2 (importing PLANTNET_QUOTA_EXHAUSTED from species_classification)
- **Issue:** Working-tree species_classification.py had PLANTNET_QUOTA_EXHAUSTED and quota tracking but these were uncommitted enhancements from Phase 09.
- **Fix:** Committed species_classification.py changes alongside test file.
- **Files modified:** species_classification.py
- **Verification:** Import succeeds; test_plantnet_quota_exhausted_returns_sentinel passes
- **Committed in:** f13b422 (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (2 blocking, 1 bug)
**Impact on plan:** All deviations were necessary for correctness on system Python. No scope creep.

## Issues Encountered

- pytest.approx requires numpy attributes (np.bool_, np.isscalar) even when numpy is not the value being compared — had to add these to the numpy stub after initial test run.
- `write_output_files` zero-canopy branch does `import pandas as pd` — had to add a pandas stub.
- GeoDataFrame is called with positional args `GeoDataFrame(data_dict, geometry=..., crs=...)` — fake_gdf functions need `*args, **kwargs` signatures.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- E1 and E2 unit tests complete and passing (50 tests)
- TST-01 and TST-02 satisfied
- Ready for remaining Phase 13 tests: E3 health assessment (already committed as test_health_assessment.py), E4 vegetation report (already committed as test_vegetation_report.py)
- Note: test_health_assessment.py and test_vegetation_report.py have pre-existing failures on system Python — they import numpy/folium directly at module level rather than using the stub-injection pattern established in this plan

---
*Phase: 13-test-suite-and-acceptance*
*Completed: 2026-02-25*
