# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Every script runs reliably, recovers from failures, and has tests proving it works
**Current focus:** Phase 5 — Delivery and Archive Tests

## Current Position

Phase: 4 of 6 (Video Pipeline Tests) — COMPLETE
Plan: 3 of 3 complete in Phase 4 (04-01, 04-02, 04-03 done)
Status: Phase 4 complete — 224 tests passing; ready to start Phase 5
Last activity: 2026-02-23 — Plan 04-03 complete: 33 unit tests for video_proxy_gen.py (UNIT-08) and video_format_export.py (UNIT-09). Full suite 224 passed.

Progress: [█████████░] 50%

## Performance Metrics

**Velocity:**
- Total plans completed: 10
- Average duration: 2.5 min
- Total execution time: 0.42 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-code-hardening | 4 | 10 min | 2.5 min |
| 02-test-infrastructure | 2 | 5 min | 2.5 min |
| 03-ingest-layer-tests | 1 | 2 min | 2 min |
| 04-video-pipeline-tests | 3 | 8 min | 2.7 min |

**Recent Trend:**
- Last 5 plans: 03-02 (2 min), 03-03 (2 min), 04-01 (2 min), 04-02 (4 min), 04-03 (2 min)
- Trend: Stable

*Updated after each plan completion*
| Phase 03-ingest-layer-tests P01 | 4 | 1 tasks | 3 files |
| Phase 03-ingest-layer-tests P03 | 4 | 1 tasks | 3 files |
| Phase 04-video-pipeline-tests P01 | 2 | 3 tasks | 3 files |
| Phase 04-video-pipeline-tests P02 | 4 | 3 tasks | 2 files |
| Phase 04-video-pipeline-tests P03 | 2 | 3 tasks | 2 files |

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
- [Phase 04-01]: sys.modules injection for supabase: mocker.patch("supabase.create_client") requires the module to be importable — use types.ModuleType stub via autouse fixture when package not installed in CI
- [Phase 04-01]: Module-level constant patching: mocker.patch("video_color_grade.SUPABASE_URL", value) patches already-evaluated module constant; os.environ patching does not work after import
- [Phase 04-01]: conftest .single() chain stub added non-breakingly for video_qa plan 04-02
- [Phase 04-video-pipeline-tests]: stub_supabase_module autouse fixture per test file (not conftest) — maintains no-autouse-in-conftest principle; uses types.ModuleType + mocker.patch.dict(sys.modules) pattern
- [Phase 04-video-pipeline-tests]: GPS drift guard confirmed: check_gps_drift only fires when duration_seconds < 30; tests must use duration_seconds=10 to trigger
- [Phase 04-video-pipeline-tests]: Banker's rounding tolerance: use abs= with pytest.approx when testing round() results at .5 boundaries (round(0.066,2)=0.07, round(30.25,1)=30.2)
- [Phase 04-video-pipeline-tests]: sys.modules stub required for supabase test (not installed) — consistent with Phase 04-01/02 pattern
- [Phase 04-video-pipeline-tests]: build_ffmpeg_command tested as pure function — no subprocess mock needed for UNIT-09 core coverage

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 3 and 4 both depend on Phase 2 but are independent of each other — can run in parallel
- ~~GAP-11 (checkpoint resume) is the most complex hardening task~~ RESOLVED — completed in 3 min (01-03)
- ~~`platform_detect.py` unit tests (UNIT-02) require EXIF fixture files or mock pyexiftool — plan for fixture setup time~~ RESOLVED — sys.modules injection avoids need for fixture files (03-02)

## Session Continuity

Last session: 2026-02-23
Stopped at: Completed 04-03-PLAN.md — 33 unit tests for video_proxy_gen.py (UNIT-08) and video_format_export.py (UNIT-09). Full suite 224 tests passed. Phase 4 complete.
Resume file: None
