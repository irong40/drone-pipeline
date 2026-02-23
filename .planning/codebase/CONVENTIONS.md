# Coding Conventions

**Analysis Date:** 2026-02-23

## Naming Patterns

**Files:**
- Snake_case with underscores: `ingest_sorter.py`, `video_color_grade.py`, `srt_telemetry_parser.py`
- Functional names describing the processing step: `video_metadata.py`, `gdrive_upload.py`, `archive_sync.py`
- Platform/component-specific names: `platform_detect.py`, `folder_watcher.py`, `folder_watcher_service.py`

**Functions:**
- Snake_case throughout: `setup_logging()`, `scan_sd_card()`, `detect_platform()`, `parse_srt_frame()`, `build_mission_folder_name()`
- Descriptive names indicating purpose: `collect_metadata()`, `validate_timestamp_gaps()`, `check_iso()`, `upload_file()`
- Regex extraction functions prefixed with `extract_`: `extract_sequence_number()`, `extract_timestamp()`, `extract_metadata_text()`
- Boolean/check functions prefixed with `check_` or `is_`: `check_ffprobe()`, `check_ffmpeg()`, `check_lrf_proxy()`
- Detection functions prefixed with `detect_`: `detect_platform()`, `detect_platform_exif()`, `detect_from_exif()`, `detect_from_filename()`
- Setup/initialization functions: `setup_logging()`, `get_drive_service()`, `get_supabase_client()`

**Variables:**
- Snake_case: `mission_config`, `video_files`, `altitude_values`, `photo_count`, `file_size_bytes`
- Acronyms preserved in uppercase: `ISO`, `FPS`, `GPS`, `DNG`, `JPG`, `SRT`, `PPK`, `LUT`, `FFmpeg`, `EXIF`
- Plurals for collections: `files`, `missions_config`, `detections`, `warnings`, `metadata_list`
- Short but clear names for loops: `f` for file dicts, `m` for mission objects, `ext` for extensions

**Types/Classes:**
- Class names in PascalCase (where used): `MissionFolderHandler` (in `folder_watcher.py`)
- Constants in UPPER_CASE with underscores: `LOG_DIR`, `INCOMING_ROOT`, `FILE_ROUTING`, `MISSION_SUBFOLDERS`, `PLATFORM_LUTS`, `PLATFORM_COLOR_PROFILES`, `EXIF_MODEL_MAP`, `DEFAULT_THRESHOLDS`, `METERS_PER_DEG_LAT`

## Code Style

**Formatting:**
- No explicit linter/formatter configured — relies on Python conventions
- 4 spaces for indentation (standard Python)
- Line length appears flexible; lines range 60-150 characters
- Imports grouped naturally: stdlib → external packages → local modules

**Comments:**
- Section headers marked with `# ─── SECTION_NAME ───` style (using Unicode box-drawing characters)
- Sections clearly demarcate major functional areas: `# ─── CONFIG ───`, `# ─── LOGGING ───`, `# ─── FILE SCANNING ───`, `# ─── WEBHOOK ───`
- Docstrings used extensively for public functions and modules
- Module-level docstring at top: describes script purpose, usage examples, input format (e.g., missions.json structure)

**Module docstrings:**
```python
"""
Sentinel Aerial Inspections — [Script Title]

[Description of what this step does]

Usage:
    python script.py arg1 --flag value
    python script.py arg1 --flag value --dry-run
"""
```

**Function docstrings:**
- Brief description followed by implementation details where relevant
- Show input/output examples for complex functions
```python
def extract_sequence_number(filename):
    """Extract the sequence number from a DJI filename.

    Mini 4 Pro: DJI_0015.JPG → 15
    M4E/M3E:   DJI_20260218101500_0015_D.JPG → 15
    """
```

## Import Organization

**Order:**
1. Standard library: `os`, `sys`, `re`, `json`, `argparse`, `logging`, `subprocess`, `shutil`, `zipfile`, `glob`, `io`, `math`, `time`, `threading`
2. Third-party packages: `requests`, `exiftool`, `supabase`, `google.oauth2`, `googleapiclient`, `PIL`, `watchdog`
3. Local imports: `from platform_detect import detect_platform_from_folder`

**Path aliases:**
- No centralized path aliases — uses absolute paths or `os.path.join()` for path construction
- Windows paths stored as raw strings: `r"E:\Sentinel\Incoming"`, `r"F:\Sentinel_Archive"`
- Path resolution: `os.path.abspath()` converts user input to absolute paths
- Pathlib used selectively: `from pathlib import Path` for rglob scanning and parts extraction

**Environment variables:**
```python
# Config block pattern
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
LOG_DIR = r"E:\Sentinel\logs"
```

## Error Handling

**Patterns:**
- Early validation in main(): check paths, files, env vars exist
```python
if not os.path.isdir(source):
    sys.exit(f"Source folder not found: {source}")
```

- `sys.exit()` for fatal errors with message
- `try/except` with specific exception types:
```python
try:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
    return None
```

- Function-level failures return `None` or empty values (not raised):
```python
def probe_video(video_path):
    """Returns dict on success, None on failure."""
    try:
        result = subprocess.run(...)
        return parsed_data
    except:
        return None
```

- Logging used for warnings/errors: `log.warning()`, `log.error()`, `log.info()`
- Path traversal protection via `os.path.abspath()` + prefix check:
```python
safe_name = os.path.basename(file_info["filename"])
dest_path = os.path.abspath(os.path.join(dest_dir, safe_name))
if not dest_path.startswith(os.path.abspath(mission_path)):
    log.warning(f"Path traversal blocked: {file_info['filename']}")
    return None
```

- Subprocess injection prevention via parameter arrays (not shell strings):
```python
cmd = [FFMPEG_BIN, "-i", input_path, "-vf", f"lut3d='{escaped_lut}'"]
result = subprocess.run(cmd, capture_output=True, text=True)
```
Path escaping for FFmpeg special chars: `lut_path.replace("\\", "/").replace(":", "\\:")`

- API query injection prevention via string escaping:
```python
safe_part = part.replace("'", "\\'")
query = f"name = '{safe_part}' and '{current_parent}' in parents and ..."
```

## Logging

**Framework:** Standard `logging` module

**Setup pattern (in every script):**
```python
def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "script_name.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)
```

**Usage in main():**
```python
log = setup_logging()
log.info(f"Scanning: {source}")
log.warning(f"Unassigned files: {len(unassigned)}")
log.error(f"Copy failed: {filename} → {e}")
```

**Log levels:**
- `INFO`: Status messages, counts, progress ("Scanning: ...", "Found 24 files", "Copied: 20 files")
- `WARNING`: Non-fatal issues, data anomalies ("Gap detected", "Symlink skipped", "Webhook failed")
- `ERROR`: Operation failures, exceptions ("Copy failed", "Upload failed", "ffprobe failed")

**File locations:**
- All logs to `E:\Sentinel\logs\` directory
- One log file per script: `ingest_sorter.log`, `video_metadata.log`, `gdrive_upload.log`, `archive_sync.log`, etc.
- Both file and stdout handlers — dual output for operational visibility

## CLI Design

**Argument parsing:**
- All scripts use `argparse.ArgumentParser` with `RawDescriptionHelpFormatter`
- `epilog` section shows usage examples:
```python
parser = argparse.ArgumentParser(
    description="Sentinel Aerial Inspections — [Name]",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  python script.py arg1 --flag value
  python script.py arg1 --flag value --dry-run
    """,
)
```

**Argument types:**
- Positional args for required inputs: `parser.add_argument("source", help="...")`
- Optional flags for modes: `parser.add_argument("--dry-run", action="store_true")`
- Optional flags with values: `parser.add_argument("--platform", choices=["mini4pro", "m4e", "m3e"])`
- Environment var overrides: `parser.add_argument("--missions", required=True, help="...")`

**Common flags (consistent across scripts):**
- `--dry-run`: Show what would happen without writing
- `--webhook`: Fire n8n webhook on completion
- `--upload`: Upload results to Supabase
- `--mission-id`: Supabase mission UUID (required for uploads)
- `--platform`: Drone platform (choices: mini4pro, m4e, m3e)

**Main pattern:**
```python
def main():
    parser = argparse.ArgumentParser(...)
    args = parser.parse_args()

    log = setup_logging()

    # Validate args
    if not os.path.isdir(args.source):
        sys.exit(f"Not found: {args.source}")

    # Execute
    result = process(args)

    log.info("Done.")

if __name__ == "__main__":
    main()
```

## Data Structures

**Config dictionaries:**
- Flat structure for simple settings: `{"platform": "m4e", "mission_number": 47}`
- Nested for complex records: missions_config with mission metadata, nested file dicts with filename/path/sequence/extension/platform/timestamp

**Mission representation:**
- From missions.json input:
```python
{
    "mission_id": "uuid-from-supabase",
    "mission_number": 47,
    "package_type": "re_standard",
    "date": "20260218",
    "sequence_start": 1,
    "sequence_end": 24
}
```

**File metadata (scan_sd_card output):**
```python
{
    "filename": "DJI_0015.JPG",
    "path": str(full_path),
    "sequence": 15,
    "extension": "JPG",
    "platform": "mini4pro",
    "timestamp": datetime_object or None
}
```

**Video asset record (to Supabase video_assets):**
```python
{
    "mission_id": mission_id,
    "filename": "DJI_0015.MP4",
    "duration_seconds": 45.6,
    "fps": 30.0,
    "file_size_bytes": 1024000,
    "resolution": "3840x2160",
    "codec": "H.264",
    "color_profile": "d_log_m",
    "has_lrf_proxy": True,
    "graded_path": path_or_None,
    "qa_status": "pending",
    "sequence_number": 15
}
```

## Regex Patterns

**DJI filenames:**
```python
# M4E/M3E timestamp format (sequence extraction)
seq_match = re.match(r"DJI_\d{14}_(\d{4})_", filename, re.IGNORECASE)

# Mini 4 Pro format (sequence extraction)
seq_match = re.match(r"DJI_(\d{4})\.", filename, re.IGNORECASE)

# Timestamp extraction from M4E/M3E
m = re.match(r"DJI_(\d{14})_", filename, re.IGNORECASE)
```

**SRT timestamp parsing:**
```python
TIMESTAMP_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")
# Parse "00:01:30,500" → (0, 1, 30, 500)
```

**Telemetry extraction from SRT lines:**
```python
GPS_RE = re.compile(r"GPS\s*\(([^)]+)\)")
ISO_RE = re.compile(r"ISO\s+(\d+)")
APERTURE_RE = re.compile(r"F/([\d.]+)")
```

## Module Patterns

**Public functions (used as imports):**
- `detect_platform_from_folder(folder_path)` in `platform_detect.py` — used by `ingest_sorter.py`
- Other modules are standalone CLI tools

**Utility functions:**
- Logging setup: `setup_logging(log_dir=LOG_DIR)` — returns configured logger
- File scanning: `scan_sd_card(source_path)` returns list of dicts
- Data aggregation: `aggregate_clip(frames, filename)` returns dict with computed metrics
- Validation: `validate_timestamp_gaps(files, missions_config)` returns list of warning strings
- Conversion: `normalize_codec(raw_codec)` maps ffprobe codec names to human-readable labels

## Special Patterns

**Temporary file handling:**
- No explicit temp files in current codebase — works directly on final paths
- Dry-run mode (`--dry-run`) logs what would happen without writing

**Retry logic:**
- Google Drive upload uses resumable chunks: `MediaFileUpload(..., resumable=True, chunksize=50*1024*1024)`
- Polling loop for completion: `while response is None: status, response = request.next_chunk()`
- No explicit retry on transient failures (relies on timeout/exception handling)

**Datetime handling:**
- UTC timestamps: `datetime.utcnow().isoformat() + "Z"` (RFC3339 format for n8n webhooks)
- SRT frame timestamps parsed to float seconds: `parse_srt_timestamp()` returns float(0.0)
- No timezone library (assumes UTC throughout pipeline)

**JSON output:**
- Scripts output JSON for n8n consumption: `print(json.dumps({...}))`
- Also support `--dump-json` flag to export metadata as formatted JSON
- Exclude internal fields in JSON: `{k: v for k, v in m.items() if k != "file_path"}`

---

*Convention analysis: 2026-02-23*
