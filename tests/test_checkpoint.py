"""
Unit tests for checkpoint.py — checkpoint manifest read/write for resume-on-failure.
Uses real filesystem via pytest's tmp_path fixture. No mocks of the filesystem.
"""
import json
import os
import stat
import sys
import tempfile
import threading

import pytest

import checkpoint
from checkpoint import (
    CHECKPOINT_VERSION,
    checkpoint_path,
    clear_checkpoint,
    load_checkpoint,
    save_checkpoint,
)


# ---------------------------------------------------------------------------
# 1. checkpoint_path — correct path format
# ---------------------------------------------------------------------------

class TestCheckpointPath:
    def test_returns_correct_filename(self, tmp_path):
        result = checkpoint_path(str(tmp_path), "video_color_grade")
        expected = os.path.join(str(tmp_path), ".checkpoint_video_color_grade.json")
        assert result == expected

    def test_filename_starts_with_dot(self, tmp_path):
        result = checkpoint_path(str(tmp_path), "ingest_sorter")
        basename = os.path.basename(result)
        assert basename.startswith(".")

    def test_filename_ends_with_json(self, tmp_path):
        result = checkpoint_path(str(tmp_path), "video_qa")
        assert result.endswith(".json")

    def test_different_scripts_produce_different_paths(self, tmp_path):
        path_a = checkpoint_path(str(tmp_path), "script_a")
        path_b = checkpoint_path(str(tmp_path), "script_b")
        assert path_a != path_b

    def test_same_args_produce_same_path(self, tmp_path):
        assert checkpoint_path(str(tmp_path), "foo") == checkpoint_path(str(tmp_path), "foo")


# ---------------------------------------------------------------------------
# 2. load_checkpoint — missing file returns empty set
# ---------------------------------------------------------------------------

class TestLoadCheckpointMissingFile:
    def test_returns_empty_set_when_no_file(self, tmp_path):
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()

    def test_return_type_is_set(self, tmp_path):
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# 3. save_checkpoint + load_checkpoint round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_basic_round_trip(self, tmp_path):
        keys = {"file_001.MP4", "file_002.MP4", "file_003.MP4"}
        save_checkpoint(str(tmp_path), "video_color_grade", keys)
        result = load_checkpoint(str(tmp_path), "video_color_grade")
        assert result == keys

    def test_empty_set_round_trip(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_color_grade", set())
        result = load_checkpoint(str(tmp_path), "video_color_grade")
        assert result == set()

    def test_single_item_round_trip(self, tmp_path):
        save_checkpoint(str(tmp_path), "srt_parser", {"only_file.SRT"})
        result = load_checkpoint(str(tmp_path), "srt_parser")
        assert result == {"only_file.SRT"}

    def test_list_input_round_trips_as_set(self, tmp_path):
        # completed may be a list; load must return a set
        save_checkpoint(str(tmp_path), "ingest_sorter", ["a", "b", "c"])
        result = load_checkpoint(str(tmp_path), "ingest_sorter")
        assert result == {"a", "b", "c"}
        assert isinstance(result, set)

    def test_overwrite_updates_checkpoint(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_qa", {"a", "b"})
        save_checkpoint(str(tmp_path), "video_qa", {"a", "b", "c"})
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == {"a", "b", "c"}

    def test_checkpoint_file_contains_correct_json_structure(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_color_grade", {"x", "y"})
        path = checkpoint_path(str(tmp_path), "video_color_grade")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["version"] == CHECKPOINT_VERSION
        assert data["script"] == "video_color_grade"
        assert sorted(data["completed"]) == sorted(["x", "y"])

    def test_completed_list_is_sorted_in_file(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_qa", {"z", "a", "m"})
        path = checkpoint_path(str(tmp_path), "video_qa")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["completed"] == sorted(["z", "a", "m"])

    def test_isolates_across_scripts(self, tmp_path):
        save_checkpoint(str(tmp_path), "script_a", {"key1"})
        save_checkpoint(str(tmp_path), "script_b", {"key2"})
        assert load_checkpoint(str(tmp_path), "script_a") == {"key1"}
        assert load_checkpoint(str(tmp_path), "script_b") == {"key2"}


# ---------------------------------------------------------------------------
# 4. save_checkpoint atomicity (temp file + os.replace)
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_no_tmp_files_left_after_successful_save(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_color_grade", {"a"})
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert tmp_files == []

    def test_checkpoint_file_exists_after_save(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_color_grade", {"a"})
        path = checkpoint_path(str(tmp_path), "video_color_grade")
        assert os.path.isfile(path)

    def test_checkpoint_file_is_valid_json_after_save(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_color_grade", {"a", "b"})
        path = checkpoint_path(str(tmp_path), "video_color_grade")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)  # must not raise
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# 5. clear_checkpoint removes the file
# ---------------------------------------------------------------------------

class TestClearCheckpoint:
    def test_removes_existing_file(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_qa", {"a"})
        path = checkpoint_path(str(tmp_path), "video_qa")
        assert os.path.isfile(path)
        clear_checkpoint(str(tmp_path), "video_qa")
        assert not os.path.isfile(path)

    def test_load_after_clear_returns_empty_set(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_qa", {"a", "b"})
        clear_checkpoint(str(tmp_path), "video_qa")
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()


# ---------------------------------------------------------------------------
# 6. clear_checkpoint safe when file does not exist
# ---------------------------------------------------------------------------

class TestClearCheckpointMissingFile:
    def test_no_error_when_file_absent(self, tmp_path):
        # Must not raise
        clear_checkpoint(str(tmp_path), "nonexistent_script")

    def test_idempotent_double_clear(self, tmp_path):
        save_checkpoint(str(tmp_path), "video_qa", {"a"})
        clear_checkpoint(str(tmp_path), "video_qa")
        clear_checkpoint(str(tmp_path), "video_qa")  # second call must not raise


# ---------------------------------------------------------------------------
# 7. load_checkpoint returns empty set for corrupt JSON
# ---------------------------------------------------------------------------

class TestLoadCorruptFile:
    def test_truncated_json(self, tmp_path):
        path = checkpoint_path(str(tmp_path), "video_qa")
        path_obj = tmp_path / os.path.basename(path)
        path_obj.write_text("{not valid json", encoding="utf-8")
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()

    def test_completely_empty_file(self, tmp_path):
        path = checkpoint_path(str(tmp_path), "video_qa")
        path_obj = tmp_path / os.path.basename(path)
        path_obj.write_text("", encoding="utf-8")
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()

    def test_json_array_instead_of_object(self, tmp_path):
        path = checkpoint_path(str(tmp_path), "video_qa")
        path_obj = tmp_path / os.path.basename(path)
        path_obj.write_text("[1, 2, 3]", encoding="utf-8")
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()

    def test_null_json(self, tmp_path):
        path = checkpoint_path(str(tmp_path), "video_qa")
        path_obj = tmp_path / os.path.basename(path)
        path_obj.write_text("null", encoding="utf-8")
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()


# ---------------------------------------------------------------------------
# 8. load_checkpoint returns empty set for wrong version
# ---------------------------------------------------------------------------

class TestLoadWrongVersion:
    def _write_checkpoint(self, tmp_path, script, version, completed):
        path = checkpoint_path(str(tmp_path), script)
        data = {"version": version, "script": script, "completed": list(completed)}
        tmp_path_obj = tmp_path / (os.path.basename(path) + ".tmp")
        tmp_path_obj.write_text(json.dumps(data), encoding="utf-8")
        os.replace(str(tmp_path_obj), path)

    def test_future_version_returns_empty_set(self, tmp_path):
        self._write_checkpoint(tmp_path, "video_qa", CHECKPOINT_VERSION + 1, ["a", "b"])
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()

    def test_version_zero_returns_empty_set(self, tmp_path):
        self._write_checkpoint(tmp_path, "video_qa", 0, ["a"])
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()

    def test_missing_version_key_returns_empty_set(self, tmp_path):
        path = checkpoint_path(str(tmp_path), "video_qa")
        data = {"script": "video_qa", "completed": ["a"]}  # no "version"
        (tmp_path / os.path.basename(path)).write_text(json.dumps(data), encoding="utf-8")
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == set()

    def test_correct_version_returns_data(self, tmp_path):
        self._write_checkpoint(tmp_path, "video_qa", CHECKPOINT_VERSION, ["a", "b"])
        result = load_checkpoint(str(tmp_path), "video_qa")
        assert result == {"a", "b"}


# ---------------------------------------------------------------------------
# 9. save_checkpoint raises OSError on permission error; tmp file is cleaned up
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod read-only directory behaves differently on Windows with NTFS ACLs",
)
class TestSavePermissionError:
    def test_raises_oserror_on_unwritable_dir(self, tmp_path):
        # Make the mission dir read-only so mkstemp fails
        os.chmod(str(tmp_path), stat.S_IRUSR | stat.S_IXUSR)
        try:
            with pytest.raises(OSError):
                save_checkpoint(str(tmp_path), "video_qa", {"a"})
        finally:
            # Restore so tmp_path cleanup succeeds
            os.chmod(str(tmp_path), stat.S_IRWXU)

    def test_no_tmp_files_left_after_permission_error(self, tmp_path):
        os.chmod(str(tmp_path), stat.S_IRUSR | stat.S_IXUSR)
        try:
            with pytest.raises(OSError):
                save_checkpoint(str(tmp_path), "video_qa", {"a"})
        except OSError:
            pass
        finally:
            os.chmod(str(tmp_path), stat.S_IRWXU)
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert tmp_files == []


# ---------------------------------------------------------------------------
# 10. Concurrent saves don't corrupt data
# ---------------------------------------------------------------------------

class TestConcurrentSaves:
    def test_concurrent_saves_last_write_wins_no_corruption(self, tmp_path):
        """
        Multiple threads writing different completed sets simultaneously.

        On POSIX, os.replace is atomic and all writes succeed; the final
        checkpoint must be valid JSON matching one of the written sets.

        On Windows, os.replace raises PermissionError when another thread
        holds the destination file open for reading (a documented OS limit).
        That is the module's documented non-fatal path — callers catch OSError.
        We accept those errors here and only assert that whatever file was
        written is valid, uncorrupted JSON.
        """
        script = "video_color_grade"
        oserrors = []
        written_sets = []

        def worker(index):
            keys = {f"file_{index:03d}_{i}.MP4" for i in range(10)}
            written_sets.append(frozenset(keys))
            try:
                save_checkpoint(str(tmp_path), script, keys)
            except OSError:
                # Non-fatal per module contract; record but don't re-raise
                oserrors.append(index)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At least one write must have succeeded (otherwise the file may not exist)
        path = checkpoint_path(str(tmp_path), script)
        if not os.path.isfile(path):
            # All writes failed — only valid if ALL raised OSError (Windows edge case)
            assert len(oserrors) == len(threads), (
                "Checkpoint file missing but not all writes raised OSError"
            )
            return

        # The file that exists must be valid, uncorrupted JSON
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)  # Must not raise — no torn write

        assert data["version"] == CHECKPOINT_VERSION
        assert isinstance(data["completed"], list)

        # The surviving set must match one of the sets that was written without error
        loaded = frozenset(data["completed"])
        assert loaded in written_sets, (
            f"Loaded set does not match any written set"
        )

    def test_no_tmp_files_left_after_concurrent_saves(self, tmp_path):
        """
        Regardless of whether concurrent os.replace succeeds or raises OSError
        (Windows limitation), the module must clean up its temp files.
        """
        script = "video_qa"

        def worker(i):
            try:
                save_checkpoint(str(tmp_path), script, {f"key_{i}"})
            except OSError:
                pass  # Non-fatal per module contract

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert tmp_files == []
