"""
Unit tests for video_qa.py — QA threshold checks, pass/review/fail classification,
Supabase fetch patterns. UNIT-07.
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


# ── check_iso ─────────────────────────────────────────────────────────────────

def test_check_iso_passes_below_ceiling():
    from video_qa import check_iso, DEFAULT_THRESHOLDS
    assert check_iso({"iso_max": 400}, DEFAULT_THRESHOLDS) is None

def test_check_iso_passes_at_ceiling():
    from video_qa import check_iso, DEFAULT_THRESHOLDS
    assert check_iso({"iso_max": 800}, DEFAULT_THRESHOLDS) is None

def test_check_iso_warning_above_ceiling_below_1_5x():
    from video_qa import check_iso, DEFAULT_THRESHOLDS
    # 800 < 1000 < 1200 → warning
    result = check_iso({"iso_max": 1000}, DEFAULT_THRESHOLDS)
    assert result is not None
    assert result["flag"] == "iso_spike"
    assert result["severity"] == "warning"
    assert result["value"] == 1000
    assert result["threshold"] == 800

def test_check_iso_fail_at_1_5x_ceiling():
    from video_qa import check_iso, DEFAULT_THRESHOLDS
    # >= 1200 → fail
    result = check_iso({"iso_max": 1200}, DEFAULT_THRESHOLDS)
    assert result["severity"] == "fail"

def test_check_iso_fail_above_1_5x():
    from video_qa import check_iso, DEFAULT_THRESHOLDS
    result = check_iso({"iso_max": 1600}, DEFAULT_THRESHOLDS)
    assert result["severity"] == "fail"

def test_check_iso_missing_field_returns_none():
    from video_qa import check_iso, DEFAULT_THRESHOLDS
    assert check_iso({}, DEFAULT_THRESHOLDS) is None


# ── check_fps ─────────────────────────────────────────────────────────────────

def test_check_fps_passes_at_minimum():
    from video_qa import check_fps, DEFAULT_THRESHOLDS
    assert check_fps({"fps": 29.0}, DEFAULT_THRESHOLDS) is None

def test_check_fps_passes_above_minimum():
    from video_qa import check_fps, DEFAULT_THRESHOLDS
    assert check_fps({"fps": 30.0}, DEFAULT_THRESHOLDS) is None

def test_check_fps_fails_below_minimum():
    from video_qa import check_fps, DEFAULT_THRESHOLDS
    result = check_fps({"fps": 23.9}, DEFAULT_THRESHOLDS)
    assert result is not None
    assert result["flag"] == "fps_drop"
    assert result["severity"] == "fail"
    assert result["value"] == pytest.approx(23.9)

def test_check_fps_missing_field_returns_none():
    from video_qa import check_fps, DEFAULT_THRESHOLDS
    assert check_fps({}, DEFAULT_THRESHOLDS) is None


# ── check_gps_drift ───────────────────────────────────────────────────────────

def test_check_gps_drift_warning_short_clip():
    from video_qa import check_gps_drift, DEFAULT_THRESHOLDS, METERS_PER_DEG_LAT, METERS_PER_DEG_LON
    # 0.01 deg lat = 1113.2m >> 5m threshold; duration=10 < 30
    asset = {
        "gps_start_lat": 36.8451, "gps_start_lon": -76.2883,
        "gps_end_lat": 36.8551, "gps_end_lon": -76.2783,
        "duration_seconds": 10,
    }
    result = check_gps_drift(asset, DEFAULT_THRESHOLDS)
    assert result is not None
    assert result["flag"] == "gps_drift"
    assert result["severity"] == "warning"

def test_check_gps_drift_no_flag_for_long_clip():
    # duration >= 30 → drift check skipped regardless of movement
    from video_qa import check_gps_drift, DEFAULT_THRESHOLDS
    asset = {
        "gps_start_lat": 36.8451, "gps_start_lon": -76.2883,
        "gps_end_lat": 36.8551, "gps_end_lon": -76.2783,
        "duration_seconds": 30,
    }
    assert check_gps_drift(asset, DEFAULT_THRESHOLDS) is None

def test_check_gps_drift_no_flag_within_threshold():
    from video_qa import check_gps_drift, DEFAULT_THRESHOLDS
    # Tiny movement, well within 5m
    asset = {
        "gps_start_lat": 36.8451, "gps_start_lon": -76.2883,
        "gps_end_lat": 36.845101, "gps_end_lon": -76.2883,
        "duration_seconds": 10,
    }
    assert check_gps_drift(asset, DEFAULT_THRESHOLDS) is None

def test_check_gps_drift_missing_coords_returns_none():
    from video_qa import check_gps_drift, DEFAULT_THRESHOLDS
    assert check_gps_drift({"duration_seconds": 10}, DEFAULT_THRESHOLDS) is None


# ── check_altitude_high ───────────────────────────────────────────────────────

def test_check_altitude_high_passes_100m():
    from video_qa import check_altitude_high
    # 100m * 3.28084 = 328.08ft — under 400ft
    assert check_altitude_high({"altitude_max": 100.0}, {}) is None

def test_check_altitude_high_warns_130m():
    from video_qa import check_altitude_high
    # 130m * 3.28084 = 426.5ft — over 400ft
    result = check_altitude_high({"altitude_max": 130.0}, {})
    assert result is not None
    assert result["flag"] == "altitude_high"
    assert result["severity"] == "warning"
    assert result["value"] == pytest.approx(426.5, abs=0.5)

def test_check_altitude_high_uses_avg_when_max_absent():
    from video_qa import check_altitude_high
    result = check_altitude_high({"altitude_avg": 130.0}, {})
    assert result is not None
    assert result["flag"] == "altitude_high"

def test_check_altitude_high_prefers_max_over_avg():
    from video_qa import check_altitude_high
    # max=80m (passes), avg=130m — should use max, pass
    assert check_altitude_high({"altitude_max": 80.0, "altitude_avg": 130.0}, {}) is None

def test_check_altitude_high_missing_returns_none():
    from video_qa import check_altitude_high
    assert check_altitude_high({}, {}) is None


# ── check_altitude_rate ───────────────────────────────────────────────────────

def test_check_altitude_rate_passes_below_threshold():
    from video_qa import check_altitude_rate, DEFAULT_THRESHOLDS
    assert check_altitude_rate({"altitude_max_change_rate": 5.0}, DEFAULT_THRESHOLDS) is None

def test_check_altitude_rate_warning_above_threshold():
    from video_qa import check_altitude_rate, DEFAULT_THRESHOLDS
    # 15 ft/s > 10 threshold, < 20 (2x) → warning
    result = check_altitude_rate({"altitude_max_change_rate": 15.0}, DEFAULT_THRESHOLDS)
    assert result is not None
    assert result["flag"] == "altitude_jerk"
    assert result["severity"] == "warning"

def test_check_altitude_rate_fail_above_2x_threshold():
    from video_qa import check_altitude_rate, DEFAULT_THRESHOLDS
    # 25 ft/s > 20 (2x threshold=10) → fail
    result = check_altitude_rate({"altitude_max_change_rate": 25.0}, DEFAULT_THRESHOLDS)
    assert result["severity"] == "fail"

def test_check_altitude_rate_missing_returns_none():
    from video_qa import check_altitude_rate, DEFAULT_THRESHOLDS
    assert check_altitude_rate({}, DEFAULT_THRESHOLDS) is None


# ── determine_qa_status ───────────────────────────────────────────────────────

def test_determine_qa_status_empty_flags_pass():
    from video_qa import determine_qa_status
    assert determine_qa_status([]) == "pass"

def test_determine_qa_status_warning_only_review():
    from video_qa import determine_qa_status
    assert determine_qa_status([{"severity": "warning"}]) == "review"

def test_determine_qa_status_any_fail_returns_fail():
    from video_qa import determine_qa_status
    flags = [{"severity": "warning"}, {"severity": "fail"}]
    assert determine_qa_status(flags) == "fail"

def test_determine_qa_status_multiple_warnings_review():
    from video_qa import determine_qa_status
    flags = [{"severity": "warning"}, {"severity": "warning"}]
    assert determine_qa_status(flags) == "review"


# ── run_qa_checks ─────────────────────────────────────────────────────────────

def test_run_qa_checks_clean_asset_returns_no_flags():
    from video_qa import run_qa_checks, DEFAULT_THRESHOLDS
    asset = {"iso_max": 400, "fps": 30.0,
             "gps_start_lat": 36.845, "gps_start_lon": -76.288,
             "gps_end_lat": 36.845, "gps_end_lon": -76.288,
             "altitude_max": 50.0, "altitude_max_change_rate": 2.0,
             "duration_seconds": 60}
    flags = run_qa_checks(asset, DEFAULT_THRESHOLDS)
    assert flags == []

def test_run_qa_checks_multiple_issues():
    from video_qa import run_qa_checks, DEFAULT_THRESHOLDS
    asset = {"iso_max": 1600, "fps": 23.0, "altitude_max": 130.0}
    flags = run_qa_checks(asset, DEFAULT_THRESHOLDS)
    flag_names = {f["flag"] for f in flags}
    assert "iso_spike" in flag_names
    assert "fps_drop" in flag_names
    assert "altitude_high" in flag_names


# ── fetch_thresholds (Supabase) ───────────────────────────────────────────────

def test_fetch_thresholds_returns_default_when_mission_not_found(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("video_qa.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("video_qa.SUPABASE_SERVICE_KEY", "test-key")
    # .single().execute().data = None → no mission found
    (mock_supabase_client.table.return_value.select.return_value
     .eq.return_value.single.return_value.execute.return_value.data) = None

    from video_qa import fetch_thresholds, DEFAULT_THRESHOLDS
    result = fetch_thresholds(mock_supabase_client, "nonexistent-uuid")
    assert result == DEFAULT_THRESHOLDS

def test_fetch_thresholds_returns_default_when_no_package_type(mock_supabase_client, mocker):
    mocker.patch("video_qa.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("video_qa.SUPABASE_SERVICE_KEY", "test-key")
    (mock_supabase_client.table.return_value.select.return_value
     .eq.return_value.single.return_value.execute.return_value.data) = {"package_type": None}

    from video_qa import fetch_thresholds, DEFAULT_THRESHOLDS
    result = fetch_thresholds(mock_supabase_client, "uuid")
    assert result == DEFAULT_THRESHOLDS


# ── update_qa_status (Supabase) ───────────────────────────────────────────────

def test_update_qa_status_calls_update(mock_supabase_client, mocker):
    mocker.patch("video_qa.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("video_qa.SUPABASE_SERVICE_KEY", "test-key")

    from video_qa import update_qa_status
    update_qa_status(mock_supabase_client, "asset-uuid", "pass", {})

    mock_supabase_client.table.assert_called_with("video_assets")
    update_call = mock_supabase_client.table.return_value.update.call_args
    payload = update_call[0][0]
    assert payload["qa_status"] == "pass"
    assert payload["qa_flags"] == {}
