"""
Sentinel Aerial Inspections — SRT Telemetry Parser (Step V2)

Parses DJI SRT subtitle files to extract per-frame telemetry data.
Writes per-clip metadata to the Supabase video_assets table.

DJI SRT files contain per-frame data at ~30fps including GPS coordinates,
altitude, ISO, shutter speed, aperture, and color temperature.

Usage:
    python srt_telemetry_parser.py E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218
    python srt_telemetry_parser.py path/to/mission --mission-id UUID --upload
    python srt_telemetry_parser.py path/to/mission --dump-json
"""

import os
import sys
import re
import json
import glob
import argparse
import logging
from datetime import datetime
from pathlib import Path

from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint
from pipeline_status import PipelineStatusReporter, add_pipeline_args
from pipeline_utils import (
    LOG_DIR, SUPABASE_URL, SUPABASE_SERVICE_KEY,
    setup_logging, extract_sequence_number, get_supabase_client,
)

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "srt_telemetry_parser"

# SRT telemetry patterns (DJI format)
# Example SRT frame:
# 1
# 00:00:00,000 --> 00:00:00,033
# F/2.8, SS 500, ISO 100, EV 0, GPS (36.8451, -76.2883, 45), D 15.3m, ...
TIMESTAMP_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")
GPS_RE = re.compile(r"GPS\s*\(([^)]+)\)")
ISO_RE = re.compile(r"ISO\s+(\d+)")
SHUTTER_RE = re.compile(r"SS\s+(\d+)")
APERTURE_RE = re.compile(r"F/([\d.]+)")
EV_RE = re.compile(r"EV\s+([+-]?[\d.]+)")
FNUM_RE = re.compile(r"FNUM:\s*(\d+)")
CT_RE = re.compile(r"CT\s+(\d+)")  # Color temperature
DISTANCE_RE = re.compile(r"D\s+([\d.]+)m")
# Alternative DJI Mini 4 Pro SRT format fields
HOME_RE = re.compile(r"\[home:\s*([^\]]+)\]")
DATETIME_RE = re.compile(r"\[datetime:\s*([^\]]+)\]")
ALTITUDE_RE = re.compile(r"\[altitude:\s*([\d.]+)\]")
LATITUDE_RE = re.compile(r"\[latitude:\s*([+-]?[\d.]+)\]")
LONGITUDE_RE = re.compile(r"\[longitude:\s*([+-]?[\d.]+)\]")


# ─── SRT PARSING ─────────────────────────────────────────────────────────────

def parse_srt_timestamp(ts_str):
    """Parse SRT timestamp to seconds. '00:01:30,500' → 90.5"""
    m = TIMESTAMP_RE.match(ts_str.strip())
    if not m:
        return 0.0
    h, mi, s, ms = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return h * 3600 + mi * 60 + s + ms / 1000.0


def parse_gps(text):
    """Extract GPS coordinates from SRT line."""
    # Standard DJI format: GPS (lat, lon, alt)
    m = GPS_RE.search(text)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        if len(parts) >= 2:
            try:
                lat = float(parts[0])
                lon = float(parts[1])
                alt = float(parts[2]) if len(parts) >= 3 else 0.0
                return {"lat": lat, "lon": lon, "alt": alt}
            except ValueError:
                pass

    # Alternative bracket format
    lat_m = LATITUDE_RE.search(text)
    lon_m = LONGITUDE_RE.search(text)
    alt_m = ALTITUDE_RE.search(text)
    if lat_m and lon_m:
        try:
            lat = float(lat_m.group(1))
            lon = float(lon_m.group(1))
            alt = float(alt_m.group(1)) if alt_m else 0.0
            return {"lat": lat, "lon": lon, "alt": alt}
        except ValueError:
            pass

    return None


def parse_srt_frame(text):
    """Parse a single SRT subtitle block into structured telemetry."""
    frame = {}

    # ISO
    m = ISO_RE.search(text)
    if m:
        frame["iso"] = int(m.group(1))

    # Shutter speed
    m = SHUTTER_RE.search(text)
    if m:
        frame["shutter_speed"] = int(m.group(1))

    # Aperture
    m = APERTURE_RE.search(text)
    if m:
        frame["aperture"] = float(m.group(1))

    # EV
    m = EV_RE.search(text)
    if m:
        frame["ev"] = float(m.group(1))

    # Color temperature
    m = CT_RE.search(text)
    if m:
        frame["color_temp"] = int(m.group(1))

    # GPS
    gps = parse_gps(text)
    if gps:
        frame["gps"] = gps

    # Distance from home
    m = DISTANCE_RE.search(text)
    if m:
        frame["distance_m"] = float(m.group(1))

    return frame


def parse_srt_file(srt_path):
    """Parse a complete SRT file into a list of frames with timestamps."""
    with open(srt_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split into subtitle blocks (separated by blank lines)
    blocks = re.split(r"\n\s*\n", content.strip())
    frames = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # Line 1: sequence number
        # Line 2: timestamp range
        # Lines 3+: telemetry data
        ts_line = None
        data_lines = []

        for line in lines:
            if "-->" in line:
                ts_line = line
            elif not line.strip().isdigit():
                data_lines.append(line)

        if not ts_line:
            continue

        # Parse timestamps
        ts_parts = ts_line.split("-->")
        start_ts = parse_srt_timestamp(ts_parts[0])
        end_ts = parse_srt_timestamp(ts_parts[1]) if len(ts_parts) > 1 else start_ts

        # Parse telemetry from data lines
        text = " ".join(data_lines)
        frame = parse_srt_frame(text)
        frame["timestamp_start"] = start_ts
        frame["timestamp_end"] = end_ts

        frames.append(frame)

    return frames


# ─── CLIP AGGREGATION ────────────────────────────────────────────────────────

def aggregate_clip(frames, filename, source_platform=None):
    """Compute per-clip aggregate metrics from parsed frames."""
    if not frames:
        return None

    gps_points = [f["gps"] for f in frames if "gps" in f]
    iso_values = [f["iso"] for f in frames if "iso" in f]
    alt_values = [f["gps"]["alt"] for f in frames if "gps" in f and "alt" in f["gps"]]

    first_ts = frames[0].get("timestamp_start", 0)
    last_ts = frames[-1].get("timestamp_end", 0)
    duration = last_ts - first_ts if last_ts > first_ts else 0

    fps = len(frames) / duration if duration > 0 else 0

    clip = {
        "filename": filename,
        "duration_seconds": round(duration, 2),
        "fps": round(fps, 1),
        "frame_count": len(frames),
        "source_platform": source_platform,
    }

    # GPS start/end
    if gps_points:
        clip["gps_start_lat"] = gps_points[0]["lat"]
        clip["gps_start_lon"] = gps_points[0]["lon"]
        clip["gps_end_lat"] = gps_points[-1]["lat"]
        clip["gps_end_lon"] = gps_points[-1]["lon"]

    # Altitude
    if alt_values:
        clip["altitude_avg"] = round(sum(alt_values) / len(alt_values), 1)
        clip["altitude_min"] = round(min(alt_values), 1)
        clip["altitude_max"] = round(max(alt_values), 1)

    # Altitude change rate (ft/s) — per-frame analysis
    if len(alt_values) >= 2 and duration > 0:
        frame_interval = duration / len(frames) if len(frames) > 1 else 1.0
        max_rate_m_per_s = 0.0
        for i in range(1, len(alt_values)):
            delta_m = abs(alt_values[i] - alt_values[i - 1])
            rate_m_per_s = delta_m / frame_interval if frame_interval > 0 else 0
            max_rate_m_per_s = max(max_rate_m_per_s, rate_m_per_s)
        # Convert to ft/s for FAA-standard comparison
        clip["altitude_max_change_rate"] = round(max_rate_m_per_s * 3.28084, 2)

    # ISO
    if iso_values:
        clip["iso_avg"] = round(sum(iso_values) / len(iso_values))
        clip["iso_max"] = max(iso_values)

    return clip


# ─── SUPABASE UPLOAD ─────────────────────────────────────────────────────────

def upload_to_supabase(clip_data, mission_id):
    """Write clip metadata to video_assets table in Supabase."""
    client = get_supabase_client()

    record = {
        "mission_id": mission_id,
        "filename": clip_data["filename"],
        "duration_seconds": clip_data.get("duration_seconds"),
        "fps": clip_data.get("fps"),
        "gps_start_lat": clip_data.get("gps_start_lat"),
        "gps_start_lon": clip_data.get("gps_start_lon"),
        "gps_end_lat": clip_data.get("gps_end_lat"),
        "gps_end_lon": clip_data.get("gps_end_lon"),
        "altitude_avg": clip_data.get("altitude_avg"),
        "altitude_min": clip_data.get("altitude_min"),
        "altitude_max": clip_data.get("altitude_max"),
        "altitude_max_change_rate": clip_data.get("altitude_max_change_rate"),
        "iso_avg": clip_data.get("iso_avg"),
        "iso_max": clip_data.get("iso_max"),
        "source_platform": clip_data.get("source_platform"),
        "has_srt_telemetry": True,
        "qa_status": "pending",
    }

    # Sequence number from filename (platform-aware)
    record["sequence_number"] = extract_sequence_number(clip_data["filename"])

    result = client.table("video_assets").insert(record).execute()
    return result.data


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — SRT Telemetry Parser (Step V2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Parses DJI SRT subtitle files and extracts per-clip telemetry data.

Examples:
  python srt_telemetry_parser.py path/to/mission
  python srt_telemetry_parser.py path/to/mission --mission-id UUID --upload
  python srt_telemetry_parser.py path/to/mission --dump-json > telemetry.json
        """,
    )
    parser.add_argument("mission_path", help="Path to mission folder")
    parser.add_argument("--mission-id", help="Supabase mission UUID (required for --upload)")
    parser.add_argument("--platform", choices=["mini4pro", "m4e", "m3e"], default="mini4pro",
                        help="Drone platform (default: mini4pro)")
    parser.add_argument("--upload", action="store_true", help="Upload results to Supabase video_assets")
    parser.add_argument("--dump-json", action="store_true", help="Output parsed data as JSON")
    parser.add_argument("--force", action="store_true",
                        help="Clear checkpoint and re-process all SRT files from scratch")
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    mission_path = os.path.abspath(args.mission_path)
    telemetry_dir = os.path.join(mission_path, "video", "telemetry")

    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="v2_srt",
    )

    if not os.path.isdir(telemetry_dir):
        log.info(f"No telemetry directory: {telemetry_dir}")
        reporter.complete(output="No telemetry directory — skipped")
        return

    # Find SRT files
    srt_files = sorted(glob.glob(os.path.join(telemetry_dir, "*.SRT")) +
                       glob.glob(os.path.join(telemetry_dir, "*.srt")))

    if not srt_files:
        log.info("No SRT files found")
        reporter.complete(output="No SRT files found — skipped")
        return

    reporter.start()

    log.info(f"Mission:  {mission_path}")
    log.info(f"Platform: {args.platform}")
    log.info(f"Found {len(srt_files)} SRT file(s)")

    try:
        # Checkpoint resume
        if args.force:
            clear_checkpoint(mission_path, SCRIPT_NAME)
            log.info("--force: checkpoint cleared, re-processing all files")
        completed = load_checkpoint(mission_path, SCRIPT_NAME)
        if completed:
            log.info(f"Resuming: {len(completed)} file(s) already completed")

        all_clips = []
        results = []

        for srt_path in srt_files:
            filename = os.path.basename(srt_path)
            # Derive video filename (DJI_0015.SRT → DJI_0015.MP4)
            video_filename = os.path.splitext(filename)[0] + ".MP4"

            item_key = srt_path
            if item_key in completed:
                log.info(f"  Skip (checkpoint): {filename}")
                results.append({"file": filename, "status": "ok"})
                continue

            log.info(f"  Parsing: {filename}")

            try:
                frames = parse_srt_file(srt_path)
            except Exception as e:
                log.error(f"    Failed to parse {filename}: {e}")
                results.append({"file": filename, "status": "failed"})
                continue

            log.info(f"    Frames: {len(frames)}")

            clip = aggregate_clip(frames, video_filename, source_platform=args.platform)
            if clip:
                clip["srt_file"] = filename
                clip["frames"] = frames if args.dump_json else None
                all_clips.append(clip)

                log.info(f"    Duration: {clip.get('duration_seconds', 0):.1f}s")
                log.info(f"    FPS: {clip.get('fps', 0):.1f}")
                log.info(f"    ISO avg/max: {clip.get('iso_avg', '?')}/{clip.get('iso_max', '?')}")

                if args.upload:
                    if not args.mission_id:
                        raise RuntimeError("--mission-id required for --upload")
                    try:
                        result = upload_to_supabase(clip, args.mission_id)
                        log.info(f"    Uploaded to Supabase: {result}")
                        results.append({"file": filename, "status": "ok"})
                        completed.add(item_key)
                        try:
                            save_checkpoint(mission_path, SCRIPT_NAME, completed)
                        except OSError as e:
                            log.warning(f"    Checkpoint write failed (non-fatal): {e}")
                    except Exception as e:
                        log.error(f"    Upload failed: {e}")
                        results.append({"file": filename, "status": "failed"})
                else:
                    results.append({"file": filename, "status": "ok"})
                    completed.add(item_key)
                    try:
                        save_checkpoint(mission_path, SCRIPT_NAME, completed)
                    except OSError as e:
                        log.warning(f"    Checkpoint write failed (non-fatal): {e}")
            else:
                log.warning(f"    No aggregate data produced for {filename}")
                results.append({"file": filename, "status": "failed"})

        if args.dump_json:
            # Clean up frames for JSON output
            output = []
            for clip in all_clips:
                c = {k: v for k, v in clip.items() if k != "frames" or v is not None}
                output.append(c)
            print(json.dumps(output, indent=2))

        ok_count = sum(1 for r in results if r["status"] == "ok")
        fail_count = sum(1 for r in results if r["status"] == "failed")
        log.info(f"\nParsed {len(all_clips)} clip(s): {ok_count} ok, {fail_count} failed")

        if fail_count > 0 and ok_count > 0:
            reporter.fail(f"Partial failure: {fail_count} SRT file(s) failed")
            sys.exit(1)   # Partial failure
        elif fail_count > 0:
            reporter.fail(f"All {fail_count} SRT file(s) failed")
            sys.exit(2)   # All failed — fatal
        else:
            reporter.complete(output=f"{ok_count} SRT file(s) parsed successfully")

    except Exception as e:
        reporter.fail(str(e))
        raise


if __name__ == "__main__":
    main()
