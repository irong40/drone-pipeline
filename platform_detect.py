"""
Sentinel Aerial Inspections — Drone Platform Detection

Identifies the exact DJI drone platform from media files using EXIF metadata
(photos) and ffprobe metadata (video). Resolves the M4E vs M3E ambiguity
since both share the same DJI_YYYYMMDDHHMMSS_NNNN_X.EXT filename pattern.

Detection priority:
  1. Photo EXIF — Model tag (most reliable)
  2. Video ffprobe — encoder/make metadata
  3. Filename pattern fallback (cannot distinguish M4E from M3E)

Usage as module:
    from platform_detect import detect_platform_from_folder

    platform = detect_platform_from_folder("E:\\incoming\\SAI_M0047...")
    # Returns: "mini4pro", "m4e", or "m3e"

Usage as CLI:
    python platform_detect.py E:\\incoming\\SAI_M0047_RE_Standard_20260218
    python platform_detect.py E:/DCIM/DJI_001
    python platform_detect.py path/to/single_photo.JPG
"""

import os
import sys
import json
import logging

from pipeline_utils import setup_logging

SCRIPT_NAME = "platform_detect"

from sentinel_core.platform import (
    detect_from_exiftool,
    detect_from_exif,
    detect_from_ffprobe,
    detect_from_filename,
    detect_platform_from_file,
    detect_platform_from_folder,
    _extract_metadata_text,
    EXIF_MODEL_MAP,
    FFPROBE_MODEL_PATTERNS,
)
from sentinel_core.constants import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS

log = logging.getLogger(__name__)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Drone Platform Detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Identifies DJI drone platform from media files using EXIF and ffprobe.

Examples:
  python platform_detect.py E:\\incoming\\SAI_M0047_RE_Standard_20260218
  python platform_detect.py E:/DCIM/DJI_001
  python platform_detect.py path/to/DJI_0015.JPG
  python platform_detect.py path/to/DJI_0015.MP4
        """,
    )
    parser.add_argument("path", help="Mission folder or single media file")
    parser.add_argument("--samples", type=int, default=5,
                        help="Max files to sample per folder (default: 5)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed detection info")
    args = parser.parse_args()

    setup_logging(SCRIPT_NAME)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    target = os.path.abspath(args.path)

    if os.path.isfile(target):
        platform, method = detect_platform_from_file(target)
        if platform:
            print(json.dumps({
                "platform": platform,
                "method": method,
                "file": target,
            }))
        else:
            print(json.dumps({"platform": None, "error": "Could not detect platform"}))
            sys.exit(1)

    elif os.path.isdir(target):
        platform, confidence, method = detect_platform_from_folder(
            target, max_samples=args.samples
        )
        print(json.dumps({
            "platform": platform,
            "confidence": confidence,
            "method": method,
            "folder": target,
        }))
        if platform is None:
            sys.exit(1)

    else:
        sys.exit(f"Path not found: {target}")


if __name__ == "__main__":
    main()
