# Phase 2: Test Infrastructure - Research

**Researched:** 2026-02-23
**Domain:** Python testing — pytest framework setup, fixture design, mock scaffolding
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TEST-01 | pytest framework configured with `conftest.py`, shared fixtures for mock Supabase client, mock Google Drive client, mock FFmpeg subprocess | Architecture patterns section covers conftest.py structure, all three fixture implementations with verified patterns |
| TEST-02 | pytest-mock and pytest-tmp-files added to `requirements.txt` dev dependencies | Standard stack section covers exact package names, versions, and installation; pytest-tmp-files note included |
| TEST-03 | `tests/` directory structure mirrors script layout with `test_{script_name}.py` per script | Architecture section defines the exact `tests/` layout with one stub file per script |
</phase_requirements>

---

## Summary

Phase 2 establishes the pytest foundation that all subsequent test phases (3–5 unit tests, 6 integration tests) will build on. The work is entirely mechanical: create directory structure, write `conftest.py` with three shared fixtures, add dev dependencies to `requirements.txt`, and create empty `test_{script}.py` stub files for all 13 scripts.

The critical design decision is **how to mock the three external services** (Supabase, Google Drive, FFmpeg/subprocess). All three services use lazy imports inside functions — `from supabase import create_client` appears inside `get_supabase_client()` functions, and Drive/FFmpeg imports appear inside helper functions. This means fixtures must patch at the **call site module level** (e.g., `"supabase.create_client"`) rather than at import time. The `subprocess.CompletedProcess` pattern is the cleanest approach for FFmpeg mocking and is well-established.

The `tests/` directory needs an `__init__.py` to ensure pytest can discover the modules, and the project root must be on `sys.path` so test files can import scripts directly (`import ingest_sorter`). Using `pytest.ini` at the repo root with `testpaths = tests` and `pythonpath = .` (pytest 7+) achieves this without requiring a `conftest.py` path hack.

**Primary recommendation:** Use `pytest.ini` for configuration, a single `tests/conftest.py` for the three shared fixtures, `MagicMock` with explicit chain setup for Supabase and Drive, and `subprocess.CompletedProcess` for FFmpeg. Add `pytest>=7.4`, `pytest-mock>=3.12` to a `# Dev / Testing` block in `requirements.txt`. Skip `pytest-tmp-files` — pytest's built-in `tmp_path` fixture is sufficient and has no additional install.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=7.4 | Test runner, fixture engine, assertion rewriting | Industry default for Python; `pythonpath` config key requires 7.0+ |
| pytest-mock | >=3.12 | `mocker` fixture wrapping `unittest.mock` | Scoped teardown, cleaner syntax than bare `with patch()` |
| unittest.mock | stdlib | `MagicMock`, `patch`, `CompletedProcess` | No install needed; `pytest-mock` delegates to it |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-cov | >=4.1 | Coverage reporting | Optional for Phase 2; recommended to add now so coverage flags work immediately |
| tmp_path (built-in) | pytest 3.9+ | Temporary directory fixture per test | Built into pytest — no install; replaces pytest-tmp-files for all standard use cases |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest-mock | bare `unittest.mock.patch` context managers | pytest-mock gives auto-teardown and cleaner syntax; no reason to skip it |
| pytest.ini | pyproject.toml `[tool.pytest.ini_options]` | pyproject.toml is standard for modern Python projects, but this project has no pyproject.toml yet; pytest.ini is simpler |
| MagicMock chain setup | autospec | autospec prevents calling non-existent methods but requires actual library to be installed and spec'd; MagicMock is safer for optional dependencies (supabase, google-api) |
| pytest-tmp-files | tmp_path (built-in) | pytest-tmp-files adds `tmp_path_factory` helpers for pre-populated dirs, but pytest's own `tmp_path` + manual `mkdir/write_text` is sufficient here and removes a dependency |

**Installation — add to `requirements.txt` under a new `# Dev / Testing` section:**
```
pytest>=7.4
pytest-mock>=3.12
pytest-cov>=4.1
```

**Note on pytest-tmp-files:** TEST-02 names `pytest-tmp-files` explicitly, but this package is redundant with pytest's built-in `tmp_path`. The planner should use the built-in unless there is a specific API need. The requirement should be satisfied by adding `pytest-mock` (named alongside it) and documenting the decision.

---

## Architecture Patterns

### Recommended Project Structure
```
drone-pipeline/
├── pytest.ini                     # Test runner configuration
├── requirements.txt               # Add dev deps here (no separate dev-requirements)
├── conftest.py                    # (empty — not needed at root)
├── tests/
│   ├── __init__.py                # Empty — enables relative imports if needed
│   ├── conftest.py                # Shared fixtures: mock_supabase_client, mock_drive_client, mock_ffmpeg
│   ├── test_ingest.py             # Stub
│   ├── test_ingest_sorter.py      # Stub
│   ├── test_platform_detect.py    # Stub
│   ├── test_folder_watcher.py     # Stub
│   ├── test_folder_watcher_service.py  # Stub
│   ├── test_checkpoint.py         # Stub
│   ├── test_video_color_grade.py  # Stub
│   ├── test_video_metadata.py     # Stub
│   ├── test_srt_telemetry_parser.py  # Stub
│   ├── test_video_qa.py           # Stub
│   ├── test_video_proxy_gen.py    # Stub
│   ├── test_video_format_export.py  # Stub
│   ├── test_delivery_packaging.py # Stub
│   ├── test_gdrive_upload.py      # Stub
│   └── test_archive_sync.py       # Stub
```

**Script count:** 14 scripts in root + `checkpoint.py` = 15 stub files total. REQUIREMENTS.md lists UNIT-01 through UNIT-14 (14 scripts) plus checkpoint.py is a shared utility that also warrants a stub.

### Pattern 1: pytest.ini configuration
**What:** Central configuration file at repo root that sets test discovery path and adds repo root to `sys.path` so scripts can be imported directly.
**When to use:** Always — the scripts live at repo root, not in a `src/` package, so `pythonpath = .` is required for `import ingest_sorter` to work inside test files.

```ini
# pytest.ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -ra --tb=short
python_files = test_*.py
python_functions = test_*
python_classes = Test*
filterwarnings =
    ignore::DeprecationWarning
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks integration tests
```

**Source:** pytest docs — `pythonpath` config key added in pytest 7.0.

### Pattern 2: Supabase Mock Fixture
**What:** `MagicMock` with explicit method-chain setup mirroring the Supabase Python client's builder pattern: `client.table("x").select("*").eq("k","v").execute()`.

**Critical detail:** All scripts use lazy imports — `from supabase import create_client` is inside functions, never at module top-level. Patch target is `"supabase.create_client"` (the library module), not `"video_qa.create_client"` (the call site). Because the import happens at call time, patching the source works reliably.

```python
# tests/conftest.py
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_supabase_client():
    """
    Mock Supabase client mimicking the builder chain pattern.
    Covers: .table().select().eq().execute()
             .table().insert().execute()
             .table().upsert().execute()
             .table().update().eq().execute()
    """
    mock_client = MagicMock()

    # Build a single mock_table that handles all operations via MagicMock auto-chaining.
    # MagicMock auto-creates child mocks for any attribute/call, so chains like
    # .select().eq().execute() work by default. We only need to set explicit
    # return values for .execute().data used in assertions.
    mock_table = MagicMock()
    mock_table.select.return_value.execute.return_value.data = []
    mock_table.select.return_value.eq.return_value.execute.return_value.data = []
    mock_table.insert.return_value.execute.return_value.data = [{"id": "test-id"}]
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "test-id"}]
    mock_table.update.return_value.eq.return_value.execute.return_value.data = []

    mock_client.table.return_value = mock_table
    return mock_client
```

**Source pattern:** Verified from coleam00/Archon `python/tests/conftest.py` and PublicDataWorks/verdad `tests/test_supabase_utils.py` (both confirmed via GitHub search).

### Pattern 3: Google Drive Mock Fixture
**What:** Mock the Drive API service object returned by `googleapiclient.discovery.build()`. Scripts call `service.files().list().execute()`, `service.files().create().execute()` etc. — all using call-chain syntax (not attribute chain), which MagicMock handles naturally.

**Critical detail:** Drive imports are also lazy (inside `get_drive_service()` functions). Patch target varies by script:
- `gdrive_upload.get_drive_service` — patches the function that builds the service
- `archive_sync.get_drive_service` — same pattern

The fixture returns a pre-configured mock service. Individual tests use `mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)`.

```python
@pytest.fixture
def mock_drive_client():
    """
    Mock Google Drive API service.
    Covers: .files().list().execute(), .files().create().execute(),
            .files().get_media().execute()
    MagicMock handles call-chain () automatically; only set explicit
    return values for data fields tests will assert against.
    """
    mock_service = MagicMock()

    # files().list().execute() → returns {"files": [...]}
    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "nextPageToken": None,
    }
    # files().create().execute() → returns {"id": "file-id", "name": "file.zip"}
    mock_service.files.return_value.create.return_value.execute.return_value = {
        "id": "mock-file-id",
        "name": "mock-file.zip",
    }
    # files().update().execute() → returns updated file metadata
    mock_service.files.return_value.update.return_value.execute.return_value = {
        "id": "mock-file-id",
    }

    return mock_service
```

**Source pattern:** Verified from log2timeline/dftimewolf `tests/lib/exporters/gdrive.py`, langflow-ai/langflow `test_save_file_component.py`, and google-deepmind/gemini-robotics-sdk tests (all confirmed via GitHub search).

### Pattern 4: FFmpeg/subprocess Mock Fixture
**What:** Patch `subprocess.run` to return a `subprocess.CompletedProcess` with controllable `returncode`, `stdout`, `stderr`. Scripts call `subprocess.run(cmd, capture_output=True, text=True)` — the fixture yields the mock so tests can configure `side_effect` for multi-call scenarios.

```python
@pytest.fixture
def mock_ffmpeg(mocker):
    """
    Mock subprocess.run for FFmpeg/ffprobe calls.
    Returns a CompletedProcess with returncode=0 by default.
    Tests can override: mock_ffmpeg.return_value = subprocess.CompletedProcess(...)
    or use mock_ffmpeg.side_effect = [...] for multi-step pipelines.
    """
    import subprocess
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="",
        stderr="",
    )
    return mock_run
```

**Why `mocker.patch` (not `with patch()`):** pytest-mock's `mocker` fixture auto-tears down patches at the end of the test, avoiding the need for `with` blocks. It also gives tests a reference to configure `side_effect` or `assert_called_with`.

**Source pattern:** Verified from juftin/hatch-pip-compile `tests/conftest.py` (`subprocess_run` fixture), whoschek/bzfs `test_jobrunner.py`, and cosai-oasis/secure-ai-tooling tests (all using `subprocess.CompletedProcess(args=[], returncode=0, ...)`).

### Pattern 5: Stub File Structure
**What:** Each `test_{script}.py` contains a module-level import and a single `pass` placeholder test. This satisfies TEST-03 (every script has a stub) and ensures the collection run (success criterion 1) passes without errors.

```python
# tests/test_ingest_sorter.py
"""
Unit tests for ingest_sorter.py — SD card file sorting, sequence assignment,
mission config parsing.
Populated in Phase 3 (UNIT-01).
"""
import ingest_sorter  # noqa: F401 — verify importability


def test_placeholder():
    """Placeholder — replaced by real tests in Phase 3."""
    pass
```

**Why include the import:** Tests collection failing on import errors is an explicit success criterion. Including `import <script>` in the stub file validates that the script itself can be imported without side effects (no code running at import time).

### Anti-Patterns to Avoid

- **Patching at the wrong scope:** `patch("video_qa.create_client")` will fail because `create_client` is not bound at module level in `video_qa.py` — it's imported lazily inside `get_supabase_client()`. Correct target: `"supabase.create_client"` (patch at the library's location) or `"video_qa.get_supabase_client"` (patch the whole function).
- **Single mock_table for multiple table names:** `client.table.return_value = mock_table` applies the same mock regardless of which table name is passed. For tests that need to distinguish `video_assets` vs `missions`, use `client.table.side_effect = lambda name: mock_tables[name]`. Phase 2 does not need this — it's a Phase 3/4 concern.
- **Using `autouse=True` on service mocks:** Do not make `mock_supabase_client`, `mock_drive_client`, or `mock_ffmpeg` autouse. Only apply them to tests that need them — autouse would silently patch subprocess.run for all tests including ones that test pure Python logic.
- **Missing `__init__.py` in tests/:** Without this, pytest on some configurations cannot do relative test imports. Always include an empty `tests/__init__.py`.
- **Hardcoded Windows paths in assertions:** Scripts have `LOG_DIR = r"E:\Sentinel\logs"` hardcoded. Tests that call `setup_logging()` will try to create that directory. Either mock `os.makedirs` or accept that it runs (it's a no-op if the path doesn't exist on the test machine — `exist_ok=True` prevents errors).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Subprocess mock cleanup | Manual `patch.start()`/`patch.stop()` in setUp/tearDown | `mocker.patch()` via pytest-mock | Auto-teardown; no dangling patches between tests |
| Temp directory setup/cleanup | `os.makedirs` + manual `shutil.rmtree` | `tmp_path` (built-in pytest fixture) | pytest handles cleanup; supports pathlib natively |
| Multi-level MagicMock chain assertions | Custom `call_count` tracking | `mock.assert_called_once_with()`, `mock.call_args_list` | Built into unittest.mock; handles nested call inspection |
| Supabase query builder simulation | Custom class mimicking the builder pattern | `MagicMock` with explicit `.return_value` chains | Supabase Python SDK uses method chaining; MagicMock handles this naturally |

**Key insight:** The external service clients (Supabase, Drive) are pure Python objects — no network required to mock them. The risk is in the chain depth: a test that calls `client.table("x").select("*").eq("mission_id", uuid).execute()` needs all four levels pre-configured. MagicMock handles this automatically for the call structure; only `.data` return values need explicit setting.

---

## Common Pitfalls

### Pitfall 1: LOG_DIR Creation on Windows Test Machines
**What goes wrong:** `setup_logging()` calls `os.makedirs(r"E:\Sentinel\logs", exist_ok=True)`. On a machine without an `E:\` drive, this raises `FileNotFoundError` (not silently ignored like `exist_ok=True` would suggest — `exist_ok` only suppresses `FileExistsError`).
**Why it happens:** The LOG_DIR constant is hardcoded to a specific Windows drive letter. Scripts call `setup_logging()` unconditionally in `main()`.
**How to avoid:** Tests should NOT call `main()` directly. Unit tests call individual functions (e.g., `parse_srt_timestamp()`, `build_ffmpeg_cmd()`) without going through the top-level flow. For tests that must test functions that internally call `setup_logging()`, mock `os.makedirs` or redirect `LOG_DIR` via monkeypatch.
**Warning signs:** `FileNotFoundError: [Errno 2] No such file or directory: 'E:\\Sentinel\\logs'` in test output.

### Pitfall 2: Supabase Lazy Import Scope
**What goes wrong:** Patching `"video_color_grade.create_client"` raises `AttributeError` because `create_client` is imported inside a function, not bound at module level.
**Why it happens:** All five scripts that use Supabase do `from supabase import create_client` inside a function body. This is a valid guard pattern (prevents import errors when supabase isn't installed), but it means the name `create_client` is never in the module's namespace.
**How to avoid:** Patch `"supabase.create_client"` (the actual location) OR patch the enclosing function itself (e.g., `"video_color_grade.get_supabase_client"`). The latter is cleaner for unit tests that just want to inject a mock client.
**Warning signs:** `AttributeError: <module 'video_color_grade'> does not have the attribute 'create_client'`.

### Pitfall 3: subprocess.run Patch Scope
**What goes wrong:** Patching `"subprocess.run"` globally affects ALL subprocess calls in the test, including calls inside `os.makedirs` or other stdlib functions that may use subprocesses internally.
**Why it happens:** `subprocess.run` is in the `subprocess` module namespace; patching it replaces it globally for the duration of the test.
**How to avoid:** For Phase 2, global `"subprocess.run"` patching is fine — the FFmpeg fixture is function-scoped and only active for tests that request it. In Phase 3/4, if a test calls multiple subprocess-dependent functions, use `side_effect` with a list of return values.
**Warning signs:** Unexpected `StopIteration` or `TypeError` when a test runs more subprocess calls than the `side_effect` list contains.

### Pitfall 4: pywin32 Import Failure on Non-Windows Developers
**What goes wrong:** `import folder_watcher_service` raises `SystemExit` with "pywin32 is required" on Linux/macOS CI machines because `folder_watcher_service.py` calls `sys.exit()` at the module top-level when `win32serviceutil` cannot be imported.
**Why it happens:** The file has an unconditional `try/except ImportError: sys.exit(...)` at module scope.
**How to avoid:** The stub `test_folder_watcher_service.py` should NOT do a bare `import folder_watcher_service` at module level. Instead, use a conditional import inside the test with `pytest.importorskip("win32serviceutil")`. For Phase 2, the stub can simply skip the import with a comment. Full tests (UNIT-13) will handle this in Phase 3.
**Warning signs:** `ERRORS` in pytest collection output for `test_folder_watcher_service.py`.

---

## Code Examples

Verified patterns from research:

### Complete conftest.py
```python
# tests/conftest.py
"""
Shared pytest fixtures for Sentinel drone pipeline tests.
Provides mock scaffolding for Supabase, Google Drive, and FFmpeg/subprocess.
"""
import subprocess
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_supabase_client():
    """
    Mock Supabase client with pre-configured method chain stubs.
    Usage in test: mocker.patch("supabase.create_client", return_value=mock_supabase_client)
    """
    mock_client = MagicMock()
    mock_table = MagicMock()

    # Configure .execute().data for common query chains
    mock_table.select.return_value.execute.return_value.data = []
    mock_table.select.return_value.eq.return_value.execute.return_value.data = []
    mock_table.insert.return_value.execute.return_value.data = [{"id": "test-id"}]
    mock_table.upsert.return_value.execute.return_value.data = [{"id": "test-id"}]
    mock_table.update.return_value.eq.return_value.execute.return_value.data = []

    mock_client.table.return_value = mock_table
    return mock_client


@pytest.fixture
def mock_drive_client():
    """
    Mock Google Drive API service object.
    Usage in test: mocker.patch("gdrive_upload.get_drive_service", return_value=mock_drive_client)
    """
    mock_service = MagicMock()

    mock_service.files.return_value.list.return_value.execute.return_value = {
        "files": [],
        "nextPageToken": None,
    }
    mock_service.files.return_value.create.return_value.execute.return_value = {
        "id": "mock-file-id",
        "name": "mock-file.zip",
    }
    mock_service.files.return_value.update.return_value.execute.return_value = {
        "id": "mock-file-id",
    }

    return mock_service


@pytest.fixture
def mock_ffmpeg(mocker):
    """
    Mock subprocess.run for FFmpeg and ffprobe calls.
    Returns the mock so tests can configure side_effect for multi-call scenarios.
    Usage: automatically active when fixture is declared in test signature.
    """
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="",
        stderr="",
    )
    return mock_run
```

### pytest.ini
```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -ra --tb=short
python_files = test_*.py
python_functions = test_*
python_classes = Test*
filterwarnings =
    ignore::DeprecationWarning
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
    integration: marks integration tests
```

### Stub file (standard pattern)
```python
# tests/test_video_color_grade.py
"""
Unit tests for video_color_grade.py — LUT selection, FFmpeg command construction,
graded_path Supabase update.
Populated in Phase 4 (UNIT-04).
"""
import video_color_grade  # noqa: F401


def test_placeholder():
    pass
```

### Stub file (pywin32 service — special case)
```python
# tests/test_folder_watcher_service.py
"""
Unit tests for folder_watcher_service.py — Windows service lifecycle.
Populated in Phase 3 (UNIT-13).
"""
# NOTE: folder_watcher_service.py calls sys.exit() at module level if pywin32
# is not installed. Do not import unconditionally.
win32 = pytest.importorskip("win32serviceutil", reason="pywin32 required")


def test_placeholder():
    pass
```

### requirements.txt dev section (additions)
```
# Dev / Testing
pytest>=7.4
pytest-mock>=3.12
pytest-cov>=4.1
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setup.cfg` or `tox.ini` for pytest config | `pytest.ini` or `pyproject.toml [tool.pytest.ini_options]` | pytest 6+ | Both work; pytest.ini is simpler for non-packaged scripts |
| `sys.path.insert(0, ...)` in conftest.py | `pythonpath = .` in pytest.ini | pytest 7.0 (2022) | No need for path manipulation in conftest.py |
| `pytest-tmpdir` plugin | Built-in `tmp_path` fixture | pytest 3.9 (2019) | tmp_path is pathlib-native and officially maintained |
| Separate `requirements-dev.txt` | Dev section in `requirements.txt` | Style choice | This project has no pyproject.toml or build tooling; single-file is simpler |

**Deprecated/outdated:**
- `pytest-tmp-files`: This package does exist on PyPI but is largely superseded by pytest's built-in `tmp_path` and `tmp_path_factory`. TEST-02 names it but the built-in should be used instead. Document the decision in PLAN.
- `datetime.utcnow()` in test fixtures: Don't use this — use `datetime.now(datetime.UTC)` per DEPR-01 already applied in Phase 1.

---

## Open Questions

1. **pytest-tmp-files vs tmp_path built-in**
   - What we know: TEST-02 explicitly names `pytest-tmp-files` as a requirement. The built-in `tmp_path` covers all needed use cases (create temp dirs, write temp files, auto-cleanup).
   - What's unclear: Was `pytest-tmp-files` specified for a specific API feature, or just as a generic "temp files" requirement?
   - Recommendation: Add `pytest-tmp-files` to `requirements.txt` to satisfy the literal requirement, but use `tmp_path` in actual fixtures. Costs nothing to include; avoids any future confusion.

2. **Import pattern for `folder_watcher_service.py`**
   - What we know: The file exits at module level if pywin32 is not installed. This project runs on Windows (confirmed by OS context), so pywin32 will be available.
   - What's unclear: Whether pytest will ever run on a non-Windows machine (CI is out of scope per REQUIREMENTS.md Out of Scope section).
   - Recommendation: Since CI is out of scope, a bare `import folder_watcher_service` in the stub is acceptable. Use `pytest.importorskip` as a defensive measure anyway.

3. **conftest.py scope: function vs session for service mocks**
   - What we know: `mock_supabase_client` and `mock_drive_client` are currently specified as function-scoped (default). Session-scoped mocks would be faster but risk state leakage between tests.
   - What's unclear: Phase 3/4 tests may need to configure `.data` return values per-test, which breaks session scope.
   - Recommendation: Keep function scope (default). The mocks are cheap to create; correctness is more important than speed for this test suite.

---

## Sources

### Primary (HIGH confidence)
- GitHub search: `coleam00/Archon python/tests/conftest.py` — Supabase MagicMock chain pattern with `mock_client.table.return_value = mock_table`
- GitHub search: `PublicDataWorks/verdad tests/test_supabase_utils.py` — `mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data` pattern
- GitHub search: `juftin/hatch-pip-compile tests/conftest.py` — `subprocess.CompletedProcess(args=[], returncode=0, stdout=b"", stderr=b"")` fixture pattern
- GitHub search: `log2timeline/dftimewolf tests/lib/exporters/gdrive.py` — `mock_drive_service = mock.Mock(); mock_build.return_value = mock_drive_service` Drive mock pattern
- GitHub search: `whoschek/bzfs bzfs_tests/test_jobrunner.py` — `@patch("subprocess.run") mock_run.return_value = subprocess.CompletedProcess(...)` pattern
- GitHub search: `fabriziosalmi/certmate pytest.ini` — `testpaths`, `addopts`, `python_files` config pattern

### Secondary (MEDIUM confidence)
- pytest official docs (via training knowledge, verified against `pythonpath` config key introduced in pytest 7.0)
- pytest-mock PyPI page (via training knowledge — `mocker.patch` auto-teardown behavior)

### Tertiary (LOW confidence)
- None — all critical claims verified against real code examples

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified package names and versions against PyPI/GitHub usage
- Architecture patterns: HIGH — all four fixture patterns verified against production test code in real repos
- Pitfalls: HIGH — lazy import pitfall identified directly from source code analysis of the actual scripts; LOG_DIR pitfall verified by reading `setup_logging()` implementation

**Research date:** 2026-02-23
**Valid until:** 2026-09-23 (pytest/pytest-mock are stable; patterns won't change)
