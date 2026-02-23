---
phase: 01-code-hardening
plan: "03"
subsystem: pipeline-scripts
tags: [checkpoint, resume, error-recovery, video-pipeline]
dependency_graph:
  requires: [01-01, 01-02]
  provides: [GAP-11-checkpoint-resume]
  affects: [video_color_grade.py, video_proxy_gen.py, video_format_export.py, srt_telemetry_parser.py, video_qa.py]
tech_stack:
  added: [checkpoint.py]
  patterns: [atomic-write-os-replace, per-mission-checkpoint-json, skip-and-continue-loop]
key_files:
  created:
    - checkpoint.py
  modified:
    - video_color_grade.py
    - video_proxy_gen.py
    - video_format_export.py
    - srt_telemetry_parser.py
    - video_qa.py
decisions:
  - "Checkpoint keys: video_path for file-based scripts, format name for video_format_export, asset UUID for video_qa"
  - "video_qa uses --mission-path optional arg (defaults to CWD) since it has no positional mission_path"
  - "video_proxy_gen: checkpoint is authoritative; file-existence check kept as secondary guard"
  - "srt_telemetry_parser: checkpoint save occurs after upload success (--upload path) or after parse success (local path)"
metrics:
  duration: "3 min"
  completed_date: "2026-02-23"
  tasks_completed: 2
  files_changed: 6
---

# Phase 01 Plan 03: Checkpoint Resume Utility Summary

Atomic JSON checkpoint/resume for all 5 video pipeline scripts — re-running after failure skips completed files and finishes from where it left off.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create checkpoint.py shared utility | 4a87662 | checkpoint.py (new) |
| 2 | Integrate checkpoint resume into 5 video scripts | 35bf323 | video_color_grade.py, video_proxy_gen.py, video_format_export.py, srt_telemetry_parser.py, video_qa.py |

## What Was Built

**checkpoint.py** — stdlib-only shared utility:
- `load_checkpoint(mission_path, script_name)` — returns set of completed item keys; empty set if no checkpoint
- `save_checkpoint(mission_path, script_name, completed)` — atomic write via tempfile + os.replace(); crash-safe
- `clear_checkpoint(mission_path, script_name)` — removes checkpoint file (used by --force)
- `checkpoint_path(mission_path, script_name)` — returns `.checkpoint_{script_name}.json` path in mission folder
- Version-tagged JSON format (CHECKPOINT_VERSION = 1) for future migrations

**5 video scripts updated** — each has:
- `from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint`
- `--force` CLI flag to clear checkpoint and re-process from scratch
- Checkpoint loading before the processing loop with resume log message
- Per-item skip check (`if item_key in completed: ... continue`)
- Per-item checkpoint save after success with non-fatal OSError handling

**Script-specific checkpoint keys:**
| Script | item_key | Notes |
|--------|----------|-------|
| video_color_grade.py | absolute video_path | File-based |
| video_proxy_gen.py | absolute video_path | Checkpoint authoritative; file-exists as secondary guard |
| video_format_export.py | fmt["name"] (e.g., "instagram_reels") | Format-based |
| srt_telemetry_parser.py | absolute srt_path | Saves after upload success or parse success |
| video_qa.py | asset["id"] (UUID) | Requires --mission-path for checkpoint dir; defaults to CWD |

## Decisions Made

1. **Checkpoint keys use absolute paths** — avoids ambiguity if CWD changes between runs; stable across resume
2. **video_qa.py gets --mission-path arg** — the script has no positional mission_path (Supabase-driven), so an optional --mission-path was added; defaults to CWD to preserve backward compat
3. **video_proxy_gen.py: checkpoint + file-exists both kept** — checkpoint is authoritative for speed (no disk stat), file-exists is retained as secondary guard for edge cases (manually created proxies, etc.)
4. **srt_telemetry_parser.py: two save paths** — checkpoint saved after upload success (--upload mode) and after parse success (local mode), ensuring correct semantics in both code paths
5. **Atomic writes via os.replace()** — documented as atomic on both POSIX and Windows since Python 3.3; tempfile ensures partial writes never replace good data

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] video_qa.py lacked mission_path for checkpoint storage**
- **Found during:** Task 2
- **Issue:** video_qa.py has no positional mission_path argument (it is Supabase-driven via --mission-id). The plan assumed all scripts had a mission_path variable, but video_qa.py does not.
- **Fix:** Added optional `--mission-path` argument (defaults to `os.getcwd()`). This preserves backward compatibility while giving operators the ability to specify where checkpoints live when running from a different directory.
- **Files modified:** video_qa.py
- **Commit:** 35bf323

## Verification Results

All plan verification criteria satisfied:

```
python -c "from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint; print('imports ok')"
# → imports ok

grep -l "from checkpoint import" video_color_grade.py video_proxy_gen.py video_format_export.py srt_telemetry_parser.py video_qa.py
# → all 5 filenames

grep -l "\-\-force" video_color_grade.py video_proxy_gen.py video_format_export.py srt_telemetry_parser.py video_qa.py
# → all 5 filenames

# Inline assertion test
python -c "from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint; ..."
# → checkpoint.py: all assertions pass

python -m py_compile video_color_grade.py video_proxy_gen.py video_format_export.py srt_telemetry_parser.py video_qa.py
# → All syntax OK
```

## Self-Check: PASSED
