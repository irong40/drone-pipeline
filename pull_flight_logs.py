#!/usr/bin/env python3
"""
Sentinel Aerial — Flight Log Puller

Pulls DJI Fly flight records (.txt) from a connected DJI RC 2 over USB/MTP
and files them into monthly subfolders under E:\\Sentinel\\FlightLogs\\.
Skips files already local (filename diff). DJI Fly .txt logs are native
AirData format — no transformation needed; drag the month folder contents
to airdata.com/upload after pulling.

Usage:
    python pull_flight_logs.py
    python pull_flight_logs.py --dest "D:/custom/path"
    python pull_flight_logs.py --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import win32com.client
    from pywintypes import com_error
except ImportError:
    sys.exit("Requires pywin32 (already in requirements.txt — pip install pywin32)")

SCRIPT_NAME = "pull_flight_logs"
logger = logging.getLogger(SCRIPT_NAME)

DEFAULT_DEST = Path(r"E:\Sentinel\FlightLogs")

# Known paths to DJI Fly's FlightRecord directory on Android-based DJI remotes.
# Listed in probability order — first match wins.
DJI_FLIGHT_RECORD_PATHS = [
    ["Internal Storage", "Android", "data", "dji.go.v5", "files", "FlightRecord"],
    ["Internal shared storage", "Android", "data", "dji.go.v5", "files", "FlightRecord"],
    ["Internal Storage", "DJI", "dji.go.v5", "CACHE", "FlightRecord"],
    ["Internal Storage", "Android", "data", "dji.pilot", "files", "FlightRecord"],
]

CSIDL_DRIVES = 17  # "This PC" shell namespace id
FILENAME_DATE_RE = re.compile(r"DJIFlightRecord_(\d{4})-(\d{2})-\d{2}")

# CopyHere flag bits: 16 = auto-replace, 4 = no progress dialog, 512 = no confirmation
COPY_FLAGS = 16 | 4 | 512
COPY_TIMEOUT_S = 45
SIZE_STABLE_WINDOW_S = 0.6


def find_rc_device(shell):
    """Find a DJI remote controller in 'This PC'. Returns the FolderItem or None."""
    pc = shell.NameSpace(CSIDL_DRIVES)
    candidates = []
    for item in pc.Items():
        name_lower = item.Name.lower()
        candidates.append(item.Name)
        if any(k in name_lower for k in ("dji rc", "rc 2", "rc2", "rc-n", "dji remote", "remotecontroller", "dji pilot")):
            logger.info("Found device: %s", item.Name)
            return item

    # Fallback: try generic "DJI" or "RC" match if nothing more specific hit
    for item in pc.Items():
        name_lower = item.Name.lower()
        if "dji" in name_lower or name_lower.startswith("rc"):
            logger.info("Found device (fallback match): %s", item.Name)
            return item

    logger.debug("Devices seen in 'This PC': %s", candidates)
    return None


def walk_folder(root_item, segments):
    """Navigate a chain of named subfolders from a starting shell folder item."""
    current = root_item.GetFolder if hasattr(root_item, "GetFolder") else root_item
    for seg in segments:
        if current is None:
            return None
        found = None
        try:
            for item in current.Items():
                if item.Name.lower() == seg.lower():
                    found = item
                    break
        except com_error as e:
            logger.debug("COM error while enumerating %r: %s", seg, e)
            return None
        if found is None:
            try:
                listing = [i.Name for i in current.Items()]
            except com_error:
                listing = ["<enumeration failed>"]
            logger.debug("Segment %r not found. Siblings: %s", seg, listing)
            return None
        current = found.GetFolder
    return current


def find_flight_records(shell, rc_item):
    """Try each known path to FlightRecord. Returns Folder or None."""
    for segments in DJI_FLIGHT_RECORD_PATHS:
        logger.debug("Trying path: %s", " / ".join(segments))
        folder = walk_folder(rc_item, segments)
        if folder is not None:
            logger.info("FlightRecord folder located: %s", " / ".join(segments))
            return folder
    return None


def month_folder_for(filename: str, dest_root: Path) -> Path:
    """Return the YYYY-MM subfolder derived from a DJI log filename."""
    m = FILENAME_DATE_RE.match(filename)
    if m:
        return dest_root / f"{m.group(1)}-{m.group(2)}"
    return dest_root / datetime.now().strftime("%Y-%m")


def existing_filenames(dest_root: Path) -> set[str]:
    """All .txt filenames already under dest_root (any depth)."""
    if not dest_root.exists():
        return set()
    return {p.name for p in dest_root.rglob("*.txt")}


def wait_for_copy(target_file: Path, timeout_s: float = COPY_TIMEOUT_S) -> bool:
    """Shell CopyHere is async. Wait for file to appear and size to stabilize."""
    deadline = time.time() + timeout_s
    last_size = -1
    stable_since = None
    while time.time() < deadline:
        if target_file.exists():
            size = target_file.stat().st_size
            if size > 0:
                if size == last_size:
                    if stable_since and (time.time() - stable_since) >= SIZE_STABLE_WINDOW_S:
                        return True
                    if not stable_since:
                        stable_since = time.time()
                else:
                    last_size = size
                    stable_since = None
        time.sleep(0.2)
    return False


def copy_flight_records(flight_folder, dest_root: Path, shell) -> dict:
    """Copy .txt files not already local. Returns a stats dict."""
    existing = existing_filenames(dest_root)
    logger.info("Local inventory: %d existing .txt files under %s", len(existing), dest_root)

    to_copy = []
    for item in flight_folder.Items():
        if not item.Name.lower().endswith(".txt"):
            continue
        if item.Name in existing:
            continue
        to_copy.append(item)

    logger.info("Remote has %d new logs to pull", len(to_copy))

    copied = 0
    failed = 0
    bytes_copied = 0
    copied_files: list[str] = []

    for item in to_copy:
        target_dir = month_folder_for(item.Name, dest_root)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / item.Name

        shell_ns = shell.NameSpace(str(target_dir))
        try:
            shell_ns.CopyHere(item, COPY_FLAGS)
        except com_error as e:
            logger.warning("CopyHere failed for %s: %s", item.Name, e)
            failed += 1
            continue

        if not wait_for_copy(target_file):
            logger.warning("Timeout (%ss) waiting for %s", COPY_TIMEOUT_S, item.Name)
            failed += 1
            continue

        size = target_file.stat().st_size
        bytes_copied += size
        copied += 1
        copied_files.append(str(target_file))
        logger.info("  %s -> %s (%.1f KB)", item.Name, target_dir.name, size / 1024)

    return {
        "copied": copied,
        "failed": failed,
        "already_local": len(existing),
        "bytes_copied": bytes_copied,
        "copied_files": copied_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pull DJI Fly flight records from connected RC over MTP/USB."
    )
    parser.add_argument("--dest", default=str(DEFAULT_DEST),
                        help=f"Destination root (default {DEFAULT_DEST})")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Log device-walk details for troubleshooting")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    dest_root = Path(args.dest)

    try:
        shell = win32com.client.Dispatch("Shell.Application")
    except com_error as e:
        print(json.dumps({"status": "error", "error": f"COM init failed: {e}"}), file=sys.stderr)
        return 1

    rc = find_rc_device(shell)
    if rc is None:
        print(json.dumps({
            "status": "error",
            "error": "No DJI RC detected. Plug RC 2 via USB, power it on, and wait for Windows to enumerate the device (5-10 seconds).",
        }))
        return 1

    try:
        flight_folder = find_flight_records(shell, rc)
    except com_error as e:
        print(json.dumps({"status": "error", "error": f"MTP walk failed: {e}"}), file=sys.stderr)
        return 1

    if flight_folder is None:
        print(json.dumps({
            "status": "error",
            "error": "FlightRecord folder not found on RC. Fly at least once with DJI Fly to create logs, or pass --verbose and check the listed paths.",
        }))
        return 1

    try:
        stats = copy_flight_records(flight_folder, dest_root, shell)
    except Exception as e:
        logger.exception("Copy stage failed")
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        return 1

    result = {
        "status": "ok",
        "dest": str(dest_root),
        **stats,
    }
    print(json.dumps(result))
    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
