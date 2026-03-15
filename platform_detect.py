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
import re
import glob
import json
import subprocess
import logging
from collections import Counter

from pipeline_utils import setup_logging

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "platform_detect"
FFPROBE_BIN = "ffprobe"

# DJI EXIF Model tag → pipeline platform ID
# DJI uses internal camera module codes in EXIF. These map to the commercial
# product names. Sources: DJI SDK docs, community EXIF databases.
EXIF_MODEL_MAP = {
    # Mini 4 Pro
    "FC8282": "mini4pro",
    "DJI Mini 4 Pro": "mini4pro",
    "L2D-Mini4Pro": "mini4pro",
    # Matrice 4E
    "FC9100": "m4e",
    "DJI Matrice 4E": "m4e",
    "M4E": "m4e",
    # Mavic 3 Enterprise
    "FC8482": "m3e",
    "L2D-20c": "m3e",
    "DJI Mavic 3E": "m3e",
    "DJI Mavic 3 Enterprise": "m3e",
    "M3E": "m3e",
    # Mavic 3 Enterprise (thermal camera)
    "M3T": "m3e",
    "DJI Mavic 3T": "m3e",
}

# Patterns to search for in ffprobe metadata strings
FFPROBE_MODEL_PATTERNS = [
    (re.compile(r"mini\s*4\s*pro", re.IGNORECASE), "mini4pro"),
    (re.compile(r"matrice\s*4\s*e", re.IGNORECASE), "m4e"),
    (re.compile(r"mavic\s*3\s*(enterprise|e\b|t\b)", re.IGNORECASE), "m3e"),
    (re.compile(r"\bM4E\b"), "m4e"),
    (re.compile(r"\bM3E\b"), "m3e"),
    (re.compile(r"\bM3T\b"), "m3e"),
    (re.compile(r"\bFC8282\b"), "mini4pro"),
    (re.compile(r"\bFC9100\b"), "m4e"),
    (re.compile(r"\bFC8482\b"), "m3e"),
]

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".dng"}
VIDEO_EXTENSIONS = {".mp4", ".mov"}

log = logging.getLogger(__name__)


# ─── EXIF DETECTION (PHOTOS) ────────────────────────────────────────────────

def detect_from_exiftool(photo_path):
    """Read XMP-drone-dji namespace via pyexiftool for reliable platform detection.

    The XMP-drone-dji:Model tag is the most reliable way to distinguish
    M4E from M3E, as both share the same filename pattern. Also reads
    AbsoluteAltitude, GimbalYawDegree, and other flight metadata.

    Returns (platform, metadata_dict) or (None, None).
    """
    try:
        import exiftool
    except ImportError:
        return None, None

    try:
        with exiftool.ExifToolHelper() as et:
            metadata_list = et.get_metadata(str(photo_path))
            if not metadata_list:
                return None, None
            meta = metadata_list[0]

            # Try XMP drone-dji model (most reliable for M4E vs M3E)
            xmp_model = meta.get("XMP:Model", "")
            exif_model = meta.get("EXIF:Model", "")
            make = meta.get("EXIF:Make", "")

            # Check XMP model first
            for candidate in [xmp_model, exif_model]:
                if candidate in EXIF_MODEL_MAP:
                    return EXIF_MODEL_MAP[candidate], meta
                # Case-insensitive substring
                for key, platform in EXIF_MODEL_MAP.items():
                    if key.upper() in str(candidate).upper():
                        return platform, meta

            # Pattern match on combined metadata
            combined = f"{xmp_model} {exif_model} {make}"
            for pattern, platform in FFPROBE_MODEL_PATTERNS:
                if pattern.search(combined):
                    return platform, meta

            if xmp_model or exif_model:
                log.debug(f"Unrecognized DJI model: XMP='{xmp_model}', EXIF='{exif_model}'")

            return None, meta

    except Exception:
        return None, None


def detect_from_exif(photo_path):
    """Read EXIF Model tag from a photo to identify the drone.

    Tries pyexiftool first (XMP-drone-dji namespace, most reliable),
    falls back to Pillow EXIF if exiftool is not installed.
    Returns platform string or None.
    """
    # Try pyexiftool first — reads XMP-drone-dji namespace
    platform, _ = detect_from_exiftool(photo_path)
    if platform:
        return platform

    # Fallback to Pillow EXIF
    try:
        from PIL import Image
    except ImportError:
        return None

    try:
        img = Image.open(photo_path)
        exif_data = img.getexif()
        if not exif_data:
            return None

        # Tag 272 = Model, Tag 271 = Make
        model = exif_data.get(272, "")  # Model
        make = exif_data.get(271, "")   # Make

        # Try direct model lookup
        if model in EXIF_MODEL_MAP:
            return EXIF_MODEL_MAP[model]

        # Try case-insensitive substring match on model
        model_upper = model.upper().strip()
        for key, platform in EXIF_MODEL_MAP.items():
            if key.upper() in model_upper:
                return platform

        # Try make field
        make_upper = make.upper().strip()
        if make_upper and "DJI" in make_upper:
            # DJI confirmed but model not recognized — try patterns
            for pattern, platform in FFPROBE_MODEL_PATTERNS:
                if pattern.search(model):
                    return platform

        # DJI camera detected but specific model unknown
        if model:
            log.debug(f"Unrecognized DJI EXIF model: '{model}' (make: '{make}')")

        return None

    except Exception:
        return None


# ─── FFPROBE DETECTION (VIDEO) ──────────────────────────────────────────────

def detect_from_ffprobe(video_path):
    """Read video metadata via ffprobe to identify the drone.

    DJI embeds camera info in video container metadata (format tags
    and stream side data). Returns platform string or None.
    """
    cmd = [
        FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        video_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None

    # Search all metadata fields for model identifiers
    searchable_text = _extract_metadata_text(data)

    for pattern, platform in FFPROBE_MODEL_PATTERNS:
        if pattern.search(searchable_text):
            return platform

    return None


def _extract_metadata_text(ffprobe_data):
    """Flatten all ffprobe metadata tags into a single searchable string."""
    parts = []

    # Format-level tags
    fmt = ffprobe_data.get("format", {})
    tags = fmt.get("tags", {})
    for key, value in tags.items():
        parts.append(f"{key}={value}")

    # Stream-level tags
    for stream in ffprobe_data.get("streams", []):
        stream_tags = stream.get("tags", {})
        for key, value in stream_tags.items():
            parts.append(f"{key}={value}")
        # Also check codec_long_name, encoder, etc.
        for field in ["codec_long_name", "encoder"]:
            if stream.get(field):
                parts.append(stream[field])

    return " ".join(parts)


# ─── FILENAME FALLBACK ──────────────────────────────────────────────────────

def detect_from_filename(filename):
    """Detect platform from DJI filename pattern.

    Mini 4 Pro: DJI_NNNN.EXT
    M4E / M3E:  DJI_YYYYMMDDHHMMSS_NNNN_X.EXT (cannot distinguish)
    """
    basename = os.path.basename(filename)
    if re.match(r"DJI_\d{14}_\d{4}_", basename, re.IGNORECASE):
        return "m4e"  # Ambiguous — could be m3e
    if re.match(r"DJI_\d{4}\.", basename, re.IGNORECASE):
        return "mini4pro"
    return None


# ─── COMPOSITE DETECTION ────────────────────────────────────────────────────

def detect_platform_from_file(file_path):
    """Detect platform from a single file using best available method.

    Returns (platform, method) tuple. Method is one of:
    "exif", "ffprobe", "filename", or None if detection failed.
    """
    ext = os.path.splitext(file_path)[1].lower()

    # Try EXIF for photos
    if ext in PHOTO_EXTENSIONS:
        platform = detect_from_exif(file_path)
        if platform:
            return platform, "exif"

    # Try ffprobe for video
    if ext in VIDEO_EXTENSIONS:
        platform = detect_from_ffprobe(file_path)
        if platform:
            return platform, "ffprobe"

    # Filename fallback
    platform = detect_from_filename(file_path)
    if platform:
        return platform, "filename"

    return None, None


def detect_platform_from_folder(folder_path, max_samples=5):
    """Detect platform by sampling files from a mission folder.

    Checks photos first (EXIF is most reliable), then video if needed.
    Samples up to max_samples files to build confidence.

    Returns (platform, confidence, method) tuple.
    Confidence: "confirmed" (EXIF/ffprobe match), "likely" (filename only),
    "ambiguous" (mixed detections), or "unknown".
    """
    detections = []

    # Prefer photos for EXIF — check jpeg/ first, then raw/
    for photo_subdir in ["photos/jpeg", "photos/raw"]:
        photo_dir = os.path.join(folder_path, photo_subdir)
        if not os.path.isdir(photo_dir):
            continue
        for fname in sorted(os.listdir(photo_dir))[:max_samples]:
            ext = os.path.splitext(fname)[1].lower()
            if ext in PHOTO_EXTENSIONS:
                fpath = os.path.join(photo_dir, fname)
                platform, method = detect_platform_from_file(fpath)
                if platform and method == "exif":
                    detections.append((platform, method))

    # If EXIF didn't resolve, try video
    if not detections:
        video_dir = os.path.join(folder_path, "video", "full")
        if os.path.isdir(video_dir):
            for fname in sorted(os.listdir(video_dir))[:max_samples]:
                ext = os.path.splitext(fname)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    fpath = os.path.join(video_dir, fname)
                    platform, method = detect_platform_from_file(fpath)
                    if platform and method == "ffprobe":
                        detections.append((platform, method))

    # If metadata detection found results, use consensus
    if detections:
        platforms = set(d[0] for d in detections)
        methods = set(d[1] for d in detections)

        if len(platforms) == 1:
            platform = platforms.pop()
            confidence = "confirmed"
            method = methods.pop() if len(methods) == 1 else "mixed"
            return platform, confidence, method
        else:
            # Multiple platforms detected — unusual, pick majority
            counts = Counter(d[0] for d in detections)
            platform = counts.most_common(1)[0][0]
            return platform, "ambiguous", "mixed"

    # Last resort: filename pattern from any file in the folder (top-level + one subdirectory depth)
    for root, dirs, filenames in os.walk(folder_path):
        depth = root.replace(str(folder_path), "").count(os.sep)
        if depth > 1:
            continue
        for fname in filenames:
            if fname.upper().startswith("DJI_"):
                platform = detect_from_filename(fname)
                if platform:
                    return platform, "likely", "filename"

    return None, "unknown", None


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
