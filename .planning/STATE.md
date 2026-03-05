---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Package Router & End-to-End Automation
status: in-progress
stopped_at: Completed 15-02-PLAN.md (mipmap_launcher fire-and-forget subprocess launcher)
last_updated: "2026-03-05T15:31:31.529Z"
last_activity: 2026-03-05 — Completed 15-03 (ortho_harvester GeoTIFF copy utility)
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 5
  completed_plans: 5
---

---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Package Router & End-to-End Automation
status: in-progress
stopped_at: Completed 15-03-PLAN.md (ortho_harvester GeoTIFF copy with integrity verification)
last_updated: "2026-03-05T15:27:30Z"
last_activity: 2026-03-05 — Completed 15-03 (ortho_harvester GeoTIFF copy utility)
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 5
  completed_plans: 5
---

---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Package Router & End-to-End Automation
status: in-progress
stopped_at: Completed 19-02-PLAN.md (n8n validation + Package Router integration tests)
last_updated: "2026-03-05T15:21:00Z"
last_activity: 2026-03-05 — Completed 19-02 (n8n workflow validation + Package Router integration tests)
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 4
  completed_plans: 4
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-05)

**Core value:** Every script runs reliably, recovers from failures, and has tests proving it works
**Current focus:** Phase 15 - Foundation Scripts & Schema (v3.0)

## Current Position

Phase: 15 of 19 (Foundation Scripts & Schema)
Plan: 3 of 5 in current phase (15-03 complete)
Status: Executing Phase 15 plans
Last activity: 2026-03-05 — Completed 15-03 (ortho_harvester GeoTIFF copy utility)

Progress: [██████████] 100% (v3.0)

## Performance Metrics

**Velocity (v1.0):**
- Total plans completed: 17
- Average duration: 2.2 min
- Total execution time: ~37 min

**Velocity (v2.0):**
- Total plans completed: 14
- Total execution time: ~154 min

**Velocity (v3.0):**
- Total plans completed: 4
- Estimated plans: 12
- 14-01: 4 min, 2 tasks, 3 files
- 14-02: 2 min, 2 tasks, 2 files
- 19-01: 3 min, 3 tasks, 5 files
- 19-02: 3 min, 2 tasks, 2 files
- 15-03: 2 min, 1 task (TDD), 2 files

## Accumulated Context

### Decisions

See PROJECT.md Key Decisions table for full history.

Recent decisions affecting current work:
- v3.0: Native Windows n8n over Docker (Python/GPU access, Windows paths unchanged)
- v3.0: Sub-workflow per path (mirrors proven Path E pattern)
- v3.0: Fire-and-forget MipMap launch with polling (avoid n8n stdout buffer overflow)
- v3.0: Sequential GPU scheduling (Path E after MipMap completes, not concurrent)
- v3.0: Single shared sub-workflow for Path B/D manual handling (package_type as parameter)
- v3.0: Folder name regex non-greedy match for package_type with underscore support
- v3.0: is_fallback flag on folder_watcher payloads for deduplication downstream
- v3.0: Config/patch files get JSON-syntax-only validation (no node structure checks)
- v3.0: build_processing_steps helper lives in test file as test utility
- v3.0: Step mapping covers all 6 automated + 2 manual types + unknown fallback
- [Phase 15]: UNIQUE(mission_id) on processing_jobs enforces one active job per mission
- [Phase 15]: rasterio fallback to TIFF magic bytes when not installed
- [Phase 15]: temp-file-then-rename copy pattern for safe GeoTIFF transfer
- [Phase 15]: No shell=True in Popen -- preserves MipMap PID for orphan detection

### Pending Todos

- Real-ortho acceptance test (TST-06 deferred from v2.0) — run E1-E4 on a real orthomosaic when available
- Verify n8n version (v1.x vs v2.x) before Phase 14 — determines Execute Command re-enabling steps
- Validate MipMap output filename pattern with test dataset during Phase 15

### Blockers/Concerns

- n8n v2.0 may disable Execute Command nodes by default — Phase 14 must verify this first
- MipMap stdout produces 50-200MB — never run directly via Execute Command node
- GPU contention between Path C/E/V — sequential scheduling required until file-based lock exists

## Session Continuity

Last session: 2026-03-05T15:28:26.184Z
Stopped at: Completed 15-02-PLAN.md (mipmap_launcher fire-and-forget subprocess launcher)
Resume file: None
