---
phase: 15-foundation-scripts-schema
plan: 02
subsystem: automation
tags: [subprocess, psutil, mipmap, fire-and-forget, pid-file, orphan-detection]

# Dependency graph
requires:
  - phase: 14-n8n-execute-command
    provides: "n8n Execute Command node enablement for calling Python scripts"
provides:
  - "mipmap_launcher.py -- fire-and-forget MipMap subprocess launcher with orphan detection"
  - "launch_mipmap() function for subprocess.Popen with stdout redirect and PID file"
  - "check_orphan() function for psutil-based orphan detection"
affects: [16-n8n-subworkflows, path-c-mipmap]

# Tech tracking
tech-stack:
  added: [psutil]
  patterns: [fire-and-forget-subprocess, pid-file-orphan-detection, stdout-redirect-to-log]

key-files:
  created: [mipmap_launcher.py, tests/test_mipmap_launcher.py]
  modified: []

key-decisions:
  - "No shell=True in Popen -- returns shell PID not MipMap PID, breaking orphan detection"
  - "PID file contains JSON with pid, started_at, project for debugging"
  - "Orphan detection checks pid_exists + process name match to handle recycled PIDs"

patterns-established:
  - "Fire-and-forget pattern: Popen with stdout to log file, PID file, return immediately"
  - "Orphan detection: PID file + psutil.pid_exists + process name match"

requirements-completed: [MPC-01, MPC-02, MPC-07, TST-01]

# Metrics
duration: 2min
completed: 2026-03-05
---

# Phase 15 Plan 02: MipMap Launcher Summary

**Fire-and-forget MipMap subprocess launcher with psutil orphan detection, PID file tracking, and pipeline contract compliance**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-05T15:25:16Z
- **Completed:** 2026-03-05T15:27:06Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments
- mipmap_launcher.py with launch_mipmap(), check_orphan(), and main() following pipeline contract
- 13 unit tests covering launch, orphan detection (4 scenarios), exit codes (0/1/2), JSON stdout, pipeline contract
- Orphan detection handles stale PIDs, recycled PIDs, and active MipMap processes
- No real MipMap executable needed -- all subprocess/psutil calls fully mocked

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Create test suite** - `1b520b1` (test)
2. **Task 1 GREEN: Implement mipmap_launcher.py** - `84036ef` (feat)

## Files Created/Modified
- `mipmap_launcher.py` - Fire-and-forget subprocess launcher with orphan detection and pipeline contract
- `tests/test_mipmap_launcher.py` - 13 unit tests covering all scenarios

## Decisions Made
- No shell=True in Popen -- shell PID breaks orphan detection, need actual MipMap PID
- PID file JSON includes pid, started_at, project for debugging and orphan identification
- Orphan detection uses psutil.pid_exists + process name match to handle PID recycling
- Log file opened before Popen so stdout redirects from the very start

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- mipmap_launcher.py ready for n8n Path C sub-workflow integration
- Requires psutil package installed in production environment
- MipMap Desktop must be installed for real execution (script handles missing gracefully with exit 2)

---
*Phase: 15-foundation-scripts-schema*
*Completed: 2026-03-05*

## Self-Check: PASSED
