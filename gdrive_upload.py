"""
Sentinel Aerial Inspections — Google Drive Delivery Upload

Uploads delivery ZIP files to Google Drive Sentinel_Deliveries/Active/ folder.
Uses a service account for authentication.

Usage:
    python gdrive_upload.py path/to/delivery.zip
    python gdrive_upload.py path/to/delivery.zip --folder-name "SAI_M0047"
    python gdrive_upload.py path/to/delivery.zip --move-to-delivered
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────────────────

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
DRIVE_ACTIVE_FOLDER = "Sentinel_Deliveries/Active"
DRIVE_DELIVERED_FOLDER = "Sentinel_Deliveries/Delivered"

# Google Drive MIME types
MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_ZIP = "application/zip"


# ─── LOGGING ─────────────────────────────────────────────────────────────────

LOG_DIR = r"E:\Sentinel\logs"


def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "gdrive_upload.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── GOOGLE DRIVE CLIENT ─────────────────────────────────────────────────────

def get_drive_service(credentials_json=None):
    """Build Google Drive API service using service account credentials."""
    from pipeline_utils import get_drive_service as _get_drive_service
    return _get_drive_service(credentials_json)


def find_or_create_folder(service, folder_path, parent_id=None):
    """Find or create a nested folder path in Google Drive.

    folder_path: "Sentinel_Deliveries/Active" creates both folders if needed.
    Returns the folder ID of the deepest folder.
    """
    parts = folder_path.strip("/").split("/")
    current_parent = parent_id or "root"

    from pipeline_utils import traverse_drive_folder
    return traverse_drive_folder(service, folder_path, parent_id=parent_id, create_missing=True)


def upload_file(service, file_path, parent_folder_id, filename=None):
    """Upload a file to Google Drive folder. Returns file metadata."""
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        sys.exit("pip install google-api-python-client")

    fname = filename or os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    metadata = {
        "name": fname,
        "parents": [parent_folder_id],
    }

    # Use resumable upload for large files
    media = MediaFileUpload(
        file_path,
        mimetype=MIME_ZIP,
        resumable=True,
        chunksize=50 * 1024 * 1024,  # 50MB chunks
    )

    request = service.files().create(body=metadata, media_body=media, fields="id, name, webViewLink")

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            logging.getLogger(__name__).info(f"  Upload progress: {progress}%")

    return response


def create_shareable_link(service, file_id):
    """Make a file viewable by anyone with the link. Returns the web view URL."""
    permission = {
        "type": "anyone",
        "role": "reader",
    }
    service.permissions().create(fileId=file_id, body=permission).execute()

    file = service.files().get(fileId=file_id, fields="webViewLink").execute()
    return file.get("webViewLink")


def move_file(service, file_id, new_parent_id):
    """Move a file to a different folder."""
    file = service.files().get(fileId=file_id, fields="parents").execute()
    old_parents = ",".join(file.get("parents", []))
    service.files().update(
        fileId=file_id,
        addParents=new_parent_id,
        removeParents=old_parents,
        fields="id, parents",
    ).execute()


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Google Drive Delivery Upload",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Uploads delivery ZIP to Google Drive Sentinel_Deliveries/Active/.

Environment variables:
  GOOGLE_SERVICE_ACCOUNT_JSON - Path to Google service account JSON file

Examples:
  python gdrive_upload.py path/to/Sentinel_123_Main_St.zip
  python gdrive_upload.py path/to/delivery.zip --folder-name SAI_M0047
  python gdrive_upload.py --move-to-delivered --file-id 1abc2def3ghi
        """,
    )
    parser.add_argument("file_path", nargs="?", help="Path to ZIP file to upload")
    parser.add_argument("--folder-name", help="Custom subfolder name in Active/")
    parser.add_argument("--credentials", help="Path to service account JSON (overrides env var)")
    parser.add_argument("--move-to-delivered", action="store_true", help="Move a file from Active/ to Delivered/")
    parser.add_argument("--file-id", help="Google Drive file ID (for --move-to-delivered)")
    parser.add_argument("--no-share", action="store_true", help="Don't create shareable link")
    args = parser.parse_args()

    log = setup_logging()

    service = get_drive_service(credentials_json=args.credentials)

    if args.move_to_delivered:
        if not args.file_id:
            sys.exit("--file-id required with --move-to-delivered")

        log.info(f"Moving file {args.file_id} to Delivered/")
        delivered_id = find_or_create_folder(service, DRIVE_DELIVERED_FOLDER)
        move_file(service, args.file_id, delivered_id)
        log.info("Done.")
        return

    if not args.file_path:
        sys.exit("File path required. Use --help for usage.")

    file_path = os.path.abspath(args.file_path)
    if not os.path.isfile(file_path):
        sys.exit(f"File not found: {file_path}")

    file_size = os.path.getsize(file_path)
    log.info(f"File: {file_path}")
    log.info(f"Size: {file_size / (1024*1024):.1f} MB")

    # Find or create Active folder
    target_folder = DRIVE_ACTIVE_FOLDER
    if args.folder_name:
        target_folder = f"{DRIVE_ACTIVE_FOLDER}/{args.folder_name}"

    log.info(f"Target: {target_folder}")
    folder_id = find_or_create_folder(service, target_folder)

    # Upload
    log.info("Uploading...")
    result = upload_file(service, file_path, folder_id)
    file_id = result["id"]
    log.info(f"Uploaded: {result['name']} (id: {file_id})")

    # Create shareable link
    if not args.no_share:
        link = create_shareable_link(service, file_id)
        log.info(f"Link: {link}")
    else:
        link = result.get("webViewLink", "")

    # Output JSON for n8n consumption
    print(json.dumps({
        "file_id": file_id,
        "file_name": result["name"],
        "web_view_link": link,
        "folder": target_folder,
    }))


if __name__ == "__main__":
    main()
