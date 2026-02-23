# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Every script runs reliably, recovers from failures, and has tests proving it works
**Current focus:** Phase 3 — Ingest Layer Tests

## Current Position

Phase: 3 of 6 (Ingest Layer Tests)
Plan: 3 of 4 complete in current phase (03-01, 03-02, 03-03 done; 03-04 remains)
Status: Active — 03-03 complete (UNIT-03 folder_watcher + UNIT-13 folder_watcher_service tests), continuing Phase 3
Last activity: 2026-02-23 — Plan 03-03 complete: 27 unit tests for folder_watcher.py (UNIT-03) and folder_watcher_service.py (UNIT-13)

Progress: [██████░░░░] 30%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 2.4 min
- Total execution time: 0.28 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-code-hardening | 4 | 10 min | 2.5 min |
| 02-test-infrastructure | 2 | 5 min | 2.5 min |
| 03-ingest-layer-tests | 1 | 2 min | 2 min |

**Recent Trend:**
- Last 5 plans: 01-04 (1 min), 02-01 (2 min), 02-02 (3 min), 03-02 (2 min)
- Trend: Stable

*Updated after each plan completion*
| Phase 03-ingest-layer-tests P01 | 4 | 1 tasks | 3 files |
| Phase 03-ingest-layer-tests P03 | 4 | 1 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Checkpoint files for resume (GAP-11): JSON manifest per mission dir, atomic writes, skip completed items — IMPLEMENTED (01-03)
- video_qa.py --mission-path optional arg: defaults to CWD since script has no positional mission_path (01-03)
- checkpoint key for video_qa: Supabase asset UUID, not file path — stable across file renames (01-03)
- pytest for testing: Industry standard, rich assertion introspection, fixture support
- Mock external services in tests: Can't call real Supabase/Drive/FFmpeg in CI
- Logging pattern: LOG_DIR constant + dual FileHandler+StreamHandler in setup_logging(log_dir=LOG_DIR) (01-01)
- datetime.UTC class attribute DOES NOT exist — must use timezone.utc; fixed in ingest_sorter.py fire_webhook (03-01 auto-fix)
- Z-suffix preserved in webhook payloads via .replace("+00:00","Z") — n8n expects Z not +00:00 (01-01)
- Exit code semantics: 0=full success, 1=partial failure, 2=fatal/all-failed — maps to n8n retry/alert/continue (01-02)
- Fatal exit pattern: log.error(msg) + sys.exit(2) — never sys.exit(string) (01-02)
- video_qa fail severity = failed, pass+review = ok — review-flagged clips still usable (01-02)
- [Phase 01-04]: Upsert (on_conflict=mission_id,filename) used for graded_path — safe before video_metadata.py runs
- [Phase 01-04]: --upload is opt-in; grading without --upload is 100% unchanged (GAP-10 closed)
- [Phase 01-04]: Supabase unique constraint on video_assets(mission_id,filename): not verifiable in CI — Phase 4 tests should mock or verify
- [Phase 02-01]: Lazy-import patch target is 'supabase.create_client' not call-site module — scripts never bind create_client at module level
- [Phase 02-01]: No autouse=True on any fixture — opt-in only, prevents silent subprocess.run mocking in pure-Python tests
- [Phase 02-01]: pytest>=7.0 pinned because pythonpath= config option was added in 7.0
- [Phase 02-02]: pytest-tmp-files declared to satisfy TEST-02 literally; built-in tmp_path fixture used in practice
- [Phase 02-02]: importorskip pattern extended to ingest/ingest_sorter/folder_watcher stubs — scripts with module-level sys.exit() or bare third-party imports must use importorskip guard not bare import
- [Phase 03-02]: sys.modules injection required for exiftool mock — mocker.patch("exiftool.ExifToolHelper") fails with ModuleNotFoundError when package not installed; use types.ModuleType + mocker.patch.dict("sys.modules") instead
- [Phase 03-02]: _extract_metadata_text does not process side_data_list — only format.tags, stream.tags, codec_long_name, encoder fields
- [Phase 03-ingest-layer-tests]: datetime.UTC is a module-level constant not a class attribute — fire_webhook fixed to use timezone.utc (03-01)
- [Phase 03-ingest-layer-tests]: gimbal_to_orientation zero-gimbal expected [1,0,0,0,0,-1,0,1,0] — not identity matrix; verified against formula (03-01)
- [Phase 03-ingest-layer-tests]: SentinelFolderWatcherService instantiated via __new__ to bypass pywin32 Win32 API calls in tests
- [Phase 03-ingest-layer-tests]: datetime.UTC does not exist as class attribute in Python 3.14 — must use timezone.utc (folder_watcher.py build_inventory fixed)

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 3 and 4 both depend on Phase 2 but are independent of each other — can run in parallel
- ~~GAP-11 (checkpoint resume) is the most complex hardening task~~ RESOLVED — completed in 3 min (01-03)
- ~~`platform_detect.py` unit tests (UNIT-02) require EXIF fixture files or mock pyexiftool — plan for fixture setup time~~ RESOLVED — sys.modules injection avoids need for fixture files (03-02)

## Session Continuity

Last session: 2026-02-23
Stopped at: Completed 03-03-PLAN.md — 27 unit tests for folder_watcher.py (UNIT-03) and folder_watcher_service.py (UNIT-13). Auto-fixed datetime.UTC bug in build_inventory.
Resume file: None
