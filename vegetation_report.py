"""
Sentinel Aerial Inspections — Vegetation Report Generation (Step E4)

Generates map overlays (species PNG, health PNG), delivery GeoJSON, interactive
Folium HTML map, and PDF summary report from canopy detection and assessment data.

Usage:
    python vegetation_report.py --mission-id {uuid} --ortho-path path.tif --output-dir /path/to/output
    python vegetation_report.py --mission-id {uuid} --ortho-path path.tif --tier extended --output-dir /path/to/output
    python vegetation_report.py --mission-id {uuid} --ortho-path path.tif --tier comprehensive --output-dir /path/to/output
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── THIRD PARTY ─────────────────────────────────────────────────────────────
import numpy as np
import rasterio
import rasterio.plot
from rasterio.mask import mask as rasterio_mask
from rasterio.crs import CRS
from shapely import wkt as shapely_wkt
from shapely.geometry import mapping as shapely_mapping
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend — must be set before pyplot import
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import folium
from folium import GeoJson

# ─── PIPELINE MODULES ────────────────────────────────────────────────────────
from pipeline_status import PipelineStatusReporter, add_pipeline_args

# ─── CONFIG ──────────────────────────────────────────────────────────────────

LOG_DIR = r"E:\Sentinel\logs"
SCRIPT_NAME = "vegetation_report"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# Folium file size warning threshold
FOLIUM_SIZE_WARN_MB = 10.0
# Folium geometry simplification tolerances
FOLIUM_SIMPLIFY_INITIAL = 0.000005  # ~0.5m — first pass
FOLIUM_SIMPLIFY_AGGRESSIVE = 0.00002  # ~2m — if still > 10 MB

# Output DPI for PNG maps
MAP_DPI = 300

SUPABASE_BATCH_SIZE = 50


# ─── SPECIES COLOR PALETTE ────────────────────────────────────────────────────

SPECIES_COLORS: Dict[str, str] = {
    "Loblolly Pine": "#006400",
    "Live Oak": "#228B22",
    "Red Maple": "#DC143C",
    "Sweetgum": "#FF8C00",
    "Eastern Redcedar": "#2E8B57",
    "Bald Cypress": "#8B4513",
    "Southern Magnolia": "#FF69B4",
    "Tulip Poplar": "#FFD700",
    "Willow Oak": "#556B2F",
    "American Holly": "#00CED1",
    "Virginia Pine": "#3CB371",
    "White Oak": "#DEB887",
    "Black Cherry": "#8B0000",
    "River Birch": "#D2691E",
    "Eastern White Pine": "#90EE90",
    "American Sycamore": "#F5DEB3",
    "Crape Myrtle": "#DA70D6",
    "Wax Myrtle": "#9ACD32",
    "Leyland Cypress": "#008080",
    "Sabal Palmetto": "#32CD32",
}

SPECIES_DEFAULT_COLOR = "#808080"  # Gray for unrecognized species


# ─── HEALTH STATUS COLOR PALETTE ─────────────────────────────────────────────

HEALTH_COLORS: Dict[str, str] = {
    "healthy": "#22C55E",
    "moderate_stress": "#EAB308",
    "stressed": "#F97316",
    "severe_decline": "#EF4444",
    "dead": "#000000",
}

HEALTH_LABELS: Dict[str, str] = {
    "healthy": "Healthy",
    "moderate_stress": "Moderate Stress",
    "stressed": "Stressed",
    "severe_decline": "Severe Decline",
    "dead": "Dead / No Canopy",
}


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


# ─── SUPABASE ────────────────────────────────────────────────────────────────

def _get_supabase_client(log: logging.Logger):
    """Return a Supabase client or None if credentials are missing."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        log.warning(
            "Supabase credentials not set (SUPABASE_URL / SUPABASE_SERVICE_KEY). "
            "Skipping Supabase operations."
        )
        return None
    try:
        from supabase import create_client
        return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except ImportError:
        log.warning("supabase package not installed. Skipping Supabase operations.")
        return None
    except Exception as exc:
        log.warning(f"Supabase client creation failed: {exc}. Skipping Supabase operations.")
        return None


def fetch_detections(
    mission_id: str,
    log: logging.Logger,
) -> List[Dict[str, Any]]:
    """Fetch all canopy detections for the mission from Supabase.

    Returns list of dicts with all vegetation_detections columns.
    Returns empty list on failure — caller handles gracefully.

    Args:
        mission_id: Supabase drone_jobs.id UUID.
        log: Logger instance.
    """
    client = _get_supabase_client(log)
    if client is None:
        return []
    try:
        result = (
            client.table("vegetation_detections")
            .select(
                "id, detection_index, geometry_wkt, centroid_lat, centroid_lon, "
                "canopy_area_sqm, canopy_width_m, canopy_height_m, detection_confidence, "
                "species_tag, species_confidence, vegetation_type, "
                "health_score, health_status, health_details, "
                "recommended_action"
            )
            .eq("mission_id", mission_id)
            .order("detection_index")
            .execute()
        )
        return result.data or []
    except Exception as exc:
        log.error(f"Supabase fetch failed: {exc}")
        return []


def fetch_mission_info(
    mission_id: str,
    log: logging.Logger,
) -> Dict[str, Any]:
    """Fetch mission metadata (address, date) for report title.

    Returns empty dict on failure — caller uses fallback values.
    """
    client = _get_supabase_client(log)
    if client is None:
        return {}
    try:
        result = (
            client.table("drone_jobs")
            .select("id, job_name, created_at, location")
            .eq("id", mission_id)
            .single()
            .execute()
        )
        return result.data or {}
    except Exception as exc:
        log.warning(f"Mission info fetch failed: {exc}")
        return {}


def write_vegetation_summary(
    mission_id: str,
    summary: Dict[str, Any],
    log: logging.Logger,
) -> None:
    """Upsert vegetation analysis summary row for this mission.

    Non-fatal: logs warning on failure.
    """
    client = _get_supabase_client(log)
    if client is None:
        return
    try:
        client.table("vegetation_analysis_summary").upsert(
            {"mission_id": mission_id, **summary},
            on_conflict="mission_id",
        ).execute()
        log.info("Supabase: vegetation_analysis_summary upserted")
    except Exception as exc:
        log.warning(f"Supabase summary write failed: {exc}")


# ─── MAP HELPER UTILITIES ─────────────────────────────────────────────────────

def _ortho_rgb_array(dataset: rasterio.DatasetReader) -> Tuple[np.ndarray, Any]:
    """Read orthomosaic RGB array for matplotlib rendering.

    Returns (rgb_hwc, transform) where rgb_hwc shape is (H, W, 3) uint8.
    Handles nodata, alpha channels, and >3-band rasters gracefully.
    """
    # Read first 3 bands
    bands = min(dataset.count, 3)
    data = dataset.read(list(range(1, bands + 1)))  # (bands, H, W)

    # Normalize to uint8 if needed
    if data.dtype != np.uint8:
        dmin, dmax = data.min(), data.max()
        if dmax > dmin:
            data = ((data - dmin) / (dmax - dmin) * 255).astype(np.uint8)
        else:
            data = np.zeros_like(data, dtype=np.uint8)

    if bands == 3:
        rgb = np.transpose(data, (1, 2, 0))  # HWC
    else:
        # Pad to 3 channels
        padded = np.zeros((3, data.shape[1], data.shape[2]), dtype=np.uint8)
        padded[:bands] = data
        rgb = np.transpose(padded, (1, 2, 0))

    return rgb, dataset.transform


def _add_north_arrow(ax: plt.Axes) -> None:
    """Add a simple north arrow to the top-right corner of the axes."""
    ax.annotate(
        "N",
        xy=(0.96, 0.94),
        xycoords="axes fraction",
        fontsize=12,
        fontweight="bold",
        ha="center",
        va="center",
        color="black",
        bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.7, edgecolor="gray"),
    )
    ax.annotate(
        "",
        xy=(0.96, 0.96),
        xycoords="axes fraction",
        xytext=(0.96, 0.90),
        arrowprops=dict(arrowstyle="->", color="black", lw=2),
    )


def _add_scale_bar(ax: plt.Axes, dataset: rasterio.DatasetReader) -> None:
    """Add a simple scale bar based on raster pixel size.

    Uses the x-axis pixel size from the dataset transform to compute
    a round-number scale in meters. Skipped if CRS units are unknown.
    """
    try:
        crs = dataset.crs
        transform = dataset.transform
        pixel_width_m = abs(transform.a)
        if crs and crs.is_geographic:
            # Convert degrees to meters at mid-latitude (rough)
            lat = dataset.bounds.top
            pixel_width_m = abs(transform.a) * 111320 * abs(float(lat) / 90 if lat else 1)

        # Pick a round bar length that fits in ~15% of the image width
        image_width_px = dataset.width
        target_bar_m = pixel_width_m * image_width_px * 0.15
        # Round to nearest 5 / 10 / 25 / 50 / 100 / 250 / 500 / 1000
        candidates = [5, 10, 25, 50, 100, 250, 500, 1000]
        bar_m = min(candidates, key=lambda c: abs(c - target_bar_m))
        bar_px = bar_m / pixel_width_m

        # Convert to axes fraction
        bar_frac = bar_px / image_width_px

        # Draw scale bar at lower-left
        ax.annotate(
            f"{bar_m} m",
            xy=(0.04, 0.04),
            xycoords="axes fraction",
            fontsize=9,
            ha="left",
            va="bottom",
            color="white",
            fontweight="bold",
        )
        ax.axhline(y=0.0, xmin=0.04, xmax=0.04 + bar_frac, lw=3, color="white",
                   transform=ax.transAxes, clip_on=False)
    except Exception:
        pass  # Scale bar is cosmetic — never fail the render


def _sentinel_branding(ax: plt.Axes) -> None:
    """Add Sentinel Aerial Inspections branding text to lower-right."""
    ax.text(
        0.98, 0.02,
        "Sentinel Aerial Inspections\nsentinelaerial.com",
        transform=ax.transAxes,
        fontsize=7,
        ha="right",
        va="bottom",
        color="white",
        alpha=0.85,
        bbox=dict(boxstyle="round,pad=0.2", facecolor="black", alpha=0.4, edgecolor="none"),
    )


# ─── TASK 1: SPECIES AND HEALTH OVERLAY MAP PNGs ─────────────────────────────

def generate_species_map(
    ortho_path: str,
    detections: List[Dict[str, Any]],
    output_path: str,
    mission_label: str = "",
    log: Optional[logging.Logger] = None,
) -> bool:
    """Render orthomosaic with color-coded species canopy overlays.

    Each canopy polygon is rendered with its species color (SPECIES_COLORS palette,
    20 Hampton Roads species). Unknown species use gray. Polygons are semi-transparent
    (alpha=0.5) so the orthomosaic basemap remains visible.

    Output: PNG at 300 DPI with legend, north arrow, scale bar, Sentinel branding.

    Args:
        ortho_path: Path to the source GeoTIFF orthomosaic.
        detections: List of detection dicts from Supabase (must include geometry_wkt, species_tag).
        output_path: Full path for the output PNG file.
        mission_label: Property address + date for figure title.
        log: Logger instance.

    Returns:
        True on success, False on failure.
    """
    if log is None:
        log = logging.getLogger(__name__)

    log.info(f"Generating species map: {output_path}")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    try:
        with rasterio.open(ortho_path) as dataset:
            rgb, transform = _ortho_rgb_array(dataset)

            fig, ax = plt.subplots(figsize=(14, 10), dpi=MAP_DPI)

            # Render orthomosaic basemap
            rasterio.plot.show(dataset, ax=ax, title=None)

            # Overlay species polygons
            seen_species = {}
            failed_polys = 0

            for det in detections:
                wkt_str = det.get("geometry_wkt", "")
                if not wkt_str:
                    continue
                species = det.get("species_tag") or "Unknown"
                color = SPECIES_COLORS.get(species, SPECIES_DEFAULT_COLOR)

                try:
                    polygon = shapely_wkt.loads(wkt_str)
                    xs, ys = polygon.exterior.xy
                    ax.fill(xs, ys, alpha=0.5, fc=color, ec=color, lw=0.5)
                    seen_species[species] = color
                except Exception as exc:
                    failed_polys += 1
                    log.debug(f"  Could not render polygon for detection {det.get('detection_index', '?')}: {exc}")

            if failed_polys > 0:
                log.warning(f"  {failed_polys} polygon(s) could not be rendered (bad WKT or geometry error)")

            # Legend: only species that appear on this map
            legend_patches = [
                mpatches.Patch(facecolor=color, edgecolor="gray", alpha=0.8, label=species)
                for species, color in sorted(seen_species.items())
            ]
            if legend_patches:
                ax.legend(
                    handles=legend_patches,
                    loc="upper left",
                    fontsize=8,
                    framealpha=0.85,
                    title="Species",
                    title_fontsize=9,
                )

            # Title
            title = "Species Distribution Map"
            if mission_label:
                title = f"{title}\n{mission_label}"
            ax.set_title(title, fontsize=13, fontweight="bold", pad=10)

            # Decorations
            _add_north_arrow(ax)
            _add_scale_bar(ax, dataset)
            _sentinel_branding(ax)

            ax.set_xlabel("")
            ax.set_ylabel("")
            plt.tight_layout()
            fig.savefig(output_path, dpi=MAP_DPI, bbox_inches="tight")
            plt.close(fig)

        log.info(f"Species map saved: {output_path}")
        return True

    except Exception as exc:
        log.error(f"Species map generation failed: {exc}")
        try:
            plt.close("all")
        except Exception:
            pass
        return False


def generate_health_map(
    ortho_path: str,
    detections: List[Dict[str, Any]],
    output_path: str,
    mission_label: str = "",
    log: Optional[logging.Logger] = None,
) -> bool:
    """Render orthomosaic with color-coded health status canopy overlays.

    Health status color mapping:
        healthy          -> #22C55E (green)
        moderate_stress  -> #EAB308 (yellow)
        stressed         -> #F97316 (orange)
        severe_decline   -> #EF4444 (red)
        dead             -> #000000 (black)

    Output: PNG at 300 DPI with legend, north arrow, scale bar, Sentinel branding.

    Args:
        ortho_path: Path to the source GeoTIFF orthomosaic.
        detections: List of detection dicts (must include geometry_wkt, health_status).
        output_path: Full path for the output PNG file.
        mission_label: Property address + date for figure title.
        log: Logger instance.

    Returns:
        True on success, False on failure.
    """
    if log is None:
        log = logging.getLogger(__name__)

    log.info(f"Generating health map: {output_path}")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    try:
        with rasterio.open(ortho_path) as dataset:
            fig, ax = plt.subplots(figsize=(14, 10), dpi=MAP_DPI)

            # Render orthomosaic basemap
            rasterio.plot.show(dataset, ax=ax, title=None)

            # Overlay health polygons
            seen_statuses = set()
            failed_polys = 0

            for det in detections:
                wkt_str = det.get("geometry_wkt", "")
                if not wkt_str:
                    continue
                status = det.get("health_status") or "unknown"
                color = HEALTH_COLORS.get(status, SPECIES_DEFAULT_COLOR)

                try:
                    polygon = shapely_wkt.loads(wkt_str)
                    xs, ys = polygon.exterior.xy
                    ax.fill(xs, ys, alpha=0.5, fc=color, ec=color, lw=0.5)
                    seen_statuses.add(status)
                except Exception as exc:
                    failed_polys += 1
                    log.debug(f"  Could not render polygon for detection {det.get('detection_index', '?')}: {exc}")

            if failed_polys > 0:
                log.warning(f"  {failed_polys} polygon(s) could not be rendered")

            # Legend: ordered by severity
            status_order = ["healthy", "moderate_stress", "stressed", "severe_decline", "dead"]
            legend_patches = [
                mpatches.Patch(
                    facecolor=HEALTH_COLORS[status],
                    edgecolor="gray",
                    alpha=0.8,
                    label=HEALTH_LABELS[status],
                )
                for status in status_order
                if status in seen_statuses and status in HEALTH_COLORS
            ]
            if legend_patches:
                ax.legend(
                    handles=legend_patches,
                    loc="upper left",
                    fontsize=9,
                    framealpha=0.85,
                    title="Health Status",
                    title_fontsize=10,
                )

            # Title
            title = "Canopy Health Assessment Map"
            if mission_label:
                title = f"{title}\n{mission_label}"
            ax.set_title(title, fontsize=13, fontweight="bold", pad=10)

            # Decorations
            _add_north_arrow(ax)
            _add_scale_bar(ax, dataset)
            _sentinel_branding(ax)

            ax.set_xlabel("")
            ax.set_ylabel("")
            plt.tight_layout()
            fig.savefig(output_path, dpi=MAP_DPI, bbox_inches="tight")
            plt.close(fig)

        log.info(f"Health map saved: {output_path}")
        return True

    except Exception as exc:
        log.error(f"Health map generation failed: {exc}")
        try:
            plt.close("all")
        except Exception:
            pass
        return False


# ─── TASK 2: GeoJSON EXPORT AND FOLIUM INTERACTIVE MAP ───────────────────────

def _detection_to_geodataframe(detections: List[Dict[str, Any]]) -> gpd.GeoDataFrame:
    """Convert detection dicts to a GeoDataFrame in EPSG:4326.

    Geometry is sourced from geometry_wkt. Coordinate precision is reduced to
    6 decimal places (~11cm precision) for delivery file size control.

    Returns empty GeoDataFrame if all geometries are invalid.
    """
    from shapely.geometry import shape
    import pyproj
    from pyproj import Transformer

    rows = []
    for det in detections:
        wkt_str = det.get("geometry_wkt", "")
        if not wkt_str:
            continue
        try:
            geom = shapely_wkt.loads(wkt_str)
            rows.append({
                "detection_index": det.get("detection_index"),
                "species_tag": det.get("species_tag", "Unknown"),
                "species_confidence": det.get("species_confidence"),
                "health_score": det.get("health_score"),
                "health_status": det.get("health_status"),
                "canopy_area_sqm": det.get("canopy_area_sqm"),
                "detection_confidence": det.get("detection_confidence"),
                "recommended_action": det.get("recommended_action") or (
                    det.get("health_details", {}) or {}
                ).get("vision", {}) and
                (det.get("health_details", {}) or {}).get("vision", {}).get("recommended_action"),
                "geometry": geom,
            })
        except Exception:
            continue

    if not rows:
        return gpd.GeoDataFrame(columns=["geometry"], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    return gdf


def _recommended_action_from_det(det: Dict[str, Any]) -> str:
    """Extract recommended_action from detection, falling back through health_details."""
    # Direct field first
    if det.get("recommended_action"):
        return str(det["recommended_action"])
    # Try to get from health_details.vision
    try:
        hd = det.get("health_details") or {}
        vision = hd.get("vision") or {}
        if vision and vision.get("recommended_action"):
            return str(vision["recommended_action"])
    except Exception:
        pass
    # Fallback from health_status
    status = det.get("health_status", "")
    if status == "healthy":
        return "monitor"
    if status in ("moderate_stress",):
        return "inspect"
    if status in ("stressed", "severe_decline", "dead"):
        return "urgent"
    return "monitor"


def export_geojson(
    detections: List[Dict[str, Any]],
    output_path: str,
    ortho_crs: Optional[Any] = None,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Export all canopy detections as GeoJSON with full attribute set.

    CRS is set to EPSG:4326 for delivery (reprojects if source CRS differs).
    Coordinate precision is reduced to 6 decimal places.

    Attributes per feature:
        detection_index, species_tag, species_confidence, health_score,
        health_status, canopy_area_sqm, detection_confidence, recommended_action

    Args:
        detections: List of detection dicts from Supabase.
        output_path: Full path for output GeoJSON file.
        ortho_crs: CRS of the orthomosaic (from rasterio dataset.crs). Used to
            reproject if geometry_wkt is not already in EPSG:4326.
        log: Logger instance.

    Returns:
        True on success, False on failure.
    """
    if log is None:
        log = logging.getLogger(__name__)

    log.info(f"Exporting GeoJSON: {output_path}")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if not detections:
        log.warning("No detections to export — GeoJSON will be empty FeatureCollection")

    try:
        rows = []
        for det in detections:
            wkt_str = det.get("geometry_wkt", "")
            if not wkt_str:
                continue
            try:
                geom = shapely_wkt.loads(wkt_str)
                rows.append({
                    "detection_index": det.get("detection_index"),
                    "species_tag": det.get("species_tag", "Unknown"),
                    "species_confidence": det.get("species_confidence"),
                    "health_score": det.get("health_score"),
                    "health_status": det.get("health_status"),
                    "canopy_area_sqm": det.get("canopy_area_sqm"),
                    "detection_confidence": det.get("detection_confidence"),
                    "recommended_action": _recommended_action_from_det(det),
                    "geometry": geom,
                })
            except Exception as exc:
                log.debug(f"Skipping detection {det.get('detection_index', '?')} — bad geometry: {exc}")
                continue

        if not rows:
            # Write empty FeatureCollection
            import json as _json
            with open(output_path, "w", encoding="utf-8") as f:
                _json.dump({"type": "FeatureCollection", "features": []}, f)
            log.warning("GeoJSON exported as empty FeatureCollection — no valid geometries")
            return True

        gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")

        # If ortho CRS is not EPSG:4326, reproject
        if ortho_crs and not ortho_crs.to_epsg() == 4326:
            try:
                gdf = gdf.set_crs(ortho_crs, allow_override=True)
                gdf = gdf.to_crs("EPSG:4326")
                log.info(f"  Reprojected from {ortho_crs.to_string()} to EPSG:4326")
            except Exception as exc:
                log.warning(f"  CRS reprojection failed: {exc} — keeping original CRS")

        # Simplify geometry slightly (tolerance=0 = no simplification) to round coords
        # Use shapely set_precision for coordinate rounding to 6 decimals
        try:
            from shapely import set_precision
            gdf["geometry"] = gdf["geometry"].apply(
                lambda g: set_precision(g, grid_size=1e-6) if g is not None else g
            )
        except ImportError:
            # Older shapely: apply coordinate precision manually
            log.debug("shapely.set_precision not available — skipping coord precision reduction")

        # Export GeoJSON
        gdf.to_file(output_path, driver="GeoJSON")
        log.info(f"GeoJSON exported: {output_path} ({len(rows)} features)")
        return True

    except Exception as exc:
        log.error(f"GeoJSON export failed: {exc}")
        return False


def generate_folium_map(
    detections: List[Dict[str, Any]],
    ortho_bounds: Optional[Tuple[float, float, float, float]],
    output_path: str,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Generate an interactive Folium map with clickable canopy popups.

    Features:
    - Satellite tile basemap (Esri World Imagery)
    - Single GeoJSON layer colored by species (default)
    - Clickable popups: species, confidence, health status, score, recommended action
    - LayerControl for toggling
    - Geometry simplified for performance (target < 10MB for 200 canopies)
    - Warns if output exceeds FOLIUM_SIZE_WARN_MB threshold

    Args:
        detections: List of detection dicts from Supabase.
        ortho_bounds: (left, bottom, right, top) in WGS84 degrees. Used to center map.
            If None, centroid is computed from detection geometries.
        output_path: Full path for output HTML file.
        log: Logger instance.

    Returns:
        True on success, False on failure.
    """
    if log is None:
        log = logging.getLogger(__name__)

    log.info(f"Generating Folium interactive map: {output_path}")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if not detections:
        log.warning("No detections — Folium map will have no canopy layer")

    try:
        # ── Determine map center ────────────────────────────────────────────
        if ortho_bounds:
            left, bottom, right, top = ortho_bounds
            center_lat = (bottom + top) / 2.0
            center_lon = (left + right) / 2.0
        else:
            # Compute center from canopy centroids
            lats = [det.get("centroid_lat") for det in detections if det.get("centroid_lat")]
            lons = [det.get("centroid_lon") for det in detections if det.get("centroid_lon")]
            if lats and lons:
                center_lat = sum(lats) / len(lats)
                center_lon = sum(lons) / len(lons)
            else:
                center_lat, center_lon = 36.8529, -76.2859  # Hampton Roads default
                log.warning("No ortho bounds or centroids — centering on Hampton Roads")

        # ── Build GeoJSON FeatureCollection ────────────────────────────────
        features = []
        for det in detections:
            wkt_str = det.get("geometry_wkt", "")
            if not wkt_str:
                continue
            try:
                geom = shapely_wkt.loads(wkt_str)

                # Simplify geometry for performance (initial pass)
                geom_simplified = geom.simplify(FOLIUM_SIMPLIFY_INITIAL, preserve_topology=True)

                species = det.get("species_tag") or "Unknown"
                health_score = det.get("health_score")
                health_status_val = det.get("health_status") or "unknown"
                confidence = det.get("species_confidence")
                det_conf = det.get("detection_confidence")
                recommended = _recommended_action_from_det(det)

                # Build popup HTML
                popup_html = f"""
<div style="font-family: Arial, sans-serif; font-size: 13px; min-width: 200px;">
  <b>Canopy #{det.get('detection_index', '?')}</b><br>
  <hr style="margin: 4px 0;">
  <b>Species:</b> {species}<br>
  <b>Species Confidence:</b> {f"{confidence:.1%}" if confidence else "N/A"}<br>
  <b>Health Status:</b> {HEALTH_LABELS.get(health_status_val, health_status_val)}<br>
  <b>Health Score:</b> {f"{health_score:.2f}" if health_score is not None else "N/A"}<br>
  <b>Canopy Area:</b> {f"{det.get('canopy_area_sqm', 0):.1f} m²" if det.get('canopy_area_sqm') else "N/A"}<br>
  <b>Recommended:</b> {recommended.title() if recommended else "Monitor"}
</div>""".strip()

                feature = {
                    "type": "Feature",
                    "geometry": shapely_mapping(geom_simplified),
                    "properties": {
                        "detection_index": det.get("detection_index"),
                        "species_tag": species,
                        "species_confidence": round(confidence, 3) if confidence else None,
                        "health_status": health_status_val,
                        "health_score": round(health_score, 3) if health_score is not None else None,
                        "recommended_action": recommended,
                        "popup_html": popup_html,
                        "species_color": SPECIES_COLORS.get(species, SPECIES_DEFAULT_COLOR),
                    },
                }
                features.append(feature)
            except Exception as exc:
                log.debug(f"Skipping detection {det.get('detection_index', '?')} in Folium: {exc}")
                continue

        geojson_data = {"type": "FeatureCollection", "features": features}

        # ── Build Folium map ───────────────────────────────────────────────
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=17,
            tiles=None,  # We add tiles manually
        )

        # Satellite tile layer (Esri World Imagery)
        folium.TileLayer(
            tiles=(
                "https://server.arcgisonline.com/ArcGIS/rest/services/"
                "World_Imagery/MapServer/tile/{z}/{y}/{x}"
            ),
            attr="Esri World Imagery",
            name="Satellite",
            overlay=False,
            control=True,
        ).add_to(m)

        # OpenStreetMap as reference layer
        folium.TileLayer(
            tiles="OpenStreetMap",
            name="Street Map",
            overlay=False,
            control=True,
        ).add_to(m)

        # ── GeoJSON layer with species color styling ────────────────────────
        def style_function(feature):
            return {
                "fillColor": feature["properties"].get("species_color", SPECIES_DEFAULT_COLOR),
                "color": feature["properties"].get("species_color", SPECIES_DEFAULT_COLOR),
                "weight": 1.5,
                "fillOpacity": 0.5,
                "opacity": 0.8,
            }

        GeoJson(
            geojson_data,
            name="Canopy Detections",
            style_function=style_function,
            smooth_factor=1,
            tooltip=folium.GeoJsonTooltip(
                fields=["species_tag", "health_status"],
                aliases=["Species:", "Health:"],
                sticky=True,
            ),
            popup=folium.GeoJsonPopup(
                fields=["popup_html"],
                aliases=[""],
                max_width=280,
                parse_html=True,
            ),
        ).add_to(m)

        # Layer control
        folium.LayerControl(collapsed=False).add_to(m)

        # ── Save and check file size ───────────────────────────────────────
        m.save(output_path)

        file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
        log.info(f"Folium map saved: {output_path} ({file_size_mb:.1f} MB)")

        if file_size_mb > FOLIUM_SIZE_WARN_MB:
            log.warning(
                f"Folium map is {file_size_mb:.1f} MB (threshold: {FOLIUM_SIZE_WARN_MB} MB). "
                "Applying aggressive geometry simplification..."
            )
            # Re-run with aggressive simplification
            for feature in geojson_data["features"]:
                wkt_str = None
                # Find the original detection for this feature
                det_idx = feature["properties"].get("detection_index")
                for det in detections:
                    if det.get("detection_index") == det_idx:
                        wkt_str = det.get("geometry_wkt", "")
                        break
                if wkt_str:
                    try:
                        geom = shapely_wkt.loads(wkt_str)
                        geom_simplified = geom.simplify(FOLIUM_SIMPLIFY_AGGRESSIVE, preserve_topology=True)
                        feature["geometry"] = shapely_mapping(geom_simplified)
                    except Exception:
                        continue

            # Rebuild and re-save
            m2 = folium.Map(
                location=[center_lat, center_lon],
                zoom_start=17,
                tiles=None,
            )
            folium.TileLayer(
                tiles=(
                    "https://server.arcgisonline.com/ArcGIS/rest/services/"
                    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
                ),
                attr="Esri World Imagery",
                name="Satellite",
                overlay=False,
                control=True,
            ).add_to(m2)
            folium.TileLayer(tiles="OpenStreetMap", name="Street Map", overlay=False, control=True).add_to(m2)
            GeoJson(
                geojson_data,
                name="Canopy Detections",
                style_function=style_function,
                smooth_factor=1,
                tooltip=folium.GeoJsonTooltip(
                    fields=["species_tag", "health_status"],
                    aliases=["Species:", "Health:"],
                    sticky=True,
                ),
                popup=folium.GeoJsonPopup(
                    fields=["popup_html"],
                    aliases=[""],
                    max_width=280,
                    parse_html=True,
                ),
            ).add_to(m2)
            folium.LayerControl(collapsed=False).add_to(m2)
            m2.save(output_path)

            new_size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log.info(f"After aggressive simplification: {new_size_mb:.1f} MB")
            if new_size_mb > FOLIUM_SIZE_WARN_MB:
                log.warning(
                    f"Folium map still {new_size_mb:.1f} MB after simplification. "
                    "Consider reducing max_canopies in E2."
                )

        return True

    except Exception as exc:
        log.error(f"Folium map generation failed: {exc}")
        return False


# ─── REPORT ORCHESTRATION ─────────────────────────────────────────────────────

def generate_all_outputs(
    mission_id: str,
    ortho_path: str,
    output_dir: str,
    tier: str,
    log: logging.Logger,
) -> Dict[str, Any]:
    """Orchestrate all E4 output generation: maps, GeoJSON, Folium, summary.

    Args:
        mission_id: Supabase drone_jobs.id UUID.
        ortho_path: Path to source GeoTIFF orthomosaic.
        output_dir: Directory for all output files.
        tier: standard | extended | comprehensive (controls Folium generation).
        log: Logger instance.

    Returns:
        Dict with output paths and summary metrics.
    """
    os.makedirs(output_dir, exist_ok=True)

    # ── Fetch data ─────────────────────────────────────────────────────────
    log.info(f"Fetching detections for mission {mission_id}...")
    detections = fetch_detections(mission_id, log)
    log.info(f"Fetched {len(detections)} detections")

    mission_info = fetch_mission_info(mission_id, log)
    job_name = mission_info.get("job_name", "")
    created_at = mission_info.get("created_at", "")
    try:
        date_str = datetime.fromisoformat(created_at.replace("Z", "+00:00")).strftime("%Y-%m-%d") if created_at else datetime.now().strftime("%Y-%m-%d")
    except Exception:
        date_str = datetime.now().strftime("%Y-%m-%d")

    mission_label = f"{job_name} — {date_str}" if job_name else date_str

    # ── Sanitize mission name for filenames ─────────────────────────────────
    safe_name = (
        (job_name or mission_id[:8])
        .replace(" ", "_")
        .replace("/", "-")
        .replace("\\", "-")
    )

    # ── Get ortho bounds and CRS ─────────────────────────────────────────────
    ortho_bounds = None
    ortho_crs = None
    if os.path.isfile(ortho_path):
        try:
            with rasterio.open(ortho_path) as ds:
                b = ds.bounds
                ortho_crs = ds.crs
                if ds.crs and ds.crs.to_epsg() == 4326:
                    ortho_bounds = (b.left, b.bottom, b.right, b.top)
                else:
                    # Reproject bounds to WGS84 for Folium center
                    import pyproj
                    transformer = pyproj.Transformer.from_crs(
                        ds.crs, "EPSG:4326", always_xy=True
                    )
                    left, bottom = transformer.transform(b.left, b.bottom)
                    right, top = transformer.transform(b.right, b.top)
                    ortho_bounds = (left, bottom, right, top)
        except Exception as exc:
            log.warning(f"Could not read ortho bounds: {exc}")

    # ── Species map ─────────────────────────────────────────────────────────
    species_map_path = os.path.join(output_dir, f"Sentinel_{safe_name}_Species_Map.png")
    species_map_ok = generate_species_map(
        ortho_path=ortho_path,
        detections=detections,
        output_path=species_map_path,
        mission_label=mission_label,
        log=log,
    )

    # ── Health map ───────────────────────────────────────────────────────────
    health_map_path = os.path.join(output_dir, f"Sentinel_{safe_name}_Health_Map.png")
    health_map_ok = generate_health_map(
        ortho_path=ortho_path,
        detections=detections,
        output_path=health_map_path,
        mission_label=mission_label,
        log=log,
    )

    # ── GeoJSON export ───────────────────────────────────────────────────────
    geojson_path = os.path.join(output_dir, f"Sentinel_{safe_name}_Canopy_Detections.geojson")
    geojson_ok = export_geojson(
        detections=detections,
        output_path=geojson_path,
        ortho_crs=ortho_crs,
        log=log,
    )

    # ── Folium interactive map (extended/comprehensive tiers) ────────────────
    folium_path = None
    folium_ok = False
    if tier in ("extended", "comprehensive"):
        folium_path = os.path.join(output_dir, f"Sentinel_{safe_name}_Interactive_Map.html")
        folium_ok = generate_folium_map(
            detections=detections,
            ortho_bounds=ortho_bounds,
            output_path=folium_path,
            log=log,
        )
    else:
        log.info("Folium map skipped (standard tier — not included)")

    # ── Compute summary metrics ──────────────────────────────────────────────
    species_counts: Dict[str, int] = {}
    health_counts: Dict[str, int] = {}
    health_scores = []
    for det in detections:
        s = det.get("species_tag") or "Unknown"
        species_counts[s] = species_counts.get(s, 0) + 1
        h = det.get("health_status") or "unknown"
        health_counts[h] = health_counts.get(h, 0) + 1
        hs = det.get("health_score")
        if hs is not None:
            health_scores.append(hs)

    avg_health = round(sum(health_scores) / len(health_scores), 3) if health_scores else None
    needs_attention = sum(
        1 for det in detections
        if det.get("health_status") in ("stressed", "severe_decline", "dead")
    )

    # ── PDF report ──────────────────────────────────────────────────────────
    pdf_path = os.path.join(output_dir, f"Sentinel_{safe_name}_Vegetation_Report.pdf")
    pdf_ok = generate_pdf(
        detections=detections,
        output_path=pdf_path,
        mission_label=mission_label,
        species_map_path=species_map_path if species_map_ok else None,
        health_map_path=health_map_path if health_map_ok else None,
        log=log,
    )

    summary = {
        "total_canopy_count": len(detections),
        "unique_species_count": len(species_counts),
        "species_distribution": species_counts,
        "avg_health_score": avg_health,
        "health_distribution": health_counts,
        "needs_attention_count": needs_attention,
        "pdf_report_path": pdf_path if pdf_ok else None,
        "species_map_path": species_map_path if species_map_ok else None,
        "health_map_path": health_map_path if health_map_ok else None,
        "geojson_path": geojson_path if geojson_ok else None,
        "interactive_map_path": folium_path if folium_ok else None,
    }

    # ── Write Supabase summary ─────────────────────────────────────────────
    write_vegetation_summary(mission_id, summary, log)

    return summary


# ─── PDF REPORT GENERATION ────────────────────────────────────────────────────

# Sentinel brand colors
try:
    from reportlab.lib.colors import HexColor as _HexColor
    SENTINEL_GREEN = _HexColor("#1B4332")
    SENTINEL_LIGHT = _HexColor("#2D6A4F")
    SENTINEL_RED = _HexColor("#DC2626")
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

METHODOLOGY_DISCLAIMER = (
    "This vegetation analysis was generated using AI-based classification "
    "(OpenAI Vision API) with cross-validation (PlantNet). Species identifications "
    "and health assessments are estimates and do not replace ground-level assessment "
    "by a certified arborist. Sentinel Aerial Inspections recommends on-site "
    "verification for any tree identified as stressed, in severe decline, or "
    "requiring urgent attention."
)

PDF_FOOTER_TEXT = (
    "Sentinel Aerial Inspections  |  FAA Part 107 Certified  |  "
    "Veteran-Owned Small Business  |  Faith & Harmony LLC"
)


def generate_pdf(
    detections: List[Dict[str, Any]],
    output_path: str,
    mission_label: str = "",
    species_map_path: Optional[str] = None,
    health_map_path: Optional[str] = None,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Generate a branded PDF vegetation analysis report using ReportLab Platypus.

    Sections (in order):
      1. Cover page — title, property address, date
      2. Executive summary — canopy count, species, avg health, attention count
      3. Species distribution table — sorted by count descending
      4. Health overview — health distribution table
      5. Species map — embedded PNG (if available)
      6. Health map — embedded PNG (if available)
      7. Attention list — trees needing action (stressed / severe_decline / dead)
      8. Methodology disclaimer (non-negotiable)
      9. Footer on every page: Sentinel Aerial Inspections branding

    Args:
        detections: List of detection dicts from Supabase.
        output_path: Full path for output PDF file.
        mission_label: Property address + date for cover page.
        species_map_path: Path to species overlay PNG (optional embed).
        health_map_path: Path to health overlay PNG (optional embed).
        log: Logger instance.

    Returns:
        True on success, False on failure.
    """
    if log is None:
        log = logging.getLogger(__name__)

    if not REPORTLAB_AVAILABLE:
        log.error(
            "reportlab is not installed. "
            "Install with: pip install reportlab"
        )
        return False

    log.info(f"Generating PDF report: {output_path}")
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.units import inch
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.colors import HexColor, white, black, lightgrey
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            PageBreak, Image as RLImage, HRFlowable,
        )
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
        from io import BytesIO

        # ── Color aliases ──────────────────────────────────────────────────
        SENT_GREEN = HexColor("#1B4332")
        SENT_LIGHT = HexColor("#2D6A4F")
        SENT_RED = HexColor("#DC2626")
        ROW_ALT = HexColor("#F0F4F0")

        # ── Page size and document ─────────────────────────────────────────
        PAGE_W, PAGE_H = letter  # 8.5 x 11 in

        def _footer_canvas(canvas_obj, doc):
            """Draw footer on every page."""
            canvas_obj.saveState()
            canvas_obj.setFont("Helvetica", 7)
            canvas_obj.setFillColor(HexColor("#555555"))
            canvas_obj.drawCentredString(
                PAGE_W / 2.0,
                0.45 * inch,
                PDF_FOOTER_TEXT,
            )
            canvas_obj.setFont("Helvetica", 7)
            canvas_obj.drawRightString(
                PAGE_W - 0.75 * inch,
                0.45 * inch,
                f"Page {doc.page}",
            )
            canvas_obj.restoreState()

        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.75 * inch,
            bottomMargin=0.75 * inch,
        )

        # ── Styles ─────────────────────────────────────────────────────────
        base_styles = getSampleStyleSheet()
        style_h1 = ParagraphStyle(
            "SentinelH1",
            parent=base_styles["Heading1"],
            textColor=SENT_GREEN,
            fontSize=18,
            spaceAfter=12,
        )
        style_h2 = ParagraphStyle(
            "SentinelH2",
            parent=base_styles["Heading2"],
            textColor=SENT_GREEN,
            fontSize=13,
            spaceAfter=8,
        )
        style_body = ParagraphStyle(
            "SentinelBody",
            parent=base_styles["Normal"],
            fontSize=10,
            spaceAfter=6,
        )
        style_disclaimer = ParagraphStyle(
            "Disclaimer",
            parent=base_styles["Normal"],
            fontSize=9,
            textColor=HexColor("#555555"),
            spaceAfter=6,
            borderPad=6,
        )
        style_center = ParagraphStyle(
            "Center",
            parent=base_styles["Normal"],
            alignment=TA_CENTER,
            fontSize=10,
        )

        # ── Compute summary stats ──────────────────────────────────────────
        species_counts: Dict[str, int] = {}
        species_health: Dict[str, List[float]] = {}
        species_area: Dict[str, float] = {}
        health_counts: Dict[str, int] = {}
        health_scores = []
        attention_list = []

        for det in detections:
            sp = det.get("species_tag") or "Unknown"
            species_counts[sp] = species_counts.get(sp, 0) + 1

            hs = det.get("health_score")
            if hs is not None:
                health_scores.append(hs)
                species_health.setdefault(sp, []).append(hs)

            area = det.get("canopy_area_sqm") or 0.0
            species_area[sp] = species_area.get(sp, 0.0) + area

            h_status = det.get("health_status") or "unknown"
            health_counts[h_status] = health_counts.get(h_status, 0) + 1

            if h_status in ("stressed", "severe_decline", "dead"):
                attention_list.append(det)

        total_canopy = len(detections)
        unique_species = len(species_counts)
        avg_health = round(sum(health_scores) / len(health_scores), 3) if health_scores else 0.0
        needs_attention = len(attention_list)

        # ── Build flowables ────────────────────────────────────────────────
        story = []

        # 1. Cover page
        story.append(Spacer(1, 1.2 * inch))
        story.append(Paragraph("Vegetation Analysis Report", style_h1))
        story.append(HRFlowable(width="100%", thickness=2, color=SENT_GREEN))
        story.append(Spacer(1, 0.15 * inch))
        if mission_label:
            story.append(Paragraph(mission_label, style_center))
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(
            f"Prepared by: Sentinel Aerial Inspections",
            style_center,
        ))
        story.append(Paragraph(
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            style_center,
        ))
        story.append(PageBreak())

        # 2. Executive Summary
        story.append(Paragraph("Executive Summary", style_h2))
        exec_data = [
            ["Metric", "Value"],
            ["Total Canopy Count", str(total_canopy)],
            ["Unique Species Identified", str(unique_species)],
            ["Average Health Score", f"{avg_health:.3f}"],
            ["Trees Requiring Attention", str(needs_attention)],
        ]
        exec_table = Table(exec_data, colWidths=[3.5 * inch, 2.5 * inch])
        exec_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SENT_GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(exec_table)
        story.append(Spacer(1, 0.2 * inch))

        # 3. Species distribution table
        story.append(Paragraph("Species Distribution", style_h2))
        sorted_species = sorted(species_counts.items(), key=lambda x: x[1], reverse=True)
        sp_table_data = [["Species", "Count", "% of Total", "Total Area (m²)", "Avg Health"]]
        for sp, cnt in sorted_species:
            pct = f"{cnt / total_canopy * 100:.1f}%" if total_canopy > 0 else "0%"
            area = f"{species_area.get(sp, 0.0):.1f}"
            avg_sp_health = (
                f"{sum(species_health[sp]) / len(species_health[sp]):.3f}"
                if sp in species_health and species_health[sp]
                else "N/A"
            )
            sp_table_data.append([sp, str(cnt), pct, area, avg_sp_health])

        sp_col_widths = [2.5 * inch, 0.8 * inch, 0.9 * inch, 1.3 * inch, 1.0 * inch]
        sp_table = Table(sp_table_data, colWidths=sp_col_widths)
        alt_rows = [white if i % 2 == 0 else ROW_ALT for i in range(len(sp_table_data) - 1)]
        sp_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SENT_GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(sp_table)
        story.append(Spacer(1, 0.2 * inch))

        # 4. Health overview
        story.append(Paragraph("Health Distribution", style_h2))
        health_order = ["healthy", "moderate_stress", "stressed", "severe_decline", "dead"]
        health_table_data = [["Health Status", "Count", "% of Total"]]
        for status in health_order:
            cnt = health_counts.get(status, 0)
            pct = f"{cnt / total_canopy * 100:.1f}%" if total_canopy > 0 and cnt > 0 else "0%"
            health_table_data.append([
                HEALTH_LABELS.get(status, status),
                str(cnt),
                pct,
            ])
        h_table = Table(health_table_data, colWidths=[3.0 * inch, 1.2 * inch, 1.2 * inch])
        h_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), SENT_GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(h_table)
        story.append(Spacer(1, 0.2 * inch))

        # 5. Species map embed
        if species_map_path and os.path.isfile(species_map_path):
            story.append(PageBreak())
            story.append(Paragraph("Species Distribution Map", style_h2))
            avail_w = PAGE_W - 1.5 * inch
            avail_h = PAGE_H - 2.5 * inch
            story.append(RLImage(species_map_path, width=avail_w, height=avail_h))

        # 6. Health map embed
        if health_map_path and os.path.isfile(health_map_path):
            story.append(PageBreak())
            story.append(Paragraph("Canopy Health Assessment Map", style_h2))
            avail_w = PAGE_W - 1.5 * inch
            avail_h = PAGE_H - 2.5 * inch
            story.append(RLImage(health_map_path, width=avail_w, height=avail_h))

        # 7. Attention list
        if attention_list:
            story.append(PageBreak())
            story.append(Paragraph("Trees Requiring Attention", style_h2))
            attn_data = [["#", "Species", "Health Score", "Status", "Recommended Action"]]
            for i, det in enumerate(
                sorted(attention_list, key=lambda d: d.get("health_score") or 1.0), start=1
            ):
                sp = det.get("species_tag") or "Unknown"
                hs_val = det.get("health_score")
                status = det.get("health_status") or "unknown"
                action = _recommended_action_from_det(det).title()
                attn_data.append([
                    str(i),
                    sp,
                    f"{hs_val:.3f}" if hs_val is not None else "N/A",
                    HEALTH_LABELS.get(status, status),
                    action,
                ])

            attn_col_widths = [0.4 * inch, 2.0 * inch, 1.0 * inch, 1.3 * inch, 1.5 * inch]
            attn_table = Table(attn_data, colWidths=attn_col_widths)
            attn_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), SENT_RED),
                ("TEXTCOLOR", (0, 0), (-1, 0), white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, ROW_ALT]),
                ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(attn_table)
            story.append(Spacer(1, 0.2 * inch))

        # 8. Methodology disclaimer
        story.append(Spacer(1, 0.3 * inch))
        story.append(Paragraph("Methodology & Disclaimer", style_h2))
        story.append(HRFlowable(width="100%", thickness=1, color=SENT_LIGHT))
        story.append(Spacer(1, 0.08 * inch))
        story.append(Paragraph(METHODOLOGY_DISCLAIMER, style_disclaimer))

        # ── Build document ─────────────────────────────────────────────────
        doc.build(story, onFirstPage=_footer_canvas, onLaterPages=_footer_canvas)
        log.info(f"PDF report saved: {output_path}")
        return True

    except Exception as exc:
        log.error(f"PDF generation failed: {exc}")
        return False


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections — Vegetation Report Generation (Step E4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Generates vegetation analysis outputs from canopy detection and health assessment data:
  - Species overlay PNG (300 DPI)
  - Health overlay PNG (300 DPI)
  - Delivery GeoJSON (all canopy attributes, EPSG:4326)
  - Interactive Folium HTML map (extended/comprehensive tiers only)

Exit codes:
  0 — All outputs generated successfully
  1 — Fatal error (ortho not found, all outputs failed)
  2 — Partial success (one or more outputs failed)

Examples:
  python vegetation_report.py --mission-id abc-123 --ortho-path ortho.tif --output-dir ./reports
  python vegetation_report.py --mission-id abc-123 --ortho-path ortho.tif --tier extended --output-dir ./reports
  python vegetation_report.py --mission-id abc-123 --ortho-path ortho.tif --tier comprehensive --output-dir ./reports
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
        "--tier",
        choices=["standard", "extended", "comprehensive"],
        default="standard",
        help="Report tier — determines which outputs are generated (default: standard)",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory for all output files (default: current directory)",
    )
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging()

    # ── Startup log ─────────────────────────────────────────────────────────
    log.info(f"Vegetation Report (E4) starting — mission {args.mission_id}")
    log.info(f"Ortho:      {args.ortho_path}")
    log.info(f"Tier:       {args.tier}")
    log.info(f"Output dir: {args.output_dir}")

    # ── Input validation ─────────────────────────────────────────────────────
    if not os.path.isfile(args.ortho_path):
        log.error(f"Ortho file not found: {args.ortho_path}")
        sys.exit(1)

    # ── Pipeline status reporter ──────────────────────────────────────────────
    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="veg_report_generation",
    )
    reporter.start()

    # ── Run generation ────────────────────────────────────────────────────────
    start_time = time.time()
    try:
        summary = generate_all_outputs(
            mission_id=args.mission_id,
            ortho_path=args.ortho_path,
            output_dir=args.output_dir,
            tier=args.tier,
            log=log,
        )
    except Exception as exc:
        log.exception(f"Report generation failed: {exc}")
        reporter.fail(str(exc))
        sys.exit(1)

    elapsed = time.time() - start_time

    # ── Results ───────────────────────────────────────────────────────────────
    outputs_ok = [
        summary.get("pdf_report_path"),
        summary.get("species_map_path"),
        summary.get("health_map_path"),
        summary.get("geojson_path"),
    ]
    if args.tier in ("extended", "comprehensive"):
        outputs_ok.append(summary.get("interactive_map_path"))

    failed_count = sum(1 for p in outputs_ok if p is None)

    log.info(
        f"Report generation complete in {elapsed:.1f}s — "
        f"{len(outputs_ok) - failed_count}/{len(outputs_ok)} outputs generated"
    )

    # ── JSON stdout ────────────────────────────────────────────────────────────
    print(json.dumps(summary))

    # ── Reporter + exit code ──────────────────────────────────────────────────
    if failed_count == 0:
        reporter.complete(output=f"{summary.get('total_canopy_count', 0)} canopies, all outputs generated")
        sys.exit(0)
    elif failed_count < len(outputs_ok):
        reporter.complete(
            output=f"{summary.get('total_canopy_count', 0)} canopies, {failed_count} output(s) failed"
        )
        sys.exit(2)
    else:
        reporter.fail("All outputs failed")
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.getLogger(__name__).exception(f"Fatal: {exc}")
        sys.exit(1)
