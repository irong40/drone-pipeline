"""
Sentinel Aerial Inspections — WebODM -> Path E Bridge

Connects WebODM's completed task outputs to the vegetation analysis pipeline.
Polls WebODM REST API for completed tasks, downloads the orthophoto to the
host filesystem where Path E expects it, updates Supabase, and fires the
n8n webhook to kick off E1->E2->E3->E4.

Usage:
    # Watch for new completed tasks and auto-trigger Path E:
    python webodm_bridge.py --watch

    # Process a specific completed task:
    python webodm_bridge.py --project 4 --task 60330d1b-e613-4fd0-a13f-4c0aaad32eeb

    # List all projects and tasks:
    python webodm_bridge.py --list

    # Download orthophoto only (no Path E trigger):
    python webodm_bridge.py --project 4 --task 60330d1b... --download-only

    # Dry run (show what would happen):
    python webodm_bridge.py --project 4 --task 60330d1b... --dry-run
"""

import os
import sys
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

import requests

from pipeline_utils import setup_logging, validate_webhook_url

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "webodm_bridge"

WEBODM_URL = os.environ.get("WEBODM_URL", "http://localhost:8080")
WEBODM_USERNAME = os.environ.get("WEBODM_USERNAME", "")
WEBODM_PASSWORD = os.environ.get("WEBODM_PASSWORD", "")
WEBODM_TOKEN = os.environ.get("WEBODM_TOKEN", "")

OUTPUT_ROOT = Path(os.environ.get("WEBODM_OUTPUT_ROOT", r"E:\output"))
N8N_WEBHOOK_URL = os.environ.get("N8N_PATHE_WEBHOOK_URL",
                                  "http://localhost:5678/webhook/path-e")

# WebODM task status codes
STATUS_QUEUED = 10
STATUS_RUNNING = 20
STATUS_FAILED = 30
STATUS_COMPLETED = 40
STATUS_CANCELED = 50

STATUS_NAMES = {
    STATUS_QUEUED: "queued",
    STATUS_RUNNING: "running",
    STATUS_FAILED: "failed",
    STATUS_COMPLETED: "completed",
    STATUS_CANCELED: "canceled",
}

# Assets to download from completed tasks
DOWNLOAD_ASSETS = ["orthophoto.tif", "dsm.tif"]

WATCH_INTERVAL = int(os.environ.get("WEBODM_WATCH_INTERVAL", "60"))  # seconds


# ─── AUTH ────────────────────────────────────────────────────────────────────

def get_auth_token():
    """Get a JWT token for WebODM API access.

    Tries in order:
    1. WEBODM_TOKEN env var (pre-generated)
    2. WEBODM_USERNAME + WEBODM_PASSWORD (generates fresh token)
    """
    if WEBODM_TOKEN:
        return WEBODM_TOKEN

    if not WEBODM_USERNAME or not WEBODM_PASSWORD:
        sys.exit(
            "WebODM credentials required. Set either:\n"
            "  WEBODM_TOKEN=<jwt-token>\n"
            "or:\n"
            "  WEBODM_USERNAME=<email>\n"
            "  WEBODM_PASSWORD=<password>\n"
            "in .env or environment variables."
        )

    resp = requests.post(
        f"{WEBODM_URL}/api/token-auth/",
        json={"username": WEBODM_USERNAME, "password": WEBODM_PASSWORD},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "token" not in data:
        sys.exit(f"Auth failed: {data}")
    return data["token"]


def api_headers(token):
    return {"Authorization": f"JWT {token}"}


# ─── API WRAPPERS ───────────────────────────────────────────────────────────

def list_projects(token):
    """List all WebODM projects."""
    resp = requests.get(f"{WEBODM_URL}/api/projects/",
                        headers=api_headers(token), timeout=15)
    resp.raise_for_status()
    return resp.json()


def list_tasks(token, project_id):
    """List tasks in a project."""
    resp = requests.get(f"{WEBODM_URL}/api/projects/{project_id}/tasks/",
                        headers=api_headers(token), timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_task(token, project_id, task_id):
    """Get task details."""
    resp = requests.get(
        f"{WEBODM_URL}/api/projects/{project_id}/tasks/{task_id}/",
        headers=api_headers(token), timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def download_asset(token, project_id, task_id, asset_name, output_path):
    """Download a task asset (orthophoto.tif, dsm.tif, etc.) to disk.

    Streams the download to handle large files without loading into memory.
    """
    log = logging.getLogger(__name__)
    url = f"{WEBODM_URL}/api/projects/{project_id}/tasks/{task_id}/download/{asset_name}"

    resp = requests.get(url, headers=api_headers(token), stream=True, timeout=30)
    resp.raise_for_status()

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0

    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)

    size_mb = downloaded / (1024 * 1024)
    log.info(f"  Downloaded {asset_name} ({size_mb:.1f} MB) -> {output_path}")
    return str(output_path)


# ─── BRIDGE LOGIC ───────────────────────────────────────────────────────────

def _override_output_root(new_root):
    """Override the module-level OUTPUT_ROOT."""
    global OUTPUT_ROOT
    OUTPUT_ROOT = new_root


def build_output_dir(task_id):
    """Build the host output directory path for a task.

    Path E expects: E:\\output\\{task-id}\\mapping\\orthomosaic.tif
    """
    return OUTPUT_ROOT / task_id / "mapping"


def process_completed_task(token, project_id, task_id, dry_run=False,
                           download_only=False, trigger_pathe=True):
    """Download assets from a completed WebODM task and optionally trigger Path E.

    Args:
        token: WebODM JWT token
        project_id: WebODM project ID
        task_id: WebODM task UUID
        dry_run: If True, show what would happen without downloading
        download_only: If True, download but don't trigger Path E
        trigger_pathe: If True, fire n8n webhook after download

    Returns:
        dict with ortho_path, dsm_path, and trigger status
    """
    log = logging.getLogger(__name__)

    task = get_task(token, project_id, task_id)
    task_name = task.get("name", task_id)
    status = task.get("status")
    available = task.get("available_assets", [])

    log.info(f"Task: {task_name}")
    log.info(f"  ID:     {task_id}")
    log.info(f"  Status: {STATUS_NAMES.get(status, status)}")
    log.info(f"  Images: {task.get('images_count', '?')}")
    log.info(f"  Assets: {', '.join(available)}")

    if status != STATUS_COMPLETED:
        log.warning(f"  Task is not completed (status={status}). Skipping.")
        return None

    output_dir = build_output_dir(task_id)
    result = {"task_id": task_id, "task_name": task_name, "project_id": project_id}

    if dry_run:
        log.info(f"\n  [DRY RUN] Would download to: {output_dir}")
        for asset in DOWNLOAD_ASSETS:
            if asset in available:
                log.info(f"    {asset} -> {output_dir / asset}")
        return result

    # Download assets
    for asset in DOWNLOAD_ASSETS:
        if asset not in available:
            log.info(f"  {asset}: not available, skipping")
            continue
        dest = output_dir / asset
        if dest.exists():
            log.info(f"  {asset}: already exists at {dest}, skipping")
            result[asset.replace(".", "_")] = str(dest)
            continue
        try:
            path = download_asset(token, project_id, task_id, asset, dest)
            result[asset.replace(".", "_")] = path
        except requests.RequestException as e:
            log.error(f"  {asset}: download failed — {e}")

    ortho_path = result.get("orthophoto_tif")
    if not ortho_path:
        log.error("  No orthophoto downloaded. Cannot proceed.")
        return result

    result["ortho_path"] = ortho_path

    # Register in Supabase (update drone_jobs with output path)
    try:
        _update_supabase(task_id, task_name, ortho_path, task)
    except Exception as e:
        log.warning(f"  Supabase update failed (non-fatal): {e}")

    # Fire n8n webhook to trigger Path E
    if not download_only and trigger_pathe:
        result["webhook_fired"] = _fire_pathe_webhook(task_id, ortho_path, task_name)
    else:
        log.info("  Path E trigger skipped (download-only mode)")

    return result


def _update_supabase(task_id, task_name, ortho_path, task_data):
    """Update Supabase drone_jobs with WebODM output path."""
    log = logging.getLogger(__name__)
    try:
        from pipeline_utils import get_supabase_client
        sb = get_supabase_client()
    except (ValueError, SystemExit):
        log.info("  Supabase: not configured, skipping")
        return

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Try to find an existing drone_job that matches this task
    # If not found, create a lightweight record
    job_data = {
        "webodm_task_id": task_id,
        "output_path": str(Path(ortho_path).parent.parent),
        "photogrammetry_status": "completed",
        "photo_count": task_data.get("images_count", 0),
    }

    # Upsert by webodm_task_id
    try:
        sb.table("drone_jobs").upsert(
            job_data, on_conflict="webodm_task_id"
        ).execute()
        log.info(f"  Supabase: drone_jobs updated for {task_id}")
    except Exception as e:
        # Column might not exist yet — log and continue
        log.warning(f"  Supabase upsert failed: {e}")


def _fire_pathe_webhook(task_id, ortho_path, task_name):
    """Fire the n8n Path E webhook to start vegetation analysis."""
    log = logging.getLogger(__name__)

    try:
        validate_webhook_url(N8N_WEBHOOK_URL)
    except ValueError as e:
        log.error(f"  Webhook blocked: {e}")
        return False

    payload = {
        "mission_id": task_id,
        "ortho_path": ortho_path,
        "task_name": task_name,
        "triggered_by": "webodm_bridge",
        "triggered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    try:
        resp = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        log.info(f"  Path E webhook fired: {N8N_WEBHOOK_URL}")
        return True
    except requests.RequestException as e:
        log.warning(f"  Path E webhook failed: {e}")
        return False


# ─── WATCH MODE ─────────────────────────────────────────────────────────────

def watch_for_completions(token, interval=WATCH_INTERVAL):
    """Poll WebODM for newly completed tasks and process them.

    Tracks which tasks have already been processed to avoid duplicates.
    """
    log = logging.getLogger(__name__)
    processed = set()

    # On startup, mark all currently completed tasks as already processed
    # so we only trigger on NEW completions
    log.info("Scanning existing tasks...")
    for project in list_projects(token):
        for task_id in project.get("tasks", []):
            try:
                task = get_task(token, project["id"], task_id)
                if task.get("status") == STATUS_COMPLETED:
                    processed.add(task_id)
            except requests.RequestException:
                pass

    log.info(f"Found {len(processed)} already-completed tasks (will not re-trigger)")
    log.info(f"Watching for new completions every {interval}s... (Ctrl+C to stop)")
    log.info("")

    while True:
        try:
            for project in list_projects(token):
                for task_id in project.get("tasks", []):
                    if task_id in processed:
                        continue
                    try:
                        task = get_task(token, project["id"], task_id)
                        if task.get("status") == STATUS_COMPLETED:
                            log.info(f"New completion: {task.get('name', task_id)}")
                            process_completed_task(token, project["id"], task_id)
                            processed.add(task_id)
                        elif task.get("status") in (STATUS_FAILED, STATUS_CANCELED):
                            processed.add(task_id)  # don't re-check
                    except requests.RequestException as e:
                        log.warning(f"  Error checking task {task_id}: {e}")

            time.sleep(interval)

        except KeyboardInterrupt:
            log.info("\nWatch stopped.")
            break
        except requests.RequestException as e:
            log.warning(f"API error: {e} — retrying in {interval}s")
            time.sleep(interval)


# ─── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel — WebODM -> Path E Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Connects WebODM completed tasks to the vegetation analysis pipeline.

Examples:
  python webodm_bridge.py --list
  python webodm_bridge.py --project 4 --task 60330d1b-e613-4fd0-a13f-4c0aaad32eeb
  python webodm_bridge.py --project 4 --task 60330d1b... --download-only
  python webodm_bridge.py --project 4 --task 60330d1b... --dry-run
  python webodm_bridge.py --watch
        """,
    )
    parser.add_argument("--list", action="store_true",
                        help="List all projects and tasks")
    parser.add_argument("--project", type=int,
                        help="WebODM project ID")
    parser.add_argument("--task", type=str,
                        help="WebODM task UUID")
    parser.add_argument("--watch", action="store_true",
                        help="Watch for new completed tasks and auto-trigger Path E")
    parser.add_argument("--watch-interval", type=int, default=WATCH_INTERVAL,
                        help=f"Poll interval in seconds for watch mode (default: {WATCH_INTERVAL})")
    parser.add_argument("--download-only", action="store_true",
                        help="Download assets but don't trigger Path E")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would happen without downloading")
    parser.add_argument("--output-root", type=str, default=str(OUTPUT_ROOT),
                        help=f"Root output directory (default: {OUTPUT_ROOT})")
    parser.add_argument("--no-supabase", action="store_true",
                        help="Skip Supabase registration")
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # Override output root if specified
    if args.output_root != str(OUTPUT_ROOT):
        _override_output_root(Path(args.output_root))

    # Auth
    token = get_auth_token()
    log.info(f"WebODM: {WEBODM_URL} (authenticated)")

    # ── List mode
    if args.list:
        projects = list_projects(token)
        for project in projects:
            log.info(f"\nProject {project['id']}: {project['name']}")
            if project.get("description"):
                log.info(f"  {project['description']}")
            for task_id in project.get("tasks", []):
                try:
                    task = get_task(token, project["id"], task_id)
                    status = STATUS_NAMES.get(task.get("status"), "?")
                    name = task.get("name", "unnamed")
                    images = task.get("images_count", 0)
                    assets = task.get("available_assets", [])
                    has_ortho = "orthophoto.tif" in assets
                    log.info(f"  Task: {name}")
                    log.info(f"    ID:     {task_id}")
                    log.info(f"    Status: {status} | {images} images | ortho: {'yes' if has_ortho else 'no'}")
                except requests.RequestException as e:
                    log.info(f"  Task {task_id}: error — {e}")
        return

    # ── Watch mode
    if args.watch:
        watch_for_completions(token, interval=args.watch_interval)
        return

    # ── Single task mode
    if args.project and args.task:
        result = process_completed_task(
            token, args.project, args.task,
            dry_run=args.dry_run,
            download_only=args.download_only,
        )
        if result:
            log.info(f"\n{json.dumps(result, indent=2)}")
        return

    # No valid mode selected
    parser.print_help()


if __name__ == "__main__":
    main()
