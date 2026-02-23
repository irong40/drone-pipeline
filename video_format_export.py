"""
Sentinel Aerial Inspections — Video Format Export (Step V6)

Batch encodes the master video edit into all delivery formats configured
in processing_templates.video_formats.

Handles resolution scaling, codec selection, and max_duration_sec truncation
for platform-specific formats (Instagram Reels 90s, TikTok 180s).

Usage:
    python video_format_export.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218
    python video_format_export.py path/to/mission --mission-id UUID
    python video_format_export.py path/to/mission --formats '[{"name":"youtube","resolution":"3840x2160","fps":30,"codec":"libx265"}]'
"""

import os
import sys
import re
import json
import glob
import argparse
import subprocess
import logging

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
FFMPEG_BIN = "ffmpeg"
FFPROBE_BIN = "ffprobe"
LOG_DIR = r"E:\Sentinel\logs"

# Fallback formats if Supabase is not available
DEFAULT_FORMATS = [
    {"name": "instagram_reels", "resolution": "1080x1920", "aspect": "9:16", "fps": 30, "codec": "libx264", "max_duration_sec": 90},
    {"name": "youtube", "resolution": "3840x2160", "aspect": "16:9", "fps": 30, "codec": "libx265"},
    {"name": "tiktok", "resolution": "1080x1920", "aspect": "9:16", "fps": 30, "codec": "libx264", "max_duration_sec": 180},
    {"name": "client_4k", "resolution": "3840x2160", "aspect": "16:9", "fps": 30, "codec": "copy"},
    {"name": "web_preview", "resolution": "1920x1080", "aspect": "16:9", "fps": 30, "codec": "libx264"},
]


# ─── LOGGING ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "video_format_export.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def get_video_duration(video_path):
    """Get video duration in seconds using ffprobe."""
    cmd = [
        FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        video_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return 0.0


def fetch_formats_from_supabase(mission_id):
    """Fetch video_formats from processing_templates via mission's package type."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return None

    try:
        from supabase import create_client
    except ImportError:
        return None

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Get mission's package_type
    mission = client.table("missions").select("package_type").eq("id", mission_id).single().execute()
    if not mission.data:
        return None

    package_type = mission.data.get("package_type")
    if not package_type:
        return None

    # Get formats from template
    template = (client.table("processing_templates")
                .select("video_formats")
                .eq("preset_name", package_type)
                .single()
                .execute())

    if template.data and template.data.get("video_formats"):
        return template.data["video_formats"]

    return None


def find_master_video(mission_path):
    """Find the master edit video in video/master/."""
    master_dir = os.path.join(mission_path, "video", "master")
    if not os.path.isdir(master_dir):
        return None

    for pattern in ["*.mp4", "*.MP4", "*.mov", "*.MOV"]:
        matches = glob.glob(os.path.join(master_dir, pattern))
        if matches:
            return matches[0]

    return None


# ─── EXPORT ──────────────────────────────────────────────────────────────────

def build_ffmpeg_command(input_path, output_path, fmt, source_duration=None):
    """Build FFmpeg command for a single format export.

    Args:
        input_path: Path to master video
        output_path: Path for output file
        fmt: Format config dict with name, resolution, fps, codec, max_duration_sec
        source_duration: Duration of source video in seconds
    """
    cmd = [FFMPEG_BIN, "-y", "-i", input_path]

    codec = fmt.get("codec", "libx264")

    # Duration truncation
    max_dur = fmt.get("max_duration_sec")
    if max_dur and source_duration and source_duration > max_dur:
        cmd.extend(["-t", str(max_dur)])

    if codec == "copy":
        # Copy codec — no re-encoding
        cmd.extend(["-c:v", "copy", "-c:a", "copy"])
    else:
        # Resolution scaling (validate format to prevent filter injection)
        resolution = fmt.get("resolution", "1920x1080")
        if not re.match(r"^\d{1,5}x\d{1,5}$", resolution):
            raise ValueError(f"Invalid resolution format: {resolution}")
        w, h = resolution.split("x")

        # Build video filter chain
        vf_parts = [f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"]
        cmd.extend(["-vf", ",".join(vf_parts)])

        # Codec
        cmd.extend(["-c:v", codec])

        # Quality settings based on codec
        if codec in ("libx264", "libx265"):
            cmd.extend(["-crf", "18", "-preset", "medium"])

        # FPS
        fps = fmt.get("fps", 30)
        cmd.extend(["-r", str(fps)])

        # Audio
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    cmd.append(output_path)
    return cmd


def export_format(input_path, output_dir, fmt, source_duration=None):
    """Export a single format. Returns (success, output_path, error)."""
    name = fmt["name"]
    ext = ".mp4"  # All formats are MP4

    # Build output filename
    input_stem = os.path.splitext(os.path.basename(input_path))[0]
    output_filename = f"{input_stem}_{name}{ext}"
    output_path = os.path.join(output_dir, output_filename)

    cmd = build_ffmpeg_command(input_path, output_path, fmt, source_duration)

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        return True, output_path, None
    return False, output_path, result.stderr[-500:]


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Video Format Export (Step V6)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Batch encodes master video edit into all configured delivery formats.

Examples:
  python video_format_export.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218
  python video_format_export.py path/to/mission --mission-id UUID
  python video_format_export.py path/to/mission --formats '[{"name":"youtube","resolution":"3840x2160","fps":30,"codec":"libx265"}]'
        """,
    )
    parser.add_argument("mission_path", help="Path to mission folder")
    parser.add_argument("--mission-id", help="Supabase mission UUID (for fetching formats)")
    parser.add_argument("--formats", help="Override formats as JSON array")
    parser.add_argument("--input-file", help="Override master video path")
    parser.add_argument("--dry-run", action="store_true", help="Show commands without executing")
    args = parser.parse_args()

    log = setup_logging()

    mission_path = os.path.abspath(args.mission_path)
    if not os.path.isdir(mission_path):
        sys.exit(f"Mission folder not found: {mission_path}")

    # Find master video
    master_video = args.input_file or find_master_video(mission_path)
    if not master_video:
        sys.exit("No master video found in video/master/. Complete Step V5 (manual edit) first.")

    log.info(f"Mission: {mission_path}")
    log.info(f"Master:  {master_video}")

    # Get source duration
    source_duration = get_video_duration(master_video)
    log.info(f"Duration: {source_duration:.1f}s")

    # Resolve export formats
    formats = None
    if args.formats:
        formats = json.loads(args.formats)
    elif args.mission_id:
        formats = fetch_formats_from_supabase(args.mission_id)

    if not formats:
        log.info("Using default export formats")
        formats = DEFAULT_FORMATS

    log.info(f"Formats: {len(formats)}")

    # Create exports directory
    exports_dir = os.path.join(mission_path, "video", "exports")
    os.makedirs(exports_dir, exist_ok=True)

    # Export each format
    results = []
    for fmt in formats:
        name = fmt["name"]
        max_dur = fmt.get("max_duration_sec")
        truncated = max_dur and source_duration > max_dur

        log.info(f"\n  Exporting: {name}")
        log.info(f"    Resolution: {fmt.get('resolution', 'copy')}")
        log.info(f"    Codec: {fmt.get('codec', 'libx264')}")
        if truncated:
            log.info(f"    Truncating: {source_duration:.0f}s → {max_dur}s")

        if args.dry_run:
            cmd = build_ffmpeg_command(master_video, f"<output>_{name}.mp4", fmt, source_duration)
            log.info(f"    [DRY RUN] {' '.join(cmd)}")
            continue

        ok, output_path, error = export_format(master_video, exports_dir, fmt, source_duration)

        if ok:
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log.info(f"    OK: {output_path} ({size_mb:.1f} MB)")
            results.append({"format": name, "path": output_path, "status": "ok"})
        else:
            log.error(f"    FAILED: {name}")
            if error:
                log.error(f"    {error}")
            results.append({"format": name, "path": None, "status": "failed"})

    # Summary
    ok_count = sum(1 for r in results if r["status"] == "ok")
    fail_count = sum(1 for r in results if r["status"] == "failed")
    log.info(f"\n{'=' * 50}")
    log.info(f"Export complete: {ok_count} ok, {fail_count} failed")


if __name__ == "__main__":
    main()
