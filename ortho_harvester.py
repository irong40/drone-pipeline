"""
Sentinel Aerial Inspections -- Ortho Harvester (Step E3)

Copies a GeoTIFF orthomosaic from MipMap workspace to the mission's mapping/
folder, then verifies copy integrity via file size comparison and rasterio
header validation.

Usage:
    python ortho_harvester.py --source-path D:\\MipMapWorkspace\\ortho.tif \\
        --mission-path E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218 \\
        --mission-id abc-123
"""

import os
import sys
import json
import shutil
import struct
import logging
import argparse
from pathlib import Path

from pipeline_status import PipelineStatusReporter, add_pipeline_args
from pipeline_utils import setup_logging

# ── CONFIG ───────────────────────────────────────────────────────────────────

SCRIPT_NAME = "ortho_harvester"

# Try importing rasterio; degrade gracefully if unavailable
try:
    import rasterio
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False


# ── GEOTIFF VALIDATION ──────────────────────────────────────────────────────

def validate_geotiff(path):
    """Validate a GeoTIFF file using rasterio (or TIFF magic bytes fallback).

    Returns:
        (bool, str): (is_valid, info_or_error_message)
    """
    if HAS_RASTERIO:
        return _validate_geotiff_rasterio(path)
    else:
        return _validate_geotiff_fallback(path)


def _validate_geotiff_rasterio(path):
    """Full validation using rasterio: CRS, dimensions, bands, read test."""
    try:
        ds = rasterio.open(path)
    except Exception as e:
        return False, f"rasterio open error: {e}"

    try:
        if ds.crs is None:
            return False, "No CRS defined"

        if ds.width <= 0 or ds.height <= 0:
            return False, f"Zero dimensions: {ds.width}x{ds.height}"

        if ds.count <= 0:
            return False, "No bands found"

        # Read a tiny window to verify data is accessible
        ds.read(1, window=((0, 1), (0, 1)))

        info = (
            f"Valid GeoTIFF: {ds.width}x{ds.height}, "
            f"{ds.count} band(s), CRS={ds.crs}"
        )
        return True, info
    except Exception as e:
        return False, f"Validation error: {e}"
    finally:
        if hasattr(ds, 'close'):
            try:
                ds.close()
            except Exception:
                pass


def _validate_geotiff_fallback(path):
    """Degraded validation when rasterio is not available.

    Checks TIFF magic bytes (0x4949 little-endian or 0x4D4D big-endian)
    and file size only.
    """
    log = logging.getLogger(__name__)
    log.warning("rasterio not available -- using degraded TIFF magic-byte validation")

    try:
        size = os.path.getsize(path)
        if size < 8:
            return False, f"File too small to be a valid TIFF: {size} bytes"

        with open(path, "rb") as f:
            magic = f.read(2)

        if magic == b"\x49\x49" or magic == b"\x4d\x4d":
            return True, f"TIFF magic bytes OK, size={size} bytes (degraded check)"
        else:
            return False, f"Not a TIFF file (magic bytes: {magic.hex()})"
    except Exception as e:
        return False, f"Fallback validation error: {e}"


# ── COPY INTEGRITY ──────────────────────────────────────────────────────────

def verify_copy_integrity(source, dest):
    """Verify copy integrity: file size comparison + GeoTIFF validation.

    Returns:
        (bool, str): (is_valid, info_or_error_message)
    """
    src_size = os.path.getsize(source)
    dst_size = os.path.getsize(dest)

    if src_size != dst_size:
        return False, f"Size mismatch: source={src_size}, dest={dst_size}"

    valid, info = validate_geotiff(dest)
    if not valid:
        return False, f"GeoTIFF validation failed on copy: {info}"

    return True, f"Integrity OK: size={dst_size}, {info}"


# ── COPY OPERATION ──────────────────────────────────────────────────────────

def copy_ortho(source_path, mission_path):
    """Copy GeoTIFF from source to mission mapping/ folder.

    Uses temp-file-then-rename pattern for safety against interruption.

    Args:
        source_path: Path to source GeoTIFF in MipMap workspace
        mission_path: Path to mission folder (mapping/ created inside)

    Returns:
        str: Path to the copied file in mapping/ folder
    """
    mapping_dir = os.path.join(mission_path, "mapping")
    os.makedirs(mapping_dir, exist_ok=True)

    filename = os.path.basename(source_path)
    dest_path = os.path.join(mapping_dir, filename)
    temp_path = dest_path + ".tmp"

    # Copy to temp file first (atomic-ish: avoids partial files on interrupt)
    shutil.copy2(source_path, temp_path)

    # Rename temp to final destination
    os.rename(temp_path, dest_path)

    return dest_path


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections -- Ortho Harvester (Step E3)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Copies GeoTIFF orthomosaic from MipMap workspace to mission mapping/ folder
with integrity verification (size match + rasterio header check).

Examples:
  python ortho_harvester.py --source-path D:\\MipMapWorkspace\\ortho.tif \\
      --mission-path E:\\Sentinel\\Incoming\\SAI_M0047 --mission-id abc-123
        """,
    )
    parser.add_argument("--source-path", required=True,
                        help="Path to source GeoTIFF in MipMap workspace")
    parser.add_argument("--mission-path", required=True,
                        help="Path to mission folder (mapping/ subfolder created inside)")
    parser.add_argument("--mission-id", required=True,
                        help="Mission identifier for logging")
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    source_path = os.path.abspath(args.source_path)
    mission_path = os.path.abspath(args.mission_path)

    # Config validation: source must exist
    if not os.path.isfile(source_path):
        log.error(f"Source GeoTIFF not found: {source_path}")
        sys.exit(2)

    # Config validation: mission folder must exist
    if not os.path.isdir(mission_path):
        log.error(f"Mission folder not found: {mission_path}")
        sys.exit(2)

    log.info(f"Mission:    {args.mission_id}")
    log.info(f"Source:     {source_path}")
    log.info(f"Dest:       {mission_path}/mapping/")

    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="ortho_harvester",
    )
    reporter.start()

    try:
        # Copy with temp-file pattern
        dest_path = copy_ortho(source_path, mission_path)
        log.info(f"Copied to: {dest_path}")

        # Verify integrity
        valid, info = verify_copy_integrity(source_path, dest_path)
        if not valid:
            log.error(f"Integrity check failed: {info}")
            reporter.fail(f"Integrity check failed: {info}")
            sys.exit(1)

        log.info(f"Integrity: {info}")

        # JSON result on stdout
        result = {
            "status": "success",
            "source": source_path,
            "destination": dest_path,
            "validation": info,
            "mission_id": args.mission_id,
        }
        print(json.dumps(result))

        reporter.complete(output=f"Copied {os.path.basename(source_path)} -> mapping/")

    except SystemExit:
        raise
    except Exception as e:
        log.error(f"ortho_harvester failed: {e}")
        reporter.fail(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
