#!/usr/bin/env python3
"""
Sentinel Aerial Inspections — Mission KMZ Preview Generator

Takes a DJI WPML KMZ and produces an interactive HTML map showing the flight
path, waypoints, headings, gimbal pitches, and mission stats. Use as a
pre-flight sanity check or as a sales artifact to send to clients.

Works on any DJI Fly WPML KMZ — files from bees360_kmz.py, WaypointMap.com,
Dronelink, etc.

Usage:
    python mission_preview.py path/to/mission.kmz
    python mission_preview.py mission.kmz --output preview.html
    python mission_preview.py mission.kmz --open
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import webbrowser
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import folium
from folium.plugins import MeasureControl

WPML_NS = "http://www.dji.com/wpmz/1.0.2"
KML_NS = "http://www.opengis.net/kml/2.2"
NS = {"wpml": WPML_NS, "kml": KML_NS}

# Mini 4 Pro: ~45 min cruise on Intelligent Flight Battery Plus, ~34 min on standard.
# Conservative drain estimate covers either pack.
BATTERY_DRAIN_PER_MIN = 2.5
TAKEOFF_LANDING_PCT = 5.0
STOP_TIME_PER_WAYPOINT_S = 3.0
EARTH_R_M = 6378137.0
M_TO_FT = 1.0 / 0.3048

# Sentinel theme
COLOR_PURPLE = "#5B2C6F"
COLOR_GOLD = "#F4D03F"
COLOR_GREEN = "#27AE60"
COLOR_DARK = "#1A0A2E"
COLOR_LIGHT_PURPLE = "#AF7AC5"


def parse_kmz(kmz_path: Path) -> dict:
    """Extract mission data from a DJI WPML KMZ archive."""
    with zipfile.ZipFile(kmz_path) as zf:
        with zf.open("wpmz/waylines.wpml") as f:
            wpml_tree = ET.parse(f)
        try:
            with zf.open("wpmz/template.kml") as f:
                template_tree = ET.parse(f)
        except KeyError:
            template_tree = None

    mission_name = kmz_path.stem
    drone_enum: int | None = None
    if template_tree is not None:
        name_el = template_tree.find(".//kml:name", NS)
        if name_el is not None and name_el.text:
            mission_name = name_el.text.strip()
        de = template_tree.find(".//wpml:droneEnumValue", NS)
        if de is not None and de.text:
            try:
                drone_enum = int(de.text)
            except ValueError:
                pass

    folder = wpml_tree.getroot().find(".//kml:Folder", NS)
    speed_el = folder.find("wpml:autoFlightSpeed", NS) if folder is not None else None
    speed_ms = float(speed_el.text) if speed_el is not None and speed_el.text else 2.0

    waypoints: list[dict] = []
    if folder is not None:
        for pm in folder.findall("kml:Placemark", NS):
            coords_el = pm.find(".//kml:coordinates", NS)
            if coords_el is None or not coords_el.text:
                continue
            parts = coords_el.text.strip().split(",")
            lon, lat = float(parts[0]), float(parts[1])

            idx = int(pm.findtext("wpml:index", default="0", namespaces=NS))
            alt_m = float(pm.findtext("wpml:executeHeight", default="0", namespaces=NS))
            wp_speed = float(pm.findtext("wpml:waypointSpeed", default=str(speed_ms), namespaces=NS))
            heading = float(pm.findtext(".//wpml:waypointHeadingAngle", default="0", namespaces=NS))

            pitch: float | None = None
            for pa in pm.findall(".//wpml:gimbalPitchRotateAngle", NS):
                if pa.text:
                    pitch = float(pa.text)
                    break

            takes_photo = any(
                (a.text or "").strip() == "takePhoto"
                for a in pm.findall(".//wpml:actionActuatorFunc", NS)
            )

            waypoints.append({
                "index": idx,
                "lat": lat,
                "lon": lon,
                "alt_m": alt_m,
                "speed_ms": wp_speed,
                "heading_deg": heading,
                "gimbal_pitch": pitch,
                "takes_photo": takes_photo,
            })

    waypoints.sort(key=lambda w: w["index"])
    return {
        "mission_name": mission_name,
        "drone_enum": drone_enum,
        "speed_ms": speed_ms,
        "waypoints": waypoints,
    }


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


def compute_stats(waypoints: list[dict], speed_ms: float) -> dict:
    """Distance, time, battery estimate."""
    total_dist = 0.0
    for i in range(len(waypoints) - 1):
        a, b = waypoints[i], waypoints[i + 1]
        total_dist += haversine_m(a["lat"], a["lon"], b["lat"], b["lon"])

    cruise_time_s = total_dist / speed_ms if speed_ms > 0 else 0
    stop_time_s = len(waypoints) * STOP_TIME_PER_WAYPOINT_S
    total_time_s = cruise_time_s + stop_time_s
    battery_pct = (total_time_s / 60.0) * BATTERY_DRAIN_PER_MIN + TAKEOFF_LANDING_PCT

    return {
        "total_distance_m": total_dist,
        "total_distance_ft": total_dist * M_TO_FT,
        "cruise_time_s": cruise_time_s,
        "stop_time_s": stop_time_s,
        "total_time_s": total_time_s,
        "battery_pct_estimate": battery_pct,
        "photo_count": sum(1 for w in waypoints if w["takes_photo"]),
    }


def _heading_endpoint(lat: float, lon: float, heading_deg: float, distance_m: float) -> tuple[float, float]:
    """Flat-earth approx — fine for the few-meter visual-aid arrows."""
    br = math.radians(heading_deg)
    dlat = (distance_m * math.cos(br)) / 111_000
    dlon = (distance_m * math.sin(br)) / (111_000 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def build_html(mission: dict, output_path: Path) -> Path:
    """Render a Folium map of the mission and write it to disk."""
    waypoints = mission["waypoints"]
    if not waypoints:
        raise ValueError("No waypoints in mission")

    stats = compute_stats(waypoints, mission["speed_ms"])

    avg_lat = sum(w["lat"] for w in waypoints) / len(waypoints)
    avg_lon = sum(w["lon"] for w in waypoints) / len(waypoints)

    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=20, max_zoom=22, tiles=None)

    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery",
        name="Satellite",
        max_zoom=22,
    ).add_to(m)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Street",
        max_zoom=19,
    ).add_to(m)

    # Flight path (dashed gold line)
    line_coords = [(w["lat"], w["lon"]) for w in waypoints]
    folium.PolyLine(
        line_coords, color=COLOR_GOLD, weight=2, opacity=0.85,
        dash_array="6, 6", tooltip="Flight path",
    ).add_to(m)

    # Waypoint markers + heading arrows
    for w in waypoints:
        is_nadir = w["index"] == 0
        color = COLOR_PURPLE if is_nadir else COLOR_GREEN
        icon_html = (
            f'<div style="background:{color};color:white;border-radius:50%;'
            f'width:26px;height:26px;text-align:center;line-height:26px;'
            f'font-weight:bold;font-size:12px;border:2px solid white;'
            f'box-shadow:0 0 4px rgba(0,0,0,0.6);">{w["index"]}</div>'
        )
        pitch_str = f'{w["gimbal_pitch"]:.0f}°' if w["gimbal_pitch"] is not None else "—"
        popup_html = (
            f'<b>Waypoint {w["index"]}</b><br>'
            f'{"Nadir overhead" if is_nadir else "Birdseye orbit"}<br>'
            f'Alt: {w["alt_m"]:.1f} m ({w["alt_m"] * M_TO_FT:.1f} ft)<br>'
            f'Heading: {w["heading_deg"]:.1f}°<br>'
            f'Gimbal pitch: {pitch_str}<br>'
            f'Photo: {"Yes" if w["takes_photo"] else "No"}'
        )
        folium.Marker(
            [w["lat"], w["lon"]],
            popup=folium.Popup(popup_html, max_width=260),
            tooltip=f'WP {w["index"]} — {w["alt_m"]:.1f}m',
            icon=folium.DivIcon(html=icon_html, icon_size=(26, 26), icon_anchor=(13, 13)),
        ).add_to(m)

        end = _heading_endpoint(w["lat"], w["lon"], w["heading_deg"], 4.0)
        folium.PolyLine(
            [(w["lat"], w["lon"]), end],
            color=COLOR_GOLD, weight=3, opacity=0.95,
        ).add_to(m)

    # Stats overlay
    drone_label = "Mini 4 Pro" if mission.get("drone_enum") == 68 else (
        f'drone enum {mission["drone_enum"]}' if mission.get("drone_enum") else "unknown drone"
    )
    stats_html = f"""
    <div style="position:fixed; top:14px; left:14px; z-index:1000;
                background:rgba(26,10,46,0.94); color:white; padding:14px 18px;
                border-radius:8px; font-family:'Segoe UI',sans-serif; font-size:12px;
                max-width:340px; box-shadow:0 4px 14px rgba(0,0,0,0.5);">
      <div style="font-size:14px; font-weight:bold; color:{COLOR_GOLD}; margin-bottom:4px;">
        {mission["mission_name"]}
      </div>
      <div style="color:{COLOR_LIGHT_PURPLE}; margin-bottom:10px; font-size:11px;">
        Sentinel Aerial Inspections &nbsp;|&nbsp; {drone_label}
      </div>
      <table style="font-size:11px; line-height:1.6;">
        <tr><td style="opacity:0.65; padding-right:10px;">Waypoints</td>
            <td><b>{len(waypoints)}</b> (1 nadir + {len(waypoints)-1} birdseye)</td></tr>
        <tr><td style="opacity:0.65;">Photos</td><td><b>{stats["photo_count"]}</b></td></tr>
        <tr><td style="opacity:0.65;">Flight distance</td>
            <td><b>{stats["total_distance_ft"]:.0f} ft</b>
                <span style="opacity:0.5;">({stats["total_distance_m"]:.0f} m)</span></td></tr>
        <tr><td style="opacity:0.65;">Est. flight time</td>
            <td><b>{int(stats["total_time_s"])} s</b>
                <span style="opacity:0.5;">({stats["total_time_s"]/60:.1f} min)</span></td></tr>
        <tr><td style="opacity:0.65;">Est. battery</td>
            <td><b>{stats["battery_pct_estimate"]:.0f}%</b></td></tr>
        <tr><td style="opacity:0.65;">Speed</td>
            <td><b>{mission["speed_ms"]:.1f} m/s</b></td></tr>
      </table>
      <div style="margin-top:8px; opacity:0.5; font-size:10px;">
        Battery estimate is conservative ({BATTERY_DRAIN_PER_MIN}%/min cruise + {TAKEOFF_LANDING_PCT}% takeoff/landing).
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(stats_html))

    folium.LayerControl(collapsed=True).add_to(m)
    m.add_child(MeasureControl(primary_length_unit="feet", secondary_length_unit="meters"))

    sw = (min(w["lat"] for w in waypoints), min(w["lon"] for w in waypoints))
    ne = (max(w["lat"] for w in waypoints), max(w["lon"] for w in waypoints))
    m.fit_bounds([sw, ne], padding=(60, 60))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    m.save(str(output_path))
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a DJI WPML KMZ as an interactive HTML preview"
    )
    parser.add_argument("kmz", help="Path to KMZ file")
    parser.add_argument("--output", help="Output HTML path (default: <kmz>.preview.html)")
    parser.add_argument("--open", action="store_true",
                        help="Open the rendered HTML in the default browser after writing")
    args = parser.parse_args(argv)

    kmz_path = Path(args.kmz)
    if not kmz_path.exists():
        print(json.dumps({"status": "error", "error": f"File not found: {kmz_path}"}), file=sys.stderr)
        return 1

    output_path = Path(args.output) if args.output else kmz_path.with_suffix(".preview.html")

    try:
        mission = parse_kmz(kmz_path)
        if not mission["waypoints"]:
            print(json.dumps({"status": "error", "error": "No waypoints found in KMZ"}), file=sys.stderr)
            return 1
        path = build_html(mission, output_path)
        result = {
            "status": "ok",
            "output": str(path),
            "size_bytes": path.stat().st_size,
            "waypoint_count": len(mission["waypoints"]),
            "mission_name": mission["mission_name"],
        }
        print(json.dumps(result))
        if args.open:
            webbrowser.open(path.as_uri())
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
