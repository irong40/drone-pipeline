---
phase: 04-video-pipeline-tests
plan: 3
subsystem: video-pipeline
tags: [tests, unit-tests, ffmpeg, proxy, format-export, tdd]
dependency_graph:
  requires: [video_proxy_gen.py, video_format_export.py, tests/conftest.py]
  provides: [UNIT-08, UNIT-09]
  affects: [Phase 5 delivery packaging tests]
tech_stack:
  added: []
  patterns:
    - sys.modules stub for supabase (types.ModuleType) — consistent with Phase 04-01/02 pattern
    - pure-function testing for build_ffmpeg_command (no subprocess mock needed)
    - tmp_path for filesystem fixture setup (find_source_videos, find_master_video)
    - mock_ffmpeg fixture for generate_proxy and get_video_duration subprocess calls
key_files:
  created: []
  modified:
    - tests/test_video_proxy_gen.py
    - tests/test_video_format_export.py
decisions:
  - sys.modules stub required for supabase test (not installed) — same pattern as Phase 04-01/02
  - build_ffmpeg_command tested as pure function — no mock needed, no subprocess calls
  - truncation boundary: source_duration > max_dur (strictly greater) — equal-to-limit returns no -t flag
metrics:
  duration: 2 min
  completed: 2026-02-23
  tasks_completed: 3
  files_modified: 2
---

# Phase 4 Plan 3: Video Proxy Gen and Format Export Tests Summary

Replaced two test stubs with complete unit test suites for video_proxy_gen.py (UNIT-08) and video_format_export.py (UNIT-09). Full Phase 4 test suite (130 tests across 6 files) and full suite (224 tests) pass with 0 failures.

## What Was Built

### Task 1 — UNIT-08: video_proxy_gen.py tests (10 tests, commit 7f744df)

**File:** `tests/test_video_proxy_gen.py`

- `find_source_videos`: 5 tests covering graded-dir preference, empty-graded fallback, full-dir fallback when graded missing, no-dirs returns empty, multi-file sorted order
- `generate_proxy`: 5 tests covering correct FFmpeg command structure (scale filter with pad, libx264, preset, crf 23, -c:a copy), failure return, ValueError for path-traversal resolution, ValueError for alpha resolution, custom crf/preset params

### Task 2 — UNIT-09: video_format_export.py tests (23 tests, commit b10f4ce)

**File:** `tests/test_video_format_export.py`

- `build_ffmpeg_command` copy-codec path: 2 tests — no `-vf`, both `-c:v copy` and `-c:a copy`
- `build_ffmpeg_command` re-encode path: 3 tests — libx264 required args (scale, crf 18, preset medium, fps, aac 192k), libx265 crf/preset, scale filter with pad
- `build_ffmpeg_command` truncation: 4 tests — applied when over limit, not applied when under, not applied when equal, not applied when duration=None
- `build_ffmpeg_command` validation: 4 tests — path-traversal raises ValueError, alpha raises ValueError, output last arg, starts with ffmpeg -y -i
- `get_video_duration`: 3 tests — parses ffprobe JSON, returns 0.0 on invalid JSON, returns 0.0 on missing duration key
- `find_master_video`: 3 tests — found, not found (no dir), not found (empty dir)
- `fetch_formats_from_supabase`: 2 tests — env not set returns None, mission not found returns None
- `DEFAULT_FORMATS`: 2 tests — required platform names present, all entries have required schema keys

### Task 3 — Full suite verification (no file changes)

- Phase 4 suite: `pytest tests/test_video_color_grade.py tests/test_video_metadata.py tests/test_srt_telemetry_parser.py tests/test_video_qa.py tests/test_video_proxy_gen.py tests/test_video_format_export.py` — **130 passed**
- Full suite: `pytest tests/` — **224 passed, 0 failed, 0 errors**
- UNIT-04 through UNIT-09 all satisfied
- Phase 4 complete — ready to proceed to Phase 5

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] supabase module not installed — sys.modules stub required**
- **Found during:** Task 2, `test_fetch_formats_from_supabase_returns_none_when_mission_not_found`
- **Issue:** `mocker.patch("supabase.create_client")` raises `ModuleNotFoundError: No module named 'supabase'`
- **Fix:** Replaced with `types.ModuleType` stub injected via `mocker.patch.dict("sys.modules", {"supabase": stub_supabase})` — consistent with Phase 04-01/02 established pattern
- **Files modified:** `tests/test_video_format_export.py`
- **Commit:** b10f4ce

## Self-Check: PASSED

- tests/test_video_proxy_gen.py — FOUND
- tests/test_video_format_export.py — FOUND
- .planning/phases/04-video-pipeline-tests/04-03-SUMMARY.md — FOUND
- commit 7f744df — FOUND
- commit b10f4ce — FOUND
