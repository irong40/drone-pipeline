"""
Sentinel Aerial Inspections -- MipMap Desktop Launcher (Step C1)

Fire-and-forget subprocess launcher for MipMap Desktop's reconstruct_full_engine.
Starts the process, redirects stdout to a log file (50-200MB output), writes a
PID file for orphan detection, and returns immediately with JSON stdout.

n8n Path C sub-workflow calls this via Execute Command. The script returns
immediately so n8n can poll for completion separately.

Usage:
    python mipmap_launcher.py --mission-id SAI_M0047 --mission-path E:\\Sentinel\\Incoming\\SAI_M0047 --engine-path "C:\\MipMap\\reconstruct_full_engine.exe"
    python mipmap_launcher.py --mission-id SAI_M0047 --mission-path E:\\Sentinel\\Incoming\\SAI_M0047

Exit codes:
    0 - MipMap launched successfully
    1 - Runtime error (orphan detected, launch failed)
    2 - Configuration error (missing engine executable)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pipeline_status import PipelineStatusReporter, add_pipeline_args
from pipeline_utils import setup_logging

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_NAME = "mipmap_launcher"

# Default engine path from env, or common install location
DEFAULT_ENGINE_PATH = os.environ.get(
    "MIPMAP_ENGINE_PATH",
    r"C:\Program Files\MipMapDesktop\reconstruct_full_engine.exe",
)

# Default workspace from env or D:\MipMapWorkspace
DEFAULT_WORKSPACE = os.environ.get("MIPMAP_WORKSPACE", r"D:\MipMapWorkspace")

# Expected process name for orphan detection
MIPMAP_PROCESS_NAME = "reconstruct_full_engine.exe"


# ─── ORPHAN DETECTION ────────────────────────────────────────────────────────

def check_orphan(pid_file_path: str) -> bool:
    """Check if a MipMap process is already running via PID file.

    Returns True if an active MipMap process is detected (orphan).
    Returns False if no PID file, stale PID, or recycled PID.
    Cleans up stale/recycled PID files automatically.
    """
    if not os.path.isfile(pid_file_path):
        return False

    try:
        with open(pid_file_path, "r") as f:
            pid_data = json.load(f)
        pid = pid_data.get("pid")
        if pid is None:
            os.remove(pid_file_path)
            return False
    except (json.JSONDecodeError, OSError):
        # Corrupt PID file -- remove and allow launch
        try:
            os.remove(pid_file_path)
        except OSError:
            pass
        return False

    import psutil

    # Check if PID is alive
    if not psutil.pid_exists(pid):
        # Stale PID -- process is dead
        try:
            os.remove(pid_file_path)
        except OSError:
            pass
        return False

    # PID exists -- check if it's actually MipMap (not a recycled PID)
    try:
        proc = psutil.Process(pid)
        proc_name = proc.name()
        if proc_name.lower() == MIPMAP_PROCESS_NAME.lower():
            # Active MipMap process found
            return True
        else:
            # PID recycled to a different process
            try:
                os.remove(pid_file_path)
            except OSError:
                pass
            return False
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        # Process disappeared or access denied -- clean up
        try:
            os.remove(pid_file_path)
        except OSError:
            pass
        return False


# ─── LAUNCH ──────────────────────────────────────────────────────────────────

def launch_mipmap(
    engine_path: str,
    workspace: str,
    mission_id: str,
    pid_file_path: str,
    log_file_path: str,
) -> dict:
    """Launch MipMap Desktop as a fire-and-forget subprocess.

    Opens a log file for stdout redirect (MipMap produces 50-200MB output),
    starts the process via Popen (no shell=True), writes a PID file, and
    returns immediately.

    Args:
        engine_path: Path to reconstruct_full_engine.exe
        workspace: MipMap workspace directory
        mission_id: Mission identifier for the PID file
        pid_file_path: Where to write the PID JSON file
        log_file_path: Where to redirect MipMap stdout

    Returns:
        dict with status, pid, log_file keys
    """
    # Ensure parent directories exist
    os.makedirs(os.path.dirname(pid_file_path), exist_ok=True)
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    # Open log file for stdout redirect
    log_handle = open(log_file_path, "w")

    # Launch MipMap -- CRITICAL: no shell=True (returns shell PID, not MipMap PID)
    cmd = [engine_path, "--workspace", workspace]
    proc = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        shell=False,
    )

    # Write PID file
    pid_data = {
        "pid": proc.pid,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "project": mission_id,
    }
    with open(pid_file_path, "w") as f:
        json.dump(pid_data, f, indent=2)

    return {
        "status": "launched",
        "pid": proc.pid,
        "log_file": log_file_path,
        "pid_file": pid_file_path,
    }


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Sentinel Aerial Inspections -- MipMap Desktop Launcher (Step C1)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mission-id", required=True,
                        help="Mission identifier (e.g. SAI_M0047)")
    parser.add_argument("--mission-path", required=True,
                        help="Path to mission folder")
    parser.add_argument("--engine-path", default=DEFAULT_ENGINE_PATH,
                        help=f"Path to reconstruct_full_engine.exe (default: {DEFAULT_ENGINE_PATH})")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE,
                        help=f"MipMap workspace directory (default: {DEFAULT_WORKSPACE})")
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # Pipeline status reporter
    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name=SCRIPT_NAME,
    )
    reporter.start()

    # Validate engine path
    if not os.path.isfile(args.engine_path):
        log.error(f"MipMap engine not found: {args.engine_path}")
        reporter.fail(f"Engine not found: {args.engine_path}")
        sys.exit(2)

    mission_path = os.path.abspath(args.mission_path)

    # Paths for PID and log files
    pipeline_dir = os.path.join(mission_path, ".pipeline")
    os.makedirs(pipeline_dir, exist_ok=True)
    pid_file_path = os.path.join(pipeline_dir, "mipmap.pid")
    log_file_path = os.path.join(pipeline_dir, "mipmap_stdout.log")

    # Check for orphan MipMap process
    if check_orphan(pid_file_path):
        log.error(f"Orphan MipMap process detected -- see PID file: {pid_file_path}")
        reporter.fail("Orphan MipMap process detected")
        print(json.dumps({
            "status": "error",
            "error": "orphan_detected",
            "pid_file": pid_file_path,
        }))
        sys.exit(1)

    # Launch MipMap
    try:
        result = launch_mipmap(
            engine_path=args.engine_path,
            workspace=args.workspace,
            mission_id=args.mission_id,
            pid_file_path=pid_file_path,
            log_file_path=log_file_path,
        )
        log.info(f"MipMap launched: PID={result['pid']}, log={result['log_file']}")
        reporter.complete(output=f"Launched PID {result['pid']}")
        print(json.dumps(result))

    except Exception as e:
        log.error(f"Failed to launch MipMap: {e}")
        reporter.fail(str(e))
        print(json.dumps({
            "status": "error",
            "error": str(e),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
