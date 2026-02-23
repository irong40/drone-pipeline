# Codebase Structure

**Analysis Date:** 2026-02-23

## Directory Layout

```
C:\Users\redle\drone-pipeline\
├── ingest_sorter.py           # SD card ingest, file sorting by mission/sequence
├── platform_detect.py         # Drone platform detection (Mini 4 Pro vs M4E vs M3E)
├── folder_watcher.py          # Folder monitoring + debounce webhook firing
├── folder_watcher_service.py  # Windows service wrapper for folder_watcher.py
├── video_color_grade.py       # V1: Apply LUT color grading
├── video_metadata.py          # V1.5: Extract ffprobe metadata to Supabase
├── srt_telemetry_parser.py    # V2: Parse DJI SRT telemetry files
├── video_qa.py                # V3: Telemetry-based QA checks
├── video_proxy_gen.py         # V4: Generate 1080p editing proxies
├── video_format_export.py     # V6: Batch encode to delivery formats
├── delivery_packaging.py       # V7 + Delivery: Package into client ZIP
├── gdrive_upload.py           # Upload delivery ZIP to Google Drive
├── archive_sync.py            # Weekly archive sync (Drive → cold storage)
├── requirements.txt           # Python dependencies
├── README.md                  # Pipeline documentation
├── .planning/
│   └── codebase/
│       ├── ARCHITECTURE.md    # (This file) Pipeline architecture
│       └── STRUCTURE.md       # (This file) Directory and code organization
└── (other directories created at runtime)
    ├── E:\Sentinel\Incoming\SAI_M{nnnn}_{package}_{date}\  # Mission folders
    ├── E:\Sentinel\logs\                                    # Log files
    ├── E:\Sentinel\Output\                                  # Delivery ZIPs
    ├── E:\Sentinel\LUTs\                                    # Color grading LUTs
    └── F:\Sentinel_Archive\                                 # Cold storage archive
```

## Directory Purposes

**Repository Root (`C:\Users\redle\drone-pipeline\`):**
- Purpose: Pipeline script collection and entry points
- Contains: 14 Python scripts, config files, requirements
- Key files: `ingest_sorter.py` (primary entry), `README.md` (usage docs)

**Mission Processing Folders (Disk Structure, not in repo):**

```
E:\Sentinel\Incoming\SAI_M0047_RE_Standard_20260218\
├── photos/
│   ├── raw/           # DNG files from SD card (ingest creates, never modified)
│   └── jpeg/          # JPEG sidecar files (ingest creates, used for EXIF detection)
├── video/
│   ├── full/          # Raw MP4/MOV clips (ingest input for V1)
│   ├── graded/        # Color-graded MP4s (V1 output, V4/V6 input)
│   ├── proxy/         # 1080p editing proxies (V4 output, editor input for V5)
│   ├── telemetry/     # DJI SRT files (ingest creates, V2 input)
│   ├── master/        # Manual editor output (V5 creates via DaVinci Resolve)
│   └── exports/       # Format-encoded videos (V6 output, V7 input)
└── ppk/               # Post-processing kinematic files (RTK data, M4E/M3E only)
```

**Logs (`E:\Sentinel\logs\`):**
- `ingest_sorter.log` — File sorting, sequence assignment, webhook fires
- `folder_watcher.log` — Folder monitoring, debounce events
- `video_color_grade.log` — LUT application progress
- `video_metadata.log` — ffprobe metadata extraction
- `video_qa.log` — QA check results
- `gdrive_upload.log` — Drive upload status
- `archive_sync.log` — Archive sync operations

**Output (`E:\Sentinel\Output\`):**
- `Sentinel_{address}_{city}_{date}.zip` — Final client delivery packages

**Color Grading LUTs (`E:\Sentinel\LUTs\`):**
- `Sentinel_DLogM.cube` — For M4E/M3E drones (D-Log M profile)
- `Sentinel_DCinelike.cube` — For Mini 4 Pro (D-Cinelike profile)

**Archive (`F:\Sentinel_Archive\`):**
- Cold storage copy of delivered files for long-term retention

## Key File Locations

**Entry Points:**

- `ingest_sorter.py`: Primary manual ingest script; reads SD card, creates mission folders, fires webhook
  - Usage: `python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json [--webhook]`
  - Key functions: `scan_sd_card()`, `sort_by_sequence_ranges()`, `create_mission_structure()`, `fire_webhook()`

- `folder_watcher.py`: Automated folder monitoring service; runs continuously, fires webhook when folder stabilizes
  - Usage: `python folder_watcher.py [--watch-dir E:\Sentinel\Incoming] [--debounce 60]`
  - Key functions: `MissionFolderHandler._on_debounce_complete()`, `fire_webhook()`, `build_inventory()`

- `platform_detect.py`: Standalone tool to identify drone platform; used by other scripts
  - Usage: `python platform_detect.py E:/DCIM/DJI_001` or `python platform_detect.py path/to/photo.JPG`
  - Key functions: `detect_platform_from_folder()`, `detect_platform_exif()`, `detect_platform_ffprobe()`

**Configuration:**

- `requirements.txt`: Lists all Python package dependencies
  - Core: Pillow, pyexiftool, requests, watchdog
  - Cloud: supabase, google-api-python-client, google-auth
  - Windows: pywin32 (for service wrapper)
  - External: FFmpeg, ffprobe, ExifTool (installed separately, not via pip)

**Core Logic (Pipeline Steps V1-V7):**

- `video_color_grade.py` (V1): Applies LUT to raw video
  - Config: `PLATFORM_LUTS` (line 29), `CRF_QUALITY = 18`, `VIDEO_CODEC = "libx264"`
  - Key functions: `find_videos()`, `get_lut_path()`, `grade_video()`

- `video_metadata.py` (V1.5): Extracts and stores video metadata
  - Config: `PLATFORM_COLOR_PROFILES` (line 37), `FFPROBE_BIN`
  - Key functions: `probe_video()`, `upload_to_supabase()`, `build_metadata_records()`

- `srt_telemetry_parser.py` (V2): Parses DJI SRT telemetry
  - Config: Regex patterns for GPS, ISO, shutter, aperture (lines 36-50)
  - Key functions: `parse_srt_file()`, `parse_gps()`, `compute_frame_distance()`, `upload_to_supabase()`

- `video_qa.py` (V3): Quality assurance checks via telemetry
  - Config: `DEFAULT_THRESHOLDS` (line 32) — ISO ceiling, altitude rate, GPS drift, min FPS
  - Key functions: `fetch_video_assets()`, `check_iso_noise()`, `check_altitude_stability()`, `check_gps_drift()`

- `video_proxy_gen.py` (V4): Generates 1080p editing proxies
  - Config: `PROXY_RESOLUTION = "1920x1080"`, `PROXY_CRF = 23`, `PROXY_PRESET = "fast"`
  - Key functions: `find_source_videos()`, `generate_proxy()`

- `video_format_export.py` (V6): Batch encodes to delivery formats
  - Config: `DEFAULT_FORMATS` (line 33) — Instagram Reels, YouTube, TikTok, client 4K, web preview
  - Key functions: `fetch_video_formats()`, `encode_video()`, `truncate_duration()`

- `delivery_packaging.py` (V7 + Delivery): Creates client-facing ZIP
  - Config: `FORMAT_LABELS` (line 41), `MAPPING_EXTENSIONS`, `REPORT_EXTENSIONS`
  - Key functions: `sanitize_address()`, `build_prefix()`, `collect_mission_outputs()`, `create_delivery_zip()`

**Testing:**

- Not detected — No unit tests or integration test suite present
- Manual testing approach: run scripts individually on test missions, inspect outputs and logs

**Utilities & Modules:**

- `platform_detect.py` is reusable module
  - Imported by `ingest_sorter.py` (line 112): `from platform_detect import detect_platform_from_folder`
  - Also usable as CLI tool: `python platform_detect.py <path>`

## Naming Conventions

**Files:**

- Script files: `{description}_{step_if_numbered}.py` or `{tool}_{action}.py`
  - Examples: `video_color_grade.py` (V1), `srt_telemetry_parser.py` (V2), `gdrive_upload.py`
  - Convention: lowercase with underscores, descriptive name + step number

- Log files: `{script_name}.log`
  - Location: `E:\Sentinel\logs\`
  - Examples: `ingest_sorter.log`, `folder_watcher.log`, `video_qa.log`

- Mission folders: `SAI_M{nnnn}_{package}_{date}`
  - Examples: `SAI_M0047_RE_Standard_20260218`, `SAI_M0001_photogrammetry_20260215`
  - Pattern: SAI (Sentinel Aerial Inspections) + M (mission) + 4-digit zero-padded number + package type + YYYYMMDD date

- Delivery ZIPs: `Sentinel_{address}_{city}_{date}.zip`
  - Example: `Sentinel_123_Main_St_Virginia_Beach_20260218.zip`
  - Pattern: Sentinel + property address + city + date, all underscores, no spaces

## Directories

**Files:**

- Python scripts: camelCase function names (detect_platform_exif, build_mission_folder_name)
- Private functions: prefixed with `_` (e.g., `_reset_timer`, `_on_debounce_complete`)
- Classes: PascalCase (MissionFolderHandler)
- Constants: UPPER_CASE (FFMPEG_BIN, CRF_QUALITY, FILE_ROUTING)

**Functions:**

- Short parameter names for clarity: source_path, mission_path, mission_config, dest_dir
- Return types: dicts (mission info), lists (files), bool (success/failure), None (void ops)
- Logging statements consistent: log.info(), log.warning(), log.error()

**Variables:**

- Timestamps: ISO format strings (datetime.utcnow().isoformat() + "Z")
- Paths: raw strings (r"E:\Sentinel\Incoming") or Path objects (pathlib.Path)
- Enums/mappings: dicts with string keys (FILE_ROUTING, PLATFORM_LUTS, PLATFORM_COLOR_PROFILES)

## Where to Add New Code

**New Processing Step (V8+):**
- Create: `video_{description}.py` or `{tool}_{action}.py`
- Template: Copy structure from existing step (e.g., `video_format_export.py`)
- Required sections:
  - Docstring with usage examples
  - CONFIG section with hardcoded defaults and env var overrides
  - setup_logging() function
  - Main processing function(s)
  - CLI argument parsing + main()
- Register in n8n workflow by adding webhook listener
- Location: Root of `C:\Users\redle\drone-pipeline\`
- Example: `video_thumbnail_gen.py` for frame extraction

**New Utility/Module:**
- Create: `{tool}_detect.py` or `{name}_utils.py`
- Design for reusability: export function(s) that can be imported by other scripts
- Also provide CLI interface via `if __name__ == "__main__"` block
- Location: Root of repo
- Example: `color_grading_utils.py` with LUT validation, preset management

**New Configuration Source:**
- Current: Hardcoded defaults + env vars + Supabase `processing_templates` table
- To add: Query Supabase at script startup, fall back to hardcoded defaults
- Pattern: See `video_qa.py` (lines 73-80) `fetch_thresholds()` + `DEFAULT_THRESHOLDS`
- Preferred over new config files to avoid file sync issues across processing machines

**New Command-Line Flag:**
- Add to argparse.ArgumentParser in main()
- Document in docstring usage examples
- Keep consistent with existing flags: `--dry-run`, `--upload`, `--webhook`, `--mission-id`
- Example: `--output-dir` for custom output location

**New External Integration:**
- Add package to `requirements.txt` with pinned version
- Create initialization function (e.g., `get_service()` for Google Drive)
- Wrap authentication logic with environment variable defaults
- Provide fallback or `--skip` flag if integration is optional
- Example: S3 upload as alternative to Google Drive

## Special Directories

**`.planning/codebase/` (Repository):**
- Purpose: GSD (Get Shit Done) codebase analysis documents
- Generated: No (manually maintained)
- Committed: Yes
- Contents:
  - `ARCHITECTURE.md` — Pipeline structure, layers, data flow, entry points
  - `STRUCTURE.md` — Directory layout, file locations, naming conventions (this file)

**`.claude/` (Repository):**
- Purpose: Claude Code context and configurations
- Generated: No (manually created)
- Committed: Yes (version control for Claude Code preferences)
- Contents: Project-specific skills, preferences, session handoff notes

**`.git/` (Repository):**
- Purpose: Git version control metadata
- Generated: Yes (git init)
- Committed: N/A (git internal)

**`__pycache__/` (Repository):**
- Purpose: Python bytecode cache
- Generated: Yes (Python runtime)
- Committed: No (.gitignore should exclude)

**`E:\Sentinel\Incoming\` (Disk Structure):**
- Purpose: Working directory for in-progress missions
- Generated: Yes (ingest_sorter.py creates SAI_M* folders)
- Committed: No (not in repo, local disk only)
- Lifecycle: Persists throughout pipeline; cleaned up after archival

**`E:\Sentinel\logs\` (Disk Structure):**
- Purpose: Script execution logs
- Generated: Yes (each script appends to its .log file)
- Committed: No (local disk only)
- Lifecycle: Accumulates; humans manually clean up old logs

**`E:\Sentinel\Output\` (Disk Structure):**
- Purpose: Delivery ZIP staging
- Generated: Yes (delivery_packaging.py creates ZIPs)
- Committed: No (local disk only)
- Lifecycle: ZIPs moved to Google Drive after upload, then to archive

**`E:\Sentinel\LUTs\` (Disk Structure):**
- Purpose: Color grading lookup tables
- Generated: No (manually created by colorist or imported from DJI)
- Committed: No (shared across systems, not in repo)
- Ownership: Design/colorist maintains

**`F:\Sentinel_Archive\` (Disk Structure):**
- Purpose: Cold storage backup
- Generated: Yes (archive_sync.py copies from Drive)
- Committed: No (external archive drive)
- Lifecycle: Permanent retention for client deliverables

---

*Structure analysis: 2026-02-23*
