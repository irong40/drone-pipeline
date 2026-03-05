"""
Unit tests for mipmap_launcher.py -- fire-and-forget MipMap subprocess launcher
with orphan detection and pipeline contract compliance. MPC-01, MPC-02, TST-01.
"""
import json
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, mock_open, ANY


# ── Supabase sys.modules stub (supabase not installed in CI) ────────────────

@pytest.fixture(autouse=True)
def stub_supabase_module(mocker):
    """Inject fake 'supabase' module so imports work without the real package."""
    if "supabase" not in sys.modules:
        fake_supabase = types.ModuleType("supabase")
        fake_supabase.create_client = MagicMock()
        mocker.patch.dict(sys.modules, {"supabase": fake_supabase})


@pytest.fixture(autouse=True)
def stub_psutil_module(mocker):
    """Inject fake 'psutil' module so imports work without the real package."""
    fake_psutil = types.ModuleType("psutil")
    fake_psutil.pid_exists = MagicMock(return_value=False)
    fake_process = MagicMock()
    fake_process.return_value.name.return_value = "reconstruct_full_engine.exe"
    fake_process.return_value.status.return_value = "running"
    fake_psutil.Process = fake_process
    fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
    fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
    mocker.patch.dict(sys.modules, {"psutil": fake_psutil})


@pytest.fixture(autouse=True)
def patch_setup_logging(mocker):
    """Prevent real log file creation during tests."""
    mock_logger = MagicMock()
    mocker.patch("pipeline_utils.setup_logging", return_value=mock_logger)


# ── launch_mipmap tests ─────────────────────────────────────────────────────

def test_launch_writes_pid_file(mocker, tmp_path):
    """launch_mipmap creates PID file with {pid, started_at, project} JSON."""
    mock_popen = MagicMock()
    mock_popen.pid = 12345
    mocker.patch("subprocess.Popen", return_value=mock_popen)

    from mipmap_launcher import launch_mipmap

    engine_path = tmp_path / "reconstruct_full_engine.exe"
    engine_path.write_bytes(b"fake")
    pid_file = tmp_path / "mipmap.pid"
    log_file = tmp_path / "mipmap.log"

    result = launch_mipmap(
        engine_path=str(engine_path),
        workspace=str(tmp_path),
        mission_id="test-mission",
        pid_file_path=str(pid_file),
        log_file_path=str(log_file),
    )

    assert pid_file.exists()
    pid_data = json.loads(pid_file.read_text())
    assert pid_data["pid"] == 12345
    assert "started_at" in pid_data
    assert pid_data["project"] == "test-mission"


def test_launch_redirects_stdout_to_log(mocker, tmp_path):
    """Popen called with stdout=file_handle, stderr=STDOUT."""
    import subprocess as sp

    mock_popen = MagicMock()
    mock_popen.pid = 99
    popen_cls = mocker.patch("subprocess.Popen", return_value=mock_popen)

    from mipmap_launcher import launch_mipmap

    engine_path = tmp_path / "reconstruct_full_engine.exe"
    engine_path.write_bytes(b"fake")
    pid_file = tmp_path / "mipmap.pid"
    log_file = tmp_path / "mipmap.log"

    launch_mipmap(
        engine_path=str(engine_path),
        workspace=str(tmp_path),
        mission_id="test-mission",
        pid_file_path=str(pid_file),
        log_file_path=str(log_file),
    )

    call_kwargs = popen_cls.call_args
    # stdout should be a file handle (not None, not PIPE)
    assert call_kwargs.kwargs.get("stdout") is not None or call_kwargs[1].get("stdout") is not None
    # stderr should be subprocess.STDOUT
    kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
    assert kw.get("stderr") == sp.STDOUT


def test_launch_returns_json_with_pid(mocker, tmp_path):
    """Returns dict with status='launched', pid, log_file."""
    mock_popen = MagicMock()
    mock_popen.pid = 42
    mocker.patch("subprocess.Popen", return_value=mock_popen)

    from mipmap_launcher import launch_mipmap

    engine_path = tmp_path / "reconstruct_full_engine.exe"
    engine_path.write_bytes(b"fake")
    pid_file = tmp_path / "mipmap.pid"
    log_file = tmp_path / "mipmap.log"

    result = launch_mipmap(
        engine_path=str(engine_path),
        workspace=str(tmp_path),
        mission_id="test-mission",
        pid_file_path=str(pid_file),
        log_file_path=str(log_file),
    )

    assert result["status"] == "launched"
    assert result["pid"] == 42
    assert "log_file" in result


def test_launch_does_not_use_shell_true(mocker, tmp_path):
    """Popen called without shell=True (critical for PID accuracy)."""
    mock_popen = MagicMock()
    mock_popen.pid = 55
    popen_cls = mocker.patch("subprocess.Popen", return_value=mock_popen)

    from mipmap_launcher import launch_mipmap

    engine_path = tmp_path / "reconstruct_full_engine.exe"
    engine_path.write_bytes(b"fake")
    pid_file = tmp_path / "mipmap.pid"
    log_file = tmp_path / "mipmap.log"

    launch_mipmap(
        engine_path=str(engine_path),
        workspace=str(tmp_path),
        mission_id="test-mission",
        pid_file_path=str(pid_file),
        log_file_path=str(log_file),
    )

    kw = popen_cls.call_args.kwargs if popen_cls.call_args.kwargs else popen_cls.call_args[1]
    # shell should either not be present or be False
    assert kw.get("shell", False) is False


# ── check_orphan tests ──────────────────────────────────────────────────────

def test_check_orphan_no_pid_file(tmp_path):
    """Returns False when no PID file exists."""
    from mipmap_launcher import check_orphan

    result = check_orphan(str(tmp_path / "nonexistent.pid"))
    assert result is False


def test_check_orphan_stale_pid(mocker, tmp_path):
    """Returns False and cleans up PID file when process is dead."""
    import psutil
    mocker.patch.object(psutil, "pid_exists", return_value=False)

    pid_file = tmp_path / "mipmap.pid"
    pid_file.write_text(json.dumps({"pid": 99999, "started_at": "2026-01-01T00:00:00Z", "project": "test"}))

    from mipmap_launcher import check_orphan

    result = check_orphan(str(pid_file))
    assert result is False
    assert not pid_file.exists()  # cleaned up


def test_check_orphan_recycled_pid(mocker, tmp_path):
    """Returns False and cleans up when PID exists but is different process."""
    import psutil
    mocker.patch.object(psutil, "pid_exists", return_value=True)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "chrome.exe"  # not MipMap
    mocker.patch.object(psutil, "Process", return_value=mock_proc)

    pid_file = tmp_path / "mipmap.pid"
    pid_file.write_text(json.dumps({"pid": 1234, "started_at": "2026-01-01T00:00:00Z", "project": "test"}))

    from mipmap_launcher import check_orphan

    result = check_orphan(str(pid_file))
    assert result is False
    assert not pid_file.exists()  # cleaned up


def test_check_orphan_active_mipmap(mocker, tmp_path):
    """Returns True when PID matches running reconstruct_full_engine.exe."""
    import psutil
    mocker.patch.object(psutil, "pid_exists", return_value=True)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "reconstruct_full_engine.exe"
    mock_proc.status.return_value = "running"
    mocker.patch.object(psutil, "Process", return_value=mock_proc)

    pid_file = tmp_path / "mipmap.pid"
    pid_file.write_text(json.dumps({"pid": 5678, "started_at": "2026-01-01T00:00:00Z", "project": "test"}))

    from mipmap_launcher import check_orphan

    result = check_orphan(str(pid_file))
    assert result is True
    assert pid_file.exists()  # NOT cleaned up


# ── main() tests ────────────────────────────────────────────────────────────

def test_main_exit_0_on_success(mocker, tmp_path):
    """main() exits 0 after successful launch."""
    mock_popen = MagicMock()
    mock_popen.pid = 100
    mocker.patch("subprocess.Popen", return_value=mock_popen)

    import psutil
    mocker.patch.object(psutil, "pid_exists", return_value=False)

    engine = tmp_path / "reconstruct_full_engine.exe"
    engine.write_bytes(b"fake")

    mocker.patch("sys.argv", [
        "mipmap_launcher.py",
        "--mission-id", "m123",
        "--mission-path", str(tmp_path),
        "--engine-path", str(engine),
        "--workspace", str(tmp_path),
    ])

    from mipmap_launcher import main
    # Should not raise SystemExit or should exit with 0
    try:
        main()
    except SystemExit as e:
        assert e.code == 0 or e.code is None


def test_main_exit_1_on_orphan(mocker, tmp_path):
    """main() exits 1 when orphan detected."""
    import psutil
    mocker.patch.object(psutil, "pid_exists", return_value=True)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "reconstruct_full_engine.exe"
    mock_proc.status.return_value = "running"
    mocker.patch.object(psutil, "Process", return_value=mock_proc)

    engine = tmp_path / "reconstruct_full_engine.exe"
    engine.write_bytes(b"fake")

    # Create existing PID file to trigger orphan detection
    pid_dir = tmp_path / ".pipeline"
    pid_dir.mkdir()
    pid_file = pid_dir / "mipmap.pid"
    pid_file.write_text(json.dumps({"pid": 999, "started_at": "2026-01-01T00:00:00Z", "project": "old"}))

    mocker.patch("sys.argv", [
        "mipmap_launcher.py",
        "--mission-id", "m123",
        "--mission-path", str(tmp_path),
        "--engine-path", str(engine),
        "--workspace", str(tmp_path),
    ])

    from mipmap_launcher import main
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_exit_2_missing_engine(mocker, tmp_path):
    """main() exits 2 when engine path does not exist."""
    mocker.patch("sys.argv", [
        "mipmap_launcher.py",
        "--mission-id", "m123",
        "--mission-path", str(tmp_path),
        "--engine-path", str(tmp_path / "nonexistent.exe"),
        "--workspace", str(tmp_path),
    ])

    from mipmap_launcher import main
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2


def test_main_prints_json_stdout(mocker, tmp_path, capsys):
    """main() prints valid JSON as last stdout line."""
    mock_popen = MagicMock()
    mock_popen.pid = 200
    mocker.patch("subprocess.Popen", return_value=mock_popen)

    import psutil
    mocker.patch.object(psutil, "pid_exists", return_value=False)

    engine = tmp_path / "reconstruct_full_engine.exe"
    engine.write_bytes(b"fake")

    mocker.patch("sys.argv", [
        "mipmap_launcher.py",
        "--mission-id", "m123",
        "--mission-path", str(tmp_path),
        "--engine-path", str(engine),
        "--workspace", str(tmp_path),
    ])

    from mipmap_launcher import main
    try:
        main()
    except SystemExit:
        pass

    captured = capsys.readouterr()
    # Find last non-empty line of stdout
    lines = [l for l in captured.out.strip().split("\n") if l.strip()]
    assert len(lines) > 0
    last_line = lines[-1]
    data = json.loads(last_line)
    assert "status" in data
    assert "pid" in data


def test_main_uses_pipeline_contract(mocker, tmp_path):
    """main() calls setup_logging, PipelineStatusReporter.start/complete."""
    mock_popen = MagicMock()
    mock_popen.pid = 300
    mocker.patch("subprocess.Popen", return_value=mock_popen)

    import psutil
    mocker.patch.object(psutil, "pid_exists", return_value=False)

    mock_reporter = MagicMock()
    mocker.patch("mipmap_launcher.PipelineStatusReporter", return_value=mock_reporter)
    mock_setup = mocker.patch("mipmap_launcher.setup_logging", return_value=MagicMock())

    engine = tmp_path / "reconstruct_full_engine.exe"
    engine.write_bytes(b"fake")

    mocker.patch("sys.argv", [
        "mipmap_launcher.py",
        "--mission-id", "m123",
        "--mission-path", str(tmp_path),
        "--engine-path", str(engine),
        "--workspace", str(tmp_path),
    ])

    from mipmap_launcher import main
    try:
        main()
    except SystemExit:
        pass

    mock_setup.assert_called_once_with("mipmap_launcher")
    mock_reporter.start.assert_called_once()
    mock_reporter.complete.assert_called_once()
