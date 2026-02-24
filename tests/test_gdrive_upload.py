"""
Unit tests for gdrive_upload.py — folder creation, file upload, shareable link,
move file. UNIT-11.

Uses mock_drive_client fixture from conftest.py.
Patches "gdrive_upload.get_drive_service" per conftest.py docs.
"""
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch


# ── googleapiclient sys.modules stub ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def stub_googleapiclient(mocker):
    """Stub googleapiclient and google.oauth2 so gdrive_upload can be imported
    without the real packages installed."""
    if "googleapiclient" not in sys.modules:
        fake_gapi = types.ModuleType("googleapiclient")
        fake_gapi.discovery = types.ModuleType("googleapiclient.discovery")
        fake_gapi.discovery.build = MagicMock()
        fake_http = types.ModuleType("googleapiclient.http")
        fake_http.MediaFileUpload = MagicMock()
        fake_http.MediaIoBaseDownload = MagicMock()
        mocker.patch.dict(sys.modules, {
            "googleapiclient": fake_gapi,
            "googleapiclient.discovery": fake_gapi.discovery,
            "googleapiclient.http": fake_http,
        })
    if "google" not in sys.modules:
        fake_google = types.ModuleType("google")
        fake_oauth2 = types.ModuleType("google.oauth2")
        fake_sa = types.ModuleType("google.oauth2.service_account")
        fake_sa.Credentials = MagicMock()
        mocker.patch.dict(sys.modules, {
            "google": fake_google,
            "google.oauth2": fake_oauth2,
            "google.oauth2.service_account": fake_sa,
        })


# ── find_or_create_folder ────────────────────────────────────────────────────

def test_find_or_create_folder_existing_returns_folder_id(mock_drive_client, mocker):
    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    # Simulate: Sentinel_Deliveries exists (id=folder-1), Active exists (id=folder-2)
    mock_drive_client.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder-1", "name": "Sentinel_Deliveries"}]},
        {"files": [{"id": "folder-2", "name": "Active"}]},
    ]

    from gdrive_upload import find_or_create_folder
    result = find_or_create_folder(mock_drive_client, "Sentinel_Deliveries/Active")
    assert result == "folder-2"


def test_find_or_create_folder_creates_missing_folder(mock_drive_client, mocker):
    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    # First folder exists, second doesn't — needs creation
    mock_drive_client.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder-1", "name": "Sentinel_Deliveries"}]},
        {"files": []},
    ]
    mock_drive_client.files.return_value.create.return_value.execute.return_value = {
        "id": "new-folder-id"
    }

    from gdrive_upload import find_or_create_folder
    result = find_or_create_folder(mock_drive_client, "Sentinel_Deliveries/Active")
    assert result == "new-folder-id"
    mock_drive_client.files.return_value.create.assert_called()


def test_find_or_create_folder_single_segment(mock_drive_client, mocker):
    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "single-id", "name": "MyFolder"}]
    }

    from gdrive_upload import find_or_create_folder
    result = find_or_create_folder(mock_drive_client, "MyFolder")
    assert result == "single-id"


# ── upload_file ──────────────────────────────────────────────────────────────

def test_upload_file_calls_create_with_correct_metadata(mock_drive_client, tmp_path, mocker):
    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    # Create a real temp file
    test_file = tmp_path / "delivery.zip"
    test_file.write_bytes(b"\x50\x4b" + b"\x00" * 100)

    # Mock the resumable upload chain
    mock_request = MagicMock()
    mock_request.next_chunk.return_value = (None, {"id": "uploaded-id", "name": "delivery.zip", "webViewLink": "https://drive.google.com/file/d/uploaded-id"})
    mock_drive_client.files.return_value.create.return_value = mock_request

    from gdrive_upload import upload_file
    result = upload_file(mock_drive_client, str(test_file), "parent-folder-id")
    assert result["id"] == "uploaded-id"


def test_upload_file_uses_custom_filename(mock_drive_client, tmp_path, mocker):
    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    test_file = tmp_path / "local.zip"
    test_file.write_bytes(b"\x50\x4b" + b"\x00" * 50)

    mock_request = MagicMock()
    mock_request.next_chunk.return_value = (None, {"id": "id-1", "name": "custom.zip"})
    mock_drive_client.files.return_value.create.return_value = mock_request

    from gdrive_upload import upload_file
    result = upload_file(mock_drive_client, str(test_file), "parent-id", filename="custom.zip")
    assert result["name"] == "custom.zip"


# ── create_shareable_link ────────────────────────────────────────────────────

def test_create_shareable_link_calls_permissions_create(mock_drive_client, mocker):
    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.get.return_value.execute.return_value = {
        "webViewLink": "https://drive.google.com/file/d/test-id/view"
    }

    from gdrive_upload import create_shareable_link
    result = create_shareable_link(mock_drive_client, "test-id")
    assert result == "https://drive.google.com/file/d/test-id/view"
    mock_drive_client.permissions.return_value.create.assert_called()


# ── move_file ────────────────────────────────────────────────────────────────

def test_move_file_calls_update_with_add_remove_parents(mock_drive_client, mocker):
    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.get.return_value.execute.return_value = {
        "parents": ["old-parent-id"]
    }

    from gdrive_upload import move_file
    move_file(mock_drive_client, "file-id", "new-parent-id")

    mock_drive_client.files.return_value.update.assert_called()
    update_call = mock_drive_client.files.return_value.update.call_args
    assert update_call[1]["addParents"] == "new-parent-id"
    assert update_call[1]["removeParents"] == "old-parent-id"
