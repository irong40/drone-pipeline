"""
Sentinel Aerial Inspections — SD Card Ingest Sorter

Sorts files from DJI SD card into structured mission folders on the processing rig.
Extends ingest.py with sequence-range sorting, multi-file-type handling, and n8n webhook.

Usage:
    python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json
    python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json --dry-run
    python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json --webhook

missions.json format:
    [
        {
            "mission_id": "uuid-from-supabase",
            "mission_number": 47,
            "package_type": "re_standard",
            "date": "20260218",
            "sequence_start": 1,
            "sequence_end": 24
        }
    ]
"""

import os
import sys
import re
import json
import shutil
import argparse
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

# ─── CONFIG ──────────────────────────────────────────────────────────────────

INCOMING_ROOT = r"E:\Sentinel\Incoming"
LOG_DIR = r"E:\Sentinel\logs"
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/ingest")
MISSION_GAP_MINUTES = 30

# File type → subfolder mapping
FILE_ROUTING = {
    "DNG": "photos/raw",
    "JPG": "photos/jpeg",
    "JPEG": "photos/jpeg",
    "MP4": "video/full",
    "MOV": "video/full",
    "LRF": "video/proxy",
    "SRT": "video/telemetry",
    "MRK": "ppk",
    "NAV": "ppk",
    "OBS": "ppk",
    "BIN": "ppk",
    "RTK": "ppk",
}

# All subfolders to create (even if empty)
MISSION_SUBFOLDERS = [
    "photos/raw",
    "photos/jpeg",
    "video/full",
    "video/proxy",
    "video/telemetry",
    "ppk",
]


# ─── LOGGING ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "ingest_sorter.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── PLATFORM DETECTION ─────────────────────────────────────────────────────

def detect_platform(filename):
    """Detect drone platform from filename pattern.

    Mini 4 Pro: DJI_NNNN.EXT (sequential four-digit)
    M4E / M3E:  DJI_YYYYMMDDHHMMSS_NNNN_X.EXT (timestamp + seq + camera)

    Note: Cannot distinguish M4E from M3E by filename alone.
    Use detect_platform_exif() on media files for exact identification.
    """
    if re.match(r"DJI_\d{14}_\d{4}_", filename, re.IGNORECASE):
        return "m4e"  # Ambiguous — use EXIF for M4E vs M3E
    if re.match(r"DJI_\d{4}\.", filename, re.IGNORECASE):
        return "mini4pro"
    return None


def detect_platform_exif(source_path):
    """Detect exact platform via EXIF metadata from media files.

    Resolves M4E vs M3E ambiguity that filename patterns cannot.
    Falls back to filename detection if EXIF is unavailable.
    """
    try:
        from platform_detect import detect_platform_from_folder
        platform, confidence, method = detect_platform_from_folder(source_path)
        if platform and confidence in ("confirmed", "likely"):
            return platform, confidence
    except ImportError:
        pass
    return None, "unavailable"


def extract_sequence_number(filename):
    """Extract the sequence number from a DJI filename.

    Mini 4 Pro: DJI_0015.JPG → 15
    M4E/M3E:   DJI_20260218101500_0015_D.JPG → 15
    """
    # Timestamp format: DJI_YYYYMMDDHHMMSS_NNNN_X.EXT
    m = re.match(r"DJI_\d{14}_(\d{4})_", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Sequential format: DJI_NNNN.EXT
    m = re.match(r"DJI_(\d{4})\.", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))

    return None


def extract_timestamp(filename):
    """Extract timestamp from M4E/M3E filename. Returns datetime or None."""
    m = re.match(r"DJI_(\d{14})_", filename, re.IGNORECASE)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
    return None


def get_file_extension(filename):
    """Get uppercase extension without dot."""
    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").upper()


# ─── FILE SCANNING ───────────────────────────────────────────────────────────

def scan_sd_card(source_path):
    """Scan SD card folder recursively for all DJI files.

    Returns list of dicts: {filename, path, sequence, extension, platform, timestamp}
    """
    files = []
    source = Path(source_path)

    for fpath in sorted(source.rglob("*")):
        if not fpath.is_file():
            continue
        fname = fpath.name

        # Skip non-DJI files
        if not fname.upper().startswith("DJI_"):
            continue

        ext = get_file_extension(fname)
        seq = extract_sequence_number(fname)
        platform = detect_platform(fname)
        ts = extract_timestamp(fname)

        if seq is None:
            continue

        files.append({
            "filename": fname,
            "path": str(fpath),
            "sequence": seq,
            "extension": ext,
            "platform": platform,
            "timestamp": ts,
        })

    return files


# ─── MISSION SORTING ─────────────────────────────────────────────────────────

def sort_by_sequence_ranges(files, missions_config):
    """Sort files into missions using pilot-defined sequence ranges.

    Each mission config has sequence_start and sequence_end.
    Files are assigned to the mission whose range contains their sequence number.
    """
    sorted_missions = defaultdict(list)
    unassigned = []

    for f in files:
        assigned = False
        for mission in missions_config:
            start = mission["sequence_start"]
            end = mission["sequence_end"]
            if start <= f["sequence"] <= end:
                mid = mission["mission_id"]
                sorted_missions[mid].append(f)
                assigned = True
                break
        if not assigned:
            unassigned.append(f)

    return dict(sorted_missions), unassigned


def validate_timestamp_gaps(files, missions_config, gap_minutes=MISSION_GAP_MINUTES):
    """Cross-check sequence-range assignments against timestamp gaps.

    For M4E/M3E files with timestamps, verify that files within a mission
    don't have gaps larger than gap_minutes. Logs warnings if they do.
    """
    warnings = []
    for mission in missions_config:
        mid = mission["mission_id"]
        ts_files = [f for f in files if f.get("timestamp") and
                    mission["sequence_start"] <= f["sequence"] <= mission["sequence_end"]]
        if len(ts_files) < 2:
            continue

        ts_files.sort(key=lambda x: x["timestamp"])
        for i in range(1, len(ts_files)):
            gap = (ts_files[i]["timestamp"] - ts_files[i - 1]["timestamp"]).total_seconds() / 60
            if gap > gap_minutes:
                warnings.append(
                    f"Mission {mid}: {gap:.0f}min gap between "
                    f"{ts_files[i - 1]['filename']} and {ts_files[i]['filename']}. "
                    f"Possible mission boundary within sequence range."
                )
    return warnings


# ─── FOLDER CREATION ─────────────────────────────────────────────────────────

def build_mission_folder_name(mission_config):
    """Build SAI_M{number}_{package}_{date} folder name."""
    num = mission_config["mission_number"]
    pkg = mission_config["package_type"]
    date = mission_config["date"]
    return f"SAI_M{num:04d}_{pkg}_{date}"


def create_mission_structure(folder_name, root=INCOMING_ROOT):
    """Create the standardized mission folder structure."""
    mission_path = os.path.join(root, folder_name)
    for subfolder in MISSION_SUBFOLDERS:
        os.makedirs(os.path.join(mission_path, subfolder), exist_ok=True)
    return mission_path


# ─── FILE COPYING ────────────────────────────────────────────────────────────

def copy_file_to_mission(file_info, mission_path):
    """Copy a single file to the correct subfolder within the mission."""
    log = logging.getLogger(__name__)
    ext = file_info["extension"]
    subfolder = FILE_ROUTING.get(ext)

    if subfolder is None:
        return None

    # Sanitize filename — use only the basename to prevent path traversal
    safe_name = os.path.basename(file_info["filename"])
    dest_dir = os.path.join(mission_path, subfolder)
    dest_path = os.path.abspath(os.path.join(dest_dir, safe_name))

    # Verify dest stays within mission directory
    if not dest_path.startswith(os.path.abspath(mission_path)):
        log.warning(f"Path traversal blocked: {file_info['filename']}")
        return None

    # Skip symlinks on source media
    if os.path.islink(file_info["path"]):
        log.warning(f"Skipping symlink: {file_info['path']}")
        return None

    try:
        shutil.copy2(file_info["path"], dest_path)
    except (OSError, IOError) as e:
        log.error(f"Copy failed: {file_info['filename']} → {e}")
        return None
    return dest_path


# ─── INVENTORY ───────────────────────────────────────────────────────────────

def count_inventory(mission_path):
    """Count files by type in a mission folder."""
    photo_exts = {"DNG", "JPG", "JPEG"}
    video_exts = {"MP4", "MOV"}
    ppk_exts = {"MRK", "NAV", "OBS", "BIN", "RTK"}

    photo_count = 0
    video_count = 0
    has_ppk = False

    for root, _, filenames in os.walk(mission_path):
        for fname in filenames:
            ext = get_file_extension(fname)
            if ext in photo_exts:
                photo_count += 1
            elif ext in video_exts:
                video_count += 1
            elif ext in ppk_exts:
                has_ppk = True

    return {
        "photo_count": photo_count,
        "video_count": video_count,
        "has_ppk_data": has_ppk,
    }


# ─── WEBHOOK ─────────────────────────────────────────────────────────────────

def fire_webhook(mission_config, inventory, source_platform, webhook_url=N8N_WEBHOOK_URL):
    """POST mission completion data to n8n webhook."""
    from pipeline_utils import validate_webhook_url
    try:
        validate_webhook_url(webhook_url)
    except ValueError as e:
        logging.getLogger(__name__).error(f"Webhook blocked: {e}")
        return False
    payload = {
        "mission_id": mission_config["mission_id"],
        "mission_number": mission_config["mission_number"],
        "package_type": mission_config["package_type"],
        "photo_count": inventory["photo_count"],
        "video_count": inventory["video_count"],
        "has_ppk_data": inventory["has_ppk_data"],
        "source_platform": source_platform,
        "ingested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logging.getLogger(__name__).warning(f"Webhook failed: {e}")
        return False


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — SD Card Ingest Sorter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json
  python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json --dry-run
  python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json --webhook
        """,
    )
    parser.add_argument("source", help="Path to SD card DCIM folder")
    parser.add_argument("--missions", required=True, help="Path to missions config JSON file")
    parser.add_argument("--incoming", default=INCOMING_ROOT, help=f"Incoming folder root (default: {INCOMING_ROOT})")
    parser.add_argument("--webhook", action="store_true", help="Fire n8n webhook after each mission")
    parser.add_argument("--webhook-url", default=N8N_WEBHOOK_URL, help="Override webhook URL")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without copying")
    parser.add_argument("--list", action="store_true", help="List files found and exit")
    args = parser.parse_args()

    log = setup_logging()

    # Validate source
    source = os.path.abspath(args.source)
    if not os.path.isdir(source):
        sys.exit(f"Source folder not found: {source}")

    # Load and validate missions config
    try:
        with open(args.missions, "r") as f:
            missions_config = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        sys.exit(f"Failed to load missions config: {e}")

    if not missions_config:
        sys.exit("Missions config is empty")

    required_keys = {"mission_id", "mission_number", "package_type", "date", "sequence_start", "sequence_end"}
    for i, mission in enumerate(missions_config):
        missing = required_keys - set(mission.keys())
        if missing:
            sys.exit(f"Mission #{i} missing required keys: {missing}")
        if not re.match(r"^\d{8}$", str(mission["date"])):
            sys.exit(f"Mission #{i} invalid date format (expected YYYYMMDD): {mission['date']}")
        if not re.match(r"^[a-zA-Z0-9_]+$", str(mission["package_type"])):
            sys.exit(f"Mission #{i} invalid package_type: {mission['package_type']}")

    log.info(f"Scanning: {source}")
    files = scan_sd_card(source)
    log.info(f"Found {len(files)} DJI files")

    if not files:
        sys.exit("No DJI files found on card")

    # Detect platform — try EXIF first for M4E/M3E disambiguation
    platforms = set(f["platform"] for f in files if f["platform"])
    source_platform = platforms.pop() if len(platforms) == 1 else "mini4pro"

    if source_platform in ("m4e", "m3e"):
        exif_platform, confidence = detect_platform_exif(source)
        if exif_platform:
            source_platform = exif_platform
            log.info(f"Detected platform: {source_platform} (EXIF {confidence})")
        else:
            log.info(f"Detected platform: {source_platform} (filename only — M4E/M3E ambiguous)")
    else:
        log.info(f"Detected platform: {source_platform}")

    if args.list:
        print(f"\n{'Seq':>5}  {'Extension':<6}  {'Platform':<10}  {'Filename'}")
        print("-" * 60)
        for f in sorted(files, key=lambda x: (x["sequence"], x["extension"])):
            print(f"{f['sequence']:>5}  {f['extension']:<6}  {f['platform'] or '?':<10}  {f['filename']}")
        return

    # Sort files into missions
    sorted_missions, unassigned = sort_by_sequence_ranges(files, missions_config)

    if unassigned:
        log.warning(f"{len(unassigned)} files not assigned to any mission:")
        for f in unassigned[:10]:
            log.warning(f"  seq={f['sequence']}  {f['filename']}")
        if len(unassigned) > 10:
            log.warning(f"  ... and {len(unassigned) - 10} more")

    # Validate timestamp gaps (M4E/M3E only)
    warnings = validate_timestamp_gaps(files, missions_config)
    for w in warnings:
        log.warning(w)

    # Process each mission
    for mission in missions_config:
        mid = mission["mission_id"]
        folder_name = build_mission_folder_name(mission)
        mission_files = sorted_missions.get(mid, [])

        log.info(f"{'=' * 60}")
        log.info(f"Mission: {folder_name}")
        log.info(f"  Files: {len(mission_files)}")
        log.info(f"  Sequence range: {mission['sequence_start']}-{mission['sequence_end']}")

        if args.dry_run:
            for f in mission_files:
                subfolder = FILE_ROUTING.get(f["extension"], "unknown")
                log.info(f"  [DRY RUN] {f['filename']} → {folder_name}/{subfolder}/")
            continue

        # Create folder structure
        mission_path = create_mission_structure(folder_name, root=args.incoming)
        log.info(f"  Created: {mission_path}")

        # Copy files
        copied = 0
        failed = 0
        for f in mission_files:
            dest = copy_file_to_mission(f, mission_path)
            if dest:
                copied += 1
            else:
                failed += 1

        log.info(f"  Copied: {copied} files, Failed: {failed}")

        if failed > 0:
            log.warning(f"  {failed} file(s) failed to copy — ingest incomplete")

        # Count inventory
        inventory = count_inventory(mission_path)
        log.info(f"  Photos: {inventory['photo_count']}, Videos: {inventory['video_count']}, PPK: {inventory['has_ppk_data']}")

        # Fire webhook (skip if any copies failed to prevent false success signal)
        if args.webhook:
            if failed > 0:
                log.warning(f"  Webhook skipped — incomplete ingest ({failed} failed copies)")
            else:
                url = args.webhook_url or N8N_WEBHOOK_URL
                ok = fire_webhook(mission, inventory, source_platform, webhook_url=url)
                log.info(f"  Webhook: {'OK' if ok else 'FAILED'}")

    log.info("Ingest complete.")


if __name__ == "__main__":
    main()
