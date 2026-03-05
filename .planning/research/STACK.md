# Stack Research — v3.0 Package Router & End-to-End Automation

**Domain:** n8n workflow orchestration, MipMap photogrammetry automation, event-driven pipeline triggers
**Researched:** 2026-03-05
**Confidence:** HIGH (n8n patterns verified against official docs; MipMap CLI verified against existing ingest.py)

---

## Context: What This Is NOT Re-Researching

The existing stack is validated and stays unchanged:

| Already Have | Status |
|--------------|--------|
| Python 3.14 (system) + 3.12 (.venv-path-e) | Validated v2.0 |
| 18 Python CLI scripts (all v1/v2 pipeline) | 402 tests passing |
| n8n self-hosted (Path E workflow, 35 nodes) | Deployed |
| watchdog-based folder_watcher.py + Windows service | Deployed |
| MipMap Desktop + ingest.py task.json generator | Working |
| Supabase (drone_jobs, processing_steps, video_assets, vegetation_detections) | Deployed |
| FFmpeg, Google Drive API, Pillow, requests | Deployed |
| Path E dependencies (DeepForest, PyTorch, rasterio, etc.) | In .venv-path-e |

Everything in this document is NEW for v3.0: n8n workflow architecture, MipMap output harvesting, and webhook contracts.

---

## Recommended Stack Additions

### n8n Workflow Nodes (No Install Required)

These are built-in n8n nodes. No npm packages or community nodes needed.

| Node Type | n8n ID | Purpose | Where Used |
|-----------|--------|---------|------------|
| Webhook | `n8n-nodes-base.webhook` | Entry point for Package Router (receives ingest_sorter POST) | Package Router trigger |
| Switch | `n8n-nodes-base.switch` | Route by `package_type` to Path A/B/C/D/V branches | Package Router core |
| IF | `n8n-nodes-base.if` | Binary conditions (has_video, has_ppk, vegetation_enabled) | Path branching |
| Execute Sub-workflow | `n8n-nodes-base.executeworkflow` | Call Path A/B/C/D/V/E as separate workflows | Router to path dispatch |
| Execute Sub-workflow Trigger | `n8n-nodes-base.executeworkflowtrigger` | Entry point in each sub-workflow | Path A/B/C/D/V start |
| Execute Command | `n8n-nodes-base.executeCommand` | Run Python scripts and MipMap engine | All paths |
| HTTP Request | `n8n-nodes-base.httpRequest` | Supabase REST API calls | Status updates |
| Code | `n8n-nodes-base.code` | JSON parsing, path construction, result transformation | Between script steps |
| Wait | `n8n-nodes-base.wait` | Poll loops (ortho wait) and delay for MipMap processing | Path C ortho polling |
| Respond to Webhook | `n8n-nodes-base.respondToWebhook` | Immediate 200 response to ingest webhook | Router entry |
| Set | `n8n-nodes-base.set` | Pass mission data between nodes | Data shaping |

**Why Sub-workflows Instead of One Giant Workflow:**
- Path E already has 35 nodes. Adding A/B/C/D/V inline would create an unmanageable 100+ node monolith.
- Sub-workflows can be tested independently (fire their trigger webhook directly).
- n8n's Execute Sub-workflow node supports "Wait for Sub-Workflow Completion" -- the router can fire Path C, wait for it, then conditionally fire Path E.
- Bug in one path doesn't break the others.

### n8n Switch Node Configuration (Package Router Core)

The Switch node is the heart of the Package Router. Use **Rules Mode** with `package_type` as the routing field.

| Output | Condition | Routes To |
|--------|-----------|-----------|
| Output 0 | `package_type` equals `re_standard` | Path A (photos) + Path V (video) |
| Output 1 | `package_type` equals `site_survey` | Path C (mapping) + Path A (photos) |
| Output 2 | `package_type` equals `environmental_survey` | Path C (mapping) + Path A (photos) |
| Output 3 | `package_type` equals `construction_hybrid` | Path B (construction) + Path C (mapping) |
| Fallback | No match | Log warning + manual routing |

**Critical:** The Switch node supports up to 4 named outputs by default. With 4 package types + fallback, this fits within the built-in limit. No community Dynamic Switch node needed.

**After the Switch, use parallel Execute Sub-workflow calls** -- e.g., `re_standard` fires both Path A and Path V sub-workflows. n8n handles this by connecting the Switch output to multiple Execute Sub-workflow nodes.

### New Python Script: mipmap_harvester.py

One new Python script is needed for v3.0. Runs on system Python 3.14.

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python 3.14 | System | mipmap_harvester.py -- copies MipMap output GeoTIFF to mission mapping/ folder | No GPU deps; standard file operations only |
| shutil (stdlib) | Built-in | File copy with metadata preservation | Already used in ingest_sorter.py |
| pathlib (stdlib) | Built-in | Cross-platform path handling | Already used across pipeline |
| json (stdlib) | Built-in | Parse MipMap info.json for status checking | Already used in ingest.py |

**No new pip dependencies for mipmap_harvester.py.** It uses only stdlib + existing pipeline_utils.py imports (setup_logging, get_supabase_client, validate_webhook_url).

### MipMap CLI Automation Pattern

Verified from existing `ingest.py` (line 517-529):

```python
# MipMap engine is invoked via subprocess, not Python API
MIPMAP_ENGINE = r"C:\Program Files\MipMap\MipMapDesktop\resources\resources\catch3d\reconstruct_full_engine.exe"

cmd = [
    MIPMAP_ENGINE,
    f'--task_json={task_json_path}',
    "--reconstruct_type=0",
]
proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
ret = proc.wait()  # Blocks until MipMap finishes
```

**MipMap output structure** (from ingest.py workspace creation):
```
D:/{user_id}/{project_name}/{task_name}/
    task.json           <-- Input (generated by ingest.py)
    info.json           <-- Status tracking
    result/
        orthomosaic.tif <-- GeoTIFF output (what we need to harvest)
        3d_tiles/       <-- 3D tileset
        pointcloud.las  <-- LAS point cloud
        model.osgb      <-- 3D model
```

The harvester needs to:
1. Monitor `info.json` for `"status": "complete"` (or watch for `result/orthomosaic.tif` to appear)
2. Copy `result/orthomosaic.tif` to `E:\Sentinel\Incoming\{mission_folder}\mapping\orthomosaic.tif`
3. Update Supabase `processing_steps` with `step_name=mapping, status=complete`

### Folder Watcher Enhancement

The existing `folder_watcher.py` fires to `http://localhost:5678/webhook/folder-watcher`. For v3.0, it needs a second webhook target or the existing webhook URL needs to point to the Package Router instead.

**Recommendation:** Change `folder_watcher.py`'s default webhook URL to point to the Package Router webhook, OR add a `--webhook-url` override (already exists as CLI arg). The Package Router replaces direct Path E triggering -- it routes everything.

**No code change needed** in folder_watcher.py itself. The `--webhook-url` arg already supports pointing to any n8n webhook endpoint. The folder_watcher fires an inventory payload; the Package Router receives it and routes.

However, the ingest_sorter webhook payload is richer (includes `mission_id`, `package_type`). The folder_watcher payload only has file counts. **The Package Router should receive its trigger from ingest_sorter.py, not folder_watcher.py.** The folder_watcher remains useful for detecting new SD card dumps before ingest_sorter runs.

---

## Webhook Contract Definitions

### Webhook 1: Ingest Complete -> Package Router

**URL:** `http://localhost:5678/webhook/package-router`
**Method:** POST
**Source:** `ingest_sorter.py --webhook`
**Payload (existing from ingest_sorter.py line 301-311):**

```json
{
    "mission_id": "uuid-from-supabase",
    "mission_number": 47,
    "package_type": "re_standard",
    "photo_count": 150,
    "video_count": 3,
    "has_ppk_data": true,
    "source_platform": "m4e",
    "ingested_at": "2026-03-05T14:30:00Z"
}
```

**Change required in ingest_sorter.py:** Update `N8N_WEBHOOK_URL` default from `/webhook/ingest` to `/webhook/package-router`. This is a one-line change.

### Webhook 2: Path C Complete -> Path E Trigger

**URL:** `http://localhost:5678/webhook/sentinel-vegetation-trigger` (already exists)
**Method:** POST
**Source:** Package Router (after Path C sub-workflow completes)
**Payload:**

```json
{
    "mission_id": "uuid-from-supabase"
}
```

This webhook already exists in `path_e_workflow.json`. The Package Router's Path C handler fires it after MipMap output is harvested and `mapping/orthomosaic.tif` is confirmed.

### Webhook 3: Folder Watcher -> n8n (unchanged)

**URL:** `http://localhost:5678/webhook/folder-watcher`
**Method:** POST
**Source:** `folder_watcher.py`
**Payload (existing, unchanged):**

```json
{
    "folder_path": "E:\\Sentinel\\Incoming\\SAI_M0047_RE_Standard_20260218",
    "folder_name": "SAI_M0047_RE_Standard_20260218",
    "mission_number": 47,
    "photo_count": 150,
    "video_count": 3,
    "has_ppk_data": true,
    "total_size_bytes": 5368709120,
    "detected_at": "2026-03-05T14:25:00Z"
}
```

The folder_watcher webhook remains separate. It notifies n8n of new folders; the operator then runs ingest_sorter which fires the Package Router webhook. These are sequential, not redundant.

### Webhook 4: Path E Review Gate (unchanged)

**URL:** `http://localhost:5678/webhook/sentinel-vegetation-resume`
Already documented in path_e_workflow.json. No changes needed.

---

## n8n Environment Variables

### Existing (already configured for Path E)

| Variable | Value | Used By |
|----------|-------|---------|
| `SUPABASE_URL` | `https://qjpujskwqaehxnqypxzu.supabase.co` | All Supabase HTTP nodes |
| `SUPABASE_SERVICE_KEY` | Service role key | All Supabase HTTP nodes |

### New for v3.0

| Variable | Value | Used By |
|----------|-------|---------|
| `N8N_BASE_URL` | `http://localhost:5678` | Inter-workflow webhook calls (Router -> Path E) |
| `MIPMAP_ENGINE_PATH` | `C:\Program Files\MipMap\MipMapDesktop\resources\resources\catch3d\reconstruct_full_engine.exe` | Path C Execute Command nodes |
| `MIPMAP_WORKSPACE` | `D:/` | Path C MipMap workspace root |
| `SENTINEL_INCOMING` | `E:\Sentinel\Incoming` | Path A/V/C script working directory |
| `SENTINEL_SCRIPTS` | `E:\Sentinel\Scripts` | Execute Command node script paths |
| `VENV_PATH_E_PYTHON` | `E:\Sentinel\.venv-path-e\Scripts\python.exe` | Path E script execution |

---

## n8n Workflow Architecture

### Package Router Workflow (NEW)

```
[Webhook: /package-router]
    |
[HTTP: Fetch drone_job from Supabase by mission_id]
    |
[Code: Enrich with template_defaults from package_router_patch.json]
    |
[Switch: package_type]
    |
    +-- re_standard -----> [Execute Sub-workflow: Path A] + [Execute Sub-workflow: Path V]
    |
    +-- site_survey -----> [Execute Sub-workflow: Path C] --> [IF: vegetation_enabled?] --> [HTTP: Fire Path E webhook]
    |                                                                                          + [Execute Sub-workflow: Path A]
    +-- env_survey ------> [Execute Sub-workflow: Path C] --> [IF: vegetation_enabled?] --> [HTTP: Fire Path E webhook]
    |                                                                                          + [Execute Sub-workflow: Path A]
    +-- construction ----> [Execute Sub-workflow: Path B] + [Execute Sub-workflow: Path C]
    |
    +-- fallback --------> [Set: status=manual_routing] --> [Stop]
```

### Path C Sub-workflow (NEW)

```
[Execute Sub-workflow Trigger]
    |
[Code: Build task.json path from mission folder]
    |
[Execute Command: python ingest.py {source} --run]
    |  (blocks until MipMap completes)
    |
[Execute Command: python mipmap_harvester.py --mission-id {id} --workspace D:/]
    |
[HTTP: PATCH processing_steps SET status=complete WHERE step_name=mapping]
    |
[Code: Return {ortho_path, mission_id}]
```

### Path A Sub-workflow (NEW)

```
[Execute Sub-workflow Trigger]
    |
[Execute Command: python video_color_grade.py {mission_dir} --platform {platform}]
    |
[Execute Command: python delivery_packaging.py {mission_dir} --address {addr} --photos-only]
    |
[HTTP: PATCH processing_steps SET status=complete WHERE step_name=photo_delivery]
```

### Path V Sub-workflow (NEW)

```
[Execute Sub-workflow Trigger]
    |
[Execute Command: python video_metadata.py {mission_dir}]
    |
[Execute Command: python video_qa.py {mission_dir}]
    |
[Execute Command: python video_proxy_gen.py {mission_dir}]
    |
[Execute Command: python video_color_grade.py {mission_dir}]
    |
[Wait: Manual DaVinci Resolve step (V5) -- webhook resume or skip]
    |
[Execute Command: python video_format_export.py {mission_dir}]
    |
[Execute Command: python delivery_packaging.py {mission_dir} --video-addendum]
    |
[HTTP: PATCH processing_steps SET status=complete WHERE step_name=video_delivery]
```

### Path E Workflow (EXISTING -- no changes)

Already deployed with 35 nodes. Triggered by POST to `/sentinel-vegetation-trigger`.

---

## n8n Timeout Configuration

MipMap photogrammetry processing takes 15-90 minutes depending on image count and quality level. The n8n default execution timeout must be increased for Path C.

| Setting | Value | Why |
|---------|-------|-----|
| `EXECUTIONS_TIMEOUT` | `7200` (2 hours) | MipMap can run 90+ minutes for large datasets |
| `EXECUTIONS_TIMEOUT_MAX` | `14400` (4 hours) | Safety ceiling for stuck processes |
| Per-workflow timeout | 2 hours on Path C | Only Path C needs extended timeout |

Set in n8n Docker compose or environment:
```
EXECUTIONS_TIMEOUT=7200
EXECUTIONS_TIMEOUT_MAX=14400
```

**Alternative:** Use `Wait for Sub-Workflow Completion: false` on Path C, then poll for completion via Supabase `processing_steps.status`. This avoids the timeout issue entirely but adds polling complexity.

**Recommendation:** Use blocking `Wait for Sub-Workflow Completion: true` with extended timeout. Simpler, and MipMap's `reconstruct_full_engine.exe` exits cleanly with exit code on completion (verified in ingest.py).

---

## Supabase Schema Additions

### New Columns on `drone_jobs`

| Column | Type | Default | Purpose |
|--------|------|---------|---------|
| `vegetation_analysis` | BOOLEAN | false | Already in package_router_patch.json |
| `vegetation_status` | TEXT | null | Already used by Path E workflow |

These are already documented in `package_router_patch.json` migration checklist. Verify they exist before v3.0 deployment.

### New `processing_steps` Rows per Mission

Each path creates its own processing_steps rows:

| step_name | Created By | Status Flow |
|-----------|------------|-------------|
| `photo_color_grade` | Path A | waiting -> running -> complete/failed |
| `photo_delivery` | Path A | waiting -> running -> complete/failed |
| `video_metadata` | Path V | waiting -> running -> complete/failed |
| `video_qa` | Path V | waiting -> running -> complete/failed |
| `video_proxy` | Path V | waiting -> running -> complete/failed |
| `video_color_grade` | Path V | waiting -> running -> complete/failed |
| `video_export` | Path V | waiting -> running -> complete/failed |
| `video_delivery` | Path V | waiting -> running -> complete/failed |
| `mapping` | Path C | waiting -> running -> complete/failed |
| `mapping_harvest` | Path C | waiting -> running -> complete/failed |
| `veg_canopy_detection` | Path E | (already exists) |
| `veg_species_classification` | Path E | (already exists) |
| `veg_health_assessment` | Path E | (already exists) |
| `veg_report_generation` | Path E | (already exists) |

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Airflow / Prefect / Dagster | n8n is already deployed and working. Adding a second orchestrator creates operational complexity for a single-operator business. | n8n sub-workflows handle the routing. |
| WebODM | MipMap Desktop is licensed and produces superior orthomosaics with 3D tiles, Gaussian splats. WebODM is a downgrade. | Continue using MipMap via CLI. |
| n8n community nodes | The built-in Switch, IF, Execute Sub-workflow, and Execute Command nodes cover all routing needs. Community nodes add update/compatibility risk. | Built-in nodes only. |
| Redis / RabbitMQ message queue | Overkill for single-rig, single-operator pipeline. n8n webhooks + Supabase status columns provide sufficient event coordination. | Webhook + Supabase polling. |
| Docker for Python scripts | Scripts run directly on the processing rig with access to local drives (E:, D:, F:). Docker would require volume mounts and complicate MipMap GPU access. | Direct execution via Execute Command node. |
| New Python web framework (Flask/FastAPI) | The webhook endpoints are handled by n8n. Python scripts remain CLI-only. No need for a Python HTTP server. | n8n webhooks. |
| Celery task queue | Single-rig, single-operator. No need for distributed task management. | n8n orchestration handles sequencing. |

---

## Alternatives Considered

| Recommended | Alternative | Why Alternative Was Rejected |
|-------------|-------------|-------------------------------|
| n8n Switch node (Rules Mode) | n8n IF chains | Switch handles 4+ branches cleanly; IF chains create visual spaghetti in n8n canvas |
| Execute Sub-workflow per path | Single monolithic workflow | Path E already has 35 nodes; adding 4 more paths inline creates unmaintainable 100+ node workflow |
| mipmap_harvester.py (new script) | n8n Code node with file ops | n8n's Code node runs in Node.js sandbox; Windows file copy with error handling and Supabase update is cleaner in Python with existing pipeline_utils |
| Blocking subprocess.wait() for MipMap | Fire-and-forget + polling | MipMap engine exits with code 0 on success; blocking is simpler and ingest.py already uses this pattern |
| ingest_sorter.py fires Package Router | folder_watcher.py fires Package Router | folder_watcher payload lacks mission_id and package_type; ingest_sorter has the full context needed for routing |
| Extended n8n timeout (2 hours) | Non-blocking sub-workflow + poll | Polling adds complexity; MipMap finishes deterministically; timeout is the simpler approach |

---

## Installation Summary

### n8n Configuration Changes

```bash
# Add to n8n Docker environment or .env file
N8N_BASE_URL=http://localhost:5678
MIPMAP_ENGINE_PATH=C:\Program Files\MipMap\MipMapDesktop\resources\resources\catch3d\reconstruct_full_engine.exe
MIPMAP_WORKSPACE=D:/
SENTINEL_INCOMING=E:\Sentinel\Incoming
SENTINEL_SCRIPTS=E:\Sentinel\Scripts
VENV_PATH_E_PYTHON=E:\Sentinel\.venv-path-e\Scripts\python.exe
EXECUTIONS_TIMEOUT=7200
EXECUTIONS_TIMEOUT_MAX=14400
```

### Python Changes

```bash
# No new pip dependencies for v3.0
# mipmap_harvester.py uses only stdlib + existing pipeline_utils.py

# One-line change in ingest_sorter.py:
# N8N_WEBHOOK_URL default: "http://localhost:5678/webhook/ingest" -> "http://localhost:5678/webhook/package-router"
```

### n8n Workflow Files to Create

| File | Nodes (estimated) | Purpose |
|------|-------------------|---------|
| `n8n/package_router_workflow.json` | 15-20 | Main router: webhook -> switch -> sub-workflow dispatch |
| `n8n/path_a_workflow.json` | 8-10 | Photo processing: color grade -> delivery packaging |
| `n8n/path_v_workflow.json` | 15-18 | Video pipeline: metadata -> QA -> proxy -> grade -> export -> delivery |
| `n8n/path_c_workflow.json` | 12-15 | Mapping: ingest.py -> MipMap -> harvester -> ortho confirmation |
| `n8n/path_b_workflow.json` | 5-8 | Construction/ADIAT: placeholder routing |
| `n8n/path_e_workflow.json` | 35 | (already exists, no changes) |

### Supabase Migration

```sql
-- Run ONLY if columns don't already exist (check package_router_patch.json migration_checklist)
ALTER TABLE drone_jobs ADD COLUMN IF NOT EXISTS vegetation_analysis BOOLEAN DEFAULT false;
ALTER TABLE drone_jobs ADD COLUMN IF NOT EXISTS vegetation_status TEXT;
```

---

## Sources

- [n8n Switch Node Documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.switch/) -- Rules Mode, Expression Mode, fallback handling (HIGH confidence)
- [n8n Sub-workflows Documentation](https://docs.n8n.io/flow-logic/subworkflows/) -- Execute Workflow node, data passing (HIGH confidence)
- [n8n Execute Sub-workflow Node](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executeworkflow/) -- Wait for completion option (HIGH confidence)
- [n8n Execute Sub-workflow Trigger](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executeworkflowtrigger/) -- Sub-workflow entry point (HIGH confidence)
- [n8n Execution Timeout Configuration](https://docs.n8n.io/hosting/configuration/configuration-examples/execution-timeout/) -- EXECUTIONS_TIMEOUT env var (HIGH confidence)
- [n8n Execute Command Common Issues](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executecommand/common-issues/) -- Windows shell, stdout buffer (HIGH confidence)
- [n8n Splitting with Conditionals](https://docs.n8n.io/flow-logic/splitting/) -- Switch vs IF branching patterns (HIGH confidence)
- [MipMap SDK Documentation](https://na.mipmap3d.com/document/docs/MipMapDesktop/softwareoverview/) -- Software overview (MEDIUM confidence -- CLI specifics verified from ingest.py source code)
- Existing `ingest.py` (lines 517-529) -- MipMap CLI invocation pattern (HIGH confidence -- project source code)
- Existing `path_e_workflow.json` -- n8n node patterns, Supabase API conventions (HIGH confidence -- project source)
- Existing `package_router_patch.json` -- Template defaults, routing conditions (HIGH confidence -- project source)
- Existing `folder_watcher.py` -- Webhook payload contract (HIGH confidence -- project source)
- Existing `ingest_sorter.py` -- Webhook payload contract, CLI args (HIGH confidence -- project source)

---

*Stack research for: v3.0 Package Router & End-to-End Automation -- drone-pipeline*
*Researched: 2026-03-05*
*Scope: n8n workflow patterns, MipMap automation, webhook contracts, new script (mipmap_harvester.py). No new pip dependencies.*
