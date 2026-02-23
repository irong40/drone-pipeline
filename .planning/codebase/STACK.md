# Technology Stack

**Analysis Date:** 2026-02-23

## Languages

**Primary:**
- Python 3.8+ - All 12 pipeline scripts for post-flight processing workflow

## Runtime

**Environment:**
- CPython 3.8+ (Windows 11 targeting)
- subprocess shell execution for FFmpeg/ffprobe and ExifTool binaries

**Package Manager:**
- pip
- Lockfile: `requirements.txt` (present)

## Frameworks

**Core:**
- No framework; pure Python CLI scripts designed for orchestration via n8n and Windows service runners

**File Processing:**
- Pillow 10.0.0+ - EXIF extraction fallback for drone photos (`ingest.py`, `platform_detect.py`)
- pyexiftool 0.5.6+ - XMP-drone-dji namespace extraction for M4E/M3E platform disambiguation (`platform_detect.py`)

**Filesystem Monitoring:**
- watchdog 4.0.0+ - Filesystem event watching for SD card ingest triggering (`folder_watcher.py`)

**Windows Integration:**
- pywin32 306+ - Windows service management for `folder_watcher_service.py` (background daemon installation)

**Testing:**
- None detected - No test framework present

**Build/Dev:**
- None detected - No build system; scripts executed directly via `python script.py`

## Key Dependencies

**Critical:**
- requests 2.31.0+ - HTTP webhooks to n8n orchestrator from `ingest_sorter.py` and `folder_watcher.py`
- supabase 2.0.0+ - Metadata persistence (video_assets, missions, processing_templates) used in `srt_telemetry_parser.py`, `video_qa.py`, `video_format_export.py`
- google-api-python-client 2.100.0+ - Google Drive API for delivery uploads and archive syncing (`gdrive_upload.py`, `archive_sync.py`)
- google-auth 2.23.0+ - Service account credential handling for Drive API authentication

**Infrastructure:**
- FFmpeg (external binary) - Video encoding, color grading, format export; called via subprocess in `video_color_grade.py`, `video_format_export.py`, `video_proxy_gen.py`
- ffprobe (FFmpeg component) - Video metadata extraction (codec, resolution, duration) in `video_metadata.py`, `platform_detect.py`, `video_format_export.py`
- ExifTool (external binary) - EXIF/XMP photo metadata extraction; required for `pyexiftool` in `platform_detect.py`

## Configuration

**Environment:**
- Configuration via environment variables only:
  - `SUPABASE_URL` - Supabase project URL
  - `SUPABASE_SERVICE_KEY` - Supabase service role API key
  - `N8N_WEBHOOK_URL` - n8n webhook endpoint for orchestration triggers
  - `GOOGLE_SERVICE_ACCOUNT_JSON` - Path to Google service account JSON file (not contents)

- Hardcoded paths (Windows):
  - `E:\Sentinel\Incoming` - Mission ingest root
  - `E:\Sentinel\logs` - Log directory
  - `E:\Sentinel\LUTs` - Color LUT files directory
  - `F:\Sentinel_Archive` - Archive cold storage target

**Build:**
- No build configuration
- Dependencies declared in `requirements.txt` with version pinning
- External binaries (FFmpeg, ExifTool) must be installed manually and available on system PATH

## Platform Requirements

**Development:**
- Python 3.8+ installed
- FFmpeg + ffprobe on PATH (https://ffmpeg.org/download.html)
- ExifTool on PATH (https://exiftool.org/)
- Windows 10+ (for pywin32 service integration)
- pip package manager

**Production:**
- Sentinel Aerial Inspections processing rig (Windows 11 on-premises)
- Local storage: E:\ (incoming), F:\ (archive)
- Network access to:
  - Supabase API (`SUPABASE_URL`)
  - Google Drive API (OAuth2 via service account)
  - n8n self-hosted webhook endpoint (`N8N_WEBHOOK_URL`)
- DJI drone SD card reader on USB
- DaVinci Resolve (for manual video editing between V5 step - external to pipeline)

---

*Stack analysis: 2026-02-23*
