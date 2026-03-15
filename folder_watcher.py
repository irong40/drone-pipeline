"""
Sentinel Aerial Inspections — Folder Watcher Service

Monitors E:\\incoming\\ for new mission folders.
Waits 60 seconds after last file write, then fires POST to n8n webhook.

Usage:
    python folder_watcher.py
    python folder_watcher.py --watch-dir E:\\incoming --debounce 60
    python folder_watcher.py --install-service
"""

import os
import sys
import time
import json
import argparse
import logging
import threading
import requests
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

from pipeline_utils import LOG_DIR, PHOTO_EXTS, VIDEO_EXTS, PPK_EXTS, setup_logging

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    sys.exit("pip install watchdog")

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "folder_watcher"
WATCH_DIR = r"E:\incoming"
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/folder-watcher")
DEBOUNCE_SECONDS = 60  # Wait this long after last file write before triggering

# File extensions we care about
KNOWN_EXTENSIONS = {
    "DNG", "JPG", "JPEG", "MP4", "MOV", "LRF", "SRT",
    "MRK", "NAV", "OBS", "BIN", "RTK",
}



# ─── FILE INVENTORY ──────────────────────────────────────────────────────────

def parse_mission_number(folder_name):
    """Extract mission number from SAI_MNNNN_... folder name."""
    import re
    m = re.match(r"SAI_M(\d{4})_", folder_name)
    return int(m.group(1)) if m else None


def build_inventory(folder_path):
    """Count files by type in a mission folder."""
    photo_count = 0
    video_count = 0
    has_ppk = False
    total_size = 0

    photo_exts = PHOTO_EXTS
    video_exts = VIDEO_EXTS
    ppk_exts = PPK_EXTS

    for root, _, filenames in os.walk(folder_path):
        for fname in filenames:
            fpath = os.path.join(root, fname)
            ext = os.path.splitext(fname)[1].lstrip(".").upper()
            size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
            total_size += size

            if ext in photo_exts:
                photo_count += 1
            elif ext in video_exts:
                video_count += 1
            elif ext in ppk_exts:
                has_ppk = True

    folder_name = os.path.basename(folder_path)
    mission_number = parse_mission_number(folder_name)

    return {
        "folder_path": str(folder_path),
        "folder_name": folder_name,
        "mission_number": mission_number,
        "photo_count": photo_count,
        "video_count": video_count,
        "has_ppk_data": has_ppk,
        "total_size_bytes": total_size,
        "detected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# ─── WEBHOOK ─────────────────────────────────────────────────────────────────

def fire_webhook(inventory, webhook_url=N8N_WEBHOOK_URL):
    """POST folder inventory to n8n webhook."""
    log = logging.getLogger(__name__)
    from pipeline_utils import validate_webhook_url
    try:
        validate_webhook_url(webhook_url)
    except ValueError as e:
        log.error(f"Webhook blocked: {e}")
        return False
    try:
        resp = requests.post(webhook_url, json=inventory, timeout=10)
        resp.raise_for_status()
        log.info(f"Webhook OK: {resp.status_code}")
        return True
    except requests.RequestException as e:
        log.error(f"Webhook failed: {e}")
        return False


# ─── DEBOUNCE HANDLER ────────────────────────────────────────────────────────

class MissionFolderHandler(FileSystemEventHandler):
    """Watches for new files in mission folders with debounce logic."""

    def __init__(self, watch_dir=WATCH_DIR, debounce_seconds=DEBOUNCE_SECONDS, webhook_url=N8N_WEBHOOK_URL):
        super().__init__()
        self.log = logging.getLogger(__name__)
        self.watch_dir = watch_dir
        self.debounce_seconds = debounce_seconds
        self.webhook_url = webhook_url
        self._timers = {}  # folder_name → Timer
        self._lock = threading.Lock()
        self._triggered = set()  # folders already triggered

    def _get_mission_folder(self, path):
        """Extract the top-level mission folder name from a file path."""
        rel = os.path.relpath(path, self.watch_dir)
        parts = Path(rel).parts
        if parts:
            return parts[0]
        return None

    def on_created(self, event):
        if event.is_directory:
            folder_name = os.path.basename(event.src_path)
            # New top-level directory — start watching
            if os.path.dirname(event.src_path) == self.watch_dir:
                self.log.info(f"New mission folder detected: {folder_name}")
                self._reset_timer(folder_name)
            return

        folder_name = self._get_mission_folder(event.src_path)
        if folder_name:
            self._reset_timer(folder_name)

    def on_modified(self, event):
        if event.is_directory:
            return
        folder_name = self._get_mission_folder(event.src_path)
        if folder_name:
            self._reset_timer(folder_name)

    def _reset_timer(self, folder_name):
        """Reset the debounce timer for a mission folder."""
        with self._lock:
            if folder_name in self._triggered:
                return  # Already processed

            if folder_name in self._timers:
                self._timers[folder_name].cancel()

            timer = threading.Timer(
                self.debounce_seconds,
                self._on_debounce_complete,
                args=[folder_name],
            )
            timer.daemon = True
            timer.start()
            self._timers[folder_name] = timer

    def _on_debounce_complete(self, folder_name):
        """Called when debounce period elapses with no new writes."""
        with self._lock:
            self._triggered.add(folder_name)
            if folder_name in self._timers:
                del self._timers[folder_name]

        folder_path = os.path.join(self.watch_dir, folder_name)
        self.log.info(f"Debounce complete for: {folder_name}")

        inventory = build_inventory(folder_path)
        self.log.info(
            f"  Photos: {inventory['photo_count']}, "
            f"Videos: {inventory['video_count']}, "
            f"PPK: {inventory['has_ppk_data']}, "
            f"Size: {inventory['total_size_bytes'] / (1024*1024):.1f} MB"
        )

        fire_webhook(inventory, self.webhook_url)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Folder Watcher Service",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Monitors the incoming folder for new mission directories.
Waits for file writes to stop, then fires a webhook to n8n.

Examples:
  python folder_watcher.py
  python folder_watcher.py --watch-dir E:\\incoming --debounce 60
  python folder_watcher.py --webhook-url http://localhost:5678/webhook/ingest
        """,
    )
    parser.add_argument("--watch-dir", default=WATCH_DIR, help=f"Directory to watch (default: {WATCH_DIR})")
    parser.add_argument("--debounce", type=int, default=DEBOUNCE_SECONDS, help=f"Seconds to wait after last write (default: {DEBOUNCE_SECONDS})")
    parser.add_argument("--webhook-url", default=N8N_WEBHOOK_URL, help="n8n webhook URL")
    parser.add_argument("--once", action="store_true", help="Process existing folders once and exit")
    args = parser.parse_args()

    setup_logging(SCRIPT_NAME)
    log = logging.getLogger(__name__)

    watch_dir = args.watch_dir
    os.makedirs(watch_dir, exist_ok=True)

    log.info(f"Folder watcher starting")
    log.info(f"  Watch dir:  {watch_dir}")
    log.info(f"  Debounce:   {args.debounce}s")
    log.info(f"  Webhook:    {args.webhook_url}")

    if args.once:
        # Process all existing folders immediately
        for name in os.listdir(watch_dir):
            folder_path = os.path.join(watch_dir, name)
            if os.path.isdir(folder_path) and name.startswith("SAI_"):
                log.info(f"Processing existing folder: {name}")
                inventory = build_inventory(folder_path)
                fire_webhook(inventory, args.webhook_url)
        return

    handler = MissionFolderHandler(
        watch_dir=watch_dir,
        debounce_seconds=args.debounce,
        webhook_url=args.webhook_url,
    )
    observer = Observer()
    observer.schedule(handler, watch_dir, recursive=True)
    observer.start()

    log.info("Watching for new mission folders... (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down...")
        observer.stop()

    observer.join()
    log.info("Folder watcher stopped.")


if __name__ == "__main__":
    main()
