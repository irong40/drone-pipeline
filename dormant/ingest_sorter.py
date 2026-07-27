"""
Sentinel Aerial Inspections — SD Card Ingest Sorter

Sorts files from DJI SD card into structured mission folders on the processing rig.
Extends ingest.py with sequence-range sorting, multi-file-type handling, and n8n webhook.

Usage:
    python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json
    python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json --dry-run
    python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json --no-webhook

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

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint
from pipeline_utils import LOG_DIR, PHOTO_EXTS, VIDEO_EXTS, PPK_EXTS, setup_logging, extract_sequence_number, preflight_check
from platform_detect import detect_from_filename

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "ingest_sorter"
INCOMING_ROOT = r"E:\incoming"
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


# ─── PLATFORM DETECTION ─────────────────────────────────────────────────────

def detect_platform(filename):
    """Detect drone platform from filename pattern.

    Mini 4 Pro: DJI_NNNN.EXT (sequential four-digit)
    M4E / M3E:  DJI_YYYYMMDDHHMMSS_NNNN_X.EXT (timestamp + seq + camera)

    Note: Cannot distinguish M4E from M3E by filename alone.
    Use detect_platform_exif() on media files for exact identification.
    """
    return detect_from_filename(filename)


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

        if not seq:
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
    photo_exts = PHOTO_EXTS
    video_exts = VIDEO_EXTS
    ppk_exts = PPK_EXTS

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


# ─── SUPABASE REGISTRATION ──────────────────────────────────────────────────

MAPPING_PACKAGES = {"construction_progress", "commercial_basic", "commercial_premium", "insurance_claim"}


def register_in_supabase(mission_config, mission_path, inventory, source_platform):
    """Create drone_assets records and set photogrammetry_status on the job.

    Uses local file paths so the processing server reads from disk.
    """
    log = logging.getLogger(__name__)
    try:
        from pipeline_utils import get_supabase_client
        sb = get_supabase_client()
    except (ValueError, SystemExit) as e:
        log.warning(f"Supabase registration skipped: {e}")
        return False

    job_id = mission_config["mission_id"]
    package_type = mission_config["package_type"]
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Create or update drone_jobs row
    job_data = {
        "id": job_id,
        "job_number": f"DJ-{mission_config['date'][:4]}-{mission_config['mission_number']:04d}",
        "status": "uploaded",
        "ingested_at": now,
        "photo_count": inventory["photo_count"],
        "has_ppk_data": inventory.get("has_ppk_data", False),
        "scheduled_date": f"{mission_config['date'][:4]}-{mission_config['date'][4:6]}-{mission_config['date'][6:8]}",
        "mission_number": mission_config["mission_number"],
    }

    # Set photogrammetry_status for mapping packages
    if package_type in MAPPING_PACKAGES:
        job_data["photogrammetry_status"] = "pending"

    try:
        sb.table("drone_jobs").upsert(job_data).execute()
        log.info(f"  Registered drone_jobs: {job_id}")
    except Exception as e:
        log.error(f"  drone_jobs upsert failed: {e}")
        return False

    # Create drone_assets records for photos
    photo_dir = os.path.join(mission_path, "photos", "jpeg")
    assets = []
    sort_order = 0

    if os.path.isdir(photo_dir):
        for fname in sorted(os.listdir(photo_dir)):
            fpath = os.path.join(photo_dir, fname)
            if not os.path.isfile(fpath):
                continue
            sort_order += 1
            assets.append({
                "job_id": job_id,
                "file_name": fname,
                "file_path": os.path.abspath(fpath).replace("\\", "/"),
                "file_type": "photo",
                "processing_status": "raw",
                "qa_status": "pending",
                "sort_order": sort_order,
            })

    # Also register RAW files
    raw_dir = os.path.join(mission_path, "photos", "raw")
    if os.path.isdir(raw_dir):
        for fname in sorted(os.listdir(raw_dir)):
            fpath = os.path.join(raw_dir, fname)
            if not os.path.isfile(fpath):
                continue
            sort_order += 1
            assets.append({
                "job_id": job_id,
                "file_name": fname,
                "file_path": os.path.abspath(fpath).replace("\\", "/"),
                "file_type": "raw",
                "processing_status": "raw",
                "qa_status": "pending",
                "sort_order": sort_order,
            })

    if assets:
        try:
            sb.table("drone_assets").insert(assets).execute()
            log.info(f"  Registered {len(assets)} drone_assets")
        except Exception as e:
            log.error(f"  drone_assets insert failed: {e}")
            return False

    return True


# ─── WEBHOOK ─────────────────────────────────────────────────────────────────

def fire_webhook(mission_config, inventory, source_platform, mission_path=None, webhook_url=N8N_WEBHOOK_URL):
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
        "mission_folder_path": mission_path,
        "ingested_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canopy_height_ft": mission_config.get("canopy_height_ft", 0),
        "required_acl_ft": mission_config.get("required_acl_ft", 0),
        "recommended_alt_ft": mission_config.get("recommended_alt_ft", 0),
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
  python ingest_sorter.py E:/DCIM/DJI_001 --missions missions.json --no-webhook
        """,
    )
    parser.add_argument("source", help="Path to SD card DCIM folder")
    parser.add_argument("--missions", required=True, help="Path to missions config JSON file")
    parser.add_argument("--incoming", default=INCOMING_ROOT, help=f"Incoming folder root (default: {INCOMING_ROOT})")
    parser.add_argument("--no-webhook", action="store_true", help="Skip n8n webhook after each mission")
    parser.add_argument("--webhook-url", default=N8N_WEBHOOK_URL, help="Override webhook URL")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip preflight service checks")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without copying")
    parser.add_argument("--list", action="store_true", help="List files found and exit")
    parser.add_argument("--force", action="store_true",
                        help="Clear checkpoint and re-copy all files from scratch")
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # Preflight — verify pipeline services are running
    if not args.skip_preflight:
        preflight_check(require_n8n=not args.no_webhook)

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

        # Checkpoint resume — keyed per mission
        SCRIPT_NAME = f"ingest_sorter_{mid}"
        if args.force:
            clear_checkpoint(mission_path, SCRIPT_NAME)
        completed = load_checkpoint(mission_path, SCRIPT_NAME)
        if completed:
            log.info(f"  Resuming: {len(completed)} file(s) already copied")

        # Copy files
        copied = 0
        skipped = 0
        failed = 0
        for f in mission_files:
            item_key = f["path"]
            if item_key in completed:
                skipped += 1
                continue
            dest = copy_file_to_mission(f, mission_path)
            if dest:
                copied += 1
                completed.add(item_key)
                try:
                    save_checkpoint(mission_path, SCRIPT_NAME, completed)
                except OSError as e:
                    log.warning(f"  Checkpoint write failed (non-fatal): {e}")
            else:
                failed += 1

        log.info(f"  Copied: {copied}, Skipped (checkpoint): {skipped}, Failed: {failed}")

        if failed > 0:
            log.warning(f"  {failed} file(s) failed to copy — ingest incomplete")

        # Count inventory
        inventory = count_inventory(mission_path)
        log.info(f"  Photos: {inventory['photo_count']}, Videos: {inventory['video_count']}, PPK: {inventory['has_ppk_data']}")

        # Register in Supabase (creates drone_jobs + drone_assets with local paths)
        register_in_supabase(mission, mission_path, inventory, source_platform)

        # Fire webhook (skip if any copies failed to prevent false success signal)
        if not args.no_webhook:
            if failed > 0:
                log.warning(f"  Webhook skipped — incomplete ingest ({failed} failed copies)")
            else:
                url = args.webhook_url or N8N_WEBHOOK_URL
                ok = fire_webhook(mission, inventory, source_platform, mission_path=mission_path, webhook_url=url)
                log.info(f"  Webhook: {'OK' if ok else 'FAILED'}")

    log.info("Ingest complete.")


if __name__ == "__main__":
    main()
