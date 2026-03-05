# Domain Pitfalls

**Domain:** Multi-path workflow orchestration, long-running subprocess management, event-driven file triggers on Windows
**Project:** Sentinel Drone Pipeline v3.0 — Package Router & End-to-End Automation
**Researched:** 2026-03-05
**Confidence:** HIGH (n8n timeout/buffer issues, Windows process management, watchdog race conditions) | MEDIUM (n8n v2.0 Execute Command migration, MipMap process lifecycle) | LOW (n8n internal memory behavior under multi-hour executions)

---

## Critical Pitfalls

Mistakes that cause rewrites, data loss, or silent processing failures.

### Pitfall 1: n8n Execute Command Node Disabled in n8n v2.0+

**What goes wrong:**
After upgrading n8n to v2.0+, the existing Path E workflow and all new v3.0 workflows that use `n8n-nodes-base.executeCommand` nodes silently fail with `Unrecognized node type: n8n-nodes-base.executeCommand`. The Path E workflow (which has 5 Execute Command nodes for E1-E4 + regenerate) stops working entirely. No warning during upgrade.

**Why it happens:**
n8n v2.0 disabled the Execute Command and LocalFileTrigger nodes by default for security reasons. The existing `path_e_workflow.json` uses `executeCommand` typeVersion 1 nodes extensively. When n8n upgrades, these nodes are not recognized unless explicitly re-enabled via environment variables.

**Consequences:**
- ALL existing Path E automation breaks silently
- New Package Router workflow cannot launch any Python scripts
- Path C MipMap automation impossible without Execute Command or an alternative
- Webhook triggers still fire but downstream processing nodes fail

**Prevention:**
Add these environment variables to the n8n service configuration BEFORE upgrading:
```env
# docker-compose.yml or .env for n8n
NODES_EXCLUDE=[]
# OR more targeted:
N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand
```
Alternatively, pin n8n to a 1.x version until v3.0 is complete. Document this in the deployment checklist. Test with `n8n list:workflow` after any n8n upgrade to verify all node types are recognized.

**Detection:**
- Workflow execution log shows "Problem running workflow: Unrecognized node type"
- Webhooks return 500 errors
- n8n UI shows Execute Command nodes with red error badges

**Phase to address:** Phase 0 (pre-development) -- verify n8n version and configure before writing any workflows

---

### Pitfall 2: n8n Execute Command stdout maxBuffer Overflow on MipMap

**What goes wrong:**
The n8n Execute Command node uses Node.js `child_process.exec()` internally, which buffers ALL stdout and stderr in memory until the command completes. MipMap's `reconstruct_full_engine.exe` outputs continuous progress logging to stdout (percentage complete, per-image alignment status, dense cloud progress). Over a multi-hour reconstruction of 200+ images, this can produce 50-200MB of stdout text. When the buffer exceeds ~1MB (Node.js default maxBuffer), the node throws `stdout maxBuffer length exceeded` and kills the MipMap process mid-reconstruction.

**Why it happens:**
Node.js `child_process.exec()` has a default `maxBuffer` of ~1MB. n8n's Execute Command node does not expose a configuration to increase this. The Path E workflow's E1-E4 scripts work fine because they output a single JSON line (<1KB). But MipMap outputs line-by-line progress for every image alignment step, every dense cloud iteration, and every mesh generation pass.

**Consequences:**
- MipMap killed mid-reconstruction after 1-3 hours of processing (wasted time)
- Workspace left in corrupt state on D:/ drive (partial results, locked files)
- No orthomosaic produced, blocking all downstream paths (A, E)
- Repeated failures consume disk space with abandoned workspaces

**Prevention:**
Do NOT use Execute Command to run MipMap directly. Instead:

**Option A (recommended): Fire-and-forget with status polling**
```
1. Execute Command: launch MipMap via a wrapper script that redirects stdout to file
   Command: start /B reconstruct_full_engine.exe --task_json=... > D:\workspace\mipmap.log 2>&1
2. Poll for completion using a Wait + Check loop (similar to existing E0 ortho polling)
3. Check MipMap result by looking for output files, not by parsing stdout
```

**Option B: Webhook callback from wrapper script**
```python
# mipmap_launcher.py — wrapper that n8n calls
import subprocess, requests, sys
proc = subprocess.Popen(cmd, stdout=open(log_path, 'w'), stderr=subprocess.STDOUT)
ret = proc.wait()  # blocks until MipMap finishes (hours)
requests.post(callback_url, json={"exit_code": ret, "mission_id": mission_id})
```
n8n workflow uses Webhook Wait node to pause until the callback arrives. This is the same pattern used for the Review Gate in Path E.

**Option C: n8n Sub-workflow with Wait node**
Launch MipMap wrapper as a background process, return immediately from Execute Command, then use n8n Wait node + file existence check loop (already proven in Path E's E0 ortho polling pattern, but extend timeout from 30 min to 8 hours).

For ALL existing Path E Execute Command nodes (E1-E4): these are safe because they output only a single JSON line. But add `2>NUL` or stderr redirection as a safety measure in case future logging is added to those scripts.

**Detection:**
- n8n execution log shows "stdout maxBuffer length exceeded"
- MipMap process disappears from Task Manager mid-run
- D:/ workspace has partial results (result/ folder exists but no orthomosaic.tif)

**Phase to address:** Phase 1 (Path C MipMap automation) -- must be solved before first automated MipMap run

---

### Pitfall 3: n8n Workflow Execution Timeout Kills Multi-Hour Processing

**What goes wrong:**
n8n's default workflow execution timeout is -1 (unlimited) for self-hosted, but if `EXECUTIONS_TIMEOUT` is set (common in Docker deployments), the ENTIRE workflow is killed after the timeout period. A Package Router workflow that launches MipMap (2-6 hours), waits for completion, copies the ortho, then triggers downstream paths will exceed any reasonable timeout. The workflow is terminated mid-execution with no cleanup.

**Why it happens:**
The `EXECUTIONS_TIMEOUT` environment variable sets a global maximum. `EXECUTIONS_TIMEOUT_MAX` sets an absolute ceiling that per-workflow settings cannot exceed. If either is set to 3600 (1 hour, a common default), the Path C automation dies before MipMap finishes.

**Consequences:**
- MipMap may continue running as orphan process (it was launched, n8n just stops tracking it)
- Supabase status stuck in "processing" with no update to "complete" or "failed"
- Downstream paths (A, V, E) never triggered
- Operator has no visibility that the workflow died -- must manually check

**Prevention:**
```env
# n8n environment configuration
EXECUTIONS_TIMEOUT=-1          # Disable global timeout (self-hosted)
EXECUTIONS_TIMEOUT_MAX=-1      # No ceiling
```
For the Package Router workflow specifically, set per-workflow timeout in workflow settings to 28800 seconds (8 hours) to accommodate the worst-case MipMap reconstruction time.

Better architecture: Split the Package Router into short-lived sub-workflows:
1. **Router workflow** (seconds): Receives webhook, routes by package_type, fires sub-workflow triggers
2. **Path C workflow** (hours): MipMap launch + polling, ortho copy. Separate execution with its own timeout.
3. **Path A/V/B/D workflows** (minutes): Photo/video processing chains. Short, predictable duration.
4. **Path E workflow** (already exists): Vegetation analysis. 15-60 minutes.

Each sub-workflow has its own execution ID and timeout, so a long Path C run does not block or kill Path A/V processing.

**Detection:**
- n8n execution history shows "Execution timed out" for the workflow
- Supabase drone_jobs stuck in intermediate status
- MipMap still running in Task Manager but n8n shows no active execution

**Phase to address:** Phase 0 (n8n configuration) and Phase 1 (workflow architecture)

---

### Pitfall 4: Folder Watcher Race Condition -- Triggering Before SD Card Copy Completes

**What goes wrong:**
The current `folder_watcher.py` uses a 60-second debounce timer. When the operator copies files from an SD card to `E:\Sentinel\Incoming\`, the copy process may pause between DCIM folders (e.g., DJI_001 finishes, 90-second pause while operator navigates to DJI_002, then DJI_002 starts). The debounce timer fires after 60 seconds of the pause, triggering the webhook with an incomplete inventory (only DJI_001 files). The remaining DJI_002 files arrive after the webhook already fired.

**Why it happens:**
The `_triggered` set in `MissionFolderHandler` marks a folder as processed after debounce fires. Once triggered, `_reset_timer()` returns immediately (`if folder_name in self._triggered: return`). New files arriving in an already-triggered folder are silently ignored.

Looking at `folder_watcher.py` line 164:
```python
if folder_name in self._triggered:
    return  # Already processed
```

This is a one-shot trigger with no re-fire capability.

**Consequences:**
- Partial mission ingested (photos only, no video or PPK data)
- Package Router routes based on incomplete inventory (photo_count correct but video_count=0)
- MipMap workspace created with partial image set
- Reconstruction fails or produces low-quality ortho

**Prevention:**
Two complementary fixes:

1. **Increase debounce to 120-180 seconds** to accommodate multi-folder SD card copies:
```python
DEBOUNCE_SECONDS = 180  # 3 minutes -- covers most SD card copy operations
```

2. **Replace one-shot trigger with re-triggerable design** using a minimum file count or size threshold:
```python
def _on_debounce_complete(self, folder_name):
    with self._lock:
        # Don't permanently block re-triggering
        # Instead, track last trigger time and allow re-fire if new files arrive
        self._last_trigger[folder_name] = time.time()
        if folder_name in self._timers:
            del self._timers[folder_name]
    # ... fire webhook as before
    # Remove from _triggered set so future files can re-trigger
    # OR: use ingest_sorter.py with --webhook as the authoritative trigger instead
```

3. **Better approach: Use `ingest_sorter.py --webhook` as the primary trigger** instead of folder_watcher.py. The operator runs ingest_sorter.py manually after SD card copy is complete, which fires the webhook with a verified complete inventory. The folder_watcher becomes a safety net, not the primary trigger.

**Detection:**
- Webhook payload shows `video_count: 0` for a mission that should have video
- MipMap workspace has fewer images than expected
- Log shows "Debounce complete" followed by new file creation events for the same folder

**Phase to address:** Phase 2 (folder watcher improvements) -- but design decision needed in Phase 0

---

### Pitfall 5: MipMap Process Orphaned When n8n Workflow Stops

**What goes wrong:**
When n8n launches MipMap via `subprocess.Popen()` (through Execute Command or a wrapper script), and the n8n workflow is manually stopped, times out, or n8n service restarts, the MipMap process continues running as an orphan on Windows. There is no parent process to signal termination. MipMap keeps running for hours, consuming GPU, CPU, and disk on D:/, with no workflow tracking its output.

On Windows specifically, `subprocess.Popen` does not create a process group by default, so terminating the parent does not cascade to children. The n8n Execute Command node calls `child_process.exec()` which creates a cmd.exe intermediary, further complicating cleanup.

**Why it happens:**
Windows does not automatically terminate child processes when the parent dies (unlike Unix process groups with `PGID`). The n8n Execute Command node has no mechanism to track or kill child processes after workflow cancellation. If the Execute Command node is killed, the cmd.exe wrapper is killed, but the underlying `reconstruct_full_engine.exe` was launched by cmd.exe and continues independently.

**Consequences:**
- GPU locked by orphan MipMap (blocks Path E canopy detection if it needs GPU)
- D:/ drive fills up with abandoned workspace data
- Re-running the workflow launches a SECOND MipMap instance (competing for GPU/disk)
- No way to associate orphan process with a mission ID without manual Task Manager inspection

**Prevention:**
```python
# mipmap_launcher.py — track process via PID file
import subprocess, os, signal, atexit

pid_file = os.path.join(workspace_dir, "mipmap.pid")

proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)

# Write PID for cleanup
with open(pid_file, 'w') as f:
    f.write(str(proc.pid))

# Register cleanup
def cleanup():
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    if os.path.exists(pid_file):
        os.remove(pid_file)

atexit.register(cleanup)
```

Additionally, add a pre-flight check to the MipMap launcher:
```python
# Check for orphan MipMap processes before launching
import psutil
for p in psutil.process_iter(['name', 'pid']):
    if p.info['name'] == 'reconstruct_full_engine.exe':
        raise RuntimeError(f"MipMap already running (PID {p.info['pid']}). "
                          f"Kill it or wait for completion before launching a new job.")
```

Write the PID to Supabase `drone_jobs.mipmap_pid` so the Package Router can track it.

**Detection:**
- `tasklist /FI "IMAGENAME eq reconstruct_full_engine.exe"` shows running MipMap with no active n8n execution
- GPU utilization at 80-100% with no active n8n workflow
- Multiple MipMap processes in Task Manager

**Phase to address:** Phase 1 (Path C MipMap automation) -- must be part of the launcher design

---

### Pitfall 6: GeoTIFF Copy Failure -- 500MB+ File Between D:/ and E:/ Drives

**What goes wrong:**
After MipMap completes on D:/ workspace, the MipMap output harvester must copy the orthomosaic.tif (typically 200MB-1.5GB) from `D:\{workspace}\result\` to `E:\Sentinel\Output\{mission}\mapping\`. Using `shutil.copy2()` for this copy has three failure modes:

1. **Disk full on E:/**: No pre-check, copy fails partway, leaves a truncated file that downstream scripts (Path E) try to open as valid GeoTIFF
2. **File locked**: MipMap may not fully release file handles on the GeoTIFF immediately after exit (Windows file handle caching). `shutil.copy2()` raises `PermissionError`.
3. **Interrupted copy**: Power loss, USB drive disconnect, or n8n stop during the 30-120 second copy window leaves a partial file with the correct filename but corrupt contents.

**Why it happens:**
`shutil.copy2()` is not atomic -- it writes bytes incrementally to the destination. If interrupted, the partial file exists at the destination path with a plausible filename. Downstream scripts check `if os.path.exists(ortho_path)` (as the existing Path E workflow does) and find "FOUND", but the file is truncated/corrupt.

**Consequences:**
- Path E canopy detection opens a truncated GeoTIFF and either crashes or produces garbage detections
- Operator unaware file is corrupt -- the existing Path E E0 check only tests existence, not integrity
- Re-running requires manual cleanup of the partial file

**Prevention:**
```python
import shutil, os, hashlib

def safe_copy_large_file(src, dst, verify=True):
    """Copy with temp file + rename for atomicity, plus optional hash verification."""
    dst_tmp = dst + ".tmp"

    # Pre-flight: check destination disk space
    stat = shutil.disk_usage(os.path.dirname(dst))
    src_size = os.path.getsize(src)
    if stat.free < src_size * 1.1:  # 10% headroom
        raise IOError(f"Insufficient disk space: need {src_size}, have {stat.free}")

    # Copy to temp file
    shutil.copy2(src, dst_tmp)

    # Verify size matches
    if os.path.getsize(dst_tmp) != src_size:
        os.remove(dst_tmp)
        raise IOError(f"Size mismatch: src={src_size}, dst={os.path.getsize(dst_tmp)}")

    # Optional: verify GeoTIFF is readable
    if verify and dst.endswith('.tif'):
        import rasterio
        try:
            with rasterio.open(dst_tmp) as ds:
                _ = ds.profile  # validates header
        except Exception as e:
            os.remove(dst_tmp)
            raise IOError(f"Copied file is not a valid GeoTIFF: {e}")

    # Atomic rename (same drive = instant, cross-drive = this is the copy itself)
    if os.path.exists(dst):
        os.replace(dst, dst + ".bak")
    os.rename(dst_tmp, dst)
```

For the existing Path E E0 ortho check, upgrade from existence check to integrity check:
```
# Instead of: if exist "ortho_path" (echo FOUND)
# Use Execute Command that runs Python to validate the file:
python -c "import rasterio; rasterio.open(r'ortho_path').close(); print('VALID')"
```

**Detection:**
- Path E E1 crashes with `rasterio.errors.RasterioIOError: not a GeoTIFF file`
- File size on E:/ is significantly smaller than on D:/
- `.tmp` files left in mapping/ folder

**Phase to address:** Phase 1 (MipMap output harvester) -- build the safe copy function before first automated copy

---

## Moderate Pitfalls

### Pitfall 7: Webhook Fire-and-Forget Loses Missions on n8n Downtime

**What goes wrong:**
Both `folder_watcher.py` (line 109) and `ingest_sorter.py` (line 313) use `requests.post(webhook_url, json=payload, timeout=10)` with no retry logic and no persistent queue. If n8n is restarting, unresponsive, or has crashed, the webhook POST fails and the mission is lost. The operator sees "Webhook failed" in the log but has no automated recovery.

**Prevention:**
Add a persistent webhook queue with retry:
```python
import json, os, time, threading

RETRY_QUEUE_PATH = r"E:\Sentinel\logs\webhook_retry_queue.jsonl"
MAX_RETRIES = 5
RETRY_DELAYS = [30, 60, 300, 900, 3600]  # 30s, 1m, 5m, 15m, 1h

def fire_webhook_with_retry(payload, webhook_url):
    """Fire webhook with persistent retry queue."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            return True
        except requests.RequestException:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
            else:
                # Persist to disk for manual replay
                with open(RETRY_QUEUE_PATH, 'a') as f:
                    f.write(json.dumps({"payload": payload, "url": webhook_url,
                                       "failed_at": datetime.now(timezone.utc).isoformat()}) + "\n")
                return False
```

Add a `--replay-queue` CLI flag to both scripts that reads and replays the JSONL file.

**Detection:**
- Log shows "Webhook failed" entries
- Missions in `E:\Sentinel\Incoming\` that never appear in Supabase
- `webhook_retry_queue.jsonl` has entries

**Phase to address:** Phase 2 (webhook reliability) -- after core routing works

---

### Pitfall 8: Package Router Concurrent Path Execution Deadlocks GPU

**What goes wrong:**
The Package Router launches multiple paths concurrently for a mission (e.g., Path C for mapping + Path V for video). If Path C's MipMap finishes and triggers Path E while Path V's FFmpeg color grading is still running, the system has:
- MipMap (GPU-intensive, complete)
- Path E canopy detection (GPU-intensive, starting)
- FFmpeg video processing (CPU+GPU encoding)

Path E's DeepForest GPU inference and FFmpeg's NVENC encoding compete for the RTX 5070's 16GB VRAM. DeepForest may OOM with `CUDA out of memory` because FFmpeg's NVENC encoder has reserved a portion of VRAM.

**Prevention:**
Implement a GPU semaphore at the workflow level:
1. **Sequential GPU paths**: In the Package Router, ensure Path E only starts after Path V video encoding is complete (or at least after FFmpeg releases the GPU).
2. **n8n concurrency control**: Use `EXECUTIONS_CONCURRENCY_PRODUCTION_LIMIT=1` to prevent parallel workflow executions, OR use n8n's built-in concurrency control to limit Execute Command nodes.
3. **Script-level GPU lock**: Use a file-based lock in Python scripts:
```python
GPU_LOCK = Path(r"E:\Sentinel\.gpu.lock")
def acquire_gpu():
    while GPU_LOCK.exists():
        time.sleep(10)
    GPU_LOCK.touch()
def release_gpu():
    GPU_LOCK.unlink(missing_ok=True)
```

**Detection:**
- `CUDA out of memory` errors in canopy_detection.py when FFmpeg is running
- Task Manager shows GPU memory at 95%+ with multiple processes
- Path E fails intermittently (works when run alone, fails when concurrent with Path V)

**Phase to address:** Phase 3 (multi-path orchestration) -- when concurrent paths are first enabled

---

### Pitfall 9: Windows Path Length Exceeds 260 Characters in MipMap Workspace

**What goes wrong:**
MipMap workspace paths on D:/ use UUID-based directory structure: `D:\{uuid}\{mission-name}\{mission-name}-{date}\result\{output-type}\{tile}\filename.ext`. With long mission names and nested output types (e.g., `3d_tiles\tileset\L16\`), total path can exceed 260 characters, the default Windows `MAX_PATH` limit. File operations silently fail or throw cryptic `FileNotFoundError` even though the file exists.

**Why it happens:**
`ingest.py` creates workspace with `str(uuid.uuid4())` (36 chars) + mission name + task name + "result" + MipMap output subdirectories. The existing code at line 300: `result_dir = os.path.join(output_dir, "result").replace("/", "\\")` starts the nesting.

**Prevention:**
1. Enable Windows long path support (registry):
```
HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1
```
2. Use `\\?\` prefix for all paths passed to MipMap and in Python file operations
3. Shorten workspace UUIDs -- use 8-char short UUID instead of full 36-char UUID:
```python
user_id = str(uuid.uuid4())[:8]  # Short enough for workspace root
```
4. In Python 3.14, use `pathlib.Path` which handles long paths better than `os.path`

**Detection:**
- `FileNotFoundError` on files that visibly exist in Explorer
- MipMap logs show errors writing 3D tile output
- `os.path.exists()` returns False for paths > 260 chars

**Phase to address:** Phase 1 (workspace creation in MipMap launcher)

---

### Pitfall 10: watchdog Duplicate Events on Windows Cause Multiple Webhook Fires

**What goes wrong:**
On Windows, the `watchdog` library using `ReadDirectoryChangesW` fires multiple `on_modified` events for a single file write. Copying a large DNG file (25MB) triggers 3-8 modified events as Windows writes the file in chunks. Each event resets the debounce timer in `folder_watcher.py`, which is the intended behavior for debouncing, BUT if two rapid file writes happen right at the debounce boundary, the timer may fire between them, causing a premature trigger.

More critically, when `folder_watcher.py` is extended for v3.0 to watch MULTIPLE directories (Incoming for SD card, mapping/ for ortho output), the same Observer watching recursively can generate cascading events as file operations in one subfolder trigger directory modification events in parent folders.

**Prevention:**
1. The current debounce design is mostly correct for the single-directory case. Keep it.
2. For multi-directory watching (ortho output detection), use SEPARATE Observer instances per watch directory, not one recursive watcher.
3. Add file stability check before triggering:
```python
def _is_file_stable(self, folder_path, check_interval=5):
    """Check that no files changed size in the last check_interval seconds."""
    sizes = {}
    for root, _, files in os.walk(folder_path):
        for f in files:
            fp = os.path.join(root, f)
            sizes[fp] = os.path.getsize(fp)
    time.sleep(check_interval)
    for fp, old_size in sizes.items():
        if os.path.exists(fp) and os.path.getsize(fp) != old_size:
            return False
    return True
```
4. For ortho detection specifically, check for a MipMap completion marker file (e.g., `result/done.flag`) rather than watching for orthomosaic.tif creation, since the GeoTIFF is written incrementally.

**Detection:**
- Webhook fired multiple times for same mission folder
- n8n shows duplicate workflow executions for same mission_id
- Log shows "Debounce complete" followed immediately by another "Debounce complete" for same folder

**Phase to address:** Phase 2 (folder watcher extension for multi-path triggers)

---

## Minor Pitfalls

### Pitfall 11: ingest_sorter Webhook Skipped on Partial Copy but No Retry Later

**What goes wrong:**
`ingest_sorter.py` line 476: `if failed > 0: log.warning("Webhook skipped")`. This is a safety feature -- don't trigger processing on incomplete data. But there is no mechanism to retry the webhook after the operator fixes the failed copies. The mission sits in `Incoming/` with no processing triggered.

**Prevention:**
Add `--retry-webhook` flag that re-counts inventory and fires webhook for missions that have a checkpoint but no webhook record. Store webhook-fired status in the checkpoint JSON.

**Phase to address:** Phase 2 (reliability improvements)

---

### Pitfall 12: Supabase Status Stuck in Intermediate State After Workflow Failure

**What goes wrong:**
If any workflow node fails between status updates, the Supabase `drone_jobs` record remains in an intermediate status (`processing`, `detecting`, `classifying`, etc.) with no timeout or cleanup. This already exists in the Path E workflow (the error handler only sets `failed` if it reaches the error handler node), but becomes much worse in v3.0 where the Package Router manages multiple path statuses.

**Prevention:**
1. Add a Supabase `updated_at` timestamp to every status update
2. Create a cleanup cron job (or n8n schedule trigger) that finds jobs stuck in intermediate status for >24 hours and marks them `failed_stale`
3. Every workflow's error handler must set status to `failed` with an `error_message` field

**Phase to address:** Phase 1 (database schema) -- add `updated_at` trigger and stale job detection

---

### Pitfall 13: n8n Wait Node + Polling Loop for Path C Uses Workflow Static Data Shared Across Executions

**What goes wrong:**
The existing Path E workflow uses `$getWorkflowStaticData('global')` to track poll attempt count (line 119 of path_e_workflow.json). Static data is shared across ALL executions of the same workflow. If two missions are processing simultaneously, their poll counters interfere with each other -- one mission resets the counter while another is mid-poll, causing either premature timeout or infinite polling.

**Why it happens:**
`$getWorkflowStaticData('global')` is workflow-scoped, not execution-scoped. This is documented in n8n docs but easy to miss. The Path E workflow currently processes one mission at a time, so this hasn't been a problem yet. But the Package Router may trigger multiple Path C polls concurrently.

**Prevention:**
Use execution-scoped data instead:
```javascript
// Instead of:
const staticData = $getWorkflowStaticData('global');
staticData.pollAttempt = (staticData.pollAttempt || 0) + 1;

// Use node input data to track attempts:
const prevAttempt = $input.item.json.poll_attempt || 0;
return [{ json: { ...data, poll_attempt: prevAttempt + 1 } }];
```
Pass the counter through the workflow data flow, not static data. This is naturally execution-scoped.

**Detection:**
- Poll attempt count jumps erratically in logs (e.g., 3, 1, 4 instead of 1, 2, 3)
- One mission times out early while another polls indefinitely
- `$getWorkflowStaticData('global')` contains stale data from previous executions

**Phase to address:** Phase 1 -- fix in existing Path E workflow AND ensure Package Router polling uses execution-scoped data

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|-------------|---------------|----------|------------|
| n8n environment setup | Execute Command disabled in v2.0 | CRITICAL | Set `NODES_EXCLUDE=[]` before any workflow development |
| n8n environment setup | Workflow execution timeout too short | CRITICAL | Set `EXECUTIONS_TIMEOUT=-1` for self-hosted |
| Path C MipMap launch | stdout maxBuffer overflow kills process | CRITICAL | Use fire-and-forget wrapper, not direct Execute Command |
| Path C MipMap launch | Orphan process on workflow cancel | HIGH | PID file + pre-flight orphan check + cleanup |
| Path C output harvester | Truncated GeoTIFF from interrupted copy | HIGH | Copy to .tmp, verify, atomic rename |
| Path C output harvester | File locked by MipMap immediately after exit | MODERATE | Wait 5s after process exit, retry open 3x with backoff |
| Package Router webhook | Lost webhook on n8n downtime | MODERATE | Persistent retry queue with JSONL fallback |
| Package Router routing | Concurrent GPU paths deadlock | HIGH | Sequential GPU scheduling or file-based GPU lock |
| Folder watcher extension | Duplicate events fire multiple webhooks | MODERATE | Separate Observer per directory, stability check |
| Folder watcher extension | Premature trigger on slow SD card copy | MODERATE | Increase debounce to 180s or use ingest_sorter as primary trigger |
| Multi-path orchestration | Static data shared across concurrent executions | HIGH | Use execution-scoped data in polling loops |
| Status tracking | Stuck intermediate status on failure | MODERATE | Stale job cleanup cron, `updated_at` timestamps |
| Windows paths | MAX_PATH 260 char limit in MipMap workspace | MODERATE | Enable LongPathsEnabled registry key, shorten UUIDs |

---

## Integration-Specific Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| n8n Execute Command + MipMap | Running MipMap directly via Execute Command | Wrapper script that redirects stdout to file, returns immediately or waits and posts callback webhook |
| n8n Execute Command + Python scripts | Not setting working directory | Always use absolute paths in command; n8n Execute Command runs from n8n's install directory, not project root |
| n8n Wait node + file polling | Using workflow static data for counter | Pass poll attempt as node data through the flow (execution-scoped) |
| n8n webhook + folder_watcher | Assuming webhook delivery is guaranteed | Add retry with persistent queue; idempotent webhook handlers (check if mission already being processed) |
| n8n sub-workflows | Passing large data between parent/child workflows | Pass mission_id only; let child workflow read data from Supabase, not from parent's JSON payload |
| subprocess.Popen + Windows | Assuming child process dies with parent | Use `CREATE_NEW_PROCESS_GROUP` flag + PID file + atexit cleanup |
| shutil.copy2 + large files | Assuming atomic copy | Copy to .tmp file, verify integrity, rename |
| watchdog + Windows | Trusting single event = single file operation | Always debounce; verify file stability before acting |
| MipMap + D:/ drive | Assuming D:/ has infinite space | Pre-flight disk space check: `shutil.disk_usage('D:/')`, alert if < 50GB free |
| Python 3.14 + Path E 3.12 | Package Router calling Path E scripts with wrong Python | Always use absolute Python path: `E:\Sentinel\.venv-path-e\Scripts\python.exe` for E scripts, system python for others |

---

## "Looks Done But Isn't" Checklist (v3.0)

- [ ] **n8n version compatible**: Verify Execute Command node is available (`n8n list:node-types | grep executeCommand`)
- [ ] **Execution timeout disabled**: Confirm `EXECUTIONS_TIMEOUT=-1` in n8n config
- [ ] **MipMap stdout redirected**: Verify wrapper script redirects stdout/stderr to log file, not captured by n8n
- [ ] **MipMap orphan check works**: Manually cancel n8n workflow mid-MipMap, confirm MipMap process is trackable and killable via PID file
- [ ] **GeoTIFF copy verified**: Copy 500MB+ test ortho from D:/ to E:/, interrupt mid-copy, verify .tmp cleanup and no corrupt file at destination
- [ ] **Webhook retry works**: Stop n8n, run ingest_sorter with --webhook, restart n8n, verify mission eventually processes
- [ ] **Concurrent paths tested**: Run Path C + Path V simultaneously, verify no GPU OOM in Path E when it starts
- [ ] **Polling counter scoped**: Run two missions through Package Router simultaneously, verify each polls independently
- [ ] **Windows long paths enabled**: Create a file at 300+ char path in D:/ workspace, verify Python can read it
- [ ] **Folder watcher debounce tested**: Copy files to Incoming/ in two batches with 90s gap, verify single webhook (not two)
- [ ] **Stale job cleanup**: Set a drone_job status to "processing", wait 24h (or fake the timestamp), verify cleanup marks it "failed_stale"
- [ ] **SD card copy + webhook flow**: Full end-to-end test from SD card insert to webhook receipt to Package Router routing

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| n8n v2.0 breaks Execute Command | LOW | Add env var, restart n8n. No data loss. |
| MipMap killed by maxBuffer | HIGH | Clean up D:/ workspace, re-launch MipMap from scratch. 2-6 hours wasted processing time. |
| Workflow timeout kills multi-hour run | MEDIUM | Fix timeout config, re-run workflow. MipMap may need re-launch. |
| Premature folder watcher trigger | LOW | Re-run ingest_sorter with --webhook to re-fire with complete inventory. |
| Orphan MipMap process | MEDIUM | Find via tasklist, kill, clean workspace, re-launch. Risk of partial D:/ workspace consuming disk. |
| Truncated GeoTIFF copied | MEDIUM | Delete corrupt file, re-copy from D:/ if workspace still exists. If D:/ cleaned up, re-run MipMap. |
| Lost webhook | LOW | Replay from retry queue or run ingest_sorter --webhook again. |
| GPU deadlock between paths | LOW | Kill the conflicting process, re-run the failed path. No data loss. |
| Stuck Supabase status | LOW | Manual SQL update: `UPDATE drone_jobs SET status='failed_stale' WHERE ...` |
| Static data corruption from concurrent polls | MEDIUM | Fix code to use execution-scoped data. Re-run affected missions. |

---

## Sources

- [n8n Execute Command node documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executecommand/)
- [n8n Execute Command common issues -- maxBuffer](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executecommand/common-issues/)
- [n8n workflow timeout configuration](https://docs.n8n.io/hosting/configuration/configuration-examples/execution-timeout/)
- [n8n v2.0 breaking changes -- Execute Command disabled](https://docs.n8n.io/2-0-breaking-changes/)
- [n8n blocking/allowing nodes](https://docs.n8n.io/hosting/securing/blocking-nodes/)
- [n8n concurrency control](https://docs.n8n.io/hosting/scaling/concurrency-control/)
- [n8n memory-related errors](https://docs.n8n.io/hosting/scaling/memory-errors/)
- [n8n community -- stdout maxBuffer length exceeded](https://community.n8n.io/t/error-stdout-maxbuffer-length-exceeded/16298)
- [n8n community -- long running workflow dying](https://community.n8n.io/t/long-running-10-20min-workflow-dying-why-how-to-debug-multi-loop-executions-that-dont-complete/8237)
- [n8n community -- Execute Command node removed in v2.0](https://community.n8n.io/t/execute-command-node-has-removed/233388)
- [n8n community -- re-enabling Execute Command in v2.0](https://community.n8n.io/t/unable-to-re-enable-execute-command-node-in-n8n-2-0-using-documented-environment-variables/238232)
- [n8n GitHub -- Unable to re-enable Execute Command in v2.0](https://github.com/n8n-io/n8n/issues/23439)
- [watchdog GitHub -- Large file raises multiple modified events](https://github.com/gorakhargosh/watchdog/issues/309)
- [watchdog GitHub -- Modified files trigger more than one event on Python 3](https://github.com/gorakhargosh/watchdog/issues/346)
- [watchdog GitHub -- Modified event triggered twice](https://github.com/gorakhargosh/watchdog/issues/93)
- [Python subprocess -- robustly stopping subprocesses](https://runebook.dev/en/docs/python/library/subprocess/subprocess.Popen.terminate)
- [Python shutil documentation -- copy2 limitations](https://docs.python.org/3/library/shutil.html)
- [n8n workflow settings -- per-workflow timeout](https://docs.n8n.io/workflows/settings/)

---

*Pitfalls research for: v3.0 Package Router, multi-path orchestration, MipMap automation, folder watcher, Windows subprocess management*
*Researched: 2026-03-05*
*Supersedes v2.0 pitfalls (2026-02-24) which covered Path E vegetation analysis pitfalls -- those remain valid and are not repeated here*
