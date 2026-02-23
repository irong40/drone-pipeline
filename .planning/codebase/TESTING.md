# Testing Patterns

**Analysis Date:** 2026-02-23

## Current State

**Status:** No tests exist yet

All 14 scripts in the pipeline are standalone CLI tools with no unit/integration test suite. Each script is manually tested during development. The scripts have been through a 3-agent code review process (2026-02-22) that verified code quality, security, and production readiness without formal test coverage.

## Test Framework Setup (Recommended)

**Runner:**
- `pytest` [version not locked, recommend >=7.0]
- Config file: `pytest.ini` (to be created in project root)

**Assertion Library:**
- `pytest` built-in assertions

**Test discovery pattern:**
- Test files: `test_<script_name>.py` co-located in `.testing/` subdirectory
- Test directory structure: `/c/Users/redle/drone-pipeline/.testing/`

**Run commands (proposed):**
```bash
pytest                              # Run all tests
pytest --watch                      # Watch mode (requires pytest-watch)
pytest --cov=. --cov-report=html   # Coverage report (requires pytest-cov)
pytest -v                           # Verbose output
pytest -k "test_ingest"            # Run specific test class/function
```

## Test Organization Structure

**Proposed layout:**
```
.testing/
├── conftest.py              # Shared fixtures, mock setup
├── fixtures/                # Fixture data
│   ├── missions.json        # Sample missions config
│   ├── sample_srt.srt       # Sample telemetry file
│   └── sample_video.mp4     # Stub video (or use factory)
├── test_ingest_sorter.py
├── test_video_metadata.py
├── test_srt_telemetry_parser.py
├── test_gdrive_upload.py
├── test_video_qa.py
├── test_platform_detect.py
├── test_folder_watcher.py
└── integration/
    ├── conftest.py          # Integration-specific setup
    └── test_full_pipeline.py
```

## Test Structure Patterns (Expected)

**Unit test suite for each script:**

Each test module will test the public functions of its corresponding script. Pattern:

```python
import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import module under test
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ingest_sorter import (
    detect_platform,
    extract_sequence_number,
    scan_sd_card,
    sort_by_sequence_ranges,
    validate_timestamp_gaps,
)


class TestPlatformDetection:
    """Test drone platform detection from DJI filenames."""

    def test_detect_platform_mini4pro(self):
        """Mini 4 Pro filename pattern DJI_NNNN."""
        assert detect_platform("DJI_0015.JPG") == "mini4pro"

    def test_detect_platform_m4e(self):
        """M4E/M3E timestamp filename pattern."""
        assert detect_platform("DJI_20260218101500_0015_D.JPG") == "m4e"

    def test_detect_platform_unknown(self):
        """Non-DJI filename."""
        assert detect_platform("random_photo.JPG") is None


class TestSequenceExtraction:
    """Test sequence number extraction from DJI filenames."""

    def test_extract_sequence_mini4pro(self):
        assert extract_sequence_number("DJI_0015.JPG") == 15

    def test_extract_sequence_m4e(self):
        assert extract_sequence_number("DJI_20260218101500_0042_D.MP4") == 42

    def test_extract_sequence_invalid(self):
        assert extract_sequence_number("not_dji.jpg") is None


class TestScanSDCard:
    """Test SD card file scanning and inventory."""

    def test_scan_sd_card_finds_files(self, tmp_path):
        """Scan creates correct file metadata dicts."""
        # Create temporary DJI files
        source = tmp_path / "DCIM" / "DJI_001"
        source.mkdir(parents=True)
        (source / "DJI_0001.JPG").write_text("fake")
        (source / "DJI_0002.MP4").write_text("fake")

        files = scan_sd_card(str(source))

        assert len(files) == 2
        assert files[0]["sequence"] == 1
        assert files[0]["extension"] == "JPG"
        assert files[1]["sequence"] == 2
        assert files[1]["extension"] == "MP4"

    def test_scan_sd_card_skips_non_dji(self, tmp_path):
        """Non-DJI files are ignored."""
        source = tmp_path / "DCIM"
        source.mkdir(parents=True)
        (source / "DJI_0001.JPG").write_text("fake")
        (source / "OTHER_0001.JPG").write_text("fake")

        files = scan_sd_card(str(source))

        assert len(files) == 1
        assert files[0]["filename"] == "DJI_0001.JPG"


class TestSortBySequenceRanges:
    """Test mission sorting by sequence ranges."""

    def test_sort_by_sequence_ranges(self):
        """Files assigned to missions by sequence."""
        files = [
            {"filename": "DJI_0001.JPG", "sequence": 1},
            {"filename": "DJI_0002.JPG", "sequence": 2},
            {"filename": "DJI_0010.JPG", "sequence": 10},
        ]
        missions_config = [
            {
                "mission_id": "uuid-1",
                "sequence_start": 1,
                "sequence_end": 5,
            },
            {
                "mission_id": "uuid-2",
                "sequence_start": 6,
                "sequence_end": 15,
            },
        ]

        sorted_missions, unassigned = sort_by_sequence_ranges(files, missions_config)

        assert len(sorted_missions["uuid-1"]) == 2
        assert len(sorted_missions["uuid-2"]) == 1
        assert len(unassigned) == 0

    def test_sort_by_sequence_ranges_unassigned(self):
        """Files outside ranges marked as unassigned."""
        files = [
            {"filename": "DJI_0001.JPG", "sequence": 1},
            {"filename": "DJI_0050.JPG", "sequence": 50},  # Outside range
        ]
        missions_config = [
            {"mission_id": "uuid-1", "sequence_start": 1, "sequence_end": 10}
        ]

        sorted_missions, unassigned = sort_by_sequence_ranges(files, missions_config)

        assert len(unassigned) == 1
        assert unassigned[0]["sequence"] == 50


class TestValidateTimestampGaps:
    """Test mission boundary detection via timestamp gaps."""

    def test_validate_timestamp_gaps_no_warning(self):
        """Timestamps within gap threshold pass validation."""
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        files = [
            {
                "filename": "DJI_0001.MP4",
                "sequence": 1,
                "timestamp": now,
            },
            {
                "filename": "DJI_0002.MP4",
                "sequence": 2,
                "timestamp": now + timedelta(seconds=20),
            },
        ]
        missions_config = [
            {"mission_id": "uuid-1", "sequence_start": 1, "sequence_end": 2}
        ]

        warnings = validate_timestamp_gaps(files, missions_config, gap_minutes=30)

        assert len(warnings) == 0

    def test_validate_timestamp_gaps_warning(self):
        """Large gaps between files trigger warnings."""
        from datetime import datetime, timedelta
        now = datetime.utcnow()
        files = [
            {
                "filename": "DJI_0001.MP4",
                "sequence": 1,
                "timestamp": now,
            },
            {
                "filename": "DJI_0002.MP4",
                "sequence": 2,
                "timestamp": now + timedelta(minutes=45),  # 45min gap
            },
        ]
        missions_config = [
            {"mission_id": "uuid-1", "sequence_start": 1, "sequence_end": 2}
        ]

        warnings = validate_timestamp_gaps(files, missions_config, gap_minutes=30)

        assert len(warnings) == 1
        assert "45min gap" in warnings[0]
```

## Test Coverage Goals

**Priority 1 — Core parsing/extraction functions:**
- File scanning and metadata extraction (`scan_sd_card`)
- Sequence number extraction from all DJI filename patterns
- Platform detection (filename patterns, EXIF fallback)
- SRT frame parsing and GPS/telemetry extraction
- Mission sorting by sequence ranges

**Priority 2 — Validation logic:**
- Timestamp gap detection (mission boundary validation)
- QA threshold checks (ISO ceiling, FPS minimum, GPS drift)
- Path traversal protection in copy operations

**Priority 3 — Data transformation:**
- Codec normalization (ffprobe → human-readable)
- Address sanitization for delivery filenames
- Altitude units conversion (meters to feet)
- GPS distance calculations (lat/lon to meters)

**Priority 4 — Integration scenarios:**
- End-to-end ingest: scan → sort → copy → inventory
- Telemetry collection: SRT parse → aggregate → upload
- Color grading: video discovery → FFmpeg → output verification

## Mocking Patterns (Expected)

**What to mock:**
- External service calls:
  - `requests.post()` for n8n webhooks
  - `supabase.create_client()` for database operations
  - `google.oauth2.service_account.Credentials` for Drive API
  - `subprocess.run()` for FFmpeg/ffprobe commands
  - File I/O operations where test data isn't needed

**What NOT to mock:**
- Core parsing logic (regex, string manipulation, calculations)
- Filesystem operations (use `tmp_path` fixture for real file ops)
- Python standard library functions (logging, json, argparse)

**Mocking examples (proposed):**

```python
@patch('requests.post')
def test_fire_webhook_success(mock_post):
    """Webhook POST succeeds."""
    mock_post.return_value = Mock(status_code=200)

    from gdrive_upload import fire_webhook
    result = fire_webhook({"mission_id": "uuid"})

    assert result is True
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert "webhook" in args[0]


@patch('subprocess.run')
def test_grade_video_ffmpeg_success(mock_run):
    """Color grading runs FFmpeg successfully."""
    mock_run.return_value = Mock(returncode=0, stderr="")

    from video_color_grade import grade_video
    success, stderr = grade_video(
        "/input.mp4",
        "/output.mp4",
        "/path/to.cube"
    )

    assert success is True
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ffmpeg" in cmd[0]
    assert "lut3d" in str(cmd)


@patch('supabase.create_client')
def test_upload_metadata_update_existing(mock_create_client):
    """Metadata upload updates existing video_assets record."""
    mock_client = MagicMock()
    mock_create_client.return_value = mock_client
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    mock_select = MagicMock()
    mock_table.select.return_value = mock_select
    mock_select.eq.return_value.execute.return_value = Mock(
        data=[{"id": "record-uuid", "filename": "DJI_0001.MP4"}]
    )

    from video_metadata import upload_metadata
    metadata = [
        {
            "filename": "DJI_0001.MP4",
            "status": "ok",
            "file_size_bytes": 1024000,
            "resolution": "3840x2160",
            "codec": "H.264",
            "color_profile": "d_log_m",
            "has_lrf_proxy": True,
            "graded_path": None,
            "fps": 30.0,
            "duration_seconds": 45.6,
        }
    ]

    updated, inserted = upload_metadata(metadata, "mission-uuid")

    assert updated == 1
    assert inserted == 0
```

## Fixtures and Test Data

**Recommended fixtures (conftest.py):**

```python
# conftest.py
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta


@pytest.fixture
def tmp_mission_folder():
    """Create a temporary mission folder with structure."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "photos" / "jpeg").mkdir(parents=True)
        (tmp_path / "photos" / "raw").mkdir(parents=True)
        (tmp_path / "video" / "full").mkdir(parents=True)
        (tmp_path / "video" / "proxy").mkdir(parents=True)
        (tmp_path / "video" / "telemetry").mkdir(parents=True)
        (tmp_path / "ppk").mkdir(parents=True)
        yield tmp_path


@pytest.fixture
def sample_missions_config():
    """Sample missions.json configuration."""
    return [
        {
            "mission_id": "uuid-mission-001",
            "mission_number": 1,
            "package_type": "re_standard",
            "date": "20260218",
            "sequence_start": 1,
            "sequence_end": 24,
        },
        {
            "mission_id": "uuid-mission-002",
            "mission_number": 2,
            "package_type": "construction",
            "date": "20260219",
            "sequence_start": 25,
            "sequence_end": 48,
        },
    ]


@pytest.fixture
def sample_srt_telemetry():
    """Sample SRT subtitle block with DJI telemetry."""
    return """1
00:00:00,000 --> 00:00:00,033
F/2.8, SS 500, ISO 100, EV 0, GPS (36.8451, -76.2883, 45), D 15.3m, H 50m

2
00:00:00,033 --> 00:00:00,067
F/2.8, SS 500, ISO 105, EV 0, GPS (36.8452, -76.2883, 46), D 15.5m, H 51m
"""


@pytest.fixture
def ffprobe_response():
    """Mock ffprobe JSON response for a video file."""
    return {
        "format": {
            "duration": "45.6",
            "size": "1024000",
            "bit_rate": "180000",
        },
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
            },
        ],
    }
```

**Test data files (to be created in `.testing/fixtures/`):**
- `missions.json` — Sample missions config (reusable across tests)
- `sample.srt` — Real DJI SRT telemetry (sanitized)
- `sample_exif.jpg` — JPEG with DJI EXIF metadata (minimal, created in test)

## Coverage

**Requirements:** No enforced minimum yet

**Recommendation:** Aim for 80%+ on core functions (extraction, parsing, validation), 60%+ overall

**View coverage:**
```bash
pytest --cov=. --cov-report=html
# Opens htmlcov/index.html in browser
```

## Common Test Patterns

**Async testing:**
Not applicable — scripts are synchronous CLI tools. Webhook calls use `requests.post()` which is synchronous.

**Error testing:**

```python
def test_copy_file_path_traversal_blocked(self, tmp_path):
    """Path traversal attempts are blocked."""
    from ingest_sorter import copy_file_to_mission

    mission_path = tmp_path / "SAI_M0001"
    mission_path.mkdir()
    (mission_path / "photos" / "jpeg").mkdir(parents=True)

    # Attempted traversal filename
    malicious_file = {
        "filename": "../../../../etc/passwd",
        "path": "/tmp/passwd",
        "extension": "JPG",
    }

    result = copy_file_to_mission(malicious_file, str(mission_path))

    assert result is None  # Blocked


def test_ffmpeg_injection_prevented(self):
    """FFmpeg arguments are not shell-injected."""
    from video_color_grade import grade_video

    # LUT path with shell metacharacters
    dangerous_lut = r"C:\luts\; rm -rf /"

    # Should escape or reject
    # (depends on implementation)
    # At minimum, should use subprocess array not shell=True


def test_supabase_query_injection_prevented(self):
    """Google Drive API queries prevent injection."""
    from gdrive_upload import find_or_create_folder

    # Mock Google Drive service
    service = MagicMock()
    mock_files = service.files.return_value

    # Folder name with quotes
    malicious_folder = "'; DROP TABLE users; --"

    # Call should escape the single quote
    find_or_create_folder(service, malicious_folder)

    # Check that query was properly escaped
    call_args = mock_files.list.call_args
    query = call_args[1]["q"]
    assert "\\'" in query or '\\' in query  # Escaped
```

## Test Types

**Unit Tests:**
- Scope: Individual functions in isolation
- Approach: Mock external dependencies, test logic with various inputs
- Example: `test_extract_sequence_number()` with different DJI filename formats

**Integration Tests:**
- Scope: Multi-function workflows (scan → sort → copy)
- Approach: Use real filesystem (tmp_path), mock only external services (n8n, Supabase, Drive)
- Example: Full ingest workflow from scan_sd_card() through copy and inventory

**E2E Tests:**
- Framework: Not used yet (would require real DJI files and services)
- Could use: Docker containers with mocked services, or staged deployments
- Deferred to post-v1.0

## Running Tests

**Local testing (proposed commands):**
```bash
# Run all tests
pytest .testing/

# Run specific script tests
pytest .testing/test_ingest_sorter.py

# Run specific test class
pytest .testing/test_ingest_sorter.py::TestPlatformDetection

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=. --cov-report=html .testing/

# Run only fast tests (skip integration)
pytest .testing/ -m "not integration"
```

**CI integration (n8n workflow):**
- Could add test step before production deployment
- Run `pytest --tb=short --json-report` → upload results to Supabase for visibility
- Mark deployments as "tested" vs "manual"

## Known Testing Gaps

**No test coverage for:**
- FFmpeg/ffprobe subprocess calls (mocked in unit tests, manual verification in staging)
- Google Drive API operations (mocked in unit tests, tested manually)
- Supabase operations (mocked in unit tests, tested manually in staging)
- Webhook firing to n8n (mocked in unit tests)
- Folder watcher event detection (complex watchdog setup, manual testing)
- File system edge cases (symlinks, permissions, concurrent writes)

**Gaps to address:**
- Add golden files test for SRT parsing (known DJI SRT files with expected output)
- Add FFmpeg error handling tests (malformed video, missing codecs)
- Add Google Drive quota/rate-limit handling tests
- Add Supabase retry/timeout handling tests

---

*Testing analysis: 2026-02-23*
