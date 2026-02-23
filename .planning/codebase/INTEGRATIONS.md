# External Integrations

**Analysis Date:** 2026-02-23

## APIs & External Services

**n8n Workflow Automation:**
- n8n (self-hosted) - Orchestration engine
  - Webhook: POST `http://localhost:5678/webhook/folder-watcher` (mission folder ready notification from `folder_watcher.py` and `ingest_sorter.py`)
  - Webhook: POST `http://localhost:5678/webhook/ingest` (mission folder ready notification from `ingest_sorter.py`)
  - Auth: None (webhook token in URL)
  - Payload: JSON with mission metadata (mission_id, mission_number, photo_count, video_count, total_size_bytes, has_ppk)

## Data Storage

**Databases:**
- Supabase (PostgreSQL)
  - Project: `qjpujskwqaehxnqypxzu` (shared with all Faith & Harmony products)
  - Connection: `SUPABASE_URL` environment variable
  - Auth: Service role API key in `SUPABASE_SERVICE_KEY` environment variable
  - Client: `supabase` Python package (create_client from `supabase` library)
  - Tables used:
    - `missions` - Mission metadata (package_type, drone_platform) read by `video_qa.py`, `video_metadata.py`, `video_format_export.py`
    - `video_assets` - Per-clip metadata (resolution, codec, color_profile, graded_path) written by `video_metadata.py`, updated by `video_qa.py`, `video_format_export.py`
    - `processing_templates` - Video QA thresholds and format export specs (iso_ceiling, altitude_change_rate, video_formats) read by `video_qa.py`, `video_format_export.py`
    - `drone_jobs` (legacy alias for missions) - Historical reference in codebase

**File Storage:**
- Local filesystem only
  - Ingest: `E:\Sentinel\Incoming\` (mounted via Windows Explorer or SD card reader)
  - Processing: Mission subfolders (photos/raw, photos/jpeg, video/full, video/proxy, video/telemetry, video/graded, video/master, video/exports, ppk)
  - Archive: `F:\Sentinel_Archive\` (cold storage)
  - Delivery packages: Temporary ZIP files before Google Drive upload
  - Color LUTs: `E:\Sentinel\LUTs\Sentinel_DLogM.cube`, `Sentinel_DCinelike.cube`

**Caching:**
- None detected

## Authentication & Identity

**Auth Provider:**
- Supabase service role authentication
  - Implementation: API key-based (service role, not user auth)
  - Used by: `srt_telemetry_parser.py`, `video_qa.py`, `video_format_export.py`
  - Credentials: `SUPABASE_SERVICE_KEY` environment variable

**Google Drive Authentication:**
- Google Cloud service account
  - Implementation: OAuth 2.0 via service account JSON credentials file
  - Used by: `gdrive_upload.py`, `archive_sync.py`
  - Credentials path: `GOOGLE_SERVICE_ACCOUNT_JSON` environment variable (file path)
  - Scopes: `https://www.googleapis.com/auth/drive` (full Drive access)

## Monitoring & Observability

**Error Tracking:**
- None detected - No external error tracking service integrated

**Logs:**
- File-based logging to `E:\Sentinel\logs\`:
  - `folder_watcher.log` - Filesystem monitoring events from `folder_watcher.py`
  - `ingest_sorter.log` - SD card ingest sorting from `ingest_sorter.py`
  - `archive_sync.log` - Archive synchronization from `archive_sync.py`
  - Each script configures logging via `logging.basicConfig()` with StreamHandler (stdout) + FileHandler (log file)

## CI/CD & Deployment

**Hosting:**
- On-premises Windows 11 processing rig (Sentinel Aerial Inspections facility)

**CI Pipeline:**
- None detected - No automated testing or CI/CD infrastructure

**Manual Orchestration:**
- n8n self-hosted workflows (external to pipeline, triggers via webhooks)
- Windows scheduled tasks (for `folder_watcher.py` background service, `archive_sync.py` weekly sync)
- Manual CLI invocation for video editing steps (V5 edit via DaVinci Resolve, not in pipeline)

## Environment Configuration

**Required env vars:**
- `SUPABASE_URL` - e.g., `https://qjpujskwqaehxnqypxzu.supabase.co`
- `SUPABASE_SERVICE_KEY` - Long service role API key from Supabase dashboard
- `N8N_WEBHOOK_URL` - e.g., `http://localhost:5678/webhook/folder-watcher` (optional if n8n not used)
- `GOOGLE_SERVICE_ACCOUNT_JSON` - Absolute file path to service account JSON (e.g., `C:\secrets\sentinel-sa.json`)

**Secrets location:**
- Google service account JSON: Stored outside repo (referenced via env var)
- Supabase keys: Stored outside repo (referenced via env var)
- Not committed to git (confirmed by absence in repository)

## Webhooks & Callbacks

**Incoming:**
- None detected - Pipeline scripts don't expose HTTP endpoints

**Outgoing:**
- n8n webhook POST from `folder_watcher.py`:
  - URL: `N8N_WEBHOOK_URL` environment variable (default `http://localhost:5678/webhook/folder-watcher`)
  - Trigger: New mission folder detected in `E:\Sentinel\Incoming\` after 60-second debounce
  - Payload JSON:
    ```json
    {
      "mission_folder": "SAI_M0047_RE_Standard_20260218",
      "mission_number": 47,
      "photo_count": 250,
      "video_count": 8,
      "has_ppk": true,
      "total_size_bytes": 145382400,
      "first_file_time": "2026-02-18T14:30:00Z",
      "last_file_time": "2026-02-18T15:45:30Z"
    }
    ```

- n8n webhook POST from `ingest_sorter.py`:
  - URL: `N8N_WEBHOOK_URL` environment variable (default `http://localhost:5678/webhook/ingest`)
  - Trigger: SD card files successfully sorted into mission folders
  - Payload JSON:
    ```json
    {
      "mission_id": "uuid",
      "mission_number": 47,
      "package_type": "re_standard",
      "sorted_folder": "SAI_M0047_RE_Standard_20260218",
      "files_moved": 258,
      "total_bytes": 145382400
    }
    ```

## External Binary Dependencies

**FFmpeg:**
- Used by: `video_color_grade.py`, `video_format_export.py`, `video_proxy_gen.py`, `video_metadata.py`
- Purpose: Video encoding, color grading with LUTs, format conversion, metadata extraction
- Invoked via: `subprocess.run([ffmpeg_bin, ...])` with custom arguments
- Installation: Manual (https://ffmpeg.org/download.html) must be on system PATH
- Version: Any recent version supporting libx264/libx265 codecs and -vf (filter graphs)

**ffprobe:**
- Used by: `video_metadata.py`, `platform_detect.py`, `video_format_export.py`
- Purpose: Non-destructive video metadata extraction (codec, resolution, duration, fps)
- Invoked via: `subprocess.run([ffprobe_bin, ...])` with JSON output format
- Installation: Bundled with FFmpeg, must be on system PATH
- Version: Same as FFmpeg

**ExifTool:**
- Used by: `platform_detect.py` (via pyexiftool)
- Purpose: XMP-drone-dji namespace extraction for M4E/M3E platform detection, photo EXIF reading
- Invoked via: `pyexiftool.ExifToolHelper()` (subprocess wrapper)
- Installation: Manual (https://exiftool.org/), must be on system PATH as `exiftool` command
- Version: Recent version with XMP support

## DJI Metadata Parsing

**SRT Telemetry Files:**
- Format: DJI subtitle format containing per-frame telemetry
- Parser: `srt_telemetry_parser.py` extracts GPS, altitude, ISO, shutter speed, aperture, color temperature
- Regex patterns: Supports both standard DJI format (`GPS (lat, lon, alt)`) and Mini 4 Pro bracket format (`[latitude: ...]`)
- Storage: Parsed data written to Supabase `video_assets` table

**EXIF Metadata:**
- Photos: DNG/JPG files from DJI drones contain EXIF Model tags
- Parser: `platform_detect.py` reads Model tag via Pillow fallback or pyexiftool (preferred)
- Model mappings: FC8282→mini4pro, FC9100→m4e, FC8482→m3e
- Purpose: Disambiguate M4E from M3E (same filename pattern)

**ffprobe Video Metadata:**
- Extracted: codec, resolution, fps, duration, color_space
- Parser: `video_metadata.py` calls ffprobe with JSON output
- Storage: Stored in Supabase `video_assets` table
- Used by: Video QA thresholds, format export scaling

---

*Integration audit: 2026-02-23*
