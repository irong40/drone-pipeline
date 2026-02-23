# Requirements: Sentinel Drone Pipeline — Hardening & Testing

**Defined:** 2026-02-23
**Core Value:** Every script runs reliably, recovers from failures, and has tests proving it works

## v1 Requirements

### Gap Closure

- [ ] **GAP-10**: `video_color_grade.py` updates `graded_path` in Supabase `video_assets` after successful grading
- [ ] **GAP-11**: All processing scripts support checkpoint-based resume (skip already-completed files on re-run)
- [ ] **GAP-13**: 5 video pipeline scripts write logs to `E:\Sentinel\logs\{script_name}.log` with both file and stdout handlers
- [ ] **DEPR-01**: Replace `datetime.utcnow()` with `datetime.now(datetime.UTC)` in `archive_sync.py`, `ingest_sorter.py`, `folder_watcher.py`
- [ ] **ERR-01**: Standardize error handling across all scripts — consistent exit codes (0=success, 1=partial failure, 2=fatal), structured log format, stderr capture to log files

### Test Infrastructure

- [ ] **TEST-01**: pytest framework configured with `conftest.py`, shared fixtures for mock Supabase client, mock Google Drive client, mock FFmpeg subprocess
- [ ] **TEST-02**: pytest-mock and pytest-tmp-files added to `requirements.txt` dev dependencies
- [ ] **TEST-03**: `tests/` directory structure mirrors script layout with `test_{script_name}.py` per script

### Unit Tests

- [ ] **UNIT-01**: Unit tests for `ingest_sorter.py` — file sorting, sequence assignment, mission config parsing
- [ ] **UNIT-02**: Unit tests for `platform_detect.py` — EXIF detection, ffprobe fallback, Mini 4 Pro vs M4E vs M3E
- [ ] **UNIT-03**: Unit tests for `folder_watcher.py` — debounce logic, event filtering, webhook payload
- [ ] **UNIT-04**: Unit tests for `video_color_grade.py` — LUT selection, FFmpeg command construction, graded_path update
- [ ] **UNIT-05**: Unit tests for `video_metadata.py` — ffprobe parsing, Supabase upsert payload, platform-specific fields
- [ ] **UNIT-06**: Unit tests for `srt_telemetry_parser.py` — SRT frame parsing, GPS extraction, telemetry aggregation
- [ ] **UNIT-07**: Unit tests for `video_qa.py` — threshold checks, pass/fail logic, QA report generation
- [ ] **UNIT-08**: Unit tests for `video_proxy_gen.py` — proxy resolution, graded vs full fallback, FFmpeg args
- [ ] **UNIT-09**: Unit tests for `video_format_export.py` — format template loading, encoding args, Supabase status update
- [ ] **UNIT-10**: Unit tests for `delivery_packaging.py` — ZIP structure, address naming, photos-only vs video-addendum
- [ ] **UNIT-11**: Unit tests for `gdrive_upload.py` — folder creation, file upload, Drive API calls
- [ ] **UNIT-12**: Unit tests for `archive_sync.py` — sync logic, cleanup safety, age-based filtering
- [ ] **UNIT-13**: Unit tests for `folder_watcher_service.py` — service install/remove, start/stop lifecycle
- [ ] **UNIT-14**: Unit tests for `ingest.py` — MipMap photogrammetry ingest (existing script)

### Integration Tests

- [ ] **INTG-01**: Integration test for ingest flow — SD card → sorted mission folder with correct structure
- [ ] **INTG-02**: Integration test for video pipeline — color grade → metadata → telemetry → QA → proxy (mocked FFmpeg, real file structure)
- [ ] **INTG-03**: Integration test for delivery flow — packaging → upload → archive (mocked Drive API, real ZIP creation)
- [ ] **INTG-04**: Integration test for checkpoint resume — simulate failure mid-script, verify resume skips completed items

## v2 Requirements

### Performance

- **PERF-01**: Parallel FFmpeg processing in `video_format_export.py`
- **PERF-02**: Async Supabase calls for batch telemetry upload

### Observability

- **OBS-01**: Structured JSON logging for machine parsing
- **OBS-02**: Pipeline metrics dashboard (processing time, failure rates)

## Out of Scope

| Feature | Reason |
|---------|--------|
| n8n workflow configuration | Separate system, managed outside this codebase |
| DaVinci Resolve integration | Manual step (V5), external to pipeline |
| New drone platform support | No new platforms planned for this milestone |
| GUI/web interface | CLI-only pipeline by design |
| CI/CD pipeline | No remote repo yet; tests run locally |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| GAP-10 | Phase 1 | Pending |
| GAP-11 | Phase 1 | Pending |
| GAP-13 | Phase 1 | Pending |
| DEPR-01 | Phase 1 | Pending |
| ERR-01 | Phase 1 | Pending |
| TEST-01 | Phase 2 | Pending |
| TEST-02 | Phase 2 | Pending |
| TEST-03 | Phase 2 | Pending |
| UNIT-01 | Phase 3 | Pending |
| UNIT-02 | Phase 3 | Pending |
| UNIT-03 | Phase 3 | Pending |
| UNIT-13 | Phase 3 | Pending |
| UNIT-14 | Phase 3 | Pending |
| UNIT-04 | Phase 4 | Pending |
| UNIT-05 | Phase 4 | Pending |
| UNIT-06 | Phase 4 | Pending |
| UNIT-07 | Phase 4 | Pending |
| UNIT-08 | Phase 4 | Pending |
| UNIT-09 | Phase 4 | Pending |
| UNIT-10 | Phase 5 | Pending |
| UNIT-11 | Phase 5 | Pending |
| UNIT-12 | Phase 5 | Pending |
| INTG-01 | Phase 6 | Pending |
| INTG-02 | Phase 6 | Pending |
| INTG-03 | Phase 6 | Pending |
| INTG-04 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 26 total
- Mapped to phases: 26
- Unmapped: 0

---
*Requirements defined: 2026-02-23*
*Last updated: 2026-02-23 after roadmap creation — all requirements mapped*
