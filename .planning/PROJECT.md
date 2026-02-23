# Sentinel Drone Pipeline — Hardening & Testing

## What This Is

Post-flight processing pipeline for Sentinel Aerial Inspections (Faith & Harmony LLC). 14 Python CLI scripts handle everything from SD card ingest to client delivery for DJI drones (Mini 4 Pro, Matrice 4E, Mavic 3 Enterprise). This milestone closes all remaining gaps from the initial build and adds a comprehensive test suite.

## Core Value

Every script runs reliably, recovers from failures, and has tests proving it works — so the pipeline can be trusted in production without manual babysitting.

## Requirements

### Validated

- ✓ SD card ingest with mission sorting — `ingest_sorter.py`
- ✓ Drone platform detection (M4E vs M3E via EXIF) — `platform_detect.py`
- ✓ Folder watching with Windows service — `folder_watcher.py`, `folder_watcher_service.py`
- ✓ Video color grading with LUT application — `video_color_grade.py`
- ✓ Video metadata extraction via ffprobe — `video_metadata.py`
- ✓ SRT telemetry parsing and Supabase upload — `srt_telemetry_parser.py`
- ✓ Automated video QA checks — `video_qa.py`
- ✓ 1080p proxy generation for editing — `video_proxy_gen.py`
- ✓ Multi-format video export — `video_format_export.py`
- ✓ Client delivery ZIP packaging — `delivery_packaging.py`
- ✓ Google Drive upload — `gdrive_upload.py`
- ✓ Archive sync (Drive → local cold storage) — `archive_sync.py`
- ✓ Path traversal guards on file operations — existing
- ✓ FFmpeg injection validation — existing
- ✓ Drive API query escaping — existing

### Active

- [ ] GAP-10: `video_color_grade.py` updates `graded_path` in Supabase `video_assets`
- [ ] GAP-11: Error recovery/resume across all scripts via checkpoint files
- [ ] GAP-13: File logging for 5 video pipeline scripts
- [ ] Fix `datetime.utcnow()` deprecation in 3 files
- [ ] Standardize error handling patterns across scripts
- [ ] Unit tests for all 14 scripts
- [ ] Integration tests for pipeline flow (ingest → delivery)

### Out of Scope

- Parallel FFmpeg processing — performance optimization, not reliability (defer to v2)
- n8n workflow configuration — separate system, not part of this codebase
- DaVinci Resolve integration — manual step (V5), external to pipeline
- New drone platform support — no new platforms planned
- GUI/web interface — CLI-only pipeline

## Context

- **Business**: Faith & Harmony LLC DBA Sentinel Aerial Inspections, veteran-owned, Hampton Roads VA
- **Processing rig**: Windows 11, E:\ (incoming), F:\ (archive), Google Drive (warm)
- **Orchestrator**: n8n self-hosted, webhook-triggered from folder watcher
- **Supabase**: Project `qjpujskwqaehxnqypxzu` (shared with other F&H products)
- **3-agent review (2026-02-22)**: Code quality, security, production readiness — 16 fixes applied, QCheck PASS
- **Known patterns**: All scripts use argparse CLI, logging module, subprocess for FFmpeg. Ingest scripts already have file logging; video scripts don't.

## Constraints

- **Stack**: Python 3.8+, FFmpeg, Supabase, Google Drive API — no new dependencies unless essential
- **Platform**: Windows 11 only — all paths use Windows conventions
- **Testing**: pytest preferred (industry standard for Python), mock external services (Supabase, Google Drive, FFmpeg)
- **No breaking changes**: Existing CLI interfaces and folder structures must remain unchanged

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Checkpoint files for resume (GAP-11) | JSON manifest per mission dir, atomic writes, skip completed items | — Pending |
| pytest for testing | Industry standard, rich assertion introspection, fixture support | — Pending |
| Mock external services in tests | Can't call real Supabase/Drive/FFmpeg in CI | — Pending |

---
*Last updated: 2026-02-23 after initialization*
