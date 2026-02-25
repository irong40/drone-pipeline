"""
Sentinel Aerial Inspections — Canopy Detection (Step E1)

Detects individual tree canopies from orthomosaic GeoTIFF using DeepForest.
Tiles image into configurable chunks, runs CUDA-accelerated inference,
applies cross-tile NMS, and exports polygons with geographic coordinates.

Usage:
    python canopy_detection.py --mission-id {uuid} --ortho-path E:\\Sentinel\\Output\\{id}\\mapping\\orthomosaic.tif
    python canopy_detection.py --mission-id {uuid} --ortho-path path.tif --tile-size 512 --score-threshold 0.4
"""

# ─── ENV CLEANUP (must run before any rasterio/pyproj import) ────────────────
import os
for var in ("PROJ_LIB", "PROJ_DATA"):
    os.environ.pop(var, None)
os.environ["GDAL_CACHEMAX"] = "256"

# ─── STDLIB ──────────────────────────────────────────────────────────────────
import sys
import json
import argparse
import logging
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ─── THIRD PARTY ─────────────────────────────────────────────────────────────
import numpy as np
import rasterio
from rasterio.windows import Window
from rasterio.transform import xy as rasterio_xy
from shapely.geometry import box as shapely_box, mapping
import geopandas as gpd
import torch
from deepforest import main as deepforest_main

# ─── PIPELINE MODULES ────────────────────────────────────────────────────────
from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint
from pipeline_status import PipelineStatusReporter, add_pipeline_args

# ─── CONFIG ──────────────────────────────────────────────────────────────────

LOG_DIR = r"E:\Sentinel\logs"
SCRIPT_NAME = "canopy_detection"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


# ─── LOGGING ─────────────────────────────────────────────────────────────────

def setup_logging(log_dir: str = LOG_DIR) -> logging.Logger:
    """Configure dual file+stdout logging.

    Creates log directory if it does not exist. Falls back to current directory
    if E:\\Sentinel\\logs is not writable (e.g., development machine).
    """
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{SCRIPT_NAME}.log")
    except OSError:
        log_dir = "."
        log_file = f"{SCRIPT_NAME}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


# ─── CUDA VERIFICATION ───────────────────────────────────────────────────────

def verify_cuda() -> None:
    """Assert CUDA is available and compute capability meets sm_120 requirement.

    Raises AssertionError with a clear message if either check fails.
    This mirrors the pattern established in test_environment.py.
    """
    assert torch.cuda.is_available(), (
        "CUDA not available — RTX 5070 required. "
        "Check PyTorch CUDA installation: torch.cuda.is_available() == False"
    )
    cap = torch.cuda.get_device_capability()
    cap_major = cap[0]
    assert cap_major >= 12, (
        f"GPU sm_{cap_major * 10} insufficient, need sm_120+. "
        f"RTX 5070 (sm_120) required for E-path inference."
    )


# ─── TILING ──────────────────────────────────────────────────────────────────

def compute_tile_windows(
    width: int,
    height: int,
    tile_size: int,
    overlap: int,
) -> List[Tuple[Window, int, int]]:
    """Compute rasterio Windows for a tiled scan of an image.

    Each window is padded by `overlap` pixels on all sides where possible,
    clamped to image boundaries at edges. Returns list of (window, col_off, row_off)
    where col_off/row_off are the pixel coordinates of the tile's top-left corner
    in the source image (without overlap padding) — used for coordinate transforms.

    Args:
        width: Image width in pixels.
        height: Image height in pixels.
        tile_size: Target tile size in pixels (non-overlapping core).
        overlap: Overlap padding added to each side of each tile.

    Returns:
        List of (Window, core_col_off, core_row_off) tuples.
    """
    tiles = []
    col_offsets = list(range(0, width, tile_size))
    row_offsets = list(range(0, height, tile_size))

    for row_off in row_offsets:
        for col_off in col_offsets:
            # Core tile extent (clamped to image boundary)
            core_col_end = min(col_off + tile_size, width)
            core_row_end = min(row_off + tile_size, height)

            # Padded read window with overlap on all sides
            read_col = max(0, col_off - overlap)
            read_row = max(0, row_off - overlap)
            read_col_end = min(width, core_col_end + overlap)
            read_row_end = min(height, core_row_end + overlap)

            win = Window(
                col_off=read_col,
                row_off=read_row,
                width=read_col_end - read_col,
                height=read_row_end - read_row,
            )
            tiles.append((win, col_off, row_off))

    return tiles


# ─── DEEPFOREST INFERENCE ────────────────────────────────────────────────────

def load_deepforest_model(log: logging.Logger) -> deepforest_main.deepforest:
    """Initialize DeepForest model on CUDA.

    DeepForest v2 API: use predict_image() for tile arrays, predict_tile() for
    large GeoTIFFs. Here we pre-tile ourselves, so predict_image() per tile.

    First run downloads ResNet50 weights (~98 MB) from PyTorch Hub.
    Subsequent runs use the local cache (~/.cache/torch/hub/).
    """
    log.info("Loading DeepForest model (downloading weights if first run)...")
    model = deepforest_main.deepforest()
    model.use_release()
    model.model.to("cuda")
    model.model.eval()
    log.info("DeepForest model loaded on CUDA")
    return model


def run_inference_on_tile(
    model: deepforest_main.deepforest,
    tile_array: np.ndarray,
    score_threshold: float,
) -> Optional[object]:
    """Run DeepForest inference on a single tile array.

    Args:
        model: Loaded DeepForest model (on CUDA).
        tile_array: HxWxC uint8 RGB numpy array.
        score_threshold: Minimum confidence to retain detections.

    Returns:
        DataFrame with columns [xmin, ymin, xmax, ymax, confidence, label]
        or None if no detections above threshold.
    """
    # DeepForest v2 predict_image() expects RGB uint8 numpy array (H, W, 3)
    # Convert to uint8 if needed (rasterio reads as uint8 for 8-bit imagery)
    if tile_array.dtype != np.uint8:
        # Normalize float tiles to uint8
        tile_min = tile_array.min()
        tile_max = tile_array.max()
        if tile_max > tile_min:
            tile_array = ((tile_array - tile_min) / (tile_max - tile_min) * 255).astype(np.uint8)
        else:
            tile_array = np.zeros_like(tile_array, dtype=np.uint8)

    # Ensure 3-band (RGB) — drop alpha or extra bands
    if tile_array.ndim == 3 and tile_array.shape[2] > 3:
        tile_array = tile_array[:, :, :3]
    elif tile_array.ndim == 3 and tile_array.shape[2] < 3:
        # Grayscale or 2-band — replicate to RGB
        tile_array = np.stack([tile_array[:, :, 0]] * 3, axis=2)

    try:
        results = model.predict_image(image=tile_array, return_plot=False)
    except Exception:
        return None

    if results is None or len(results) == 0:
        return None

    # Filter by score threshold
    results = results[results["score"] >= score_threshold].copy()
    if len(results) == 0:
        return None

    return results


# ─── COORDINATE TRANSFORM ────────────────────────────────────────────────────

def pixel_box_to_geo(
    dataset: rasterio.DatasetReader,
    win: Window,
    det_xmin: float,
    det_ymin: float,
    det_xmax: float,
    det_ymax: float,
) -> Tuple[float, float, float, float]:
    """Convert tile-relative pixel bounding box to geographic coordinates.

    DeepForest returns box coords relative to the tile array (0-based).
    We add the window's col_off/row_off to get absolute pixel coords in
    the source image, then use rasterio's transform to get geographic coords.

    Args:
        dataset: Open rasterio dataset.
        win: The Window used to read this tile (gives absolute pixel offset).
        det_xmin/ymin/xmax/ymax: Bounding box in tile-local pixels.

    Returns:
        (geo_xmin, geo_ymin, geo_xmax, geo_ymax) in CRS units.
    """
    # Tile-local to absolute image pixel
    abs_col_min = win.col_off + det_xmin
    abs_row_min = win.row_off + det_ymin
    abs_col_max = win.col_off + det_xmax
    abs_row_max = win.row_off + det_ymax

    # rasterio_xy(transform, row, col) -> (x, y) in CRS units
    geo_x1, geo_y1 = rasterio_xy(dataset.transform, abs_row_min, abs_col_min)
    geo_x2, geo_y2 = rasterio_xy(dataset.transform, abs_row_max, abs_col_max)

    # Normalize: xmin < xmax, ymin < ymax (y may flip in some CRS)
    geo_xmin = min(geo_x1, geo_x2)
    geo_xmax = max(geo_x1, geo_x2)
    geo_ymin = min(geo_y1, geo_y2)
    geo_ymax = max(geo_y1, geo_y2)

    return geo_xmin, geo_ymin, geo_xmax, geo_ymax


# ─── CROSS-TILE NMS ──────────────────────────────────────────────────────────

def compute_iou(poly_a, poly_b) -> float:
    """Compute Intersection over Union for two Shapely geometries."""
    if not poly_a.intersects(poly_b):
        return 0.0
    intersection = poly_a.intersection(poly_b).area
    union = poly_a.union(poly_b).area
    if union == 0.0:
        return 0.0
    return intersection / union


def cross_tile_nms(
    detections: List[Dict],
    iou_threshold: float,
) -> List[Dict]:
    """Non-maximum suppression across all tiles in geographic coordinates.

    Algorithm: sort by confidence descending, iterate; suppress any later
    detection with IoU > threshold against a kept detection.

    Args:
        detections: List of dicts with keys:
            polygon (Shapely geometry), confidence (float), label (str),
            geo_xmin, geo_ymin, geo_xmax, geo_ymax (floats)
        iou_threshold: IoU above which the lower-confidence box is suppressed.

    Returns:
        Filtered list of detections (same dict structure).
    """
    if not detections:
        return []

    # Sort descending by confidence
    sorted_dets = sorted(detections, key=lambda d: d["confidence"], reverse=True)

    kept = []
    suppressed = set()

    for i, det in enumerate(sorted_dets):
        if i in suppressed:
            continue
        kept.append(det)
        for j in range(i + 1, len(sorted_dets)):
            if j in suppressed:
                continue
            iou = compute_iou(det["polygon"], sorted_dets[j]["polygon"])
            if iou > iou_threshold:
                suppressed.add(j)

    return kept


# ─── MAIN DETECTION PIPELINE ─────────────────────────────────────────────────

def detect_canopies(
    ortho_path: str,
    tile_size: int,
    overlap: int,
    score_threshold: float,
    iou_threshold: float,
    log: logging.Logger,
) -> List[Dict]:
    """Run full canopy detection pipeline on a GeoTIFF.

    1. Opens GeoTIFF with rasterio, reads CRS and transform.
    2. Computes tile grid with overlap.
    3. Runs DeepForest inference per tile (CUDA).
    4. Transforms pixel bounding boxes to geographic coordinates.
    5. Applies cross-tile NMS to remove duplicates.

    Args:
        ortho_path: Path to source GeoTIFF orthomosaic.
        tile_size: Tile size in pixels (non-overlapping core).
        overlap: Overlap padding in pixels per side.
        score_threshold: Minimum confidence threshold for detections.
        iou_threshold: IoU threshold for NMS suppression.
        log: Logger instance.

    Returns:
        List of detection dicts with keys:
            polygon, geo_xmin, geo_ymin, geo_xmax, geo_ymax,
            centroid_x, centroid_y, confidence, label,
            width_m, height_m, area_m2
    """
    model = load_deepforest_model(log)

    all_detections: List[Dict] = []

    with rasterio.open(ortho_path) as dataset:
        crs = dataset.crs
        transform = dataset.transform
        width = dataset.width
        height = dataset.height
        band_count = dataset.count

        log.info(f"Ortho: {width}x{height}px, {band_count} bands, CRS={crs.to_epsg()}")

        tiles = compute_tile_windows(width, height, tile_size, overlap)
        log.info(f"Tiling: {len(tiles)} tiles ({tile_size}px core, {overlap}px overlap)")

        for tile_idx, (win, core_col, core_row) in enumerate(tiles):
            log.info(f"  Tile {tile_idx + 1}/{len(tiles)} col={core_col} row={core_row}")

            # Read tile as CHW array (bands, height, width)
            tile_chw = dataset.read(window=win)

            # Convert CHW -> HWC for DeepForest
            tile_hwc = np.transpose(tile_chw, (1, 2, 0))

            # Free CHW array immediately to reduce peak memory
            del tile_chw

            results_df = run_inference_on_tile(model, tile_hwc, score_threshold)
            del tile_hwc

            # Periodically flush CUDA cache to prevent fragmentation
            if tile_idx % 10 == 0:
                torch.cuda.empty_cache()

            if results_df is None:
                log.info(f"    No detections")
                continue

            log.info(f"    {len(results_df)} detections above threshold")

            # Convert each detection to geographic coordinates
            for _, row in results_df.iterrows():
                geo_xmin, geo_ymin, geo_xmax, geo_ymax = pixel_box_to_geo(
                    dataset, win,
                    float(row["xmin"]), float(row["ymin"]),
                    float(row["xmax"]), float(row["ymax"]),
                )

                polygon = shapely_box(geo_xmin, geo_ymin, geo_xmax, geo_ymax)
                centroid = polygon.centroid

                # Width/height in CRS units (meters for UTM projections)
                width_m = geo_xmax - geo_xmin
                height_m = geo_ymax - geo_ymin
                area_m2 = polygon.area

                all_detections.append({
                    "polygon": polygon,
                    "geo_xmin": geo_xmin,
                    "geo_ymin": geo_ymin,
                    "geo_xmax": geo_xmax,
                    "geo_ymax": geo_ymax,
                    "centroid_x": centroid.x,
                    "centroid_y": centroid.y,
                    "confidence": float(row["score"]),
                    "label": str(row.get("label", "Tree")),
                    "width_m": width_m,
                    "height_m": height_m,
                    "area_m2": area_m2,
                })

    log.info(f"Pre-NMS detections: {len(all_detections)}")

    # Cross-tile NMS
    deduped = cross_tile_nms(all_detections, iou_threshold)
    suppressed_count = len(all_detections) - len(deduped)
    log.info(f"Post-NMS detections: {len(deduped)} ({suppressed_count} suppressed)")

    return deduped


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Canopy Detection (Step E1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Detects individual tree canopies from orthomosaic GeoTIFF using DeepForest.

Examples:
  python canopy_detection.py --mission-id abc-123 --ortho-path E:\\Sentinel\\Output\\abc-123\\mapping\\orthomosaic.tif
  python canopy_detection.py --mission-id abc-123 --ortho-path ortho.tif --tile-size 512 --score-threshold 0.4
  python canopy_detection.py --mission-id abc-123 --ortho-path ortho.tif --force
        """,
    )
    parser.add_argument(
        "--mission-id",
        required=True,
        help="Supabase mission UUID (drone_jobs.id)",
    )
    parser.add_argument(
        "--ortho-path",
        required=True,
        help="Path to source GeoTIFF orthomosaic",
    )
    parser.add_argument(
        "--tile-size",
        type=int,
        default=1024,
        help="Tile size in pixels — non-overlapping core (default: 1024)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=128,
        help="Overlap padding in pixels per side (default: 128)",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.3,
        help="Minimum confidence threshold for detections (default: 0.3)",
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.3,
        help="IoU threshold for cross-tile NMS suppression (default: 0.3)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for results (default: same directory as --ortho-path)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear checkpoint and reprocess from scratch",
    )
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging()

    # ── Startup verification ────────────────────────────────────────────────
    log.info(f"Canopy Detection (E1) starting — mission {args.mission_id}")
    log.info(f"Ortho:          {args.ortho_path}")
    log.info(f"Tile size:      {args.tile_size}px core, {args.overlap}px overlap")
    log.info(f"Score thresh:   {args.score_threshold}")
    log.info(f"IoU thresh:     {args.iou_threshold}")

    try:
        verify_cuda()
        device_name = torch.cuda.get_device_name(0)
        cap = torch.cuda.get_device_capability()
        log.info(f"CUDA verified:  {device_name} sm_{cap[0] * 10}")
    except AssertionError as e:
        log.error(f"CUDA check failed: {e}")
        sys.exit(2)

    # ── Input validation ────────────────────────────────────────────────────
    if not os.path.isfile(args.ortho_path):
        log.error(f"Ortho file not found: {args.ortho_path}")
        sys.exit(2)

    output_dir = args.output_dir or os.path.dirname(os.path.abspath(args.ortho_path))
    os.makedirs(output_dir, exist_ok=True)

    # ── Checkpoint resume ────────────────────────────────────────────────────
    mission_dir = os.path.dirname(os.path.abspath(args.ortho_path))
    if args.force:
        clear_checkpoint(mission_dir, SCRIPT_NAME)
        log.info("--force: checkpoint cleared, reprocessing from scratch")

    # ── Pipeline status reporter ─────────────────────────────────────────────
    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="canopy_detection",
    )
    reporter.start()

    # ── Run detection ────────────────────────────────────────────────────────
    start_time = time.time()
    try:
        detections = detect_canopies(
            ortho_path=args.ortho_path,
            tile_size=args.tile_size,
            overlap=args.overlap,
            score_threshold=args.score_threshold,
            iou_threshold=args.iou_threshold,
            log=log,
        )
    except Exception as e:
        log.exception(f"Detection failed: {e}")
        reporter.fail(str(e))
        sys.exit(1)

    elapsed = time.time() - start_time
    log.info(f"Detection complete: {len(detections)} canopies in {elapsed:.1f}s")

    reporter.complete(output=f"{len(detections)} canopies detected")


if __name__ == "__main__":
    main()
