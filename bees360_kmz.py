#!/usr/bin/env python3
"""
Sentinel Aerial Inspections — Bees360 Autonomous Mission Generator

Produces a DJI WPML-compliant KMZ for the 9 autonomous Bees360 shots
(1 nadir overhead + 8 birdseye orbit at -45 deg). Closeups (20+) stay
manual on the ground; Sortie's bees360 profile enforces the 5-per-side
spec post-flight when the SD card is sorted.

Pipeline:
    address ──► parcel_lookup.geocode + find_parcel ──► polygon
    polygon ──► centroid (or override coords)
    centroid + radius ──► 9 waypoints (1 nadir + 8 birdseye)
    waypoints ──► WPML KMZ (wpmz/template.kml + wpmz/waylines.wpml)

Naming for in-field identification:
    KMZ filename:  Bees360_{address_slug}_{YYYYMMDD}.kmz
    Mission name:  "Bees360 - {short_address} - {MM/DD}"
                   (DJI Fly's library reads the <name> tag)

Drone target:    DJI Mini 4 Pro (droneEnumValue=68, sub=0)
Schema:          DJI WPML 1.0.2 (matches WaypointMap.com output)

Defaults align with Sortie's bees360.json profile:
    nadir   alt 25 ft, gimbal -90 deg
    birdseye alt 25 ft, gimbal -45 deg, 25 ft orbit radius
    speed   2.0 m/s

Usage:
    python bees360_kmz.py "1234 Main St, Chesapeake, VA 23320"
    python bees360_kmz.py --lat 36.7681 --lon -76.2875 --label "Test Site"
    python bees360_kmz.py "1234 Main St, Chesapeake, VA" --orbit-radius-ft 30 --alt-ft 30
    python bees360_kmz.py "1234 Main St, Chesapeake, VA" --front-bearing 90
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parcel_lookup  # noqa: E402

SCRIPT_NAME = "bees360_kmz"
logger = logging.getLogger(SCRIPT_NAME)

DEFAULT_ALT_FT = 25.0
DEFAULT_ORBIT_RADIUS_FT = 25.0
DEFAULT_OUTPUT_DIR = Path(r"E:\Sentinel\Missions")

# Typical building heights (ft above grade) for US residential/commercial.
# Mission altitude is computed as height + BEES360_CLEARANCE_FT so the drone
# clears the roof peak with enough margin for clean Bees360-spec shots.
PROPERTY_PRESETS = {
    "ranch": 12,             # 1-story ranch, bungalow
    "2story": 25,            # Standard 2-story residential
    "3story": 35,            # 3-story residential / townhouse
    "commercial_small": 30,  # Strip mall, 2-story commercial
    "commercial_large": 45,  # 3+ story commercial
}
BEES360_CLEARANCE_FT = 30.0  # Required alt above subject per Bees360 spec
DEFAULT_NADIR_PITCH = -90
DEFAULT_OBLIQUE_PITCH = -45
DEFAULT_GLOBAL_SPEED_MS = 2.0
ORBIT_BEARINGS = [0, 45, 90, 135, 180, 225, 270, 315]

DRONE_ENUM_MINI_4_PRO = 68
DRONE_SUB_ENUM = 0
WPML_NS = "http://www.dji.com/wpmz/1.0.2"
KML_NS = "http://www.opengis.net/kml/2.2"

FT_TO_M = 0.3048
EARTH_R_M = 6378137.0


def polygon_centroid(coords: list) -> tuple[float, float]:
    """Average of vertices. Input GeoJSON-order [lon, lat]. Returns (lat, lon)."""
    if not coords:
        raise ValueError("Empty polygon")
    pts = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
    lon = sum(p[0] for p in pts) / len(pts)
    lat = sum(p[1] for p in pts) / len(pts)
    return lat, lon


def destination_point(lat: float, lon: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """Destination given start, bearing (deg from N, CW), and distance (m). Great-circle."""
    br = math.radians(bearing_deg)
    d = distance_m / EARTH_R_M
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(br))
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def bearing_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from p1 to p2, deg from N, normalized to (-180, 180].

    DJI WPML waypointHeadingAngle uses the [-180, 180] convention, not 0-360.
    An east-pointing heading is +90, west is -90 (not 270).
    """
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    deg = math.degrees(math.atan2(y, x))
    if deg > 180:
        deg -= 360
    elif deg <= -180:
        deg += 360
    return deg


def build_waypoints(
    centroid_lat: float,
    centroid_lon: float,
    alt_m: float,
    orbit_radius_m: float,
    front_bearing: float | None,
) -> list[dict]:
    """Generate 9 Bees360 waypoints. Index 0 = nadir; 1-8 = birdseye orbit (CW)."""
    waypoints = []

    waypoints.append({
        "lon": centroid_lon,
        "lat": centroid_lat,
        "alt_m": alt_m,
        "heading_deg": front_bearing if front_bearing is not None else 0.0,
        "gimbal_pitch": DEFAULT_NADIR_PITCH,
    })

    start_offset = front_bearing if front_bearing is not None else 0.0
    for base in ORBIT_BEARINGS:
        bearing_from_centroid = (start_offset + base) % 360
        wp_lat, wp_lon = destination_point(centroid_lat, centroid_lon, bearing_from_centroid, orbit_radius_m)
        heading_to_centroid = bearing_between(wp_lat, wp_lon, centroid_lat, centroid_lon)
        waypoints.append({
            "lon": wp_lon,
            "lat": wp_lat,
            "alt_m": alt_m,
            "heading_deg": heading_to_centroid,
            "gimbal_pitch": DEFAULT_OBLIQUE_PITCH,
        })

    return waypoints


def _wpml(tag: str) -> str:
    return f"{{{WPML_NS}}}{tag}"


def _kml(tag: str) -> str:
    return f"{{{KML_NS}}}{tag}"


def _pretty(elem: ET.Element) -> str:
    """Serialize with declaration + 2-space indent."""
    rough = ET.tostring(elem, encoding="unicode")
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")


def _add_mission_config(parent: ET.Element, drone_enum: int, drone_sub: int, transitional_speed_ms: float) -> None:
    mc = ET.SubElement(parent, _wpml("missionConfig"))
    ET.SubElement(mc, _wpml("flyToWaylineMode")).text = "safely"
    ET.SubElement(mc, _wpml("finishAction")).text = "noAction"
    ET.SubElement(mc, _wpml("exitOnRCLost")).text = "executeLostAction"
    ET.SubElement(mc, _wpml("executeRCLostAction")).text = "hover"
    ET.SubElement(mc, _wpml("globalTransitionalSpeed")).text = str(transitional_speed_ms)
    di = ET.SubElement(mc, _wpml("droneInfo"))
    ET.SubElement(di, _wpml("droneEnumValue")).text = str(drone_enum)
    ET.SubElement(di, _wpml("droneSubEnumValue")).text = str(drone_sub)


def build_template_kml(
    mission_name: str,
    drone_enum: int = DRONE_ENUM_MINI_4_PRO,
    drone_sub: int = DRONE_SUB_ENUM,
    transitional_speed_ms: float = 2.5,
) -> str:
    """High-level mission config. The <name> tag drives DJI Fly library display."""
    ET.register_namespace("", KML_NS)
    ET.register_namespace("wpml", WPML_NS)

    kml = ET.Element(_kml("kml"))
    document = ET.SubElement(kml, _kml("Document"))

    name_el = ET.SubElement(document, _kml("name"))
    name_el.text = mission_name

    ET.SubElement(document, _wpml("author")).text = "fly"
    now_ms = str(int(time.time() * 1000))
    ET.SubElement(document, _wpml("createTime")).text = now_ms
    ET.SubElement(document, _wpml("updateTime")).text = now_ms

    _add_mission_config(document, drone_enum, drone_sub, transitional_speed_ms)
    return _pretty(kml)


def build_waylines_wpml(
    waypoints: list[dict],
    speed_ms: float = DEFAULT_GLOBAL_SPEED_MS,
    drone_enum: int = DRONE_ENUM_MINI_4_PRO,
    drone_sub: int = DRONE_SUB_ENUM,
    transitional_speed_ms: float = 2.5,
) -> str:
    """Per-waypoint execution details. Matches WaypointMap reference structure."""
    ET.register_namespace("", KML_NS)
    ET.register_namespace("wpml", WPML_NS)

    kml = ET.Element(_kml("kml"))
    document = ET.SubElement(kml, _kml("Document"))

    _add_mission_config(document, drone_enum, drone_sub, transitional_speed_ms)

    folder = ET.SubElement(document, _kml("Folder"))
    ET.SubElement(folder, _wpml("templateId")).text = "0"
    ET.SubElement(folder, _wpml("executeHeightMode")).text = "relativeToStartPoint"
    ET.SubElement(folder, _wpml("waylineId")).text = "0"
    ET.SubElement(folder, _wpml("distance")).text = "0"
    ET.SubElement(folder, _wpml("duration")).text = "0"
    ET.SubElement(folder, _wpml("autoFlightSpeed")).text = str(speed_ms)

    last_index = len(waypoints) - 1
    action_id = 0

    for idx, wp in enumerate(waypoints):
        pm = ET.SubElement(folder, _kml("Placemark"))
        point = ET.SubElement(pm, _kml("Point"))
        ET.SubElement(point, _kml("coordinates")).text = f"{wp['lon']:.10f},{wp['lat']:.10f}"

        ET.SubElement(pm, _wpml("index")).text = str(idx)
        ET.SubElement(pm, _wpml("executeHeight")).text = f"{wp['alt_m']:.2f}"
        ET.SubElement(pm, _wpml("waypointSpeed")).text = str(speed_ms)

        hp = ET.SubElement(pm, _wpml("waypointHeadingParam"))
        ET.SubElement(hp, _wpml("waypointHeadingMode")).text = "smoothTransition"
        ET.SubElement(hp, _wpml("waypointHeadingAngle")).text = f"{wp['heading_deg']:.4f}"
        ET.SubElement(hp, _wpml("waypointPoiPoint")).text = "0.000000,0.000000,0.000000"
        ET.SubElement(hp, _wpml("waypointHeadingAngleEnable")).text = "1"
        ET.SubElement(hp, _wpml("waypointHeadingPathMode")).text = "followBadArc"

        # Stop at every waypoint so the drone is stationary when takePhoto fires.
        # Discontinuity curvature = fly straight, stop, sharp turn, fly straight.
        # Continuity curvature requires smooth arcs, which conflicts with stopping at every point.
        tp = ET.SubElement(pm, _wpml("waypointTurnParam"))
        ET.SubElement(tp, _wpml("waypointTurnMode")).text = "toPointAndStopWithDiscontinuityCurvature"
        ET.SubElement(tp, _wpml("waypointTurnDampingDist")).text = "0"

        ET.SubElement(pm, _wpml("useStraightLine")).text = "0"

        # Action group 1 (per-waypoint): takePhoto + gimbalRotate to absolute pitch.
        # Sending the gimbal command on every waypoint guarantees the nadir (-90)
        # and obliques (-45) hit their targets even if the previous angle differed.
        ag1 = ET.SubElement(pm, _wpml("actionGroup"))
        ET.SubElement(ag1, _wpml("actionGroupId")).text = "1"
        ET.SubElement(ag1, _wpml("actionGroupStartIndex")).text = str(idx)
        ET.SubElement(ag1, _wpml("actionGroupEndIndex")).text = str(idx)
        ET.SubElement(ag1, _wpml("actionGroupMode")).text = "parallel"
        trig = ET.SubElement(ag1, _wpml("actionTrigger"))
        ET.SubElement(trig, _wpml("actionTriggerType")).text = "reachPoint"

        action_id += 1
        a = ET.SubElement(ag1, _wpml("action"))
        ET.SubElement(a, _wpml("actionId")).text = str(action_id)
        ET.SubElement(a, _wpml("actionActuatorFunc")).text = "takePhoto"
        p = ET.SubElement(a, _wpml("actionActuatorFuncParam"))
        ET.SubElement(p, _wpml("payloadPositionIndex")).text = "0"

        action_id += 1
        a = ET.SubElement(ag1, _wpml("action"))
        ET.SubElement(a, _wpml("actionId")).text = str(action_id)
        ET.SubElement(a, _wpml("actionActuatorFunc")).text = "gimbalRotate"
        p = ET.SubElement(a, _wpml("actionActuatorFuncParam"))
        ET.SubElement(p, _wpml("gimbalHeadingYawBase")).text = "aircraft"
        ET.SubElement(p, _wpml("gimbalRotateMode")).text = "absoluteAngle"
        ET.SubElement(p, _wpml("gimbalPitchRotateEnable")).text = "1"
        ET.SubElement(p, _wpml("gimbalPitchRotateAngle")).text = str(wp["gimbal_pitch"])
        ET.SubElement(p, _wpml("gimbalRollRotateEnable")).text = "0"
        ET.SubElement(p, _wpml("gimbalRollRotateAngle")).text = "0"
        ET.SubElement(p, _wpml("gimbalYawRotateEnable")).text = "0"
        ET.SubElement(p, _wpml("gimbalYawRotateAngle")).text = "0"
        ET.SubElement(p, _wpml("gimbalRotateTimeEnable")).text = "0"
        ET.SubElement(p, _wpml("gimbalRotateTime")).text = "0"
        ET.SubElement(p, _wpml("payloadPositionIndex")).text = "0"

        # Action group 2 (transit): interpolate gimbal pitch toward next waypoint.
        if idx < last_index:
            ag2 = ET.SubElement(pm, _wpml("actionGroup"))
            ET.SubElement(ag2, _wpml("actionGroupId")).text = "2"
            ET.SubElement(ag2, _wpml("actionGroupStartIndex")).text = str(idx)
            ET.SubElement(ag2, _wpml("actionGroupEndIndex")).text = str(idx + 1)
            ET.SubElement(ag2, _wpml("actionGroupMode")).text = "parallel"
            trig = ET.SubElement(ag2, _wpml("actionTrigger"))
            ET.SubElement(trig, _wpml("actionTriggerType")).text = "reachPoint"
            action_id += 1
            a = ET.SubElement(ag2, _wpml("action"))
            ET.SubElement(a, _wpml("actionId")).text = str(action_id)
            ET.SubElement(a, _wpml("actionActuatorFunc")).text = "gimbalEvenlyRotate"
            p = ET.SubElement(a, _wpml("actionActuatorFuncParam"))
            ET.SubElement(p, _wpml("gimbalPitchRotateAngle")).text = str(waypoints[idx + 1]["gimbal_pitch"])
            ET.SubElement(p, _wpml("payloadPositionIndex")).text = "0"

    return _pretty(kml)


def write_kmz(template_kml: str, waylines_wpml: str, output_path: Path) -> Path:
    """Pack template.kml + waylines.wpml into the wpmz/ folder of a KMZ archive."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("wpmz/template.kml", template_kml)
        zf.writestr("wpmz/waylines.wpml", waylines_wpml)
    logger.info("Wrote %s (%d bytes)", output_path, output_path.stat().st_size)
    return output_path


def slugify_address(address: str) -> str:
    """Filesystem-safe condensed address slug."""
    s = address.strip().split(",")[0]
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_]", "", s)
    return s[:60]


def short_address(address: str) -> str:
    """Human-readable short address for in-app display."""
    return address.split(",")[0].strip()


def generate(
    address: str | None,
    lat: float | None,
    lon: float | None,
    label: str | None,
    output: str | None,
    alt_ft: float,
    orbit_radius_ft: float,
    front_bearing: float | None,
    speed_ms: float,
) -> Path:
    """End-to-end: resolve coords → build waypoints → write KMZ. Returns output path."""
    if lat is not None and lon is not None:
        centroid_lat, centroid_lon = lat, lon
        display_label = label or f"{lat:.5f},{lon:.5f}"
        slug = slugify_address(label) if label else f"{lat:.5f}_{lon:.5f}".replace(".", "p").replace("-", "n")
        logger.info("Using override coords (%.6f, %.6f), label=%r", lat, lon, display_label)
    else:
        if not address:
            raise ValueError("Must provide either address or --lat/--lon")
        coords = parcel_lookup.geocode(address)
        try:
            feature = parcel_lookup.find_parcel(coords[0], coords[1], address)
            polygon_coords = feature["geometry"]["coordinates"][0]
            centroid_lat, centroid_lon = polygon_centroid(polygon_coords)
            logger.info("Parcel centroid: (%.6f, %.6f)", centroid_lat, centroid_lon)
        except Exception as e:
            logger.warning("Parcel lookup failed (%s) — falling back to geocoded point", e)
            centroid_lat, centroid_lon = coords
        display_label = label or short_address(address)
        slug = slugify_address(address)

    today_display = datetime.now().strftime("%m/%d")
    mission_name = f"Bees360 - {display_label} - {today_display}"
    logger.info("Mission name: %s", mission_name)

    alt_m = alt_ft * FT_TO_M
    orbit_radius_m = orbit_radius_ft * FT_TO_M
    logger.info("Alt %.1f ft (%.2f m), orbit radius %.1f ft (%.2f m)",
                alt_ft, alt_m, orbit_radius_ft, orbit_radius_m)

    waypoints = build_waypoints(centroid_lat, centroid_lon, alt_m, orbit_radius_m, front_bearing)
    logger.info("Generated %d waypoints (1 nadir + 8 birdseye, front_bearing=%s)",
                len(waypoints), front_bearing)

    template_kml = build_template_kml(mission_name)
    waylines_wpml = build_waylines_wpml(waypoints, speed_ms=speed_ms)

    if output:
        output_path = Path(output)
    else:
        date_str = datetime.now().strftime("%Y%m%d")
        output_path = DEFAULT_OUTPUT_DIR / f"Bees360_{slug}_{date_str}.kmz"
    return write_kmz(template_kml, waylines_wpml, output_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a Bees360 autonomous mission KMZ for DJI Mini 4 Pro",
    )
    parser.add_argument("address", nargs="?", help="Property address (geocoded via VGIN/Census)")
    parser.add_argument("--lat", type=float, help="Override latitude (skip geocoding)")
    parser.add_argument("--lon", type=float, help="Override longitude (skip geocoding)")
    parser.add_argument("--label", help="Display label when using --lat/--lon (or override address-derived name)")
    parser.add_argument("--output", help="Output KMZ path (default: drone-pipeline/kml/Bees360_{slug}_{date}.kmz)")
    parser.add_argument("--property-type", choices=list(PROPERTY_PRESETS),
                        help="Property type preset — auto-sets altitude to "
                             f"building_height + {BEES360_CLEARANCE_FT:.0f} ft clearance, "
                             "and orbit radius = altitude (keeps camera framing on centroid at -45° pitch).")
    parser.add_argument("--alt-ft", type=float, default=None,
                        help=f"Flight altitude above takeoff in feet (default {DEFAULT_ALT_FT}, "
                             "or computed from --property-type). Explicit value wins.")
    parser.add_argument("--orbit-radius-ft", type=float, default=None,
                        help=f"Birdseye orbit radius from centroid in feet (default {DEFAULT_ORBIT_RADIUS_FT}, "
                             "or matches altitude when --property-type is set). Explicit value wins.")
    parser.add_argument("--front-bearing", type=float,
                        help="Property's front compass bearing (deg from N). Aligns orbit so first birdseye = front.")
    parser.add_argument("--speed-ms", type=float, default=DEFAULT_GLOBAL_SPEED_MS,
                        help=f"Flight speed between waypoints in m/s (default {DEFAULT_GLOBAL_SPEED_MS})")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    if not args.address and (args.lat is None or args.lon is None):
        parser.error("Provide either an address or both --lat and --lon")

    # Resolve altitude and orbit radius from --property-type preset when not
    # explicitly set. Explicit --alt-ft / --orbit-radius-ft always wins.
    alt_ft = args.alt_ft
    orbit_radius_ft = args.orbit_radius_ft
    if args.property_type:
        preset_alt = PROPERTY_PRESETS[args.property_type] + BEES360_CLEARANCE_FT
        if alt_ft is None:
            alt_ft = preset_alt
        if orbit_radius_ft is None:
            orbit_radius_ft = alt_ft
        logger.info("Property preset %r: building %d ft -> alt %.0f ft, radius %.0f ft",
                    args.property_type, PROPERTY_PRESETS[args.property_type],
                    alt_ft, orbit_radius_ft)
    if alt_ft is None:
        alt_ft = DEFAULT_ALT_FT
    if orbit_radius_ft is None:
        orbit_radius_ft = DEFAULT_ORBIT_RADIUS_FT

    try:
        path = generate(
            address=args.address,
            lat=args.lat,
            lon=args.lon,
            label=args.label,
            output=args.output,
            alt_ft=alt_ft,
            orbit_radius_ft=orbit_radius_ft,
            front_bearing=args.front_bearing,
            speed_ms=args.speed_ms,
        )
        print(json.dumps({"status": "ok", "output": str(path), "size_bytes": path.stat().st_size}))
        return 0
    except Exception as e:
        logger.exception("Mission generation failed")
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
