"""
Sentinel Aerial Inspections — Video Metadata Extraction (Step V1.5)

Runs ffprobe on video clips to populate video_assets columns that SRT
telemetry cannot provide: resolution, codec, file_size_bytes, color_profile,
has_lrf_proxy, and graded_path.

Designed to run after color grading (V1) and before or after SRT parsing (V2).
Updates existing video_assets records by matching on mission_id + filename,
or inserts new records if run before V2.

Usage:
    python video_metadata.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218 --mission-id UUID --upload
    python video_metadata.py path/to/mission --platform mini4pro --dump-json
    python video_metadata.py path/to/mission --mission-id UUID --upload --dry-run
"""

import os
import sys
import re
import json
import glob
import argparse
import subprocess
import logging

from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint
from pipeline_status import PipelineStatusReporter, add_pipeline_args
from pipeline_utils import (
    LOG_DIR, VIDEO_EXTENSIONS, SUPABASE_URL, SUPABASE_SERVICE_KEY,
    setup_logging, extract_sequence_number, get_supabase_client,
)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "video_metadata"
FFPROBE_BIN = "ffprobe"

# Platform → expected color profile
PLATFORM_COLOR_PROFILES = {
    "m4e": "d_log_m",
    "m3e": "d_log_m",
    "mini4pro": "d_cinelike",
}


# ─── FFPROBE ─────────────────────────────────────────────────────────────────

def check_ffprobe():
    """Verify ffprobe is installed and accessible."""
    try:
        subprocess.run(
            [FFPROBE_BIN, "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def probe_video(video_path):
    """Run ffprobe on a video file and return parsed metadata.

    Returns dict with: resolution, codec, fps, duration_seconds, file_size_bytes,
    bit_rate, audio_codec, width, height.
    Returns None on failure.
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
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None

    # Find the video stream
    video_stream = None
    audio_stream = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    if not video_stream:
        return None

    # Extract resolution
    width = video_stream.get("width", 0)
    height = video_stream.get("height", 0)
    resolution = f"{width}x{height}" if width and height else None

    # Extract codec name and normalize
    raw_codec = video_stream.get("codec_name", "").lower()
    codec = normalize_codec(raw_codec)

    # Extract FPS from r_frame_rate (e.g., "30/1" or "29970/1000")
    fps = None
    r_frame_rate = video_stream.get("r_frame_rate", "")
    if "/" in r_frame_rate:
        num, den = r_frame_rate.split("/")
        try:
            fps = round(int(num) / int(den), 2)
        except (ValueError, ZeroDivisionError):
            pass

    # Extract duration and file size from format
    fmt = data.get("format", {})
    duration = None
    try:
        duration = round(float(fmt.get("duration", 0)), 2)
    except (ValueError, TypeError):
        pass

    file_size = None
    try:
        file_size = int(fmt.get("size", 0))
    except (ValueError, TypeError):
        pass

    bit_rate = None
    try:
        bit_rate = int(fmt.get("bit_rate", 0))
    except (ValueError, TypeError):
        pass

    return {
        "resolution": resolution,
        "width": width,
        "height": height,
        "codec": codec,
        "codec_raw": raw_codec,
        "fps": fps,
        "duration_seconds": duration,
        "file_size_bytes": file_size,
        "bit_rate": bit_rate,
        "audio_codec": audio_stream.get("codec_name") if audio_stream else None,
    }


def normalize_codec(raw_codec):
    """Normalize ffprobe codec name to human-readable label.

    h264 → H.264, hevc → H.265, etc.
    """
    mapping = {
        "h264": "H.264",
        "hevc": "H.265",
        "h265": "H.265",
        "av1": "AV1",
        "vp9": "VP9",
        "mpeg4": "MPEG-4",
        "prores": "ProRes",
    }
    return mapping.get(raw_codec, raw_codec.upper() if raw_codec else None)


# ─── FILE DISCOVERY ──────────────────────────────────────────────────────────

def find_video_files(mission_path):
    """Find video files in video/full/ directory."""
    video_dir = os.path.join(mission_path, "video", "full")
    if not os.path.isdir(video_dir):
        return []

    videos = []
    for pattern in VIDEO_EXTENSIONS:
        videos.extend(glob.glob(os.path.join(video_dir, pattern)))
    return sorted(set(videos))


def find_graded_file(mission_path, original_filename):
    """Find the graded version of a video file.

    video/full/DJI_0015.MP4 → video/graded/DJI_0015_graded.MP4
    """
    name, ext = os.path.splitext(original_filename)
    graded_dir = os.path.join(mission_path, "video", "graded")
    graded_path = os.path.join(graded_dir, f"{name}_graded{ext}")
    if os.path.isfile(graded_path):
        return graded_path
    # Try case-insensitive match
    graded_path_lower = os.path.join(graded_dir, f"{name}_graded{ext.lower()}")
    if os.path.isfile(graded_path_lower):
        return graded_path_lower
    return None


def check_lrf_proxy(mission_path, original_filename):
    """Check if an LRF proxy file exists for this video.

    DJI cameras write DJI_0015.LRF alongside DJI_0015.MP4.
    """
    name = os.path.splitext(original_filename)[0]
    proxy_dir = os.path.join(mission_path, "video", "proxy")
    # Check both original proxy dir and the standard location
    for search_dir in [proxy_dir, os.path.join(mission_path, "video", "full")]:
        if not os.path.isdir(search_dir):
            continue
        for ext in [".LRF", ".lrf"]:
            lrf_path = os.path.join(search_dir, f"{name}{ext}")
            if os.path.isfile(lrf_path):
                return True
    return False


# ─── METADATA COLLECTION ────────────────────────────────────────────────────

def collect_metadata(mission_path, platform="mini4pro", completed=None):
    """Collect metadata for all video files in a mission.

    For each video:
      1. Run ffprobe on the raw file (video/full/)
      2. Check for graded version (video/graded/)
      3. Check for LRF proxy
      4. Derive color_profile from platform

    completed: optional set of already-processed item keys (for checkpoint resume).
    Returns list of metadata dicts.
    """
    log = logging.getLogger(__name__)
    videos = find_video_files(mission_path)

    if not videos:
        return []

    if completed is None:
        completed = set()

    color_profile = PLATFORM_COLOR_PROFILES.get(platform)
    results = []

    for video_path in videos:
        filename = os.path.basename(video_path)

        if video_path in completed:
            log.info(f"  Skip (checkpoint): {filename}")
            continue

        log.info(f"  Probing: {filename}")

        # Run ffprobe
        probe = probe_video(video_path)
        if not probe:
            log.warning(f"    ffprobe failed for {filename}")
            results.append({
                "filename": filename,
                "file_path": video_path,
                "status": "probe_failed",
            })
            continue

        # Check for graded version
        graded_path = find_graded_file(mission_path, filename)
        graded_probe = None
        if graded_path:
            graded_probe = probe_video(graded_path)
            log.info(f"    Graded: {os.path.basename(graded_path)}")

        # Check for LRF proxy
        has_lrf = check_lrf_proxy(mission_path, filename)

        # Build metadata record
        meta = {
            "filename": filename,
            "file_path": video_path,
            "file_size_bytes": probe["file_size_bytes"],
            "resolution": probe["resolution"],
            "codec": probe["codec"],
            "fps": probe["fps"],
            "duration_seconds": probe["duration_seconds"],
            "color_profile": color_profile,
            "has_lrf_proxy": has_lrf,
            "graded_path": graded_path,
            "status": "ok",
            # Extra fields for JSON dump (not uploaded to Supabase)
            "width": probe["width"],
            "height": probe["height"],
            "codec_raw": probe["codec_raw"],
            "bit_rate": probe["bit_rate"],
            "audio_codec": probe["audio_codec"],
        }

        # If graded version exists, include its size for reference
        if graded_probe:
            meta["graded_file_size_bytes"] = graded_probe["file_size_bytes"]
            meta["graded_codec"] = graded_probe["codec"]
            meta["graded_resolution"] = graded_probe["resolution"]

        log.info(f"    {probe['resolution']} | {probe['codec']} | {probe['fps']}fps | {probe['duration_seconds']:.1f}s | {(probe['file_size_bytes'] or 0) / (1024*1024):.1f} MB")
        if has_lrf:
            log.info(f"    LRF proxy: found")
        if graded_path:
            log.info(f"    Graded path: {graded_path}")

        results.append(meta)
        completed.add(video_path)

    return results


# ─── SUPABASE UPLOAD ─────────────────────────────────────────────────────────

def upload_metadata(metadata_list, mission_id, dry_run=False):
    """Update video_assets records with ffprobe metadata.

    Matches existing records by mission_id + filename (created by V2 SRT parser).
    If no existing record found, inserts a new one (supports running before V2).
    """
    log = logging.getLogger(__name__)

    client = get_supabase_client()

    # Fetch existing records for this mission
    existing = client.table("video_assets").select(
        "id, filename"
    ).eq("mission_id", mission_id).execute()

    existing_map = {r["filename"]: r["id"] for r in (existing.data or [])}

    updated = 0
    inserted = 0

    for meta in metadata_list:
        if meta["status"] != "ok":
            continue

        # Fields to set from ffprobe
        update_fields = {
            "file_size_bytes": meta["file_size_bytes"],
            "resolution": meta["resolution"],
            "codec": meta["codec"],
            "color_profile": meta["color_profile"],
            "has_lrf_proxy": meta["has_lrf_proxy"],
            "graded_path": meta["graded_path"],
        }

        # Also set fps if we got a good value (V2 SRT parser may have set it too)
        if meta["fps"]:
            update_fields["fps"] = meta["fps"]

        filename = meta["filename"]

        if dry_run:
            if filename in existing_map:
                log.info(f"    [DRY RUN] Would UPDATE {filename}")
            else:
                log.info(f"    [DRY RUN] Would INSERT {filename}")
            continue

        if filename in existing_map:
            # Update existing record
            record_id = existing_map[filename]
            client.table("video_assets").update(
                update_fields
            ).eq("id", record_id).execute()
            log.info(f"    Updated: {filename}")
            updated += 1
        else:
            # Insert new record (running before V2)
            insert_fields = {
                "mission_id": mission_id,
                "filename": filename,
                "sequence_number": extract_sequence_number(filename),
                "qa_status": "pending",
                **update_fields,
            }
            if meta["duration_seconds"]:
                insert_fields["duration_seconds"] = meta["duration_seconds"]
            client.table("video_assets").insert(insert_fields).execute()
            log.info(f"    Inserted: {filename}")
            inserted += 1

    return updated, inserted


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Video Metadata Extraction (Step V1.5)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Runs ffprobe on video clips to populate video_assets columns: resolution,
codec, file_size_bytes, color_profile, has_lrf_proxy, and graded_path.

Run after color grading (V1), before or after SRT parsing (V2).

Examples:
  python video_metadata.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218 --platform mini4pro
  python video_metadata.py path/to/mission --mission-id UUID --upload
  python video_metadata.py path/to/mission --dump-json
  python video_metadata.py path/to/mission --mission-id UUID --upload --dry-run
        """,
    )
    parser.add_argument("mission_path", help="Path to mission folder")
    parser.add_argument("--platform", choices=["mini4pro", "m4e", "m3e"], default="mini4pro",
                        help="Drone platform for color profile (default: mini4pro)")
    parser.add_argument("--mission-id", help="Supabase mission UUID (required for --upload)")
    parser.add_argument("--upload", action="store_true", help="Upload metadata to Supabase video_assets")
    parser.add_argument("--dump-json", action="store_true", help="Output metadata as JSON")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without writing")
    parser.add_argument("--force", action="store_true",
                        help="Clear checkpoint and re-process all files from scratch")
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # Pre-flight: check ffprobe
    if not check_ffprobe():
        sys.exit("ffprobe not found. Install FFmpeg from https://ffmpeg.org/download.html and add to PATH.")

    mission_path = os.path.abspath(args.mission_path)
    if not os.path.isdir(mission_path):
        sys.exit(f"Mission folder not found: {mission_path}")

    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="v1_5_metadata",
    )
    if not args.dry_run:
        reporter.start()

    log.info(f"Video metadata extraction starting")
    log.info(f"  Mission:  {mission_path}")
    log.info(f"  Platform: {args.platform}")

    try:
        # Checkpoint resume
        if args.force:
            clear_checkpoint(mission_path, SCRIPT_NAME)
            log.info("--force: checkpoint cleared, re-processing all files")
        completed = load_checkpoint(mission_path, SCRIPT_NAME)
        if completed:
            log.info(f"Resuming: {len(completed)} file(s) already completed")

        # Collect metadata
        metadata = collect_metadata(mission_path, platform=args.platform, completed=completed)

        if not metadata:
            log.info("No video files found in video/full/")
            reporter.complete(output="No video files found — skipped")
            return

        # Save checkpoint after collection
        try:
            save_checkpoint(mission_path, SCRIPT_NAME, completed)
        except OSError as e:
            log.warning(f"Checkpoint write failed (non-fatal): {e}")

        # Summary
        ok_count = sum(1 for m in metadata if m["status"] == "ok")
        fail_count = sum(1 for m in metadata if m["status"] == "probe_failed")
        graded_count = sum(1 for m in metadata if m.get("graded_path"))
        lrf_count = sum(1 for m in metadata if m.get("has_lrf_proxy"))

        log.info(f"\nMetadata collected:")
        log.info(f"  Probed:  {ok_count} ok, {fail_count} failed")
        log.info(f"  Graded:  {graded_count} clips have graded versions")
        log.info(f"  LRF:     {lrf_count} clips have LRF proxies")

        # Upload to Supabase
        if args.upload:
            if not args.mission_id:
                raise RuntimeError("--mission-id required for --upload")
            log.info(f"\nUploading to Supabase (mission: {args.mission_id})...")
            updated, inserted = upload_metadata(metadata, args.mission_id, dry_run=args.dry_run)
            if args.dry_run:
                log.info(f"[DRY RUN] No changes written.")
            else:
                log.info(f"Supabase: {updated} updated, {inserted} inserted")

        # JSON output
        if args.dump_json:
            # Clean up internal fields for JSON output
            output = []
            for m in metadata:
                entry = {k: v for k, v in m.items() if k != "file_path"}
                output.append(entry)
            print(json.dumps(output, indent=2))

        log.info("\nVideo metadata extraction complete.")

        if fail_count > 0:
            reporter.fail(f"Partial failure: {fail_count} probe(s) failed")
            sys.exit(1)
        else:
            reporter.complete(output=f"{ok_count} video(s) metadata extracted")

    except Exception as e:
        reporter.fail(str(e))
        raise


if __name__ == "__main__":
    main()
