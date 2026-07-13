"""
DJI Mission Ingest → MipMap task.json Generator

Usage:
    python ingest.py E:/DCIM/DJI_001
    python ingest.py E:/DCIM/DJI_001 --run
    python ingest.py E:/DCIM/DJI_001 --mission 2026-02-18_1600
"""

import os
import sys
import json
import uuid
import argparse
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

try:
    from pipeline_utils import preflight_check
except ImportError:
    preflight_check = None

# ─── CONFIG ──────────────────────────────────────────────────────────────────

MIPMAP_ENGINE = r"C:\Program Files\MipMap\MipMapDesktop\resources\resources\catch3d\reconstruct_full_engine.exe"
GDAL_FOLDER = r"C:\ProgramData\MipMap\MipMapDesktop\gdal_data"
EXTENSIONS = [
    os.path.join(os.environ.get("APPDATA", ""), "mipmap-desktop", "extentions", "gs_dlls"),
    os.path.join(os.environ.get("APPDATA", ""), "mipmap-desktop", "extentions", "ml_dlls"),
]
WORKSPACE = "D:/"
LICENSE_ID = 9000
MISSION_GAP_MINUTES = 30  # minutes between shots to split missions

# Fallback camera defaults (used only when EXIF/XMP unavailable)
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


# ─── SENTINEL-CORE IMPORTS ──────────────────────────────────────────────────

from sentinel_core.metadata import extract_gps_from_exif, extract_xmp_fields, extract_xmp_gimbal, gimbal_to_orientation
from sentinel_core.geo import get_utm_zone
from sentinel_core.filename import parse_dji_filename
from sentinel_core.constants import PHOTO_EXTENSIONS


def scan_folder(folder_path):
    """Scan a DCIM folder and return parsed file info for photos.

    Supports both M4E/M3E timestamp format (DJI_YYYYMMDDHHMMSS_NNNN_X.EXT)
    and Mini 4 Pro sequential format (DJI_NNNN.EXT).
    """
    files = []
    for fname in sorted(os.listdir(folder_path)):
        fpath = os.path.join(folder_path, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext not in PHOTO_EXTENSIONS:
            continue
        parsed = parse_dji_filename(fname)
        if parsed:
            parsed["path"] = os.path.abspath(fpath)
            files.append(parsed)
        elif fname.upper().startswith("DJI_"):
            # Mini 4 Pro sequential format — no timestamp to parse
            files.append({
                "datetime": None,
                "sequence": 0,
                "extension": ext.lstrip(".").upper(),
                "filename": fname,
                "path": os.path.abspath(fpath),
            })
    return files


def split_missions(files, gap_minutes=MISSION_GAP_MINUTES):
    """Split files into missions based on timestamp gaps.

    Files without timestamps (Mini 4 Pro sequential format) are grouped
    into a single mission keyed by 'unknown'.
    """
    if not files:
        return {}

    # Separate timestamped vs non-timestamped files
    with_ts = [f for f in files if f["datetime"] is not None]
    without_ts = [f for f in files if f["datetime"] is None]

    missions = {}

    if without_ts:
        missions["unknown"] = without_ts

    if not with_ts:
        return missions

    files = sorted(with_ts, key=lambda f: f["datetime"])
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

def _parse_dewarp_data(dewarp_str):
    """Parse DJI DewarpData string into calibration values.

    Format: 'date;fx,fy,cx_offset,cy_offset,k1,k2,p1,p2,k3'
    Returns list of 9 floats, or None.
    """
    parts = dewarp_str.split(";")
    if len(parts) != 2:
        return None
    values = [float(v) for v in parts[1].split(",")]
    if len(values) < 9:
        return None
    return values


def _detect_camera_from_first_photo(filepath):
    """Read camera parameters from the first photo in a mission.

    Returns dict with width, height, focal_length_35mm, and calibration params.
    Falls back to CAMERA_DEFAULTS if metadata is unreadable.
    """
    try:
        from PIL import Image
        img = Image.open(filepath)
        w, h = img.size
        exif = img.getexif()
        focal_35mm = exif.get(41989, CAMERA_DEFAULTS["focal_length_35mm"]) if exif else CAMERA_DEFAULTS["focal_length_35mm"]
    except Exception:
        return CAMERA_DEFAULTS

    xmp = extract_xmp_fields(filepath)
    dewarp = xmp.get("DewarpData", "") if xmp else ""
    calib = _parse_dewarp_data(dewarp)

    if calib and len(calib) >= 9:
        # DewarpData: fx, fy, cx_offset, cy_offset, k1, k2, p1, p2, k3
        fx, fy = calib[0], calib[1]
        cx = calib[2] + w / 2.0
        cy = calib[3] + h / 2.0
        k1, k2, p1, p2, k3 = calib[4], calib[5], calib[6], calib[7], calib[8]
        params = [fx, fy, cx, cy, k1, k2, k3, p1, p2, 0]
    else:
        # Fallback: estimate from CalibratedFocalLength or hardcoded default
        cal_fl = float(xmp.get("CalibratedFocalLength", w * 0.7)) if xmp else w * 0.7
        params = [cal_fl, cal_fl, w / 2.0, h / 2.0, 0, 0, 0, 0, 0, 0]

    return {
        "width": w,
        "height": h,
        "focal_length_35mm": focal_35mm,
        "fx": params[0],
        "fy": params[1],
        "cx": params[2],
        "cy": params[3],
        "projection_model": 0,
        "params": params,
    }


def build_image_meta_data(files):
    """Build the image_meta_data array from photo files with EXIF/XMP.

    Reads camera calibration from the first photo's metadata (DewarpData,
    image dimensions, focal length). Uses RTK GPS status for pos_sigma
    when available.
    """
    if not files:
        return [], None

    # Detect camera from first photo
    cam = _detect_camera_from_first_photo(files[0]["path"])
    calib = cam.get("params", [cam["fx"], cam["fy"], cam["cx"], cam["cy"], 0, 0, 0, 0, 0, 0])

    images = []
    for idx, f in enumerate(files, start=1):
        filepath = f["path"]
        gps = extract_gps_from_exif(filepath)
        xmp = extract_xmp_fields(filepath)

        if not gps:
            print(f"  WARN: No GPS for {f['filename']}, skipping")
            continue

        # Gimbal orientation
        orientation = [1, 0, 0, 0, 1, 0, 0, 0, 1]  # identity fallback
        rel_alt = 0
        if xmp:
            pitch = float(xmp.get("GimbalPitchDegree", 0))
            roll = float(xmp.get("GimbalRollDegree", 0))
            yaw = float(xmp.get("GimbalYawDegree", 0))
            orientation = gimbal_to_orientation(pitch, roll, yaw)
            rel_alt = float(xmp.get("RelativeAltitude", 0))

        # RTK GPS gives cm-level accuracy vs standard GPS meter-level
        gps_status = xmp.get("GpsStatus", "") if xmp else ""
        is_rtk = gps_status.upper() in ("RTK", "RTKFIXED", "RTK_FIXED")
        pos_sigma = [0.03, 0.03, 0.06] if is_rtk else [2, 2, 5]

        images.append({
            "id": idx,
            "path": filepath.replace("/", "\\"),
            "meta_data": {
                "width": cam["width"],
                "height": cam["height"],
                "camera_id": 1,
                "pos": gps,
                "pos_sigma": pos_sigma,
                "orientation": orientation,
                "relative_altitude": rel_alt,
                "focal_length_in_35mm": cam["focal_length_35mm"],
                "pre_calib_param": list(calib),
            },
        })

    return images, cam


def build_task_json(mission_name, files, output_dir):
    """Build the complete task.json for a mission."""
    images, cam = build_image_meta_data(files)
    if not images:
        return None

    # Determine UTM zone from first image GPS (with hemisphere)
    lon = images[0]["meta_data"]["pos"][0]
    lat = images[0]["meta_data"]["pos"][1]
    zone, utm_epsg = get_utm_zone(lon, latitude=lat)
    hemisphere = "N" if lat >= 0 else "S"

    calib = cam.get("params", [cam["fx"], cam["fy"], cam["cx"], cam["cy"], 0, 0, 0, 0, 0, 0])

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
    parser.add_argument("--skip-preflight", action="store_true", help="Skip preflight service checks")
    args = parser.parse_args()

    # Preflight — verify pipeline services are running
    if not args.skip_preflight and preflight_check:
        preflight_check(require_n8n=False, require_nodeodm=args.run)

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
