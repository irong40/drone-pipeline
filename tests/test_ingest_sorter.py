"""
Unit tests for ingest_sorter.py — SD card file sorting, sequence assignment, mission config parsing.
Populated in Phase 3 (UNIT-01).

NOTE: ingest_sorter.py imports requests at module level. This stub uses pytest.importorskip
as a defensive guard so collection skips cleanly on environments without requests installed.
"""
import pytest

# Guard: skip entire file if requests is not available
pytest.importorskip("requests", reason="requests required for ingest_sorter.py importability test")

import ingest_sorter  # noqa: F401 — verify importability after requests confirmed


def test_placeholder():
    """Placeholder — replaced by real tests in Phase 3."""
    pass
