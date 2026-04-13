#!/usr/bin/env python3
"""
Sentinel Aerial Inspections — Building Footprints Lookup (Overture Maps)

Local-parquet building lookup for mission centering. Queries Overture Maps'
buildings theme (successor to Microsoft Building Footprints; monthly updates,
Microsoft + Meta + OSM data). Initial bbox download populates a local parquet;
runtime queries are sub-second.

Coverage advantage over OSM Overpass:
    ~748K buildings in Hampton Roads vs ~tens-to-hundreds from OSM Overpass,
    with roof-height data (meters) on many records. A CONTAINS-geocode match
    unambiguously identifies the target building even when the parcel polygon
    is fuzzy at edges or the target address is not mapped in OSM.

One-time setup:
    python building_footprints.py import

Re-download (monthly-ish, as Overture publishes new releases):
    python building_footprints.py import --force

Custom bbox (default covers Hampton Roads):
    python building_footprints.py import --bbox "-76.80,36.50,-75.90,37.30"
    python building_footprints.py import --release 2026-03-18.0

Programmatic use:
    from building_footprints import find_building_at_point, is_available
    if is_available():
        b = find_building_at_point(36.79513, -76.40554)
        # b -> {"id", "centroid_lat", "centroid_lon", "height_m", "num_floors",
        #       "contains_geocode", "dist_ft", "geom_wkt"}
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger("building_footprints")

DEFAULT_DIR = Path(r"E:\Sentinel\BuildingFootprints")
DEFAULT_PARQUET = DEFAULT_DIR / "hampton_roads_buildings.parquet"
DEFAULT_META = DEFAULT_DIR / "hampton_roads_meta.json"

# Hampton Roads bbox (Chesapeake, Norfolk, Virginia Beach, Suffolk, Portsmouth,
# Hampton, Newport News, Smithfield, Isle of Wight). Tune via --bbox if your
# operating area shifts.
DEFAULT_BBOX = {"xmin": -76.80, "ymin": 36.50, "xmax": -75.90, "ymax": 37.30}

OVERTURE_RELEASE = "2026-03-18.0"
OVERTURE_S3 = "s3://overturemaps-us-west-2/release/{release}/theme=buildings/type=building/*"
S3_REGION = "us-west-2"

# Default proximity tolerance when no building CONTAINS the geocoded point.
# 50 m covers most residential lot sizes (about half a typical suburban lot).
DEFAULT_TOLERANCE_M = 50.0
M_PER_DEG_LAT = 111_000.0
FT_PER_M = 3.28084


def _require_duckdb():
    try:
        import duckdb  # noqa: F401
        return duckdb
    except ImportError:
        sys.exit("Requires duckdb. Install with: pip install duckdb")


def is_available(parquet_path: Path = DEFAULT_PARQUET) -> bool:
    """True when the local parquet exists and is non-trivially sized."""
    return parquet_path.exists() and parquet_path.stat().st_size > 1_000_000


def read_metadata(meta_path: Path = DEFAULT_META) -> dict | None:
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def find_building_in_parcel(
    parcel_ring: list,
    geocode_lat: float | None = None,
    geocode_lon: float | None = None,
    parquet_path: Path = DEFAULT_PARQUET,
) -> dict | None:
    """Best-match building among those whose centroid falls inside a parcel ring.

    Preferred over find_building_at_point when a parcel polygon is available —
    parcel filtering defeats geocoder inaccuracy (VGIN/Census can be 40+ ft
    off), letting us identify the correct building even when the geocoded
    point lands on a neighbor.

    Args:
        parcel_ring: outer ring of parcel polygon as list of [lon, lat].
        geocode_lat, geocode_lon: optional; used as tiebreaker when multiple
            buildings land inside the parcel.
        parquet_path: local Overture parquet.

    Ranking (strongest first):
        1. Building polygon CONTAINS the geocoded point (unambiguous).
        2. Largest building whose subtype is 'residential' AND class is 'house'.
        3. Largest building of any class inside the parcel.

    Returns the same dict shape as find_building_at_point(), or None.
    """
    if not is_available(parquet_path) or not parcel_ring:
        return None

    duckdb = _require_duckdb()
    con = duckdb.connect()
    con.execute("LOAD spatial;")

    # Build the parcel polygon WKT. Close the ring if not already closed.
    ring = parcel_ring[:] if parcel_ring[0] == parcel_ring[-1] else parcel_ring + [parcel_ring[0]]
    coords_wkt = ", ".join(f"{p[0]} {p[1]}" for p in ring)
    parcel_wkt = f"POLYGON(({coords_wkt}))"

    # Parcel bbox for cheap prefilter.
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    south, north = min(lats), max(lats)
    west, east = min(lons), max(lons)

    geo_point_wkt = None
    if geocode_lat is not None and geocode_lon is not None:
        geo_point_wkt = f"POINT({geocode_lon} {geocode_lat})"

    sql = f"""
    WITH hits AS (
      SELECT id, subtype, class, height, num_floors,
             centroid_lat, centroid_lon, geom_wkt,
             ST_Area(ST_GeomFromText(geom_wkt)) AS area_deg,
             {"ST_Contains(ST_GeomFromText(geom_wkt), ST_GeomFromText(?)) AS contains_geocode," if geo_point_wkt else "FALSE AS contains_geocode,"}
             ST_Contains(ST_GeomFromText(?), ST_Point(centroid_lon, centroid_lat)) AS centroid_in_parcel
      FROM read_parquet(?)
      WHERE centroid_lat BETWEEN ? AND ?
        AND centroid_lon BETWEEN ? AND ?
    )
    SELECT id, subtype, class, height, num_floors, centroid_lat, centroid_lon,
           geom_wkt, area_deg, contains_geocode, centroid_in_parcel
    FROM hits
    WHERE centroid_in_parcel
    ORDER BY contains_geocode DESC,
             CASE WHEN subtype = 'residential' AND class = 'house' THEN 0 ELSE 1 END,
             area_deg DESC
    LIMIT 1
    """

    params: list = []
    if geo_point_wkt:
        params.append(geo_point_wkt)
    params += [parcel_wkt, str(parquet_path), south, north, west, east]
    row = con.execute(sql, params).fetchone()
    if not row:
        return None

    id_, subtype, class_, height_m, num_floors, clat, clon, wkt, area_deg, contains, _in_parcel = row
    return {
        "id": id_,
        "centroid_lat": clat,
        "centroid_lon": clon,
        "height_m": height_m,
        "height_ft": height_m * FT_PER_M if height_m is not None else None,
        "num_floors": num_floors,
        "subtype": subtype,
        "class": class_,
        "contains_geocode": bool(contains),
        "dist_ft": 0.0 if bool(contains) else None,
        "geom_wkt": wkt,
        "area_deg": area_deg,
        "_source": "overture_local_parcel",
    }


def find_building_at_point(
    lat: float,
    lon: float,
    parquet_path: Path = DEFAULT_PARQUET,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
) -> dict | None:
    """Best-match building for a geocoded address point.

    Ranking (strongest first):
        1. Building polygon CONTAINS the input point.
        2. Nearest building centroid within tolerance_m meters.

    Returns None when no building falls within tolerance. Returned dict keys:
        id, centroid_lat, centroid_lon, height_m, num_floors,
        contains_geocode, dist_ft, geom_wkt, subtype, class
    """
    if not is_available(parquet_path):
        return None

    duckdb = _require_duckdb()
    con = duckdb.connect()
    con.execute("LOAD spatial;")

    # Convert tolerance from meters to degrees — use a slightly wider bbox so
    # we catch large buildings whose centroid is beyond tolerance but whose
    # footprint still reaches the point.
    delta_deg = (tolerance_m * 2) / M_PER_DEG_LAT

    sql = f"""
    SELECT id, subtype, class, height, num_floors,
           centroid_lat, centroid_lon, geom_wkt,
           ST_Contains(ST_GeomFromText(geom_wkt), ST_Point(?, ?)) AS contains_geocode,
           ((centroid_lat - ?) * (centroid_lat - ?) +
            (centroid_lon - ?) * (centroid_lon - ?)) AS dist_sq
    FROM read_parquet(?)
    WHERE centroid_lat BETWEEN ? - ? AND ? + ?
      AND centroid_lon BETWEEN ? - ? AND ? + ?
    ORDER BY contains_geocode DESC, dist_sq ASC
    LIMIT 1
    """
    params = (
        lon, lat,                   # ST_Point(lon, lat)
        lat, lat, lon, lon,         # dist_sq
        str(parquet_path),
        lat, delta_deg, lat, delta_deg,
        lon, delta_deg, lon, delta_deg,
    )
    row = con.execute(sql, params).fetchone()
    if not row:
        return None

    id_, subtype, class_, height_m, num_floors, clat, clon, wkt, contains, dist_sq = row
    dist_m = (dist_sq ** 0.5) * M_PER_DEG_LAT
    dist_ft = dist_m * FT_PER_M
    # Enforce tolerance for centroid-based matches; CONTAINS always wins.
    if not contains and dist_m > tolerance_m:
        return None

    return {
        "id": id_,
        "centroid_lat": clat,
        "centroid_lon": clon,
        "height_m": height_m,
        "height_ft": height_m * FT_PER_M if height_m is not None else None,
        "num_floors": num_floors,
        "subtype": subtype,
        "class": class_,
        "contains_geocode": bool(contains),
        "dist_ft": dist_ft,
        "geom_wkt": wkt,
        "_source": "overture_local",
    }


def import_data(
    bbox: dict = DEFAULT_BBOX,
    release: str = OVERTURE_RELEASE,
    parquet_path: Path = DEFAULT_PARQUET,
    meta_path: Path = DEFAULT_META,
    force: bool = False,
) -> dict:
    """Download a bbox subset of Overture Maps buildings to a local parquet.

    Subsequent calls to find_building_at_point() will read this file. Re-run
    with --force (or when Overture publishes a new release) to refresh.
    """
    if parquet_path.exists() and not force:
        raise FileExistsError(
            f"{parquet_path} already exists. Pass force=True (or --force) to re-download."
        )

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    duckdb = _require_duckdb()

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute(f"SET s3_region='{S3_REGION}';")

    source = OVERTURE_S3.format(release=release)
    tmp_path = parquet_path.with_suffix(".tmp.parquet")

    sql = f"""
    COPY (
        SELECT id,
               names.primary AS name,
               height,
               num_floors,
               subtype,
               class,
               ST_Y(ST_Centroid(geometry)) AS centroid_lat,
               ST_X(ST_Centroid(geometry)) AS centroid_lon,
               ST_AsText(geometry) AS geom_wkt,
               bbox.xmin AS min_lon, bbox.xmax AS max_lon,
               bbox.ymin AS min_lat, bbox.ymax AS max_lat
        FROM read_parquet('{source}', hive_partitioning=1)
        WHERE bbox.xmin >= {bbox['xmin']} AND bbox.xmax <= {bbox['xmax']}
          AND bbox.ymin >= {bbox['ymin']} AND bbox.ymax <= {bbox['ymax']}
    ) TO '{tmp_path}' (FORMAT PARQUET, COMPRESSION ZSTD);
    """

    logger.info("Downloading Overture buildings for bbox %s from release %s...", bbox, release)
    t0 = time.time()
    con.execute(sql)
    elapsed = time.time() - t0

    count = con.execute(f"SELECT count(*) FROM read_parquet('{tmp_path}')").fetchone()[0]
    size_bytes = tmp_path.stat().st_size

    # Atomic move over any existing file.
    if parquet_path.exists():
        parquet_path.unlink()
    os.replace(tmp_path, parquet_path)

    meta = {
        "source": source,
        "release": release,
        "bbox": bbox,
        "building_count": count,
        "size_mb": round(size_bytes / (1024 * 1024), 1),
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "download_seconds": round(elapsed, 1),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    logger.info("Wrote %s (%s buildings, %.1f MB, %.1fs)",
                parquet_path, f"{count:,}", meta["size_mb"], elapsed)
    return meta


def _cmd_import(args):
    bbox = DEFAULT_BBOX
    if args.bbox:
        parts = [float(x) for x in args.bbox.split(",")]
        if len(parts) != 4:
            sys.exit("--bbox must be 'xmin,ymin,xmax,ymax' (4 numbers)")
        bbox = {"xmin": parts[0], "ymin": parts[1], "xmax": parts[2], "ymax": parts[3]}

    try:
        meta = import_data(
            bbox=bbox,
            release=args.release,
            parquet_path=Path(args.output),
            meta_path=Path(args.output).with_name("hampton_roads_meta.json") if not args.meta else Path(args.meta),
            force=args.force,
        )
    except FileExistsError as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        return 1

    print(json.dumps({"status": "ok", **meta}, indent=2))
    return 0


def _cmd_status(args):
    path = Path(args.path)
    out = {
        "parquet_path": str(path),
        "available": is_available(path),
        "size_mb": round(path.stat().st_size / (1024 * 1024), 1) if path.exists() else 0,
        "metadata": read_metadata(Path(args.path).with_name("hampton_roads_meta.json")),
    }
    print(json.dumps(out, indent=2))
    return 0


def _cmd_lookup(args):
    b = find_building_at_point(
        args.lat, args.lon,
        parquet_path=Path(args.path),
        tolerance_m=args.tolerance_m,
    )
    if not b:
        print(json.dumps({"status": "no_match"}))
        return 1
    b_out = {k: v for k, v in b.items() if k != "geom_wkt"}
    print(json.dumps({"status": "ok", **b_out}, indent=2, default=str))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="Download Overture buildings for a bbox into a local parquet")
    p_import.add_argument("--bbox", help="xmin,ymin,xmax,ymax (defaults to Hampton Roads)")
    p_import.add_argument("--release", default=OVERTURE_RELEASE, help=f"Overture release (default {OVERTURE_RELEASE})")
    p_import.add_argument("--output", default=str(DEFAULT_PARQUET), help=f"Output parquet path (default {DEFAULT_PARQUET})")
    p_import.add_argument("--meta", help="Metadata JSON path (default alongside parquet)")
    p_import.add_argument("--force", action="store_true", help="Overwrite existing parquet")
    p_import.set_defaults(func=_cmd_import)

    p_status = sub.add_parser("status", help="Show whether the local parquet exists and its metadata")
    p_status.add_argument("--path", default=str(DEFAULT_PARQUET))
    p_status.set_defaults(func=_cmd_status)

    p_lookup = sub.add_parser("lookup", help="Look up the best-match building for a lat/lon")
    p_lookup.add_argument("--lat", type=float, required=True)
    p_lookup.add_argument("--lon", type=float, required=True)
    p_lookup.add_argument("--path", default=str(DEFAULT_PARQUET))
    p_lookup.add_argument("--tolerance-m", type=float, default=DEFAULT_TOLERANCE_M)
    p_lookup.set_defaults(func=_cmd_lookup)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
