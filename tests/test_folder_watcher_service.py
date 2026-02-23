"""
Unit tests for folder_watcher_service.py — Windows service lifecycle (install, remove, start, stop).
Populated in Phase 3 (UNIT-13).

NOTE: folder_watcher_service.py calls sys.exit() at module level when pywin32 is not
installed. This stub uses pytest.importorskip as a defensive guard. On this Windows
machine pywin32 is available, so tests will run normally. If ever executed on a
non-Windows CI runner, this test file will be skipped cleanly instead of erroring.
"""
import pytest

# Guard: skip entire file if pywin32 is not available (non-Windows CI)
pytest.importorskip("win32serviceutil", reason="pywin32 required for Windows service tests")

import folder_watcher_service  # noqa: F401 — verify importability after pywin32 confirmed


def test_placeholder():
    """Placeholder — replaced by real tests in Phase 3 (UNIT-13)."""
    pass
