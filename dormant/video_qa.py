"""
Sentinel Aerial Inspections — Video QA Analysis (Step V3)

Analyzes video telemetry data for quality issues.
Reads video_assets from Supabase, applies threshold checks,
updates qa_status and qa_flags.

Thresholds (from processing_templates.video_qa_thresholds):
  - iso_ceiling: 800 (ISO spikes above this flag noisy footage)
  - altitude_change_rate_ft_per_sec: 10 (jerky movement)
  - gps_drift_threshold_meters: 5 (stabilization issues)
  - min_fps: 29 (encoding issues)

Usage:
    python video_qa.py --mission-id UUID
    python video_qa.py --mission-id UUID --thresholds '{"iso_ceiling": 800}'
    python video_qa.py path/to/mission --local (uses SRT files directly)
"""

import os
import sys
import json
import math
import argparse
import logging

from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint
from pipeline_utils import LOG_DIR, setup_logging, get_supabase_client

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "video_qa"

DEFAULT_THRESHOLDS = {
    "iso_ceiling": 800,
    "altitude_change_rate_ft_per_sec": 10,
    "gps_drift_threshold_meters": 5,
    "min_fps": 29,
}

# Approximate meters per degree at mid-latitudes
METERS_PER_DEG_LAT = 111_320
METERS_PER_DEG_LON = 82_000  # ~at 36N latitude (Hampton Roads)


# ─── SUPABASE ───────────────────────────────────────────────────────────────

def fetch_video_assets(client, mission_id):
    """Fetch video_assets records for a mission."""
    result = client.table("video_assets").select("*").eq("mission_id", mission_id).execute()
    return result.data or []


def fetch_thresholds(client, mission_id):
    """Fetch QA thresholds from processing_templates via the mission's package type."""
    # Get the mission's package_type (stored in drone_jobs)
    mission = client.table("missions").select("package_type").eq("id", mission_id).single().execute()
    if not mission.data:
        return DEFAULT_THRESHOLDS

    package_type = mission.data.get("package_type")
    if not package_type:
        return DEFAULT_THRESHOLDS

    # Get thresholds from processing_templates
    template = (client.table("processing_templates")
                .select("video_qa_thresholds")
                .eq("preset_name", package_type)
                .single()
                .execute())

    if template.data and template.data.get("video_qa_thresholds"):
        return template.data["video_qa_thresholds"]

    return DEFAULT_THRESHOLDS


def update_qa_status(client, asset_id, qa_status, qa_flags):
    """Update video_assets qa_status and qa_flags."""
    client.table("video_assets").update({
        "qa_status": qa_status,
        "qa_flags": qa_flags,
    }).eq("id", asset_id).execute()


# ─── QA CHECKS ───────────────────────────────────────────────────────────────

def check_iso(asset, thresholds):
    """Check if ISO exceeds ceiling."""
    ceiling = thresholds.get("iso_ceiling", 800)
    iso_max = asset.get("iso_max")
    if iso_max and iso_max > ceiling:
        return {
            "flag": "iso_spike",
            "severity": "warning" if iso_max < ceiling * 1.5 else "fail",
            "message": f"ISO max {iso_max} exceeds ceiling {ceiling}",
            "value": iso_max,
            "threshold": ceiling,
        }
    return None


def check_fps(asset, thresholds):
    """Check if FPS is below minimum."""
    min_fps = thresholds.get("min_fps", 29)
    fps = asset.get("fps")
    if fps and fps < min_fps:
        return {
            "flag": "fps_drop",
            "severity": "fail",
            "message": f"FPS {fps:.1f} below minimum {min_fps}",
            "value": fps,
            "threshold": min_fps,
        }
    return None


def check_gps_drift(asset, thresholds):
    """Check if GPS start/end positions indicate excessive drift."""
    threshold_m = thresholds.get("gps_drift_threshold_meters", 5)

    start_lat = asset.get("gps_start_lat")
    start_lon = asset.get("gps_start_lon")
    end_lat = asset.get("gps_end_lat")
    end_lon = asset.get("gps_end_lon")

    if any(v is None for v in [start_lat, start_lon, end_lat, end_lon]):
        return None

    # Simple distance calculation (good enough for short distances)
    dlat = (end_lat - start_lat) * METERS_PER_DEG_LAT
    dlon = (end_lon - start_lon) * METERS_PER_DEG_LON
    distance = math.sqrt(dlat ** 2 + dlon ** 2)

    # Only flag if the clip is short (hover footage should have minimal drift)
    duration = asset.get("duration_seconds", 0)
    if duration > 0 and duration < 30 and distance > threshold_m:
        return {
            "flag": "gps_drift",
            "severity": "warning",
            "message": f"GPS drift {distance:.1f}m in {duration:.0f}s clip (threshold: {threshold_m}m)",
            "value": round(distance, 1),
            "threshold": threshold_m,
        }
    return None


def check_altitude_high(asset, thresholds):
    """Check if altitude exceeds FAA 400ft AGL limit."""
    # SRT telemetry reports altitude in meters — convert to feet for comparison.
    # Use altitude_max (per-frame peak) if available, fall back to altitude_avg.
    alt_max_m = asset.get("altitude_max")
    alt_avg_m = asset.get("altitude_avg")
    alt_m = alt_max_m if alt_max_m is not None else alt_avg_m

    if alt_m is not None:
        alt_ft = alt_m * 3.28084  # meters to feet
        if alt_ft > 400:  # FAA limit is 400ft AGL
            label = "peak" if alt_max_m is not None else "average"
            return {
                "flag": "altitude_high",
                "severity": "warning",
                "message": f"Altitude {label} {alt_ft:.0f}ft ({alt_m:.0f}m) exceeds 400ft AGL limit",
                "value": round(alt_ft, 1),
                "threshold": 400,
            }
    return None


def check_altitude_rate(asset, thresholds):
    """Check if altitude change rate indicates jerky vertical movement.

    Uses altitude_max_change_rate (ft/s) computed by srt_telemetry_parser
    from per-frame SRT altitude data.
    """
    max_rate = thresholds.get("altitude_change_rate_ft_per_sec", 10)

    rate = asset.get("altitude_max_change_rate")
    if rate is not None and rate > max_rate:
        return {
            "flag": "altitude_jerk",
            "severity": "warning" if rate < max_rate * 2 else "fail",
            "message": f"Altitude change rate {rate:.1f} ft/s exceeds {max_rate} ft/s threshold",
            "value": round(rate, 1),
            "threshold": max_rate,
        }
    return None


def run_qa_checks(asset, thresholds):
    """Run all QA checks on a single video asset."""
    checks = [
        check_iso(asset, thresholds),
        check_fps(asset, thresholds),
        check_gps_drift(asset, thresholds),
        check_altitude_high(asset, thresholds),
        check_altitude_rate(asset, thresholds),
    ]
    flags = [c for c in checks if c is not None]
    return flags


def determine_qa_status(flags):
    """Determine overall QA status from flags.

    pass: no flags
    review: warnings only
    fail: any fail-severity flag
    """
    if not flags:
        return "pass"

    severities = {f["severity"] for f in flags}
    if "fail" in severities:
        return "fail"
    return "review"


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Video QA Analysis (Step V3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Analyzes video clip telemetry for quality issues.

Examples:
  python video_qa.py --mission-id a1b2c3d4-...
  python video_qa.py --mission-id UUID --thresholds '{"iso_ceiling": 1000}'
  python video_qa.py --mission-id UUID --dry-run
        """,
    )
    parser.add_argument("--mission-id", required=True, help="Supabase mission UUID")
    parser.add_argument("--mission-path", default=None,
                        help="Path to mission folder (for checkpoint file storage; defaults to CWD)")
    parser.add_argument("--thresholds", help="Override thresholds as JSON string")
    parser.add_argument("--dry-run", action="store_true", help="Analyze without updating Supabase")
    parser.add_argument("--force", action="store_true",
                        help="Clear checkpoint and re-process all assets from scratch")
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    mission_path = os.path.abspath(args.mission_path) if args.mission_path else os.getcwd()

    # Connect to Supabase
    try:
        client = get_supabase_client()
    except ValueError as e:
        log.error(f"Supabase configuration error: {e}")
        sys.exit(2)

    # Fetch video assets
    assets = fetch_video_assets(client, args.mission_id)
    if not assets:
        log.info(f"No video assets found for mission {args.mission_id}")
        return

    log.info(f"Mission: {args.mission_id}")
    log.info(f"Video assets: {len(assets)}")

    # Checkpoint resume
    if args.force:
        clear_checkpoint(mission_path, SCRIPT_NAME)
        log.info("--force: checkpoint cleared, re-processing all assets")
    completed = load_checkpoint(mission_path, SCRIPT_NAME)
    if completed:
        log.info(f"Resuming: {len(completed)} asset(s) already completed")

    # Get thresholds
    if args.thresholds:
        try:
            thresholds = {**DEFAULT_THRESHOLDS, **json.loads(args.thresholds)}
        except json.JSONDecodeError as e:
            log.error(f"Invalid --thresholds JSON: {e}")
            sys.exit(2)
    else:
        try:
            thresholds = fetch_thresholds(client, args.mission_id)
        except Exception:
            thresholds = DEFAULT_THRESHOLDS

    log.info(f"Thresholds: {json.dumps(thresholds)}")

    # Run QA on each asset
    mission_flags = []
    per_asset_status = []
    for asset in assets:
        filename = asset.get("filename", asset["id"])
        item_key = asset["id"]

        if item_key in completed:
            log.info(f"\n  Skip (checkpoint): {filename}")
            # Count checkpointed assets as pass for mission summary
            per_asset_status.append("pass")
            continue

        log.info(f"\n  Checking: {filename}")

        flags = run_qa_checks(asset, thresholds)
        qa_status = determine_qa_status(flags)
        per_asset_status.append(qa_status)

        for flag in flags:
            log.info(f"    [{flag['severity'].upper()}] {flag['flag']}: {flag['message']}")

        log.info(f"    Status: {qa_status}")

        if not args.dry_run:
            qa_flags_json = {f["flag"]: f for f in flags}
            update_qa_status(client, asset["id"], qa_status, qa_flags_json)
            log.info(f"    Updated in Supabase")
            completed.add(item_key)
            try:
                save_checkpoint(mission_path, SCRIPT_NAME, completed)
            except OSError as e:
                log.warning(f"    Checkpoint write failed (non-fatal): {e}")

        mission_flags.extend(flags)

    # Mission-level summary (use cached results, don't re-run checks)
    overall = determine_qa_status(mission_flags)
    pass_count = sum(1 for s in per_asset_status if s == "pass")
    ok_count = sum(1 for s in per_asset_status if s in ("pass", "review"))
    fail_count = sum(1 for s in per_asset_status if s == "fail")

    log.info(f"\n{'=' * 50}")
    log.info(f"QA Summary: {pass_count}/{len(assets)} clips passed")
    log.info(f"Mission QA: {overall}")
    log.info(f"Flags: {len(mission_flags)}")

    if fail_count > 0 and ok_count > 0:
        sys.exit(1)   # Partial failure
    elif fail_count > 0:
        sys.exit(2)   # All failed — fatal


if __name__ == "__main__":
    main()
