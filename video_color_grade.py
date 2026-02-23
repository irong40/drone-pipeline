"""
Sentinel Aerial Inspections — Video Color Grading (Step V1)

Applies Sentinel branded LUTs to raw drone video via FFmpeg.
Selects LUT based on source platform: DLogM for M4E/M3E, DCinelike for Mini 4 Pro.

Usage:
    python video_color_grade.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218
    python video_color_grade.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218 --platform mini4pro
    python video_color_grade.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218 --lut custom.cube
"""

import os
import sys
import glob
import argparse
import subprocess
import logging
from pathlib import Path

# ─── CONFIG ──────────────────────────────────────────────────────────────────

LUT_DIR = r"E:\Sentinel\LUTs"
LOG_DIR = r"E:\Sentinel\logs"
FFMPEG_BIN = "ffmpeg"  # Assumes ffmpeg is on PATH
CRF_QUALITY = 18  # Lower = better quality, 18 is visually lossless
VIDEO_CODEC = "libx264"

# Platform → LUT mapping
PLATFORM_LUTS = {
    "m4e": "Sentinel_DLogM.cube",
    "m3e": "Sentinel_DLogM.cube",
    "mini4pro": "Sentinel_DCinelike.cube",
}

VIDEO_EXTENSIONS = {"*.mp4", "*.MP4", "*.mov", "*.MOV"}


# ─── LOGGING ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "video_color_grade.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── COLOR GRADING ───────────────────────────────────────────────────────────

def find_videos(mission_path):
    """Find all video files in video/full/ subfolder."""
    video_dir = os.path.join(mission_path, "video", "full")
    if not os.path.isdir(video_dir):
        return []

    videos = []
    for pattern in VIDEO_EXTENSIONS:
        videos.extend(glob.glob(os.path.join(video_dir, pattern)))

    return sorted(set(videos))


def get_lut_path(platform, lut_override=None, lut_dir=LUT_DIR):
    """Resolve LUT file path based on platform or override."""
    if lut_override:
        # Allow absolute path or filename in LUT_DIR
        if os.path.isabs(lut_override) and os.path.isfile(lut_override):
            return lut_override
        path = os.path.join(lut_dir, lut_override)
        if os.path.isfile(path):
            return path
        return None

    lut_name = PLATFORM_LUTS.get(platform)
    if not lut_name:
        return None

    path = os.path.join(lut_dir, lut_name)
    if os.path.isfile(path):
        return path
    return None


def grade_video(input_path, output_path, lut_path, crf=CRF_QUALITY, codec=VIDEO_CODEC):
    """Apply LUT to a single video file using FFmpeg.

    Command: ffmpeg -i input.mp4 -vf lut3d=LUT_PATH -c:v libx264 -crf 18 output.mp4
    """
    # Escape LUT path for FFmpeg filter syntax (backslashes and colons are special)
    escaped_lut = lut_path.replace("\\", "/").replace(":", "\\:")

    cmd = [
        FFMPEG_BIN,
        "-y",  # Overwrite output
        "-i", input_path,
        "-vf", f"lut3d='{escaped_lut}'",
        "-c:v", codec,
        "-crf", str(crf),
        "-c:a", "copy",  # Copy audio without re-encoding
        output_path,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    return result.returncode == 0, result.stderr


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Video Color Grading (Step V1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Applies Sentinel branded LUTs to drone video clips using FFmpeg lut3d filter.

Examples:
  python video_color_grade.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218
  python video_color_grade.py path/to/mission --platform m4e
  python video_color_grade.py path/to/mission --lut MyCustom.cube
        """,
    )
    parser.add_argument("mission_path", help="Path to mission folder")
    parser.add_argument("--platform", choices=["mini4pro", "m4e", "m3e"], default="mini4pro",
                        help="Drone platform for LUT selection (default: mini4pro)")
    parser.add_argument("--lut", help="Override LUT filename or path")
    parser.add_argument("--lut-dir", default=LUT_DIR, help=f"LUT directory (default: {LUT_DIR})")
    parser.add_argument("--crf", type=int, default=CRF_QUALITY, help=f"FFmpeg CRF quality (default: {CRF_QUALITY})")
    parser.add_argument("--codec", default=VIDEO_CODEC, help=f"Video codec (default: {VIDEO_CODEC})")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    args = parser.parse_args()

    log = setup_logging()

    mission_path = os.path.abspath(args.mission_path)
    if not os.path.isdir(mission_path):
        sys.exit(f"Mission folder not found: {mission_path}")

    # Resolve LUT
    lut_path = get_lut_path(args.platform, lut_override=args.lut, lut_dir=args.lut_dir)
    if not lut_path:
        sys.exit(f"LUT not found for platform '{args.platform}' in {args.lut_dir}")

    log.info(f"Mission:  {mission_path}")
    log.info(f"Platform: {args.platform}")
    log.info(f"LUT:      {lut_path}")

    # Find videos
    videos = find_videos(mission_path)
    if not videos:
        log.info("No video files found in video/full/")
        return

    log.info(f"Found {len(videos)} video(s)")

    # Create output directory
    graded_dir = os.path.join(mission_path, "video", "graded")
    os.makedirs(graded_dir, exist_ok=True)

    # Process each video
    results = []
    for video_path in videos:
        filename = os.path.basename(video_path)
        name, ext = os.path.splitext(filename)
        output_path = os.path.join(graded_dir, f"{name}_graded{ext}")

        log.info(f"  Grading: {filename}")

        if args.dry_run:
            log.info(f"  [DRY RUN] → {output_path}")
            continue

        ok, stderr = grade_video(video_path, output_path, lut_path, crf=args.crf, codec=args.codec)

        if ok:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log.info(f"  OK: {output_path} ({size_mb:.1f} MB)")
            results.append({"input": video_path, "output": output_path, "status": "ok"})
        else:
            log.error(f"  FAILED: {filename}")
            log.error(f"  FFmpeg stderr: {stderr[-500:]}")
            results.append({"input": video_path, "output": None, "status": "failed"})

    # Summary
    ok_count = sum(1 for r in results if r["status"] == "ok")
    fail_count = sum(1 for r in results if r["status"] == "failed")
    log.info(f"\nColor grading complete: {ok_count} ok, {fail_count} failed")


if __name__ == "__main__":
    main()
