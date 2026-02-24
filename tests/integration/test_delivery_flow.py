"""
Integration test: delivery packaging + Drive upload flow — real ZIP creation with
correctly renamed photos/videos, plus mocked Drive API calls. INTG-03.
"""
import os
import zipfile
import pytest

from delivery_packaging import (
    collect_photos,
    collect_video_exports,
    rename_photo,
    rename_video_export,
    create_delivery_zip,
    build_prefix,
)


@pytest.fixture
def complete_mission(tmp_path):
    """Mission folder with photos and video exports."""
    mission = tmp_path / "SAI_M0047_re_standard_20260218"

    # Photos
    jpeg_dir = mission / "photos" / "jpeg"
    jpeg_dir.mkdir(parents=True)
    for i in range(1, 4):
        (jpeg_dir / f"DJI_{i:04d}.JPG").write_bytes(b"\xff\xd8" + bytes([i]) * 20)

    # Video exports
    exports_dir = mission / "video" / "exports"
    exports_dir.mkdir(parents=True)
    (exports_dir / "master_youtube.mp4").write_bytes(b"\x00\x00\x00\x20ftyp" + b"\x00" * 50)
    (exports_dir / "master_instagram_reels.mp4").write_bytes(b"\x00\x00\x00\x20ftyp" + b"\x00" * 40)

    return mission


def test_delivery_zip_contains_renamed_photos(complete_mission, tmp_path):
    """Collect photos -> build manifest -> create ZIP with Sentinel naming."""
    photos = collect_photos(str(complete_mission))
    assert len(photos) == 3

    prefix = build_prefix("123 Main St", "Virginia Beach")
    manifest = []
    for i, ppath in enumerate(photos, 1):
        archive_name = f"photos/{rename_photo(ppath, prefix, i)}"
        manifest.append((ppath, archive_name))

    zip_path = str(tmp_path / "delivery.zip")
    create_delivery_zip(zip_path, manifest)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == 3
        for name in names:
            assert name.startswith("photos/Sentinel_")
            assert name.endswith(".jpg")


def test_delivery_zip_contains_renamed_videos(complete_mission, tmp_path):
    """Collect video exports -> rename -> create ZIP with PropertyTour labels."""
    videos = collect_video_exports(str(complete_mission))
    assert len(videos) == 2

    prefix = build_prefix("123 Main St", "Virginia Beach")
    manifest = []
    for vpath in videos:
        archive_name = f"video/{rename_video_export(vpath, prefix)}"
        manifest.append((vpath, archive_name))

    zip_path = str(tmp_path / "delivery.zip")
    create_delivery_zip(zip_path, manifest)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert any("PropertyTour_YouTube" in n for n in names)
        assert any("PropertyTour_Reels" in n for n in names)


def test_delivery_zip_full_delivery_photos_and_videos(complete_mission, tmp_path):
    """Combined manifest of photos + videos -> ZIP with correct prefixes."""
    photos = collect_photos(str(complete_mission))
    videos = collect_video_exports(str(complete_mission))

    prefix = build_prefix("456 Oak Ave", "Norfolk")
    manifest = []
    for i, ppath in enumerate(photos, 1):
        manifest.append((ppath, f"photos/{rename_photo(ppath, prefix, i)}"))
    for vpath in videos:
        manifest.append((vpath, f"video/{rename_video_export(vpath, prefix)}"))

    zip_path = str(tmp_path / "full_delivery.zip")
    create_delivery_zip(zip_path, manifest)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == 5
        photo_names = [n for n in names if n.startswith("photos/")]
        video_names = [n for n in names if n.startswith("video/")]
        assert len(photo_names) == 3
        assert len(video_names) == 2


def test_drive_upload_calls_find_or_create_and_upload(complete_mission, tmp_path, mock_drive_client, mocker):
    """Create real ZIP, then mock Drive service to verify API calls."""
    import sys
    import types
    from unittest.mock import MagicMock

    # Stub googleapiclient
    if "googleapiclient" not in sys.modules:
        fake_gapi = types.ModuleType("googleapiclient")
        fake_gapi.discovery = types.ModuleType("googleapiclient.discovery")
        fake_gapi.discovery.build = MagicMock()
        fake_http = types.ModuleType("googleapiclient.http")
        fake_http.MediaFileUpload = MagicMock()
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

    mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)

    # Create a real ZIP first
    photos = collect_photos(str(complete_mission))
    prefix = build_prefix("789 Elm Dr", "Hampton")
    manifest = [(p, f"photos/{rename_photo(p, prefix, i)}") for i, p in enumerate(photos, 1)]
    zip_path = str(tmp_path / "test_upload.zip")
    create_delivery_zip(zip_path, manifest)
    assert os.path.isfile(zip_path)

    # Mock find_or_create_folder
    mock_drive_client.files.return_value.list.return_value.execute.side_effect = [
        {"files": [{"id": "deliveries-id", "name": "Sentinel_Deliveries"}]},
        {"files": [{"id": "active-id", "name": "Active"}]},
    ]

    from gdrive_upload import find_or_create_folder
    folder_id = find_or_create_folder(mock_drive_client, "Sentinel_Deliveries/Active")
    assert folder_id == "active-id"

    # Mock upload_file resumable upload
    mock_request = MagicMock()
    mock_request.next_chunk.return_value = (None, {"id": "uploaded-id", "name": "test_upload.zip"})
    mock_drive_client.files.return_value.create.return_value = mock_request

    from gdrive_upload import upload_file
    result = upload_file(mock_drive_client, zip_path, folder_id)
    assert result["id"] == "uploaded-id"
