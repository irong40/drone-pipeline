"""
Sentinel Aerial Inspections — Delivery Packaging (Step V7 + Section 7.1)

Creates client-facing delivery ZIP from mission outputs. Renames internal
SAI_MNNNN files to property-address naming convention per spec Section 7.1.

Collects:
  - photos/jpeg/ → photos/ (renamed Sentinel_{address}_{NNN}.jpg)
  - video/exports/ → video/ (renamed Sentinel_{address}_PropertyTour_{format}.mp4)
  - mapping outputs → mapping/ (if present)
  - reports → reports/ (if present)

Supports two-stage delivery (spec Section 7.3):
  --photos-only    Package photos first while video editing continues
  --video-addendum Package video exports as a supplemental delivery

Usage:
    python delivery_packaging.py path/to/mission --address "123 Main St" --city "Virginia Beach"
    python delivery_packaging.py path/to/mission --address "456 Oak Ave" --city "Norfolk" --photos-only
    python delivery_packaging.py path/to/mission --address "456 Oak Ave" --city "Norfolk" --video-addendum
    python delivery_packaging.py path/to/mission --address "789 Elm Dr" --city "Hampton" --dry-run
"""

import os
import sys
import re
import json
import shutil
import zipfile
import argparse
import logging
from datetime import datetime
from pathlib import Path

from pipeline_status import PipelineStatusReporter, add_pipeline_args
from pipeline_utils import setup_logging

# ─── CONFIG ──────────────────────────────────────────────────────────────────

OUTPUT_ROOT = r"E:\Sentinel\Output"

# Video export format name → client-facing label
FORMAT_LABELS = {
    "instagram_reels": "Reels",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "client_4k": "4K",
    "web_preview": "WebPreview",
}

# Mapping output file patterns
MAPPING_EXTENSIONS = {".tif", ".tiff", ".obj", ".laz", ".las", ".ply"}
REPORT_EXTENSIONS = {".pdf", ".docx", ".xlsx"}


# ─── ADDRESS FORMATTING ─────────────────────────────────────────────────────

def sanitize_address(address):
    """Convert street address to filename-safe format.

    '123 Main St' → '123_Main_St'
    '456 Oak Ave, Apt 2B' → '456_Oak_Ave_Apt_2B'
    """
    # Remove characters that aren't alphanumeric, spaces, or hyphens
    clean = re.sub(r"[^\w\s-]", "", address)
    # Replace whitespace with underscores
    clean = re.sub(r"\s+", "_", clean.strip())
    return clean


def build_prefix(address, city):
    """Build the client-facing file prefix.

    Sentinel_123_Main_St_Virginia_Beach
    """
    addr = sanitize_address(address)
    city_clean = sanitize_address(city)
    return f"Sentinel_{addr}_{city_clean}"


def build_zip_name(prefix, date_str):
    """Build the ZIP filename.

    Sentinel_123_Main_St_Virginia_Beach_20260218.zip
    """
    return f"{prefix}_{date_str}.zip"


# ─── FILE COLLECTION ────────────────────────────────────────────────────────

def collect_photos(mission_path):
    """Collect JPEG photos for delivery."""
    jpeg_dir = os.path.join(mission_path, "photos", "jpeg")
    if not os.path.isdir(jpeg_dir):
        return []

    photos = []
    for fname in sorted(os.listdir(jpeg_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in (".jpg", ".jpeg"):
            photos.append(os.path.join(jpeg_dir, fname))
    return photos


def collect_video_exports(mission_path):
    """Collect video exports for delivery."""
    exports_dir = os.path.join(mission_path, "video", "exports")
    if not os.path.isdir(exports_dir):
        return []

    exports = []
    for fname in sorted(os.listdir(exports_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in (".mp4", ".mov"):
            exports.append(os.path.join(exports_dir, fname))
    return exports


def collect_mapping(mission_path):
    """Collect mapping outputs (orthophoto, 3D model, point cloud)."""
    # Check common mapping output locations
    mapping_files = []
    for subdir in ["mapping", "output", "webodm"]:
        mapping_dir = os.path.join(mission_path, subdir)
        if not os.path.isdir(mapping_dir):
            continue
        for root, _, filenames in os.walk(mapping_dir):
            for fname in filenames:
                ext = os.path.splitext(fname)[1].lower()
                if ext in MAPPING_EXTENSIONS:
                    mapping_files.append(os.path.join(root, fname))
    return sorted(mapping_files)


def collect_reports(mission_path):
    """Collect report files (PDFs, etc.)."""
    reports = []
    reports_dir = os.path.join(mission_path, "reports")
    if not os.path.isdir(reports_dir):
        return reports

    for fname in sorted(os.listdir(reports_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in REPORT_EXTENSIONS:
            reports.append(os.path.join(reports_dir, fname))
    return reports


def get_vegetation_status(mission_path):
    """Read vegetation pipeline status from mission folder.

    Returns the status string ('complete', 'failed', 'pending') or None
    if the vegetation pipeline has not been run for this mission.

    Convention: vegetation/.status file contains the status string.
    Written by vegetation_report.py (E4) on completion.
    """
    status_file = os.path.join(mission_path, "vegetation", ".status")
    if not os.path.isfile(status_file):
        return None
    try:
        with open(status_file, "r") as f:
            return f.read().strip().lower() or None
    except OSError:
        return None


# Vegetation output file extensions for delivery
VEGETATION_EXTENSIONS = {".pdf", ".png", ".geojson", ".html"}


def collect_vegetation(mission_path):
    """Collect vegetation analysis outputs for delivery.

    Only returns files when vegetation/.status == 'complete'.
    Returns empty list if status is absent, 'failed', 'pending', or any
    other non-complete value.

    Files collected: PDF report, species/health map PNGs, delivery GeoJSON,
    and optional Folium HTML — all from the mission's vegetation/ subfolder.
    """
    status = get_vegetation_status(mission_path)
    if status != "complete":
        return []

    veg_dir = os.path.join(mission_path, "vegetation")
    files = []
    for fname in sorted(os.listdir(veg_dir)):
        ext = os.path.splitext(fname)[1].lower()
        if ext in VEGETATION_EXTENSIONS:
            files.append(os.path.join(veg_dir, fname))
    return files


# ─── RENAMING ────────────────────────────────────────────────────────────────

def rename_photo(original_path, prefix, index):
    """Generate client-facing photo name.

    Sentinel_123_Main_St_Virginia_Beach_001.jpg
    """
    ext = os.path.splitext(original_path)[1].lower()
    return f"{prefix}_{index:03d}{ext}"


def rename_video_export(original_path, prefix):
    """Generate client-facing video export name.

    Sentinel_123_Main_St_Virginia_Beach_PropertyTour_YouTube.mp4

    Detects format from the export filename suffix (e.g., master_youtube.mp4).
    """
    fname = os.path.basename(original_path)
    name_lower = os.path.splitext(fname)[0].lower()
    ext = os.path.splitext(fname)[1].lower()

    # Try to match known format labels from the filename
    for format_key, label in FORMAT_LABELS.items():
        if format_key in name_lower:
            return f"{prefix}_PropertyTour_{label}{ext}"

    # Fallback: use original filename stem
    stem = os.path.splitext(fname)[0]
    return f"{prefix}_{stem}{ext}"


def rename_mapping(original_path, prefix):
    """Generate client-facing mapping output name.

    Sentinel_123_Main_St_Virginia_Beach_Orthophoto.tif
    """
    fname = os.path.basename(original_path)
    ext = os.path.splitext(fname)[1].lower()
    name_lower = fname.lower()

    if "ortho" in name_lower:
        return f"{prefix}_Orthophoto{ext}"
    elif "3d" in name_lower or "model" in name_lower or "mesh" in name_lower:
        return f"{prefix}_3DModel{ext}"
    elif "point" in name_lower or "cloud" in name_lower:
        return f"{prefix}_PointCloud{ext}"
    elif "dsm" in name_lower or "dtm" in name_lower or "dem" in name_lower:
        return f"{prefix}_ElevationModel{ext}"
    else:
        return f"{prefix}_{os.path.splitext(fname)[0]}{ext}"


def rename_report(original_path, prefix):
    """Generate client-facing report name.

    Sentinel_123_Main_St_Virginia_Beach_Inspection_Report.pdf
    """
    fname = os.path.basename(original_path)
    ext = os.path.splitext(fname)[1].lower()
    name_lower = fname.lower()

    if "inspection" in name_lower:
        return f"{prefix}_Inspection_Report{ext}"
    elif "change" in name_lower or "detection" in name_lower:
        return f"{prefix}_Change_Detection{ext}"
    else:
        stem = sanitize_address(os.path.splitext(fname)[0])
        return f"{prefix}_{stem}{ext}"


# ─── ZIP CREATION ────────────────────────────────────────────────────────────

def create_delivery_zip(zip_path, file_manifest, dry_run=False):
    """Create the delivery ZIP from a manifest of (source_path, archive_name) tuples."""
    log = logging.getLogger(__name__)

    if dry_run:
        for source, archive_name in file_manifest:
            size_mb = os.path.getsize(source) / (1024 * 1024)
            log.info(f"  [DRY RUN] {archive_name} ({size_mb:.1f} MB)")
        return None

    os.makedirs(os.path.dirname(zip_path), exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for source, archive_name in file_manifest:
            log.info(f"  Adding: {archive_name}")
            zf.write(source, archive_name)

    return zip_path


# ─── EXTRACT DATE FROM FOLDER ────────────────────────────────────────────────

def extract_date_from_folder(mission_path):
    """Extract date string from SAI_MNNNN_PKG_YYYYMMDD folder name."""
    folder_name = os.path.basename(mission_path)
    m = re.search(r"(\d{8})$", folder_name)
    if m:
        return m.group(1)
    return datetime.now().strftime("%Y%m%d")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Delivery Packaging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Creates client-facing delivery ZIP from mission outputs.

Examples:
  python delivery_packaging.py path/to/mission --address "123 Main St" --city "Virginia Beach"
  python delivery_packaging.py path/to/mission --address "456 Oak Ave" --city "Norfolk" --photos-only
  python delivery_packaging.py path/to/mission --address "456 Oak Ave" --city "Norfolk" --video-addendum
  python delivery_packaging.py path/to/mission --address "789 Elm Dr" --city "Hampton" --dry-run
        """,
    )
    parser.add_argument("mission_path", help="Path to mission folder")
    parser.add_argument("--address", required=True, help="Property street address (e.g., '123 Main St')")
    parser.add_argument("--city", required=True, help="City name (e.g., 'Virginia Beach')")
    parser.add_argument("--date", help="Override date (YYYYMMDD). Auto-detected from folder name if omitted.")
    parser.add_argument("--output-dir", default=OUTPUT_ROOT, help=f"Output directory for ZIP (default: {OUTPUT_ROOT})")
    parser.add_argument("--photos-only", action="store_true",
                        help="Package photos only (two-stage delivery: photos first)")
    parser.add_argument("--video-addendum", action="store_true",
                        help="Package video exports only (two-stage delivery: video supplement)")
    parser.add_argument("--include-mapping", action="store_true",
                        help="Include mapping outputs (orthophoto, 3D model, point cloud)")
    parser.add_argument("--include-reports", action="store_true",
                        help="Include report files (PDFs)")
    parser.add_argument("--include-vegetation", action="store_true",
                        help="Include vegetation analysis outputs (PDF, maps, GeoJSON) when pipeline is complete")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be packaged without creating ZIP")
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging("delivery_packaging")

    # Pipeline status reporter (no-op when processing_job_id is None)
    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="delivery_packaging",
    )

    mission_path = os.path.abspath(args.mission_path)
    if not os.path.isdir(mission_path):
        sys.exit(f"Mission folder not found: {mission_path}")

    if args.photos_only and args.video_addendum:
        sys.exit("Cannot use --photos-only and --video-addendum together")

    # Dry-run mode skips status reporting entirely
    if args.dry_run:
        _run_packaging(args, mission_path, log, dry_run=True)
        return

    reporter.start()

    try:
        result_data = _run_packaging(args, mission_path, log, dry_run=False)
        reporter.complete(output=result_data)
    except SystemExit:
        raise
    except Exception as e:
        reporter.fail(error=str(e))
        log.error(f"Delivery packaging failed: {e}")
        sys.exit(1)


def _run_packaging(args, mission_path, log, dry_run=False):
    """Core packaging logic. Returns result dict on success, or calls sys.exit on failure."""
    # Build naming
    prefix = build_prefix(args.address, args.city)
    date_str = args.date or extract_date_from_folder(mission_path)

    log.info(f"Mission:  {mission_path}")
    log.info(f"Address:  {args.address}, {args.city}")
    log.info(f"Prefix:   {prefix}")
    log.info(f"Date:     {date_str}")

    # Collect files based on delivery mode
    manifest = []  # List of (source_path, archive_name_in_zip)

    if args.video_addendum:
        # Video-only supplemental delivery
        log.info(f"Mode:     Video addendum")
        videos = collect_video_exports(mission_path)
        if not videos:
            raise RuntimeError("No video exports found in video/exports/. Run video_format_export.py first.")
        for vpath in videos:
            archive_name = f"video/{rename_video_export(vpath, prefix)}"
            manifest.append((vpath, archive_name))

    elif args.photos_only:
        # Photos-only first delivery
        log.info(f"Mode:     Photos only")
        photos = collect_photos(mission_path)
        if not photos:
            raise RuntimeError("No JPEG photos found in photos/jpeg/.")
        for i, ppath in enumerate(photos, 1):
            archive_name = f"photos/{rename_photo(ppath, prefix, i)}"
            manifest.append((ppath, archive_name))

    else:
        # Full delivery — everything available
        log.info(f"Mode:     Full delivery")

        # Photos
        photos = collect_photos(mission_path)
        for i, ppath in enumerate(photos, 1):
            archive_name = f"photos/{rename_photo(ppath, prefix, i)}"
            manifest.append((ppath, archive_name))

        # Video exports
        videos = collect_video_exports(mission_path)
        for vpath in videos:
            archive_name = f"video/{rename_video_export(vpath, prefix)}"
            manifest.append((vpath, archive_name))

        # Mapping (optional, included by default for full delivery if present)
        mapping = collect_mapping(mission_path)
        if mapping or args.include_mapping:
            for mpath in mapping:
                archive_name = f"mapping/{rename_mapping(mpath, prefix)}"
                manifest.append((mpath, archive_name))

        # Reports (optional)
        if args.include_reports:
            reports = collect_reports(mission_path)
            for rpath in reports:
                archive_name = f"reports/{rename_report(rpath, prefix)}"
                manifest.append((rpath, archive_name))

        # Vegetation analysis (optional — only included when pipeline is complete)
        if args.include_vegetation:
            veg_files = collect_vegetation(mission_path)
            if veg_files:
                for vpath in veg_files:
                    archive_name = f"vegetation/{os.path.basename(vpath)}"
                    manifest.append((vpath, archive_name))
                log.info(f"Vegetation: {len(veg_files)} files included")
            else:
                veg_status = get_vegetation_status(mission_path)
                if veg_status is None:
                    log.info("Vegetation: pipeline not run for this mission — skipping")
                else:
                    log.info(f"Vegetation: pipeline status='{veg_status}' — skipping (not complete)")

    if not manifest:
        raise RuntimeError("No files to package. Check mission folder contents.")

    # Summary
    photo_count = sum(1 for _, n in manifest if n.startswith("photos/"))
    video_count = sum(1 for _, n in manifest if n.startswith("video/"))
    mapping_count = sum(1 for _, n in manifest if n.startswith("mapping/"))
    report_count = sum(1 for _, n in manifest if n.startswith("reports/"))
    vegetation_count = sum(1 for _, n in manifest if n.startswith("vegetation/"))

    log.info(f"\nPackage contents:")
    log.info(f"  Photos:     {photo_count}")
    log.info(f"  Videos:     {video_count}")
    log.info(f"  Mapping:    {mapping_count}")
    log.info(f"  Reports:    {report_count}")
    log.info(f"  Vegetation: {vegetation_count}")
    log.info(f"  Total:      {len(manifest)} files")

    # Build ZIP name
    if args.video_addendum:
        zip_name = f"{prefix}_{date_str}_VideoAddendum.zip"
    elif args.photos_only:
        zip_name = f"{prefix}_{date_str}_Photos.zip"
    else:
        zip_name = build_zip_name(prefix, date_str)

    zip_path = os.path.join(args.output_dir, zip_name)
    log.info(f"\nOutput: {zip_path}")

    # Create ZIP
    result = create_delivery_zip(zip_path, manifest, dry_run=dry_run)

    if dry_run:
        log.info("\n[DRY RUN] No ZIP created.")
        return None

    if result:
        zip_size = os.path.getsize(result) / (1024 * 1024)
        log.info(f"\nDelivery ZIP created: {result} ({zip_size:.1f} MB)")

        result_data = {
            "zip_path": result,
            "zip_name": zip_name,
            "zip_size_mb": round(zip_size, 1),
            "prefix": prefix,
            "address": args.address,
            "city": args.city,
            "date": date_str,
            "photo_count": photo_count,
            "video_count": video_count,
            "mapping_count": mapping_count,
            "report_count": report_count,
            "vegetation_count": vegetation_count,
            "mode": "video_addendum" if args.video_addendum else "photos_only" if args.photos_only else "full",
        }

        # Output JSON for n8n consumption
        print(json.dumps(result_data))
        return result_data
    else:
        raise RuntimeError("ZIP creation failed")


if __name__ == "__main__":
    main()
