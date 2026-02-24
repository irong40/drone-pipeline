"""
Unit tests for archive_sync.py — sync logic, skip-existing, path-traversal guard,
cleanup safety, dry-run behavior. UNIT-12.

Uses mock_drive_client fixture from conftest.py.
Patches "archive_sync.get_drive_service" per conftest.py docs.
"""
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, timezone


# ── googleapiclient sys.modules stub ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def stub_googleapiclient(mocker):
    """Stub googleapiclient and google.oauth2 so archive_sync can be imported."""
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


# ── find_folder ──────────────────────────────────────────────────────────────

def test_find_folder_returns_id_when_found(mock_drive_client, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "folder-1"}]},
        {"files": [{"id": "folder-2"}]},
    ]

    from archive_sync import find_folder
    result = find_folder(mock_drive_client, "Sentinel_Deliveries/Delivered")
    assert result == "folder-2"


def test_find_folder_returns_none_when_not_found(mock_drive_client, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": []
    }

    from archive_sync import find_folder
    result = find_folder(mock_drive_client, "Nonexistent/Folder")
    assert result is None


# ── list_files_in_folder ─────────────────────────────────────────────────────

def test_list_files_in_folder_returns_all_pages(mock_drive_client, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    # Simulate two pages
    mock_drive_client.files.return_value.list.return_value.execute.side_effect = [
        {
            "files": [{"id": "f1", "name": "file1.zip"}],
            "nextPageToken": "token-2",
        },
        {
            "files": [{"id": "f2", "name": "file2.zip"}],
            "nextPageToken": None,
        },
    ]

    from archive_sync import list_files_in_folder
    result = list_files_in_folder(mock_drive_client, "folder-id")
    assert len(result) == 2
    assert result[0]["id"] == "f1"
    assert result[1]["id"] == "f2"


# ── sync_delivered_to_archive ────────────────────────────────────────────────

def test_sync_downloads_new_file(mock_drive_client, tmp_path, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    # list_files_in_folder returns one file
    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "f1", "name": "delivery.zip", "size": "1024"}],
        "nextPageToken": None,
    }

    # Mock download_file to actually create the dest file with correct size
    def fake_download(service, file_id, dest_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"\x00" * 1024)

    mocker.patch("archive_sync.download_file", side_effect=fake_download)

    from archive_sync import sync_delivered_to_archive
    result = sync_delivered_to_archive(mock_drive_client, "folder-id", str(tmp_path))
    assert len(result) == 1
    assert result[0]["status"] == "synced"


def test_sync_skips_existing_file_with_matching_size(mock_drive_client, tmp_path, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    # Pre-create the file with matching size
    existing = tmp_path / "delivery.zip"
    existing.write_bytes(b"\x00" * 2048)

    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "f1", "name": "delivery.zip", "size": "2048"}],
        "nextPageToken": None,
    }

    from archive_sync import sync_delivered_to_archive
    result = sync_delivered_to_archive(mock_drive_client, "folder-id", str(tmp_path))
    assert len(result) == 1
    assert result[0]["status"] == "exists"


def test_sync_dry_run_does_not_download(mock_drive_client, tmp_path, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "f1", "name": "delivery.zip", "size": "1024"}],
        "nextPageToken": None,
    }
    mock_download = mocker.patch("archive_sync.download_file")

    from archive_sync import sync_delivered_to_archive
    result = sync_delivered_to_archive(mock_drive_client, "folder-id", str(tmp_path), dry_run=True)
    assert len(result) == 1
    assert result[0]["status"] == "dry_run"
    mock_download.assert_not_called()


def test_sync_rejects_path_traversal_filename(mock_drive_client, tmp_path, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "f1", "name": "../../../etc/passwd", "size": "100"}],
        "nextPageToken": None,
    }

    # Mock download_file — after basename stripping, "passwd" is safe and sync proceeds
    def fake_download(service, file_id, dest_path):
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(b"\x00" * 100)

    mocker.patch("archive_sync.download_file", side_effect=fake_download)

    from archive_sync import sync_delivered_to_archive
    result = sync_delivered_to_archive(mock_drive_client, "folder-id", str(tmp_path))
    assert len(result) == 1
    # Path traversal neutralized by os.path.basename — file lands in archive_dir as "passwd"
    assert result[0]["status"] == "synced"
    # Verify the file was created in the archive dir, not in ../../etc/
    assert os.path.isfile(os.path.join(str(tmp_path), "passwd"))


def test_sync_empty_folder_returns_empty_list(mock_drive_client, tmp_path, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "nextPageToken": None,
    }

    from archive_sync import sync_delivered_to_archive
    result = sync_delivered_to_archive(mock_drive_client, "folder-id", str(tmp_path))
    assert result == []


# ── cleanup_old_delivered ────────────────────────────────────────────────────

def test_cleanup_only_deletes_verified_archived_files(mock_drive_client, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    # Mock datetime for cutoff calculation
    mock_dt = mocker.patch("archive_sync.datetime")
    now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    mock_dt.now.return_value = now
    mock_dt.UTC = timezone.utc
    mock_dt.fromisoformat = datetime.fromisoformat

    old_time = "2026-01-01T10:00:00Z"  # > 30 days ago

    # Two old files — only one is in synced_results
    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "f1", "name": "verified.zip", "createdTime": old_time,
             "size": "100", "mimeType": "application/zip", "modifiedTime": old_time},
            {"id": "f2", "name": "unverified.zip", "createdTime": old_time,
             "size": "200", "mimeType": "application/zip", "modifiedTime": old_time},
        ],
        "nextPageToken": None,
    }

    synced_results = [{"name": "verified.zip", "status": "synced"}]
    mock_delete = mocker.patch("archive_sync.delete_file")

    from archive_sync import cleanup_old_delivered
    removed = cleanup_old_delivered(mock_drive_client, "folder-id", synced_results, days=30)
    assert removed == 1
    mock_delete.assert_called_once_with(mock_drive_client, "f1")


def test_cleanup_dry_run_does_not_delete(mock_drive_client, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    mock_dt = mocker.patch("archive_sync.datetime")
    now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    mock_dt.now.return_value = now
    mock_dt.UTC = timezone.utc
    mock_dt.fromisoformat = datetime.fromisoformat

    old_time = "2026-01-01T10:00:00Z"
    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "f1", "name": "old.zip", "createdTime": old_time,
             "size": "100", "mimeType": "application/zip", "modifiedTime": old_time},
        ],
        "nextPageToken": None,
    }

    synced_results = [{"name": "old.zip", "status": "synced"}]
    mock_delete = mocker.patch("archive_sync.delete_file")

    from archive_sync import cleanup_old_delivered
    removed = cleanup_old_delivered(mock_drive_client, "folder-id", synced_results, days=30, dry_run=True)
    assert removed == 1
    mock_delete.assert_not_called()


def test_cleanup_skips_recent_files(mock_drive_client, mocker):
    mocker.patch("archive_sync.get_drive_service", return_value=mock_drive_client)

    mock_dt = mocker.patch("archive_sync.datetime")
    now = datetime(2026, 2, 24, 12, 0, 0, tzinfo=timezone.utc)
    mock_dt.now.return_value = now
    mock_dt.UTC = timezone.utc
    mock_dt.fromisoformat = datetime.fromisoformat

    # File created only 5 days ago
    recent_time = "2026-02-19T10:00:00Z"
    mock_drive_client.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "f1", "name": "recent.zip", "createdTime": recent_time,
             "size": "100", "mimeType": "application/zip", "modifiedTime": recent_time},
        ],
        "nextPageToken": None,
    }

    synced_results = [{"name": "recent.zip", "status": "synced"}]

    from archive_sync import cleanup_old_delivered
    removed = cleanup_old_delivered(mock_drive_client, "folder-id", synced_results, days=30)
    assert removed == 0
