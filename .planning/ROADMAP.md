# Roadmap: Sentinel Drone Pipeline — Hardening & Testing

## Overview

Close the remaining gaps from the initial build (GAP-10, GAP-11, GAP-13, plus deprecation and error handling), then layer in a comprehensive test suite working layer by layer from ingest through delivery. When complete, every script runs reliably, recovers from failures, and has tests proving it works.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Code Hardening** - Fix the 5 active gaps across all scripts (completed 2026-02-23)
- [x] **Phase 2: Test Infrastructure** - Configure pytest, fixtures, and mock scaffolding (completed 2026-02-23)
- [ ] **Phase 3: Ingest Layer Tests** - Unit tests for ingest_sorter, platform_detect, folder_watcher
- [ ] **Phase 4: Video Pipeline Tests** - Unit tests for all 6 video processing scripts
- [ ] **Phase 5: Delivery Layer Tests** - Unit tests for delivery_packaging, gdrive_upload, archive_sync
- [ ] **Phase 6: Integration Tests** - End-to-end flow tests with checkpointing verification

## Phase Details

### Phase 1: Code Hardening
**Goal**: Every script is production-hardened with consistent logging, error handling, Supabase updates, and no deprecation warnings
**Depends on**: Nothing (first phase)
**Requirements**: GAP-10, GAP-11, GAP-13, DEPR-01, ERR-01
**Success Criteria** (what must be TRUE):
  1. Running any video script in production writes a persistent log file to `E:\Sentinel\logs\` — no output is lost when stdout is discarded
  2. Re-running any script after a mid-run failure skips already-completed files and processes only the remaining ones
  3. After `video_color_grade.py` grades a clip, the `graded_path` column in Supabase `video_assets` is updated immediately without requiring a separate metadata run
  4. All scripts exit with consistent codes (0=success, 1=partial failure, 2=fatal) and log to stderr on error
  5. Running `python -W error` against all 3 affected files produces no DeprecationWarning for datetime usage
**Plans**: 4 plans

Plans:
- [ ] 01-01-PLAN.md — Add file logging to 5 video scripts (GAP-13) + fix datetime deprecation in 3 files (DEPR-01)
- [ ] 01-02-PLAN.md — Standardize exit codes and fatal error handling across 5 video scripts (ERR-01)
- [ ] 01-03-PLAN.md — Create checkpoint.py utility + integrate checkpoint resume into 5 video scripts (GAP-11)
- [ ] 01-04-PLAN.md — Add Supabase graded_path update to video_color_grade.py (GAP-10)

### Phase 2: Test Infrastructure
**Goal**: pytest framework is configured with shared fixtures and mock scaffolding that all subsequent test phases can build on
**Depends on**: Phase 1
**Requirements**: TEST-01, TEST-02, TEST-03
**Success Criteria** (what must be TRUE):
  1. Running `pytest tests/` from the repo root completes without import errors or configuration failures
  2. A test can import `mock_supabase_client`, `mock_drive_client`, and `mock_ffmpeg` fixtures from conftest.py without additional setup
  3. Every script has a corresponding `test_{script_name}.py` stub file in the `tests/` directory
**Plans**: 2 plans

Plans:
- [ ] 02-01-PLAN.md — Create pytest.ini + tests/__init__.py + tests/conftest.py with 3 shared fixtures (TEST-01)
- [ ] 02-02-PLAN.md — Add dev dependencies to requirements.txt + create 15 test stub files (TEST-02, TEST-03)

### Phase 3: Ingest Layer Tests
**Goal**: Ingest layer scripts have verified unit test coverage for all critical logic paths
**Depends on**: Phase 2
**Requirements**: UNIT-01, UNIT-02, UNIT-03, UNIT-13, UNIT-14
**Success Criteria** (what must be TRUE):
  1. `pytest tests/test_ingest_sorter.py` passes — file sorting, sequence assignment, and mission config validation are verified
  2. `pytest tests/test_platform_detect.py` passes — Mini 4 Pro, M4E, and M3E are correctly identified from EXIF fixtures, and the ffprobe fallback path is covered
  3. `pytest tests/test_folder_watcher.py` and `test_folder_watcher_service.py` pass — debounce logic, event filtering, and service lifecycle are verified
  4. `pytest tests/test_ingest.py` passes — MipMap photogrammetry ingest logic is covered
**Plans**: TBD

Plans:
- [ ] 03-01: Unit tests for ingest_sorter.py and ingest.py
- [ ] 03-02: Unit tests for platform_detect.py
- [ ] 03-03: Unit tests for folder_watcher.py and folder_watcher_service.py

### Phase 4: Video Pipeline Tests
**Goal**: All 6 video processing scripts have unit test coverage verifying FFmpeg command construction, Supabase payloads, and processing logic
**Depends on**: Phase 2
**Requirements**: UNIT-04, UNIT-05, UNIT-06, UNIT-07, UNIT-08, UNIT-09
**Success Criteria** (what must be TRUE):
  1. `pytest tests/test_video_color_grade.py` passes — LUT selection per platform, FFmpeg command structure, and graded_path Supabase update are verified
  2. `pytest tests/test_video_metadata.py` and `test_srt_telemetry_parser.py` pass — ffprobe parsing, Supabase upsert payloads, and SRT frame aggregation are verified
  3. `pytest tests/test_video_qa.py` passes — threshold checks, pass/warn/fail classification, and QA report structure are verified
  4. `pytest tests/test_video_proxy_gen.py` and `test_video_format_export.py` pass — proxy resolution selection, graded fallback, format template loading, and encoding args are verified
**Plans**: TBD

Plans:
- [ ] 04-01: Unit tests for video_color_grade.py and video_metadata.py
- [ ] 04-02: Unit tests for srt_telemetry_parser.py and video_qa.py
- [ ] 04-03: Unit tests for video_proxy_gen.py and video_format_export.py

### Phase 5: Delivery Layer Tests
**Goal**: Delivery layer scripts have unit test coverage for packaging, Drive API interactions, and archive sync logic
**Depends on**: Phase 2
**Requirements**: UNIT-10, UNIT-11, UNIT-12
**Success Criteria** (what must be TRUE):
  1. `pytest tests/test_delivery_packaging.py` passes — ZIP structure, address-based naming, and photos-only vs video-addendum modes are verified
  2. `pytest tests/test_gdrive_upload.py` passes — folder creation, file upload, and Drive API calls are verified against mocked Drive client
  3. `pytest tests/test_archive_sync.py` passes — age-based file filtering, sync logic, and cleanup safety guards are verified
**Plans**: TBD

Plans:
- [ ] 05-01: Unit tests for delivery_packaging.py
- [ ] 05-02: Unit tests for gdrive_upload.py and archive_sync.py

### Phase 6: Integration Tests
**Goal**: End-to-end integration tests verify the full pipeline flow and checkpoint-based resume work correctly against a real file structure
**Depends on**: Phase 3, Phase 4, Phase 5
**Requirements**: INTG-01, INTG-02, INTG-03, INTG-04
**Success Criteria** (what must be TRUE):
  1. `pytest tests/integration/test_ingest_flow.py` passes — a synthetic SD card structure is ingested and produces a correctly structured mission folder
  2. `pytest tests/integration/test_video_pipeline.py` passes — color grade through proxy generation runs against a small test fixture with mocked FFmpeg and real file structure
  3. `pytest tests/integration/test_delivery_flow.py` passes — packaging and Drive upload run against a complete mock mission with mocked Drive API and real ZIP creation
  4. `pytest tests/integration/test_checkpoint_resume.py` passes — a simulated mid-script failure followed by re-run skips completed files and finishes processing the remaining ones
**Plans**: TBD

Plans:
- [ ] 06-01: Integration test for ingest flow (INTG-01)
- [ ] 06-02: Integration test for video pipeline flow (INTG-02)
- [ ] 06-03: Integration test for delivery flow + checkpoint resume (INTG-03, INTG-04)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6
Phases 3, 4, 5 all depend on Phase 2. Phases 3 and 4 can run in parallel if desired.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Code Hardening | 4/4 | Complete    | 2026-02-23 |
| 2. Test Infrastructure | 2/2 | Complete   | 2026-02-23 |
| 3. Ingest Layer Tests | 0/3 | Not started | - |
| 4. Video Pipeline Tests | 0/3 | Not started | - |
| 5. Delivery Layer Tests | 0/2 | Not started | - |
| 6. Integration Tests | 0/3 | Not started | - |
