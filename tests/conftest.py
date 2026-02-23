"""
Shared pytest fixtures for Sentinel drone pipeline tests.
Provides mock scaffolding for Supabase, Google Drive, and FFmpeg/subprocess.
"""
import subprocess
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_supabase_client():
    """
    Mock Supabase client with pre-configured method chain stubs.

    Covers: .table().select().eq().execute()
             .table().insert().execute()
             .table().upsert().execute()
             .table().update().eq().execute()

    Usage in test:
        def test_something(mock_supabase_client, mocker):
            mocker.patch("supabase.create_client", return_value=mock_supabase_client)

    IMPORTANT: Patch target is "supabase.create_client" NOT "video_qa.create_client".
    Scripts use lazy imports (create_client inside functions), so the name is never
    bound at module level. Patch the library source, not the call site.
    """
    mock_client = MagicMock()
    mock_table = MagicMock()

    # Configure .execute().data for common query chains.
    # MagicMock auto-chains for any attribute/call not listed here.
    mock_table.select.return_value.execute.return_value.data = []
    mock_table.select.return_value.eq.return_value.execute.return_value.data = []
    mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None
    mock_table.insert.return_value.execute.return_value.data = [{"id": "test-id"}]
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "test-id"}]
    mock_table.update.return_value.eq.return_value.execute.return_value.data = []

    mock_client.table.return_value = mock_table
    return mock_client


@pytest.fixture
def mock_drive_client():
    """
    Mock Google Drive API service object.

    Covers: .files().list().execute(), .files().create().execute(),
            .files().update().execute()

    Usage in test:
        def test_something(mock_drive_client, mocker):
            mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    Note: Patch "gdrive_upload.get_drive_service" or "archive_sync.get_drive_service"
    (the function that returns the service), not the googleapiclient.discovery.build call.
    """
    mock_service = MagicMock()

    # files().list().execute() -> {"files": [...], "nextPageToken": None}
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "nextPageToken": None,
    }
    # files().create().execute() -> {"id": "file-id", "name": "file.zip"}
    mock_service.files.return_value.create.return_value.execute.return_value = {
        "id": "mock-file-id",
        "name": "mock-file.zip",
    }
    # files().update().execute() -> {"id": "file-id"}
    mock_service.files.return_value.update.return_value.execute.return_value = {
        "id": "mock-file-id",
    }

    return mock_service


@pytest.fixture
def mock_ffmpeg(mocker):
    """
    Mock subprocess.run for FFmpeg and ffprobe calls.

    Returns the mock so tests can configure return_value or side_effect:
        mock_ffmpeg.return_value = subprocess.CompletedProcess(args=[], returncode=1, ...)
        mock_ffmpeg.side_effect = [result1, result2]  # for multi-call tests

    Scope: function (default) -- tears down automatically via pytest-mock after each test.
    Do NOT make autouse=True -- only applies to tests that explicitly request this fixture.
    """
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="",
        stderr="",
    )
    return mock_run
