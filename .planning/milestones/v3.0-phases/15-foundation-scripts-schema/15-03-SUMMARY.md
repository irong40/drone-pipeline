---
phase: 15-foundation-scripts-schema
plan: 03
subsystem: pipeline
tags: [geotiff, rasterio, shutil, copy-integrity, tdd]

requires:
  - phase: 15-foundation-scripts-schema
    provides: pipeline_status.py, pipeline_utils.py (shared pipeline contract)
provides:
  - ortho_harvester.py -- GeoTIFF copy from MipMap workspace to mission mapping/ with integrity verification
  - tests/test_ortho_harvester.py -- 15 unit tests covering validation, copy, exit codes, pipeline contract
affects: [mipmap-integration, path-e-automation, n8n-workflows]

tech-stack:
  added: [rasterio (optional), shutil.copy2]
  patterns: [temp-file-then-rename copy, rasterio fallback to TIFF magic bytes, pipeline contract]

key-files:
  created: [ortho_harvester.py, tests/test_ortho_harvester.py]
  modified: []

key-decisions:
  - "rasterio fallback to TIFF magic bytes (0x4949/0x4D4D) when rasterio not installed"
  - "temp-file-then-rename pattern for safe copy (shutil.copy2 to .tmp, then os.rename)"
  - "MockRasterioDataset class in tests for configurable rasterio mock"

patterns-established:
  - "rasterio stub: autouse fixture injecting fake rasterio module into sys.modules"
  - "temp-file-then-rename: copy to .tmp then os.rename for atomic-ish file operations"

requirements-completed: [MPC-04, MPC-05, TST-02]

duration: 2min
completed: 2026-03-05
---

# Phase 15 Plan 03: Ortho Harvester Summary

**GeoTIFF copy utility with rasterio validation, temp-file-then-rename safety, and TIFF magic byte fallback**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T15:25:20Z
- **Completed:** 2026-03-05T15:27:08Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments
- ortho_harvester.py copies GeoTIFF from MipMap workspace to mission mapping/ folder
- Integrity verification via file size comparison + rasterio header check (CRS, dimensions, bands)
- Graceful degradation to TIFF magic byte validation when rasterio unavailable
- Pipeline contract followed: argparse CLI, setup_logging, PipelineStatusReporter, exit codes 0/1/2
- 15 unit tests pass with fully mocked rasterio and shutil -- no real GeoTIFF needed

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for ortho_harvester** - `4651313` (test)
2. **Task 1 (GREEN): Implement ortho_harvester.py** - `f383122` (feat)

## Files Created/Modified
- `ortho_harvester.py` - GeoTIFF copy with integrity verification, pipeline contract, rasterio fallback
- `tests/test_ortho_harvester.py` - 15 tests: validate_geotiff (5), verify_copy_integrity (2), copy_ortho (3), main (5)

## Decisions Made
- rasterio fallback checks TIFF magic bytes (0x4949 little-endian or 0x4D4D big-endian) + file size when rasterio not installed
- temp-file-then-rename pattern: shutil.copy2 to .tmp file, then os.rename for safety against interruption
- MockRasterioDataset class with configurable width/height/count/crs for flexible test scenarios

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ortho_harvester.py ready for integration with MipMap workflow (Path E)
- Exports copy_ortho(), validate_geotiff(), verify_copy_integrity(), main() as specified
- rasterio optional dependency -- works with degraded validation if not installed

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 15-foundation-scripts-schema*
*Completed: 2026-03-05*
