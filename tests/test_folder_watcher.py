"""
Unit tests for folder_watcher.py — filesystem event monitoring, debounce logic, webhook triggering.
Covers UNIT-03: debounce timer control, event filtering, webhook payload with Z-suffix timestamp.

NOTE: folder_watcher.py imports requests at module level and calls sys.exit() when watchdog
is not installed. This file uses pytest.importorskip guards so collection skips cleanly
on environments without these dependencies.
"""
import os
import pytest
from unittest.mock import MagicMock

# Guards: skip entire file if required packages are not available
pytest.importorskip("requests", reason="requests required for folder_watcher.py importability test")
pytest.importorskip("watchdog", reason="watchdog required for folder_watcher.py importability test")

import requests  # noqa: E402 — imported after importorskip guard
import folder_watcher  # noqa: F401,E402 — verify importability after dependencies confirmed

from folder_watcher import (  # noqa: E402
    parse_mission_number,
    build_inventory,
    fire_webhook,
    MissionFolderHandler,
)


# ─── parse_mission_number ─────────────────────────────────────────────────────

def test_parse_mission_number_standard():
    """Extracts mission number from a standard SAI folder name."""
    assert parse_mission_number("SAI_M0047_re_standard_20260218") == 47


def test_parse_mission_number_leading_zeros():
    """Leading zeros are stripped — returns integer 1 not 0001."""
    assert parse_mission_number("SAI_M0001_video_20260101") == 1


def test_parse_mission_number_max():
    """Accepts 4-digit mission numbers up to 9999."""
    assert parse_mission_number("SAI_M9999_mapping_20260301") == 9999


def test_parse_mission_number_no_match():
    """Non-SAI folder names return None."""
    assert parse_mission_number("NOT_A_MISSION_FOLDER") is None


def test_parse_mission_number_broken():
    """SAI_M without digits returns None — regex requires \\d{4}."""
    assert parse_mission_number("SAI_M_broken") is None


# ─── build_inventory ─────────────────────────────────────────────────────────

def test_build_inventory_mixed_files(tmp_path):
    """Counts photos, video, and PPK files; mission_number extracted; Z-suffix timestamp."""
    mission_path = tmp_path / "SAI_M0047_re_standard_20260218"
    (mission_path / "photos" / "jpeg").mkdir(parents=True)
    (mission_path / "video" / "full").mkdir(parents=True)
    (mission_path / "ppk").mkdir(parents=True)

    (mission_path / "photos" / "jpeg" / "DJI_0001.JPG").write_bytes(b"fake photo")
    (mission_path / "video" / "full" / "DJI_0001.MP4").write_bytes(b"fake video")
    (mission_path / "ppk" / "DJI_0001.MRK").write_bytes(b"fake ppk")

    result = build_inventory(str(mission_path))

    assert result["photo_count"] == 1
    assert result["video_count"] == 1
    assert result["has_ppk_data"] is True
    assert result["mission_number"] == 47
    assert result["detected_at"].endswith("Z"), (
        f"detected_at must use Z suffix, got: {result['detected_at']!r}"
    )


def test_build_inventory_empty_folder(tmp_path):
    """Empty mission folder returns zero counts and no PPK."""
    mission_path = tmp_path / "SAI_M0001_re_standard_20260218"
    mission_path.mkdir()

    result = build_inventory(str(mission_path))

    assert result["photo_count"] == 0
    assert result["video_count"] == 0
    assert result["has_ppk_data"] is False


def test_build_inventory_photos_only(tmp_path):
    """Folder with only DNG files: photo_count > 0, has_ppk_data = False."""
    mission_path = tmp_path / "SAI_M0002_re_standard_20260218"
    (mission_path / "photos" / "raw").mkdir(parents=True)
    (mission_path / "photos" / "raw" / "DJI_0001.DNG").write_bytes(b"raw1")
    (mission_path / "photos" / "raw" / "DJI_0002.DNG").write_bytes(b"raw2")

    result = build_inventory(str(mission_path))

    assert result["photo_count"] > 0
    assert result["has_ppk_data"] is False


def test_build_inventory_total_size(tmp_path):
    """total_size_bytes is > 0 when a real file with content is present."""
    mission_path = tmp_path / "SAI_M0003_re_standard_20260218"
    (mission_path / "photos" / "jpeg").mkdir(parents=True)
    (mission_path / "photos" / "jpeg" / "DJI_0001.JPG").write_bytes(b"x" * 512)

    result = build_inventory(str(mission_path))

    assert result["total_size_bytes"] > 0


def test_build_inventory_z_suffix_not_plus(tmp_path):
    """detected_at must use Z suffix, never +00:00."""
    mission_path = tmp_path / "SAI_M0004_re_standard_20260218"
    mission_path.mkdir()

    result = build_inventory(str(mission_path))

    assert "+00:00" not in result["detected_at"]
    assert result["detected_at"].endswith("Z")


# ─── fire_webhook ─────────────────────────────────────────────────────────────

def test_fire_webhook_success(mocker):
    """Returns True when requests.post succeeds and raise_for_status() does nothing."""
    mock_post = mocker.patch("requests.post")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_post.return_value = mock_resp

    inventory = {
        "folder_name": "SAI_M0047_re_standard_20260218",
        "photo_count": 3,
        "video_count": 0,
        "has_ppk_data": False,
    }

    result = fire_webhook(inventory)

    assert result is True
    mock_post.assert_called_once()
    _, call_kwargs = mock_post.call_args
    assert call_kwargs.get("json") == inventory


def test_fire_webhook_request_exception(mocker):
    """Returns False when raise_for_status() raises RequestException."""
    mock_post = mocker.patch("requests.post")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.RequestException("connection refused")
    mock_post.return_value = mock_resp

    inventory = {"folder_name": "SAI_M0047_re_standard_20260218", "photo_count": 0}

    result = fire_webhook(inventory)

    assert result is False


# ─── MissionFolderHandler._reset_timer ────────────────────────────────────────

def test_reset_timer_cancels_previous_and_starts_new(mocker):
    """Calling _reset_timer twice: first timer is cancelled, second timer starts."""
    mock_timer_class = mocker.patch("folder_watcher.threading.Timer")
    mock_timer1 = MagicMock()
    mock_timer2 = MagicMock()
    mock_timer_class.side_effect = [mock_timer1, mock_timer2]

    handler = MissionFolderHandler(watch_dir="/tmp/watch", debounce_seconds=60)
    handler._reset_timer("SAI_M0001_re_standard_20260218")
    handler._reset_timer("SAI_M0001_re_standard_20260218")

    mock_timer1.cancel.assert_called_once()
    mock_timer2.start.assert_called_once()


def test_reset_timer_triggered_guard(mocker):
    """Once a folder is in _triggered, a second _reset_timer call is a no-op."""
    mock_timer_class = mocker.patch("folder_watcher.threading.Timer")
    mock_timer1 = MagicMock()
    mock_timer_class.side_effect = [mock_timer1]

    handler = MissionFolderHandler(watch_dir="/tmp/watch", debounce_seconds=60)
    handler._reset_timer("SAI_M0001_re_standard_20260218")

    # Simulate folder already processed
    handler._triggered.add("SAI_M0001_re_standard_20260218")

    handler._reset_timer("SAI_M0001_re_standard_20260218")

    # Only one timer ever created (the second call returned early)
    assert mock_timer_class.call_count == 1


def test_reset_timer_daemon_flag(mocker):
    """Timer has daemon=True set so it doesn't block process exit."""
    mock_timer_class = mocker.patch("folder_watcher.threading.Timer")
    mock_timer1 = MagicMock()
    mock_timer_class.return_value = mock_timer1

    handler = MissionFolderHandler(watch_dir="/tmp/watch", debounce_seconds=60)
    handler._reset_timer("SAI_M0001_re_standard_20260218")

    # daemon attribute should be set to True before start()
    assert mock_timer1.daemon is True
    mock_timer1.start.assert_called_once()


# ─── MissionFolderHandler.on_created ─────────────────────────────────────────

def test_on_created_top_level_mission_folder(mocker):
    """Directory event at top level calls _reset_timer with the folder name."""
    mocker.patch("folder_watcher.threading.Timer")
    handler = MissionFolderHandler(watch_dir="/watch", debounce_seconds=60)
    mocker.patch.object(handler, "_reset_timer")

    event = MagicMock()
    event.is_directory = True
    event.src_path = "/watch/SAI_M0001_re_standard_20260218"

    handler.on_created(event)

    handler._reset_timer.assert_called_once_with("SAI_M0001_re_standard_20260218")


def test_on_created_file_inside_mission_folder(mocker):
    """File event inside a mission folder calls _reset_timer with the mission folder name."""
    mocker.patch("folder_watcher.threading.Timer")
    handler = MissionFolderHandler(watch_dir="/watch", debounce_seconds=60)
    mocker.patch.object(handler, "_reset_timer")

    event = MagicMock()
    event.is_directory = False
    event.src_path = "/watch/SAI_M0001_re_standard_20260218/photos/jpeg/DJI_0001.JPG"

    handler.on_created(event)

    handler._reset_timer.assert_called_once_with("SAI_M0001_re_standard_20260218")


def test_on_created_nested_subdir_ignored(mocker):
    """Non-top-level directory events do not call _reset_timer."""
    mocker.patch("folder_watcher.threading.Timer")
    handler = MissionFolderHandler(watch_dir="/watch", debounce_seconds=60)
    mocker.patch.object(handler, "_reset_timer")

    event = MagicMock()
    event.is_directory = True
    # This is a subdirectory inside the mission folder, not a top-level mission dir
    event.src_path = "/watch/SAI_M0001_re_standard_20260218/photos"

    handler.on_created(event)

    handler._reset_timer.assert_not_called()


# ─── MissionFolderHandler._on_debounce_complete ───────────────────────────────

def test_on_debounce_complete_triggers_inventory_and_webhook(mocker, tmp_path):
    """_on_debounce_complete: adds to _triggered, calls build_inventory, calls fire_webhook."""
    mocker.patch("folder_watcher.threading.Timer")

    fake_inventory = {
        "folder_name": "SAI_M0001_re_standard_20260218",
        "photo_count": 5,
        "video_count": 1,
        "has_ppk_data": True,
        "total_size_bytes": 1024,
    }
    mock_build = mocker.patch("folder_watcher.build_inventory", return_value=fake_inventory)
    mock_fire = mocker.patch("folder_watcher.fire_webhook")

    handler = MissionFolderHandler(watch_dir=str(tmp_path), debounce_seconds=60)
    folder_name = "SAI_M0001_re_standard_20260218"

    handler._on_debounce_complete(folder_name)

    assert folder_name in handler._triggered
    expected_path = os.path.join(str(tmp_path), folder_name)
    mock_build.assert_called_once_with(expected_path)
    mock_fire.assert_called_once()
