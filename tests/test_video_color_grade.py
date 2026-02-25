"""
Unit tests for video_color_grade.py — LUT selection, FFmpeg command construction,
graded_path Supabase upsert. UNIT-04.
"""
import os
import types
import pytest
from unittest.mock import MagicMock, call


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


# ── get_lut_path ──────────────────────────────────────────────────────────────

def test_get_lut_path_m4e(tmp_path):
    lut_file = tmp_path / "Sentinel_DLogM.cube"
    lut_file.write_bytes(b"")
    from video_color_grade import get_lut_path
    assert get_lut_path("m4e", lut_dir=str(tmp_path)) == str(lut_file)

def test_get_lut_path_m3e_same_lut_as_m4e(tmp_path):
    lut_file = tmp_path / "Sentinel_DLogM.cube"
    lut_file.write_bytes(b"")
    from video_color_grade import get_lut_path
    assert get_lut_path("m3e", lut_dir=str(tmp_path)) == str(lut_file)

def test_get_lut_path_mini4pro(tmp_path):
    lut_file = tmp_path / "Sentinel_DCinelike.cube"
    lut_file.write_bytes(b"")
    from video_color_grade import get_lut_path
    assert get_lut_path("mini4pro", lut_dir=str(tmp_path)) == str(lut_file)

def test_get_lut_path_unknown_platform_returns_none(tmp_path):
    from video_color_grade import get_lut_path
    assert get_lut_path("phantom4", lut_dir=str(tmp_path)) is None

def test_get_lut_path_file_missing_returns_none(tmp_path):
    # Platform valid but LUT file not on disk
    from video_color_grade import get_lut_path
    assert get_lut_path("m4e", lut_dir=str(tmp_path)) is None

def test_get_lut_path_override_absolute(tmp_path):
    custom = tmp_path / "custom.cube"
    custom.write_bytes(b"")
    from video_color_grade import get_lut_path
    assert get_lut_path("mini4pro", lut_override=str(custom), lut_dir=str(tmp_path)) == str(custom)

def test_get_lut_path_override_relative_resolves_in_lut_dir(tmp_path):
    custom = tmp_path / "custom.cube"
    custom.write_bytes(b"")
    from video_color_grade import get_lut_path
    result = get_lut_path("mini4pro", lut_override="custom.cube", lut_dir=str(tmp_path))
    assert result == str(custom)

def test_get_lut_path_override_missing_returns_none(tmp_path):
    from video_color_grade import get_lut_path
    assert get_lut_path("mini4pro", lut_override="nonexistent.cube", lut_dir=str(tmp_path)) is None


# ── grade_video ───────────────────────────────────────────────────────────────

def test_grade_video_builds_correct_command(mock_ffmpeg, tmp_path):
    lut_file = tmp_path / "Sentinel_DLogM.cube"
    lut_file.write_bytes(b"")
    input_path = str(tmp_path / "DJI_0001.MP4")
    output_path = str(tmp_path / "DJI_0001_graded.MP4")

    from video_color_grade import grade_video
    ok, stderr = grade_video(input_path, output_path, str(lut_file), lut_dir=str(tmp_path))

    assert ok is True
    assert stderr == ""
    cmd = mock_ffmpeg.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-i" in cmd
    assert cmd[cmd.index("-i") + 1] == input_path
    assert "-vf" in cmd
    vf_idx = cmd.index("-vf")
    assert "lut3d=" in cmd[vf_idx + 1]
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "-crf" in cmd
    assert "18" in cmd
    assert "-c:a" in cmd
    assert "copy" in cmd
    assert cmd[-1] == output_path

def test_grade_video_lut_path_escaped_for_ffmpeg(mock_ffmpeg, tmp_path):
    # LUT path escape: backslashes -> forward slashes, colons -> \:
    lut_file = tmp_path / "Sentinel_DLogM.cube"
    lut_file.write_bytes(b"")
    input_path = str(tmp_path / "DJI_0001.MP4")
    output_path = str(tmp_path / "DJI_0001_graded.MP4")

    from video_color_grade import grade_video
    grade_video(input_path, output_path, str(lut_file), lut_dir=str(tmp_path))

    cmd = mock_ffmpeg.call_args[0][0]
    vf_idx = cmd.index("-vf")
    vf_arg = cmd[vf_idx + 1]
    expected_escaped = str(lut_file).replace("\\", "/").replace(":", "\\:")
    assert f"lut3d='{expected_escaped}'" in vf_arg

def test_grade_video_returns_false_on_ffmpeg_failure(mock_ffmpeg, tmp_path):
    mock_ffmpeg.return_value.returncode = 1
    mock_ffmpeg.return_value.stderr = "FFmpeg error"
    lut_file = tmp_path / "lut.cube"
    lut_file.write_bytes(b"")

    from video_color_grade import grade_video
    ok, stderr = grade_video("/input.mp4", "/output.mp4", str(lut_file), lut_dir=str(tmp_path))
    assert ok is False
    assert stderr == "FFmpeg error"

def test_grade_video_custom_crf_and_codec(mock_ffmpeg, tmp_path):
    lut_file = tmp_path / "lut.cube"
    lut_file.write_bytes(b"")

    from video_color_grade import grade_video
    grade_video("/input.mp4", "/output.mp4", str(lut_file), crf=23, codec="libx265", lut_dir=str(tmp_path))

    cmd = mock_ffmpeg.call_args[0][0]
    assert "23" in cmd
    assert "libx265" in cmd


# ── update_graded_path ────────────────────────────────────────────────────────

def test_update_graded_path_calls_upsert_with_correct_payload(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("video_color_grade.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("video_color_grade.SUPABASE_SERVICE_KEY", "test-key")

    from video_color_grade import update_graded_path
    result = update_graded_path("mission-uuid", "DJI_0001.MP4", "/path/to/graded.MP4")

    assert result is True
    mock_supabase_client.table.assert_called_with("video_assets")
    upsert_call = mock_supabase_client.table.return_value.upsert.call_args
    payload = upsert_call[0][0]
    assert payload["mission_id"] == "mission-uuid"
    assert payload["filename"] == "DJI_0001.MP4"
    assert payload["graded_path"] == "/path/to/graded.MP4"
    kwargs = upsert_call[1]
    assert kwargs.get("on_conflict") == "mission_id,filename"

def test_update_graded_path_returns_false_when_env_not_set(mocker):
    mocker.patch("video_color_grade.SUPABASE_URL", "")
    mocker.patch("video_color_grade.SUPABASE_SERVICE_KEY", "")
    from video_color_grade import update_graded_path
    assert update_graded_path("uuid", "file.mp4", "/path") is False

def test_update_graded_path_returns_false_on_supabase_exception(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("video_color_grade.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("video_color_grade.SUPABASE_SERVICE_KEY", "test-key")
    mock_supabase_client.table.return_value.upsert.return_value.execute.side_effect = Exception("DB error")

    from video_color_grade import update_graded_path
    result = update_graded_path("uuid", "file.mp4", "/graded.mp4")
    assert result is False
