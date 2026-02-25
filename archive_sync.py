"""
Sentinel Aerial Inspections — Archive Sync

Copies delivered files from Google Drive Sentinel_Deliveries/Delivered/
to local archive drive for cold storage. Runs as a weekly scheduled task.

Usage:
    python archive_sync.py
    python archive_sync.py --archive-dir F:\\Sentinel_Archive
    python archive_sync.py --dry-run
    python archive_sync.py --cleanup-days 30
"""

import os
import sys
import json
import argparse
import logging
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────────────────

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
ARCHIVE_DIR = r"F:\Sentinel_Archive"
LOG_DIR = r"E:\Sentinel\logs"
DRIVE_DELIVERED_FOLDER = "Sentinel_Deliveries/Delivered"
CLEANUP_DAYS = 30  # Remove from Drive after N days


# ─── LOGGING ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "archive_sync.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── GOOGLE DRIVE ────────────────────────────────────────────────────────────

def get_drive_service(credentials_json=None):
    """Build Google Drive API service."""
    from pipeline_utils import get_drive_service as _get_drive_service
    return _get_drive_service(credentials_json)


def find_folder(service, folder_path):
    """Find a nested folder by path. Returns folder ID or None."""
    from pipeline_utils import traverse_drive_folder
    return traverse_drive_folder(service, folder_path, create_missing=False)


def list_files_in_folder(service, folder_id):
    """List all files in a Google Drive folder."""
    from pipeline_utils import validate_drive_id
    validate_drive_id(folder_id)
    query = f"'{folder_id}' in parents and trashed = false"
    all_files = []
    page_token = None

    while True:
        results = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, size, createdTime, modifiedTime, mimeType)",
            pageToken=page_token,
        ).execute()

        all_files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return all_files


def download_file(service, file_id, dest_path):
    """Download a file from Google Drive to local path."""
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        sys.exit("pip install google-api-python-client")

    request = service.files().get_media(fileId=file_id)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    with open(dest_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request, chunksize=50 * 1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                progress = int(status.progress() * 100)
                logging.getLogger(__name__).info(f"    Download: {progress}%")


def delete_file(service, file_id):
    """Permanently delete a file from Google Drive."""
    service.files().delete(fileId=file_id).execute()


# ─── SYNC LOGIC ──────────────────────────────────────────────────────────────

def sync_delivered_to_archive(service, folder_id, archive_dir, dry_run=False):
    """Download all files from Delivered/ to local archive."""
    log = logging.getLogger(__name__)
    files = list_files_in_folder(service, folder_id)

    if not files:
        log.info("No files in Delivered/ folder")
        return []

    log.info(f"Found {len(files)} file(s) in Delivered/")
    synced = []

    for f in files:
        name = f["name"]
        file_id = f["id"]
        size = int(f.get("size", 0))

        # Sanitize filename — strip directory components to prevent path traversal
        safe_name = os.path.basename(name)
        dest_path = os.path.abspath(os.path.join(archive_dir, safe_name))

        # Verify dest stays within archive directory
        if not dest_path.startswith(os.path.abspath(archive_dir)):
            log.warning(f"  Skipping unsafe filename: {name}")
            synced.append({"name": name, "status": "skipped_unsafe"})
            continue

        # Skip if already archived
        if os.path.isfile(dest_path):
            existing_size = os.path.getsize(dest_path)
            if existing_size == size:
                log.info(f"  Skip (exists): {name}")
                synced.append({"name": name, "status": "exists"})
                continue

        log.info(f"  Downloading: {name} ({size / (1024*1024):.1f} MB)")

        if dry_run:
            log.info(f"    [DRY RUN] → {dest_path}")
            synced.append({"name": name, "status": "dry_run"})
            continue

        download_file(service, file_id, dest_path)

        # Verify download
        if os.path.isfile(dest_path):
            local_size = os.path.getsize(dest_path)
            if local_size == size:
                log.info(f"    Archived: {dest_path}")
                synced.append({"name": name, "file_id": file_id, "status": "synced"})
            else:
                log.warning(f"    Size mismatch: local={local_size} drive={size}")
                synced.append({"name": name, "status": "size_mismatch"})
        else:
            log.error(f"    Download failed: {name}")
            synced.append({"name": name, "status": "failed"})

    return synced


def cleanup_old_delivered(service, folder_id, synced_results, days=CLEANUP_DAYS, dry_run=False):
    """Remove files from Delivered/ that are older than N days AND verified archived.

    Only deletes files whose sync status is 'synced' or 'exists' to prevent data loss.
    """
    log = logging.getLogger(__name__)
    files = list_files_in_folder(service, folder_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0

    # Build set of safely archived file names
    safe_names = {s["name"] for s in synced_results if s["status"] in ("synced", "exists")}

    for f in files:
        created = datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00"))
        if created < cutoff:
            if f["name"] not in safe_names:
                log.warning(f"  Skipping cleanup (not verified archived): {f['name']}")
                continue
            log.info(f"  Cleanup: {f['name']} (created {created.date()})")
            if not dry_run:
                delete_file(service, f["id"])
            removed += 1

    return removed


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Archive Sync",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Syncs delivered files from Google Drive to local archive.

Environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON - Path to service account JSON

Examples:
  python archive_sync.py
  python archive_sync.py --archive-dir F:\\Sentinel_Archive --dry-run
  python archive_sync.py --cleanup-days 30
        """,
    )
    parser.add_argument("--archive-dir", default=ARCHIVE_DIR, help=f"Local archive path (default: {ARCHIVE_DIR})")
    parser.add_argument("--credentials", help="Service account JSON path (overrides env var)")
    parser.add_argument("--cleanup-days", type=int, default=CLEANUP_DAYS,
                        help=f"Remove Drive files older than N days (default: {CLEANUP_DAYS})")
    parser.add_argument("--no-cleanup", action="store_true", help="Skip cleanup step")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without executing")
    args = parser.parse_args()

    log = setup_logging()

    log.info("Archive sync starting")
    log.info(f"  Archive dir:   {args.archive_dir}")
    log.info(f"  Cleanup days:  {args.cleanup_days}")
    log.info(f"  Dry run:       {args.dry_run}")

    os.makedirs(args.archive_dir, exist_ok=True)

    service = get_drive_service(credentials_json=args.credentials)

    # Find Delivered folder
    folder_id = find_folder(service, DRIVE_DELIVERED_FOLDER)
    if not folder_id:
        log.info("Delivered folder not found on Drive. Nothing to sync.")
        return

    # Sync
    log.info("\n--- Syncing Delivered → Archive ---")
    synced = sync_delivered_to_archive(service, folder_id, args.archive_dir, dry_run=args.dry_run)

    synced_count = sum(1 for s in synced if s["status"] == "synced")
    exists_count = sum(1 for s in synced if s["status"] == "exists")
    log.info(f"Sync: {synced_count} downloaded, {exists_count} already archived")

    # Cleanup old files from Drive
    if not args.no_cleanup:
        log.info(f"\n--- Cleaning up files older than {args.cleanup_days} days ---")
        removed = cleanup_old_delivered(service, folder_id, synced, days=args.cleanup_days, dry_run=args.dry_run)
        log.info(f"Cleanup: {removed} file(s) removed from Drive")

    log.info("\nArchive sync complete.")


if __name__ == "__main__":
    main()
