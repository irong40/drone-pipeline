"""
Unit tests for video_format_export.py — build_ffmpeg_command (copy-codec path,
re-encode path, truncation, resolution validation), get_video_duration,
find_master_video, fetch_formats_from_supabase. UNIT-09.
"""
import json
import pytest


# ── build_ffmpeg_command — copy codec ─────────────────────────────────────────

def test_build_ffmpeg_command_copy_codec_no_scale_filter():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "client_4k", "resolution": "3840x2160", "codec": "copy"}
    cmd = build_ffmpeg_command("/input/master.mp4", "/output/master_client_4k.mp4", fmt)
    assert "-c:v" in cmd
    assert "copy" in cmd
    # No vf scale filter for copy codec
    assert "-vf" not in cmd

def test_build_ffmpeg_command_copy_codec_audio_copy():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "client_4k", "resolution": "3840x2160", "codec": "copy"}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)
    # Verify both -c:v copy and -c:a copy
    copy_indices = [i for i, v in enumerate(cmd) if v == "copy"]
    assert len(copy_indices) == 2  # video and audio


# ── build_ffmpeg_command — re-encode ──────────────────────────────────────────

def test_build_ffmpeg_command_libx264_includes_required_args():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "web_preview", "resolution": "1920x1080", "fps": 30, "codec": "libx264"}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)
    assert "-vf" in cmd
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert "scale=1920:1080" in vf_arg
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "-crf" in cmd
    assert "18" in cmd
    assert "-preset" in cmd
    assert "medium" in cmd
    assert "-r" in cmd
    assert "30" in cmd
    assert "-c:a" in cmd
    assert "aac" in cmd
    assert "-b:a" in cmd
    assert "192k" in cmd

def test_build_ffmpeg_command_libx265_includes_crf_preset():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "youtube", "resolution": "3840x2160", "fps": 30, "codec": "libx265"}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)
    assert "libx265" in cmd
    assert "-crf" in cmd
    assert "18" in cmd
    assert "-preset" in cmd
    assert "medium" in cmd

def test_build_ffmpeg_command_scale_filter_has_pad():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "instagram_reels", "resolution": "1080x1920", "fps": 30, "codec": "libx264"}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf_arg
    assert "pad=1080:1920" in vf_arg


# ── build_ffmpeg_command — truncation ─────────────────────────────────────────

def test_build_ffmpeg_command_truncation_applied_when_over_limit():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "instagram_reels", "resolution": "1080x1920", "fps": 30,
           "codec": "libx264", "max_duration_sec": 90}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt, source_duration=120.0)
    assert "-t" in cmd
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "90"

def test_build_ffmpeg_command_no_truncation_when_under_limit():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "instagram_reels", "resolution": "1080x1920", "fps": 30,
           "codec": "libx264", "max_duration_sec": 90}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt, source_duration=60.0)
    assert "-t" not in cmd

def test_build_ffmpeg_command_no_truncation_when_equal_to_limit():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "tiktok", "resolution": "1080x1920", "fps": 30,
           "codec": "libx264", "max_duration_sec": 180}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt, source_duration=180.0)
    assert "-t" not in cmd

def test_build_ffmpeg_command_no_truncation_when_duration_not_provided():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "instagram_reels", "resolution": "1080x1920", "fps": 30,
           "codec": "libx264", "max_duration_sec": 90}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt, source_duration=None)
    assert "-t" not in cmd


# ── build_ffmpeg_command — resolution validation ──────────────────────────────

def test_build_ffmpeg_command_invalid_resolution_raises():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "evil", "resolution": "../../etc/passwd", "codec": "libx264"}
    with pytest.raises(ValueError, match="Invalid resolution"):
        build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)

def test_build_ffmpeg_command_resolution_with_letters_raises():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "bad", "resolution": "1920xHD", "codec": "libx264"}
    with pytest.raises(ValueError, match="Invalid resolution"):
        build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)

def test_build_ffmpeg_command_output_path_is_last_arg():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "web", "resolution": "1920x1080", "fps": 30, "codec": "libx264"}
    cmd = build_ffmpeg_command("/in.mp4", "/out/file.mp4", fmt)
    assert cmd[-1] == "/out/file.mp4"

def test_build_ffmpeg_command_starts_with_ffmpeg_y_i():
    from video_format_export import build_ffmpeg_command
    fmt = {"name": "web", "resolution": "1920x1080", "fps": 30, "codec": "libx264"}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-i" in cmd


# ── get_video_duration ────────────────────────────────────────────────────────

def test_get_video_duration_parses_ffprobe_output(mock_ffmpeg):
    mock_ffmpeg.return_value.stdout = json.dumps({"format": {"duration": "30.5"}})
    from video_format_export import get_video_duration
    assert get_video_duration("/fake/video.mp4") == pytest.approx(30.5)

def test_get_video_duration_returns_zero_on_invalid_json(mock_ffmpeg):
    mock_ffmpeg.return_value.stdout = "not-json"
    from video_format_export import get_video_duration
    assert get_video_duration("/fake.mp4") == pytest.approx(0.0)

def test_get_video_duration_returns_zero_on_missing_duration_key(mock_ffmpeg):
    mock_ffmpeg.return_value.stdout = json.dumps({"format": {}})
    from video_format_export import get_video_duration
    # float({}) raises — returns 0.0 from except
    assert get_video_duration("/fake.mp4") == pytest.approx(0.0)


# ── find_master_video ─────────────────────────────────────────────────────────

def test_find_master_video_found(tmp_path):
    master_dir = tmp_path / "video" / "master"
    master_dir.mkdir(parents=True)
    master_file = master_dir / "SAI_M0047_edit.mp4"
    master_file.write_bytes(b"fake")

    from video_format_export import find_master_video
    result = find_master_video(str(tmp_path))
    assert result == str(master_file)

def test_find_master_video_not_found_no_dir(tmp_path):
    from video_format_export import find_master_video
    assert find_master_video(str(tmp_path)) is None

def test_find_master_video_not_found_empty_dir(tmp_path):
    master_dir = tmp_path / "video" / "master"
    master_dir.mkdir(parents=True)
    from video_format_export import find_master_video
    assert find_master_video(str(tmp_path)) is None


# ── fetch_formats_from_supabase ───────────────────────────────────────────────

def test_fetch_formats_from_supabase_returns_none_when_env_not_set(mocker):
    mocker.patch("pipeline_utils.SUPABASE_URL", "")
    mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "")
    mocker.patch("video_format_export.get_supabase_client", return_value=None)
    from video_format_export import fetch_formats_from_supabase
    assert fetch_formats_from_supabase("mission-uuid") is None

def test_fetch_formats_from_supabase_returns_none_when_mission_not_found(mock_supabase_client, mocker):
    import types
    stub_supabase = types.ModuleType("supabase")
    stub_supabase.create_client = lambda url, key: mock_supabase_client
    mocker.patch.dict("sys.modules", {"supabase": stub_supabase})
    mocker.patch("pipeline_utils.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("pipeline_utils.SUPABASE_SERVICE_KEY", "test-key")
    # .single().execute().data = None -> no mission found
    (mock_supabase_client.table.return_value.select.return_value
     .eq.return_value.single.return_value.execute.return_value.data) = None

    from video_format_export import fetch_formats_from_supabase
    assert fetch_formats_from_supabase("nonexistent-uuid") is None


# ── DEFAULT_FORMATS completeness ──────────────────────────────────────────────

def test_default_formats_contains_required_platforms():
    from video_format_export import DEFAULT_FORMATS
    names = {f["name"] for f in DEFAULT_FORMATS}
    assert "instagram_reels" in names
    assert "youtube" in names
    assert "tiktok" in names
    assert "client_4k" in names

def test_default_formats_all_have_name_resolution_codec():
    from video_format_export import DEFAULT_FORMATS
    for fmt in DEFAULT_FORMATS:
        assert "name" in fmt
        assert "resolution" in fmt or fmt.get("codec") == "copy"
        assert "codec" in fmt
