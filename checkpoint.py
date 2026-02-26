"""
Sentinel Aerial Inspections — Checkpoint/Resume Utility

Provides atomic JSON checkpoint files for per-file resume across pipeline scripts.
Checkpoints are stored in the mission folder as .checkpoint_{script}.json.
"""

import json
import os
import tempfile

CHECKPOINT_VERSION = 1


def checkpoint_path(mission_path, script_name):
    """Return the path to the checkpoint file for this script + mission."""
    return os.path.join(mission_path, f".checkpoint_{script_name}.json")


def load_checkpoint(mission_path, script_name):
    """Load the set of completed item keys. Returns empty set if no checkpoint exists."""
    path = checkpoint_path(mission_path, script_name)
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return set()
        if data.get("version") != CHECKPOINT_VERSION:
            return set()
        return set(data.get("completed", []))
    except (json.JSONDecodeError, KeyError, OSError):
        return set()


def save_checkpoint(mission_path, script_name, completed):
    """Atomically write checkpoint. completed is a set or list of item keys."""
    path = checkpoint_path(mission_path, script_name)
    data = {
        "version": CHECKPOINT_VERSION,
        "script": script_name,
        "completed": sorted(completed),
    }
    dir_ = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)  # Atomic on POSIX and Windows (Python 3.3+)
    except OSError as e:
        # Non-fatal: log in caller; worst case script re-processes on next run
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def clear_checkpoint(mission_path, script_name):
    """Remove checkpoint file (used by --force flag to re-process from scratch)."""
    path = checkpoint_path(mission_path, script_name)
    if os.path.isfile(path):
        os.unlink(path)
