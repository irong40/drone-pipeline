# Phase 3: Ingest Layer Tests - Research

**Researched:** 2026-02-23
**Domain:** Python unit testing (pytest) — file sorting logic, EXIF/ffprobe platform detection, watchdog filesystem events, Windows service lifecycle
**Confidence:** HIGH (all findings verified against source code and pytest documentation)

---

## Summary

Phase 3 replaces five test stub files with real unit tests covering the ingest layer scripts: `ingest_sorter.py`, `platform_detect.py`, `folder_watcher.py`, `folder_watcher_service.py`, and `ingest.py`. The infrastructure from Phase 2 is already in place — pytest, pytest-mock, conftest.py fixtures, and the stub files with importorskip guards are all ready. Phase 3 work is purely test authoring.

The core challenge is that three of the five scripts have external dependencies that must be mocked: `platform_detect.py` calls `pyexiftool` and `subprocess` (ffprobe), `folder_watcher.py` fires HTTP webhooks via `requests` and uses `watchdog` observers backed by OS threads, and `folder_watcher_service.py` wraps `pywin32` Windows service APIs. `ingest_sorter.py` and `ingest.py` are the most testable — their pure-Python logic functions are straightforward to unit test with `tmp_path` and `MagicMock`.

The three-plan breakdown in the phase definition is correct and maps cleanly to the three test files with distinct testing patterns: (03-01) pure logic tests + file I/O mocking, (03-02) EXIF/ffprobe mock fixtures, (03-03) threading/event handler mocking + Windows service stubs.

**Primary recommendation:** Author tests function-by-function against the actual source code; each test module should import only the tested functions (not the full module's `main()`), and use `pytest.importorskip` guards already in the stubs — do not remove them.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| UNIT-01 | Unit tests for `ingest_sorter.py` — file sorting, sequence assignment, mission config parsing | All testable functions identified. `sort_by_sequence_ranges`, `extract_sequence_number`, `detect_platform`, `build_mission_folder_name`, `validate_timestamp_gaps`, `copy_file_to_mission` are pure or near-pure functions testable without real filesystem I/O. `scan_sd_card` requires `tmp_path`. `fire_webhook` requires `requests` mock. |
| UNIT-02 | Unit tests for `platform_detect.py` — EXIF detection, ffprobe fallback, Mini 4 Pro vs M4E vs M3E | `detect_from_exiftool` requires patching `exiftool.ExifToolHelper`. `detect_from_ffprobe` requires patching `subprocess.run`. `detect_from_filename`, `_extract_metadata_text`, `detect_platform_from_file` and `detect_platform_from_folder` all testable with mocked sub-functions. EXIF fixture files are NOT required — mock `exiftool.ExifToolHelper` return values directly. |
| UNIT-03 | Unit tests for `folder_watcher.py` — debounce logic, event filtering, webhook payload | `MissionFolderHandler` is a class with thread-backed debounce timers. Tests must control `threading.Timer` to avoid real sleep. `parse_mission_number`, `build_inventory` are pure functions testable with `tmp_path`. `fire_webhook` mocked via `mocker.patch("requests.post")`. |
| UNIT-13 | Unit tests for `folder_watcher_service.py` — service install/remove, start/stop lifecycle | `SentinelFolderWatcherService` is a `win32serviceutil.ServiceFramework` subclass. Tests mock `win32event`, `win32service`, `win32serviceutil`, and `servicemanager`. Service `main()` logic (which creates Observer) tested by mocking `MissionFolderHandler` and `Observer`. |
| UNIT-14 | Unit tests for `ingest.py` — MipMap photogrammetry ingest logic | `parse_dji_filename`, `split_missions`, `get_utm_zone`, `gimbal_to_orientation`, `extract_xmp_gimbal` are pure/near-pure. `extract_gps_from_exif` requires mocking `PIL.Image`. `build_task_json` calls both; test with fully mocked EXIF returns. `create_workspace` writes files — use `tmp_path`. |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=7.4 (pinned in requirements.txt) | Test runner, fixtures, assertions | Industry standard; `pythonpath=.` config requires >=7.0 |
| pytest-mock | >=3.12 | `mocker` fixture, `mocker.patch()` | Auto-teardown of patches; avoids manual `unittest.mock.patch` context managers |
| unittest.mock | stdlib | `MagicMock`, `patch`, `call` | Available everywhere; used directly for non-pytest mock needs |
| pytest.tmp_path | built-in | Temporary directories for file I/O tests | Cleaner than `tempfile.mkdtemp`; auto-cleaned after each test |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-cov | >=4.1 | Coverage reporting | Already in requirements.txt; run with `--cov=.` after Phase 3 |
| freezegun | N/A | Freeze `datetime.now()` calls | Only needed if testing timestamp-sensitive logic; not required here — timestamps in `build_inventory` are incidental |
| threading.Timer (stdlib) | N/A | Replaced in tests via patching | Must patch `threading.Timer` in folder_watcher tests to avoid real 60s sleep |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `mocker.patch` (pytest-mock) | `unittest.mock.patch` as context manager | pytest-mock is already installed and cleaner; no reason to use raw `patch` |
| Real tmp files via `tmp_path` | `pyfakefs` or `fakefs` | `tmp_path` is sufficient; pyfakefs would complicate pywin32/watchdog interop |
| Direct mock of `exiftool.ExifToolHelper` | Creating real `.jpg` EXIF fixture files | Mocking is faster, no binary assets needed, no ExifTool binary dependency in CI |

**Installation:** Already complete (Phase 2). No new packages needed for Phase 3.

---

## Architecture Patterns

### Recommended Project Structure

```
tests/
├── conftest.py                    # Phase 2 fixtures (mock_supabase_client, mock_drive_client, mock_ffmpeg)
├── test_ingest_sorter.py          # UNIT-01 — replaces stub
├── test_platform_detect.py        # UNIT-02 — replaces stub
├── test_folder_watcher.py         # UNIT-03 — replaces stub
├── test_folder_watcher_service.py # UNIT-13 — replaces stub
└── test_ingest.py                 # UNIT-14 — replaces stub
```

No new fixture files. No `fixtures/` subdirectory. All test data is built inline or via `tmp_path`.

### Pattern 1: Import the function under test, not the module's main()

**What:** Import only the specific functions being tested. Never call `main()` in unit tests.

**When to use:** All five test files in Phase 3.

**Example:**
```python
from ingest_sorter import (
    extract_sequence_number,
    detect_platform,
    sort_by_sequence_ranges,
    build_mission_folder_name,
    validate_timestamp_gaps,
    copy_file_to_mission,
    scan_sd_card,
    fire_webhook,
)
```

### Pattern 2: Patching lazy imports

**What:** Scripts in this project use lazy imports (imports inside functions, not at module level). The correct patch target is the imported name's origin module, not the calling module.

**When to use:** `exiftool.ExifToolHelper`, `supabase.create_client`, `PIL.Image`, `requests.post`.

**Example — patching pyexiftool:**
```python
def test_detect_from_exiftool_mini4pro(mocker):
    mock_et_instance = MagicMock()
    mock_et_instance.get_metadata.return_value = [
        {"XMP:Model": "FC8282", "EXIF:Model": "", "EXIF:Make": "DJI"}
    ]
    mock_et_class = mocker.patch("exiftool.ExifToolHelper")
    mock_et_class.return_value.__enter__.return_value = mock_et_instance

    from platform_detect import detect_from_exiftool
    platform, meta = detect_from_exiftool("fake.jpg")
    assert platform == "mini4pro"
```

**Note from Phase 2 decisions:** Patch `"supabase.create_client"` NOT `"ingest_sorter.create_client"` — scripts never bind `create_client` at module level.

### Pattern 3: Controlling threading.Timer for debounce tests

**What:** `MissionFolderHandler._reset_timer` schedules a `threading.Timer`. In tests, patch `threading.Timer` to return a mock that doesn't actually sleep. To test the debounce callback, call `_on_debounce_complete` directly.

**When to use:** All `MissionFolderHandler` debounce tests (UNIT-03).

**Example:**
```python
def test_debounce_reset_cancels_previous(mocker):
    mock_timer_class = mocker.patch("folder_watcher.threading.Timer")
    mock_timer1 = MagicMock()
    mock_timer2 = MagicMock()
    mock_timer_class.side_effect = [mock_timer1, mock_timer2]

    handler = MissionFolderHandler(watch_dir="/tmp/watch", debounce_seconds=60)
    handler._reset_timer("SAI_M0001_re_standard_20260218")
    handler._reset_timer("SAI_M0001_re_standard_20260218")

    mock_timer1.cancel.assert_called_once()
    mock_timer2.start.assert_called_once()
```

### Pattern 4: Testing file I/O with tmp_path

**What:** Use `tmp_path` fixture to create real temporary files and directory structures. For `scan_sd_card`, `build_inventory`, `count_inventory`, and `create_workspace`, create the minimal file/folder structure in `tmp_path`.

**When to use:** `ingest_sorter.scan_sd_card`, `ingest_sorter.copy_file_to_mission`, `ingest_sorter.create_mission_structure`, `folder_watcher.build_inventory`, `ingest.create_workspace`.

**Example:**
```python
def test_scan_sd_card_finds_dji_files(tmp_path):
    # Create fake DJI files
    (tmp_path / "DJI_0001.JPG").write_bytes(b"fake")
    (tmp_path / "DJI_0002.JPG").write_bytes(b"fake")
    (tmp_path / "non_dji.txt").write_bytes(b"skip")

    from ingest_sorter import scan_sd_card
    files = scan_sd_card(str(tmp_path))
    assert len(files) == 2
    assert all(f["extension"] == "JPG" for f in files)
```

### Pattern 5: Windows service testing without real pywin32 calls

**What:** `SentinelFolderWatcherService` inherits from `win32serviceutil.ServiceFramework`. Mock `win32serviceutil.ServiceFramework.__init__`, `win32event.CreateEvent`, and `win32event.SetEvent` to avoid OS calls. Test `SvcStop` and `SvcDoRun` logic by instantiating the class with a mocked `args` list.

**When to use:** `test_folder_watcher_service.py` (UNIT-13).

**Example:**
```python
def test_svc_stop_sets_running_false(mocker):
    mocker.patch("win32serviceutil.ServiceFramework.__init__", return_value=None)
    mocker.patch("win32event.CreateEvent", return_value=MagicMock())
    mocker.patch("win32event.SetEvent")
    mocker.patch.object(
        folder_watcher_service.SentinelFolderWatcherService,
        "ReportServiceStatus"
    )

    svc = folder_watcher_service.SentinelFolderWatcherService.__new__(
        folder_watcher_service.SentinelFolderWatcherService
    )
    svc.stop_event = MagicMock()
    svc.running = True
    svc.SvcStop()

    assert svc.running is False
```

### Anti-Patterns to Avoid

- **Calling `main()` in unit tests:** All five scripts have `sys.exit()` calls in `main()`. Calling `main()` in a test will fail unless all args and mocks are set up perfectly. Test functions directly instead.
- **Real filesystem paths like `E:\Sentinel\`:** Never test with hardcoded production paths. Always override with `tmp_path` or pass path parameters directly to functions.
- **Real threading.Timer sleeps:** `DEBOUNCE_SECONDS = 60` — never let a real Timer run in tests. Always patch `threading.Timer`.
- **Real HTTP calls to n8n:** Always patch `requests.post` in `fire_webhook` tests. The conftest `mock_supabase_client` does not cover `requests`.
- **Real pyexiftool/ExifTool binary:** Never rely on ExifTool being installed in CI. Always mock `exiftool.ExifToolHelper`.
- **Real ffprobe binary:** Already handled by conftest `mock_ffmpeg` fixture for `subprocess.run`. For `detect_from_ffprobe`, use `mock_ffmpeg` or patch `subprocess.run` directly.
- **Removing importorskip guards:** The stubs already have `pytest.importorskip` guards for `requests`, `watchdog`, `win32serviceutil`, `PIL`. Keep these — they protect CI environments.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Controlling datetime output | Custom clock class | `mocker.patch("ingest_sorter.datetime")` or `freezegun` | `datetime.now(datetime.UTC)` is called inside functions; patch at the module level |
| Fake filesystem | Custom file creation helpers | `pytest.tmp_path` (built-in) | Already available; auto-cleaned after test |
| Mock HTTP responses | Custom HTTP server | `mocker.patch("requests.post")` | Much simpler for unit tests; integration tests can use `responses` library later |
| Thread synchronization in tests | Custom threading helpers | Direct call to `_on_debounce_complete()` + patch `threading.Timer` | Avoids race conditions in tests |
| EXIF fixture binary files | Real `.jpg` files with embedded EXIF | Mock `exiftool.ExifToolHelper.get_metadata` return value | No binary assets, no ExifTool dependency, runs on any machine |

**Key insight:** Every external I/O call in these scripts (filesystem, subprocess, HTTP, threading) has a standard pytest-mock solution. Don't build custom abstractions — patch the standard library call sites.

---

## Common Pitfalls

### Pitfall 1: pyexiftool context manager protocol

**What goes wrong:** `exiftool.ExifToolHelper` is used as a context manager (`with exiftool.ExifToolHelper() as et:`). Mocking only the class instantiation (`mocker.patch("exiftool.ExifToolHelper")`) is not enough — the mock must implement `__enter__` and `__return__` to behave like a context manager.

**Why it happens:** `MagicMock()` does implement `__enter__` and `__exit__` automatically, but only if set up correctly. The mock returned by `MagicMock.return_value.__enter__` is what `et` resolves to inside the `with` block.

**How to avoid:** Use the pattern:
```python
mock_et_class = mocker.patch("exiftool.ExifToolHelper")
mock_et_instance = MagicMock()
mock_et_class.return_value.__enter__.return_value = mock_et_instance
mock_et_instance.get_metadata.return_value = [{"XMP:Model": "FC8282", ...}]
```

**Warning signs:** `AttributeError: 'MagicMock' object has no attribute 'get_metadata'` — means the `__enter__` return value isn't set up correctly.

### Pitfall 2: detect_from_exif fallback chain

**What goes wrong:** `detect_from_exif` first calls `detect_from_exiftool`, then falls back to `PIL.Image`. If `detect_from_exiftool` is patched to return a result, the PIL path is never exercised. To test PIL fallback, you must also mock `detect_from_exiftool` to return `(None, None)`.

**Why it happens:** The function explicitly returns early if `detect_from_exiftool` succeeds. This is correct behavior but requires careful test design to cover both branches.

**How to avoid:** Two distinct tests: (a) patch exiftool to succeed → assert exif path taken, (b) patch `exiftool.ExifToolHelper` to raise `ImportError` or patch `detect_from_exiftool` to return `(None, None)` → patch `PIL.Image.open` → assert PIL path taken.

### Pitfall 3: MissionFolderHandler._triggered set prevents re-triggering

**What goes wrong:** Once a folder is added to `self._triggered`, `_reset_timer` returns immediately. Tests that reuse the same handler instance across multiple sub-tests will not re-trigger for the same folder name.

**Why it happens:** This is intentional behavior (idempotency guard), but it makes test ordering matter if using a shared handler instance.

**How to avoid:** Create a fresh `MissionFolderHandler` instance in each test, or clear `handler._triggered` between tests. Use function-scoped fixtures.

### Pitfall 4: copy_file_to_mission path traversal check on Windows

**What goes wrong:** `copy_file_to_mission` uses `os.path.abspath` and `startswith` to prevent path traversal. On Windows, `abspath` produces backslash paths, but `startswith` is case-sensitive. Tests using forward-slash paths may fail the guard unexpectedly.

**Why it happens:** `os.path.abspath("c:/foo/bar")` on Windows returns `C:\foo\bar`. `"C:\foo\bar\evil".startswith("c:\foo\bar")` → False (case mismatch on drive letter).

**How to avoid:** In tests, construct `file_info["path"]` using `str(tmp_path / "DJI_0001.JPG")` (which gives native OS path from `tmp_path`), and pass `mission_path = str(tmp_path / "mission")` — both come from the same `tmp_path` root so the `startswith` guard will pass.

### Pitfall 5: folder_watcher_service imports fail on non-Windows

**What goes wrong:** The `pytest.importorskip("win32serviceutil")` guard already handles this. But if a test attempts to instantiate `SentinelFolderWatcherService` directly (which calls `win32serviceutil.ServiceFramework.__init__`), it will fail even on Windows unless the pywin32 initialization path is mocked.

**Why it happens:** `ServiceFramework.__init__` tries to call Win32 APIs to register the service handle. In a test context (no actual service dispatcher), this raises an error.

**How to avoid:** Use `SentinelFolderWatcherService.__new__(SentinelFolderWatcherService)` to instantiate without calling `__init__`, then set attributes manually. Or mock `win32serviceutil.ServiceFramework.__init__` to `return None`.

### Pitfall 6: ingest.py uses `img._getexif()` (private Pillow API)

**What goes wrong:** `extract_gps_from_exif` calls `img._getexif()` (underscore prefix), which is a private/legacy Pillow method. When mocking `PIL.Image.open`, the returned mock must have `._getexif()` configured. `MagicMock()` will auto-create it, but the return value (a dict of tag_id → value) must be realistic.

**Why it happens:** `ingest.py` was written before Phase 1 and uses the older `_getexif()` API rather than `getexif()`.

**How to avoid:**
```python
mock_img = MagicMock()
mock_img._getexif.return_value = {
    34853: {  # GPSInfo tag
        1: "N", 2: (37, 0, 0),   # lat ref, lat
        3: "W", 4: (76, 0, 0),   # lon ref, lon
        6: 50.0,                   # altitude
    }
}
mocker.patch("PIL.Image.open", return_value=mock_img)
```

### Pitfall 7: gimbal_to_orientation uses float math — don't assert exact equality

**What goes wrong:** `gimbal_to_orientation` returns a list of 9 floats computed from trig functions. Asserting `result == expected_list` will fail due to floating point precision.

**Why it happens:** `math.cos`, `math.sin` introduce floating-point rounding.

**How to avoid:** Use `pytest.approx`:
```python
result = gimbal_to_orientation(0, 0, 0)
assert result == pytest.approx([1, 0, 0, 0, 0, -1, 0, 1, 0], abs=1e-9)
```

---

## Code Examples

Verified patterns from direct source code inspection:

### extract_sequence_number — two regex branches

```python
# Source: ingest_sorter.py lines 127-137
# Branch 1: timestamp format
assert extract_sequence_number("DJI_20260218101500_0015_D.JPG") == 15
# Branch 2: sequential format
assert extract_sequence_number("DJI_0015.JPG") == 15
# None case
assert extract_sequence_number("RANDOM_0015.JPG") is None
```

### detect_platform — filename-only (not EXIF)

```python
# Source: ingest_sorter.py lines 97-102
# Note: ingest_sorter.detect_platform() != platform_detect.detect_from_filename()
# These are separate implementations. Test both independently.
assert detect_platform("DJI_20260218101500_0015_D.JPG") == "m4e"
assert detect_platform("DJI_0015.JPG") == "mini4pro"
assert detect_platform("RANDOM_FILE.JPG") is None
```

### sort_by_sequence_ranges — the core sorting logic

```python
# Source: ingest_sorter.py lines 196-217
files = [
    {"sequence": 1, "filename": "DJI_0001.JPG", "extension": "JPG", "platform": "mini4pro", "timestamp": None},
    {"sequence": 5, "filename": "DJI_0005.JPG", "extension": "JPG", "platform": "mini4pro", "timestamp": None},
    {"sequence": 10, "filename": "DJI_0010.JPG", "extension": "JPG", "platform": "mini4pro", "timestamp": None},
]
missions = [
    {"mission_id": "uuid-1", "sequence_start": 1, "sequence_end": 6},
    {"mission_id": "uuid-2", "sequence_start": 7, "sequence_end": 12},
]
sorted_m, unassigned = sort_by_sequence_ranges(files, missions)
assert "uuid-1" in sorted_m
assert len(sorted_m["uuid-1"]) == 2  # seq 1 and 5
assert len(sorted_m["uuid-2"]) == 1  # seq 10
assert unassigned == []
```

### build_mission_folder_name — formatting

```python
# Source: ingest_sorter.py lines 249-253
mission = {"mission_number": 47, "package_type": "re_standard", "date": "20260218"}
assert build_mission_folder_name(mission) == "SAI_M0047_re_standard_20260218"
```

### detect_platform_from_folder — consensus logic

```python
# Source: platform_detect.py lines 291-354
# Key behaviors to test:
# 1. EXIF photo path — creates photos/jpeg subfolder with mock photos
# 2. ffprobe video fallback — no photos, uses video/full subfolder
# 3. filename fallback — no metadata methods, uses filename pattern
# 4. ambiguous — multiple platforms detected, picks majority
```

### build_inventory (folder_watcher.py) — file counting

```python
# Source: folder_watcher.py lines 73-110
# Creates tmp_path structure, writes files, counts by extension
# Key: has_ppk = True if ANY ppk file found (not a count)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `datetime.utcnow()` | `datetime.now(datetime.UTC)` | Phase 1 (DEPR-01) | Tests that assert on timestamp strings should expect "Z" suffix, not "+00:00" |
| Bare `import` at module top (potential sys.exit) | `pytest.importorskip` guards in stubs | Phase 2 (02-02) | Keep these guards in place when writing real tests |
| `drone_jobs` table name | `missions` table name | Pre-Phase 1 review | Not relevant to Phase 3 (no Supabase calls in ingest layer) |

**Deprecated/outdated:**
- `datetime.utcnow()`: Replaced in `ingest_sorter.py` and `folder_watcher.py` during Phase 1. The `fire_webhook` payload now uses `datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")`. Tests verifying the payload should match the `Z`-suffix format.
- `img._getexif()` in `ingest.py`: Still present (private Pillow API). Not deprecated yet but worth noting — test against what's there, not what's ideal.

---

## Open Questions

1. **Does pywin32 require actual Win32 OS calls during service `__init__`?**
   - What we know: `win32serviceutil.ServiceFramework.__init__` registers a service handle. In test context (no service dispatcher), this may raise or require `win32event.CreateEvent` to succeed.
   - What's unclear: Whether a plain `mocker.patch("win32serviceutil.ServiceFramework.__init__", return_value=None)` is sufficient, or if additional pywin32 setup is needed.
   - Recommendation: Use `__new__` instantiation pattern (bypass `__init__` entirely) for the simplest service lifecycle tests. If `SvcDoRun` must be tested more deeply, mock `win32event.WaitForSingleObject` to return `win32event.WAIT_OBJECT_0` immediately.

2. **Does `scan_sd_card` need recursive subdirectory coverage?**
   - What we know: It calls `source.rglob("*")` — explicitly recursive. DJI SD cards typically have `DCIM/DJI_001/`, `DCIM/DJI_002/` subdirectories.
   - What's unclear: Whether tests should replicate multi-level subdirectory structure or a flat tmp_path suffices for coverage.
   - Recommendation: One flat test (covers basic path) + one recursive test with a single subdirectory level. Does not need to replicate the full DJI SD card structure.

3. **How to test `validate_timestamp_gaps` with time-aware datetimes?**
   - What we know: The function computes `total_seconds() / 60` from datetime objects. `extract_timestamp` returns `datetime.strptime(...)` which produces naive datetime objects (no timezone).
   - What's unclear: Whether tests should use naive datetimes (matching source behavior) or if there's a UTC requirement.
   - Recommendation: Use naive `datetime` objects in test data — matching the actual behavior of `extract_timestamp` which returns naive datetimes from `strptime`.

---

## Sources

### Primary (HIGH confidence)

- Direct source code inspection: `ingest_sorter.py`, `platform_detect.py`, `folder_watcher.py`, `folder_watcher_service.py`, `ingest.py` — all functions catalogued from file
- `tests/conftest.py` — existing fixture patterns verified directly
- `tests/test_ingest_sorter.py`, `test_platform_detect.py`, `test_folder_watcher.py`, `test_folder_watcher_service.py`, `test_ingest.py` — existing stubs and importorskip guards confirmed
- `pytest.ini` — `pythonpath = .` config confirmed; addopts `-ra --tb=short` confirmed
- `requirements.txt` — pytest>=7.4, pytest-mock>=3.12 confirmed installed

### Secondary (MEDIUM confidence)

- `.planning/STATE.md` decisions log — Phase 2 decisions about patch targets, importorskip patterns, fixture autouse=False confirmed

### Tertiary (LOW confidence)

- None — all findings grounded in source code for this phase.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified in requirements.txt and Phase 2 infrastructure
- Architecture: HIGH — derived directly from reading all five source files
- Pitfalls: HIGH — derived from actual source code patterns (path traversal check, exiftool context manager, float math, pywin32 init)
- Windows service testing: MEDIUM — pywin32 behavior in test context may require adjustment; `__new__` pattern is standard but specific behavior depends on pywin32 version

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable Python/pytest ecosystem; source code won't change before tests are written)
