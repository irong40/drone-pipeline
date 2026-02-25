"""
Integration test: video pipeline flow — color grading (V1) through proxy
generation (V4) against a real mission folder with mocked FFmpeg. INTG-02.

FFmpeg subprocess calls mocked; all directory and checkpoint I/O is real.
"""
import os
import sys
import types
import subprocess
import pytest
from unittest.mock import MagicMock
from pathlib import Path

from checkpoint import load_checkpoint, save_checkpoint


# ── Supabase sys.modules stub ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def stub_supabase_module(mocker):
    if "supabase" not in sys.modules:
        fake_supabase = types.ModuleType("supabase")
        fake_supabase.create_client = MagicMock()
        mocker.patch.dict(sys.modules, {"supabase": fake_supabase})


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def mission_folder(tmp_path):
    """Standard mission folder structure with video files."""
    mission = tmp_path / "SAI_M0047_re_standard_20260218"
    (mission / "video" / "full").mkdir(parents=True)
    (mission / "video" / "graded").mkdir(parents=True)
    (mission / "video" / "proxy").mkdir(parents=True)
    (mission / "LUTs").mkdir(parents=True)

    # Fake video files
    (mission / "video" / "full" / "DJI_0001.MP4").write_bytes(b"\x00" * 100)
    (mission / "video" / "full" / "DJI_0002.MP4").write_bytes(b"\x00" * 100)

    # Fake LUT file
    (mission / "LUTs" / "Sentinel_DCinelike.cube").write_bytes(b"LUT_3D_SIZE 33\n")

    return mission


@pytest.fixture
def mock_ffmpeg_success(mocker):
    """Mock subprocess.run so FFmpeg writes fake output to the last cmd arg."""
    def side_effect(cmd, *args, **kwargs):
        # The last argument is the output path
        output_path = cmd[-1] if isinstance(cmd, list) else None
        if output_path and not output_path.startswith("-"):
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(b"\x00" * 50)  # Fake output
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    return mocker.patch("subprocess.run", side_effect=side_effect)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_color_grade_creates_graded_files(mission_folder, mock_ffmpeg_success):
    """Grade loop creates output files and writes checkpoint."""
    from video_color_grade import get_lut_path, find_videos, grade_video

    lut_path = get_lut_path("mini4pro", lut_dir=str(mission_folder / "LUTs"))
    assert lut_path is not None

    videos = find_videos(str(mission_folder))
    assert len(videos) == 2

    completed = set()
    graded_dir = mission_folder / "video" / "graded"
    SCRIPT_NAME = "video_color_grade"

    for video_path in videos:
        filename = os.path.basename(video_path)
        name, ext = os.path.splitext(filename)
        output_path = str(graded_dir / f"{name}_graded{ext}")

        ok, stderr = grade_video(video_path, output_path, lut_path, lut_dir=str(mission_folder / "LUTs"))
        assert ok is True
        assert os.path.isfile(output_path)
        completed.add(video_path)

    save_checkpoint(str(mission_folder), SCRIPT_NAME, completed)

    # Verify checkpoint written
    ckpt = load_checkpoint(str(mission_folder), SCRIPT_NAME)
    assert len(ckpt) == 2

    # Verify graded files exist
    graded_files = list(graded_dir.glob("*_graded.MP4"))
    assert len(graded_files) == 2


def test_color_grade_checkpoint_skips_completed(mission_folder, mock_ffmpeg_success):
    """Pre-populated checkpoint causes only new files to be processed."""
    from video_color_grade import find_videos, grade_video

    videos = find_videos(str(mission_folder))
    SCRIPT_NAME = "video_color_grade"

    # Pre-populate checkpoint with first file
    save_checkpoint(str(mission_folder), SCRIPT_NAME, {videos[0]})

    completed = load_checkpoint(str(mission_folder), SCRIPT_NAME)
    processed_count = 0

    for video_path in videos:
        if video_path in completed:
            continue
        name, ext = os.path.splitext(os.path.basename(video_path))
        output_path = str(mission_folder / "video" / "graded" / f"{name}_graded{ext}")
        lut_file = mission_folder / "LUTs" / "fake_lut.cube"
        lut_file.write_bytes(b"")
        grade_video(video_path, output_path, str(lut_file), lut_dir=str(mission_folder / "LUTs"))
        processed_count += 1

    assert processed_count == 1  # Only DJI_0002 processed
    assert mock_ffmpeg_success.call_count == 1


def test_proxy_generation_runs_after_grading(mission_folder, mock_ffmpeg_success):
    """Proxy generation creates proxy files from graded directory."""
    from video_proxy_gen import find_source_videos, generate_proxy

    # Pre-populate graded files
    graded_dir = mission_folder / "video" / "graded"
    (graded_dir / "DJI_0001_graded.MP4").write_bytes(b"\x00" * 80)
    (graded_dir / "DJI_0002_graded.MP4").write_bytes(b"\x00" * 80)

    videos, source_dir = find_source_videos(str(mission_folder))
    assert len(videos) == 2
    assert "graded" in source_dir

    proxy_dir = mission_folder / "video" / "proxy"
    for video_path in videos:
        filename = os.path.basename(video_path)
        name, ext = os.path.splitext(filename)
        clean_name = name.replace("_graded", "")
        output_path = str(proxy_dir / f"{clean_name}_proxy{ext}")

        ok, stderr = generate_proxy(video_path, output_path)
        assert ok is True
        assert os.path.isfile(output_path)

    proxy_files = list(proxy_dir.glob("*_proxy.MP4"))
    assert len(proxy_files) == 2


def test_video_pipeline_no_videos_exits_cleanly(mission_folder, mock_ffmpeg_success):
    """Empty video/full/ means no processing and no subprocess calls."""
    from video_color_grade import find_videos

    # Remove all videos from full/
    for f in (mission_folder / "video" / "full").iterdir():
        f.unlink()

    videos = find_videos(str(mission_folder))
    assert videos == []
    mock_ffmpeg_success.assert_not_called()
