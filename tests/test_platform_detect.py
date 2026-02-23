"""
Unit tests for platform_detect.py — EXIF drone platform detection (Mini 4 Pro, M4E, M3E).
UNIT-02: Full coverage of detect_from_exiftool, detect_from_exif, detect_from_ffprobe,
_extract_metadata_text, and detect_platform_from_folder.
"""
import json
import subprocess
import sys
import types
import pytest
from unittest.mock import MagicMock

import platform_detect
from platform_detect import (
    detect_from_exiftool,
    detect_from_exif,
    detect_from_ffprobe,
    _extract_metadata_text,
    detect_platform_from_folder,
)


def _make_exiftool_mock(metadata_list=None, enter_side_effect=None):
    """Build a fake exiftool module + ExifToolHelper for sys.modules injection.

    Returns (fake_exiftool_module, mock_et_instance) so tests can configure
    mock_et_instance.get_metadata.return_value before calling detect_from_exiftool.
    """
    fake_exiftool = types.ModuleType("exiftool")
    mock_et_class = MagicMock()
    mock_et_instance = MagicMock()

    if enter_side_effect is not None:
        mock_et_class.return_value.__enter__.side_effect = enter_side_effect
    else:
        mock_et_class.return_value.__enter__.return_value = mock_et_instance
        if metadata_list is not None:
            mock_et_instance.get_metadata.return_value = metadata_list

    fake_exiftool.ExifToolHelper = mock_et_class
    return fake_exiftool, mock_et_instance


# ─── detect_from_exiftool ────────────────────────────────────────────────────

def test_exiftool_mini4pro_via_xmp(mocker):
    """Mini 4 Pro identified via XMP:Model = FC8282."""
    fake_et, mock_instance = _make_exiftool_mock(
        [{"XMP:Model": "FC8282", "EXIF:Model": "", "EXIF:Make": "DJI"}]
    )
    mocker.patch.dict("sys.modules", {"exiftool": fake_et})

    platform, meta = detect_from_exiftool("fake_mini4pro.JPG")

    assert platform == "mini4pro"
    assert meta is not None
    assert meta["XMP:Model"] == "FC8282"


def test_exiftool_m4e_via_xmp(mocker):
    """M4E identified via XMP:Model = FC9100."""
    fake_et, mock_instance = _make_exiftool_mock(
        [{"XMP:Model": "FC9100", "EXIF:Model": "", "EXIF:Make": "DJI"}]
    )
    mocker.patch.dict("sys.modules", {"exiftool": fake_et})

    platform, meta = detect_from_exiftool("fake_m4e.JPG")

    assert platform == "m4e"
    assert meta is not None


def test_exiftool_m3e_via_exif_model(mocker):
    """M3E identified via EXIF:Model when XMP:Model is empty."""
    fake_et, mock_instance = _make_exiftool_mock(
        [{"XMP:Model": "", "EXIF:Model": "DJI Mavic 3 Enterprise", "EXIF:Make": "DJI"}]
    )
    mocker.patch.dict("sys.modules", {"exiftool": fake_et})

    platform, meta = detect_from_exiftool("fake_m3e.JPG")

    assert platform == "m3e"
    assert meta is not None


def test_exiftool_unrecognized_model_returns_none_meta(mocker):
    """Unrecognized model returns (None, meta) — meta dict is still returned."""
    fake_et, mock_instance = _make_exiftool_mock(
        [{"XMP:Model": "UNKNOWN", "EXIF:Model": "UNKNOWN", "EXIF:Make": "DJI"}]
    )
    mocker.patch.dict("sys.modules", {"exiftool": fake_et})

    platform, meta = detect_from_exiftool("fake_unknown.JPG")

    assert platform is None
    assert meta is not None  # meta dict still returned even if platform not identified
    assert meta["XMP:Model"] == "UNKNOWN"


def test_exiftool_exception_returns_none_none(mocker):
    """Exception during context manager entry returns (None, None)."""
    fake_et, _ = _make_exiftool_mock(enter_side_effect=Exception("exiftool failed"))
    mocker.patch.dict("sys.modules", {"exiftool": fake_et})

    platform, meta = detect_from_exiftool("fake.JPG")

    assert platform is None
    assert meta is None


def test_exiftool_empty_metadata_list_returns_none_none(mocker):
    """Empty metadata list from exiftool returns (None, None)."""
    fake_et, mock_instance = _make_exiftool_mock([])
    mocker.patch.dict("sys.modules", {"exiftool": fake_et})

    platform, meta = detect_from_exiftool("fake.JPG")

    assert platform is None
    assert meta is None


# ─── detect_from_exif (fallback chain) ──────────────────────────────────────

def test_exif_returns_platform_when_exiftool_succeeds(mocker):
    """detect_from_exif returns platform directly when detect_from_exiftool succeeds."""
    mocker.patch(
        "platform_detect.detect_from_exiftool",
        return_value=("mini4pro", {"XMP:Model": "FC8282"}),
    )
    mock_pil_open = mocker.patch("PIL.Image.open")

    result = detect_from_exif("fake_mini4pro.JPG")

    assert result == "mini4pro"
    mock_pil_open.assert_not_called()


def test_exif_pil_fallback_mini4pro(mocker):
    """PIL fallback correctly identifies Mini 4 Pro via tag 272 = FC8282."""
    mocker.patch("platform_detect.detect_from_exiftool", return_value=(None, None))
    mock_img = MagicMock()
    mock_img.getexif.return_value = {272: "FC8282", 271: "DJI"}
    mocker.patch("PIL.Image.open", return_value=mock_img)

    result = detect_from_exif("fake_mini4pro.JPG")

    assert result == "mini4pro"


def test_exif_pil_fallback_m3e_via_pattern(mocker):
    """PIL fallback identifies M3E via substring pattern on model string."""
    mocker.patch("platform_detect.detect_from_exiftool", return_value=(None, None))
    mock_img = MagicMock()
    mock_img.getexif.return_value = {272: "DJI Mavic 3E", 271: "DJI"}
    mocker.patch("PIL.Image.open", return_value=mock_img)

    result = detect_from_exif("fake_m3e.JPG")

    assert result == "m3e"


def test_exif_no_exif_data_returns_none(mocker):
    """PIL fallback returns None when getexif() returns None."""
    mocker.patch("platform_detect.detect_from_exiftool", return_value=(None, None))
    mock_img = MagicMock()
    mock_img.getexif.return_value = None
    mocker.patch("PIL.Image.open", return_value=mock_img)

    result = detect_from_exif("fake.JPG")

    assert result is None


# ─── detect_from_ffprobe ─────────────────────────────────────────────────────

def test_ffprobe_mini4pro_in_format_tags(mocker):
    """Mini 4 Pro detected from format-level encoder tag."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({
            "format": {"tags": {"encoder": "DJI Mini 4 Pro"}},
            "streams": [],
        }),
        stderr="",
    )

    result = detect_from_ffprobe("fake_mini4pro.MP4")

    assert result == "mini4pro"


def test_ffprobe_m4e_in_stream_tags(mocker):
    """M4E detected from stream-level make tag."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({
            "format": {},
            "streams": [{"tags": {"make": "DJI Matrice 4E"}}],
        }),
        stderr="",
    )

    result = detect_from_ffprobe("fake_m4e.MP4")

    assert result == "m4e"


def test_ffprobe_returncode_nonzero_returns_none(mocker):
    """Non-zero returncode returns None (ffprobe failed)."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr="error",
    )

    result = detect_from_ffprobe("fake.MP4")

    assert result is None


def test_ffprobe_json_decode_error_returns_none(mocker):
    """Invalid JSON stdout returns None."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="not valid json {{{}",
        stderr="",
    )

    result = detect_from_ffprobe("fake.MP4")

    assert result is None


def test_ffprobe_no_matching_patterns_returns_none(mocker):
    """Valid JSON but no recognized platform patterns returns None."""
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"format": {"tags": {}}, "streams": []}),
        stderr="",
    )

    result = detect_from_ffprobe("fake_unknown.MP4")

    assert result is None


# ─── _extract_metadata_text ──────────────────────────────────────────────────

def test_extract_metadata_format_tags_only():
    """Format-level tags are included in the searchable text."""
    data = {
        "format": {"tags": {"encoder": "DJI Mini 4 Pro", "artist": "test"}},
        "streams": [],
    }
    result = _extract_metadata_text(data)

    assert "DJI Mini 4 Pro" in result
    assert "test" in result


def test_extract_metadata_stream_tags():
    """Stream-level tags are included in the searchable text."""
    data = {
        "format": {},
        "streams": [{"tags": {"make": "DJI Matrice 4E"}}],
    }
    result = _extract_metadata_text(data)

    assert "DJI Matrice 4E" in result


def test_extract_metadata_stream_codec_field():
    """Stream codec_long_name field is included in the searchable text."""
    data = {
        "format": {},
        "streams": [{"codec_long_name": "H.264 / AVC / MPEG-4 DJI M3E encoder"}],
    }
    result = _extract_metadata_text(data)

    assert "DJI M3E encoder" in result


# ─── detect_platform_from_folder ─────────────────────────────────────────────

def test_detect_platform_from_folder_photo_exif_path(tmp_path, mocker):
    """Photo EXIF path: JPEG file in photos/jpeg subfolder triggers EXIF detection."""
    # Create the expected directory structure with a fake JPEG file
    jpeg_dir = tmp_path / "photos" / "jpeg"
    jpeg_dir.mkdir(parents=True)
    fake_jpg = jpeg_dir / "DJI_0001.JPG"
    fake_jpg.write_bytes(b"")  # 0-byte placeholder

    # Patch detect_from_exiftool to return M4E identification
    mocker.patch(
        "platform_detect.detect_from_exiftool",
        return_value=("m4e", {"XMP:Model": "FC9100"}),
    )

    platform, confidence, method = detect_platform_from_folder(str(tmp_path))

    assert platform == "m4e"
    assert confidence == "confirmed"
    assert method == "exif"


def test_detect_platform_from_folder_empty_folder_returns_unknown(tmp_path):
    """Empty folder returns (None, 'unknown', None) — no files to sample."""
    platform, confidence, method = detect_platform_from_folder(str(tmp_path))

    assert platform is None
    assert confidence == "unknown"
    assert method is None


def test_detect_platform_from_folder_filename_fallback(tmp_path):
    """When no EXIF/ffprobe data, filename pattern fallback identifies mini4pro."""
    # Place a file with DJI mini4pro filename pattern at the top level
    fake_file = tmp_path / "DJI_0001.JPG"
    fake_file.write_bytes(b"")

    # Patch detect_from_exiftool to return nothing (exiftool unavailable)
    # and PIL to return no EXIF — so EXIF path finds no platform
    # The folder detection falls through to filename fallback
    platform, confidence, method = detect_platform_from_folder(str(tmp_path))

    # With a DJI_0001.JPG file, filename fallback should kick in
    assert platform == "mini4pro"
    assert confidence == "likely"
    assert method == "filename"
