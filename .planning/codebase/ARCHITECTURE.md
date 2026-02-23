# Architecture

**Analysis Date:** 2026-02-23

## Pattern Overview

**Overall:** Sequential pipeline with event-driven initiation

The drone pipeline is a strictly sequential, single-mission processing workflow. Each script performs a specific transformation step and passes control to the next. The pipeline is initiated either manually or automatically via n8n webhooks from folder watcher events.

**Key Characteristics:**
- Linear transformation pipeline: raw files → structured processing → client delivery
- Event-driven at entry points: file system monitoring triggers webhook fires
- File system as state machine: folder structure and subdirectories indicate pipeline progress
- Stateful processing: Supabase database augments folder state with flight telemetry, QA checks, format configs
- Disk-intensive: operates on large video/photo files (multi-GB missions)
- Multi-platform abstraction: handles Mini 4 Pro, Matrice 4E, Mavic 3 Enterprise via platform detection

## Layers

**Ingest Layer:**
- Purpose: Capture raw media from SD cards, organize into mission-specific structures, detect drone platform
- Location: `ingest_sorter.py`, `platform_detect.py`, `folder_watcher.py`, `folder_watcher_service.py`
- Contains: File scanning, sequence-range assignment, EXIF/ffprobe-based platform detection, filesystem monitoring
- Depends on: FFmpeg/ffprobe (for video metadata), pyexiftool (for photo EXIF), watchdog (for file system events)
- Used by: Pipeline orchestrator (n8n) via webhooks

**Video Processing Layer:**
- Purpose: Transform raw video clips through color grading, quality analysis, proxy generation, and format export
- Location: `video_color_grade.py`, `video_metadata.py`, `video_qa.py`, `video_proxy_gen.py`, `video_format_export.py`
- Contains: LUT application, ffprobe metadata extraction, telemetry-based QA checks, 1080p proxy generation, platform-aware format encoding
- Depends on: FFmpeg/ffprobe, Supabase database (for telemetry storage and QA thresholds), drone platform identification
- Used by: Manual editing workflow (proxies for DaVinci Resolve), delivery packaging

**Telemetry Layer:**
- Purpose: Extract and store flight data from DJI SRT subtitle files for QA and archival
- Location: `srt_telemetry_parser.py`
- Contains: SRT frame parsing, GPS/altitude/ISO/shutter extraction, per-clip telemetry aggregation
- Depends on: Supabase `video_assets` and `telemetry_frames` tables
- Used by: Video QA layer, reports and historical analysis

**Delivery Layer:**
- Purpose: Package processed files into client-facing ZIPs with standardized naming, upload to Google Drive, archive to cold storage
- Location: `delivery_packaging.py`, `gdrive_upload.py`, `archive_sync.py`
- Contains: ZIP creation with property address naming, Google Drive folder structure management, Drive-to-local archive sync with cleanup
- Depends on: Google Drive API (service account auth), local file system (archive drive), mission metadata (address, city)
- Used by: Client delivery, long-term archival

## Data Flow

**Primary Flow: Raw SD Card → Delivery ZIP**

1. **Ingest (manual or watcher-triggered)**
   - `ingest_sorter.py`: Reads missions config JSON, scans SD card for DJI files, assigns sequences to missions via range matching
   - Validates timestamp gaps between files (M4E/M3E only)
   - Creates `SAI_M{nnnn}_{package}_{date}/` folder structure with subfolders: `photos/raw`, `photos/jpeg`, `video/full`, `video/proxy`, `video/telemetry`, `ppk`
   - Copies files to mission folder, maintaining file type routing (DNG→photos/raw, JPG→photos/jpeg, MP4→video/full, SRT→video/telemetry, etc.)
   - Fires n8n webhook with mission inventory (photo count, video count, PPK present)

2. **Platform Detection (embedded in ingest, standalone in video scripts)**
   - `platform_detect.py`: Detects drone via EXIF Model tag (photos) or ffprobe metadata (video)
   - Maps DJI internal model codes (FC9100=M4E, FC8482=M3E, FC8282=Mini 4 Pro) to pipeline IDs
   - Resolves M4E vs M3E ambiguity that filename patterns alone cannot

3. **Color Grading (V1)**
   - `video_color_grade.py`: Reads raw MP4s from `video/full/`, applies LUT via FFmpeg
   - Platform-aware LUT selection: M4E/M3E use `Sentinel_DLogM.cube`, Mini 4 Pro uses `Sentinel_DCinelike.cube`
   - Outputs graded clips to `video/graded/` (CRF 18, visually lossless H.264)

4. **Video Metadata Extraction (V1.5)**
   - `video_metadata.py`: Runs ffprobe on raw and graded clips
   - Extracts: resolution, codec, FPS, duration, file size, color profile
   - Writes to Supabase `video_assets` table (columns: resolution, codec, file_size_bytes, color_profile, has_lrf_proxy, graded_path)
   - Can run before or after SRT parsing; updates existing records by mission_id + filename match

5. **SRT Telemetry Parsing (V2)**
   - `srt_telemetry_parser.py`: Reads SRT files from `video/telemetry/`
   - Parses per-frame data at ~30fps: GPS coords, altitude, ISO, shutter speed, aperture, color temperature, distance
   - Aggregates per-clip stats (avg GPS drift, max altitude change rate, ISO range)
   - Writes clip records to `video_assets`, frame records to `telemetry_frames`

6. **Video QA (V3)**
   - `video_qa.py`: Fetches video_assets from Supabase, applies threshold checks
   - Thresholds from `processing_templates.video_qa_thresholds`: ISO ceiling (800), altitude change rate (10 ft/s), GPS drift (5m), min FPS (29)
   - Updates `qa_status` (pass/warn/fail) and `qa_flags` JSON array
   - Blocks downstream steps if QA fails

7. **Proxy Generation (V4)**
   - `video_proxy_gen.py`: Generates 1080p editing proxies from graded clips
   - Reads from `video/graded/` (preferred) or `video/full/` (fallback)
   - Outputs to `video/proxy/` with CRF 23, preset fast (for editing speed)
   - LRF files from camera are replaced by these FFmpeg proxies

8. **Manual Edit (V5) — External**
   - Editor uses DaVinci Resolve with `video/proxy/` files
   - Saves master edit to `video/master/` (single concatenated timeline or VFX project export)

9. **Format Export (V6)**
   - `video_format_export.py`: Reads master edit from `video/master/`
   - Queries Supabase `processing_templates.video_formats` for platform configs (Instagram Reels, YouTube, TikTok, client 4K, web)
   - Encodes to multiple resolutions/codecs with duration truncation (Reels: 90s max, TikTok: 180s max)
   - Outputs to `video/exports/{format_name}.mp4`

10. **Delivery Packaging (V7)**
    - `delivery_packaging.py`: Collects output files from processed mission
    - Transforms internal naming (SAI_MNNNN) to property-address naming (Sentinel_123_Main_St_Virginia_Beach)
    - Creates client ZIP with structure:
      ```
      Sentinel_123_Main_St_Virginia_Beach_20260218/
        photos/          (JPEG files from photos/jpeg/)
        video/           (format exports from video/exports/)
        mapping/         (if present, from photogrammetry outputs)
        reports/         (if present)
      ```
    - Supports two-stage delivery: `--photos-only` (before video edit) + `--video-addendum` (after edit)
    - Outputs to `E:\Sentinel\Output\{zip_name}.zip`

11. **Google Drive Upload (Delivery)**
    - `gdrive_upload.py`: POSTs delivery ZIP to Drive
    - Authenticates via service account (GOOGLE_SERVICE_ACCOUNT_JSON path)
    - Uploads to `Sentinel_Deliveries/Active/` folder
    - Can move to `Sentinel_Deliveries/Delivered/` if `--move-to-delivered` flag set

12. **Archive Sync (Maintenance)**
    - `archive_sync.py`: Weekly task
    - Downloads files from Drive `Sentinel_Deliveries/Delivered/`
    - Syncs to cold storage (F:\Sentinel_Archive)
    - Deletes from Drive after CLEANUP_DAYS (default 30 days) to manage quota

**State Management:**

Mission state is tracked via three mechanisms:

1. **Folder structure progression**: Presence of subfolders (`video/graded/`, `video/proxy/`, `video/exports/`, `video/master/`) signals completion of pipeline steps
2. **Supabase database**:
   - `missions` table: mission_id, package_type, status
   - `video_assets` table: clip metadata, telemetry aggregates, QA status
   - `telemetry_frames` table: per-frame GPS/altitude/ISO data
   - `processing_templates` table: LUT paths, QA thresholds, video format configs
3. **Log files**: Pipeline steps log to `E:\Sentinel\logs\{script_name}.log` for debugging and audit trail

## Key Abstractions

**Platform Abstraction:**
- Purpose: Handle three drone platforms (Mini 4 Pro, M4E, M3E) with different file patterns, EXIF metadata, and processing needs
- Examples: `platform_detect.py` (core), used by `ingest_sorter.py`, `video_color_grade.py`, `video_metadata.py`
- Pattern: Detect once at ingest, store in Supabase `missions.platform` or infer from video metadata; scripts query this to select LUTs, color profiles, thresholds

**Mission Folder Structure:**
- Purpose: Standardize mission layout across all processing steps
- Examples: `ingest_sorter.py` creates `SAI_M{nnnn}_{package}_{date}/` with fixed subfolders
- Pattern: All downstream scripts navigate via `mission_path/video/full/`, `mission_path/video/graded/`, etc.; no hardcoded paths beyond `E:\Sentinel\Incoming\`

**Webhook-Driven Orchestration:**
- Purpose: Decouple ingest and processing from n8n workflow engine
- Examples: `ingest_sorter.py` and `folder_watcher.py` fire HTTP POST to `N8N_WEBHOOK_URL`
- Pattern: Payload includes mission_id, inventory counts, platform; n8n routes to next processing step based on workflow logic

**Supabase-Backed Configuration:**
- Purpose: Centralize QA thresholds, video formats, LUT paths without modifying scripts
- Examples: `processing_templates` table supplies QA thresholds to `video_qa.py`, format specs to `video_format_export.py`
- Pattern: Scripts query Supabase on startup; fallback to hardcoded defaults if DB unavailable (e.g., `DEFAULT_FORMATS` in `video_format_export.py`)

**Telemetry Aggregation:**
- Purpose: Convert per-frame SRT data into clip-level QA metrics
- Examples: `srt_telemetry_parser.py` reads 30fps frames, computes avg GPS drift, max altitude change rate; stores in `video_assets`
- Pattern: QA layer consumes aggregated stats, not raw frames (for performance)

## Entry Points

**Manual Ingest:**
- Location: Command-line invocation of `ingest_sorter.py`
- Triggers: Human copies files from SD card, runs `python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json`
- Responsibilities: Parse missions config, scan SD card, sort files into mission folders, fire webhook if `--webhook` flag set

**Automated Folder Watcher:**
- Location: `folder_watcher.py` as Windows service (or standalone daemon)
- Triggers: Monitors `E:\Sentinel\Incoming\` for new SAI_M* folders using watchdog
- Responsibilities: Debounce file writes (60s default), count inventory, fire webhook when folder stabilizes

**Video Processing Scripts (V1-V6):**
- Location: Command-line invocation or n8n workflow nodes
- Triggers: Human runs script or n8n calls script via subprocess after webhook
- Responsibilities: Each script is self-contained; reads from mission folder, applies transformation, writes outputs, optionally updates Supabase

**Delivery Packaging:**
- Location: Command-line invocation of `delivery_packaging.py`
- Triggers: Human runs after video edit is saved to `video/master/`
- Responsibilities: Collect outputs, rename with property address, create client ZIP

**Google Drive Upload:**
- Location: Command-line invocation of `gdrive_upload.py`
- Triggers: Human runs after delivery packaging completes
- Responsibilities: Authenticate with service account, POST ZIP to Drive, move to Delivered folder if flagged

**Archive Sync:**
- Location: Windows Task Scheduler (cron-like) calling `python archive_sync.py`
- Triggers: Weekly schedule (Sunday night)
- Responsibilities: Sync Drive Delivered folder to local archive, clean up aged files from Drive

## Error Handling

**Strategy:** Graceful degradation with logging and optional webhook skip

**Patterns:**

1. **File Operation Errors (copy, write, probe):**
   - Catch: OSError, IOError, subprocess.TimeoutExpired
   - Action: Log error, skip file or mission, continue with remaining items
   - Example: `ingest_sorter.py` lines 291-295 catch copy failures, increment failed counter, skip webhook if any copies failed
   - Implication: Pipeline does not halt on individual file failures; human must review logs and manually retry

2. **Platform Detection Failures:**
   - Fallback chain: EXIF → ffprobe metadata → filename pattern → default (mini4pro)
   - Example: `ingest_sorter.py` lines 410-418 try EXIF-based detection first, fall back to filename if unavailable
   - Risk: Incorrect platform selection leads to wrong LUT or color profile downstream; log messages indicate confidence level

3. **Supabase Connection Failures:**
   - Catch: ImportError (missing supabase library), ValueError (missing env vars), network errors
   - Action: Log warning, use hardcoded fallbacks (e.g., DEFAULT_FORMATS in `video_format_export.py`)
   - Example: `srt_telemetry_parser.py` can dump JSON locally without Supabase via `--dump-json` flag
   - Implication: Partial pipeline completion possible; QA checks and format selection may be suboptimal

4. **FFmpeg/ffprobe Unavailable:**
   - Catch: FileNotFoundError, subprocess.TimeoutExpired
   - Action: Halt with clear error message: `Check that ffmpeg/ffprobe is installed and on PATH`
   - Example: `video_color_grade.py` line 25 assumes `ffmpeg` is on PATH; no fallback
   - Implication: Environment setup (FFmpeg installation) is critical prerequisite

5. **Validation Errors:**
   - Input validation in ingest: Check missions config JSON format, validate date YYYYMMDD, check filename patterns
   - Example: `ingest_sorter.py` lines 389-398 validate all missions have required keys, correct date format, alphanumeric package_type
   - Action: Exit with sys.exit(message) before processing
   - Implication: Bad config blocks entire ingest; human must fix and retry

## Cross-Cutting Concerns

**Logging:** Each script configures its own logger with both file and console handlers, logging to `E:\Sentinel\logs\{script_name}.log`
- Format: `"%(asctime)s [%(levelname)s] %(message)s"`
- Levels: INFO for normal flow, WARNING for recoverable issues, ERROR for failures
- Note: No structured logging (JSON); simple text format for human readability

**Validation:** Input paths, missions config JSON, file extensions, missions folder naming (SAI_M pattern), filename patterns (DJI_)
- Performed early in pipeline (ingest layer) to prevent corrupt state downstream
- Example: `copy_file_to_mission()` (line 278 in `ingest_sorter.py`) validates path doesn't escape mission directory via startswith() check

**Authentication:** Google Drive (service account JSON), Supabase (environment variables SUPABASE_URL + SUPABASE_SERVICE_KEY)
- Service account credentials loaded from file path via GOOGLE_SERVICE_ACCOUNT_JSON env var
- Supabase keys must be set before script execution; no prompt for missing keys
- No token refresh logic; service account tokens assumed valid (short-lived refresh handled by google-auth library)

**Platform-Awareness:** Mini 4 Pro, M4E, M3E detected once at ingest, percolates through pipeline
- Drives LUT selection (PLATFORM_LUTS in `video_color_grade.py`), color profile expectation (PLATFORM_COLOR_PROFILES in `video_metadata.py`)
- Encoded in Supabase `missions.platform` or inferred from EXIF/ffprobe at each step if needed
- Filename patterns differ (Mini 4 Pro: DJI_NNNN.EXT vs M4E/M3E: DJI_YYYYMMDDHHMMSS_NNNN_X.EXT)

**File Routing:** File type → folder mapping centralized in `FILE_ROUTING` dict (ingest_sorter.py line 45)
- DNG→photos/raw, JPG→photos/jpeg, MP4→video/full, SRT→video/telemetry, LRF→video/proxy, PPK files→ppk
- Ensures consistent structure; new file types can be added by updating dict without changing logic

---

*Architecture analysis: 2026-02-23*
