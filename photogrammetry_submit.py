"""
Sentinel Aerial Inspections — Photogrammetry Submit (Path C)

Submits drone photos to NodeODM for orthomosaic generation.
Polls for task completion, then downloads outputs to the mission
output directory where Path E expects them.

Usage:
    python photogrammetry_submit.py --mission-id UUID --photos-dir E:\\incoming\\SAI_M0047\\photos\\jpeg
    python photogrammetry_submit.py --mission-id UUID --photos-dir path/to/photos --output-dir E:\\output\\UUID\\mapping
    python photogrammetry_submit.py --mission-id UUID --photos-dir path/to/photos --nodeodm-url http://localhost:3000
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

from pipeline_utils import setup_logging
from sentinel_core.nodeodm import (
    check_nodeodm,
    submit_task,
    poll_task,
    download_outputs,
)
from sentinel_core.constants import PHOTO_EXTENSIONS

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "photogrammetry_submit"
NODEODM_URL = os.environ.get("NODEODM_URL", "http://localhost:3000")
OUTPUT_ROOT = r"E:\output"
POLL_INTERVAL_SECONDS = 30
MAX_POLL_HOURS = 6

# Default ODM processing options for aerial survey orthomosaics
DEFAULT_ODM_OPTIONS = [
    {"name": "dsm", "value": True},
    {"name": "dtm", "value": True},
    {"name": "orthophoto-resolution", "value": 5},  # 5 cm/pixel
    {"name": "fast-orthophoto", "value": False},
    {"name": "auto-boundary", "value": True},
    {"name": "pc-quality", "value": "medium"},
    {"name": "feature-quality", "value": "high"},
    {"name": "split", "value": 4},              # split into 4 submodels to limit RAM
    {"name": "split-overlap", "value": 150},     # 150m overlap between submodels
]


# ─── LOCAL HELPERS ───────────────────────────────────────────────────────────

_SUBMIT_EXTENSIONS = PHOTO_EXTENSIONS | {".png"}


def find_photos(photos_dir):
    """Find all photo files in directory."""
    photos = []
    for fname in sorted(os.listdir(photos_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in _SUBMIT_EXTENSIONS:
            photos.append(os.path.join(photos_dir, fname))
    return photos


def update_supabase_status(mission_id, status, output_path=None):
    """Update photogrammetry_status in drone_jobs."""
    log = logging.getLogger(__name__)
    try:
        from pipeline_utils import get_supabase_client
        sb = get_supabase_client()
        data = {"photogrammetry_status": status}
        if output_path:
            data["output_path"] = output_path
        sb.table("drone_jobs").update(data).eq("id", mission_id).execute()
        log.info(f"  Supabase: photogrammetry_status={status}")
    except Exception as e:
        log.warning(f"  Supabase update failed (non-fatal): {e}")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Photogrammetry Submit (Path C)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Submits drone photos to NodeODM for orthomosaic generation.
Polls until complete, downloads outputs, updates Supabase.

Examples:
  python photogrammetry_submit.py --mission-id abc-123 --photos-dir E:\\incoming\\SAI_M0047\\photos\\jpeg
  python photogrammetry_submit.py --mission-id abc-123 --photos-dir photos/ --output-dir E:\\output\\abc-123\\mapping
  python photogrammetry_submit.py --mission-id abc-123 --photos-dir photos/ --nodeodm-url http://192.168.1.10:3000

Exit codes:
  0 — Success: orthomosaic produced and downloaded
  1 — Fatal error: NodeODM unreachable, submission failed, or task failed
  2 — Partial success: task completed but some outputs missing
        """,
    )
    parser.add_argument("--mission-id", required=True, help="Supabase mission UUID")
    parser.add_argument("--photos-dir", required=True, help="Directory containing photos to process")
    parser.add_argument("--output-dir", help="Output directory for downloads (default: E:\\output\\{mission-id}\\mapping)")
    parser.add_argument("--nodeodm-url", default=NODEODM_URL, help=f"NodeODM API URL (default: {NODEODM_URL})")
    parser.add_argument("--poll-interval", type=int, default=POLL_INTERVAL_SECONDS,
                        help=f"Seconds between status polls (default: {POLL_INTERVAL_SECONDS})")
    parser.add_argument("--max-hours", type=float, default=MAX_POLL_HOURS,
                        help=f"Maximum hours to wait for completion (default: {MAX_POLL_HOURS})")
    parser.add_argument("--options", help="Override ODM options as JSON array")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be submitted without processing")
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # Validate photos directory
    photos_dir = os.path.abspath(args.photos_dir)
    if not os.path.isdir(photos_dir):
        log.error(f"Photos directory not found: {photos_dir}")
        sys.exit(1)

    photos = find_photos(photos_dir)
    if not photos:
        log.error(f"No photos found in: {photos_dir}")
        sys.exit(1)

    # Output directory
    output_dir = args.output_dir or os.path.join(OUTPUT_ROOT, args.mission_id, "mapping")

    # ODM options
    odm_options = DEFAULT_ODM_OPTIONS
    if args.options:
        try:
            odm_options = json.loads(args.options)
        except json.JSONDecodeError as e:
            log.error(f"Invalid --options JSON: {e}")
            sys.exit(1)

    log.info(f"Mission:     {args.mission_id}")
    log.info(f"Photos:      {len(photos)} files in {photos_dir}")
    log.info(f"Output:      {output_dir}")
    log.info(f"NodeODM:     {args.nodeodm_url}")
    log.info(f"Poll:        {args.poll_interval}s interval, {args.max_hours}h max")

    if args.dry_run:
        log.info("[DRY RUN] Would submit these photos:")
        for p in photos[:10]:
            log.info(f"  {os.path.basename(p)}")
        if len(photos) > 10:
            log.info(f"  ... and {len(photos) - 10} more")
        return

    # Check NodeODM
    info = check_nodeodm(args.nodeodm_url)
    if not info:
        log.error(f"NodeODM not reachable at {args.nodeodm_url}")
        update_supabase_status(args.mission_id, "failed")
        sys.exit(1)

    log.info(f"NodeODM:     v{info.get('version', '?')} / ODM v{info.get('engineVersion', '?')}")
    log.info(f"Queue:       {info.get('taskQueueCount', 0)} tasks")

    # Update Supabase status
    update_supabase_status(args.mission_id, "processing", output_path=output_dir)

    # Submit task
    task_name = f"sentinel-{args.mission_id[:8]}"
    task_uuid = submit_task(args.nodeodm_url, photos, options=odm_options, name=task_name)
    if not task_uuid:
        update_supabase_status(args.mission_id, "failed")
        sys.exit(1)

    # Poll for completion
    result = poll_task(args.nodeodm_url, task_uuid,
                       poll_interval=args.poll_interval,
                       max_hours=args.max_hours)

    if not result:
        log.error("Task timed out")
        update_supabase_status(args.mission_id, "failed")
        sys.exit(1)

    status_code = result.get("status", {}).get("code", -1)
    if status_code != 40:
        error_msg = result.get("status", {}).get("errorMessage", "unknown")
        log.error(f"Task did not complete successfully: {error_msg}")
        update_supabase_status(args.mission_id, "failed")
        sys.exit(1)

    # Download outputs
    downloaded = download_outputs(args.nodeodm_url, task_uuid, output_dir)

    # Copy orthophoto as orthomosaic.tif (the name Path E expects)
    ortho_src = downloaded.get("orthophoto.tif")
    if ortho_src:
        import shutil
        ortho_dest = os.path.join(output_dir, "orthomosaic.tif")
        if ortho_src != ortho_dest:
            shutil.copy2(ortho_src, ortho_dest)
            downloaded["orthomosaic.tif"] = ortho_dest
            log.info("  Copied: orthophoto.tif -> orthomosaic.tif (Path E compatible)")

    if "orthomosaic.tif" not in downloaded and "orthophoto.tif" not in downloaded:
        log.error("No orthomosaic produced — check NodeODM logs")
        update_supabase_status(args.mission_id, "failed")
        sys.exit(1)

    # Update status
    update_supabase_status(args.mission_id, "complete")

    # Output JSON for n8n consumption
    ortho_path = downloaded.get("orthomosaic.tif", downloaded.get("orthophoto.tif", ""))
    output = {
        "mission_id": args.mission_id,
        "task_uuid": task_uuid,
        "ortho_path": ortho_path,
        "output_dir": output_dir,
        "downloaded_files": list(downloaded.keys()),
        "processing_time_minutes": round(result.get("processingTime", 0) / 60000, 1),
    }

    has_all = "orthomosaic.tif" in downloaded
    if has_all:
        log.info(f"\nPath C complete — orthomosaic at: {ortho_path}")
    else:
        log.warning("Partial output — some assets missing")

    print(json.dumps(output))

    sys.exit(0 if has_all else 2)


if __name__ == "__main__":
    main()
