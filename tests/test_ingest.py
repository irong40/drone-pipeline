"""
Unit tests for ingest.py — MipMap photogrammetry ingest.
UNIT-14: covers parse_dji_filename, split_missions, get_utm_zone,
         gimbal_to_orientation, extract_gps_from_exif, extract_xmp_gimbal.

NOTE: ingest.py calls sys.exit() at module level when Pillow is not installed.
This stub uses pytest.importorskip as a defensive guard so collection skips cleanly
on environments without Pillow rather than raising a SystemExit INTERNALERROR.
"""
import math
import pytest
from datetime import datetime
from unittest.mock import MagicMock

# Guard: skip entire file if Pillow is not available
pytest.importorskip("PIL", reason="Pillow required for ingest.py importability test")

import ingest  # noqa: F401 — verify importability after PIL confirmed

from ingest import (
    parse_dji_filename,
    split_missions,
    get_utm_zone,
    gimbal_to_orientation,
    extract_gps_from_exif,
    extract_xmp_gimbal,
)


# ─── parse_dji_filename ───────────────────────────────────────────────────────

def test_parse_dji_filename_m4e_format():
    """M4E timestamp format parsed: datetime, sequence, extension extracted."""
    result = parse_dji_filename("DJI_20260218101500_0015_D.JPG")
    assert result is not None
    assert result["datetime"] == datetime(2026, 2, 18, 10, 15, 0)
    assert result["sequence"] == 15
    assert result["extension"] == "JPG"


def test_parse_dji_filename_m4e_with_suffix():
    """M4E variant with extra suffix (e.g. NOV25): sequence and extension still parsed."""
    result = parse_dji_filename("DJI_20260218101500_0001_D_NOV25.DNG")
    assert result is not None
    assert result["sequence"] == 1
    assert result["extension"] == "DNG"


def test_parse_dji_filename_mini4pro_returns_none():
    """Mini 4 Pro sequential format (DJI_NNNN.EXT) does not match M4E pattern — returns None."""
    assert parse_dji_filename("DJI_0015.JPG") is None


def test_parse_dji_filename_random_returns_none():
    """Non-DJI filename returns None."""
    assert parse_dji_filename("random.jpg") is None


# ─── split_missions ───────────────────────────────────────────────────────────

def _make_file_dict(dt):
    return {
        "filename": f"DJI_{dt.strftime('%Y%m%d%H%M%S')}_0001_D.JPG",
        "datetime": dt,
        "sequence": 1,
        "extension": "JPG",
    }


def test_split_missions_two_missions_on_gap():
    """35-minute gap between groups produces two separate missions."""
    t0 = datetime(2026, 2, 18, 10, 0, 0)
    t1 = datetime(2026, 2, 18, 10, 5, 0)
    t2 = datetime(2026, 2, 18, 10, 10, 0)
    # Gap: 35 minutes after t2
    t3 = datetime(2026, 2, 18, 10, 45, 0)
    t4 = datetime(2026, 2, 18, 10, 50, 0)

    files = [_make_file_dict(t0), _make_file_dict(t1), _make_file_dict(t2),
             _make_file_dict(t3), _make_file_dict(t4)]
    result = split_missions(files)
    assert len(result) == 2


def test_split_missions_single_mission_within_threshold():
    """All files within 30-minute gap produce a single mission."""
    t0 = datetime(2026, 2, 18, 10, 0, 0)
    t1 = datetime(2026, 2, 18, 10, 10, 0)
    t2 = datetime(2026, 2, 18, 10, 20, 0)
    files = [_make_file_dict(t0), _make_file_dict(t1), _make_file_dict(t2)]
    result = split_missions(files)
    assert len(result) == 1


def test_split_missions_empty_returns_empty_dict():
    """Empty input list returns empty dict."""
    assert split_missions([]) == {}


# ─── get_utm_zone ─────────────────────────────────────────────────────────────

def test_get_utm_zone_hampton_roads():
    """Hampton Roads VA longitude -76.3 is in UTM zone 18 (EPSG 32618)."""
    zone, epsg = get_utm_zone(-76.3)
    assert zone == 18
    assert epsg == 32618


def test_get_utm_zone_west_edge():
    """Longitude -180.0 (west edge) is zone 1, EPSG 32601."""
    zone, epsg = get_utm_zone(-180.0)
    assert zone == 1
    assert epsg == 32601


def test_get_utm_zone_prime_meridian():
    """Longitude 0.0 (prime meridian) is zone 31, EPSG 32631."""
    zone, epsg = get_utm_zone(0.0)
    assert zone == 31
    assert epsg == 32631


# ─── gimbal_to_orientation ────────────────────────────────────────────────────

def test_gimbal_to_orientation_zero_gimbal():
    """Zero pitch/roll/yaw produces the standard DJI nadir orientation matrix."""
    result = gimbal_to_orientation(0.0, 0.0, 0.0)
    # From formula: cy=1,sy=0,cp=1,sp=0,cr=1,sr=0
    # Row0: [cy*cr-sy*sp*sr, -sy*cr-cy*sp*sr, cp*sr] = [1, 0, 0]
    # Row1: [sy*sp, cy*sp, -cp] = [0, 0, -1]
    # Row2: [sy*cp, cy*cp, sp]  = [0, 1, 0]
    expected = [1, 0, 0, 0, 0, -1, 0, 1, 0]
    assert len(result) == 9
    for actual_val, exp_val in zip(result, expected):
        assert actual_val == pytest.approx(exp_val, abs=1e-9)


def test_gimbal_to_orientation_90_degree_yaw():
    """90-degree yaw: cos(90)≈0, sin(90)=1 — matrix uses simplified roll=0 path."""
    result = gimbal_to_orientation(0.0, 0.0, 90.0)
    # cy≈0, sy=1, cp=1, sp=0, cr=1, sr=0
    # Row0: [cy*1-sy*0*0, -sy*1-cy*0*0, cp*0] = [0, -1, 0]
    # Row1: [sy*0, cy*0, -cp] = [0, 0, -1]
    # Row2: [sy*cp, cy*cp, sp] = [1, 0, 0]
    expected = [0, -1, 0, 0, 0, -1, 1, 0, 0]
    assert len(result) == 9
    for actual_val, exp_val in zip(result, expected):
        assert actual_val == pytest.approx(exp_val, abs=1e-9)


def test_gimbal_to_orientation_nonzero_roll_returns_9_elements():
    """Non-zero roll triggers full Rz@Rx@Ry path — result must still be 9-element list."""
    result = gimbal_to_orientation(0.0, 1.0, 0.0)
    assert isinstance(result, list)
    assert len(result) == 9


# ─── extract_gps_from_exif ────────────────────────────────────────────────────

def test_extract_gps_from_exif_valid(mocker):
    """Valid GPS EXIF: returns [lon, lat, alt] as floats."""
    from PIL import Image
    mock_exif = Image.Exif()
    # GPSInfo IFD: {1: lat_ref, 2: lat_dms, 3: lon_ref, 4: lon_dms, 6: alt}
    gps_data = {1: "N", 2: (37, 0, 0), 3: "W", 4: (76, 0, 0), 6: 50.0}
    mock_img = MagicMock()
    mock_exif_obj = MagicMock()
    mock_exif_obj.__bool__ = lambda self: True
    mock_exif_obj.get_ifd = MagicMock(return_value=gps_data)
    mock_img.getexif.return_value = mock_exif_obj
    mocker.patch("PIL.Image.open", return_value=mock_img)

    result = extract_gps_from_exif("/fake/DJI_0001.JPG")
    assert result is not None
    # lon = -76.0 (W), lat = 37.0 (N), alt = 50.0
    assert result[0] == pytest.approx(-76.0, abs=1e-9)
    assert result[1] == pytest.approx(37.0, abs=1e-9)
    assert result[2] == pytest.approx(50.0, abs=1e-9)


def test_extract_gps_from_exif_no_exif(mocker):
    """Image with no EXIF (getexif returns empty): returns None."""
    mock_img = MagicMock()
    mock_exif_obj = MagicMock()
    mock_exif_obj.__bool__ = lambda self: False
    mock_img.getexif.return_value = mock_exif_obj
    mocker.patch("PIL.Image.open", return_value=mock_img)

    result = extract_gps_from_exif("/fake/DJI_0001.JPG")
    assert result is None


def test_extract_gps_from_exif_no_gps_tag(mocker):
    """EXIF present but no GPS tag: returns None."""
    mock_img = MagicMock()
    mock_exif_obj = MagicMock()
    mock_exif_obj.__bool__ = lambda self: True
    mock_exif_obj.get_ifd = MagicMock(return_value={})  # Empty GPSInfo IFD
    mock_img.getexif.return_value = mock_exif_obj
    mocker.patch("PIL.Image.open", return_value=mock_img)

    result = extract_gps_from_exif("/fake/DJI_0001.JPG")
    assert result is None


# ─── extract_xmp_gimbal ───────────────────────────────────────────────────────

def test_extract_xmp_gimbal_valid_xmp(tmp_path):
    """XMP block with gimbal data: parsed correctly into float dict."""
    xmp_bytes = (
        b'<x:xmpmeta drone-dji:GimbalPitchDegree="-90.0" '
        b'drone-dji:GimbalRollDegree="0.0" '
        b'drone-dji:GimbalYawDegree="45.0" '
        b'drone-dji:RelativeAltitude="30.5" '
        b'drone-dji:AbsoluteAltitude="35.2"></x:xmpmeta>'
    )
    test_file = tmp_path / "test.jpg"
    test_file.write_bytes(xmp_bytes)

    result = extract_xmp_gimbal(str(test_file))
    assert result is not None
    assert result["pitch"] == pytest.approx(-90.0)
    assert result["yaw"] == pytest.approx(45.0)
    assert result["roll"] == pytest.approx(0.0)
    assert result["relative_altitude"] == pytest.approx(30.5)
    assert result["absolute_altitude"] == pytest.approx(35.2)


def test_extract_xmp_gimbal_no_xmp_block(tmp_path):
    """File with no XMP block returns None."""
    test_file = tmp_path / "no_xmp.jpg"
    test_file.write_bytes(b"JFIF fake jpeg data without xmp block")

    result = extract_xmp_gimbal(str(test_file))
    assert result is None
