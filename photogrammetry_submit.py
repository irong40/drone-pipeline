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
import time
import argparse
import logging
import requests
from pathlib import Path
from datetime import datetime, timezone

from pipeline_utils import setup_logging

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "photogrammetry_submit"
NODEODM_URL = os.environ.get("NODEODM_URL", "http://localhost:3000")
OUTPUT_ROOT = r"E:\output"
POLL_INTERVAL_SECONDS = 30
MAX_POLL_HOURS = 6
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".dng", ".tif", ".tiff", ".png"}

# Default ODM processing options for aerial survey orthomosaics
DEFAULT_ODM_OPTIONS = [
    {"name": "dsm", "value": True},
    {"name": "dtm", "value": True},
    {"name": "orthophoto-resolution", "value": 5},  # 5 cm/pixel
    {"name": "fast-orthophoto", "value": False},
    {"name": "auto-boundary", "value": True},
    {"name": "pc-quality", "value": "medium"},
    {"name": "feature-quality", "value": "high"},
]


# ─── NODEODM API ─────────────────────────────────────────────────────────────

def check_nodeodm(base_url):
    """Verify NodeODM is reachable and return server info."""
    try:
        resp = requests.get(f"{base_url}/info", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return None


def find_photos(photos_dir):
    """Find all photo files in directory."""
    photos = []
    for fname in sorted(os.listdir(photos_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in PHOTO_EXTENSIONS:
            photos.append(os.path.join(photos_dir, fname))
    return photos


def submit_task(base_url, photo_paths, options=None, name="sentinel-mission"):
    """Submit photos to NodeODM for processing.

    Returns task UUID on success, None on failure.
    """
    log = logging.getLogger(__name__)

    files = []
    for photo_path in photo_paths:
        fname = os.path.basename(photo_path)
        files.append(("images", (fname, open(photo_path, "rb"), "image/jpeg")))

    data = {"name": name}
    if options:
        data["options"] = json.dumps(options)

    try:
        log.info(f"Submitting {len(photo_paths)} photos to NodeODM...")
        resp = requests.post(
            f"{base_url}/task/new",
            files=files,
            data=data,
            timeout=300,  # 5 min upload timeout
        )
        resp.raise_for_status()
        result = resp.json()
        task_uuid = result.get("uuid")
        log.info(f"Task created: {task_uuid}")
        return task_uuid
    except requests.RequestException as e:
        log.error(f"Task submission failed: {e}")
        return None
    finally:
        # Close all file handles
        for _, file_tuple in files:
            file_tuple[1].close()


def poll_task(base_url, task_uuid, poll_interval=POLL_INTERVAL_SECONDS, max_hours=MAX_POLL_HOURS):
    """Poll NodeODM task status until completion or failure.

    Returns final task info dict, or None on timeout.
    """
    log = logging.getLogger(__name__)
    max_attempts = int((max_hours * 3600) / poll_interval)
    start_time = time.time()

    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.get(f"{base_url}/task/{task_uuid}/info", timeout=10)
            resp.raise_for_status()
            info = resp.json()
        except requests.RequestException as e:
            log.warning(f"Poll attempt {attempt} failed: {e}")
            time.sleep(poll_interval)
            continue

        status_code = info.get("status", {}).get("code", -1)
        progress = info.get("progress", 0)

        # NodeODM status codes: 10=queued, 20=running, 30=failed, 40=completed, 50=canceled
        if status_code == 40:
            elapsed = time.time() - start_time
            log.info(f"Task completed in {elapsed / 60:.1f} minutes")
            return info

        if status_code == 30:
            error = info.get("status", {}).get("errorMessage", "unknown error")
            log.error(f"Task failed: {error}")
            return info

        if status_code == 50:
            log.error("Task was canceled")
            return info

        status_label = {10: "queued", 20: "running"}.get(status_code, f"status={status_code}")
        elapsed = time.time() - start_time
        log.info(f"  [{status_label}] {progress:.0f}% complete ({elapsed / 60:.1f}m elapsed)")

        time.sleep(poll_interval)

    log.error(f"Task timed out after {max_hours} hours")
    return None


def download_outputs(base_url, task_uuid, output_dir):
    """Download orthomosaic and other outputs from completed task.

    Downloads:
    - orthomosaic.tif (all.zip/odm_orthophoto/odm_orthophoto.tif)
    - dsm.tif (if available)
    - dtm.tif (if available)

    Returns dict of downloaded file paths.
    """
    log = logging.getLogger(__name__)
    os.makedirs(output_dir, exist_ok=True)
    downloaded = {}

    # Download individual assets
    assets = {
        "orthophoto.tif": "orthophoto.tif",
        "dsm.tif": "dsm.tif",
        "dtm.tif": "dtm.tif",
    }

    for asset_name, local_name in assets.items():
        url = f"{base_url}/task/{task_uuid}/download/{asset_name}"
        local_path = os.path.join(output_dir, local_name)

        try:
            resp = requests.get(url, stream=True, timeout=30)
            if resp.status_code == 200:
                with open(local_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                size_mb = os.path.getsize(local_path) / (1024 * 1024)
                log.info(f"  Downloaded: {local_name} ({size_mb:.1f} MB)")
                downloaded[asset_name] = local_path
            elif resp.status_code == 404:
                log.info(f"  Not available: {asset_name}")
            else:
                log.warning(f"  Download failed for {asset_name}: HTTP {resp.status_code}")
        except requests.RequestException as e:
            log.warning(f"  Download failed for {asset_name}: {e}")

    # Also copy orthophoto as orthomosaic.tif (the name Path E expects)
    ortho_src = downloaded.get("orthophoto.tif")
    if ortho_src:
        ortho_dest = os.path.join(output_dir, "orthomosaic.tif")
        if ortho_src != ortho_dest:
            import shutil
            shutil.copy2(ortho_src, ortho_dest)
            downloaded["orthomosaic.tif"] = ortho_dest
            log.info(f"  Copied: orthophoto.tif → orthomosaic.tif (Path E compatible)")

    return downloaded


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
