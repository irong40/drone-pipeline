"""
DJI Mission Ingest → MipMap task.json Generator

Usage:
    python ingest.py E:/DCIM/DJI_001
    python ingest.py E:/DCIM/DJI_001 --run
    python ingest.py E:/DCIM/DJI_001 --mission 2026-02-18_1600
"""

import os
import sys
import re
import json
import math
import uuid
import shutil
import argparse
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
except ImportError:
    sys.exit("pip install Pillow")

# ─── CONFIG ──────────────────────────────────────────────────────────────────

MIPMAP_ENGINE = r"C:\Program Files\MipMap\MipMapDesktop\resources\resources\catch3d\reconstruct_full_engine.exe"
GDAL_FOLDER = r"C:\ProgramData\MipMap\MipMapDesktop\gdal_data"
EXTENSIONS = [
    r"C:\Users\redle\AppData\Roaming\mipmap-desktop\extentions\gs_dlls",
    r"C:\Users\redle\AppData\Roaming\mipmap-desktop\extentions\ml_dlls",
]
WORKSPACE = "D:/"
LICENSE_ID = 9000
MISSION_GAP_MINUTES = 30  # minutes between shots to split missions

# Camera defaults for DJI Mini 4 Pro (FC8482)
CAMERA_DEFAULTS = {
    "width": 8064,
    "height": 4536,
    "focal_length_35mm": 24,
    "fx": 5529.6,
    "fy": 5529.6,
    "cx": 4032.0,
    "cy": 2268.0,
    "projection_model": 0,  # 0=Perspective
}

# Default output toggles — match what you set in MipMap GUI
OUTPUT_DEFAULTS = {
    "generate_3d_tiles": True,
    "generate_osgb": True,
    "generate_obj": False,
    "generate_ply": False,
    "generate_fbx": False,
    "generate_skp": False,
    "generate_glb": False,
    "generate_pc_pnts": True,
    "generate_pc_osgb": False,
    "generate_las": True,
    "generate_pc_ply": False,
    "generate_gs_ply": True,
    "generate_gs_splat": False,
    "generate_gs_splat_sog_tiles": True,
    "generate_gs_sog": False,
    "generate_geotiff": True,
    "generate_tile_2D": True,
    "generate_2D_from_3D_model": True,
}

# Default processing params
PROCESSING_DEFAULTS = {
    "resolution_level": 2,         # 1=Ultra, 2=High, 3=Medium
    "mesh_decimate_ratio": 1,      # 1.0 = full quality
    "remove_small_islands": True,
    "fill_water_area_with_AI": False,
    "dom_gsd": 0,                  # 0 = auto
    "keep_undistort_images": False,
    "build_overview": False,
    "cut_frame_2d": False,
    "cut_frame_width": 4096,
    "input_image_type": 1,
    "output_block_change_xml": True,
    "boundary_from_image": None,
    "resumable_reconstruction": True,
}


# ─── EXIF / XMP EXTRACTION ──────────────────────────────────────────────────

def extract_gps_from_exif(filepath):
    """Extract GPS coords from EXIF as [longitude, latitude, altitude]."""
    try:
        img = Image.open(filepath)
        exif = img._getexif()
        if not exif:
            return None
        gps_info = {}
        for tag_id, value in exif.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "GPSInfo":
                gps_info = value
                break
        if not gps_info:
            return None

        def dms_to_decimal(dms, ref):
            d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
            dec = d + m / 60 + s / 3600
            if ref in ("S", "W"):
                dec = -dec
            return dec

        lat = dms_to_decimal(gps_info[2], gps_info[1])
        lon = dms_to_decimal(gps_info[4], gps_info[3])
        alt = float(gps_info.get(6, 0))
        return [lon, lat, alt]
    except Exception:
        return None


def extract_xmp_gimbal(filepath):
    """Extract DJI gimbal angles and metadata from XMP."""
    try:
        with open(filepath, "rb") as f:
            data = f.read(500000)
        start = data.find(b"<x:xmpmeta")
        if start < 0:
            return None
        end = data.find(b"</x:xmpmeta>", start) + len(b"</x:xmpmeta>")
        xmp = data[start:end].decode("utf-8", errors="ignore")
        fields = dict(re.findall(r'drone-dji:(\w+)="([^"]+)"', xmp))
        return {
            "pitch": float(fields.get("GimbalPitchDegree", 0)),
            "roll": float(fields.get("GimbalRollDegree", 0)),
            "yaw": float(fields.get("GimbalYawDegree", 0)),
            "relative_altitude": float(fields.get("RelativeAltitude", 0)),
            "absolute_altitude": float(fields.get("AbsoluteAltitude", 0)),
        }
    except Exception:
        return None


def gimbal_to_orientation(pitch_deg, roll_deg, yaw_deg):
    """Convert DJI gimbal angles to MipMap's 9-element orientation matrix.

    MipMap convention (verified against live task.json):
        Row 0: [cos(y)*cos(r) - sin(y)*sin(p)*sin(r),
                -sin(y)*cos(r) - cos(y)*sin(p)*sin(r),
                cos(p)*sin(r)]
        Row 1: [sin(y)*sin(p), cos(y)*sin(p), -cos(p)]
        Row 2: [sin(y)*cos(p), cos(y)*cos(p),  sin(p)]

    When roll=0 (typical for DJI):
        Row 0: [cos(y), -sin(y), 0]
        Row 1: [sin(y)*sin(p), cos(y)*sin(p), -cos(p)]
        Row 2: [sin(y)*cos(p), cos(y)*cos(p),  sin(p)]
    """
    p = math.radians(pitch_deg)
    r = math.radians(roll_deg)
    y = math.radians(yaw_deg)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    cy, sy = math.cos(y), math.sin(y)

    # Rz(yaw) @ Rx_cam(pitch) @ Ry_cam(roll)
    R = [
        cy * cr - sy * sp * sr, -sy * cr - cy * sp * sr,  cp * sr,
        sy * sp,                 cy * sp,                 -cp,
        sy * cp,                 cy * cp,                  sp,
    ]

    # When roll != 0, use full matrix. Verify the general form:
    # Actually for roll=0 this reduces to the verified formula.
    # For non-zero roll, we need the full Rz(y) @ Rx(p) @ Ry(r):
    if abs(roll_deg) > 0.01:
        Rz = [[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]]
        Rx = [[1, 0, 0], [0, cp, -sp], [0, sp, cp]]
        Ry = [[cr, 0, sr], [0, 1, 0], [-sr, 0, cr]]
        # Rz @ Rx @ Ry
        RxRy = [[sum(Rx[i][k] * Ry[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        M = [[sum(Rz[i][k] * RxRy[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
        R = [M[0][0], M[0][1], M[0][2], M[1][0], M[1][1], M[1][2], M[2][0], M[2][1], M[2][2]]

    return R


def get_utm_zone(longitude):
    """Compute UTM zone and EPSG code from longitude."""
    zone = int((longitude + 180) / 6) + 1
    # Assume northern hemisphere for now (latitude > 0)
    epsg = 32600 + zone
    return zone, epsg


# ─── FILE SCANNING ───────────────────────────────────────────────────────────

def parse_dji_filename(filename):
    """Parse DJI filename: DJI_YYYYMMDDHHMMSS_NNNN_D_NOV25.EXT"""
    m = re.match(r"DJI_(\d{14})_(\d{4})_.*\.(\w+)$", filename, re.IGNORECASE)
    if not m:
        return None
    ts_str, seq, ext = m.group(1), m.group(2), m.group(3).upper()
    dt = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
    return {"datetime": dt, "sequence": int(seq), "extension": ext, "filename": filename}


def scan_folder(folder_path):
    """Scan a DCIM folder and return parsed file info for JPGs only."""
    files = []
    for fname in sorted(os.listdir(folder_path)):
        fpath = os.path.join(folder_path, fname)
        if not os.path.isfile(fpath):
            continue
        parsed = parse_dji_filename(fname)
        if parsed and parsed["extension"] == "JPG":
            parsed["path"] = os.path.abspath(fpath)
            files.append(parsed)
    return files


def split_missions(files, gap_minutes=MISSION_GAP_MINUTES):
    """Split files into missions based on timestamp gaps."""
    if not files:
        return {}
    files = sorted(files, key=lambda f: f["datetime"])
    missions = {}
    current = [files[0]]
    for f in files[1:]:
        gap = (f["datetime"] - current[-1]["datetime"]).total_seconds() / 60
        if gap > gap_minutes:
            dt = current[0]["datetime"]
            key = dt.strftime("%Y-%m-%d_%H%M")
            missions[key] = current
            current = [f]
        else:
            current.append(f)
    dt = current[0]["datetime"]
    key = dt.strftime("%Y-%m-%d_%H%M")
    missions[key] = current
    return missions


# ─── TASK.JSON GENERATION ────────────────────────────────────────────────────

def build_image_meta_data(files):
    """Build the image_meta_data array from JPG files with EXIF/XMP."""
    images = []
    cam = CAMERA_DEFAULTS
    calib = [cam["fx"], cam["fy"], cam["cx"], cam["cy"], 0, 0, 0, 0, 0, 0]

    for idx, f in enumerate(files, start=1):
        filepath = f["path"]
        gps = extract_gps_from_exif(filepath)
        xmp = extract_xmp_gimbal(filepath)

        if not gps:
            print(f"  WARN: No GPS for {f['filename']}, skipping")
            continue

        orientation = [1, 0, 0, 0, 1, 0, 0, 0, 1]  # identity fallback
        rel_alt = 0
        if xmp:
            orientation = gimbal_to_orientation(xmp["pitch"], xmp["roll"], xmp["yaw"])
            rel_alt = xmp["relative_altitude"]

        images.append({
            "id": idx,
            "path": filepath.replace("/", "\\"),
            "meta_data": {
                "width": cam["width"],
                "height": cam["height"],
                "camera_id": 1,
                "pos": gps,
                "pos_sigma": [2, 2, 5],
                "orientation": orientation,
                "relative_altitude": rel_alt,
                "focal_length_in_35mm": cam["focal_length_35mm"],
                "pre_calib_param": list(calib),
            },
        })

    return images


def build_task_json(mission_name, files, output_dir):
    """Build the complete task.json for a mission."""
    images = build_image_meta_data(files)
    if not images:
        return None

    # Determine UTM zone from first image GPS
    lon = images[0]["meta_data"]["pos"][0]
    lat = images[0]["meta_data"]["pos"][1]
    zone, utm_epsg = get_utm_zone(lon)
    hemisphere = "N" if lat >= 0 else "S"

    cam = CAMERA_DEFAULTS
    calib = [cam["fx"], cam["fy"], cam["cx"], cam["cy"], 0, 0, 0, 0, 0, 0]

    result_dir = os.path.join(output_dir, "result").replace("/", "\\")

    task = {
        "license_id": LICENSE_ID,
        "working_dir": result_dir,
        "extension_paths": EXTENSIONS,
        "gdal_folder": GDAL_FOLDER,
        **OUTPUT_DEFAULTS,
        **PROCESSING_DEFAULTS,
        "coordinate_system_2d": {
            "type": 3,
            "type_name": "Projected",
            "label": f"WGS 84 / UTM zone {zone}{hemisphere}",
            "epsg_code": utm_epsg,
        },
        "camera_meta_data": [
            {
                "id": 1,
                "meta_data": {
                    "projection_model": cam["projection_model"],
                    "camera_name": "Camera-1",
                    "width": cam["width"],
                    "height": cam["height"],
                    "parameters": list(calib),
                    "constant_parameters": [],
                },
            }
        ],
        "coordinate_system": {
            "type": 2,
            "label": "WGS 84",
            "type_name": "Geographic",
            "epsg_code": 4326,
        },
        "image_meta_data": images,
    }

    return task


# ─── WORKSPACE SETUP ─────────────────────────────────────────────────────────

def create_workspace(mission_name, task_json, workspace=WORKSPACE):
    """Create MipMap workspace directory structure and write task.json."""
    user_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    project_name = mission_name
    task_name = f"{mission_name}-{now.strftime('%Y%m%d')}"

    # Root: workspace/{user_id}/
    root = os.path.join(workspace, user_id)
    project_dir = os.path.join(root, project_name)
    task_dir = os.path.join(project_dir, task_name)
    result_dir = os.path.join(task_dir, "result")

    os.makedirs(result_dir, exist_ok=True)

    # Update working_dir in task_json
    task_json["working_dir"] = result_dir.replace("/", "\\")

    # Write task.json
    task_json_path = os.path.join(task_dir, "task.json")
    with open(task_json_path, "w") as f:
        json.dump(task_json, f, indent=2)

    # Write indexes.json
    indexes = {
        "projects": {project_id: project_name},
        "tasks": {task_id: {"name": task_name, "project_id": project_id}},
    }
    with open(os.path.join(root, "indexes.json"), "w") as f:
        json.dump(indexes, f, indent=2)

    # Write project_index.json
    with open(os.path.join(root, "project_index.json"), "w") as f:
        json.dump({project_id: project_name}, f, indent=2)

    # Write task_index.json
    with open(os.path.join(root, "task_index.json"), "w") as f:
        json.dump({task_id: task_name}, f, indent=2)

    # Write info.json
    info = {
        "name": task_name,
        "project_id": project_id,
        "user_id": user_id,
        "captured_at": now.isoformat() + "Z",
        "data_type": "normal",
        "status": "waiting",
        "metadata": {
            "groups": [
                {"id": "annotation", "type": "annotation", "i18nKey": "annotation",
                 "collapsed": False, "visible": True, "opacity": 1, "name": "Annotation"},
                {"id": "output", "type": "output", "i18nKey": "result_layer",
                 "collapsed": False, "visible": True, "opacity": 1, "name": "Product Layer"},
                {"id": "dataset", "type": "dataset", "i18nKey": "data_set",
                 "collapsed": False, "visible": True, "opacity": 1, "name": "Dataset"},
                {"id": "overlay", "type": "overlay", "i18nKey": "over_lay",
                 "collapsed": False, "visible": True, "opacity": 1, "name": "Overlay"},
            ],
            "photoPos": {
                "coordinate_system": {"type": 2, "label": "WGS 84", "type_name": "Geographic", "epsg_code": 4326}
            },
            "showROI": True,
            "showBlock": True,
        },
        "params": {
            "type": "rgb",
            "at_mode": "normal",
            "reconstruct_mode": "standalone",
            "resolution_level": PROCESSING_DEFAULTS["resolution_level"],
            "roi": None,
            "mesh_decimate_ratio": PROCESSING_DEFAULTS["mesh_decimate_ratio"],
            "remove_small_islands": PROCESSING_DEFAULTS["remove_small_islands"],
            "machine_learning": False,
            "lidar_mesh_fineness": 0.05,
            "reconstruct_2d": {
                "enable": True,
                "coordinate_system": task_json["coordinate_system_2d"],
                "build_overview": False,
                "cut_frame_2d": False,
                "cut_frame_width": 4096,
                "gsd_mode": "auto",
                "dom_gsd": 0,
            },
            "reconstruct_3d": {
                "enable": True,
                "outputs": ["3d_tiles", "osgb", "pc_pnts", "las", "gs_ply", "gs_sog_tiles"],
                "coordinate_system": "",
            },
        },
        "task_id": task_id,
        "createdAt": now.isoformat(),
        "updatedAt": now.isoformat(),
        "started_at": now.isoformat(),
    }
    with open(os.path.join(task_dir, "info.json"), "w") as f:
        json.dump(info, f, indent=2)

    return {
        "root": root,
        "task_dir": task_dir,
        "task_json_path": task_json_path,
        "result_dir": result_dir,
        "user_id": user_id,
        "project_id": project_id,
        "task_id": task_id,
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DJI Mission Ingest → MipMap task.json")
    parser.add_argument("source", help="Path to DCIM folder (e.g. E:/DCIM/DJI_001)")
    parser.add_argument("--mission", help="Process only this mission (e.g. 2026-02-18_1600)")
    parser.add_argument("--run", action="store_true", help="Launch reconstruct_full_engine after generating")
    parser.add_argument("--quality", type=int, choices=[1, 2, 3], default=2,
                        help="Resolution level: 1=Ultra, 2=High (default), 3=Medium")
    parser.add_argument("--workspace", default=WORKSPACE, help=f"Workspace root (default: {WORKSPACE})")
    parser.add_argument("--list", action="store_true", help="List missions found, don't process")
    args = parser.parse_args()

    source = os.path.abspath(args.source)
    if not os.path.isdir(source):
        sys.exit(f"Source folder not found: {source}")

    print(f"Scanning: {source}")
    files = scan_folder(source)
    print(f"Found {len(files)} JPG files")

    if not files:
        sys.exit("No DJI JPG files found")

    missions = split_missions(files)
    print(f"Detected {len(missions)} mission(s):\n")

    for name, mfiles in sorted(missions.items()):
        first = mfiles[0]["datetime"].strftime("%H:%M:%S")
        last = mfiles[-1]["datetime"].strftime("%H:%M:%S")
        print(f"  {name}  |  {len(mfiles)} photos  |  {first} -> {last}")

    if args.list:
        return

    # Filter to specific mission if requested
    if args.mission:
        if args.mission not in missions:
            sys.exit(f"\nMission '{args.mission}' not found. Available: {', '.join(sorted(missions.keys()))}")
        missions = {args.mission: missions[args.mission]}

    print()

    for name, mfiles in sorted(missions.items()):
        print(f"{'='*60}")
        print(f"Processing mission: {name} ({len(mfiles)} photos)")
        print(f"{'='*60}")

        # Build task.json
        task_dir_temp = os.path.join(args.workspace, "temp")
        task = build_task_json(name, mfiles, task_dir_temp)
        if not task:
            print("  ERROR: No valid images with GPS. Skipping.")
            continue

        task["resolution_level"] = args.quality

        # Create workspace
        ws = create_workspace(name, task, workspace=args.workspace)
        print(f"  Workspace: {ws['task_dir']}")
        print(f"  task.json: {ws['task_json_path']}")
        print(f"  Images:    {len(task['image_meta_data'])}")
        print(f"  UTM Zone:  {task['coordinate_system_2d']['label']}")
        print(f"  Quality:   Level {task['resolution_level']}")

        if args.run:
            import subprocess
            cmd = [
                MIPMAP_ENGINE,
                f'--task_json={ws["task_json_path"]}',
                "--reconstruct_type=0",
            ]
            print(f"\n  Launching: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
            print(f"  PID: {proc.pid}")
            print(f"  Waiting for completion...")
            ret = proc.wait()
            print(f"  Exit code: {ret}")
        else:
            print(f"\n  To run manually:")
            print(f'  "{MIPMAP_ENGINE}" --task_json="{ws["task_json_path"]}" --reconstruct_type=0')

        print()


if __name__ == "__main__":
    main()
