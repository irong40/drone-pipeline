"""
Sentinel Aerial Inspections — Video Proxy Generation (Step V4)

Generates 1080p proxy files from graded 4K clips for efficient editing
in DaVinci Resolve. Runs after color grading (V1) and QA (V3), before
the manual edit step (V5).

Reads from video/graded/ (or video/full/ if no graded clips exist).
Writes to video/proxy/, replacing camera-generated LRF proxy files.

Usage:
    python video_proxy_gen.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218
    python video_proxy_gen.py path/to/mission --resolution 1920x1080
    python video_proxy_gen.py path/to/mission --dry-run
"""

import os
import sys
import re
import glob
import argparse
import subprocess
import logging

# ─── CONFIG ──────────────────────────────────────────────────────────────────

FFMPEG_BIN = "ffmpeg"
LOG_DIR = r"E:\Sentinel\logs"
PROXY_RESOLUTION = "1920x1080"
PROXY_CRF = 23  # Fast, decent quality — proxies are for editing, not delivery
PROXY_PRESET = "fast"
PROXY_CODEC = "libx264"

VIDEO_EXTENSIONS = {"*.mp4", "*.MP4", "*.mov", "*.MOV"}


# ─── LOGGING ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "video_proxy_gen.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── PROXY GENERATION ────────────────────────────────────────────────────────

def check_ffmpeg():
    """Verify FFmpeg is installed and accessible."""
    try:
        subprocess.run(
            [FFMPEG_BIN, "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def find_source_videos(mission_path):
    """Find source videos — prefer graded/ (V1 output), fall back to full/ (raw)."""
    graded_dir = os.path.join(mission_path, "video", "graded")
    full_dir = os.path.join(mission_path, "video", "full")

    # Prefer graded clips if they exist
    for source_dir in [graded_dir, full_dir]:
        if not os.path.isdir(source_dir):
            continue
        videos = []
        for pattern in VIDEO_EXTENSIONS:
            videos.extend(glob.glob(os.path.join(source_dir, pattern)))
        if videos:
            return sorted(set(videos)), source_dir

    return [], None


def generate_proxy(input_path, output_path, resolution=PROXY_RESOLUTION,
                   crf=PROXY_CRF, preset=PROXY_PRESET, codec=PROXY_CODEC):
    """Generate a 1080p proxy from a single video file.

    Command: ffmpeg -i input.mp4 -vf scale=1920:1080 -c:v libx264 -preset fast -crf 23 proxy.mp4
    """
    # Validate resolution format
    if not re.match(r"^\d{1,5}x\d{1,5}$", resolution):
        raise ValueError(f"Invalid resolution format: {resolution}")

    w, h = resolution.split("x")

    cmd = [
        FFMPEG_BIN,
        "-y",
        "-i", input_path,
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
        "-c:v", codec,
        "-preset", preset,
        "-crf", str(crf),
        "-c:a", "copy",
        output_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Video Proxy Generation (Step V4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Generates 1080p proxy files for efficient editing in DaVinci Resolve.
Reads from video/graded/ (preferred) or video/full/ (fallback).

Examples:
  python video_proxy_gen.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218
  python video_proxy_gen.py path/to/mission --resolution 1920x1080
  python video_proxy_gen.py path/to/mission --crf 20 --preset medium
  python video_proxy_gen.py path/to/mission --dry-run
        """,
    )
    parser.add_argument("mission_path", help="Path to mission folder")
    parser.add_argument("--resolution", default=PROXY_RESOLUTION,
                        help=f"Proxy resolution WxH (default: {PROXY_RESOLUTION})")
    parser.add_argument("--crf", type=int, default=PROXY_CRF,
                        help=f"FFmpeg CRF quality (default: {PROXY_CRF})")
    parser.add_argument("--preset", default=PROXY_PRESET,
                        choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium"],
                        help=f"FFmpeg preset (default: {PROXY_PRESET})")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    args = parser.parse_args()

    log = setup_logging()

    # Pre-flight: check FFmpeg
    if not args.dry_run and not check_ffmpeg():
        log.error("FFmpeg not found. Install from https://ffmpeg.org/download.html and add to PATH.")
        sys.exit(2)

    mission_path = os.path.abspath(args.mission_path)
    if not os.path.isdir(mission_path):
        log.error(f"Mission folder not found: {mission_path}")
        sys.exit(2)

    # Find source videos
    videos, source_dir = find_source_videos(mission_path)
    if not videos:
        log.info("No video files found in video/graded/ or video/full/")
        return

    log.info(f"Mission:    {mission_path}")
    log.info(f"Source:     {source_dir}")
    log.info(f"Resolution: {args.resolution}")
    log.info(f"CRF:        {args.crf}")
    log.info(f"Preset:     {args.preset}")
    log.info(f"Found {len(videos)} video(s)")

    # Create proxy output directory
    proxy_dir = os.path.join(mission_path, "video", "proxy")
    os.makedirs(proxy_dir, exist_ok=True)

    # Process each video
    results = []
    for video_path in videos:
        filename = os.path.basename(video_path)
        name, ext = os.path.splitext(filename)
        # Strip _graded suffix if present so proxy names match original clip names
        clean_name = re.sub(r"_graded$", "", name)
        output_path = os.path.join(proxy_dir, f"{clean_name}_proxy{ext}")

        # Skip if proxy already exists and is non-empty
        if os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
            log.info(f"  Skip (exists): {clean_name}_proxy{ext}")
            results.append({"input": video_path, "output": output_path, "status": "exists"})
            continue

        log.info(f"  Generating: {filename} → {clean_name}_proxy{ext}")

        if args.dry_run:
            log.info(f"    [DRY RUN] → {output_path}")
            continue

        ok, stderr = generate_proxy(
            video_path, output_path,
            resolution=args.resolution, crf=args.crf, preset=args.preset,
        )

        if ok:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log.info(f"    OK: {output_path} ({size_mb:.1f} MB)")
            results.append({"input": video_path, "output": output_path, "status": "ok"})
        else:
            log.error(f"    FAILED: {filename}")
            if stderr:
                log.error(f"    FFmpeg: {stderr[-500:]}")
            # Clean up partial output
            if os.path.isfile(output_path):
                os.remove(output_path)
            results.append({"input": video_path, "output": None, "status": "failed"})

    # Summary
    ok_count = sum(1 for r in results if r["status"] == "ok")
    exists_count = sum(1 for r in results if r["status"] == "exists")
    fail_count = sum(1 for r in results if r["status"] == "failed")
    log.info(f"\nProxy generation complete: {ok_count} new, {exists_count} existing, {fail_count} failed")

    success_count = ok_count + exists_count
    if fail_count > 0 and success_count > 0:
        sys.exit(1)   # Partial failure
    elif fail_count > 0:
        sys.exit(2)   # All failed — fatal


if __name__ == "__main__":
    main()
