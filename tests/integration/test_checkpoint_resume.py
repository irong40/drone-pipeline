"""
Integration test: checkpoint-based resume across a simulated mid-pipeline crash. INTG-04.

Tests use checkpoint.py's real save/load against tmp_path — no mocking of checkpoint.
"""
import os
import json
import pytest

from checkpoint import load_checkpoint, save_checkpoint, clear_checkpoint, checkpoint_path


SCRIPT_NAME = "video_color_grade"


@pytest.fixture
def items():
    """5 fake file path strings to simulate pipeline items."""
    return [f"/mission/video/full/DJI_{i:04d}.MP4" for i in range(1, 6)]


def test_checkpoint_resume_skips_completed_items(tmp_path, items):
    """Run 1: process 2 items, crash. Run 2: load checkpoint, process remaining 3."""
    mission = str(tmp_path)

    # Run 1: process items 0-1, then "crash"
    completed_run1 = set()
    for item in items[:2]:
        completed_run1.add(item)
    save_checkpoint(mission, SCRIPT_NAME, completed_run1)

    # Run 2: load checkpoint, process remaining
    completed_run2 = load_checkpoint(mission, SCRIPT_NAME)
    assert len(completed_run2) == 2

    processed_in_run2 = []
    for item in items:
        if item in completed_run2:
            continue
        processed_in_run2.append(item)
        completed_run2.add(item)

    save_checkpoint(mission, SCRIPT_NAME, completed_run2)

    # Assertions
    assert len(processed_in_run2) == 3  # Items 2, 3, 4
    assert not set(items[:2]).intersection(processed_in_run2)  # No overlap
    final = load_checkpoint(mission, SCRIPT_NAME)
    assert len(final) == 5
    assert final == set(items)


def test_checkpoint_resume_all_skipped_on_second_full_run(tmp_path, items):
    """Complete all items on first run. Second run: nothing processed."""
    mission = str(tmp_path)

    # First run: complete all
    save_checkpoint(mission, SCRIPT_NAME, set(items))

    # Second run: load and check
    completed = load_checkpoint(mission, SCRIPT_NAME)
    processed = []
    for item in items:
        if item in completed:
            continue
        processed.append(item)

    assert processed == []
    assert len(completed) == 5


def test_clear_checkpoint_forces_full_reprocess(tmp_path, items):
    """clear_checkpoint deletes the file, forcing load_checkpoint to return empty."""
    mission = str(tmp_path)

    # Populate with all 5
    save_checkpoint(mission, SCRIPT_NAME, set(items))
    assert len(load_checkpoint(mission, SCRIPT_NAME)) == 5

    # Clear
    clear_checkpoint(mission, SCRIPT_NAME)

    # Verify file deleted and load returns empty
    cp = checkpoint_path(mission, SCRIPT_NAME)
    assert not os.path.exists(cp)
    assert load_checkpoint(mission, SCRIPT_NAME) == set()


def test_checkpoint_atomic_write_survives_partial_state(tmp_path, items):
    """Save 3 items -> read raw JSON -> verify structure. Round-trip matches."""
    mission = str(tmp_path)
    partial = set(items[:3])

    save_checkpoint(mission, SCRIPT_NAME, partial)

    # Read raw JSON
    cp = checkpoint_path(mission, SCRIPT_NAME)
    with open(cp, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["version"] == 1
    assert data["script"] == SCRIPT_NAME
    assert data["completed"] == sorted(partial)  # sorted list

    # Round-trip
    loaded = load_checkpoint(mission, SCRIPT_NAME)
    assert loaded == partial
