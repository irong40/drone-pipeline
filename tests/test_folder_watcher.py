"""
Unit tests for folder_watcher.py — filesystem event monitoring, debounce logic, webhook triggering.
Populated in Phase 3 (UNIT-03).

NOTE: folder_watcher.py imports requests at module level and calls sys.exit() when watchdog
is not installed. This stub uses pytest.importorskip guards so collection skips cleanly
on environments without these dependencies.
"""
import pytest

# Guards: skip entire file if required packages are not available
pytest.importorskip("requests", reason="requests required for folder_watcher.py importability test")
pytest.importorskip("watchdog", reason="watchdog required for folder_watcher.py importability test")

import folder_watcher  # noqa: F401 — verify importability after dependencies confirmed


def test_placeholder():
    """Placeholder — replaced by real tests in Phase 3."""
    pass
