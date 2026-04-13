"""
Sentinel Aerial Inspections — Parcel Boundary Lookup

Takes a property address, geocodes it, queries county GIS for the parcel
boundary polygon, and exports to KML for import into WaypointMap or DJI Pilot 2.

Strategy:
    1. Geocode address → lat/lon (VGIN for VA, Census for NC/fallback)
    2. Determine county from coordinates
    3. Spatial query against county parcel layer → polygon
    4. Export polygon to KML file

Supported areas:
    - All Virginia localities (via VGIN statewide parcels)
    - All NC counties (via NC OneMap statewide parcels)
    - Fallback: US Census geocoder + VGIN/NC OneMap

Usage:
    python parcel_lookup.py "1234 Main St, Chesapeake, VA 23320"
    python parcel_lookup.py "1234 Main St, Chesapeake, VA" --output mission_boundary.kml
    python parcel_lookup.py --lat 36.7681 --lon -76.2875
    python parcel_lookup.py "1234 Main St, Chesapeake, VA" --buffer 50
"""

import os
import sys
import json
import argparse
import logging
import math
from pathlib import Path

import requests
import simplekml

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "parcel_lookup"
logger = logging.getLogger(SCRIPT_NAME)

# Geocoding endpoints
VGIN_GEOCODER = "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/Geocoding/VGIN_Composite_Locator/GeocodeServer/findAddressCandidates"
CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

# Statewide parcel endpoints (spatial query — works for any locality)
VGIN_PARCELS = "https://vginmaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/VA_Parcels/FeatureServer/0/query"
NC_PARCELS = "https://services.nconemap.gov/secure/rest/services/NC1Map_Parcels/FeatureServer/1/query"

# County-specific endpoints (better field coverage)
COUNTY_ENDPOINTS = {
    "chesapeake": {
        "url": "https://gis.cityofchesapeake.net/mapping/rest/services/Common_Layers/Parcels/MapServer/0/query",
        "address_field": "ADDRESS",
        "owner_field": "OWNER",
        "parcel_id_field": "MAP_PARCEL",
    },
    "virginia beach": {
        "url": "https://geo.vbgov.com/mapservices/rest/services/Basemaps/Property_Information/MapServer/12/query",
        "address_field": "PROP_ADDRESS",
        "owner_field": None,
        "parcel_id_field": "PAR_GPIN",
    },
    "norfolk": {
        "url": "https://gisshare.norfolk.gov/pubserver/rest/services/OpenData/Parcels/FeatureServer/1/query",
        "address_field": None,
        "owner_field": None,
        "parcel_id_field": "GPIN",
    },
    "suffolk": {
        "url": "https://suffolkgis.suffolk-va.net/hosting/rest/services/ALL_GIS_Layers/MapServer/271/query",
        "address_field": None,
        "owner_field": "OWNER",
        "parcel_id_field": "GPIN",
    },
}

REQUEST_TIMEOUT = 15

# OSM Overpass API — queries building footprints within a parcel bbox.
# Free, no API key required, ~0.5-2 sec typical response.
OSM_OVERPASS_URL = "https://overpass-api.de/api/interpreter"


# ─── POLYGON GEOMETRY (no shapely dep) ───────────────────────────────────────

def _ring_point_in_polygon(lon: float, lat: float, ring: list) -> bool:
    """Ray-casting point-in-polygon test. ring = list of [lon, lat]."""
    n = len(ring)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _ring_centroid(ring: list) -> tuple[float, float]:
    """Average of unique vertices. ring = list of [lon, lat]. Returns (lon, lat)."""
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _ring_area(ring: list) -> float:
    """Signed area via shoelace. Units: sq degrees (ok for relative comparison)."""
    n = len(ring)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


# ─── OSM BUILDING LOOKUP ─────────────────────────────────────────────────────

def find_building_in_parcel(parcel_feature: dict) -> dict | None:
    """Query OSM Overpass for buildings inside the parcel polygon.

    Returns a GeoJSON-like Feature for the largest building whose centroid
    falls inside the parcel outer ring, or None if OSM has no buildings there.

    The returned feature's `properties` includes:
        centroid_lat, centroid_lon, osm_tags, building_count_in_parcel
    """
    outer_ring = parcel_feature["geometry"]["coordinates"][0]
    lons = [p[0] for p in outer_ring]
    lats = [p[1] for p in outer_ring]
    south, north = min(lats), max(lats)
    west, east = min(lons), max(lons)

    query = (
        f"[out:json][timeout:15];"
        f'(way["building"]({south},{west},{north},{east}););'
        f"out geom;"
    )

    try:
        resp = requests.post(OSM_OVERPASS_URL, data={"data": query}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("OSM Overpass query failed: %s", e)
        return None

    candidates = []
    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue
        geom = element.get("geometry", [])
        if len(geom) < 3:
            continue
        bldg_ring = [[node["lon"], node["lat"]] for node in geom]
        cx, cy = _ring_centroid(bldg_ring)
        if not _ring_point_in_polygon(cx, cy, outer_ring):
            continue
        area = _ring_area(bldg_ring)
        candidates.append((area, cx, cy, bldg_ring, element.get("tags", {})))

    if not candidates:
        logger.info("OSM: no buildings found in parcel bbox (OSM residential coverage is spotty)")
        return None

    candidates.sort(reverse=True, key=lambda x: x[0])
    area, cx, cy, bldg_ring, tags = candidates[0]
    logger.info("OSM: found %d building(s) inside parcel, using largest (rel area %.2e)",
                len(candidates), area)
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [bldg_ring]},
        "properties": {
            "centroid_lat": cy,
            "centroid_lon": cx,
            "osm_tags": tags,
            "building_count_in_parcel": len(candidates),
            "_source": "osm_overpass",
        },
    }


# ─── GEOCODING ───────────────────────────────────────────────────────────────

def geocode_vgin(address: str) -> tuple[float, float] | None:
    """Geocode address using VGIN Virginia Composite Locator."""
    try:
        resp = requests.get(VGIN_GEOCODER, params={
            "SingleLine": address,
            "outFields": "*",
            "maxLocations": 1,
            "f": "json",
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if candidates:
            loc = candidates[0]["location"]
            score = candidates[0].get("score", 0)
            logger.info("VGIN geocode: %s → (%.6f, %.6f) score=%s", address, loc["y"], loc["x"], score)
            return loc["y"], loc["x"]  # lat, lon
    except Exception as e:
        logger.warning("VGIN geocode failed: %s", e)
    return None


def geocode_census(address: str) -> tuple[float, float] | None:
    """Geocode address using US Census geocoder (nationwide fallback)."""
    try:
        resp = requests.get(CENSUS_GEOCODER, params={
            "address": address,
            "benchmark": "Public_AR_Current",
            "format": "json",
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        matches = data.get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0]["coordinates"]
            logger.info("Census geocode: %s → (%.6f, %.6f)", address, coords["y"], coords["x"])
            return coords["y"], coords["x"]  # lat, lon
    except Exception as e:
        logger.warning("Census geocode failed: %s", e)
    return None


def geocode(address: str) -> tuple[float, float]:
    """Geocode address using best available service."""
    # Try VGIN first (better for VA addresses)
    result = geocode_vgin(address)
    if result:
        return result

    # Fallback to Census (nationwide)
    result = geocode_census(address)
    if result:
        return result

    raise ValueError(f"Could not geocode address: {address}")


# ─── STATE DETECTION ─────────────────────────────────────────────────────────

def detect_state(lat: float, lon: float, address: str = "") -> str:
    """Determine if coordinates are in VA or NC (rough bounding box)."""
    addr_lower = address.lower()
    if ", va" in addr_lower or "virginia" in addr_lower:
        return "VA"
    if ", nc" in addr_lower or "north carolina" in addr_lower:
        return "NC"
    # Rough lat boundary: VA/NC border is ~36.5°N
    if lat > 36.5:
        return "VA"
    return "NC"


def detect_locality(address: str) -> str | None:
    """Extract locality name from address for county-specific endpoint lookup."""
    addr_lower = address.lower()
    for locality in COUNTY_ENDPOINTS:
        if locality in addr_lower:
            return locality
    return None


# ─── PARCEL QUERY ────────────────────────────────────────────────────────────

def query_parcel_spatial(endpoint_url: str, lat: float, lon: float, out_sr: int = 4326) -> dict | None:
    """Spatial query: find parcel polygon containing the given point.

    Uses an envelope around the point (±30m) to handle cases where the
    geocoded point lands on a road or driveway outside the parcel polygon.
    """
    # ~30 meters buffer in degrees
    buf = 0.0003

    # Try point query first
    for geom_param, geom_type in [
        (f"{lon},{lat}", "esriGeometryPoint"),
        (f"{lon-buf},{lat-buf},{lon+buf},{lat+buf}", "esriGeometryEnvelope"),
    ]:
        try:
            resp = requests.get(endpoint_url, params={
                "geometry": geom_param,
                "geometryType": geom_type,
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": str(out_sr),
                "f": "json",
            }, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            features = data.get("features", [])
            if features:
                # Convert ESRI JSON to GeoJSON-like structure
                feature = features[0]
                rings = feature.get("geometry", {}).get("rings", [])
                if rings:
                    geojson_feature = {
                        "type": "Feature",
                        "properties": feature.get("attributes", {}),
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": rings,
                        },
                    }
                    logger.info("Found parcel with %d vertices via %s",
                                sum(len(r) for r in rings), geom_type)
                    return geojson_feature
        except Exception as e:
            logger.warning("Parcel query failed on %s (%s): %s", endpoint_url, geom_type, e)

    return None


def query_parcel_by_address(endpoint_url: str, address: str, address_field: str, out_sr: int = 4326) -> dict | None:
    """Query parcel by address field (WHERE clause)."""
    # Extract street part from full address (remove city, state, zip)
    parts = address.split(",")
    street = parts[0].strip().upper()

    try:
        resp = requests.get(endpoint_url, params={
            "where": f"{address_field} LIKE '%{street}%'",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": str(out_sr),
            "f": "json",
        }, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        features = data.get("features", [])
        if features:
            feature = features[0]
            rings = feature.get("geometry", {}).get("rings", [])
            if rings:
                geojson_feature = {
                    "type": "Feature",
                    "properties": feature.get("attributes", {}),
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": rings,
                    },
                }
                logger.info("Found parcel by address query: %s", street)
                return geojson_feature
    except Exception as e:
        logger.warning("Address query failed on %s: %s", endpoint_url, e)

    return None


def find_parcel(lat: float, lon: float, address: str = "") -> dict:
    """Find parcel boundary for given coordinates.

    Tries county-specific endpoint first, then statewide fallback.
    Returns GeoJSON Feature with geometry and properties.
    """
    state = detect_state(lat, lon, address)
    locality = detect_locality(address)

    # Try county-specific endpoint first
    if locality and locality in COUNTY_ENDPOINTS:
        endpoint = COUNTY_ENDPOINTS[locality]
        logger.info("Trying %s local endpoint", locality)

        # Try address query first if field is available
        if address and endpoint.get("address_field"):
            feature = query_parcel_by_address(endpoint["url"], address, endpoint["address_field"])
            if feature:
                feature["_source"] = f"{locality} local GIS (address)"
                return feature

        # Fall back to spatial query
        feature = query_parcel_spatial(endpoint["url"], lat, lon)
        if feature:
            feature["_source"] = f"{locality} local GIS (spatial)"
            return feature

    # Fall back to statewide
    if state == "VA":
        logger.info("Trying VGIN statewide parcels")
        feature = query_parcel_spatial(VGIN_PARCELS, lat, lon)
        if feature:
            feature["_source"] = "VGIN statewide"
            return feature
    elif state == "NC":
        logger.info("Trying NC OneMap statewide parcels")
        feature = query_parcel_spatial(NC_PARCELS, lat, lon)
        if feature:
            feature["_source"] = "NC OneMap statewide"
            return feature

    # Try the other state as last resort
    other = NC_PARCELS if state == "VA" else VGIN_PARCELS
    feature = query_parcel_spatial(other, lat, lon)
    if feature:
        feature["_source"] = "fallback statewide"
        return feature

    raise ValueError(f"No parcel found at ({lat}, {lon})")


# ─── BUFFER ──────────────────────────────────────────────────────────────────

def buffer_polygon(coords: list, buffer_ft: float) -> list:
    """Simple buffer by expanding polygon outward from centroid.

    Not a true GIS buffer — approximates by scaling each vertex outward
    from the centroid. Good enough for adding a safety margin to survey area.
    """
    if buffer_ft <= 0:
        return coords

    # Convert feet to approximate degrees (1 degree ≈ 364,000 ft at 36°N)
    buffer_deg = buffer_ft / 364000

    # Calculate centroid
    n = len(coords)
    if n == 0:
        return coords
    cx = sum(c[0] for c in coords) / n
    cy = sum(c[1] for c in coords) / n

    buffered = []
    for x, y in coords:
        dx = x - cx
        dy = y - cy
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0:
            scale = (dist + buffer_deg) / dist
            buffered.append([cx + dx * scale, cy + dy * scale])
        else:
            buffered.append([x, y])

    return buffered


# ─── KML EXPORT ──────────────────────────────────────────────────────────────

def export_kml(feature: dict, output_path: str, address: str = "", buffer_ft: float = 0) -> str:
    """Export GeoJSON Feature to KML file.

    Compatible with WaypointMap and DJI Pilot 2 KML import.
    """
    kml = simplekml.Kml()

    geometry = feature["geometry"]
    properties = feature.get("properties", {})
    source = feature.get("_source", "unknown")

    # Build name from address or parcel ID
    parcel_id = (
        properties.get("MAP_PARCEL")
        or properties.get("PAR_GPIN")
        or properties.get("GPIN")
        or properties.get("PARCELID")
        or properties.get("parno")
        or "Parcel"
    )
    name = address if address else f"Parcel {parcel_id}"

    # Build description
    desc_parts = [f"Parcel ID: {parcel_id}"]
    owner = properties.get("OWNER") or properties.get("owner")
    if owner:
        desc_parts.append(f"Owner: {owner}")
    addr = properties.get("ADDRESS") or properties.get("PROP_ADDRESS") or properties.get("siteadd")
    if addr:
        desc_parts.append(f"Address: {addr}")
    desc_parts.append(f"Source: {source}")
    description = "\n".join(desc_parts)

    # Handle GeoJSON geometry types
    geo_type = geometry.get("type", "")
    rings = []

    if geo_type == "Polygon":
        rings = geometry["coordinates"]
    elif geo_type == "MultiPolygon":
        # Use the largest polygon (by vertex count)
        largest = max(geometry["coordinates"], key=lambda p: len(p[0]))
        rings = largest
    else:
        raise ValueError(f"Unexpected geometry type: {geo_type}")

    if not rings:
        raise ValueError("No polygon rings in geometry")

    # Apply buffer if requested
    outer_ring = rings[0]
    if buffer_ft > 0:
        outer_ring = buffer_polygon(outer_ring, buffer_ft)
        name += f" (+{buffer_ft}ft buffer)"

    # Convert to KML coordinates (lon, lat, alt)
    kml_coords = [(coord[0], coord[1], 0) for coord in outer_ring]

    pol = kml.newpolygon(name=name)
    pol.outerboundaryis = kml_coords
    pol.description = description

    # Style — yellow boundary, semi-transparent fill
    pol.style.linestyle.color = simplekml.Color.yellow
    pol.style.linestyle.width = 3
    pol.style.polystyle.color = simplekml.Color.changealphaint(80, simplekml.Color.yellow)

    # Add centroid pin
    cx = sum(c[0] for c in outer_ring) / len(outer_ring)
    cy = sum(c[1] for c in outer_ring) / len(outer_ring)
    pin = kml.newpoint(name=f"Center: {name}")
    pin.coords = [(cx, cy)]
    pin.description = description

    kml.save(output_path)
    logger.info("KML saved: %s", output_path)
    return output_path


# ─── AREA CALCULATION ────────────────────────────────────────────────────────

def polygon_area_acres(coords: list) -> float:
    """Calculate polygon area in acres using the shoelace formula.

    Assumes coords are in WGS84 (lon, lat). Converts to approximate
    square feet using local scale factors at the polygon's latitude.
    """
    if len(coords) < 3:
        return 0

    avg_lat = sum(c[1] for c in coords) / len(coords)
    lat_ft = 364000  # ft per degree latitude (roughly constant)
    lon_ft = 364000 * math.cos(math.radians(avg_lat))  # ft per degree longitude

    # Shoelace formula in ft²
    n = len(coords)
    area = 0
    for i in range(n):
        j = (i + 1) % n
        x1 = coords[i][0] * lon_ft
        y1 = coords[i][1] * lat_ft
        x2 = coords[j][0] * lon_ft
        y2 = coords[j][1] * lat_ft
        area += x1 * y2 - x2 * y1

    sq_ft = abs(area) / 2
    return sq_ft / 43560  # convert to acres


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run(
    address: str = "",
    lat: float | None = None,
    lon: float | None = None,
    output: str | None = None,
    buffer_ft: float = 0,
) -> dict:
    """Run parcel lookup and KML export.

    Returns dict with parcel info, area, and output path.
    """
    # Geocode if needed
    if lat is None or lon is None:
        if not address:
            raise ValueError("Provide either an address or lat/lon coordinates")
        lat, lon = geocode(address)

    logger.info("Looking up parcel at (%.6f, %.6f)", lat, lon)

    # Find parcel
    feature = find_parcel(lat, lon, address)

    # Calculate area
    geometry = feature["geometry"]
    geo_type = geometry.get("type", "")
    if geo_type == "Polygon":
        outer = geometry["coordinates"][0]
    elif geo_type == "MultiPolygon":
        largest = max(geometry["coordinates"], key=lambda p: len(p[0]))
        outer = largest[0]
    else:
        outer = []

    acres = polygon_area_acres(outer)
    properties = feature.get("properties", {})

    # Default output path
    if not output:
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in (address or f"{lat}_{lon}"))
        safe_name = safe_name.strip().replace(" ", "_")[:60]
        output = str(Path(r"E:\Sentinel\Missions") / f"{safe_name}.kml")

    # Ensure output directory exists
    Path(output).parent.mkdir(parents=True, exist_ok=True)

    # Export KML
    export_kml(feature, output, address=address, buffer_ft=buffer_ft)

    parcel_id = (
        properties.get("MAP_PARCEL")
        or properties.get("PAR_GPIN")
        or properties.get("GPIN")
        or properties.get("PARCELID")
        or properties.get("parno")
        or "unknown"
    )

    result = {
        "status": "ok",
        "address": address,
        "lat": lat,
        "lon": lon,
        "parcel_id": parcel_id,
        "owner": properties.get("OWNER") or properties.get("owner") or "",
        "acres": round(acres, 2),
        "source": feature.get("_source", "unknown"),
        "kml_path": output,
        "buffer_ft": buffer_ft,
        "vertex_count": len(outer),
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Sentinel — Parcel Boundary Lookup → KML Export",
    )
    parser.add_argument("address", nargs="?", default="", help="Property address to look up")
    parser.add_argument("--lat", type=float, help="Latitude (instead of address)")
    parser.add_argument("--lon", type=float, help="Longitude (instead of address)")
    parser.add_argument("--output", "-o", help="Output KML file path")
    parser.add_argument("--buffer", type=float, default=0, help="Buffer distance in feet (expand boundary)")
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    try:
        result = run(
            address=args.address,
            lat=args.lat,
            lon=args.lon,
            output=args.output,
            buffer_ft=args.buffer,
        )

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"\nParcel found:")
            print(f"  Address:   {result['address']}")
            print(f"  Parcel ID: {result['parcel_id']}")
            if result['owner']:
                print(f"  Owner:     {result['owner']}")
            print(f"  Area:      {result['acres']} acres")
            print(f"  Vertices:  {result['vertex_count']}")
            print(f"  Source:     {result['source']}")
            print(f"  KML:       {result['kml_path']}")
            if result['buffer_ft']:
                print(f"  Buffer:    {result['buffer_ft']} ft")
            print(f"\nLoad this KML into WaypointMap or DJI Pilot 2 to define your survey area.")

        sys.exit(0)

    except Exception as e:
        logger.error("Failed: %s", e)
        if args.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
