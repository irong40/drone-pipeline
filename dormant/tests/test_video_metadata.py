"""
Unit tests for video_metadata.py — ffprobe parsing, codec normalization,
sequence number extraction, graded file detection, LRF proxy detection,
Supabase update-vs-insert branch. UNIT-05.
"""
import json
import types
import pytest
from unittest.mock import MagicMock


# ── Supabase sys.modules stub (supabase not installed in CI) ──────────────────

@pytest.fixture(autouse=True)
def stub_supabase_module(mocker):
    """
    Inject a fake 'supabase' module so mocker.patch("supabase.create_client")
    works without the real supabase package installed.
    """
    if "supabase" not in __import__("sys").modules:
        fake_supabase = types.ModuleType("supabase")
        fake_supabase.create_client = MagicMock()
        mocker.patch.dict(__import__("sys").modules, {"supabase": fake_supabase})


FFPROBE_SAMPLE = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 3840,
            "height": 2160,
            "r_frame_rate": "30/1",
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
        },
    ],
    "format": {
        "duration": "30.0",
        "size": "104857600",
        "bit_rate": "27962026",
    },
}


# ── normalize_codec ───────────────────────────────────────────────────────────

def test_normalize_codec_h264():
    from video_metadata import normalize_codec
    assert normalize_codec("h264") == "H.264"

def test_normalize_codec_hevc():
    from video_metadata import normalize_codec
    assert normalize_codec("hevc") == "H.265"

def test_normalize_codec_h265_alias():
    from video_metadata import normalize_codec
    assert normalize_codec("h265") == "H.265"

def test_normalize_codec_av1():
    from video_metadata import normalize_codec
    assert normalize_codec("av1") == "AV1"

def test_normalize_codec_prores():
    from video_metadata import normalize_codec
    assert normalize_codec("prores") == "ProRes"

def test_normalize_codec_unknown_returns_uppercase():
    from video_metadata import normalize_codec
    assert normalize_codec("vp8") == "VP8"

def test_normalize_codec_empty_returns_none():
    from video_metadata import normalize_codec
    assert normalize_codec("") is None


# ── extract_sequence_number ───────────────────────────────────────────────────

def test_extract_sequence_number_m4e_format():
    from video_metadata import extract_sequence_number
    assert extract_sequence_number("DJI_20260218101500_0015_D.MP4") == 15

def test_extract_sequence_number_mini4pro_format():
    from video_metadata import extract_sequence_number
    assert extract_sequence_number("DJI_0015.MP4") == 15

def test_extract_sequence_number_no_match_returns_zero():
    from video_metadata import extract_sequence_number
    assert extract_sequence_number("RANDOM_0015.MP4") == 0

def test_extract_sequence_number_m4e_zero_padded():
    from video_metadata import extract_sequence_number
    assert extract_sequence_number("DJI_20260218101500_0001_D.MP4") == 1


# ── probe_video ───────────────────────────────────────────────────────────────

def test_probe_video_parses_4k_h264(mock_ffmpeg, tmp_path):
    mock_ffmpeg.return_value.returncode = 0
    mock_ffmpeg.return_value.stdout = json.dumps(FFPROBE_SAMPLE)

    from video_metadata import probe_video
    result = probe_video(str(tmp_path / "DJI_0001.MP4"))

    assert result is not None
    assert result["resolution"] == "3840x2160"
    assert result["width"] == 3840
    assert result["height"] == 2160
    assert result["codec"] == "H.264"
    assert result["fps"] == pytest.approx(30.0)
    assert result["duration_seconds"] == pytest.approx(30.0)
    assert result["file_size_bytes"] == 104857600
    assert result["audio_codec"] == "aac"

def test_probe_video_returns_none_on_ffprobe_failure(mock_ffmpeg):
    mock_ffmpeg.return_value.returncode = 1
    mock_ffmpeg.return_value.stdout = ""
    from video_metadata import probe_video
    assert probe_video("/fake/path.mp4") is None

def test_probe_video_returns_none_on_invalid_json(mock_ffmpeg):
    mock_ffmpeg.return_value.returncode = 0
    mock_ffmpeg.return_value.stdout = "not-json"
    from video_metadata import probe_video
    assert probe_video("/fake/path.mp4") is None

def test_probe_video_returns_none_when_no_video_stream(mock_ffmpeg):
    payload = {"streams": [{"codec_type": "audio", "codec_name": "aac"}], "format": {}}
    mock_ffmpeg.return_value.returncode = 0
    mock_ffmpeg.return_value.stdout = json.dumps(payload)
    from video_metadata import probe_video
    assert probe_video("/fake/path.mp4") is None

def test_probe_video_fractional_fps(mock_ffmpeg):
    payload = {
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 1920,
                      "height": 1080, "r_frame_rate": "60000/1001"}],
        "format": {"duration": "10.0", "size": "1000000", "bit_rate": "800000"},
    }
    mock_ffmpeg.return_value.returncode = 0
    mock_ffmpeg.return_value.stdout = json.dumps(payload)
    from video_metadata import probe_video
    result = probe_video("/fake.mp4")
    assert result["fps"] == pytest.approx(59.94, abs=0.01)


# ── find_graded_file ──────────────────────────────────────────────────────────

def test_find_graded_file_found(tmp_path):
    graded_dir = tmp_path / "video" / "graded"
    graded_dir.mkdir(parents=True)
    graded_file = graded_dir / "DJI_0001_graded.MP4"
    graded_file.write_bytes(b"fake")

    from video_metadata import find_graded_file
    result = find_graded_file(str(tmp_path), "DJI_0001.MP4")
    assert result == str(graded_file)

def test_find_graded_file_not_found(tmp_path):
    from video_metadata import find_graded_file
    assert find_graded_file(str(tmp_path), "DJI_0001.MP4") is None


# ── check_lrf_proxy ───────────────────────────────────────────────────────────

def test_check_lrf_proxy_found_in_full_dir(tmp_path):
    full_dir = tmp_path / "video" / "full"
    full_dir.mkdir(parents=True)
    (full_dir / "DJI_0001.LRF").write_bytes(b"")
    from video_metadata import check_lrf_proxy
    assert check_lrf_proxy(str(tmp_path), "DJI_0001.MP4") is True

def test_check_lrf_proxy_not_found(tmp_path):
    from video_metadata import check_lrf_proxy
    assert check_lrf_proxy(str(tmp_path), "DJI_0001.MP4") is False


# ── upload_metadata ───────────────────────────────────────────────────────────

def test_upload_metadata_update_branch(mock_supabase_client, mocker):
    """When filename exists in video_assets, triggers update path."""
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key")
    # Configure select to return existing record
    mock_supabase_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "existing-id", "filename": "DJI_0001.MP4"}
    ]

    metadata = [{
        "filename": "DJI_0001.MP4", "status": "ok",
        "file_size_bytes": 1000, "resolution": "3840x2160",
        "codec": "H.264", "color_profile": "d_log_m",
        "has_lrf_proxy": False, "graded_path": None, "fps": 30.0,
    }]
    from video_metadata import upload_metadata
    updated, inserted = upload_metadata(metadata, "mission-uuid")
    assert updated == 1
    assert inserted == 0

def test_upload_metadata_insert_branch(mock_supabase_client, mocker):
    """When filename does NOT exist in video_assets, triggers insert path."""
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key")
    # Conftest default: data = [] (no existing records)

    metadata = [{
        "filename": "DJI_0001.MP4", "status": "ok",
        "file_size_bytes": 1000, "resolution": "3840x2160",
        "codec": "H.264", "color_profile": "d_log_m",
        "has_lrf_proxy": False, "graded_path": None, "fps": 30.0,
        "duration_seconds": 30.0,
    }]
    from video_metadata import upload_metadata
    updated, inserted = upload_metadata(metadata, "mission-uuid")
    assert updated == 0
    assert inserted == 1

def test_upload_metadata_skips_failed_records(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key")

    metadata = [{"filename": "DJI_0001.MP4", "status": "probe_failed"}]
    from video_metadata import upload_metadata
    updated, inserted = upload_metadata(metadata, "mission-uuid")
    assert updated == 0
    assert inserted == 0

def test_upload_metadata_raises_when_env_not_set(mocker):
    mocker.patch("pipeline_utils.SUPABASE_URL", "")
    mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "")
    from video_metadata import upload_metadata
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        upload_metadata([], "mission-uuid")
