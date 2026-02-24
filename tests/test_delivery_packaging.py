"""
Unit tests for delivery_packaging.py — ZIP structure, address-based naming,
file collection, renaming, and delivery ZIP creation. UNIT-10.
"""
import os
import zipfile
import pytest

from delivery_packaging import (
    sanitize_address,
    build_prefix,
    build_zip_name,
    extract_date_from_folder,
    collect_photos,
    collect_video_exports,
    collect_mapping,
    collect_reports,
    rename_photo,
    rename_video_export,
    rename_mapping,
    rename_report,
    create_delivery_zip,
)


# ── sanitize_address ─────────────────────────────────────────────────────────

def test_sanitize_address_spaces_to_underscores():
    assert sanitize_address("123 Main St") == "123_Main_St"


def test_sanitize_address_strips_commas_and_special():
    assert sanitize_address("456 Oak Ave, Apt 2B") == "456_Oak_Ave_Apt_2B"


def test_sanitize_address_preserves_hyphens():
    assert sanitize_address("789 Elm-Dr") == "789_Elm-Dr"


def test_sanitize_address_strips_leading_trailing_whitespace():
    assert sanitize_address("  100 Pine Rd  ") == "100_Pine_Rd"


# ── build_prefix ─────────────────────────────────────────────────────────────

def test_build_prefix_standard():
    result = build_prefix("123 Main St", "Virginia Beach")
    assert result == "Sentinel_123_Main_St_Virginia_Beach"


def test_build_prefix_special_chars_in_city():
    result = build_prefix("456 Oak Ave", "O'Fallon")
    assert result == "Sentinel_456_Oak_Ave_OFallon"


# ── build_zip_name ───────────────────────────────────────────────────────────

def test_build_zip_name_format():
    result = build_zip_name("Sentinel_123_Main_St_VB", "20260218")
    assert result == "Sentinel_123_Main_St_VB_20260218.zip"


# ── extract_date_from_folder ─────────────────────────────────────────────────

def test_extract_date_from_folder_standard_name():
    result = extract_date_from_folder("/path/to/SAI_M0047_re_standard_20260218")
    assert result == "20260218"


def test_extract_date_from_folder_no_date_uses_today(mocker):
    mocker.patch("delivery_packaging.datetime")
    from delivery_packaging import datetime as dt_mock
    dt_mock.now.return_value.strftime.return_value = "20260224"
    result = extract_date_from_folder("/path/to/some_folder")
    assert result == "20260224"


# ── collect_photos ───────────────────────────────────────────────────────────

def test_collect_photos_finds_jpegs(tmp_path):
    jpeg_dir = tmp_path / "photos" / "jpeg"
    jpeg_dir.mkdir(parents=True)
    (jpeg_dir / "DJI_0001.JPG").write_bytes(b"\xff\xd8")
    (jpeg_dir / "DJI_0002.jpg").write_bytes(b"\xff\xd8")
    (jpeg_dir / "readme.txt").write_bytes(b"skip me")

    result = collect_photos(str(tmp_path))
    assert len(result) == 2
    assert all(f.endswith((".JPG", ".jpg")) for f in result)


def test_collect_photos_empty_when_no_dir(tmp_path):
    assert collect_photos(str(tmp_path)) == []


# ── collect_video_exports ────────────────────────────────────────────────────

def test_collect_video_exports_finds_mp4s(tmp_path):
    exports_dir = tmp_path / "video" / "exports"
    exports_dir.mkdir(parents=True)
    (exports_dir / "master_youtube.mp4").write_bytes(b"\x00")
    (exports_dir / "master_instagram_reels.mp4").write_bytes(b"\x00")
    (exports_dir / "thumbnail.png").write_bytes(b"\x89PNG")

    result = collect_video_exports(str(tmp_path))
    assert len(result) == 2


def test_collect_video_exports_empty_when_no_dir(tmp_path):
    assert collect_video_exports(str(tmp_path)) == []


# ── rename_photo ─────────────────────────────────────────────────────────────

def test_rename_photo_format():
    result = rename_photo("/path/DJI_0001.JPG", "Sentinel_123_Main_VB", 1)
    assert result == "Sentinel_123_Main_VB_001.jpg"


def test_rename_photo_preserves_extension():
    result = rename_photo("/path/photo.jpeg", "Sentinel_Test", 5)
    assert result == "Sentinel_Test_005.jpeg"


# ── rename_video_export ──────────────────────────────────────────────────────

def test_rename_video_youtube_format():
    result = rename_video_export("/path/master_youtube.mp4", "Sentinel_123_Main_VB")
    assert result == "Sentinel_123_Main_VB_PropertyTour_YouTube.mp4"


def test_rename_video_instagram_reels_format():
    result = rename_video_export("/path/master_instagram_reels.mp4", "Sentinel_123_Main_VB")
    assert result == "Sentinel_123_Main_VB_PropertyTour_Reels.mp4"


def test_rename_video_unknown_format_uses_stem():
    result = rename_video_export("/path/custom_edit.mp4", "Sentinel_Test")
    assert result == "Sentinel_Test_custom_edit.mp4"


# ── rename_mapping ───────────────────────────────────────────────────────────

def test_rename_mapping_orthophoto():
    result = rename_mapping("/path/ortho_result.tif", "Sentinel_Test")
    assert result == "Sentinel_Test_Orthophoto.tif"


def test_rename_mapping_3d_model():
    result = rename_mapping("/path/3d_model.obj", "Sentinel_Test")
    assert result == "Sentinel_Test_3DModel.obj"


def test_rename_mapping_point_cloud():
    result = rename_mapping("/path/point_cloud.laz", "Sentinel_Test")
    assert result == "Sentinel_Test_PointCloud.laz"


def test_rename_mapping_fallback():
    result = rename_mapping("/path/custom_output.tif", "Sentinel_Test")
    assert result == "Sentinel_Test_custom_output.tif"


# ── rename_report ────────────────────────────────────────────────────────────

def test_rename_report_inspection():
    result = rename_report("/path/inspection_report.pdf", "Sentinel_Test")
    assert result == "Sentinel_Test_Inspection_Report.pdf"


def test_rename_report_change_detection():
    result = rename_report("/path/change_detection.pdf", "Sentinel_Test")
    assert result == "Sentinel_Test_Change_Detection.pdf"


# ── create_delivery_zip ──────────────────────────────────────────────────────

def test_create_delivery_zip_creates_valid_zip(tmp_path):
    # Create source files
    src1 = tmp_path / "photo1.jpg"
    src2 = tmp_path / "photo2.jpg"
    src1.write_bytes(b"\xff\xd8photo1")
    src2.write_bytes(b"\xff\xd8photo2")

    manifest = [
        (str(src1), "photos/Sentinel_Test_001.jpg"),
        (str(src2), "photos/Sentinel_Test_002.jpg"),
    ]
    zip_path = str(tmp_path / "output" / "delivery.zip")

    result = create_delivery_zip(zip_path, manifest)
    assert result == zip_path
    assert os.path.isfile(zip_path)

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert "photos/Sentinel_Test_001.jpg" in names
        assert "photos/Sentinel_Test_002.jpg" in names
        assert len(names) == 2


def test_create_delivery_zip_dry_run_returns_none(tmp_path):
    src = tmp_path / "file.jpg"
    src.write_bytes(b"\xff\xd8")
    manifest = [(str(src), "photos/test.jpg")]
    zip_path = str(tmp_path / "output" / "delivery.zip")

    result = create_delivery_zip(zip_path, manifest, dry_run=True)
    assert result is None
    assert not os.path.exists(zip_path)


def test_create_delivery_zip_photos_and_videos(tmp_path):
    jpeg_dir = tmp_path / "photos" / "jpeg"
    jpeg_dir.mkdir(parents=True)
    exports_dir = tmp_path / "video" / "exports"
    exports_dir.mkdir(parents=True)

    photos = []
    for i in range(3):
        p = jpeg_dir / f"DJI_{i:04d}.JPG"
        p.write_bytes(b"\xff\xd8" + bytes(i))
        photos.append(str(p))

    videos = []
    for name in ["master_youtube.mp4", "master_instagram_reels.mp4"]:
        v = exports_dir / name
        v.write_bytes(b"\x00\x00" + name.encode())
        videos.append(str(v))

    prefix = "Sentinel_123_Main_VB"
    manifest = []
    for i, p in enumerate(photos, 1):
        archive_name = f"photos/{rename_photo(p, prefix, i)}"
        manifest.append((p, archive_name))
    for v in videos:
        archive_name = f"video/{rename_video_export(v, prefix)}"
        manifest.append((v, archive_name))

    zip_path = str(tmp_path / "output" / "delivery.zip")
    result = create_delivery_zip(zip_path, manifest)
    assert result == zip_path

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        assert len(names) == 5
        photo_names = [n for n in names if n.startswith("photos/")]
        video_names = [n for n in names if n.startswith("video/")]
        assert len(photo_names) == 3
        assert len(video_names) == 2
        assert any("PropertyTour_YouTube" in n for n in video_names)
        assert any("PropertyTour_Reels" in n for n in video_names)
