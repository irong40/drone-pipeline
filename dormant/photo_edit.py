"""
Sentinel Aerial Inspections — Path A: Photo Editing via Lightroom Classic

Applies SAI develop presets to drone photos by writing XMP sidecar files
and routing through Lightroom Classic's auto-import/export pipeline.

Flow:
    1. Maps package_type to SAI preset
    2. Copies photos to LR_AutoImport/{mission_id}/
    3. Writes .xmp sidecar files with preset settings alongside each photo
    4. Lightroom Classic auto-imports (watched folder) with sidecars applied
    5. LR plugin auto-exports edited photos to LR_Export/{mission_id}/
    6. This script polls LR_Export until all photos arrive or timeout
    7. Moves edited photos to E:\\output\\{mission_id}\\photos\\edited\\

Usage:
    python photo_edit.py --mission-id UUID --mission-path "E:\\incoming\\SAI_M0047_re_standard_20260331" --package-type re_standard
    python photo_edit.py --mission-id UUID --mission-path "..." --package-type re_standard --preset SAI-Luxury
    python photo_edit.py --mission-id UUID --mission-path "..." --package-type re_standard --dry-run
"""

import os
import sys
import json
import shutil
import argparse
import logging
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from pipeline_utils import LOG_DIR, PHOTO_EXTS, setup_logging

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "photo_edit"

LR_AUTO_IMPORT = Path(os.environ.get(
    "LR_AUTO_IMPORT",
    r"C:\Users\redle.SOULAAN\Pictures\LR_AutoImport"
))
LR_EXPORT = Path(os.environ.get(
    "LR_EXPORT",
    r"C:\Users\redle.SOULAAN\Pictures\LR_Export"
))
OUTPUT_ROOT = Path(os.environ.get("OUTPUT_ROOT", r"E:\output"))

# XMP presets directory (Adobe CameraRaw Settings)
XMP_PRESETS_DIR = Path(os.environ.get(
    "XMP_PRESETS_DIR",
    r"C:\Users\redle.SOULAAN\AppData\Roaming\Adobe\CameraRaw\Settings"
))

# Timeout waiting for LR export (seconds)
LR_EXPORT_TIMEOUT = int(os.environ.get("LR_EXPORT_TIMEOUT", "600"))  # 10 min
LR_POLL_INTERVAL = int(os.environ.get("LR_POLL_INTERVAL", "5"))  # 5 sec

# ─── PRESET MAPPING ─────────────────────────────────────────────────────────

# Maps package_type → default SAI XMP preset name
PRESET_MAP = {
    # Real estate
    "re_basic": "SAI-ListingLite",
    "re_standard": "SAI-ListingPro",
    "re_premium": "SAI-Luxury",
    # Commercial
    "commercial_basic": "SAI-Commercial",
    "commercial_premium": "SAI-Commercial",
    # Construction
    "construction_progress": "SAI-Construction",
    # Insurance / inspection
    "insurance_claim": "SAI-Inspection",
    # Survey
    "site_survey": "SAI-Commercial",
    "environmental_survey": "SAI-Commercial",
}

# Special preset for twilight/golden hour (applied based on time-of-day override)
TWILIGHT_PRESET = "SAI-NearTwilight"

logger = logging.getLogger(SCRIPT_NAME)


# ─── XMP SIDECAR GENERATION ─────────────────────────────────────────────────

def read_preset_xmp(preset_name: str) -> str | None:
    """Read an XMP preset file from the CameraRaw Settings directory."""
    xmp_path = XMP_PRESETS_DIR / f"{preset_name}.xmp"
    if not xmp_path.exists():
        logger.error("Preset not found: %s", xmp_path)
        return None
    return xmp_path.read_text(encoding="utf-8")


def write_sidecar(photo_path: Path, preset_xmp: str) -> Path:
    """Write an XMP sidecar file next to a photo.

    For photo.DNG → photo.xmp
    For photo.JPG → photo.xmp
    LR Classic reads these on import and applies the develop settings.
    """
    sidecar_path = photo_path.with_suffix(".xmp")
    sidecar_path.write_text(preset_xmp, encoding="utf-8")
    return sidecar_path


# ─── PHOTO DISCOVERY ────────────────────────────────────────────────────────

def find_photos(mission_path: Path) -> list[Path]:
    """Find all photos in a mission folder (photos/raw + photos/jpeg)."""
    photos = []
    for subdir in ["photos/raw", "photos/jpeg"]:
        photo_dir = mission_path / subdir
        if not photo_dir.exists():
            continue
        for f in sorted(photo_dir.iterdir()):
            if f.suffix.upper().lstrip(".") in PHOTO_EXTS and f.is_file():
                photos.append(f)
    # Prefer RAW (DNG) over JPEG if both exist for same base name
    raw_stems = {f.stem for f in photos if f.suffix.upper() == ".DNG"}
    deduped = [
        f for f in photos
        if f.suffix.upper() == ".DNG" or f.stem not in raw_stems
    ]
    return deduped


# ─── STAGE TO LIGHTROOM ─────────────────────────────────────────────────────

def stage_for_lightroom(
    photos: list[Path],
    mission_id: str,
    preset_xmp: str,
    dry_run: bool = False,
) -> tuple[Path, int]:
    """Copy photos + XMP sidecars to LR_AutoImport/{mission_id}/.

    Returns (import_dir, count).
    """
    import_dir = LR_AUTO_IMPORT / mission_id
    if not dry_run:
        import_dir.mkdir(parents=True, exist_ok=True)

    staged = 0
    for photo in photos:
        dest = import_dir / photo.name
        if dry_run:
            logger.info("[DRY RUN] Would copy %s → %s", photo, dest)
        else:
            shutil.copy2(photo, dest)
            write_sidecar(dest, preset_xmp)
            logger.debug("Staged: %s + sidecar", dest.name)
        staged += 1

    logger.info("Staged %d photos to %s", staged, import_dir)
    return import_dir, staged


# ─── POLL FOR EXPORT ─────────────────────────────────────────────────────────

def poll_lr_export(
    mission_id: str,
    expected_count: int,
    timeout: int = LR_EXPORT_TIMEOUT,
    interval: int = LR_POLL_INTERVAL,
) -> tuple[list[Path], bool]:
    """Poll LR_Export/{mission_id}/ until expected photo count arrives or timeout.

    Returns (exported_files, timed_out).
    """
    export_dir = LR_EXPORT / mission_id
    start = time.time()
    last_count = 0

    logger.info(
        "Waiting for %d photos in %s (timeout: %ds)",
        expected_count, export_dir, timeout,
    )

    while time.time() - start < timeout:
        if export_dir.exists():
            files = [
                f for f in export_dir.iterdir()
                if f.is_file() and f.suffix.upper().lstrip(".") in {"JPG", "JPEG", "TIFF", "TIF", "PNG"}
            ]
            if len(files) != last_count:
                last_count = len(files)
                logger.info("Export progress: %d / %d", last_count, expected_count)
            if len(files) >= expected_count:
                logger.info("All %d photos exported", len(files))
                return sorted(files), False
        time.sleep(interval)

    # Timeout — return whatever we got
    if export_dir.exists():
        files = [
            f for f in export_dir.iterdir()
            if f.is_file() and f.suffix.upper().lstrip(".") in {"JPG", "JPEG", "TIFF", "TIF", "PNG"}
        ]
        logger.warning(
            "Timeout after %ds: got %d / %d photos",
            timeout, len(files), expected_count,
        )
        return sorted(files), True
    else:
        logger.warning("Timeout: export directory never created")
        return [], True


# ─── COLLECT RESULTS ─────────────────────────────────────────────────────────

def collect_edited_photos(
    mission_id: str,
    exported_files: list[Path],
) -> Path:
    """Move exported photos from LR_Export to E:\\output\\{mission_id}\\photos\\edited\\."""
    output_dir = OUTPUT_ROOT / mission_id / "photos" / "edited"
    output_dir.mkdir(parents=True, exist_ok=True)

    for f in exported_files:
        dest = output_dir / f.name
        shutil.move(str(f), str(dest))
        logger.debug("Moved: %s → %s", f.name, dest)

    logger.info("Collected %d edited photos to %s", len(exported_files), output_dir)

    # Clean up LR_Export/{mission_id} and LR_AutoImport/{mission_id}
    export_dir = LR_EXPORT / mission_id
    import_dir = LR_AUTO_IMPORT / mission_id
    for d in [export_dir, import_dir]:
        if d.exists():
            shutil.rmtree(d)
            logger.debug("Cleaned up: %s", d)

    return output_dir


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run(
    mission_id: str,
    mission_path: str,
    package_type: str,
    preset_override: str | None = None,
    dry_run: bool = False,
    skip_poll: bool = False,
    timeout: int = LR_EXPORT_TIMEOUT,
) -> dict:
    """Execute Path A photo editing pipeline.

    Returns JSON-serializable result dict.
    """
    mission_dir = Path(mission_path)
    if not mission_dir.exists():
        raise FileNotFoundError(f"Mission folder not found: {mission_dir}")

    # Resolve preset
    if preset_override:
        preset_name = preset_override
    else:
        preset_name = PRESET_MAP.get(package_type)
        if not preset_name:
            raise ValueError(
                f"No preset mapped for package_type '{package_type}'. "
                f"Known types: {', '.join(sorted(PRESET_MAP.keys()))}"
            )

    logger.info("Path A: mission=%s package=%s preset=%s", mission_id, package_type, preset_name)

    # Read preset XMP
    preset_xmp = read_preset_xmp(preset_name)
    if not preset_xmp:
        raise FileNotFoundError(f"XMP preset file not found: {preset_name}")

    # Find photos
    photos = find_photos(mission_dir)
    if not photos:
        logger.warning("No photos found in %s", mission_dir)
        return {
            "status": "skipped",
            "mission_id": mission_id,
            "reason": "no_photos",
            "photo_count": 0,
        }

    logger.info("Found %d photos (%d DNG, %d JPG)",
                len(photos),
                sum(1 for p in photos if p.suffix.upper() == ".DNG"),
                sum(1 for p in photos if p.suffix.upper() in (".JPG", ".JPEG")))

    # Stage to Lightroom
    import_dir, staged_count = stage_for_lightroom(
        photos, mission_id, preset_xmp, dry_run=dry_run,
    )

    if dry_run:
        return {
            "status": "dry_run",
            "mission_id": mission_id,
            "preset": preset_name,
            "photo_count": staged_count,
            "import_dir": str(import_dir),
        }

    if skip_poll:
        return {
            "status": "staged",
            "mission_id": mission_id,
            "preset": preset_name,
            "photo_count": staged_count,
            "import_dir": str(import_dir),
            "message": "Photos staged for Lightroom. Run with --poll to wait for export.",
        }

    # Poll for LR export
    exported_files, timed_out = poll_lr_export(mission_id, staged_count, timeout=timeout)

    if not exported_files:
        return {
            "status": "error",
            "mission_id": mission_id,
            "preset": preset_name,
            "photo_count": staged_count,
            "exported_count": 0,
            "error": "No exported files found. Is Lightroom Classic running with auto-import enabled?",
        }

    # Collect results
    output_dir = collect_edited_photos(mission_id, exported_files)

    return {
        "status": "partial" if timed_out else "complete",
        "mission_id": mission_id,
        "preset": preset_name,
        "photo_count": staged_count,
        "exported_count": len(exported_files),
        "output_path": str(output_dir),
        "timed_out": timed_out,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Path A — Photo editing via Lightroom Classic",
    )
    parser.add_argument("--mission-id", required=True, help="Mission UUID")
    parser.add_argument("--mission-path", required=True, help="Path to mission folder")
    parser.add_argument("--package-type", required=True, help="Package type (re_standard, etc.)")
    parser.add_argument("--preset", default=None, help="Override preset name (e.g. SAI-NearTwilight)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without copying")
    parser.add_argument("--skip-poll", action="store_true", help="Stage photos only, don't wait for LR export")
    parser.add_argument("--timeout", type=int, default=LR_EXPORT_TIMEOUT, help="Export poll timeout (seconds)")
    args = parser.parse_args()

    setup_logging(SCRIPT_NAME)

    try:
        result = run(
            mission_id=args.mission_id,
            mission_path=args.mission_path,
            package_type=args.package_type,
            preset_override=args.preset,
            dry_run=args.dry_run,
            skip_poll=args.skip_poll,
            timeout=args.timeout,
        )
        print(json.dumps(result))
        sys.exit(0 if result["status"] in ("complete", "staged", "dry_run", "skipped") else 1)
    except Exception as e:
        logger.exception("Path A failed: %s", e)
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
