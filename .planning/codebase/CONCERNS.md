# Codebase Concerns

**Analysis Date:** 2026-02-23

## Tech Debt

**GAP-10: video_color_grade missing Supabase update**
- Issue: `video_color_grade.py` generates graded video files but does NOT update the `graded_path` column in the Supabase `video_assets` table. Only `video_metadata.py` can populate this field via ffprobe inspection.
- Files: `video_color_grade.py` (lines 1-197), `video_metadata.py` (lines 289, 357)
- Impact: Downstream steps (video_qa, video_proxy_gen) may not reliably find graded video files if they depend on `graded_path` being set at the time of grading. Current workaround is to always run `video_metadata.py` after grading, but this creates a hard dependency and ordering constraint.
- Fix approach: Either (1) add Supabase client to `video_color_grade.py` to update `graded_path` immediately after successful encoding, or (2) document strict ordering requirement in orchestration layer and ensure n8n never skips the metadata step.

**GAP-11: No error recovery/resume across scripts**
- Issue: All 14 scripts assume fresh run with no partial progress. If a script fails mid-mission (e.g., FFmpeg crash on file 5 of 10), re-running the script either re-processes already-successful files (wasting time) or requires manual cleanup of partial outputs before retry.
- Files: All scripts, particularly video processing pipeline (`video_color_grade.py`, `video_proxy_gen.py`, `video_format_export.py`, `srt_telemetry_parser.py`, `video_qa.py`)
- Impact: Long-running missions (100+ photos, 50+ video clips) may experience 10-20% failure rate due to transient I/O issues, disk full, or process interruption. Recovery requires manual intervention (deleting partial files) or acceptance of wasted processing.
- Fix approach: Add resume capability via checkpoint files (JSON manifest of completed files) in each mission's output directory. Before processing, read checkpoint; skip already-completed items; append new completions. Use atomic writes to prevent checkpoint corruption. Estimated effort: 3-5 hours per script.

**GAP-13: No file logging for video pipeline scripts**
- Issue: Video processing scripts (`video_color_grade.py`, `video_proxy_gen.py`, `video_format_export.py`, `srt_telemetry_parser.py`, `video_qa.py`) log to stdout only. Photos and ingest scripts correctly log to files in `E:\Sentinel\logs\`.
- Files: `video_color_grade.py` (lines 40-46), `video_proxy_gen.py` (lines 38-44), `video_format_export.py` (lines 44-50), `srt_telemetry_parser.py` (lines 55-61), `video_qa.py` (lines 46-52)
- Impact: When running in production (n8n orchestrator or Windows Task Scheduler), stdout is lost. Troubleshooting failures requires manual stdout capture or re-running locally. No persistent audit trail of which videos failed and why.
- Fix approach: Add file logging to all 5 video scripts following pattern from `ingest_sorter.py` lines 73-84 and `archive_sync.py` lines 34-45. Create `{LOG_DIR}/{script_name}.log` with both file and stdout handlers. Estimated effort: 30 minutes.

**datetime.utcnow() deprecation warnings**
- Issue: Python 3.12+ deprecates `datetime.utcnow()` in favor of `datetime.now(datetime.UTC)`. Currently used in 3 files without warning suppression or migration path.
- Files: `archive_sync.py` (line 206), `ingest_sorter.py` (line 339), `folder_watcher.py` (line 109)
- Impact: Code will break on Python 3.13+. Not urgent (current environment uses Python 3.x but version not locked), but should be addressed before environment upgrade.
- Fix approach: Replace `datetime.utcnow()` with `datetime.now(datetime.UTC)` and import `datetime.UTC` from `datetime` module. Update 3 files in parallel (5 minutes total). Should pair with a Python version lock in `requirements.txt`.

**Inconsistent error handling patterns**
- Issue: FFmpeg operations handle errors in 3 different ways: (1) check returncode and log stderr (video_color_grade, video_proxy_gen), (2) catch subprocess exceptions (none), (3) let exceptions bubble up. Database operations use try/except for import errors but not for API failures. No consistent error reporting format.
- Files: `video_color_grade.py` (lines 104-110), `video_proxy_gen.py` (lines 103-104), `gdrive_upload.py` (lines 44-62), `srt_telemetry_parser.py` (lines 369-373), `video_qa.py` (lines 273-279)
- Impact: When chained in n8n, mixed error signals make it hard to determine why a mission failed. Some scripts exit with status 1, others log.error() and continue, others raise exceptions.
- Fix approach: Define shared `ErrorHandler` class with standardized logging + exit code behavior. Use in all scripts consistently.

## Known Bugs

**Path traversal vulnerability in file operations (MITIGATED but review needed)**
- Symptoms: Malicious filenames with `..` or absolute paths could write files outside intended directories
- Files: `ingest_sorter.py` (lines 275-283), `archive_sync.py` (lines 156-164), `delivery_packaging.py` (collection functions)
- Current mitigation: Uses `os.path.basename()` to strip directory components, then verifies result with `startswith(os.path.abspath(...))` to ensure dest stays within intended directory. This is correct but not obvious.
- Recommendation: Add explicit docstring warnings to `copy_file_to_mission()` and `sync_delivered_to_archive()` documenting the security assumption. Consider adding logging for blocked traversal attempts (already present in both files).

**FFmpeg stderr truncation loses diagnostic data**
- Symptoms: FFmpeg failures show only last 500 characters of stderr: `stderr[-500:]`
- Files: `video_color_grade.py` (line 186), `video_proxy_gen.py` (lines 194-195), `video_format_export.py` (line 188)
- Impact: Long FFmpeg errors (complex filter chains, detailed codec warnings) are cut off. When troubleshooting, must manually re-run failed command to see full error.
- Fix approach: Log full stderr to file immediately, then truncate for console. Or concatenate first and last 250 chars to preserve context.

**Supabase query injection via string interpolation (MITIGATED)**
- Symptoms: None currently detected
- Files: `gdrive_upload.py` (lines 76-83), `archive_sync.py` (lines 75-82), `video_qa.py` (lines 85-89)
- Current mitigation: Query strings escape quotes with `.replace("'", "\\'")` before inclusion. However, this is manually done per-query and error-prone.
- Recommendation: Supabase Python client should support parameterized queries natively. Verify current version supports this and migrate away from string interpolation if possible. For now, keep escaping but add comment flagging each query as "manually escaped."

## Performance Bottlenecks

**Sequential video processing in a single script**
- Problem: `video_format_export.py` processes each format export sequentially (lines 250-276). For 5 formats on a 4K file, this means 5 serial FFmpeg invocations (could be 2-4 hours total on slow hardware).
- Files: `video_format_export.py`, particularly the loop at lines 250-276
- Cause: FFmpeg subprocess calls are not parallelized. Each format waits for the previous to complete.
- Improvement path: Use Python `concurrent.futures.ThreadPoolExecutor` (or `multiprocessing`) to spawn 2-4 FFmpeg processes in parallel. Requires careful management of output file naming and disk I/O. Estimated speedup: 2-3x on multi-core systems. Effort: 4-6 hours.

**Repeated ffprobe calls for the same file**
- Problem: `video_metadata.py` runs ffprobe twice per video: once on raw file (lines 258), once on graded file if it exists (lines 272). If graded version is run again, ffprobe is re-run even if file hasn't changed.
- Files: `video_metadata.py` (lines 253-273)
- Cause: No caching of probe results. Each invocation takes 1-2 seconds.
- Improvement path: Cache ffprobe results per mission by file path + modification time. Store in a mission-level `.probe_cache.json`. Estimated savings: 30-60 seconds per mission with many videos.

**Google Drive API quota exhaustion**
- Problem: `gdrive_upload.py` and `archive_sync.py` list folder contents without pagination limits checked or quota monitoring. Large delivery folders could trigger API quota errors.
- Files: `archive_sync.py` (lines 91-109), `gdrive_upload.py` (lines 66-99)
- Cause: No rate limiting or quota check before API calls.
- Improvement path: Add quota tracking; log remaining quota after each operation; add exponential backoff for 403 (quota) errors. Document daily API quota limits.

## Fragile Areas

**EXIF/XMP metadata extraction for platform detection**
- Files: `platform_detect.py` (entire file, ~400 lines)
- Why fragile: Depends on `pyexiftool` (external library wrapping command-line `exiftool` binary). If binary is missing or version changes, EXIF detection silently fails and falls back to filename-only detection. M4E vs M3E distinction is lost.
- Safe modification: (1) Always test with `detect_platform_exif()` before relying on result. (2) Log confidence level ("confirmed" vs "likely" vs "unavailable"). (3) Have fallback behavior for when EXIF is unavailable (current code does this).
- Test coverage: No automated tests exist. Manual testing with actual M4E and M3E files needed to verify detections.

**Supabase connection and transaction handling**
- Files: All scripts with Supabase client (`video_metadata.py`, `srt_telemetry_parser.py`, `video_qa.py`, `video_format_export.py`)
- Why fragile: No connection pooling, no transaction rollback, no retry logic. If Supabase is down during mission processing, entire script fails. If a partial insert fails (e.g., out of range value), there's no cleanup or compensation.
- Safe modification: Always wrap Supabase calls in try/except with specific error handling. Log connection errors before exiting. Consider adding `tenacity` library for automatic retries on transient failures.
- Test coverage: No automated tests. Supabase integration tested manually only.

**FFmpeg command construction and execution**
- Files: `video_color_grade.py` (lines 85-110), `video_proxy_gen.py` (lines 79-104), `video_format_export.py` (lines 122-169)
- Why fragile: FFmpeg commands are built as Python lists and passed to `subprocess.run()` without shell=True (good). However, LUT paths and filenames are escaped manually in some places but not others. If a filename contains special chars (quotes, backslashes), encoding might fail unpredictably.
- Safe modification: Validate all paths before encoding. Use `pathlib.Path` for path manipulation to reduce manual escaping. Consider moving to `FFmpeg-Python` wrapper library for cleaner command construction.
- Test coverage: No unit tests for FFmpeg command generation. Only manual testing with known filenames.

**Webhook failure doesn't block mission completion**
- Files: `ingest_sorter.py` (lines 482-489), `folder_watcher.py` (lines 115-124)
- Why fragile: If n8n webhook is down, the log statement warns but mission continues. Downstream steps are never triggered. This can lead to incomplete processing that looks successful locally but fails silently in orchestration.
- Safe modification: Add `--webhook-required` flag to make webhook failures fatal when running in production mode. Default behavior (current) is acceptable for testing.
- Test coverage: No automated tests. Webhook integration tested manually only.

## Security Considerations

**Credentials in environment variables not validated**
- Risk: Scripts assume `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON` are correctly set. If missing or invalid, errors are caught late during first API call, not at startup.
- Files: `video_metadata.py` (lines 31-32), `srt_telemetry_parser.py` (lines 28-29), `video_qa.py` (lines 29-30), `gdrive_upload.py` (lines 44-63), `archive_sync.py` (lines 50-66)
- Current mitigation: Scripts raise explicit errors if credentials are missing (e.g., line 54-55 in gdrive_upload.py). This is acceptable but inconsistent across scripts.
- Recommendations: (1) Add a shared `validate_credentials()` function that all scripts call at startup. (2) Never log credential values. (3) Document all required env vars in README.

**Google Drive sharing link creation is unrestricted**
- Risk: `create_shareable_link()` (gdrive_upload.py lines 137-146) makes files readable by "anyone with the link" without expiration. If a link is leaked, the delivery is readable indefinitely.
- Files: `gdrive_upload.py` (lines 137-146)
- Current mitigation: None. Links are permanent until manually revoked.
- Recommendations: (1) Add optional `--no-share` flag (already exists, line 184). (2) Consider adding optional password protection via Drive API v3 (not natively supported; workaround is client-side). (3) Document that links should be revoked after customer downloads. (4) Log all shared file IDs to audit log.

**Local filesystem permissions not enforced**
- Risk: All mission files are written to `E:\Sentinel\Incoming\` and `E:\Sentinel\Output\` with default Windows permissions. If the script runs as a non-admin user, permission errors are possible. If it runs as admin, output is owned by admin (privileged escalation risk if edited later).
- Files: All file I/O operations across all 14 scripts
- Current mitigation: None. Scripts assume they have write access.
- Recommendations: (1) Document required Windows permissions for the script service account. (2) Run folder_watcher as a Windows service with minimal privileges. (3) Set explicit ACLs on output directories in setup script.

## Scaling Limits

**Archive sync downloads all Delivered files every run**
- Current capacity: Designed for ~100-200 GB per month of deliveries
- Limit: If Delivered folder grows beyond 1-2 TB without cleanup, `list_files_in_folder()` (archive_sync.py line 91-109) will time out or hit API pagination limits. Each download is sequential.
- Scaling path: (1) Implement incremental sync using Drive file creation timestamps (already recorded in `createdTime`). (2) Parallelize downloads using `concurrent.futures`. (3) Add checkpoint to skip already-archived files by Drive file ID, not just size matching. Estimated work: 8 hours.

**Video processing pipeline single-machine bound**
- Current capacity: ~200-300 GB of raw video per week per machine
- Limit: All video processing (grading, proxy gen, format export) happens on a single rig. If multiple drone teams fly simultaneously, ingest exceeds processing capacity.
- Scaling path: Deploy n8n as true distributed workflow with multiple worker nodes. Each script would run on a dedicated worker with GPU acceleration for FFmpeg. Requires n8n enterprise or self-hosted scaling. Estimated work: 40-60 hours (DevOps, not script changes).

**Database row limits not documented**
- Current capacity: Supabase free tier supports ~1M rows per month
- Limit: Each video clip creates 1 video_assets row. With 50 clips/mission and 20 missions/month, that's 1,000 rows/month (well within limits). However, if telemetry is sampled (every frame = 900 frames at 30fps per 30-sec clip), this explodes to millions of rows.
- Scaling path: (1) Document current sampling strategy (aggregate per-clip, not per-frame). (2) Add option to store frame-level telemetry in separate table with sampling interval. (3) Implement data retention policy (archive old missions to cold storage).

## Test Coverage Gaps

**No unit tests for any script**
- What's not tested: Command-line argument parsing, file operations (find, copy, rename), Supabase upsert logic, FFmpeg error handling, webhook retries, etc.
- Files: All 14 scripts have zero unit test coverage
- Risk: Refactoring is dangerous. Changes to core logic (e.g., filename patterns, error handling) could silently break downstream steps.
- Priority: High. Recommended approach:
  1. Start with `test_ingest_sorter.py`: Unit test for `sort_by_sequence_ranges()`, `validate_timestamp_gaps()`, `extract_sequence_number()` (math functions that don't depend on I/O).
  2. Add `test_video_metadata.py`: Unit test for `probe_video()` mock, `normalize_codec()`.
  3. Add `test_delivery_packaging.py`: Unit test for `sanitize_address()`, `rename_photo()`, `rename_video_export()` (pure functions).
  4. Integration tests for full mission processing pipeline against a test Supabase project.
- Estimated effort: 40-60 hours total (10-15 per major module).

**No integration tests with Supabase**
- What's not tested: Upsert logic in `video_metadata.py`, `srt_telemetry_parser.py`, `video_qa.py` when records already exist or have conflicting data.
- Risk: Duplicate data insertion, silent updates that clobber fields, race conditions if mission is processed twice concurrently.
- Priority: Medium. Recommended approach: Use Supabase test environment or Docker Postgres with schema recreation. Mock service key for CI/CD. Estimated effort: 20-30 hours.

**No tests for FFmpeg command injection**
- What's not tested: Whether filenames with special chars (quotes, backticks, `$()`, etc.) are properly escaped before passing to `subprocess.run()`.
- Risk: Command injection if a filename is crafted maliciously. Low risk in practice (files come from DJI cameras), but security best practice requires testing.
- Priority: Low. Recommended approach: Unit test with sample malicious filenames. Estimated effort: 4-6 hours.

**No e2e tests for full pipeline**
- What's not tested: Entire workflow from ingest through delivery. Does a mission successfully round-trip through all 7 steps?
- Risk: Unknown until production deployment. Breaking changes can go unnoticed if one intermediate step fails.
- Priority: Medium. Recommended approach: Create a synthetic mission folder (10 small test videos, 20 test photos) and run through full pipeline. Automated CI/CD job weekly. Estimated effort: 12-16 hours.

---

*Concerns audit: 2026-02-23*
