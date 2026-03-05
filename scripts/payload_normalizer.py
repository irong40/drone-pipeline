"""
Payload Normalizer — Python reference implementation.

Mirrors the JavaScript Code node logic in n8n/package_router_normalizer.js.
Provides testable pure functions for folder name parsing and payload
normalization used by the Package Router.

Functions:
    parse_folder_name(folder_name) -> dict | None
    normalize_payload(payload) -> dict
"""
import re
from typing import Optional


# Regex for Sentinel folder naming convention: SAI_MNNNN_TYPE_YYYYMMDD
# The package_type can contain underscores (e.g., construction_hybrid),
# so we use a non-greedy match followed by an 8-digit date anchor.
FOLDER_NAME_PATTERN = re.compile(r"^SAI_M(\d{4})_(.+?)_(\d{8})$")


def parse_folder_name(folder_name: str) -> Optional[dict]:
    """
    Parse a Sentinel folder name into structured components.

    Expected format: SAI_MNNNN_packagetype_YYYYMMDD
    Examples:
        SAI_M0047_re_standard_20260218
        SAI_M0001_construction_hybrid_20260301

    Args:
        folder_name: The folder name string (not full path).

    Returns:
        Dict with mission_number (int), package_type (str), date (str),
        or None if the folder name doesn't match the expected pattern.
    """
    if not folder_name:
        return None

    match = FOLDER_NAME_PATTERN.match(folder_name)
    if not match:
        return None

    return {
        "mission_number": int(match.group(1)),
        "package_type": match.group(2),
        "date": match.group(3),
    }


def normalize_payload(payload: dict) -> dict:
    """
    Normalize a webhook payload from either folder_watcher or ingest_sorter
    into a common format for the Package Router.

    Detection logic:
        - If mission_id is present and folder_name is absent -> ingest_sorter
        - If folder_name is present and mission_id is absent -> folder_watcher

    Args:
        payload: Raw webhook payload dict.

    Returns:
        Normalized dict with consistent keys for routing.
    """
    has_mission_id = bool(payload.get("mission_id"))
    has_folder_name = bool(payload.get("folder_name"))

    if has_mission_id and not has_folder_name:
        # ingest_sorter payload — pass through with metadata
        return {
            "mission_id": payload["mission_id"],
            "mission_number": payload.get("mission_number", 0),
            "package_type": payload.get("package_type", "unknown"),
            "photo_count": payload.get("photo_count", 0),
            "video_count": payload.get("video_count", 0),
            "has_ppk_data": payload.get("has_ppk_data", False),
            "source": "ingest_sorter",
            "needs_mission_lookup": False,
            "is_fallback": False,
            "folder_path": payload.get("sorted_folder", payload.get("folder_path", "")),
        }

    if has_folder_name and not has_mission_id:
        # folder_watcher payload — parse folder name for package_type
        parsed = parse_folder_name(payload["folder_name"])

        if parsed:
            mission_number = parsed["mission_number"]
            package_type = parsed["package_type"]
        else:
            mission_number = payload.get("mission_number", 0)
            package_type = "unknown"

        return {
            "mission_id": None,
            "mission_number": mission_number,
            "package_type": package_type,
            "photo_count": payload.get("photo_count", 0),
            "video_count": payload.get("video_count", 0),
            "has_ppk_data": payload.get("has_ppk_data", False),
            "source": "folder_watcher",
            "needs_mission_lookup": True,
            "is_fallback": True,
            "folder_path": payload.get("folder_path", ""),
        }

    # Unknown payload shape — best-effort normalization
    return {
        "mission_id": payload.get("mission_id"),
        "mission_number": payload.get("mission_number", 0),
        "package_type": payload.get("package_type", "unknown"),
        "photo_count": payload.get("photo_count", 0),
        "video_count": payload.get("video_count", 0),
        "has_ppk_data": payload.get("has_ppk_data", False),
        "source": "unknown",
        "needs_mission_lookup": not has_mission_id,
        "is_fallback": False,
        "folder_path": payload.get("folder_path", ""),
    }
