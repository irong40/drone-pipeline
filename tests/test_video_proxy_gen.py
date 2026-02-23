"""
Unit tests for video_proxy_gen.py — proxy source discovery, graded/full fallback,
FFmpeg proxy command construction, resolution validation. UNIT-08.
"""
import pytest


# ── find_source_videos ────────────────────────────────────────────────────────

def test_find_source_videos_prefers_graded(tmp_path):
    graded_dir = tmp_path / "video" / "graded"
    graded_dir.mkdir(parents=True)
    (graded_dir / "DJI_0001_graded.MP4").write_bytes(b"fake")
    full_dir = tmp_path / "video" / "full"
    full_dir.mkdir(parents=True)
    (full_dir / "DJI_0001.MP4").write_bytes(b"fake")

    from video_proxy_gen import find_source_videos
    videos, source = find_source_videos(str(tmp_path))
    assert "graded" in source
    assert len(videos) == 1
    assert "graded" in videos[0]

def test_find_source_videos_falls_back_to_full_when_graded_empty(tmp_path):
    graded_dir = tmp_path / "video" / "graded"
    graded_dir.mkdir(parents=True)  # Empty — no video files
    full_dir = tmp_path / "video" / "full"
    full_dir.mkdir(parents=True)
    (full_dir / "DJI_0001.MP4").write_bytes(b"fake")

    from video_proxy_gen import find_source_videos
    videos, source = find_source_videos(str(tmp_path))
    assert "full" in source
    assert len(videos) == 1

def test_find_source_videos_returns_empty_when_no_dirs(tmp_path):
    from video_proxy_gen import find_source_videos
    videos, source = find_source_videos(str(tmp_path))
    assert videos == []
    assert source is None

def test_find_source_videos_falls_back_when_graded_dir_missing(tmp_path):
    full_dir = tmp_path / "video" / "full"
    full_dir.mkdir(parents=True)
    (full_dir / "DJI_0001.MP4").write_bytes(b"fake")

    from video_proxy_gen import find_source_videos
    videos, source = find_source_videos(str(tmp_path))
    assert "full" in source

def test_find_source_videos_multiple_files_sorted(tmp_path):
    graded_dir = tmp_path / "video" / "graded"
    graded_dir.mkdir(parents=True)
    (graded_dir / "DJI_0003_graded.MP4").write_bytes(b"fake")
    (graded_dir / "DJI_0001_graded.MP4").write_bytes(b"fake")
    (graded_dir / "DJI_0002_graded.MP4").write_bytes(b"fake")

    from video_proxy_gen import find_source_videos
    videos, _ = find_source_videos(str(tmp_path))
    assert len(videos) == 3
    assert videos[0] < videos[1] < videos[2]  # sorted


# ── generate_proxy ────────────────────────────────────────────────────────────

def test_generate_proxy_builds_correct_command(mock_ffmpeg, tmp_path):
    input_path = str(tmp_path / "DJI_0001_graded.MP4")
    output_path = str(tmp_path / "DJI_0001_proxy.MP4")

    from video_proxy_gen import generate_proxy
    ok, stderr = generate_proxy(input_path, output_path, resolution="1920x1080")

    assert ok is True
    cmd = mock_ffmpeg.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-i" in cmd
    assert cmd[cmd.index("-i") + 1] == input_path
    assert "-vf" in cmd
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert "scale=1920:1080" in vf_arg
    assert "force_original_aspect_ratio=decrease" in vf_arg
    assert "pad=1920:1080" in vf_arg
    assert "-c:v" in cmd
    assert "libx264" in cmd
    assert "-preset" in cmd
    assert "-crf" in cmd
    assert "23" in cmd
    assert "-c:a" in cmd
    assert "copy" in cmd
    assert cmd[-1] == output_path

def test_generate_proxy_returns_false_on_ffmpeg_failure(mock_ffmpeg, tmp_path):
    mock_ffmpeg.return_value.returncode = 1
    mock_ffmpeg.return_value.stderr = "encode error"

    from video_proxy_gen import generate_proxy
    ok, stderr = generate_proxy("/in.mp4", "/out.mp4")
    assert ok is False
    assert stderr == "encode error"

def test_generate_proxy_raises_on_invalid_resolution(mock_ffmpeg):
    from video_proxy_gen import generate_proxy
    with pytest.raises(ValueError, match="Invalid resolution"):
        generate_proxy("/in.mp4", "/out.mp4", resolution="../../etc/passwd")

def test_generate_proxy_raises_on_resolution_with_letters(mock_ffmpeg):
    from video_proxy_gen import generate_proxy
    with pytest.raises(ValueError, match="Invalid resolution"):
        generate_proxy("/in.mp4", "/out.mp4", resolution="1920xHD")

def test_generate_proxy_custom_params(mock_ffmpeg, tmp_path):
    from video_proxy_gen import generate_proxy
    generate_proxy("/in.mp4", "/out.mp4", resolution="1280x720", crf=28, preset="ultrafast")

    cmd = mock_ffmpeg.call_args[0][0]
    assert "scale=1280:720" in cmd[cmd.index("-vf") + 1]
    assert "28" in cmd
    assert "ultrafast" in cmd
