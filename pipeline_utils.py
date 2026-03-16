"""
Sentinel Aerial Inspections — Shared Pipeline Utilities

Common functions extracted from pipeline scripts to eliminate duplication.
"""

import os
import re
import sys
import logging
import shutil
from urllib.parse import urlparse


# ─── CONSTANTS ──────────────────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# Glob-style patterns for finding video files (used with glob.glob)
VIDEO_EXTENSIONS = {"*.mp4", "*.MP4", "*.mov", "*.MOV"}

# Extension sets for file-type classification (uppercase, no dots)
PHOTO_EXTS = {"DNG", "JPG", "JPEG"}
VIDEO_EXTS = {"MP4", "MOV"}
PPK_EXTS = {"MRK", "NAV", "OBS", "BIN", "RTK"}

# Allowed codecs for FFmpeg video encoding
ALLOWED_VIDEO_CODECS = {
    "libx264", "libx265", "copy", "vp9", "av1",
    "libaom-av1", "libvpx-vp9", "prores", "prores_ks",
}

# Allowed webhook hosts (local n8n only)
ALLOWED_WEBHOOK_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Supabase credentials (read from env once)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


# ─── LOGGING ────────────────────────────────────────────────────────────────

def setup_logging(script_name, log_dir=LOG_DIR):
    """Configure logging with file + stdout handlers.

    Args:
        script_name: Used for log filename (e.g. "video_color_grade" -> video_color_grade.log)
        log_dir: Directory for log files (default: {repo}/logs)
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{script_name}.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── SUPABASE CLIENT ────────────────────────────────────────────────────────

def get_supabase_client():
    """Return a Supabase client or raise ValueError if credentials are missing.

    Lazy-imports supabase to keep the module importable without the package.
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    try:
        from supabase import create_client
    except ImportError:
        sys.exit("pip install supabase")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# ─── DJI FILENAME PARSING ──────────────────────────────────────────────────

def extract_sequence_number(filename):
    """Extract the sequence number from a DJI filename.

    Mini 4 Pro: DJI_0015.JPG -> 15
    M4E/M3E:   DJI_20260218101500_0015_D.JPG -> 15
    """
    # Timestamp format: DJI_YYYYMMDDHHMMSS_NNNN_X.EXT
    m = re.match(r"DJI_\d{14}_(\d{4})_", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Sequential format: DJI_NNNN.EXT
    m = re.match(r"DJI_(\d{4})\.", filename, re.IGNORECASE)
    if m:
        return int(m.group(1))

    return 0


# ─── GOOGLE DRIVE ───────────────────────────────────────────────────────────

GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")


def get_drive_service(credentials_json=None):
    """Build Google Drive API service using service account credentials."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("pip install google-api-python-client google-auth")

    creds_path = credentials_json or GOOGLE_SERVICE_ACCOUNT_JSON

    if not creds_path:
        sys.exit("GOOGLE_SERVICE_ACCOUNT_JSON env var must be set to the path of the service account JSON file")

    if not os.path.isfile(creds_path):
        sys.exit(f"Service account JSON not found: {creds_path}")

    scopes = ["https://www.googleapis.com/auth/drive"]
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
    service = build("drive", "v3", credentials=creds)
    return service


def validate_drive_id(drive_id):
    """Validate that a Google Drive ID matches the expected alphanumeric pattern."""
    if not re.match(r'^[a-zA-Z0-9_-]+$', drive_id):
        raise ValueError(f"Unexpected Drive ID format: {drive_id}")
    return drive_id


def traverse_drive_folder(service, folder_path, parent_id=None, create_missing=False):
    """Traverse a nested folder path in Google Drive.

    Args:
        service: Google Drive API service
        folder_path: e.g. "Sentinel_Deliveries/Active"
        parent_id: Starting parent ID (default: root)
        create_missing: If True, create folders that don't exist

    Returns the folder ID of the deepest folder, or None if not found
    and create_missing is False.
    """
    MIME_FOLDER = "application/vnd.google-apps.folder"
    parts = folder_path.strip("/").split("/")
    current_parent = parent_id or "root"

    for part in parts:
        safe_part = part.replace("'", "\\'")
        validate_drive_id(current_parent)
        query = (
            f"name = '{safe_part}' and "
            f"'{current_parent}' in parents and "
            f"mimeType = '{MIME_FOLDER}' and "
            f"trashed = false"
        )
        results = service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get("files", [])

        if files:
            current_parent = files[0]["id"]
        elif create_missing:
            metadata = {
                "name": part,
                "mimeType": MIME_FOLDER,
                "parents": [current_parent],
            }
            folder = service.files().create(body=metadata, fields="id").execute()
            current_parent = folder["id"]
        else:
            return None

    return current_parent


# ─── PREFLIGHT CHECK ────────────────────────────────────────────────────

def preflight_check(require_n8n=True, require_ffmpeg=False, require_nodeodm=False):
    """Verify pipeline dependencies are running before ingest.

    Checks Docker containers (n8n, NodeODM), FFmpeg, and directories.
    Logs warnings for missing services but only exits on fatal issues.

    Returns dict of {service: bool} statuses.
    """
    log = logging.getLogger(__name__)
    log.info("Preflight check...")

    status = {}

    # Check n8n is reachable
    try:
        import requests
        resp = requests.get("http://localhost:5678/healthz", timeout=3)
        status["n8n"] = resp.status_code == 200
    except Exception:
        status["n8n"] = False

    if not status["n8n"]:
        msg = "n8n is not running — webhook routing will fail"
        if require_n8n:
            log.error(f"  FAIL: {msg}")
        else:
            log.warning(f"  WARN: {msg}")

    # Check FFmpeg
    status["ffmpeg"] = shutil.which("ffmpeg") is not None
    if not status["ffmpeg"]:
        msg = "FFmpeg not found in PATH — video processing will fail"
        if require_ffmpeg:
            log.error(f"  FAIL: {msg}")
        else:
            log.warning(f"  WARN: {msg}")

    # Check NodeODM (Docker)
    try:
        import requests
        resp = requests.get("http://localhost:3000/info", timeout=3)
        status["nodeodm"] = resp.status_code == 200
    except Exception:
        status["nodeodm"] = False

    if not status["nodeodm"]:
        msg = "NodeODM not reachable — photogrammetry (Path C) will fail"
        if require_nodeodm:
            log.error(f"  FAIL: {msg}")
        else:
            log.warning(f"  WARN: {msg}")

    # Check directories
    for d in [r"E:\incoming", r"E:\output"]:
        if not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
            log.info(f"  Created: {d}")

    # Check Supabase
    status["supabase"] = bool(SUPABASE_URL and SUPABASE_SERVICE_KEY)
    if not status["supabase"]:
        log.warning("  WARN: Supabase credentials not set")

    ok = [k for k, v in status.items() if v]
    fail = [k for k, v in status.items() if not v]
    log.info(f"  OK: {', '.join(ok) if ok else 'none'}")
    if fail:
        log.info(f"  Missing: {', '.join(fail)}")

    return status


# ─── VALIDATION ─────────────────────────────────────────────────────────────

def validate_webhook_url(url):
    """Validate that a webhook URL points to an allowed host."""
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_WEBHOOK_HOSTS:
        raise ValueError(
            f"Webhook URL host '{parsed.hostname}' not in allowlist "
            f"({', '.join(ALLOWED_WEBHOOK_HOSTS)}). "
            f"Update ALLOWED_WEBHOOK_HOSTS in pipeline_utils.py if this is intentional."
        )
    return url


def validate_codec(codec):
    """Validate that an FFmpeg codec is in the allowlist."""
    if codec not in ALLOWED_VIDEO_CODECS:
        raise ValueError(
            f"Disallowed codec: '{codec}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_VIDEO_CODECS))}"
        )
    return codec


def validate_format_spec(fmt):
    """Validate a video format spec dict from CLI JSON input."""
    codec = fmt.get("codec", "libx264")
    validate_codec(codec)

    fps = fmt.get("fps", 30)
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise ValueError(f"Invalid fps value: {fps}")

    resolution = fmt.get("resolution")
    if resolution and not re.match(r"^\d{1,5}x\d{1,5}$", resolution):
        raise ValueError(f"Invalid resolution format: {resolution}")

    max_dur = fmt.get("max_duration_sec")
    if max_dur is not None and (not isinstance(max_dur, (int, float)) or max_dur <= 0):
        raise ValueError(f"Invalid max_duration_sec: {max_dur}")

    return fmt
