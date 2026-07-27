"""
Unit tests for folder_watcher_service.py — Windows service lifecycle (SvcStop, SvcDoRun).
Covers UNIT-13: service class attributes, running flag, Win32 event calls, servicemanager logging.

NOTE: folder_watcher_service.py calls sys.exit() at module level when pywin32 is not
installed. This file uses pytest.importorskip as a defensive guard. On this Windows
machine pywin32 is available, so tests will run normally. If ever executed on a
non-Windows CI runner, this test file will be skipped cleanly instead of erroring.

PATTERN: Use __new__ to instantiate SentinelFolderWatcherService without calling __init__,
which would trigger Win32 API calls (win32event.CreateEvent, ServiceFramework registration).
Then set instance attributes manually before each test.
"""
import pytest
from unittest.mock import MagicMock

# Guard: skip entire file if pywin32 is not available (non-Windows CI)
pytest.importorskip("win32serviceutil", reason="pywin32 required for Windows service tests")

import win32event      # noqa: E402 — imported after importorskip guard
import servicemanager  # noqa: E402

import folder_watcher_service  # noqa: F401,E402 — verify importability after pywin32 confirmed

from folder_watcher_service import SentinelFolderWatcherService  # noqa: E402


# ─── Service class attributes ─────────────────────────────────────────────────

def test_svc_name():
    """Service registration name must be exactly 'SentinelFolderWatcher'."""
    assert SentinelFolderWatcherService._svc_name_ == "SentinelFolderWatcher"


def test_svc_display_name_contains_sentinel():
    """Display name shown in services.msc must mention Sentinel."""
    assert "Sentinel" in SentinelFolderWatcherService._svc_display_name_


def test_svc_description_is_nonempty():
    """Description field must be a non-empty string."""
    desc = SentinelFolderWatcherService._svc_description_
    assert isinstance(desc, str)
    assert len(desc) > 0


# ─── SvcStop ─────────────────────────────────────────────────────────────────

def test_svc_stop_sets_running_false(mocker):
    """SvcStop sets running=False and signals stop_event via win32event.SetEvent."""
    mock_set_event = mocker.patch("win32event.SetEvent")

    svc = SentinelFolderWatcherService.__new__(SentinelFolderWatcherService)
    svc.stop_event = MagicMock()
    svc.running = True
    mocker.patch.object(svc, "ReportServiceStatus")

    svc.SvcStop()

    assert svc.running is False
    mock_set_event.assert_called_once_with(svc.stop_event)


def test_svc_stop_reports_stop_pending(mocker):
    """SvcStop calls ReportServiceStatus to notify SCM of pending stop."""
    import win32service
    mocker.patch("win32event.SetEvent")

    svc = SentinelFolderWatcherService.__new__(SentinelFolderWatcherService)
    svc.stop_event = MagicMock()
    svc.running = True
    mock_report = mocker.patch.object(svc, "ReportServiceStatus")

    svc.SvcStop()

    mock_report.assert_called_once_with(win32service.SERVICE_STOP_PENDING)


# ─── SvcDoRun ─────────────────────────────────────────────────────────────────

def test_svc_do_run_sets_running_true(mocker):
    """SvcDoRun sets running=True before calling main()."""
    mocker.patch("servicemanager.LogMsg")

    svc = SentinelFolderWatcherService.__new__(SentinelFolderWatcherService)
    svc.running = False
    mocker.patch.object(svc, "main")

    svc.SvcDoRun()

    assert svc.running is True


def test_svc_do_run_calls_main(mocker):
    """SvcDoRun calls self.main() to start the folder watcher loop."""
    mocker.patch("servicemanager.LogMsg")

    svc = SentinelFolderWatcherService.__new__(SentinelFolderWatcherService)
    svc.running = False
    mock_main = mocker.patch.object(svc, "main")

    svc.SvcDoRun()

    mock_main.assert_called_once()


def test_svc_do_run_logs_to_eventlog(mocker):
    """SvcDoRun calls servicemanager.LogMsg to write a Windows Event Log entry."""
    mock_log_msg = mocker.patch("servicemanager.LogMsg")

    svc = SentinelFolderWatcherService.__new__(SentinelFolderWatcherService)
    svc.running = False
    mocker.patch.object(svc, "main")

    svc.SvcDoRun()

    mock_log_msg.assert_called_once()
