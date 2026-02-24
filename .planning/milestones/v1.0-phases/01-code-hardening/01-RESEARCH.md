# Phase 1: Code Hardening — Research

**Researched:** 2026-02-23
**Domain:** Python CLI hardening — logging, error handling, checkpoint/resume, datetime, Supabase
**Confidence:** HIGH (all findings verified against actual source code + authoritative documentation)

---

## Summary

Phase 1 covers five distinct hardening concerns across 8 scripts. The work is mostly
mechanical and high-confidence: the codebase already has one reference implementation for
every pattern needed — `ingest_sorter.py` for logging, `video_proxy_gen.py` for skip-if-exists,
and `archive_sync.py` for Supabase upsert shape. Each task is essentially a propagation of
existing patterns, not invention of new ones.

The most complex task is GAP-11 (checkpoint/resume). It requires atomic JSON checkpoint files,
careful placement of checkpoint reads/writes inside per-file loops, and a consistent naming
convention. The CONCERNS.md estimate of 3-5 hours per script is accurate for a naive approach;
with a shared `checkpoint.py` helper, it reduces to ~1 hour per script after the helper is
written.

The `datetime.utcnow()` migration (DEPR-01) is the simplest task: three one-line replacements
plus an import update. Python 3.14.3 is installed on this system; the deprecation warning is
now a `DeprecationWarning` that will become an error in a future version.

**Primary recommendation:** Build a shared `checkpoint.py` utility first (Plan 01-03). It
unlocks consistent resume logic across all five video scripts and becomes testable in isolation.
For GAP-10 and GAP-13, follow `ingest_sorter.py` verbatim — it is already the reference pattern.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| GAP-10 | `video_color_grade.py` must update `graded_path` in Supabase `video_assets` after successful grading | Supabase upsert pattern documented below; existing pattern in `video_metadata.py` lines 289/357 |
| GAP-11 | All processing scripts support checkpoint-based resume (skip already-completed files on re-run) | Checkpoint/resume pattern documented below; shared helper recommended |
| GAP-13 | 5 video pipeline scripts write logs to `E:\Sentinel\logs\{script_name}.log` with file + stdout handlers | Reference pattern exists verbatim in `ingest_sorter.py` lines 73-84; five scripts need identical upgrade |
| DEPR-01 | Replace `datetime.utcnow()` with `datetime.now(datetime.UTC)` in `archive_sync.py`, `ingest_sorter.py`, `folder_watcher.py` | Python 3.11+ `datetime.UTC` confirmed available; system is Python 3.14.3 |
| ERR-01 | Standardize exit codes (0=success, 1=partial failure, 2=fatal), consistent log format, stderr to log | Existing scripts use 0/1 inconsistently; pattern documented below; no library needed |
</phase_requirements>

---

## Standard Stack

### Core (already in use — no new dependencies needed)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `logging` | stdlib | Dual file+console handlers | Already used; 5 scripts missing file handler |
| `datetime` | stdlib | UTC timestamps | `datetime.UTC` available since Python 3.11; system is 3.14.3 |
| `json` | stdlib | Checkpoint file serialization | Already used throughout |
| `os`, `pathlib` | stdlib | Atomic file operations for checkpoints | Already used |
| `supabase` | >=2.0.0 | Database client for GAP-10 upsert | Already in requirements.txt |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `tempfile` | stdlib | Atomic writes (write-to-temp, rename) | Checkpoint file writes to prevent corruption |
| `sys` | stdlib | Exit codes via `sys.exit(int)` | Standardized exit codes for ERR-01 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `logging` | `structlog` or `loguru` | v2 requirement (OBS-01); out of scope for Phase 1 |
| JSON checkpoints | SQLite | Overkill; JSON is readable, debuggable, and sufficient |
| Manual upsert | `tenacity` retry wrapper | Useful but CONCERNS.md flags Supabase retry as fragile; keep simple for Phase 1 |

**Installation:** No new packages needed for Phase 1.

---

## Architecture Patterns

### Pattern 1: Dual File+Console Logging (GAP-13)

**What:** Every script calls `setup_logging()` once in `main()`. The function creates the log
directory, configures `logging.basicConfig` with two handlers (FileHandler + StreamHandler),
and returns a named logger.

**When to use:** Always. All 5 video scripts need this added.

**Reference implementation** — from `ingest_sorter.py` lines 73-84 (HIGH confidence, verified):

```python
LOG_DIR = r"E:\Sentinel\logs"

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "video_color_grade.log")  # change per script
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)
```

**Critical detail:** The 5 video scripts currently have `setup_logging()` but it only has a
`StreamHandler`. The fix is to add `LOG_DIR` constant and `logging.FileHandler(log_file)` to
each existing function. Do NOT restructure the function signature — it is called identically
in `main()` across all scripts already.

**Target scripts and log file names:**

| Script | Current handlers | Target log file |
|--------|-----------------|-----------------|
| `video_color_grade.py` | StreamHandler only | `video_color_grade.log` |
| `video_proxy_gen.py` | StreamHandler only | `video_proxy_gen.log` |
| `video_format_export.py` | StreamHandler only | `video_format_export.log` |
| `srt_telemetry_parser.py` | StreamHandler only | `srt_telemetry_parser.log` |
| `video_qa.py` | StreamHandler only | `video_qa.log` |

### Pattern 2: datetime.UTC Migration (DEPR-01)

**What:** Replace `datetime.utcnow()` with `datetime.now(datetime.UTC)`. The result is a
timezone-aware datetime. When producing ISO 8601 strings, use `.isoformat()` directly —
it will include `+00:00` offset. If the downstream consumer (n8n webhook) requires a trailing
`Z`, replace with `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`.

**Python 3.11+ change** (HIGH confidence — official docs):
- `datetime.UTC` is an alias for `datetime.timezone.utc` added in Python 3.11
- `datetime.utcnow()` deprecated in 3.12, will be removed in a future version
- System is Python 3.14.3 — deprecation warning is active

**Three locations (verified by grep):**

```python
# archive_sync.py line 206 — used for cutoff calculation
# BEFORE:
cutoff = datetime.utcnow() - timedelta(days=days)
# AFTER:
cutoff = datetime.now(datetime.UTC) - timedelta(days=days)

# ingest_sorter.py line 339 — used in webhook payload
# BEFORE:
"ingested_at": datetime.utcnow().isoformat() + "Z",
# AFTER:
"ingested_at": datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),

# folder_watcher.py line 109 — used in webhook inventory
# BEFORE:
"detected_at": datetime.utcnow().isoformat() + "Z",
# AFTER:
"detected_at": datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
```

**Import note:** All three files already import `from datetime import datetime, timedelta` (or
just `from datetime import datetime`). `datetime.UTC` is accessed via the `datetime` class —
no additional import needed.

### Pattern 3: Checkpoint/Resume (GAP-11)

**What:** Before processing a list of files, read a JSON manifest of previously completed
files. Skip any file already in the manifest. After each successful file, atomically append
to the manifest.

**When to use:** Any script that processes a list of files in a loop where each item takes
non-trivial time (FFmpeg, Supabase uploads, file copies).

**Recommended approach:** Create `checkpoint.py` as a shared utility. Scripts import it.

```python
# checkpoint.py — new shared utility
import json
import os
import tempfile

CHECKPOINT_VERSION = 1

def checkpoint_path(mission_path, script_name):
    """Returns path to checkpoint file for this script + mission."""
    return os.path.join(mission_path, f".checkpoint_{script_name}.json")

def load_checkpoint(mission_path, script_name):
    """Load set of completed file paths. Returns empty set if no checkpoint."""
    path = checkpoint_path(mission_path, script_name)
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("version") != CHECKPOINT_VERSION:
            return set()
        return set(data.get("completed", []))
    except (json.JSONDecodeError, KeyError, OSError):
        return set()

def save_checkpoint(mission_path, script_name, completed):
    """Atomically write checkpoint. completed is a set/list of file paths."""
    path = checkpoint_path(mission_path, script_name)
    data = {
        "version": CHECKPOINT_VERSION,
        "script": script_name,
        "completed": sorted(completed),
    }
    # Atomic write: write to temp file, rename to target
    dir_ = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, path)  # Atomic on same filesystem
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def clear_checkpoint(mission_path, script_name):
    """Remove checkpoint file (e.g., on fresh run with --force)."""
    path = checkpoint_path(mission_path, script_name)
    if os.path.isfile(path):
        os.unlink(path)
```

**Usage in a video script:**

```python
from checkpoint import load_checkpoint, save_checkpoint

def main():
    # ... arg parsing ...
    mission_path = os.path.abspath(args.mission_path)

    completed = load_checkpoint(mission_path, "video_color_grade")

    for video_path in videos:
        if video_path in completed:
            log.info(f"  Skip (checkpoint): {os.path.basename(video_path)}")
            continue

        ok, stderr = grade_video(video_path, output_path, lut_path)

        if ok:
            completed.add(video_path)
            save_checkpoint(mission_path, "video_color_grade", completed)
            log.info(f"  OK: {output_path}")
        else:
            log.error(f"  FAILED: {os.path.basename(video_path)}")
```

**Key design decisions:**
- Track by **input file path** (stable, unique per mission)
- Save checkpoint after each successful file (not batched) — so partial progress is preserved
- Use `os.replace()` for atomic rename — POSIX-atomic, also works on Windows (Python 3.3+)
- Store in mission folder (`.checkpoint_{script}.json`) — not in `LOG_DIR` — so it travels with the mission
- `--force` flag should call `clear_checkpoint()` to re-process from scratch

**Scripts requiring GAP-11:**

| Script | Loop type | Checkpoint key |
|--------|-----------|---------------|
| `video_color_grade.py` | per MP4 in video/full/ | input video path |
| `video_proxy_gen.py` | per video in graded/ or full/ | input video path |
| `video_format_export.py` | per format config | format name (not file) |
| `srt_telemetry_parser.py` | per SRT file | SRT file path |
| `video_qa.py` | per Supabase asset | asset id (string) |

**Note on `video_format_export.py`:** The loop is over format configs, not input files.
Checkpoint key should be `fmt["name"]` (e.g., `"instagram_reels"`) since a single master
file is processed into multiple outputs. Already has per-format output files in `video/exports/`
which serve as a natural existence check — but explicit checkpoint is cleaner for resume.

**Note on `video_qa.py`:** Operates on Supabase asset IDs, not file paths. Checkpoint key is
`asset["id"]` (UUID string). The Supabase update (`update_qa_status`) is idempotent, so
re-running on already-QA'd assets is safe but slow (extra network round-trips). Checkpoint
prevents redundant API calls.

### Pattern 4: Standardized Exit Codes (ERR-01)

**What:** Define and enforce three exit code values across all scripts.

| Code | Meaning | When to use |
|------|---------|-------------|
| `0` | Full success | All files processed successfully |
| `1` | Partial failure | Some files failed, some succeeded |
| `2` | Fatal / config error | Can't proceed at all (bad args, missing FFmpeg, missing env var) |

**Current state (verified by code inspection):**
- `video_proxy_gen.py`: Uses `sys.exit(1)` when `fail_count > 0` — closest to standard
- `video_color_grade.py`: No `sys.exit()` at end — exits 0 even on failures
- `video_format_export.py`: No `sys.exit()` at end — exits 0 even on failures
- `srt_telemetry_parser.py`: `sys.exit(1)` only when `--upload` + no `--mission-id`
- `video_qa.py`: No `sys.exit()` at end

**Pattern to apply in `main()`:**

```python
def main():
    # ...

    # Fatal exit (already done in most scripts via sys.exit(message))
    if not os.path.isdir(mission_path):
        sys.exit(2)  # Change from sys.exit(message) to sys.exit(2) for parseable exit

    # After processing loop:
    if fail_count > 0 and ok_count > 0:
        log.warning(f"{fail_count} file(s) failed")
        sys.exit(1)   # partial failure
    elif fail_count > 0:
        log.error(f"All {fail_count} file(s) failed")
        sys.exit(2)   # fatal — nothing succeeded
    # else: implicit sys.exit(0)
```

**Important:** Current scripts call `sys.exit(message_string)` for fatal config errors. This
prints the message BUT exits with code 1 (because the string is truthy). For n8n orchestration,
we need the exit code to be `2` for these cases. Change to:

```python
# BEFORE:
sys.exit(f"Mission folder not found: {mission_path}")

# AFTER:
log.error(f"Mission folder not found: {mission_path}")
sys.exit(2)
```

**stderr to log:** Fatal errors should use `log.error()` before `sys.exit(2)`. The dual-handler
logging (GAP-13) ensures stderr content is captured in the log file. Do NOT redirect stderr
separately — the logging setup handles it.

### Pattern 5: Supabase graded_path Update (GAP-10)

**What:** After `grade_video()` succeeds in `video_color_grade.py`, update the `video_assets`
row for that file to set `graded_path = output_path`.

**Why upsert not update:** The `video_assets` row may or may not exist at grading time.
`video_metadata.py` creates it; grading runs before metadata. Use `upsert` with
`on_conflict="mission_id,filename"` so it creates if missing, updates if present.

**Supabase Python client upsert pattern** (verified against supabase-py docs, HIGH confidence):

```python
def update_graded_path(mission_id, filename, graded_path):
    """Update or create video_assets row with graded_path."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return  # Skip silently — Supabase is optional for grading
    try:
        from supabase import create_client
    except ImportError:
        return

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    client.table("video_assets").upsert(
        {
            "mission_id": mission_id,
            "filename": filename,
            "graded_path": graded_path,
        },
        on_conflict="mission_id,filename",
    ).execute()
```

**CLI integration:** `video_color_grade.py` needs `--mission-id` argument (optional) and
`--upload` flag to opt-in to Supabase update. When not provided, grading still works fully —
Supabase update is skipped with a log warning.

```python
parser.add_argument("--mission-id", help="Supabase mission UUID (required for --upload)")
parser.add_argument("--upload", action="store_true", help="Update graded_path in Supabase video_assets")
```

**In the processing loop:**

```python
if ok:
    # ... existing log/results code ...
    if args.upload and args.mission_id:
        update_graded_path(args.mission_id, filename, output_path)
        log.info(f"  Supabase: graded_path updated")
    elif args.upload and not args.mission_id:
        log.warning("  --upload requires --mission-id; skipping Supabase update")
```

### Anti-Patterns to Avoid

- **Adding `force=True` to `logging.basicConfig`:** Not needed if `setup_logging()` is called
  once at program start. Using `force=True` silently drops handlers configured elsewhere.
- **Using `os.rename()` instead of `os.replace()` for atomic checkpoint writes:** `os.rename()`
  raises on Windows if destination exists; `os.replace()` is atomic and overwrites safely.
- **Storing checkpoints in `LOG_DIR`:** Logs are for humans; checkpoints are pipeline state.
  Keep checkpoints in the mission folder so they're self-contained.
- **Checking `output_path` existence as resume signal** (instead of checkpoint): File existence
  is unreliable — partial writes leave orphan files that look complete. Checkpoint is authoritative.
- **`sys.exit("string")` for fatal errors:** Exits with code 1 (truthy string), not 2. n8n
  cannot distinguish fatal from partial failure. Use `log.error()` + `sys.exit(2)`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic file writes | Custom lock file | `tempfile.mkstemp` + `os.replace()` | Handles crashes mid-write; both stdlib |
| Supabase upsert | INSERT + UPDATE + SELECT | `client.table().upsert(on_conflict=...)` | Client handles conflict resolution |
| UTC datetime | Manual TZ string construction | `datetime.now(datetime.UTC)` | Stdlib; correct, timezone-aware |
| Log file rotation | Custom log pruning | `logging.handlers.RotatingFileHandler` | Not needed for Phase 1; log file per script is fine |

---

## Common Pitfalls

### Pitfall 1: logging.basicConfig Called Twice

**What goes wrong:** If any library (watchdog, supabase, requests) calls `logging.basicConfig`
before the script's `setup_logging()`, the second call is silently ignored — no file handler
is added.

**Why it happens:** `logging.basicConfig` is a no-op if the root logger already has handlers.

**How to avoid:** Call `setup_logging()` as the very first thing in `main()`, before any
imports that might configure logging.

**Warning signs:** Log file exists but is empty; stdout shows logs but file does not.

**Fix if it happens:**
```python
# Instead of basicConfig, use explicit handler attachment:
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(logging.FileHandler(log_file))
root_logger.addHandler(logging.StreamHandler(sys.stdout))
```

### Pitfall 2: Checkpoint Race on Windows

**What goes wrong:** `os.replace()` on Windows can fail with `PermissionError` if an
antivirus scanner or Windows Defender has the temp file open for scanning.

**Why it happens:** Windows file locking is advisory but antivirus tools hold handles.

**How to avoid:** Wrap `save_checkpoint()` in `try/except OSError` and log a warning rather
than crashing. Checkpoint failure is non-fatal — worst case the script re-processes a file
on resume.

**Warning signs:** `PermissionError` in log on Windows rig.

### Pitfall 3: datetime.UTC vs timezone.utc Confusion

**What goes wrong:** Using `datetime.datetime.utcnow()` still compiles without error in
Python 3.14; it just emits a `DeprecationWarning`. Devs sometimes fix the warning with
`warnings.filterwarnings("ignore")` instead of migrating.

**Why it happens:** The warning is not yet an error.

**How to avoid:** The migration is mechanical. `datetime.UTC` is a class attribute of
`datetime.datetime` (i.e., `from datetime import datetime; datetime.UTC`). It is also
accessible as `datetime.timezone.utc`.

**Warning signs:** `DeprecationWarning: datetime.datetime.utcnow() is deprecated` in test
output or runtime logs.

### Pitfall 4: Supabase Upsert Missing Conflict Column

**What goes wrong:** `upsert(on_conflict="mission_id,filename")` fails if the `video_assets`
table doesn't have a UNIQUE constraint on `(mission_id, filename)`.

**Why it happens:** Supabase upsert relies on the database unique constraint to determine
what "conflict" means.

**How to avoid:** Verify the Supabase schema has: `UNIQUE (mission_id, filename)` on
`video_assets`. Check this before implementing GAP-10.

**Warning signs:** `supabase.exceptions.APIError: there is no unique or exclusion constraint
matching the ON CONFLICT specification`.

### Pitfall 5: Exit Code 1 From sys.exit(string)

**What goes wrong:** `sys.exit("error message")` prints to stderr and exits with code 1
(because non-empty string is truthy). This makes fatal errors look like partial failures
to n8n.

**Why it happens:** `sys.exit()` with a non-integer maps to code 1 by convention.

**How to avoid:** For ERR-01 compliance, ALL `sys.exit(string)` calls must be converted to
`log.error(string); sys.exit(2)` for fatal errors. Keep the log message; lose the string arg.

**Warning signs:** n8n sees exit code 1 for both "5 of 10 files failed" and "FFmpeg not found".

---

## Code Examples

All examples are based on verified source code from this codebase.

### GAP-13: Upgrading setup_logging() in a Video Script

```python
# video_color_grade.py — full replacement of setup_logging()

LOG_DIR = r"E:\Sentinel\logs"   # Add this constant near top of CONFIG section

def setup_logging(log_dir=LOG_DIR):
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "video_color_grade.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)
```

Changes vs current: Add `LOG_DIR` constant, add `os.makedirs`, add `log_file`, add
`logging.FileHandler(log_file)` to handlers list.

### DEPR-01: datetime.utcnow() Replacement

```python
# archive_sync.py — cleanup_old_delivered()
# Line 206: replace utcnow() with now(datetime.UTC)
cutoff = datetime.now(datetime.UTC) - timedelta(days=days)

# Also update the comparison on line 213 — createdTime from Drive API is UTC ISO 8601
# The existing .replace(tzinfo=None) strips timezone from the Drive timestamp.
# With aware cutoff, need consistent comparison:
created = datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00"))
# created is now timezone-aware; cutoff is also timezone-aware — comparison works.
# Remove the .replace(tzinfo=None) that was needed to compare with naive utcnow()
```

```python
# ingest_sorter.py — fire_webhook() line 339
"ingested_at": datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),

# folder_watcher.py — build_inventory() line 109
"detected_at": datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
```

**Caution for archive_sync.py:** Line 213 currently does `.replace(tzinfo=None)` to strip
timezone from the Drive API timestamp before comparing with the naive `datetime.utcnow()`
cutoff. Once cutoff is timezone-aware, the comparison partner must also be aware. Either:
(a) keep both naive (`.replace(tzinfo=None)` on both) or (b) make both aware (preferred).
Option (b) is correct; `.replace(tzinfo=None)` on line 213 should be removed.

### GAP-10: graded_path Supabase Update

```python
# video_color_grade.py — new function + integration

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

def update_graded_path(mission_id, filename, graded_path):
    """Update video_assets.graded_path after successful color grading."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return False
    try:
        from supabase import create_client
        client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        client.table("video_assets").upsert(
            {
                "mission_id": mission_id,
                "filename": filename,
                "graded_path": graded_path,
            },
            on_conflict="mission_id,filename",
        ).execute()
        return True
    except Exception as e:
        logging.getLogger(__name__).warning(f"Supabase update failed: {e}")
        return False
```

### ERR-01: Standardized Exit Codes

```python
# Standard main() exit pattern for all video scripts

def main():
    # ... processing loop ...

    ok_count = sum(1 for r in results if r["status"] == "ok")
    fail_count = sum(1 for r in results if r["status"] == "failed")
    log.info(f"Complete: {ok_count} ok, {fail_count} failed")

    if fail_count > 0 and ok_count > 0:
        sys.exit(1)   # Partial failure — some work done
    elif fail_count > 0:
        sys.exit(2)   # All failed — fatal outcome
    # sys.exit(0) implicit

# Replace all sys.exit("fatal message") with:
    log.error("Fatal message here")
    sys.exit(2)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `datetime.utcnow()` | `datetime.now(datetime.UTC)` | Python 3.12 deprecated | Timezone-aware datetime; correct UTC |
| `sys.exit("string")` | `log.error(); sys.exit(int)` | Best practice for CLI | Machine-parseable exit codes |
| Skip if output file exists | JSON checkpoint manifest | Phase 1 | Handles partial writes, rename failures |
| Supabase `insert()` | `upsert(on_conflict=...)` | supabase-py v2+ | Idempotent; safe to re-run |

**Deprecated/outdated:**
- `datetime.utcnow()`: Deprecated Python 3.12. Returns naive datetime. Use `datetime.now(datetime.UTC)`.
- `logging.basicConfig` called after handlers exist: Silently ignored. Call before imports.

---

## Open Questions

1. **video_assets unique constraint for GAP-10 upsert**
   - What we know: `upsert(on_conflict="mission_id,filename")` requires a unique constraint in the DB
   - What's unclear: Whether this constraint currently exists on the `video_assets` table in Supabase
   - Recommendation: Query Supabase schema before Plan 01-04 executes. If constraint is missing,
     add a migration. Alternatively, use `.update().eq("mission_id", x).eq("filename", y)` as a
     two-step approach (check if row exists, insert or update).

2. **video_qa.py checkpoint key: asset ID vs filename**
   - What we know: `video_qa.py` iterates over Supabase rows (asset dicts with `id` UUID)
   - What's unclear: Whether asset IDs are stable across re-runs (they are, as UUIDs in Supabase)
   - Recommendation: Use `asset["id"]` as checkpoint key. It is UUID-stable and mission-scoped.

3. **video_format_export.py exit code on 0 formats exported**
   - What we know: If all formats fail, `fail_count > 0` and `ok_count == 0`
   - What's unclear: Should this be code 2 (fatal) or code 1 (partial)? No formats = mission cannot complete.
   - Recommendation: Code 2 when no formats succeed. Code 1 when some succeed.

---

## Sources

### Primary (HIGH confidence)

- Verified against `C:/Users/redle/drone-pipeline/ingest_sorter.py` — reference logging implementation
- Verified against `C:/Users/redle/drone-pipeline/archive_sync.py` — datetime.utcnow() location (line 206)
- Verified against `C:/Users/redle/drone-pipeline/folder_watcher.py` — datetime.utcnow() location (line 109)
- Verified against `C:/Users/redle/drone-pipeline/ingest_sorter.py` — datetime.utcnow() location (line 339)
- Verified against `C:/Users/redle/drone-pipeline/video_color_grade.py` — no Supabase client, no file handler
- Verified against `C:/Users/redle/drone-pipeline/video_proxy_gen.py` — no file handler
- Verified against `C:/Users/redle/drone-pipeline/video_format_export.py` — no file handler, no exit codes
- Verified against `C:/Users/redle/drone-pipeline/srt_telemetry_parser.py` — no file handler
- Verified against `C:/Users/redle/drone-pipeline/video_qa.py` — no file handler, no exit codes
- Verified against `.planning/codebase/CONVENTIONS.md` — logging pattern, exit code conventions
- Verified against `.planning/codebase/CONCERNS.md` — all gap descriptions and fix approaches
- Python 3.14.3 confirmed on system (`python --version`)
- `datetime.UTC` available since Python 3.11 (stdlib docs)
- `os.replace()` atomic on POSIX + Windows (Python docs, stdlib)
- `supabase-py` upsert with `on_conflict` — supabase-py v2 API

### Secondary (MEDIUM confidence)

- Checkpoint/resume pattern: industry-standard JSON manifest approach; no specific library citation
  needed as this is stdlib-only

---

## Metadata

**Confidence breakdown:**
- GAP-13 (logging): HIGH — exact reference implementation exists in codebase
- DEPR-01 (datetime): HIGH — three locations confirmed by grep; Python 3.11+ stdlib
- GAP-11 (checkpoint): HIGH for pattern; MEDIUM for video_qa.py Supabase-keyed variant
- ERR-01 (exit codes): HIGH — current behavior verified by code inspection
- GAP-10 (Supabase update): HIGH for pattern; MEDIUM for constraint existence (needs verification)

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stdlib patterns are stable; supabase-py API stable in v2)

**Scope note:** This research covers only Phase 1 requirements (GAP-10, GAP-11, GAP-13,
DEPR-01, ERR-01). Test infrastructure (TEST-01/02/03) and unit tests (UNIT-*) are out of
scope — those belong to Phase 2 and beyond.
