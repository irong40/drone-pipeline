# Phase 4: Video Pipeline Tests - Research

**Researched:** 2026-02-23
**Domain:** Python unit testing (pytest) — FFmpeg command construction, ffprobe subprocess mocking, SRT regex parsing, Supabase upsert/insert payloads, QA threshold logic
**Confidence:** HIGH (all findings derived directly from source file inspection; no assumptions)

---

## Summary

Phase 4 replaces six test stub files with real unit tests covering the video processing pipeline: `video_color_grade.py`, `video_metadata.py`, `srt_telemetry_parser.py`, `video_qa.py`, `video_proxy_gen.py`, and `video_format_export.py`. The Phase 2 infrastructure (pytest, pytest-mock, conftest.py fixtures) is already complete and all six stub files import cleanly (`pytest --co` confirms 6 placeholder tests collectible). Phase 4 work is purely test authoring against existing source code.

The central testing challenge across all six scripts is subprocess/FFmpeg: `video_color_grade.py`, `video_proxy_gen.py`, and `video_format_export.py` call `subprocess.run` directly to execute FFmpeg, while `video_metadata.py` and `video_format_export.py` call ffprobe. The conftest `mock_ffmpeg` fixture patches `subprocess.run` globally and is the correct base for all FFmpeg tests. For ffprobe, the mock must return a `CompletedProcess` with structured JSON in `stdout`. The SRT parser and QA analyzer are the most unit-testable scripts — they contain pure Python logic (regex parsing, math calculations) with no subprocess calls, making them straightforward to test with inline data.

The three-plan breakdown (04-01: color grade + metadata, 04-02: SRT parser + QA, 04-03: proxy gen + format export) is well-structured. Each pairing shares a primary testing concern: 04-01 involves subprocess/ffprobe mocking and Supabase upsert patterns, 04-02 involves pure-Python regex and math (no subprocess), and 04-03 involves FFmpeg command construction and format template logic. Plans 04-01 and 04-03 require the `mock_ffmpeg` fixture; Plan 04-02 does not.

**Primary recommendation:** Test functions in isolation by importing them directly. Use the existing `mock_ffmpeg` fixture for all subprocess calls. For ffprobe JSON output, construct minimal `{"format": {...}, "streams": [...]}` dicts as `stdout`. For Supabase, use the existing `mock_supabase_client` fixture with `mocker.patch("supabase.create_client", return_value=mock_supabase_client)`.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| UNIT-04 | Unit tests for `video_color_grade.py` — LUT selection, FFmpeg command construction, graded_path update | `get_lut_path` and `grade_video` are the core testable functions. `get_lut_path` is pure Python (no subprocess) — test with `tmp_path` LUT files. `grade_video` calls `subprocess.run` — use `mock_ffmpeg` fixture and inspect the `cmd` list passed to subprocess. `update_graded_path` uses lazy `supabase.create_client` — use `mock_supabase_client` + `mocker.patch("supabase.create_client")`. |
| UNIT-05 | Unit tests for `video_metadata.py` — ffprobe parsing, Supabase upsert payload, platform-specific fields | `probe_video` calls ffprobe via `subprocess.run` — mock returns JSON `stdout`. `normalize_codec` and `extract_sequence_number` are pure functions. `find_graded_file` and `check_lrf_proxy` use `os.path.isfile` — test with `tmp_path`. `upload_metadata` uses `mock_supabase_client`; test the update-vs-insert branch logic by configuring `existing_map` via mock return data. |
| UNIT-06 | Unit tests for `srt_telemetry_parser.py` — SRT frame parsing, GPS extraction, telemetry aggregation | `parse_srt_timestamp`, `parse_gps`, `parse_srt_frame`, `parse_srt_file`, and `aggregate_clip` are all pure Python (no subprocess, no I/O except `parse_srt_file` which reads a file). Test regex parsers with inline string data. `parse_srt_file` uses `tmp_path`. `aggregate_clip` requires constructing a `frames` list of dicts. `upload_to_supabase` uses lazy `supabase.create_client` and the sequence number extraction logic. |
| UNIT-07 | Unit tests for `video_qa.py` — threshold checks, pass/fail logic, QA report generation | All five check functions (`check_iso`, `check_fps`, `check_gps_drift`, `check_altitude_high`, `check_altitude_rate`) are pure Python taking `asset` dict + `thresholds` dict. `determine_qa_status` and `run_qa_checks` are pure. `fetch_video_assets`, `fetch_thresholds`, and `update_qa_status` require `mock_supabase_client`. The Supabase mock chain for `missions.select().eq().single().execute()` needs `.single()` added to the mock chain (not currently in conftest). |
| UNIT-08 | Unit tests for `video_proxy_gen.py` — proxy resolution, graded vs full fallback, FFmpeg args | `find_source_videos` uses `os.path.isdir` and `glob` — test with `tmp_path`. `generate_proxy` calls `subprocess.run` — use `mock_ffmpeg`. The resolution format validation in `generate_proxy` (`re.match(r"^\d{1,5}x\d{1,5}$")`) is testable with invalid strings. Test the graded-vs-full fallback by creating only one of the two directories in `tmp_path`. The `_graded` suffix stripping in output filename is testable without subprocess. |
| UNIT-09 | Unit tests for `video_format_export.py` — format template loading, encoding args, Supabase status update | `build_ffmpeg_command` is the primary test target — pure function returning a list. Test copy-codec path, resolution-scale path, max_duration truncation, invalid resolution rejection. `find_master_video` uses `glob` — test with `tmp_path`. `get_video_duration` calls ffprobe subprocess. `fetch_formats_from_supabase` uses lazy `supabase.create_client`. |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=7.4 (pinned) | Test runner, fixtures, assertions | Industry standard; `pythonpath=.` config in pytest.ini requires >=7.0 |
| pytest-mock | >=3.12 | `mocker` fixture, `mocker.patch()` | Auto-teardown of patches; avoids manual `unittest.mock.patch` context managers |
| unittest.mock | stdlib | `MagicMock`, `patch`, `call` | Used directly for `subprocess.CompletedProcess` construction |
| pytest.tmp_path | built-in | Temporary directories for filesystem tests | Used for LUT files, video directories, SRT files, mission folders |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| subprocess.CompletedProcess | stdlib | Return value for `mock_ffmpeg` | Construct with `args=[], returncode=0, stdout=json_str, stderr=""` |
| json | stdlib | Build ffprobe stdout payloads | `json.dumps({"format": {...}, "streams": [...]})` for probe_video tests |
| math | stdlib | Validate GPS distance calculations | QA GPS drift check uses `math.sqrt`; verify against known input/output |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `mock_ffmpeg` fixture (patches `subprocess.run`) | Patching at call site (`video_color_grade.subprocess.run`) | `subprocess.run` is not rebound at module level; patching the stdlib is correct and simpler |
| Inline `MagicMock` for Supabase | `mock_supabase_client` conftest fixture | Use the conftest fixture — it's already configured; only build inline mocks when a non-standard chain is needed (e.g., `.single()`) |
| Real `.cube` LUT files | `tmp_path` with `write_bytes(b"")` fake LUT | `get_lut_path` only checks `os.path.isfile` — zero-byte fake file is sufficient |
| Real `.srt` SRT files | Inline strings passed to `parse_srt_frame` | All SRT parsing is pure string-in → dict-out; no file I/O needed for frame-level tests |

**Installation:** Already complete (Phase 2). No new packages needed for Phase 4.

---

## Architecture Patterns

### Recommended Project Structure

```
tests/
├── conftest.py                    # Existing — mock_supabase_client, mock_ffmpeg fixtures
├── test_video_color_grade.py      # UNIT-04 — replaces stub
├── test_video_metadata.py         # UNIT-05 — replaces stub
├── test_srt_telemetry_parser.py   # UNIT-06 — replaces stub
├── test_video_qa.py               # UNIT-07 — replaces stub
├── test_video_proxy_gen.py        # UNIT-08 — replaces stub
└── test_video_format_export.py    # UNIT-09 — replaces stub
```

No new fixture files. No `fixtures/` subdirectory. No new conftest additions required for Plans 04-01, 04-02, and 04-03 except a `.single()` mock chain fix for `video_qa.py` Supabase tests (see Pitfall 2).

### Pattern 1: Import functions under test, not main()

**What:** Import only the specific functions being tested. Never call `main()` in unit tests.

**When to use:** All six test files in Phase 4.

**Example:**
```python
from video_color_grade import get_lut_path, grade_video, update_graded_path
from video_qa import check_iso, check_fps, determine_qa_status, run_qa_checks
from srt_telemetry_parser import parse_srt_timestamp, parse_gps, parse_srt_frame, aggregate_clip
```

### Pattern 2: mock_ffmpeg fixture for subprocess.run

**What:** The conftest `mock_ffmpeg` fixture patches `subprocess.run` globally for the test. Inspect `mock_ffmpeg.call_args` to verify the command list passed to FFmpeg.

**When to use:** All tests for `grade_video`, `generate_proxy`, `build_ffmpeg_command`/`export_format`, and `get_video_duration`.

**Example:**
```python
def test_grade_video_builds_lut3d_command(mock_ffmpeg, tmp_path):
    lut_file = tmp_path / "Sentinel_DLogM.cube"
    lut_file.write_bytes(b"")
    input_path = str(tmp_path / "DJI_0001.MP4")
    output_path = str(tmp_path / "DJI_0001_graded.MP4")

    from video_color_grade import grade_video
    ok, stderr = grade_video(input_path, output_path, str(lut_file))

    assert ok is True
    cmd = mock_ffmpeg.call_args[0][0]  # positional args[0] = cmd list
    assert cmd[0] == "ffmpeg"
    assert "-vf" in cmd
    vf_idx = cmd.index("-vf")
    assert "lut3d=" in cmd[vf_idx + 1]
    assert "-c:v" in cmd
    assert "libx264" in cmd
```

### Pattern 3: ffprobe JSON stdout mock

**What:** `probe_video` and `get_video_duration` parse `subprocess.run(...).stdout` as JSON. Configure `mock_ffmpeg.return_value.stdout` with a serialized ffprobe JSON response.

**When to use:** `test_video_metadata.py` (probe_video), `test_video_format_export.py` (get_video_duration).

**Example:**
```python
FFPROBE_SAMPLE = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 3840,
            "height": 2160,
            "r_frame_rate": "30/1",
        },
        {
            "codec_type": "audio",
            "codec_name": "aac",
        }
    ],
    "format": {
        "duration": "30.0",
        "size": "104857600",
        "bit_rate": "27962026",
    }
}

def test_probe_video_parses_4k(mock_ffmpeg, tmp_path):
    import json
    mock_ffmpeg.return_value.returncode = 0
    mock_ffmpeg.return_value.stdout = json.dumps(FFPROBE_SAMPLE)

    from video_metadata import probe_video
    result = probe_video(str(tmp_path / "DJI_0001.MP4"))

    assert result["resolution"] == "3840x2160"
    assert result["codec"] == "H.264"
    assert result["fps"] == 30.0
    assert result["duration_seconds"] == 30.0
    assert result["file_size_bytes"] == 104857600
    assert result["audio_codec"] == "aac"
```

### Pattern 4: Supabase mock for lazy-import scripts

**What:** All six video scripts use lazy imports (`from supabase import create_client` inside functions). Patch `"supabase.create_client"` (the origin module), NOT `"video_color_grade.create_client"`.

**When to use:** `update_graded_path`, `upload_metadata`, `upload_to_supabase`, `fetch_thresholds`, `fetch_video_assets`, `update_qa_status`, `fetch_formats_from_supabase`.

**Example:**
```python
def test_update_graded_path_calls_upsert(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch.dict(os.environ, {
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_SERVICE_KEY": "test-key",
    })

    from video_color_grade import update_graded_path
    result = update_graded_path("mission-uuid", "DJI_0001.MP4", "/path/to/graded.MP4")

    assert result is True
    mock_supabase_client.table.assert_called_with("video_assets")
    mock_supabase_client.table.return_value.upsert.assert_called_once()
    upsert_call = mock_supabase_client.table.return_value.upsert.call_args
    payload = upsert_call[0][0]
    assert payload["mission_id"] == "mission-uuid"
    assert payload["graded_path"] == "/path/to/graded.MP4"
```

### Pattern 5: Pure QA logic tests (no mocking needed)

**What:** All five `check_*` functions in `video_qa.py` take plain dicts as input and return plain dicts or None. These are the most straightforward tests — no mocking required.

**When to use:** All `check_iso`, `check_fps`, `check_gps_drift`, `check_altitude_high`, `check_altitude_rate`, `determine_qa_status`, and `run_qa_checks` tests.

**Example:**
```python
from video_qa import check_iso, check_fps, determine_qa_status, DEFAULT_THRESHOLDS

def test_check_iso_pass():
    asset = {"iso_max": 400}
    assert check_iso(asset, DEFAULT_THRESHOLDS) is None

def test_check_iso_warning():
    asset = {"iso_max": 1000}  # > 800 ceiling, < 800*1.5=1200 → warning
    result = check_iso(asset, DEFAULT_THRESHOLDS)
    assert result["flag"] == "iso_spike"
    assert result["severity"] == "warning"

def test_check_iso_fail():
    asset = {"iso_max": 1600}  # > 1200 → fail
    result = check_iso(asset, DEFAULT_THRESHOLDS)
    assert result["severity"] == "fail"

def test_determine_qa_status_from_flags():
    assert determine_qa_status([]) == "pass"
    assert determine_qa_status([{"severity": "warning"}]) == "review"
    assert determine_qa_status([{"severity": "warning"}, {"severity": "fail"}]) == "fail"
```

### Pattern 6: SRT parsing with inline string fixtures

**What:** SRT parsing functions accept plain strings, not file paths. Inline SRT block strings are the cleanest test data.

**When to use:** `parse_srt_timestamp`, `parse_gps`, `parse_srt_frame` tests in `test_srt_telemetry_parser.py`.

**Example:**
```python
from srt_telemetry_parser import parse_srt_timestamp, parse_gps, parse_srt_frame

def test_parse_srt_timestamp_converts_to_seconds():
    assert parse_srt_timestamp("00:01:30,500") == 90.5
    assert parse_srt_timestamp("00:00:00,000") == 0.0
    assert parse_srt_timestamp("01:00:00,000") == 3600.0

def test_parse_gps_standard_format():
    text = "F/2.8, SS 500, ISO 100, EV 0, GPS (36.8451, -76.2883, 45)"
    result = parse_gps(text)
    assert result["lat"] == pytest.approx(36.8451)
    assert result["lon"] == pytest.approx(-76.2883)
    assert result["alt"] == pytest.approx(45.0)

def test_parse_gps_bracket_format():
    text = "[latitude: 36.8451] [longitude: -76.2883] [altitude: 45.0]"
    result = parse_gps(text)
    assert result["lat"] == pytest.approx(36.8451)

def test_parse_srt_frame_full():
    text = "F/2.8, SS 500, ISO 200, EV -0.3, CT 5500, GPS (36.8, -76.3, 30), D 15.3m"
    frame = parse_srt_frame(text)
    assert frame["iso"] == 200
    assert frame["shutter_speed"] == 500
    assert frame["aperture"] == pytest.approx(2.8)
    assert frame["ev"] == pytest.approx(-0.3)
    assert frame["color_temp"] == 5500
    assert frame["gps"]["lat"] == pytest.approx(36.8)
    assert frame["distance_m"] == pytest.approx(15.3)
```

### Pattern 7: build_ffmpeg_command as the primary export test target

**What:** `build_ffmpeg_command` in `video_format_export.py` is a pure function returning a list. It is the most important function to test — it determines the entire encoding pipeline. Test it without any subprocess calls.

**When to use:** `test_video_format_export.py` for all encoding-logic tests.

**Example:**
```python
from video_format_export import build_ffmpeg_command

def test_build_ffmpeg_command_copy_codec():
    fmt = {"name": "client_4k", "resolution": "3840x2160", "codec": "copy"}
    cmd = build_ffmpeg_command("/input/master.mp4", "/output/master_client_4k.mp4", fmt)
    assert "-c:v" in cmd
    assert "copy" in cmd
    assert "-vf" not in cmd  # No scale filter for copy codec

def test_build_ffmpeg_command_with_truncation():
    fmt = {"name": "instagram_reels", "resolution": "1080x1920", "codec": "libx264", "max_duration_sec": 90}
    cmd = build_ffmpeg_command("/input/master.mp4", "/out.mp4", fmt, source_duration=120.0)
    assert "-t" in cmd
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "90"

def test_build_ffmpeg_command_no_truncation_when_short():
    fmt = {"name": "instagram_reels", "resolution": "1080x1920", "codec": "libx264", "max_duration_sec": 90}
    cmd = build_ffmpeg_command("/input/master.mp4", "/out.mp4", fmt, source_duration=60.0)
    assert "-t" not in cmd

def test_build_ffmpeg_command_invalid_resolution_raises():
    fmt = {"name": "evil", "resolution": "../../etc/passwd", "codec": "libx264"}
    with pytest.raises(ValueError, match="Invalid resolution"):
        build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)
```

### Anti-Patterns to Avoid

- **Calling `main()` in unit tests:** All six scripts have `sys.exit()` in `main()`. Test functions directly.
- **Real filesystem paths like `E:\Sentinel\LUTs\`:** Pass path parameters to functions directly; use `tmp_path` for filesystem tests.
- **Asserting exact ffmpeg command string:** Assert specific list elements (`cmd[0] == "ffmpeg"`, `"-crf" in cmd`) rather than the full list — minor formatting changes would break string assertions.
- **Real ffprobe subprocess calls:** All `probe_video` and `get_video_duration` calls must use `mock_ffmpeg`. The test environment has ffprobe available locally but tests must not depend on it.
- **Unpatched SUPABASE_URL/SUPABASE_SERVICE_KEY:** `update_graded_path` and `upload_to_supabase` guard on env vars before importing supabase. Tests must set these via `mocker.patch.dict(os.environ, {...})` or they return `False`/raise early.
- **Sharing conftest mock_supabase_client state between tests:** The conftest fixture is function-scoped (default). Each test gets a fresh `MagicMock` — do not configure mock state in module-level setup.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fake ffprobe JSON output | Custom subprocess wrapper | `mock_ffmpeg.return_value.stdout = json.dumps(payload)` | `probe_video` calls `subprocess.run` and parses `.stdout` directly |
| LUT file existence check | File path string manipulation | `tmp_path / "Sentinel_DLogM.cube"` with `.write_bytes(b"")` | `get_lut_path` only checks `os.path.isfile` — zero-byte file is sufficient |
| GPS distance calculation | Custom math helper | Compute expected value with same formula: `math.sqrt(dlat**2 + dlon**2)` | Verify the calculation is correct, not that Python's math works |
| Format template fixture | Supabase schema replication | Inline `DEFAULT_FORMATS` list from `video_format_export.py` | Tests should use the same data the script uses; no Supabase required for `build_ffmpeg_command` tests |
| SRT fixture files | Binary `.srt` test assets | Inline multi-line strings | `parse_srt_frame` takes a string; `parse_srt_file` uses `tmp_path` with `.write_text()` |

**Key insight:** The video pipeline scripts are more testable than they appear because the core processing logic (`build_ffmpeg_command`, all `check_*` functions, all SRT parsers) is pure Python. Subprocess calls and Supabase calls are always in thin wrapper functions that are easy to isolate.

---

## Common Pitfalls

### Pitfall 1: SUPABASE_URL env var guard prevents Supabase code from running

**What goes wrong:** `update_graded_path` in `video_color_grade.py` returns `False` immediately if `SUPABASE_URL` or `SUPABASE_SERVICE_KEY` is empty. Tests that don't set these env vars will silently test the early-return path only.

**Why it happens:** The guard is `if not SUPABASE_URL or not SUPABASE_SERVICE_KEY: return False`. These are module-level constants set at import time from `os.environ.get(...)`. In CI, they default to `""`.

**How to avoid:** Set environment variables before the function is called using `mocker.patch.dict`:
```python
mocker.patch.dict(os.environ, {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SERVICE_KEY": "test-key",
})
```
Note: These module-level constants are read once at import time. Patching `os.environ` after import does NOT update `SUPABASE_URL` in `video_color_grade.py`. Instead, patch the module-level variable directly:
```python
mocker.patch("video_color_grade.SUPABASE_URL", "https://test.supabase.co")
mocker.patch("video_color_grade.SUPABASE_SERVICE_KEY", "test-key")
```
This applies to ALL six video scripts that use `SUPABASE_URL = os.environ.get(...)` at module level.

**Warning signs:** Test passes but `mock_supabase_client.table` is never called — means the early-return guard fired.

### Pitfall 2: mock_supabase_client doesn't cover .single() chains

**What goes wrong:** `fetch_thresholds` in `video_qa.py` calls `.single().execute()` on the query chain:
```python
mission = client.table("missions").select("package_type").eq("id", mission_id).single().execute()
```
The existing `mock_supabase_client` conftest fixture configures `select().eq().execute()` but NOT `select().eq().single().execute()`. The call will return a MagicMock (auto-created) but `.data` will not be a predictable value.

**Why it happens:** The conftest was designed for the ingest scripts which don't use `.single()`. The video QA script uses `.single()` for mission and template lookups.

**How to avoid:** Configure the `.single()` chain inline in the test, or add it to the conftest fixture. Inline approach:
```python
def test_fetch_thresholds_returns_default_on_no_mission(mock_supabase_client, mocker):
    mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    mocker.patch("video_qa.SUPABASE_URL", "https://test.supabase.co")
    mocker.patch("video_qa.SUPABASE_SERVICE_KEY", "test-key")
    # Configure .single().execute().data = None (no mission found)
    mock_supabase_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None

    from video_qa import fetch_thresholds, DEFAULT_THRESHOLDS
    result = fetch_thresholds(mock_supabase_client, "nonexistent-uuid")
    assert result == DEFAULT_THRESHOLDS
```

**Warning signs:** Test passes unexpectedly, or `fetch_thresholds` doesn't return `DEFAULT_THRESHOLDS` when expected.

### Pitfall 3: LUT path escape for FFmpeg filter syntax

**What goes wrong:** `grade_video` escapes the LUT path for FFmpeg's filter graph syntax:
```python
escaped_lut = lut_path.replace("\\", "/").replace(":", "\\:")
```
On Windows, `E:\Sentinel\LUTs\Sentinel_DLogM.cube` becomes `E\:/Sentinel/LUTs/Sentinel_DLogM.cube`. Tests that assert exact `-vf` argument content must account for this transformation.

**Why it happens:** The FFmpeg `lut3d` filter uses its own path syntax different from the OS path separator.

**How to avoid:** In tests, use forward-slash paths or `tmp_path` paths (which pytest provides as posixpath strings on Windows too). Assert that `-vf` contains `lut3d=` without asserting the exact escaped path. Or compute the expected escaped value the same way the source does:
```python
expected_escaped = str(lut_file).replace("\\", "/").replace(":", "\\:")
assert f"lut3d='{expected_escaped}'" in cmd[cmd.index("-vf") + 1]
```

### Pitfall 4: aggregate_clip requires non-empty frames with GPS data

**What goes wrong:** `aggregate_clip` checks `len(frames)` and conditionally adds `gps_start_lat` etc. only if `gps_points` is non-empty. Tests that pass frames without GPS data will get a clip without GPS fields — this is correct behavior, but assertions must match.

**Why it happens:** GPS is optional in SRT frames. The function gracefully handles missing GPS.

**How to avoid:** Build test frame lists explicitly:
```python
frames_with_gps = [
    {"timestamp_start": 0.0, "timestamp_end": 0.033, "iso": 100,
     "gps": {"lat": 36.845, "lon": -76.288, "alt": 30.0}},
    {"timestamp_start": 0.033, "timestamp_end": 0.066, "iso": 100,
     "gps": {"lat": 36.846, "lon": -76.289, "alt": 31.0}},
]
clip = aggregate_clip(frames_with_gps, "DJI_0001.MP4", source_platform="mini4pro")
assert "gps_start_lat" in clip
assert clip["gps_start_lat"] == pytest.approx(36.845)
```

### Pitfall 5: find_source_videos graded-vs-full fallback depends on directory existence AND file presence

**What goes wrong:** `find_source_videos` in `video_proxy_gen.py` iterates `[graded_dir, full_dir]` and returns the first directory that exists AND has video files. Creating an empty `graded_dir` in `tmp_path` will cause the function to skip it and fall through to `full_dir`.

**Why it happens:** The check is:
```python
if not os.path.isdir(source_dir): continue
videos = []
for pattern in VIDEO_EXTENSIONS: videos.extend(glob.glob(...))
if videos: return sorted(set(videos)), source_dir
```
Both conditions must be met: directory exists AND contains video files.

**How to avoid:** Test the fallback by creating `graded_dir` as an empty directory — the function will skip it and use `full_dir`:
```python
def test_find_source_videos_falls_back_to_full(tmp_path):
    graded_dir = tmp_path / "video" / "graded"
    graded_dir.mkdir(parents=True)  # Empty — no videos
    full_dir = tmp_path / "video" / "full"
    full_dir.mkdir(parents=True)
    (full_dir / "DJI_0001.MP4").write_bytes(b"fake")

    from video_proxy_gen import find_source_videos
    videos, source = find_source_videos(str(tmp_path))
    assert len(videos) == 1
    assert "full" in source
```

### Pitfall 6: probe_video returns None when ffprobe returns non-zero or invalid JSON

**What goes wrong:** `probe_video` returns `None` (not raises) on ffprobe failure. Tests must check return value, not exception.

**Why it happens:** The function has `try/except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError): return None` and also `if result.returncode != 0: return None`.

**How to avoid:**
```python
def test_probe_video_returns_none_on_ffprobe_failure(mock_ffmpeg):
    mock_ffmpeg.return_value.returncode = 1
    mock_ffmpeg.return_value.stdout = ""
    from video_metadata import probe_video
    assert probe_video("/fake/path.mp4") is None
```

### Pitfall 7: check_gps_drift only fires for short clips (< 30 seconds)

**What goes wrong:** The GPS drift check has a guard: `if duration > 0 and duration < 30 and distance > threshold_m`. Tests with `duration_seconds >= 30` will always return `None` from `check_gps_drift`, even with extreme drift.

**Why it happens:** The check is intentionally scoped to hover footage only (short clips should stay put).

**How to avoid:** Use a short duration in the test asset dict:
```python
asset = {
    "gps_start_lat": 36.8451, "gps_start_lon": -76.2883,
    "gps_end_lat": 36.8551, "gps_end_lon": -76.2783,
    "duration_seconds": 10,  # Must be < 30 to trigger drift check
}
result = check_gps_drift(asset, DEFAULT_THRESHOLDS)
assert result is not None
assert result["flag"] == "gps_drift"
```

---

## Code Examples

Verified patterns from direct source code inspection:

### LUT Selection Per Platform

```python
# Source: video_color_grade.py — PLATFORM_LUTS dict + get_lut_path function
# Key: get_lut_path returns None if file doesn't exist on disk, not if platform is unknown
# Only platforms "m4e", "m3e", "mini4pro" are defined. Unknown platform → None (no lut_name).
# Override path: absolute path wins; relative path resolves relative to lut_dir.

def test_get_lut_path_m4e_platform(tmp_path):
    lut_file = tmp_path / "Sentinel_DLogM.cube"
    lut_file.write_bytes(b"")
    from video_color_grade import get_lut_path
    result = get_lut_path("m4e", lut_dir=str(tmp_path))
    assert result == str(lut_file)

def test_get_lut_path_mini4pro_platform(tmp_path):
    lut_file = tmp_path / "Sentinel_DCinelike.cube"
    lut_file.write_bytes(b"")
    from video_color_grade import get_lut_path
    result = get_lut_path("mini4pro", lut_dir=str(tmp_path))
    assert result == str(lut_file)

def test_get_lut_path_unknown_platform_returns_none(tmp_path):
    from video_color_grade import get_lut_path
    assert get_lut_path("phantom4", lut_dir=str(tmp_path)) is None

def test_get_lut_path_file_not_found_returns_none(tmp_path):
    # Platform is valid, file just doesn't exist
    from video_color_grade import get_lut_path
    assert get_lut_path("m4e", lut_dir=str(tmp_path)) is None
```

### normalize_codec Mapping

```python
# Source: video_metadata.py — normalize_codec function
# Simple dict-based mapping. Unknown codec returns .upper() of raw string.
from video_metadata import normalize_codec

def test_normalize_codec_known_codecs():
    assert normalize_codec("h264") == "H.264"
    assert normalize_codec("hevc") == "H.265"
    assert normalize_codec("h265") == "H.265"
    assert normalize_codec("av1") == "AV1"
    assert normalize_codec("prores") == "ProRes"

def test_normalize_codec_unknown_returns_uppercase():
    assert normalize_codec("vp8") == "VP8"
    assert normalize_codec("") is None
```

### extract_sequence_number — DJI Filename Regex

```python
# Source: video_metadata.py lines 400-408 (same logic as srt_telemetry_parser.py)
# Two patterns: M4E timestamp format vs Mini 4 Pro sequential format
from video_metadata import extract_sequence_number

def test_extract_sequence_number_m4e_format():
    assert extract_sequence_number("DJI_20260218101500_0015_D.MP4") == 15

def test_extract_sequence_number_mini4pro_format():
    assert extract_sequence_number("DJI_0015.MP4") == 15

def test_extract_sequence_number_no_match_returns_zero():
    assert extract_sequence_number("RANDOM_0015.MP4") == 0
```

### aggregate_clip Duration and FPS Calculation

```python
# Source: srt_telemetry_parser.py — aggregate_clip function
# duration = last_ts_end - first_ts_start
# fps = frame_count / duration
# altitude_max_change_rate in ft/s (converted from m/s)
frames = [
    {"timestamp_start": 0.0, "timestamp_end": 0.033,
     "gps": {"lat": 36.845, "lon": -76.288, "alt": 30.0}, "iso": 100},
    {"timestamp_start": 0.033, "timestamp_end": 0.066,
     "gps": {"lat": 36.845, "lon": -76.288, "alt": 30.5}, "iso": 100},
]
# duration = 0.066 - 0.0 = 0.066
# fps = 2 / 0.066 ≈ 30.3
from srt_telemetry_parser import aggregate_clip
clip = aggregate_clip(frames, "DJI_0001.MP4", source_platform="mini4pro")
assert clip["frame_count"] == 2
assert clip["fps"] == pytest.approx(30.3, abs=0.2)
assert clip["gps_start_lat"] == pytest.approx(36.845)
```

### check_altitude_high — meters-to-feet conversion

```python
# Source: video_qa.py — check_altitude_high
# Uses altitude_max if present, falls back to altitude_avg
# Threshold: 400 ft AGL (FAA limit)
# alt_ft = alt_m * 3.28084
from video_qa import check_altitude_high

def test_check_altitude_high_below_limit():
    asset = {"altitude_max": 100.0}  # 100m * 3.28 = 328ft — under 400ft
    assert check_altitude_high(asset, {}) is None

def test_check_altitude_high_above_limit():
    asset = {"altitude_max": 130.0}  # 130m * 3.28 = 426ft — over 400ft
    result = check_altitude_high(asset, {})
    assert result["flag"] == "altitude_high"
    assert result["severity"] == "warning"
    assert result["value"] == pytest.approx(426.5, abs=0.5)

def test_check_altitude_high_uses_avg_when_max_absent():
    asset = {"altitude_avg": 130.0}  # no altitude_max
    result = check_altitude_high(asset, {})
    assert result is not None
```

### build_ffmpeg_command — copy codec vs re-encode

```python
# Source: video_format_export.py — build_ffmpeg_command function
# copy codec: -c:v copy -c:a copy (no -vf scale filter)
# libx264/libx265: -vf scale + -c:v codec -crf 18 -preset medium -r fps -c:a aac -b:a 192k
from video_format_export import build_ffmpeg_command

def test_build_ffmpeg_command_libx265_includes_crf_preset():
    fmt = {"name": "youtube", "resolution": "3840x2160", "fps": 30, "codec": "libx265"}
    cmd = build_ffmpeg_command("/in.mp4", "/out.mp4", fmt)
    assert "-crf" in cmd
    assert "18" in cmd
    assert "-preset" in cmd
    assert "medium" in cmd
    assert "-c:a" in cmd
    assert "aac" in cmd
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `datetime.utcnow()` | `datetime.now(timezone.utc)` | Phase 1 (DEPR-01) | Not directly relevant to Phase 4 — none of the six video scripts use datetime |
| `drone_jobs` table | `missions` table | Pre-Phase 1 review | `video_qa.py` already uses `missions` table — tests must match |
| Supabase unique constraint on video_assets(mission_id,filename) | Upsert with `on_conflict="mission_id,filename"` | Phase 1 (GAP-10) | `update_graded_path` uses upsert — tests must verify the `on_conflict` arg is passed |

**Deprecated/outdated:**
- `datetime.UTC` class attribute: Does not exist in Python — must use `timezone.utc`. Already fixed in Phase 1/3. The six video scripts in Phase 4 do not use datetime, so this is not a concern.
- None of the six video scripts have issues requiring source fixes before tests can be written.

---

## Open Questions

1. **Does the conftest `mock_supabase_client` need `.single()` added for Phase 4?**
   - What we know: `video_qa.py` `fetch_thresholds` uses `.single().execute()`. The conftest does not have this chain. `video_format_export.py` `fetch_formats_from_supabase` also uses `.single().execute()`.
   - What's unclear: Whether to add `.single()` support to conftest (shared, cleaner) or configure it inline per test (isolated, no conftest changes).
   - Recommendation: Add `.single()` support to conftest in the Plan 04-01 task that first needs it. One-line addition: `mock_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None`. This is a non-breaking addition.

2. **Should `upload_metadata` update-vs-insert branch have separate tests?**
   - What we know: `upload_metadata` branches on whether `filename in existing_map`. The `existing_map` is built from `client.table("video_assets").select("id, filename").eq("mission_id", ...).execute().data`. Setting `mock_table.select.return_value.eq.return_value.execute.return_value.data` controls which branch is taken.
   - What's unclear: Whether the conftest select chain stub returns `[]` (empty — triggers insert branch) by default. It does: `mock_table.select.return_value.eq.return_value.execute.return_value.data = []`.
   - Recommendation: Write two distinct tests: (a) conftest default (empty existing_map) → tests insert branch, (b) override to `[{"id": "existing-id", "filename": "DJI_0001.MP4"}]` → tests update branch.

3. **Are `video_proxy_gen.generate_proxy` and `video_color_grade.grade_video` fully equivalent for subprocess testing?**
   - What we know: Both call `subprocess.run(cmd, capture_output=True, text=True)` and check `result.returncode == 0`. Both return `(bool, stderr_string)`.
   - What's unclear: Whether the `mock_ffmpeg` fixture's default `returncode=0` is sufficient, or if tests need to also set `stdout=""`.
   - Recommendation: The default `mock_ffmpeg` fixture already sets `returncode=0, stdout="", stderr=""` — sufficient for success-path tests. For failure-path tests, configure `mock_ffmpeg.return_value.returncode = 1` and `mock_ffmpeg.return_value.stderr = "Error message"`.

---

## Sources

### Primary (HIGH confidence)

- Direct source inspection: `video_color_grade.py`, `video_metadata.py`, `srt_telemetry_parser.py`, `video_qa.py`, `video_proxy_gen.py`, `video_format_export.py` — all functions catalogued from file reads
- `tests/conftest.py` — existing fixture patterns and mock chain configurations verified directly
- `tests/test_video_color_grade.py` et al. — existing stubs confirmed (placeholder only, import at module top)
- `pytest.ini` — `pythonpath = .` config confirmed; `testpaths = tests` confirmed
- `checkpoint.py` — checkpoint pattern confirmed (all six video scripts use `load_checkpoint`/`save_checkpoint`)
- `.planning/STATE.md` — Phase 2 decisions about patch targets, importorskip patterns, lazy import mock targets confirmed

### Secondary (MEDIUM confidence)

- `.planning/phases/03-ingest-layer-tests/03-RESEARCH.md` — established testing patterns for this codebase (subprocess mocking, lazy import patching, `__new__` instantiation) are consistent across phases
- `.planning/STATE.md` decisions log — Phase 01-04 decision: "Supabase unique constraint on video_assets(mission_id,filename): not verifiable in CI — Phase 4 tests should mock or verify"

### Tertiary (LOW confidence)

- None — all findings grounded in source code for this phase.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified in requirements.txt and Phase 2 infrastructure; no new packages needed
- Architecture: HIGH — derived directly from reading all six source files; function signatures and logic are clear
- Pitfalls: HIGH — all pitfalls identified from actual source code patterns (module-level env var guards, `.single()` chain gap, LUT escape logic, GPS drift short-clip guard, graded-vs-full fallback behavior)
- Supabase mock chains: MEDIUM — conftest covers most patterns; `.single()` chain is a gap that needs one-line fix

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable Python/pytest ecosystem; source scripts are complete and won't change before tests are written)
