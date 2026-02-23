"""
Unit tests for ingest.py — MipMap photogrammetry ingest.
Populated in Phase 3 (UNIT-14).

NOTE: ingest.py calls sys.exit() at module level when Pillow is not installed.
This stub uses pytest.importorskip as a defensive guard so collection skips cleanly
on environments without Pillow rather than raising a SystemExit INTERNALERROR.
"""
import pytest

# Guard: skip entire file if Pillow is not available
pytest.importorskip("PIL", reason="Pillow required for ingest.py importability test")

import ingest  # noqa: F401 — verify importability after PIL confirmed


def test_placeholder():
    """Placeholder — replaced by real tests in Phase 3."""
    pass
