"""
Unit tests for srt_telemetry_parser.py — SRT frame parsing, GPS extraction,
clip aggregation, telemetry Supabase upload. UNIT-06.
"""
import math
import types
import pytest
from unittest.mock import MagicMock


# ── Supabase sys.modules stub (supabase not installed in CI) ──────────────────

@pytest.fixture(autouse=True)
def stub_supabase_module(mocker):
    """
    Inject a fake 'supabase' module so mocker.patch("supabase.create_client")
    works without the real supabase package installed.

    autouse=True so every test in this file benefits automatically.
    """
    if "supabase" not in __import__("sys").modules:
        fake_supabase = types.ModuleType("supabase")
        fake_supabase.create_client = MagicMock()
        mocker.patch.dict(__import__("sys").modules, {"supabase": fake_supabase})


# ── parse_srt_timestamp ───────────────────────────────────────────────────────

def test_parse_srt_timestamp_zero():
    from srt_telemetry_parser import parse_srt_timestamp
    assert parse_srt_timestamp("00:00:00,000") == pytest.approx(0.0)

def test_parse_srt_timestamp_seconds_and_ms():
    from srt_telemetry_parser import parse_srt_timestamp
    assert parse_srt_timestamp("00:00:01,500") == pytest.approx(1.5)

def test_parse_srt_timestamp_minutes():
    from srt_telemetry_parser import parse_srt_timestamp
    assert parse_srt_timestamp("00:01:30,500") == pytest.approx(90.5)

def test_parse_srt_timestamp_hours():
    from srt_telemetry_parser import parse_srt_timestamp
    assert parse_srt_timestamp("01:00:00,000") == pytest.approx(3600.0)

def test_parse_srt_timestamp_invalid_returns_zero():
    from srt_telemetry_parser import parse_srt_timestamp
    assert parse_srt_timestamp("not-a-timestamp") == pytest.approx(0.0)


# ── parse_gps ─────────────────────────────────────────────────────────────────

def test_parse_gps_standard_dji_format():
    from srt_telemetry_parser import parse_gps
    text = "F/2.8, SS 500, ISO 100, EV 0, GPS (36.8451, -76.2883, 45)"
    result = parse_gps(text)
    assert result is not None
    assert result["lat"] == pytest.approx(36.8451)
    assert result["lon"] == pytest.approx(-76.2883)
    assert result["alt"] == pytest.approx(45.0)

def test_parse_gps_bracket_format():
    from srt_telemetry_parser import parse_gps
    text = "[latitude: 36.8451] [longitude: -76.2883] [altitude: 45.0]"
    result = parse_gps(text)
    assert result is not None
    assert result["lat"] == pytest.approx(36.8451)
    assert result["lon"] == pytest.approx(-76.2883)
    assert result["alt"] == pytest.approx(45.0)

def test_parse_gps_bracket_format_no_altitude():
    from srt_telemetry_parser import parse_gps
    text = "[latitude: 36.8451] [longitude: -76.2883]"
    result = parse_gps(text)
    assert result is not None
    assert result["alt"] == pytest.approx(0.0)

def test_parse_gps_no_gps_returns_none():
    from srt_telemetry_parser import parse_gps
    assert parse_gps("F/2.8, SS 500, ISO 100") is None

def test_parse_gps_negative_coordinates():
    from srt_telemetry_parser import parse_gps
    text = "GPS (-33.8688, 151.2093, 100)"
    result = parse_gps(text)
    assert result["lat"] == pytest.approx(-33.8688)
    assert result["lon"] == pytest.approx(151.2093)


# ── parse_srt_frame ───────────────────────────────────────────────────────────

def test_parse_srt_frame_full_standard_format():
    from srt_telemetry_parser import parse_srt_frame
    text = "F/2.8, SS 500, ISO 200, EV -0.3, CT 5500, GPS (36.8, -76.3, 30), D 15.3m"
    frame = parse_srt_frame(text)
    assert frame["iso"] == 200
    assert frame["shutter_speed"] == 500
    assert frame["aperture"] == pytest.approx(2.8)
    assert frame["ev"] == pytest.approx(-0.3)
    assert frame["color_temp"] == 5500
    assert frame["gps"]["lat"] == pytest.approx(36.8)
    assert frame["distance_m"] == pytest.approx(15.3)

def test_parse_srt_frame_missing_fields_not_in_result():
    from srt_telemetry_parser import parse_srt_frame
    frame = parse_srt_frame("ISO 100")
    assert frame["iso"] == 100
    assert "aperture" not in frame
    assert "gps" not in frame

def test_parse_srt_frame_zero_ev():
    from srt_telemetry_parser import parse_srt_frame
    frame = parse_srt_frame("EV 0")
    assert frame["ev"] == pytest.approx(0.0)

def test_parse_srt_frame_positive_ev():
    from srt_telemetry_parser import parse_srt_frame
    frame = parse_srt_frame("EV +0.7")
    assert frame["ev"] == pytest.approx(0.7)


# ── parse_srt_file ────────────────────────────────────────────────────────────

def test_parse_srt_file_two_frames(tmp_path):
    srt_content = """1
00:00:00,000 --> 00:00:00,033
F/2.8, SS 500, ISO 100, EV 0, GPS (36.845, -76.288, 30)

2
00:00:00,033 --> 00:00:00,066
F/2.8, SS 500, ISO 100, EV 0, GPS (36.845, -76.288, 31)
"""
    srt_file = tmp_path / "DJI_0001.SRT"
    srt_file.write_text(srt_content, encoding="utf-8")

    from srt_telemetry_parser import parse_srt_file
    frames = parse_srt_file(str(srt_file))
    assert len(frames) == 2
    assert frames[0]["timestamp_start"] == pytest.approx(0.0)
    assert frames[0]["timestamp_end"] == pytest.approx(0.033)
    assert frames[1]["timestamp_start"] == pytest.approx(0.033)
    assert frames[0]["gps"]["lat"] == pytest.approx(36.845)

def test_parse_srt_file_empty_file(tmp_path):
    srt_file = tmp_path / "empty.SRT"
    srt_file.write_text("", encoding="utf-8")
    from srt_telemetry_parser import parse_srt_file
    assert parse_srt_file(str(srt_file)) == []


# ── aggregate_clip ────────────────────────────────────────────────────────────

FRAMES_WITH_GPS = [
    {"timestamp_start": 0.0, "timestamp_end": 0.033,
     "gps": {"lat": 36.845, "lon": -76.288, "alt": 30.0}, "iso": 100},
    {"timestamp_start": 0.033, "timestamp_end": 0.066,
     "gps": {"lat": 36.845, "lon": -76.289, "alt": 30.5}, "iso": 200},
]

def test_aggregate_clip_basic_metrics():
    from srt_telemetry_parser import aggregate_clip
    clip = aggregate_clip(FRAMES_WITH_GPS, "DJI_0001.MP4", source_platform="mini4pro")
    assert clip is not None
    assert clip["frame_count"] == 2
    assert clip["filename"] == "DJI_0001.MP4"
    assert clip["source_platform"] == "mini4pro"
    # duration = 0.066 - 0.0 = 0.066, but round(0.066, 2) = 0.07 (Python banker's rounding)
    assert clip["duration_seconds"] == pytest.approx(0.066, abs=0.01)
    # fps = 2 / 0.066 ≈ 30.3
    assert clip["fps"] == pytest.approx(30.3, abs=0.5)

def test_aggregate_clip_gps_start_end():
    from srt_telemetry_parser import aggregate_clip
    clip = aggregate_clip(FRAMES_WITH_GPS, "DJI_0001.MP4")
    assert clip["gps_start_lat"] == pytest.approx(36.845)
    assert clip["gps_start_lon"] == pytest.approx(-76.288)
    assert clip["gps_end_lat"] == pytest.approx(36.845)
    assert clip["gps_end_lon"] == pytest.approx(-76.289)

def test_aggregate_clip_altitude_stats():
    from srt_telemetry_parser import aggregate_clip
    clip = aggregate_clip(FRAMES_WITH_GPS, "DJI_0001.MP4")
    assert clip["altitude_min"] == pytest.approx(30.0)
    assert clip["altitude_max"] == pytest.approx(30.5)
    # round(30.25, 1) = 30.2 due to Python banker's rounding
    assert clip["altitude_avg"] == pytest.approx(30.25, abs=0.1)

def test_aggregate_clip_altitude_change_rate_in_ft_per_s():
    from srt_telemetry_parser import aggregate_clip
    # delta_m = 0.5m, frame_interval = 0.066/2 = 0.033s
    # rate_m_per_s = 0.5/0.033 ≈ 15.15 m/s
    # rate_ft_per_s = 15.15 * 3.28084 ≈ 49.7 ft/s
    clip = aggregate_clip(FRAMES_WITH_GPS, "DJI_0001.MP4")
    assert clip["altitude_max_change_rate"] == pytest.approx(49.7, abs=2.0)

def test_aggregate_clip_iso_stats():
    from srt_telemetry_parser import aggregate_clip
    clip = aggregate_clip(FRAMES_WITH_GPS, "DJI_0001.MP4")
    assert clip["iso_avg"] == 150
    assert clip["iso_max"] == 200

def test_aggregate_clip_no_gps_omits_gps_fields():
    from srt_telemetry_parser import aggregate_clip
    frames = [
        {"timestamp_start": 0.0, "timestamp_end": 0.033, "iso": 100},
        {"timestamp_start": 0.033, "timestamp_end": 0.066, "iso": 100},
    ]
    clip = aggregate_clip(frames, "DJI_0001.MP4")
    assert "gps_start_lat" not in clip
    assert "altitude_avg" not in clip

def test_aggregate_clip_empty_frames_returns_none():
    from srt_telemetry_parser import aggregate_clip
    assert aggregate_clip([], "DJI_0001.MP4") is None


# ── upload_to_supabase ────────────────────────────────────────────────────────

def test_upload_to_supabase_inserts_record(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("srt_telemetry_parser.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("srt_telemetry_parser.SUPABASE_SERVICE_KEY", "test-key")

    clip_data = {
        "filename": "DJI_0001.MP4",
        "duration_seconds": 10.0,
        "fps": 30.0,
        "gps_start_lat": 36.845, "gps_start_lon": -76.288,
        "gps_end_lat": 36.845, "gps_end_lon": -76.289,
        "altitude_avg": 30.0, "altitude_min": 29.0, "altitude_max": 31.0,
        "altitude_max_change_rate": 1.5,
        "iso_avg": 100, "iso_max": 200,
        "source_platform": "mini4pro",
    }
    from srt_telemetry_parser import upload_to_supabase
    upload_to_supabase(clip_data, "mission-uuid")

    mock_supabase_client.table.assert_called_with("video_assets")
    insert_call = mock_supabase_client.table.return_value.insert.call_args
    record = insert_call[0][0]
    assert record["mission_id"] == "mission-uuid"
    assert record["filename"] == "DJI_0001.MP4"
    assert record["has_srt_telemetry"] is True
    assert record["qa_status"] == "pending"

def test_upload_to_supabase_m4e_sequence_number(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("srt_telemetry_parser.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("srt_telemetry_parser.SUPABASE_SERVICE_KEY", "test-key")

    from srt_telemetry_parser import upload_to_supabase
    upload_to_supabase({"filename": "DJI_20260218101500_0015_D.MP4"}, "uuid")
    record = mock_supabase_client.table.return_value.insert.call_args[0][0]
    assert record["sequence_number"] == 15

def test_upload_to_supabase_raises_when_env_not_set(mocker):
    mocker.patch("srt_telemetry_parser.SUPABASE_URL", "")
    mocker.patch("srt_telemetry_parser.SUPABASE_SERVICE_KEY", "")
    from srt_telemetry_parser import upload_to_supabase
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        upload_to_supabase({"filename": "DJI_0001.MP4"}, "uuid")
