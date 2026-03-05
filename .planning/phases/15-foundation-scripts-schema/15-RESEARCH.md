# Phase 15: Foundation Scripts + Schema - Research

**Researched:** 2026-03-05
**Domain:** Python pipeline scripts (subprocess management, file operations) + Supabase schema
**Confidence:** HIGH

## Summary

Phase 15 creates two new Python scripts (mipmap_launcher.py, ortho_harvester.py) and three Supabase schema changes (processing_jobs table, mipmap_workspace column, processing_templates columns). The codebase has 18 existing scripts with a well-established "pipeline contract" pattern that both new scripts must follow exactly: argparse CLI, JSON stdout, setup_logging from pipeline_utils, Supabase status updates via PipelineStatusReporter, and exit codes 0/1/2.

The project already has pipeline_status.py (PipelineStatusReporter class) which handles all step-level status reporting to processing_jobs. Both new scripts integrate with this. The test suite (402 tests) uses a consistent pattern: per-file autouse fixtures for sys.modules stubs, shared conftest.py fixtures for mock_supabase_client/mock_ffmpeg, and pytest-mock (mocker) for patching.

**Primary recommendation:** Follow the exact patterns from video_color_grade.py (pipeline contract) and test_video_color_grade.py (test structure). Use subprocess.Popen (not subprocess.run) for fire-and-forget MipMap launch. Use psutil for PID-based orphan detection. Use rasterio for GeoTIFF validation.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MPC-01 | mipmap_launcher.py launches reconstruct_full_engine.exe with stdout to log, writes PID, returns immediately | Subprocess.Popen pattern with stdout redirect, PID file write |
| MPC-02 | mipmap_launcher.py follows pipeline contract | Exact pattern from video_color_grade.py: argparse, setup_logging, PipelineStatusReporter, exit codes |
| MPC-04 | ortho_harvester.py copies GeoTIFF with integrity verification | shutil.copy2 + rasterio.open() header check + file size comparison |
| MPC-05 | ortho_harvester.py follows pipeline contract | Same pipeline contract as MPC-02 |
| MPC-07 | Orphan process detection via PID file | psutil.pid_exists() + psutil.Process(pid).name() check |
| SCH-01 | processing_jobs table with per-step status tracking | New migration, schema designed from pipeline_status.py usage patterns |
| SCH-02 | mipmap_workspace JSONB column on drone_jobs | ALTER TABLE ADD COLUMN, matches vegetation_columns migration pattern |
| SCH-03 | processing_templates path-specific config columns | ALTER TABLE ADD COLUMN for video_formats, vegetation_config, etc. |
| TST-01 | mipmap_launcher.py unit tests with mocked subprocess | Mock subprocess.Popen, psutil; follow test_video_color_grade.py pattern |
| TST-02 | ortho_harvester.py unit tests with mocked file ops and rasterio | Mock shutil.copy2, rasterio.open; use tmp_path fixture |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| subprocess (stdlib) | 3.14 | Launch MipMap as detached process | Popen for fire-and-forget, stdout redirect to file |
| psutil | 5.9+ | Orphan process detection | Cross-platform PID checking, process name validation |
| shutil (stdlib) | 3.14 | File copy with metadata preservation | copy2 preserves timestamps, existing pattern in ingest_sorter.py |
| rasterio | 1.3+ | GeoTIFF header validation | Already in project (Path E uses it), open() reads CRS/bounds/bands |
| argparse (stdlib) | 3.14 | CLI argument parsing | Pipeline contract requires it |
| pipeline_utils | local | setup_logging, get_supabase_client | Shared utility module |
| pipeline_status | local | PipelineStatusReporter, add_pipeline_args | Step-level Supabase status reporting |
| checkpoint | local | load_checkpoint, save_checkpoint | Resume support (may not be needed for these scripts) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 8.x | Test framework | All tests |
| pytest-mock | 3.x | mocker fixture | Patching in tests |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| psutil for PID check | os.kill(pid, 0) on Windows | os.kill unreliable on Windows; psutil is cross-platform and can verify process name |
| rasterio for validation | GDAL directly | rasterio already in project, simpler API |
| shutil.copy2 | robocopy subprocess | shutil is Pythonic, already used in ingest_sorter |

**Installation:**
```bash
pip install psutil
# rasterio already installed in project (Path E)
```

**Note:** rasterio is a heavy dependency. For mipmap_launcher.py and ortho_harvester.py running on system Python 3.14, rasterio may need to be installed separately (Path E uses Python 3.12 venv). Verify rasterio availability on system Python or use a lightweight check (file size + try/except rasterio.open).

## Architecture Patterns

### Recommended Project Structure
```
drone-pipeline/
  mipmap_launcher.py        # New: MPC-01, MPC-02, MPC-07
  ortho_harvester.py        # New: MPC-04, MPC-05
  pipeline_status.py        # Existing: PipelineStatusReporter (already has processing_jobs support)
  pipeline_utils.py         # Existing: setup_logging, get_supabase_client
  tests/
    test_mipmap_launcher.py  # New: TST-01
    test_ortho_harvester.py  # New: TST-02
  db_migrations/migrations/
    20260305000001_processing_jobs.sql       # New: SCH-01
    20260305000002_mipmap_workspace.sql      # New: SCH-02, SCH-03
```

### Pattern 1: Pipeline Contract (from video_color_grade.py)
**What:** Standard structure every pipeline script follows
**When to use:** Every new script
**Example:**
```python
# Source: video_color_grade.py (verified from codebase)
"""
Sentinel Aerial Inspections -- Script Name (Step XX)
Usage:
    python script_name.py MISSION_PATH [--options]
"""
import os
import sys
import argparse
import logging

from pipeline_status import PipelineStatusReporter, add_pipeline_args
from pipeline_utils import setup_logging, get_supabase_client

SCRIPT_NAME = "script_name"

def main():
    parser = argparse.ArgumentParser(description="...")
    parser.add_argument("mission_path", help="Path to mission folder")
    # script-specific args
    add_pipeline_args(parser)  # adds --processing-job-id
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # Validate inputs
    if not os.path.isdir(args.mission_path):
        log.error(f"Mission folder not found: {args.mission_path}")
        sys.exit(2)  # exit 2 = config/input error

    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name=SCRIPT_NAME,
    )
    reporter.start()

    try:
        # ... do work ...
        reporter.complete(output="summary")
    except Exception as e:
        reporter.fail(str(e))
        sys.exit(1)  # exit 1 = runtime failure

if __name__ == "__main__":
    main()
```

### Pattern 2: Fire-and-Forget Subprocess (mipmap_launcher.py specific)
**What:** Launch MipMap as detached process, write PID, return immediately
**When to use:** MipMap only -- produces 50-200MB stdout, cannot use Execute Command directly
**Example:**
```python
# Source: design based on PROJECT.md constraint + subprocess docs
import subprocess
import json

def launch_mipmap(engine_path, workspace, project_file, log_file_path):
    """Launch MipMap and return immediately with PID."""
    with open(log_file_path, "w") as log_fh:
        proc = subprocess.Popen(
            [engine_path, project_file],
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            cwd=workspace,
            # On Windows, no need for start_new_session
        )

    pid = proc.pid
    # Write PID file for orphan detection
    pid_file = os.path.join(workspace, "mipmap.pid")
    with open(pid_file, "w") as f:
        json.dump({"pid": pid, "started_at": _now_iso(), "project": project_file}, f)

    return {"status": "launched", "pid": pid, "log_file": log_file_path}
```

### Pattern 3: PID-Based Orphan Detection (MPC-07)
**What:** Check if MipMap is already running before launching
**When to use:** Before every mipmap_launcher.py invocation
**Example:**
```python
import psutil

def check_orphan(pid_file_path, expected_exe_name="reconstruct_full_engine.exe"):
    """Check if a MipMap process from a previous run is still alive."""
    if not os.path.exists(pid_file_path):
        return False  # No PID file = no orphan

    with open(pid_file_path) as f:
        data = json.load(f)
    pid = data["pid"]

    if not psutil.pid_exists(pid):
        # Process died, clean up stale PID file
        os.remove(pid_file_path)
        return False

    try:
        proc = psutil.Process(pid)
        # Verify it's actually MipMap, not a recycled PID
        if expected_exe_name.lower() in proc.name().lower():
            return True  # Orphan detected, still running
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    # PID was recycled to a different process
    os.remove(pid_file_path)
    return False
```

### Pattern 4: GeoTIFF Integrity Validation (ortho_harvester.py)
**What:** Verify copied GeoTIFF is valid and complete
**When to use:** After copying ortho from MipMap workspace to mission mapping/
**Example:**
```python
import rasterio

def validate_geotiff(file_path):
    """Validate GeoTIFF has valid header, CRS, and non-zero dimensions."""
    try:
        with rasterio.open(file_path) as ds:
            if ds.width <= 0 or ds.height <= 0:
                return False, "Zero dimensions"
            if ds.count <= 0:
                return False, "No bands"
            if ds.crs is None:
                return False, "No CRS"
            # Read a small window to verify data is accessible
            ds.read(1, window=rasterio.windows.Window(0, 0, 1, 1))
            return True, f"{ds.width}x{ds.height}, {ds.count} bands, CRS={ds.crs}"
    except Exception as e:
        return False, f"Invalid GeoTIFF: {e}"

def verify_copy_integrity(source_path, dest_path):
    """Verify destination file matches source size and is a valid GeoTIFF."""
    src_size = os.path.getsize(source_path)
    dst_size = os.path.getsize(dest_path)
    if src_size != dst_size:
        return False, f"Size mismatch: {src_size} vs {dst_size}"
    return validate_geotiff(dest_path)
```

### Pattern 5: Supabase Status Update (from pipeline_status.py)
**What:** PipelineStatusReporter reports step status to processing_jobs table
**When to use:** Every script call from n8n (no-op when --processing-job-id not provided)
**Critical detail:** The reporter fetches the job, finds the step by name in the `steps` JSONB array, patches it, and derives job-level status from all step statuses. This means the processing_jobs.steps array must be pre-populated with step entries when the job is created (done by Package Router in Phase 16).

### Anti-Patterns to Avoid
- **Never use subprocess.run for MipMap:** stdout is 50-200MB, would crash n8n Execute Command node
- **Never use shell=True for Popen:** Returns shell PID instead of process PID, breaks orphan detection
- **Never skip PipelineStatusReporter:** Even if status updates are "optional", the pattern must be consistent across all scripts
- **Never hardcode paths:** Use argparse arguments with defaults from env vars or constants, matching existing scripts

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Process existence check on Windows | os.kill(pid, 0) or /proc/ | psutil.pid_exists() + psutil.Process() | os.kill behaves differently on Windows; /proc doesn't exist |
| Supabase step status reporting | Custom Supabase update logic | PipelineStatusReporter from pipeline_status.py | Already built, handles all status transitions, no-op when offline |
| CLI argument parsing | Custom sys.argv parsing | argparse + add_pipeline_args() | Pipeline contract requires argparse |
| Logging setup | Custom logging config | setup_logging() from pipeline_utils.py | Standardized file + stdout logging |
| GeoTIFF metadata reading | Manual TIFF header parsing | rasterio.open() | Handles all TIFF variants, CRS detection |

**Key insight:** The project has a strong shared infrastructure (pipeline_utils, pipeline_status, checkpoint). New scripts should ONLY contain business logic; all cross-cutting concerns are already solved.

## Common Pitfalls

### Pitfall 1: PID Recycling on Windows
**What goes wrong:** A PID file contains PID 12345. Process 12345 died, but Windows recycled that PID to a different process. Script incorrectly thinks MipMap is still running.
**Why it happens:** Windows recycles PIDs aggressively, especially on busy systems.
**How to avoid:** After psutil.pid_exists(), also check psutil.Process(pid).name() contains "reconstruct_full_engine" or similar.
**Warning signs:** mipmap_launcher.py refuses to start but no MipMap window is visible.

### Pitfall 2: rasterio on System Python 3.14
**What goes wrong:** rasterio may not have a wheel for Python 3.14; installation fails.
**Why it happens:** Path E uses Python 3.12 venv specifically because some geo packages don't support 3.14.
**How to avoid:** Test rasterio import on system Python first. Fallback plan: use simpler validation (file size + try opening with struct to check TIFF magic bytes) if rasterio unavailable.
**Warning signs:** `pip install rasterio` fails with build errors on 3.14.

### Pitfall 3: MipMap Engine Not Installed
**What goes wrong:** MIPMAP_ENGINE_PATH is still a placeholder. Script must handle this gracefully.
**Why it happens:** MipMap Desktop not installed on new rig yet (confirmed in Phase 14 summary).
**How to avoid:** Validate engine_path exists and is executable before attempting launch. Exit code 2 (config error). Tests mock subprocess.Popen so no real MipMap needed.
**Warning signs:** sys.exit(2) with clear error message about missing engine.

### Pitfall 4: Supabase Migration Ordering
**What goes wrong:** Migration that adds columns references a table that doesn't exist yet.
**Why it happens:** processing_jobs table must be created BEFORE any references to it.
**How to avoid:** Split into two migrations with correct timestamps: first creates processing_jobs table, second adds columns to existing tables. Follow existing timestamp convention (20260225NNNNNN).
**Warning signs:** Migration SQL error: "relation does not exist".

### Pitfall 5: JSON stdout Contract
**What goes wrong:** n8n Execute Command node expects JSON stdout to parse results. Script writes non-JSON to stdout.
**Why it happens:** setup_logging sends log messages to stdout. JSON result mixed with log lines.
**How to avoid:** Print JSON result as the LAST line of stdout. n8n can parse the last line. OR: use print(json.dumps(result)) at the very end, after logging is done. The existing scripts (video_color_grade.py) don't output JSON -- they rely on exit codes. Check if n8n workflow actually needs JSON stdout or just exit codes.
**Warning signs:** n8n fails to parse Execute Command output.

### Pitfall 6: Large File Copy Interruption
**What goes wrong:** GeoTIFF is large (1-10GB). Copy interrupted by crash/power loss leaves partial file.
**Why it happens:** shutil.copy2 is not atomic.
**How to avoid:** Copy to a temp filename first, then rename. Verify size after copy. rasterio validation catches corrupted files.
**Warning signs:** Size mismatch between source and destination.

## Code Examples

### mipmap_launcher.py Main Structure
```python
# Source: Composite from video_color_grade.py pattern + subprocess docs
SCRIPT_NAME = "mipmap_launcher"

def main():
    parser = argparse.ArgumentParser(description="Launch MipMap Desktop engine")
    parser.add_argument("--mission-id", required=True, help="Supabase mission UUID")
    parser.add_argument("--mission-path", required=True, help="Path to mission folder")
    parser.add_argument("--engine-path", default=os.environ.get("MIPMAP_ENGINE_PATH", ""),
                        help="Path to reconstruct_full_engine.exe")
    parser.add_argument("--workspace", default=os.environ.get("MIPMAP_WORKSPACE", r"D:\MipMapWorkspace"),
                        help="MipMap workspace directory")
    add_pipeline_args(parser)
    args = parser.parse_args()

    log = setup_logging(SCRIPT_NAME)

    # Validate engine exists
    if not args.engine_path or not os.path.isfile(args.engine_path):
        log.error(f"MipMap engine not found: {args.engine_path}")
        print(json.dumps({"status": "error", "error": "engine_not_found"}))
        sys.exit(2)

    # Check for orphan
    pid_file = os.path.join(args.workspace, "mipmap.pid")
    if check_orphan(pid_file):
        log.error("MipMap already running (orphan detected)")
        print(json.dumps({"status": "error", "error": "orphan_detected"}))
        sys.exit(1)

    reporter = PipelineStatusReporter(
        processing_job_id=getattr(args, "processing_job_id", None),
        step_name="mipmap_launcher",
    )
    reporter.start()

    try:
        result = launch_mipmap(args.engine_path, args.workspace, args.mission_path, ...)
        reporter.complete(output=f"Launched PID {result['pid']}")
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        reporter.fail(str(e))
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)
```

### processing_jobs Table Schema
```sql
-- Source: Designed from pipeline_status.py usage patterns (verified from codebase)
CREATE TABLE public.processing_jobs (
  id              UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
  mission_id      UUID          NOT NULL REFERENCES public.drone_jobs(id) ON DELETE CASCADE,
  package_type    TEXT          NOT NULL,
  status          TEXT          NOT NULL DEFAULT 'pending',
  -- status values: pending, running, awaiting_manual_edit, complete, failed
  current_step    TEXT,
  steps           JSONB         NOT NULL DEFAULT '[]'::jsonb,
  -- steps array: [{name, status, started_at, completed_at, error, output}]
  error_message   TEXT,
  created_at      TIMESTAMPTZ   DEFAULT now(),
  updated_at      TIMESTAMPTZ   DEFAULT now(),
  completed_at    TIMESTAMPTZ,
  UNIQUE (mission_id)  -- one active job per mission
);

-- Auto-update trigger
CREATE TRIGGER processing_jobs_updated_at
  BEFORE UPDATE ON public.processing_jobs
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- Indexes
CREATE INDEX idx_processing_jobs_mission ON public.processing_jobs (mission_id);
CREATE INDEX idx_processing_jobs_status ON public.processing_jobs (status);

-- RLS (same pattern as vegetation tables)
ALTER TABLE public.processing_jobs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on processing_jobs"
  ON public.processing_jobs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Authenticated users can read processing_jobs"
  ON public.processing_jobs FOR SELECT TO authenticated USING (true);
```

### Test Pattern (from test_video_color_grade.py)
```python
# Source: test_video_color_grade.py (verified from codebase)
import types
import pytest
from unittest.mock import MagicMock

@pytest.fixture(autouse=True)
def stub_supabase_module(mocker):
    """Inject fake supabase module so tests run without supabase package."""
    if "supabase" not in __import__("sys").modules:
        fake_supabase = types.ModuleType("supabase")
        fake_supabase.create_client = MagicMock()
        mocker.patch.dict(__import__("sys").modules, {"supabase": fake_supabase})

# For mipmap_launcher tests, also stub psutil:
@pytest.fixture(autouse=True)
def stub_psutil(mocker):
    """Inject fake psutil module if not installed."""
    if "psutil" not in __import__("sys").modules:
        fake_psutil = types.ModuleType("psutil")
        fake_psutil.pid_exists = MagicMock(return_value=False)
        fake_psutil.Process = MagicMock()
        fake_psutil.NoSuchProcess = type("NoSuchProcess", (Exception,), {})
        fake_psutil.AccessDenied = type("AccessDenied", (Exception,), {})
        mocker.patch.dict(__import__("sys").modules, {"psutil": fake_psutil})
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Ad-hoc status updates | PipelineStatusReporter class | v2.0 (2026-02-25) | All scripts use same reporter pattern |
| No processing_jobs table | processing_jobs with JSONB steps | v3.0 (this phase) | Enables n8n to track step progress |
| Manual MipMap launch | Automated fire-and-forget | v3.0 (this phase) | Saves 5-10 min per mapping mission |

**Deprecated/outdated:**
- pipeline_status.py already exists and references processing_jobs table -- the table schema must match the queries it already makes (fetch by id, update steps array, derive job status from step statuses)

## Open Questions

1. **MipMap CLI Arguments**
   - What we know: The engine is `reconstruct_full_engine.exe`, workspace is `D:\MipMapWorkspace`
   - What's unclear: Exact CLI arguments (project file path? input folder? output path?) -- MipMap Desktop is not installed on this rig
   - Recommendation: Design mipmap_launcher.py with flexible argparse args. The engine_path and project arguments can be configured when MipMap is actually installed. For now, tests mock subprocess.Popen entirely.

2. **rasterio on System Python 3.14**
   - What we know: rasterio works on Python 3.12 (Path E venv). System Python is 3.14.
   - What's unclear: Whether rasterio has 3.14 wheels
   - Recommendation: Try installing rasterio on system Python. If it fails, implement a lightweight fallback validation (TIFF magic bytes 0x4949 or 0x4D4D + file size check) and add rasterio validation as optional enhancement.

3. **processing_templates Existing Schema**
   - What we know: processing_templates table exists (referenced in vegetation_columns migration). It already has vegetation_enabled and vegetation_config columns.
   - What's unclear: The full current schema of processing_templates (base columns from initial migration not in repo)
   - Recommendation: Query Supabase to inspect current processing_templates schema before writing migration. Or use IF NOT EXISTS guards on all ALTER TABLE statements.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | pytest.ini |
| Quick run command | `pytest tests/test_mipmap_launcher.py tests/test_ortho_harvester.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TST-01 | mipmap_launcher subprocess mock, PID file, orphan detection | unit | `pytest tests/test_mipmap_launcher.py -x` | Wave 0 |
| TST-02 | ortho_harvester file copy, rasterio validation mock | unit | `pytest tests/test_ortho_harvester.py -x` | Wave 0 |
| MPC-01 | Launch subprocess, write PID, return JSON | unit | `pytest tests/test_mipmap_launcher.py::test_launch_writes_pid -x` | Wave 0 |
| MPC-02 | Pipeline contract (argparse, logging, exit codes) | unit | `pytest tests/test_mipmap_launcher.py::test_main_exit_codes -x` | Wave 0 |
| MPC-04 | Copy GeoTIFF + integrity check | unit | `pytest tests/test_ortho_harvester.py::test_copy_with_validation -x` | Wave 0 |
| MPC-05 | Pipeline contract | unit | `pytest tests/test_ortho_harvester.py::test_main_exit_codes -x` | Wave 0 |
| MPC-07 | Orphan detection | unit | `pytest tests/test_mipmap_launcher.py::test_orphan_detection -x` | Wave 0 |
| SCH-01 | processing_jobs table exists | manual-only | SQL migration applied via Supabase dashboard | N/A |
| SCH-02 | mipmap_workspace JSONB column | manual-only | SQL migration applied via Supabase dashboard | N/A |
| SCH-03 | processing_templates config columns | manual-only | SQL migration applied via Supabase dashboard | N/A |

### Sampling Rate
- **Per task commit:** `pytest tests/test_mipmap_launcher.py tests/test_ortho_harvester.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_mipmap_launcher.py` -- covers TST-01, MPC-01, MPC-02, MPC-07
- [ ] `tests/test_ortho_harvester.py` -- covers TST-02, MPC-04, MPC-05
- [ ] psutil installation: `pip install psutil` -- if not already installed

## Sources

### Primary (HIGH confidence)
- **video_color_grade.py** (codebase) -- Pipeline contract pattern, argparse + setup_logging + PipelineStatusReporter + exit codes
- **pipeline_status.py** (codebase) -- PipelineStatusReporter class, processing_jobs query patterns (fetch, update steps JSONB)
- **pipeline_utils.py** (codebase) -- setup_logging(), get_supabase_client() shared utilities
- **tests/conftest.py** (codebase) -- mock_supabase_client, mock_ffmpeg shared fixtures
- **test_video_color_grade.py** (codebase) -- Test pattern: autouse stub_supabase_module, per-file fixture isolation
- **test_canopy_detection.py** (codebase) -- sys.modules stub injection for heavy dependencies
- **db_migrations/migrations/20260225000001_vegetation_tables.sql** (codebase) -- Migration pattern: RLS, triggers, indexes
- **db_migrations/migrations/20260225000002_vegetation_columns.sql** (codebase) -- ALTER TABLE ADD COLUMN pattern
- **n8n/NATIVE-CONFIG.md** (codebase) -- MIPMAP_ENGINE_PATH, MIPMAP_WORKSPACE env vars
- [Python subprocess docs](https://docs.python.org/3/library/subprocess.html) -- Popen PID, stdout redirect
- [psutil docs](https://psutil.readthedocs.io/) -- pid_exists(), Process.name()
- [rasterio quickstart](https://rasterio.readthedocs.io/en/stable/quickstart.html) -- open(), metadata access

### Secondary (MEDIUM confidence)
- [Rasterio validation patterns](https://www.gpxz.io/blog/raster-validation) -- GeoTIFF corruption detection approaches

### Tertiary (LOW confidence)
- MipMap Desktop CLI -- No public documentation found for reconstruct_full_engine.exe arguments. Design must be flexible.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All libraries either already in project or well-documented stdlib
- Architecture: HIGH -- Following exact patterns from 18 existing scripts
- Pitfalls: HIGH -- Based on actual codebase analysis and known constraints (MipMap not installed, Python 3.14 compatibility)
- Schema: MEDIUM -- processing_jobs schema inferred from pipeline_status.py usage, but processing_templates base schema not fully visible

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable domain, no fast-moving dependencies)
